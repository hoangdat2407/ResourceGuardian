"""Tenant-scoped inventory identity persistence and API pagination contracts."""
import json
import time
import unittest
import uuid

import boto3
from moto import mock_aws

from tests.test_api import app, event


class InventoryIdentityTest(unittest.TestCase):
    def setUp(self):
        self.mock = mock_aws()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.table = boto3.resource("dynamodb", region_name="ap-southeast-1").create_table(
            TableName="inventory-identity-table",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        self.old_table = app.table
        app.table = self.table
        self.addCleanup(setattr, app, "table", self.old_table)
        self.now = int(time.time())
        self.scan_id = str(uuid.uuid4())
        self.profile = {
            "pk": "TENANT#alice", "sk": "PROFILE", "external_id": "test-external-id",
            "account_id": "123456789012", "regions": ["ap-southeast-1"],
            "service_groups": ["storage"], "connection_version": "v1",
            "settings": app.config({}),
        }
        self.marker = {
            "pk": self.profile["pk"], "sk": "RESULT#ap-southeast-1", "region": "ap-southeast-1",
            "scan_id": self.scan_id, "connection_version": "v1", "status": "RUNNING",
            "run_token": "run-token", "run_until": self.now + 300, "deadline_at": self.now + 900,
            "started_at": self.now,
        }
        app.put(self.profile)
        app.put(self.marker)

    def persist(self, count=61):
        resources = [
            {
                "type": "EBS", "service_id": "ebs",
                "resource_id": "vol-" + ("x" * 600 if index == 0 else str(index)),
                "resource_name": "Dữ liệu_日本_" + str(index),
            }
            for index in range(count)
        ]
        written = app.record_inventory_pages(self.marker, resources, lambda: None, self.profile["account_id"])
        self.assertEqual(written, count)
        terminal = {
            **self.marker, "status": "SUCCEEDED", "completed_at": self.now + 1, "errors": [],
            "counts": {"EBS": count}, "findings": [], "inventory_persisted": True,
            "inventory_count": count, "inventory_run_token": self.marker["run_token"],
            "expires": self.now + app.RETENTION_SECONDS,
        }
        app.put(terminal)
        return terminal

    def request(self, user="alice", **query):
        reply = app.api(event("GET", "/inventory", user=user, query=query), None)
        return reply["statusCode"], json.loads(reply["body"])

    def test_persists_bounded_pages_and_paginates_every_identity(self):
        self.persist()
        pages = list(app.all_items(self.profile["pk"], "INVENTORY#v1#" + self.scan_id + "#"))
        self.assertEqual([len(page["resources"]) for page in pages], [25, 25, 11])
        self.assertTrue(all(page["account_id"] == self.profile["account_id"] for page in pages))

        found, token = [], None
        while True:
            query = {"scan_id": self.scan_id, "limit": "17"}
            if token:
                query["next_token"] = token
            code, body = self.request(**query)
            self.assertEqual(code, 200)
            self.assertTrue(body["available"])
            found.extend(body["resources"])
            token = body["next_token"]
            if not token:
                break
        self.assertEqual(len(found), 61)
        self.assertEqual(len({item["resource_id"] for item in found}), 61)
        self.assertTrue(any(item.get("resource_name") == "Dữ liệu_日本_0" for item in found))
        self.assertTrue(any(len(item["resource_id"]) > 600 for item in found))

    def test_filters_unicode_account_scan_and_rejects_cross_tenant_token(self):
        self.persist(3)
        for query in (
            {"q": "日本_1"},
            {"q": "vol-" + ("x" * 600)},
            {"q": self.profile["account_id"]},
            {"q": self.scan_id},
            {"type": "EBS", "service": "ebs", "region": "ap-southeast-1"},
        ):
            with self.subTest(query=query):
                code, body = self.request(scan_id=self.scan_id, limit="10", **query)
                self.assertEqual(code, 200)
                self.assertGreater(len(body["resources"]), 0)

        _, first = self.request(scan_id=self.scan_id, limit="1")
        app.put({**self.profile, "pk": "TENANT#bob"})
        code, body = self.request(user="bob", scan_id=self.scan_id, limit="1", next_token=first["next_token"])
        self.assertIn(code, (400, 404))
        self.assertEqual(body.get("resources", []), [])

    def test_legacy_scan_reports_aggregate_only_without_fake_resources(self):
        legacy = {**self.marker, "status": "SUCCEEDED", "counts": {"EBS": 2}, "findings": [],
                  "completed_at": self.now, "expires": self.now + app.RETENTION_SECONDS}
        legacy.pop("run_token")
        app.put(legacy)
        code, body = self.request(scan_id=self.scan_id, limit="10")
        self.assertEqual(code, 200)
        self.assertFalse(body["available"])
        self.assertTrue(body["aggregate_only"])
        self.assertEqual(body["resources"], [])
        self.assertIsNone(body["total_count"])


if __name__ == "__main__":
    unittest.main()
