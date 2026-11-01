"""Demo history pagination/scan snapshots through its handler, without AWS."""
import base64
import copy
import io
import json
import unittest
import uuid
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import demo


class DemoHistoryPagination(unittest.TestCase):
    def setUp(self):
        self.saved = copy.deepcopy((demo.PROFILE, demo.CURRENT, demo.HISTORY, demo.FEEDBACK, demo.READY_AT, demo.FINDING_OBSERVATIONS))
        self.addCleanup(self.restore)
        demo.FINDING_OBSERVATIONS = {}
        self.now = 1793361600
        clock = patch.object(demo.time, "time", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        demo.PROFILE.update(connection_version="history-v1", regions=["ap-southeast-1", "ap-southeast-2", "us-east-1"])
        demo.PROFILE["service_groups"] = list(demo.SERVICE_GROUPS)
        demo.CURRENT, demo.HISTORY, demo.FEEDBACK, demo.READY_AT = [], [], {}, 0
        for number in range(15):
            scan_id = str(uuid.UUID(int=number + 1, version=4))
            for region in demo.PROFILE["regions"]:
                row = demo.complete(scan_id, self.now - number * 60, region)
                row["completed_at"] = row["started_at"] + 10
                demo.HISTORY.append(row)

    def restore(self):
        demo.PROFILE, demo.CURRENT, demo.HISTORY, demo.FEEDBACK, demo.READY_AT, demo.FINDING_OBSERVATIONS = self.saved

    def request(self, method="GET", path="/history", body=None, *, through_get=False):
        payload = json.dumps(body).encode() if body is not None else b""
        handler = object.__new__(demo.Handler)
        handler.headers = {"Authorization": "Bearer demo-local-only", "Content-Length": str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        handler.reply = MagicMock()
        if through_get:
            handler.path = "/api" + path
            handler.do_GET()
        else:
            handler.handle_api(method, path)
        handler.reply.assert_called_once()
        code, value = handler.reply.call_args.args
        return code, copy.deepcopy(value)

    def page(self, **query):
        return self.request(path="/history" + ("?" + urlencode(query) if query else ""))

    @staticmethod
    def identity(row):
        return row["scan_id"], row["region"]

    def test_three_pages_cover_all_region_results_without_duplicates(self):
        original = copy.deepcopy(demo.HISTORY)
        first = self.page()[1]
        second = self.page(next_token=first["next_token"])[1]
        third = self.page(next_token=second["next_token"])[1]
        self.assertEqual([len(page["results"]) for page in [first, second, third]], [20, 20, 5])
        self.assertIsNone(third["next_token"])
        actual = [self.identity(row) for page in [first, second, third] for row in page["results"]]
        expected = [self.identity(row) for row in sorted(original, key=demo.history_key, reverse=True)]
        self.assertEqual(actual, expected)
        self.assertEqual(len(set(actual)), 45)
        self.assertEqual(demo.HISTORY, original)
        self.assertTrue(all("candidates" not in row for page in [first, second, third] for row in page["results"]))

    def test_created_at_controls_order_like_backend_history_key(self):
        older = demo.HISTORY[-1]
        older["created_at"] = self.now + 100
        self.assertEqual(self.page(limit=1)[1]["results"][0]["scan_id"], older["scan_id"])
        self.assertEqual(self.page(limit=1)[1]["results"][0]["region"], older["region"])

    def test_limits_get_query_string_and_first_page_reload(self):
        for limit, expected in [(1, 1), (100, 45)]:
            self.assertEqual(len(self.page(limit=limit)[1]["results"]), expected)
        code, first = self.request(path="/history?limit=1", through_get=True)
        self.assertEqual(code, 200)
        code, second = self.request(path="/history?" + urlencode({"limit": 1, "next_token": first["next_token"]}), through_get=True)
        self.assertEqual(code, 200)
        self.assertNotEqual(self.identity(first["results"][0]), self.identity(second["results"][0]))
        self.assertEqual(self.page(limit=1)[1], first)

    def test_expired_version_and_region_rows_are_filtered_without_ttl_cleanup(self):
        ordered = sorted(demo.HISTORY, key=demo.history_key, reverse=True)
        for row in ordered[:25]:
            row["expires"] = self.now
        demo.HISTORY.append({**ordered[25], "connection_version": "old"})
        demo.HISTORY.append({**ordered[25], "region": "eu-west-1"})
        demo.HISTORY.append({key: value for key, value in ordered[25].items() if key != "expires"})
        response = self.page()[1]
        self.assertEqual([self.identity(row) for row in response["results"]], [self.identity(row) for row in ordered[25:]])
        self.assertIsNone(response["next_token"])
        self.assertEqual(len(demo.HISTORY), 48)

    def test_invalid_limits_and_tokens_do_not_mutate_history(self):
        before = copy.deepcopy(demo.HISTORY)
        paths = ["/history?limit=" + value for value in ["", "0", "101", "-1", "1.5", "true", "none"]]
        paths += ["/history?limit=1&limit=2", "/history?next_token=", "/history?next_token=bad", "/history?next_token=%21%21%21"]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.request(path=path)[0], 400)
                self.assertEqual(demo.HISTORY, before)

    def test_cursor_is_bound_to_route_connection_and_history_key(self):
        cursor = self.page(limit=1)[1]["next_token"]
        value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        invalid = [[], {**value, "route": "/feedback"}, {**value, "connection_version": "old"},
                   {**value, "extra": True}, {**value, "key": None},
                   {**value, "key": "HISTORY#123#eu-west-1#scan"},
                   {**value, "key": "HISTORY#no#ap-southeast-1#scan"},
                   {**value, "key": "HISTORY#123#ap-southeast-1#"}]
        for item in invalid:
            with self.subTest(item=item):
                token = base64.urlsafe_b64encode(json.dumps(item).encode()).decode().rstrip("=")
                self.assertEqual(self.page(next_token=token)[0], 400)
        self.assertEqual(self.request(path="/feedback?" + urlencode({"next_token": cursor}))[0], 400)

    def test_cursor_survives_deletion_of_preceding_rows(self):
        first = self.page()[1]
        preceding = {self.identity(row) for row in first["results"]}
        demo.HISTORY[:] = [row for row in demo.HISTORY if self.identity(row) not in preceding]
        second = self.page(next_token=first["next_token"])[1]
        self.assertEqual(len(second["results"]), 20)
        self.assertTrue(preceding.isdisjoint(map(self.identity, second["results"])))

    def test_reconnect_rejects_old_cursor_and_hides_old_scan(self):
        page = self.page()[1]
        scan_id = page["results"][0]["scan_id"]
        code, _ = self.request("PUT", "/connection", {
            "role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-demo",
            "regions": ["ap-southeast-1"], "service_groups": ["compute"],
        })
        self.assertEqual(code, 200)
        self.assertEqual(self.page(next_token=page["next_token"])[0], 400)
        self.assertEqual(self.page()[1], {"results": [], "next_token": None})
        self.assertEqual(self.request(path="/scans/" + scan_id)[0], 404)

    def test_scan_detail_returns_each_region_once_and_retained_regions_beyond_current(self):
        scan_id = demo.HISTORY[0]["scan_id"]
        demo.CURRENT = copy.deepcopy(demo.HISTORY[:2])
        code, response = self.request(path="/scans/" + scan_id)
        self.assertEqual(code, 200)
        self.assertEqual(response["scan_id"], scan_id)
        self.assertEqual({row["region"] for row in response["results"]}, set(demo.PROFILE["regions"]))
        self.assertEqual(len(response["results"]), 3)
        self.assertTrue(all("candidates" not in row for row in response["results"]))
        demo.CURRENT = []
        for row in demo.HISTORY[:3]:
            row["expires"] = self.now
        self.assertEqual(self.request(path="/scans/" + scan_id)[0], 404)

    def test_feedback_changes_neither_history_nor_scan_snapshots(self):
        demo.CURRENT = [copy.deepcopy(demo.HISTORY[0])]
        row = demo.CURRENT[0]
        ident = row["candidates"][0]["finding_id"]
        first_page = self.page()[1]
        detail = self.request(path="/scans/" + row["scan_id"])[1]
        before = copy.deepcopy(demo.HISTORY)
        code, _ = self.request("PUT", "/feedback", {"region": row["region"], "finding_id": ident, "kept": True})
        self.assertEqual(code, 200)
        self.assertNotIn(ident, {item["finding_id"] for item in self.request(path="/findings")[1]["results"][0]["findings"]})
        self.assertEqual(self.page()[1], first_page)
        self.assertEqual(self.request(path="/scans/" + row["scan_id"])[1], detail)
        self.assertEqual(demo.HISTORY, before)

    def test_terminal_history_wins_while_current_adds_other_active_regions(self):
        scan_id = demo.HISTORY[0]["scan_id"]
        saved = copy.deepcopy(demo.HISTORY[0])
        other_region = demo.PROFILE["regions"][1]
        demo.HISTORY = [saved]
        demo.CURRENT = [
            {**copy.deepcopy(saved), "status": "RUNNING", "findings": []},
            {"scan_id": scan_id, "region": other_region, "connection_version": "history-v1",
             "trigger": "manual", "status": "RUNNING", "started_at": self.now},
        ]
        code, response = self.request(path="/scans/" + scan_id)
        self.assertEqual(code, 200)
        regions = {row["region"]: row for row in response["results"]}
        self.assertEqual(len(response["results"]), 2)
        self.assertEqual(regions[saved["region"]], demo.public_result(saved))
        self.assertEqual(regions[other_region]["status"], "RUNNING")
        self.assertNotIn("findings", regions[other_region])

    def test_completed_scan_retains_more_than_twenty_rows_and_prunes_expired_history(self):
        expired = copy.deepcopy(demo.HISTORY[0])
        expired["scan_id"] = str(uuid.uuid4())
        expired["expires"] = self.now
        demo.HISTORY.append(expired)
        code, accepted = self.request("POST", "/scans")
        self.assertEqual(code, 202)
        self.assertEqual(uuid.UUID(accepted["scan_id"]).version, 4)
        self.assertTrue(all(row["trigger"] == "manual" for row in demo.CURRENT))
        demo.READY_AT = self.now
        demo.tick()
        self.assertEqual(len(demo.HISTORY), 48)
        self.assertNotIn(expired["scan_id"], {row["scan_id"] for row in demo.HISTORY})
        self.assertEqual(len({self.identity(row) for row in self.page(limit=100)[1]["results"]}), 48)
        self.assertTrue(all(row["trigger"] == "manual" for row in demo.CURRENT))


if __name__ == "__main__":
    unittest.main()
