"""Notification state regressions: Moto DynamoDB and mocked SES, never live AWS."""
import copy
import json
import os
import unittest
from unittest.mock import MagicMock, patch

import boto3
from botocore.exceptions import ClientError, ReadTimeoutError
from moto import mock_aws

from tests.test_api import app, event


class Notifications(unittest.TestCase):
    def setUp(self):
        self.aws = mock_aws()
        self.aws.start()
        self.addCleanup(self.aws.stop)
        db = boto3.resource("dynamodb", region_name="ap-southeast-1")
        self.table = db.create_table(
            TableName="test-table",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        self.start_patch(patch.object(app, "table", self.table))
        self.start_patch(patch.dict(os.environ, SES_SENDER="owner@example.com", WEB_URL="https://guardian.example/"))
        self.now = 1800000000
        self.start_patch(patch.object(app.time, "time", side_effect=lambda: self.now))
        self.client = self.start_patch(patch.object(app.boto3, "client"))
        self.ses = self.client.return_value
        self.ses.send_email.return_value = {"MessageId": "ses-message-1"}
        self.profile = {
            "pk": "TENANT#alice", "sk": "PROFILE", "connection_version": "v1",
            "account_id": "123456789012", "settings": app.config({"interval_hours": 6}),
            "notifications": {"enabled": True, "email": "verified@example.com"},
        }
        self.result = {
            "region": "ap-southeast-1", "scan_id": "scan-1", "status": "PARTIAL",
            "completed_at": self.now, "counts": {"EBS": 2}, "finding_count": 2,
            "errors": [{"type": "EC2", "code": "AccessDenied"}],
            "note": "Only selected regions; at most 50 displayed findings.",
            "findings": [
                {"type": "EBS", "resource_id": "vol-demo", "level": "REVIEW", "rule_id": "EBS_UNATTACHED",
                 "reason": "Unattached volume; validate retention", "evidence": {"size_gib": 20, "observed_hours": 48}},
                {"type": "EBS", "resource_id": "vol-wait", "level": "OBSERVING", "reason": "Wait for observation"},
            ],
        }

    def start_patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def notice(self, profile=None):
        profile = profile or self.profile
        records = list(app.all_items(profile["pk"], "NOTICE#" + profile["connection_version"] + "#"))
        self.assertEqual(len(records), 1)
        return records[0]

    def changed_result(self):
        result = copy.deepcopy(self.result)
        result["findings"][0]["resource_id"] = "vol-new"
        return result

    def scan_with_email(self):
        profile = {
            **self.profile, "regions": [self.result["region"]],
            "service_groups": list(app.SERVICE_GROUPS),
            "role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-demo",
        }
        app.put(profile)
        app.put({
            "pk": profile["pk"], "sk": "RESULT#" + self.result["region"],
            "scan_id": "scan-email", "status": "QUEUED", "started_at": self.now,
        })
        findings = [
            {**finding, "finding_id": str(index) * 64}
            for index, finding in enumerate(self.result["findings"])
        ]
        collected = {"findings": findings, "counts": {"EBS": 2}, "partial": False, "errors": []}
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 200000
        with patch.object(app, "session"), patch.object(app, "collect_region", return_value=collected):
            app.worker({
                "pk": profile["pk"], "region": self.result["region"],
                "scan_id": "scan-email", "connection_version": "v1",
            }, context)
        return app.get(profile["pk"], "RESULT#" + self.result["region"])

    def test_worker_persists_notification_success_in_result_and_history(self):
        result = self.scan_with_email()
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["notification"], "SENT")
        history = list(app.all_items(self.profile["pk"], "HISTORY#"))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["notification"], "SENT")
        self.assertEqual(self.notice()["message_id"], "ses-message-1")

    def test_worker_keeps_scan_and_history_when_ses_rejects_digest(self):
        self.ses.send_email.side_effect = ClientError({
            "Error": {"Code": "MessageRejected", "Message": "rejected"},
            "ResponseMetadata": {"HTTPStatusCode": 400},
        }, "SendEmail")
        result = self.scan_with_email()
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["notification"], "FAILED")
        self.assertEqual(len(result["findings"]), 2)
        history = list(app.all_items(self.profile["pk"], "HISTORY#"))
        self.assertEqual(history[0]["notification"], "FAILED")
        self.assertEqual(self.notice()["status"], "FAILED")

    def test_success_persists_acceptance_and_meaningful_digest(self):
        self.assertEqual(app.notify(self.profile, self.result), "SENT")
        record = self.notice()
        self.assertEqual(record["status"], "SENT")
        self.assertEqual(record["message_id"], "ses-message-1")
        self.assertEqual(record["sent_at"], self.now)
        self.assertEqual(record["cooldown_until"], self.now + 6 * 3600)
        request = self.ses.send_email.call_args.kwargs
        self.assertEqual(request["Destination"], {"ToAddresses": ["verified@example.com"]})
        body = request["Message"]["Body"]["Text"]["Data"]
        for expected in ("123456789012", "ap-southeast-1", "scan-1", "PARTIAL", "vol-demo",
                         "validate retention", "size_gib", "AccessDenied", "https://guardian.example/",
                         "Only selected regions", "không tự dừng hoặc xóa"):
            self.assertIn(expected, body)
        self.assertNotIn("vol-wait", body)
        self.assertEqual(request["Message"]["Body"]["Text"]["Charset"], "UTF-8")
        self.assertEqual(self.client.call_args.kwargs["config"].retries["total_max_attempts"], 1)

    def test_same_findings_do_not_resend_when_metrics_or_order_change(self):
        self.assertEqual(app.notify(self.profile, self.result), "SENT")
        result = copy.deepcopy(self.result)
        result["findings"].reverse()
        result["findings"][1]["evidence"]["observed_hours"] = 100
        self.now += 7 * 3600
        self.assertEqual(app.notify(self.profile, result), "UNCHANGED")
        self.ses.send_email.assert_called_once()

    def test_changed_set_waits_for_scan_interval_boundary(self):
        self.assertEqual(app.notify(self.profile, self.result), "SENT")
        changed = self.changed_result()
        self.now += 6 * 3600 - 1
        self.assertEqual(app.notify(self.profile, changed), "COOLDOWN")
        self.now += 1
        self.assertEqual(app.notify(self.profile, changed), "SENT")
        self.assertEqual(self.ses.send_email.call_count, 2)

    def test_resolution_resets_dedup_without_resetting_cooldown(self):
        self.assertEqual(app.notify(self.profile, self.result), "SENT")
        empty = {**self.result, "findings": []}
        self.assertEqual(app.notify(self.profile, empty), "NO_NEW_FINDINGS")
        self.assertEqual(self.notice()["message_id"], "ses-message-1")
        self.assertEqual(app.notify(self.profile, self.result), "COOLDOWN")
        self.now += 6 * 3600
        self.assertEqual(app.notify(self.profile, self.result), "SENT")

    def test_empty_set_does_not_send(self):
        self.assertEqual(app.notify(self.profile, {**self.result, "findings": []}), "NO_NEW_FINDINGS")
        self.ses.send_email.assert_not_called()

    def test_rejection_is_durable_and_retried_only_after_cooldown(self):
        self.ses.send_email.side_effect = ClientError(
            {"Error": {"Code": "MessageRejected", "Message": "sandbox rejection"},
             "ResponseMetadata": {"HTTPStatusCode": 400}}, "SendEmail")
        self.assertEqual(app.notify(self.profile, self.result), "FAILED")
        record = self.notice()
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["error_code"], "MessageRejected")
        self.assertNotIn("fingerprint", record)
        self.assertNotIn("message_id", record)
        self.assertEqual(app.notify(self.profile, self.result), "COOLDOWN")
        self.now += 6 * 3600
        self.ses.send_email.side_effect = None
        self.assertEqual(app.notify(self.profile, self.result), "SENT")
        self.assertEqual(self.ses.send_email.call_count, 2)

    def test_lost_ses_response_is_unknown_not_rejected(self):
        self.ses.send_email.side_effect = ReadTimeoutError(endpoint_url="https://email.example")
        self.assertEqual(app.notify(self.profile, self.result), "UNKNOWN")
        self.assertEqual(self.notice()["status"], "UNKNOWN")
        self.assertEqual(self.notice()["error_code"], "ReadTimeoutError")
        self.assertEqual(app.notify(self.profile, self.result), "COOLDOWN")

    def test_ses_server_error_or_missing_receipt_is_unknown(self):
        self.ses.send_email.side_effect = ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "retry later"},
             "ResponseMetadata": {"HTTPStatusCode": 503}}, "SendEmail")
        self.assertEqual(app.notify(self.profile, self.result), "UNKNOWN")
        self.now += 6 * 3600
        self.ses.send_email.side_effect = None
        self.ses.send_email.return_value = {}
        self.assertEqual(app.notify(self.profile, self.result), "UNKNOWN")
        self.assertEqual(self.notice()["error_code"], "MissingMessageId")

    def test_concurrent_sends_observe_durable_claim(self):
        nested = []
        def send(**kwargs):
            self.assertEqual(self.notice()["status"], "SENDING")
            nested.append(app.notify(self.profile, self.result))
            return {"MessageId": "concurrent-accepted"}
        self.ses.send_email.side_effect = send
        self.assertEqual(app.notify(self.profile, self.result), "SENT")
        self.assertEqual(nested, ["IN_PROGRESS"])
        self.ses.send_email.assert_called_once()

    def test_two_attempts_reading_same_snapshot_use_conditional_claim(self):
        real_put = self.table.put_item
        nested = []
        first_claim = True
        def interleaved_put(**kwargs):
            nonlocal first_claim
            if first_claim:
                first_claim = False
                nested.append(app.notify(self.profile, self.result))
            return real_put(**kwargs)
        with patch.object(self.table, "put_item", side_effect=interleaved_put):
            self.assertEqual(app.notify(self.profile, self.result), "IN_PROGRESS")
        self.assertEqual(nested, ["SENT"])
        self.ses.send_email.assert_called_once()
        self.assertEqual(self.notice()["message_id"], "ses-message-1")

    def test_state_failure_before_send_never_calls_ses(self):
        failure = ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}}, "PutItem")
        with patch.object(self.table, "put_item", side_effect=failure):
            self.assertEqual(app.notify(self.profile, self.result), "STATE_FAILED")
        self.ses.send_email.assert_not_called()

    def test_accepted_send_with_failed_state_write_is_not_failed_delivery(self):
        real_put = self.table.put_item
        def fail_after_acceptance(**kwargs):
            if kwargs["Item"]["status"] == "SENT":
                raise ClientError({"Error": {"Code": "InternalServerError", "Message": "write failed"}}, "PutItem")
            return real_put(**kwargs)
        with patch.object(self.table, "put_item", side_effect=fail_after_acceptance):
            self.assertEqual(app.notify(self.profile, self.result), "SENT_UNRECORDED")
        self.assertEqual(self.notice()["status"], "SENDING")
        self.assertEqual(app.notify(self.profile, self.result), "IN_PROGRESS")
        self.ses.send_email.assert_called_once()
        self.now += 6 * 3600
        self.assertEqual(app.notify(self.profile, self.result), "SENT")
        self.assertEqual(self.ses.send_email.call_count, 2)

    def test_previous_message_receipt_survives_later_rejection(self):
        self.assertEqual(app.notify(self.profile, self.result), "SENT")
        self.now += 6 * 3600
        self.ses.send_email.side_effect = ClientError({"Error": {"Code": "MessageRejected", "Message": "rejected"}}, "SendEmail")
        self.assertEqual(app.notify(self.profile, self.changed_result()), "FAILED")
        record = self.notice()
        self.assertNotIn("message_id", record)
        self.assertEqual(record["last_message_id"], "ses-message-1")

    def test_recipient_connection_region_and_tenant_have_separate_state(self):
        self.assertEqual(app.notify(self.profile, self.result), "SENT")
        variants = [
            ({**self.profile, "notifications": {"enabled": True, "email": "other-verified@example.com"}}, self.result),
            ({**self.profile, "connection_version": "v2"}, self.result),
            ({**self.profile, "pk": "TENANT#bob"}, self.result),
            (self.profile, {**self.result, "region": "us-east-1"}),
        ]
        for profile, result in variants:
            with self.subTest(profile=profile, region=result["region"]):
                self.assertEqual(app.notify(profile, result), "SENT")
                self.assertEqual(app.notify(profile, result), "UNCHANGED")
        self.assertEqual(self.ses.send_email.call_count, 5)

    def test_default_off_sender_off_and_missing_verified_recipient(self):
        self.assertEqual(app.notify({**self.profile, "notifications": {"enabled": False}}, self.result), "DISABLED")
        with patch.dict(os.environ, SES_SENDER=""):
            self.assertEqual(app.notify(self.profile, self.result), "DISABLED")
        self.assertEqual(app.notify({**self.profile, "notifications": {"enabled": True}}, self.result), "DISABLED")
        self.ses.send_email.assert_not_called()

    def test_unverified_cognito_email_cannot_enable_notifications(self):
        app.put(self.profile)
        request = event("PUT", "/notifications", body={"enabled": True, "email": "attacker@example.com"})
        request["headers"] = {"authorization": "Bearer access-token"}
        self.client.return_value.get_user.return_value = {"UserAttributes": [
            {"Name": "email", "Value": "unverified@example.com"}, {"Name": "email_verified", "Value": "false"},
        ]}
        response = app.api(request, None)
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("Verify Cognito email", json.loads(response["body"])["error"])


if __name__ == "__main__":
    unittest.main()
