"""Feedback metadata and snapshot contracts using Moto, never a deployed AWS API."""
import copy
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import boto3
from moto import mock_aws

from tests.test_api import app, event


class FeedbackMetadata(unittest.TestCase):
    def setUp(self):
        aws = mock_aws()
        aws.start()
        self.addCleanup(aws.stop)
        self.table = boto3.resource("dynamodb", region_name="ap-southeast-1").create_table(
            TableName="feedback-metadata",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        self.start_patch(app, "table", self.table)
        self.now = 1793000000
        self.start_patch(app.time, "time", return_value=self.now)
        self.profile = {
            "pk": "TENANT#alice", "sk": "PROFILE", "connection_version": "v1",
            "regions": ["ap-southeast-1", "ap-southeast-2"], "settings": app.config({}),
            "account_id": "999999999999", "service_groups": list(app.SERVICE_GROUPS),
        }
        self.finding = {
            "finding_id": "a" * 64, "type": "S3_MULTIPART", "region": "ap-southeast-1",
            "resource_id": "s3://fixture-bucket/archive.bin", "account_id": "111111111111",
            "rule_id": "S3_STALE_MULTIPART", "level": "REVIEW", "reason": "Review upload",
            "evidence": {"upload_id": "fixture-upload", "age_days": 8},
        }
        app.put(self.profile)
        self.result = self.save_result()

    def start_patch(self, target, name, *args, **kwargs):
        patcher = patch.object(target, name, *args, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def save_result(self, finding=None, *, candidate_pool=True, **overrides):
        row = {
            "pk": self.profile["pk"], "sk": "RESULT#ap-southeast-1", "region": "ap-southeast-1",
            "connection_version": "v1", "status": "SUCCEEDED", "findings": [],
            "scan_id": "00000000-0000-4000-8000-000000000001", "completed_at": self.now,
        }
        row["candidates" if candidate_pool else "findings"] = [copy.deepcopy(self.finding if finding is None else finding)]
        row.update(overrides)
        app.put(row)
        return row

    def feedback(self, **fields):
        payload = {"region": self.finding["region"], "finding_id": self.finding["finding_id"], **fields}
        reply = app.api(event("PUT", "/feedback", body=payload), None)
        return reply["statusCode"], json.loads(reply["body"])

    def get_feedback(self):
        reply = app.api(event("GET", "/feedback"), None)
        self.assertEqual(reply["statusCode"], 200)
        return json.loads(reply["body"])["results"]

    def expected_metadata(self, finding=None):
        finding = self.finding if finding is None else finding
        return {field: finding[field] for field in ("type", "resource_id", "account_id", "rule_id")}

    def assert_metadata(self, record, expected=None):
        expected = self.expected_metadata() if expected is None else expected
        for field, value in expected.items():
            self.assertEqual(record[field], value, field)

    def test_candidate_metadata_round_trips_in_put_storage_and_get(self):
        code, record = self.feedback(acknowledged=True)
        self.assertEqual(code, 200)
        self.assert_metadata(record)
        self.assertNotEqual(record["account_id"], self.profile["account_id"])
        self.assertNotIn("evidence", record)
        self.assert_metadata(app.get(self.profile["pk"], record["sk"]))
        self.assert_metadata(self.get_feedback()[0])

    def test_legacy_findings_without_candidate_pool_supply_metadata(self):
        legacy = copy.deepcopy(self.finding)
        legacy.pop("region")
        self.save_result(legacy, candidate_pool=False)
        code, record = self.feedback(kept=True)
        self.assertEqual(code, 200)
        self.assert_metadata(record)
        self.assertTrue(record["kept"])

    def test_hidden_candidate_metadata_wins_over_displayed_legacy_finding(self):
        other = {**self.finding, "resource_id": "wrong-displayed-resource"}
        self.save_result(findings=[other])
        code, record = self.feedback(kept=True)
        self.assertEqual(code, 200)
        self.assert_metadata(record)

    def test_metadata_is_preserved_if_candidate_is_no_longer_saved(self):
        self.assertEqual(self.feedback(acknowledged=True)[0], 200)
        self.save_result(candidates=[], findings=[])
        history = {**self.result, "sk": "HISTORY#1", "findings": [{**self.finding, "resource_id": "wrong-history"}]}
        app.put(history)
        code, record = self.feedback(kept=True)
        self.assertEqual(code, 200)
        self.assert_metadata(record)
        self.assertTrue(record["acknowledged"])
        self.assertTrue(record["kept"])

    def test_incomplete_candidate_enriches_valid_fields_without_erasing_metadata(self):
        self.feedback(acknowledged=True)
        incomplete = {
            "finding_id": self.finding["finding_id"], "resource_id": "s3://fixture-bucket/renamed.bin",
            "type": None, "account_id": "", "rule_id": 42,
        }
        self.save_result(incomplete)
        code, record = self.feedback(kept=True)
        self.assertEqual(code, 200)
        expected = {**self.expected_metadata(), "resource_id": incomplete["resource_id"]}
        self.assert_metadata(record, expected)

    def test_legacy_feedback_without_metadata_remains_manageable_by_id_and_region(self):
        self.save_result(candidates=[], findings=[])
        existing = {
            "pk": self.profile["pk"], "sk": app.feedback_prefix(self.profile, self.finding["region"]) + self.finding["finding_id"],
            "connection_version": "v1", "region": self.finding["region"], "finding_id": self.finding["finding_id"],
            "kept": True,
        }
        app.put(existing)
        code, record = self.feedback(acknowledged=True)
        self.assertEqual(code, 200)
        self.assertTrue(record["kept"])
        self.assertTrue(record["acknowledged"])
        for field in self.expected_metadata():
            self.assertNotIn(field, record)
        self.assertEqual(self.get_feedback()[0]["finding_id"], self.finding["finding_id"])

    def test_missing_metadata_is_not_inferred_from_profile_or_evidence(self):
        incomplete = {"finding_id": self.finding["finding_id"], "evidence": self.expected_metadata()}
        self.save_result(incomplete)
        code, record = self.feedback(kept=True)
        self.assertEqual(code, 200)
        for field in self.expected_metadata():
            self.assertNotIn(field, record)

    def test_request_metadata_is_rejected_without_writing(self):
        for field, value in self.expected_metadata().items():
            with self.subTest(field=field), patch.object(app, "put") as put:
                code, _ = self.feedback(acknowledged=True, **{field: value})
                self.assertEqual(code, 400)
                put.assert_not_called()

    def test_unrelated_region_or_connection_candidates_cannot_supply_metadata(self):
        for overrides in ({"region": "ap-southeast-2"}, {"connection_version": "old"},
                          {"candidates": [{**self.finding, "region": "ap-southeast-2"}]},
                          {"candidates": [{**self.finding, "finding_id": "b" * 64}]}):
            with self.subTest(overrides=overrides):
                self.save_result(**overrides)
                code, _ = self.feedback(acknowledged=True)
                self.assertEqual(code, 404)
                self.assertEqual(self.get_feedback(), [])

    def test_other_tenant_candidates_and_feedback_are_not_read_or_updated(self):
        self.table.delete_item(Key={"pk": self.profile["pk"], "sk": self.result["sk"]})
        foreign = self.save_result(pk="TENANT#bob")
        foreign_feedback = {
            "pk": "TENANT#bob", "sk": app.feedback_prefix(self.profile, self.finding["region"]) + self.finding["finding_id"],
            "connection_version": "v1", "region": self.finding["region"], "finding_id": self.finding["finding_id"],
            "kept": True, **self.expected_metadata(),
        }
        app.put(foreign_feedback)
        code, _ = self.feedback(acknowledged=True)
        self.assertEqual(code, 404)
        self.assertEqual(self.get_feedback(), [])
        self.assertEqual(app.get("TENANT#bob", foreign["sk"]), foreign)
        self.assertEqual(app.get("TENANT#bob", foreign_feedback["sk"]), foreign_feedback)

    def test_new_connection_cannot_reuse_old_feedback_metadata(self):
        self.feedback(acknowledged=True)
        app.put({**self.profile, "connection_version": "v2"})
        code, _ = self.feedback(kept=True)
        self.assertEqual(code, 404)
        self.assertEqual(self.get_feedback(), [])

    def test_flags_remain_independent_and_feedback_does_not_rewrite_snapshots(self):
        self.result["findings"] = [copy.deepcopy(self.finding)]
        app.put(self.result)
        history = {**self.result, "sk": "HISTORY#1", "expires": self.now + 86400}
        app.put(history)
        until = datetime.fromtimestamp(self.now + 86400, timezone.utc).isoformat().replace("+00:00", "Z")
        for fields in ({"acknowledged": True}, {"kept": True}, {"ignoreUntil": until},
                       {"kept": False}, {"ignoreUntil": None}):
            code, record = self.feedback(**fields)
            self.assertEqual(code, 200)
            self.assert_metadata(record)
            self.assertTrue(record["acknowledged"])
            if fields == {"kept": False}:
                self.assertEqual(record["ignore_until"], self.now + 86400)
            current_reply = app.api(event("GET", "/findings"), None)
            current = json.loads(current_reply["body"])["results"][0]["findings"]
            if record.get("kept") or record.get("ignore_until", 0) > self.now:
                self.assertEqual(current, [])
            else:
                self.assertEqual(len(current), 1)
                self.assertTrue(current[0]["acknowledged"])
            self.assertEqual(app.get(self.profile["pk"], self.result["sk"]), self.result)
            self.assertEqual(app.get(self.profile["pk"], history["sk"]), history)
        code, record = self.feedback(acknowledged=False)
        self.assertEqual(code, 200)
        self.assertFalse(record["acknowledged"])
        self.assertFalse(record["kept"])
        self.assertEqual(record["ignore_until"], 0)


if __name__ == "__main__":
    unittest.main()
