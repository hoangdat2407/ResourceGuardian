"""History pagination and scan snapshot contracts against local Moto DynamoDB."""
import copy
import json
import unittest
import uuid
from unittest.mock import patch

import boto3
from moto import mock_aws

from tests.test_api import app, event


class HistoryManagement(unittest.TestCase):
    def setUp(self):
        aws = mock_aws()
        aws.start()
        self.addCleanup(aws.stop)
        self.table = boto3.resource("dynamodb", region_name="ap-southeast-1").create_table(
            TableName="history-management",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        self.now = 1793361600
        for target, name, value in ((app, "table", self.table), (app.time, "time", lambda: self.now)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.regions = ["ap-southeast-1", "ap-southeast-2", "us-east-1"]
        self.profile = {
            "pk": "TENANT#alice", "sk": "PROFILE", "connection_version": "v1",
            "regions": self.regions, "settings": app.config({}),
            "service_groups": list(app.SERVICE_GROUPS),
        }
        app.put(self.profile)

    def snapshot(self, number, region=None, scan_id=None, **fields):
        row = {
            "pk": self.profile["pk"], "connection_version": "v1",
            "region": region or self.regions[0], "scan_id": scan_id or str(uuid.UUID(int=number + 1, version=4)),
            "started_at": self.now - 1000 + number, "completed_at": self.now - 900 + number,
            "trigger": "manual", "status": "SUCCEEDED", "findings": [],
            "expires": self.now + 30 * 86400, **fields,
        }
        row["sk"] = app.history_key(row)
        app.put(row)
        return row

    def current(self, row, **fields):
        current = {**row, "sk": "RESULT#" + row["region"], **fields}
        app.put(current)
        return current

    def request(self, path="/history", query=None, user="alice", method="GET", body=None):
        response = app.api(event(method, path, user=user, body=body, query=query), None)
        return response["statusCode"], json.loads(response["body"])

    @staticmethod
    def identity(row):
        return row["scan_id"], row["region"]

    def test_default_pages_cover_more_than_twenty_results_and_all_regions_per_scan(self):
        stored = []
        for number in range(15):
            scan_id = str(uuid.uuid4())
            for region in self.regions:
                stored.append(self.snapshot(number, region, scan_id))
        actual, sizes, token = [], [], None
        for _ in range(4):
            code, page = self.request(query={"next_token": token} if token else None)
            self.assertEqual(code, 200)
            sizes.append(len(page["results"]))
            actual.extend(page["results"])
            token = page["next_token"]
            if token is None:
                break
        self.assertEqual(sizes, [20, 20, 5])
        self.assertIsNone(token)
        self.assertEqual([row["sk"] for row in actual], sorted((row["sk"] for row in stored), reverse=True))
        self.assertEqual(len(set(map(self.identity, actual))), 45)
        for row in stored:
            self.assertEqual({item["region"] for item in actual if item["scan_id"] == row["scan_id"]}, set(self.regions))

    def test_page_fills_past_expired_and_old_connection_rows_without_ttl_cleanup(self):
        stored = [self.snapshot(index, expires=self.now if index % 3 == 0 else self.now + 100,
                                connection_version="old" if index % 3 == 1 else "v1")
                  for index in range(18)]
        actual, token = [], None
        for _ in range(10):
            code, page = self.request(query={"limit": "2", **({"next_token": token} if token else {})})
            self.assertEqual(code, 200)
            actual.extend(page["results"])
            token = page["next_token"]
            if token is None:
                break
        self.assertIsNone(token)
        self.assertEqual(set(map(self.identity, actual)),
                         {self.identity(row) for row in stored if row["expires"] > self.now and row["connection_version"] == "v1"})
        self.assertEqual(len(actual), 6)
        self.assertEqual(len(list(app.all_items(self.profile["pk"], "HISTORY#"))), 18)

    def test_cursor_rejects_other_tenants_and_routes_and_can_resume_after_boundary_deleted(self):
        for index in range(4):
            self.snapshot(index)
        code, first = self.request(query={"limit": "2"})
        self.assertEqual(code, 200)
        token = first["next_token"]
        app.put({**self.profile, "pk": "TENANT#bob"})
        self.assertEqual(self.request(query={"next_token": token}, user="bob")[0], 400)
        self.assertEqual(self.request("/feedback", query={"next_token": token})[0], 400)
        for row in first["results"]:
            self.table.delete_item(Key={"pk": row["pk"], "sk": row["sk"]})
        code, second = self.request(query={"limit": "2", "next_token": token})
        self.assertEqual(code, 200)
        self.assertEqual(len(second["results"]), 2)
        self.assertTrue(set(map(self.identity, first["results"])).isdisjoint(map(self.identity, second["results"])))

    def test_reconnect_filters_old_history_even_when_client_presents_old_cursor(self):
        for index in range(3):
            self.snapshot(index)
        token = self.request(query={"limit": "1"})[1]["next_token"]
        app.put({**self.profile, "connection_version": "v2"})
        # History tokens contain tenant/key only; the profile filter still prevents old data exposure.
        for query in (None, {"next_token": token}):
            self.assertEqual(self.request(query=query), (200, {"results": [], "next_token": None}))

    def test_scan_falls_back_to_history_after_current_replaced_and_preserves_legacy_fields(self):
        scan_id = str(uuid.uuid4())
        old = []
        for region in self.regions:
            row = self.snapshot(1, region, scan_id, findings=[{"resource_id": "legacy-" + region}],
                                candidates=[{"resource_id": "private"}])
            row.pop("trigger")
            row.pop("started_at")
            app.put(row)
            old.append(row)
            self.current(self.snapshot(2, region))
        code, scan = self.request("/scans/" + scan_id)
        self.assertEqual(code, 200)
        self.assertEqual(set(map(self.identity, scan["results"])), set(map(self.identity, old)))
        for row in scan["results"]:
            self.assertNotIn("candidates", row)
            self.assertNotIn("trigger", row)
            self.assertNotIn("started_at", row)
            self.assertNotIn("first_seen_at", row["findings"][0])
        for row in old:
            self.assertEqual(app.get(row["pk"], row["sk"]), row)

    def test_scan_keeps_all_regions_when_only_some_current_results_have_been_replaced(self):
        scan_id = str(uuid.uuid4())
        expected = []
        for region in self.regions:
            row = self.snapshot(1, region, scan_id)
            expected.append(row)
            self.current(row)
        self.current(self.snapshot(2, self.regions[0]))
        code, scan = self.request("/scans/" + scan_id)
        self.assertEqual(code, 200)
        self.assertEqual(set(map(self.identity, scan["results"])), set(map(self.identity, expected)))

    def test_scan_uses_terminal_history_snapshot_and_adds_regions_still_running(self):
        scan_id = str(uuid.uuid4())
        completed = self.snapshot(1, self.regions[0], scan_id, status="PARTIAL",
                                  findings=[{"resource_id": "snapshot-original"}],
                                  errors=[{"type": "EC2", "code": "RESOURCE_LIMIT"}])
        self.current(completed, status="SUCCEEDED", findings=[{"resource_id": "changed-current"}])
        running = self.current({**completed, "region": self.regions[1]}, status="RUNNING", findings=[],
                               deadline_at=self.now + 100, candidates=[{"resource_id": "private"}])
        code, scan = self.request("/scans/" + scan_id)
        self.assertEqual(code, 200)
        by_region = {row["region"]: row for row in scan["results"]}
        self.assertEqual(set(by_region), set(self.regions[:2]))
        self.assertEqual(by_region[completed["region"]]["findings"], completed["findings"])
        self.assertEqual(by_region[completed["region"]]["status"], "PARTIAL")
        self.assertEqual(by_region[completed["region"]]["errors"], completed["errors"])
        self.assertEqual(by_region[running["region"]]["status"], "RUNNING")
        self.assertTrue(all("candidates" not in row for row in scan["results"]))

    def test_scan_does_not_restore_expired_or_other_connection_history_regions(self):
        scan_id = str(uuid.uuid4())
        self.snapshot(1, self.regions[0], scan_id, expires=self.now)
        self.snapshot(1, self.regions[1], scan_id, connection_version="old")
        code, _ = self.request("/scans/" + scan_id)
        self.assertEqual(code, 404)
        current = self.current(self.snapshot(1, self.regions[2], scan_id))
        code, scan = self.request("/scans/" + scan_id)
        self.assertEqual(code, 200)
        self.assertEqual(list(map(self.identity, scan["results"])), [self.identity(current)])

    def test_new_feedback_changes_current_only_and_never_rewrites_history_or_scan(self):
        finding = {"finding_id": "a" * 64, "type": "EBS", "region": self.regions[0],
                   "resource_id": "vol-snapshot", "level": "REVIEW", "evidence": {"size_gib": 0}}
        row = self.snapshot(1, findings=[finding], candidates=[finding])
        self.current(row)
        before_history = self.request()[1]
        before_scan = self.request("/scans/" + row["scan_id"])[1]
        before_stored = copy.deepcopy(app.get(row["pk"], row["sk"]))
        code, _ = self.request("/feedback", method="PUT", body={
            "finding_id": finding["finding_id"], "region": finding["region"], "acknowledged": True, "kept": True,
        })
        self.assertEqual(code, 200)
        self.assertEqual(self.request("/findings")[1]["results"][0]["findings"], [])
        self.assertEqual(self.request()[1], before_history)
        self.assertEqual(self.request("/scans/" + row["scan_id"])[1], before_scan)
        self.assertEqual(app.get(row["pk"], row["sk"]), before_stored)
        self.assertNotIn("candidates", before_history["results"][0])
        self.assertNotIn("candidates", before_scan["results"][0])

    def test_invalid_pagination_and_scan_ids_return_four_hundred_without_writes(self):
        row = self.snapshot(1)
        for raw in ("", "0", "101", "-1", "1.5", "true"):
            with self.subTest(limit=raw):
                self.assertEqual(self.request(query={"limit": raw})[0], 400)
        for token in ("", "not-json", app.encode_token({"pk": self.profile["pk"], "sk": "FEEDBACK#v1#x"})):
            with self.subTest(token=token):
                self.assertEqual(self.request(query={"next_token": token})[0], 400)
        for scan_id in ("bad", str(uuid.uuid1()), str(uuid.uuid4()).upper()):
            with self.subTest(scan_id=scan_id):
                self.assertEqual(self.request("/scans/" + scan_id)[0], 400)
        self.assertEqual(app.get(row["pk"], row["sk"]), row)


if __name__ == "__main__":
    unittest.main()
