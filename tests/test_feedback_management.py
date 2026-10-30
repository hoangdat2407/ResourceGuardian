"""Feedback management and pagination contracts against local Moto DynamoDB."""
import copy
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import boto3
from moto import mock_aws

from tests.test_api import app, event


class FeedbackManagement(unittest.TestCase):
    def setUp(self):
        aws = mock_aws()
        aws.start()
        self.addCleanup(aws.stop)
        self.table = boto3.resource("dynamodb", region_name="ap-southeast-1").create_table(
            TableName="feedback-management",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        for target, name, value in ((app, "table", self.table), (app.time, "time", lambda: 1793361600)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.now = 1793361600
        self.profile = {
            "pk": "TENANT#alice", "sk": "PROFILE", "connection_version": "v1",
            "regions": ["ap-southeast-1", "ap-southeast-2"], "settings": app.config({}),
            "service_groups": list(app.SERVICE_GROUPS),
        }
        app.put(self.profile)

    def record(self, number, **fields):
        region = fields.pop("region", "ap-southeast-1")
        ident = format(number, "064x")
        record = {
            "pk": self.profile["pk"], "sk": app.feedback_prefix(self.profile, region) + ident,
            "region": region, "finding_id": ident, "connection_version": "v1", **fields,
        }
        app.put(record)
        return record

    def request(self, method, path="/feedback", body=None, query=None):
        request = event(method, path, body=body)
        if query is not None:
            request["queryStringParameters"] = query
        response = app.api(request, None)
        return response["statusCode"], json.loads(response["body"])

    def update(self, record, **fields):
        return self.request("PUT", body={
            "region": record["region"], "finding_id": record["finding_id"], **fields,
        })

    def test_default_page_of_acknowledged_only_records_still_has_more_hidden_feedback(self):
        for index in range(31):
            self.record(index, acknowledged=True, kept=index < 11)
        code, first = self.request("GET")
        self.assertEqual(code, 200)
        self.assertEqual(len(first["results"]), 20)
        self.assertTrue(all(record["acknowledged"] and not record["kept"] for record in first["results"]))
        self.assertIsNotNone(first["next_token"])
        code, second = self.request("GET", query={"next_token": first["next_token"]})
        self.assertEqual(code, 200)
        self.assertEqual(len(second["results"]), 11)
        self.assertTrue(all(record["kept"] for record in second["results"]))
        self.assertIsNone(second["next_token"])
        combined = first["results"] + second["results"]
        self.assertEqual(len({(record["region"], record["finding_id"]) for record in combined}), 31)
        self.assertTrue(all("resource_id" not in record for record in combined))

    def test_pagination_reads_past_expired_and_wrong_version_items_without_losing_live_records(self):
        expected = set()
        for index in range(13):
            fields = {"kept": True} if index % 3 == 0 else {"ignore_until": self.now + 100, "expires": self.now + 100}
            if index % 4 == 1:
                fields = {"ignore_until": self.now, "expires": self.now}
            elif index % 4 == 2:
                fields["connection_version"] = "old-version"
            else:
                expected.add(format(index, "064x"))
            self.record(index, **fields)
        identifiers, token = [], None
        for _ in range(10):
            query = {"limit": "2", **({"next_token": token} if token else {})}
            code, page = self.request("GET", query=query)
            self.assertEqual(code, 200)
            identifiers.extend(record["finding_id"] for record in page["results"])
            token = page["next_token"]
            if token is None:
                break
        self.assertIsNone(token)
        self.assertEqual(set(identifiers), expected)
        self.assertEqual(len(identifiers), len(expected))

    def test_feedback_cursor_cannot_continue_after_reconnect_or_cross_to_history(self):
        for index in range(3):
            self.record(index, kept=True)
        code, first = self.request("GET", query={"limit": "1"})
        self.assertEqual(code, 200)
        token = first["next_token"]
        self.assertIsNotNone(token)
        self.assertEqual(self.request("GET", "/history", query={"next_token": token})[0], 400)
        app.put({**self.profile, "connection_version": "v2"})
        self.assertEqual(self.request("GET", query={"next_token": token})[0], 400)
        code, fresh = self.request("GET")
        self.assertEqual(code, 200)
        self.assertEqual(fresh, {"results": [], "next_token": None})

    def test_clear_legacy_feedback_without_candidate_preserves_other_flags_and_history(self):
        record = self.record(1, acknowledged=True, kept=True, ignore_until=self.now + 86400)
        history = {
            "pk": self.profile["pk"], "sk": "HISTORY#1", "region": record["region"],
            "connection_version": "v1", "findings": [{"finding_id": record["finding_id"], "level": "REVIEW"}],
            "status": "SUCCEEDED", "expires": self.now + 86400,
        }
        app.put(history)
        original = copy.deepcopy(history)
        code, cleared_keep = self.update(record, kept=False)
        self.assertEqual(code, 200)
        self.assertFalse(cleared_keep["kept"])
        self.assertTrue(cleared_keep["acknowledged"])
        self.assertEqual(cleared_keep["ignore_until"], self.now + 86400)
        code, cleared_ignore = self.update(record, ignoreUntil=None)
        self.assertEqual(code, 200)
        self.assertEqual(cleared_ignore["ignore_until"], 0)
        self.assertFalse(cleared_ignore["kept"])
        self.assertTrue(cleared_ignore["acknowledged"])
        self.assertNotIn("resource_id", cleared_ignore)
        self.assertEqual(self.request("GET", "/findings"), (200, {"results": []}))
        self.assertEqual(app.get(self.profile["pk"], history["sk"]), original)
        code, page = self.request("GET")
        self.assertEqual(code, 200)
        self.assertEqual(len(page["results"]), 1)
        self.assertEqual(page["results"][0]["finding_id"], record["finding_id"])

    def test_extend_ignore_to_thirty_days_preserves_keep_and_acknowledgement(self):
        record = self.record(2, acknowledged=True, kept=True, ignore_until=self.now + 86400)
        until = datetime.fromtimestamp(self.now + 30 * 86400, timezone.utc).isoformat().replace("+00:00", "Z")
        code, updated = self.update(record, ignoreUntil=until)
        self.assertEqual(code, 200)
        self.assertEqual(updated["ignore_until"], self.now + 30 * 86400)
        self.assertTrue(updated["acknowledged"])
        self.assertTrue(updated["kept"])
        self.assertNotIn("expires", updated)

    def test_expired_ignore_with_acknowledgement_is_listed_but_pure_expired_record_is_not(self):
        acknowledged = self.record(1, acknowledged=True, ignore_until=self.now)
        kept = self.record(2, kept=True, ignore_until=self.now - 1)
        self.record(3, ignore_until=self.now, expires=self.now)
        code, page = self.request("GET")
        self.assertEqual(code, 200)
        self.assertEqual({record["finding_id"] for record in page["results"]},
                         {acknowledged["finding_id"], kept["finding_id"]})
        active_hidden = [record for record in page["results"]
                         if record.get("kept") or record.get("ignore_until", 0) > self.now]
        self.assertEqual([record["finding_id"] for record in active_hidden], [kept["finding_id"]])


if __name__ == "__main__":
    unittest.main()
