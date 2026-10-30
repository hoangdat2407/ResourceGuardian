"""Local demo feedback pagination and management, without sockets or AWS calls."""
import base64
import copy
import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import demo


class DemoFeedbackPagination(unittest.TestCase):
    def setUp(self):
        self.saved = copy.deepcopy((demo.PROFILE, demo.CURRENT, demo.HISTORY, demo.FEEDBACK, demo.READY_AT))
        self.addCleanup(self.restore)
        self.now = 1793361600
        clock = patch.object(demo.time, "time", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        demo.READY_AT = 0
        demo.PROFILE.update(connection_version="page-v1", regions=["ap-southeast-1", "ap-southeast-2"])
        demo.FEEDBACK = {}
        for number in range(45):
            ident = format(number + 1, "064x")
            demo.FEEDBACK[ident] = {
                "finding_id": ident, "region": demo.PROFILE["regions"][number // 25],
                "connection_version": "page-v1", "kept": True, "acknowledged": number % 2 == 0,
            }
        demo.CURRENT, demo.HISTORY = [], []

    def restore(self):
        demo.PROFILE, demo.CURRENT, demo.HISTORY, demo.FEEDBACK, demo.READY_AT = self.saved

    def request(self, method="GET", path="/feedback", body=None, *, through_get=False):
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
        code, result = handler.reply.call_args.args
        return code, copy.deepcopy(result)

    def page(self, **query):
        return self.request(path="/feedback" + ("?" + urlencode(query) if query else ""))

    def identity(self, record):
        return record["region"], record["finding_id"]

    def test_default_pages_cover_more_than_twenty_records_in_backend_sort_order(self):
        before = copy.deepcopy(demo.FEEDBACK)
        code, first = self.page()
        self.assertEqual(code, 200)
        self.assertEqual(len(first["results"]), 20)
        self.assertIsInstance(first["next_token"], str)
        code, second = self.page(next_token=first["next_token"])
        self.assertEqual(code, 200)
        self.assertEqual(len(second["results"]), 20)
        code, third = self.page(next_token=second["next_token"])
        self.assertEqual(code, 200)
        self.assertEqual(len(third["results"]), 5)
        self.assertIsNone(third["next_token"])
        actual = [self.identity(row) for page in (first, second, third) for row in page["results"]]
        self.assertEqual(actual, sorted((self.identity(row) for row in before.values()), reverse=True))
        self.assertEqual(len(set(actual)), 45)
        self.assertEqual(demo.FEEDBACK, before)

    def test_get_handler_preserves_limit_and_cursor_query_string(self):
        code, first = self.request(path="/feedback?limit=1", through_get=True)
        self.assertEqual(code, 200)
        self.assertEqual(len(first["results"]), 1)
        code, second = self.request(path="/feedback?" + urlencode({"limit": 1, "next_token": first["next_token"]}), through_get=True)
        self.assertEqual(code, 200)
        self.assertEqual(len(second["results"]), 1)
        self.assertNotEqual(self.identity(first["results"][0]), self.identity(second["results"][0]))

    def test_one_and_hundred_limits_and_first_page_reload(self):
        for limit, count in ((1, 1), (100, 45)):
            with self.subTest(limit=limit):
                code, result = self.page(limit=limit)
                self.assertEqual(code, 200)
                self.assertEqual(len(result["results"]), count)
        first = self.page()[1]
        self.page(next_token=first["next_token"])
        self.assertEqual(self.page()[1], first)

    def test_expired_and_foreign_rows_are_filtered_and_page_is_filled(self):
        ordered = sorted(demo.FEEDBACK.values(), key=self.identity, reverse=True)
        for record in ordered[:25]:
            record["expires"] = self.now
        demo.FEEDBACK["foreign-version"] = {"finding_id": "f" * 64, "region": "ap-southeast-1", "connection_version": "old", "kept": True}
        demo.FEEDBACK["foreign-region"] = {"finding_id": "e" * 64, "region": "us-east-1", "connection_version": "page-v1", "kept": True}
        code, result = self.page()
        self.assertEqual(code, 200)
        self.assertEqual([self.identity(row) for row in result["results"]], [self.identity(row) for row in ordered[25:]])
        self.assertIsNone(result["next_token"])
        self.assertEqual(len(demo.FEEDBACK), 47, "Expiry must not depend on physical cleanup")

    def test_metadata_free_and_acknowledged_only_records_are_returned_for_client_filtering(self):
        for record in demo.FEEDBACK.values():
            record["kept"] = False
            record["acknowledged"] = True
        code, result = self.page(limit=1)
        self.assertEqual(code, 200)
        self.assertEqual(len(result["results"]), 1)
        self.assertNotIn("resource_id", result["results"][0])
        self.assertFalse(result["results"][0]["kept"])
        self.assertTrue(result["next_token"], "A UI-filtered empty page still needs its cursor")

    def test_invalid_limit_and_token_are_rejected_without_state_changes(self):
        paths = ["/feedback?limit=" + value for value in ("", "0", "101", "-1", "1.5", "true", "no")]
        paths += ["/feedback?limit=1&limit=2", "/feedback?next_token=", "/feedback?next_token=bad", "/feedback?next_token=%21%21%21"]
        before = copy.deepcopy(demo.FEEDBACK)
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.request(path=path)[0], 400)
                self.assertEqual(demo.FEEDBACK, before)

    def test_cursor_is_bound_to_route_and_connection_and_rejects_malformed_keys(self):
        token = self.page(limit=1)[1]["next_token"]
        original = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        invalid = [[], {**original, "route": "/history"}, {**original, "connection_version": "old"},
                   {**original, "region": "us-east-1"}, {**original, "finding_id": "bad"},
                   {**original, "extra": "invalid"}]
        for value in invalid:
            with self.subTest(value=value):
                cursor = base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
                self.assertEqual(self.page(next_token=cursor)[0], 400)
        code, _ = self.request("PUT", "/connection", {
            "role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-demo",
            "regions": ["ap-southeast-1"], "service_groups": ["compute"],
        })
        self.assertEqual(code, 200)
        self.assertEqual(self.page(next_token=token)[0], 400)
        self.assertEqual(self.page()[1], {"results": [], "next_token": None})

    def test_cursor_survives_record_removal_without_skipping_or_duplicating_next_page(self):
        first = self.page()[1]
        for record in first["results"]:
            demo.FEEDBACK.pop(record["finding_id"])
        code, second = self.page(next_token=first["next_token"])
        self.assertEqual(code, 200)
        self.assertEqual(len(second["results"]), 20)
        self.assertTrue(set(map(self.identity, first["results"])).isdisjoint(map(self.identity, second["results"])))

    def test_legacy_clear_keeps_other_flags_and_does_not_invent_missing_candidate(self):
        record = next(iter(demo.FEEDBACK.values()))
        record.update(acknowledged=True, kept=True, ignore_until=self.now + 86400)
        body = {"region": record["region"], "finding_id": record["finding_id"]}
        code, updated = self.request("PUT", "/feedback", {**body, "kept": False})
        self.assertEqual(code, 200)
        self.assertTrue(updated["acknowledged"])
        self.assertEqual(updated["ignore_until"], self.now + 86400)
        code, cleared = self.request("PUT", "/feedback", {**body, "ignoreUntil": None})
        self.assertEqual(code, 200)
        self.assertTrue(cleared["acknowledged"])
        self.assertFalse(cleared["kept"])
        self.assertEqual(cleared["ignore_until"], 0)
        self.assertEqual(self.request(path="/findings")[1]["results"], [])
        self.assertTrue(any(item["finding_id"] == body["finding_id"] for item in self.page(limit=100)[1]["results"]))


if __name__ == "__main__":
    unittest.main()
