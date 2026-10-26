"""Scheduling and recovery contracts using Moto, never a deployed AWS stack."""
import copy
import json
import unittest
import uuid
from unittest.mock import MagicMock, patch

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws

from tests.test_api import app, event


def aws_error(code, operation="TransactWriteItems", **extra):
    return ClientError({"Error": {"Code": code, "Message": "private provider message"}, **extra}, operation)


class Task8(unittest.TestCase):
    def setUp(self):
        self.aws = mock_aws()
        self.aws.start()
        db = boto3.resource("dynamodb", region_name="ap-southeast-1")
        self.table = db.create_table(
            TableName="task8-test",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        self.addCleanup(self.aws.stop)
        self.addCleanup(patch.stopall)
        patch.object(app, "table", self.table).start()
        self.now = 1793000000
        patch.object(app.time, "time", return_value=self.now).start()
        self.profile = {
            "pk": "TENANT#alice", "sk": "PROFILE", "external_id": "private-external-id",
            "settings": app.config({}), "service_groups": list(app.SERVICE_GROUPS),
            "role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-test",
            "account_id": "123456789012", "regions": ["ap-southeast-1"], "connection_version": "v1",
        }
        app.put(self.profile)
        self.context = MagicMock()
        self.context.get_remaining_time_in_millis.return_value = 200000
        self.sess = patch.object(app, "session", return_value=MagicMock()).start()
        self.collect = patch.object(app, "collect_region", return_value={
            "counts": {}, "findings": [], "errors": [], "partial": False,
        }).start()
        self.invoke = patch.object(app.invoker, "invoke", return_value={"StatusCode": 202}).start()

    def marker(self, **overrides):
        item = {
            "pk": self.profile["pk"], "sk": "RESULT#ap-southeast-1", "region": "ap-southeast-1",
            "scan_id": str(uuid.uuid4()), "connection_version": "v1", "status": "QUEUED",
            "created_at": self.now, "started_at": self.now, "deadline_at": self.now + 900,
            "trigger": "manual", "attempt_count": 0,
        }
        item.update(overrides)
        app.put(item)
        return item

    def job(self, marker):
        return {key: marker[key] for key in ("pk", "region", "scan_id", "connection_version")}

    def row(self):
        return app.get(self.profile["pk"], "RESULT#ap-southeast-1")

    def histories(self):
        return list(app.all_items(self.profile["pk"], "HISTORY#"))

    def test_result_and_history_transaction_retries_without_losing_history(self):
        marker = self.marker()
        transaction = self.table.meta.client.transact_write_items

        def fail_result(**kwargs):
            if any(action.get("Put", {}).get("Item", {}).get("sk", "").startswith("HISTORY#") for action in kwargs["TransactItems"]):
                raise aws_error("ProvisionedThroughputExceededException")
            return transaction(**kwargs)

        with patch.object(self.table.meta.client, "transact_write_items", side_effect=fail_result):
            with self.assertRaises(ClientError):
                app.worker(self.job(marker), self.context)
        self.assertNotIn(self.row()["status"], ("SUCCEEDED", "PARTIAL"))
        self.assertEqual(self.histories(), [])
        app.worker(self.job(marker), self.context)
        app.worker(self.job(marker), self.context)
        self.assertEqual(self.row()["status"], "SUCCEEDED")
        self.assertEqual(len(self.histories()), 1)

    def test_terminal_race_cannot_reopen_result_or_read_target(self):
        marker = self.marker()
        transaction = self.table.meta.client.transact_write_items

        def completed_before_claim(**kwargs):
            if any(action.get("Update", {}).get("ExpressionAttributeValues", {}).get(":running") == "RUNNING" for action in kwargs["TransactItems"]):
                app.put({**marker, "status": "SUCCEEDED", "completed_at": self.now})
            return transaction(**kwargs)

        with patch.object(self.table.meta.client, "transact_write_items", side_effect=completed_before_claim):
            app.worker(self.job(marker), self.context)
        self.sess.assert_not_called()
        self.assertEqual(self.row()["status"], "SUCCEEDED")

    def test_revoked_role_has_atomic_history_timestamps_and_retention(self):
        marker = self.marker()
        self.sess.side_effect = aws_error("AccessDenied", "AssumeRole")
        app.worker(self.job(marker), self.context)
        result = self.row()
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["started_at"], self.now)
        self.assertGreater(result["expires"], self.now)
        self.assertEqual(len(self.histories()), 1)
        self.assertEqual(self.histories()[0]["scan_id"], marker["scan_id"])
        self.assertNotIn("private provider", json.dumps(result))

    def test_scheduler_isolates_invalid_profile_before_valid_tenant(self):
        bad = {**self.profile, "pk": "TENANT#invalid", "settings": {"interval_hours": 0}}
        pages = [{"Items": [bad, self.profile]}]
        with patch.object(self.table, "scan", side_effect=pages):
            result = app.scheduler({}, self.context)
        self.assertEqual(result["queued_tenants"], 1)
        self.assertEqual(self.invoke.call_count, 1)

    def test_admission_commits_lock_all_regions_and_clock_before_dispatch(self):
        self.profile["regions"] = ["ap-southeast-1", "us-east-1"]
        app.put(self.profile)

        def invoke(**kwargs):
            markers = list(app.all_items(self.profile["pk"], "RESULT#"))
            self.assertEqual(len(markers), 2)
            self.assertEqual({row["scan_id"] for row in markers}, {json.loads(kwargs["Payload"])["scan_id"]})
            self.assertEqual(app.get(self.profile["pk"], "PROFILE")["last_queued"], self.now)
            self.assertEqual(app.get(self.profile["pk"], "LOCK")["lease_until"], self.now + 930)
            return {"StatusCode": 202}

        self.invoke.side_effect = invoke
        scan_id = app.enqueue(self.profile, self.now)
        self.assertTrue(scan_id)
        self.assertIsNone(app.enqueue(self.profile, self.now, trigger="scheduled"))
        self.assertEqual(self.invoke.call_count, 2)

    def test_admission_transaction_failure_creates_no_orphan_or_dispatch(self):
        with patch.object(self.table.meta.client, "transact_write_items", side_effect=aws_error("TransactionConflictException")):
            with self.assertRaises(ClientError):
                app.enqueue(self.profile, self.now)
        self.assertEqual(self.row(), {})
        self.assertEqual(app.get(self.profile["pk"], "LOCK"), {})
        self.assertNotIn("last_queued", app.get(self.profile["pk"], "PROFILE"))
        self.invoke.assert_not_called()

    def test_scheduler_interval_boundaries_and_pagination(self):
        for interval in (1, 24):
            for offset in (-1, 0, 1):
                with self.subTest(interval=interval, offset=offset):
                    profile = {**self.profile, "pk": "TENANT#{}-{}".format(interval, offset),
                               "settings": app.config({"interval_hours": interval}),
                               "last_queued": self.now - interval * 3600 - offset}
                    app.put(profile)
                    pages = [{"Items": [{"pk": "TENANT#empty", "sk": "PROFILE"}],
                              "LastEvaluatedKey": {"pk": "TENANT#empty", "sk": "PROFILE"}}, {"Items": [profile]}]
                    with patch.object(self.table, "scan", side_effect=pages) as scan:
                        reply = app.scheduler({}, self.context)
                    self.assertEqual(reply["queued_tenants"], int(offset >= 0))
                    self.assertEqual(scan.call_args.kwargs["ExclusiveStartKey"]["sk"], "PROFILE")

    def test_legacy_profile_settings_are_normalized_without_blocking_schedule(self):
        old = {**self.profile, "settings": {"interval_hours": 6}}
        app.put(old)
        self.assertTrue(app.enqueue(app.normalize_profile(old), self.now, trigger="scheduled"))

    def test_stale_scheduler_profile_cannot_queue_after_reconnect_or_settings_change(self):
        for updated in ({"connection_version": "v2"}, {"settings": app.config({"interval_hours": 24})}):
            with self.subTest(updated=updated):
                app.put({**self.profile, **updated})
                self.assertIsNone(app.enqueue(self.profile, self.now, trigger="scheduled"))
        self.assertEqual(self.row(), {})
        self.invoke.assert_not_called()

    def test_dispatch_failure_is_terminal_with_history_and_other_region_runs(self):
        self.profile["regions"] = ["ap-southeast-1", "us-east-1"]
        app.put(self.profile)
        self.invoke.side_effect = [RuntimeError("private invoke details"), {"StatusCode": 202}]
        scan_id = app.enqueue(self.profile, self.now)
        self.assertEqual(self.row()["error_code"], "DISPATCH_FAILED")
        self.assertEqual(self.row()["status"], "FAILED")
        self.assertEqual(len(self.histories()), 1)
        second = app.get(self.profile["pk"], "RESULT#us-east-1")
        self.assertEqual(second["status"], "QUEUED")
        self.assertTrue(app.get(self.profile["pk"], "LOCK"))
        app.worker(self.job(second), self.context)
        self.assertEqual(app.get(self.profile["pk"], "LOCK"), {})
        self.assertEqual({r["scan_id"] for r in self.histories()}, {scan_id})

    def test_expired_marker_is_archived_before_replacement(self):
        old = self.marker(created_at=self.now - 1000, started_at=self.now - 1000, deadline_at=self.now - 100)
        scan_id = app.enqueue(self.profile, self.now)
        self.assertNotEqual(scan_id, old["scan_id"])
        self.assertEqual(self.histories()[0]["status"], "TIMED_OUT")
        self.assertEqual(self.histories()[0]["scan_id"], old["scan_id"])

    def test_valid_active_marker_blocks_admission_even_if_lock_expired(self):
        self.marker()
        app.put({"pk": self.profile["pk"], "sk": "LOCK", "lease_until": self.now - 1})
        self.assertIsNone(app.enqueue(self.profile, self.now))
        self.invoke.assert_not_called()

    def test_duplicate_active_lease_retries_and_exact_expiry_can_be_claimed(self):
        marker = self.marker(status="RUNNING", run_token="old", run_until=self.now + 1, attempt_count=1)
        with self.assertRaises(RuntimeError):
            app.worker(self.job(marker), self.context)
        self.sess.assert_not_called()
        marker["run_until"] = self.now
        app.put(marker)
        app.worker(self.job(marker), self.context)
        self.assertEqual(self.row()["status"], "SUCCEEDED")
        self.assertEqual(self.row()["attempt_count"], 2)

    def test_old_run_token_cannot_finalize_or_release_new_worker(self):
        marker = self.marker(status="RUNNING", run_token="new", run_until=self.now + 330)
        saved = app.finish_scan(marker, "FAILED", run_token="old")
        self.assertIsNone(saved)
        self.assertEqual(self.row()["run_token"], "new")
        self.assertEqual(self.histories(), [])

    def test_reconnect_during_scan_rejects_old_result_and_preserves_new_result(self):
        marker = self.marker()

        def collect(*args):
            app.put({**self.profile, "connection_version": "v2"})
            app.put({**marker, "connection_version": "v2", "scan_id": str(uuid.uuid4())})
            return {"counts": {}, "findings": [], "errors": [], "partial": False}

        self.collect.side_effect = collect
        app.worker(self.job(marker), self.context)
        self.assertEqual(self.row()["connection_version"], "v2")
        self.assertEqual(self.row()["status"], "QUEUED")
        self.assertNotIn("run_until", self.row())
        self.assertEqual(self.histories(), [])

    def test_connection_save_preserves_concurrently_queued_clock_and_settings(self):
        actual = MagicMock()
        actual.client.return_value.get_caller_identity.return_value = {"Account": "123456789012"}

        def assume(profile):
            app.put({**self.profile, "last_queued": self.now, "settings": app.config({"interval_hours": 24})})
            return actual

        self.sess.side_effect = assume
        reply = app.api(event("PUT", "/connection", body={"role_arn": self.profile["role_arn"], "regions": ["us-east-1"]}), None)
        self.assertEqual(reply["statusCode"], 200)
        profile = app.get(self.profile["pk"], "PROFILE")
        self.assertEqual(profile["last_queued"], self.now)
        self.assertEqual(profile["settings"]["interval_hours"], 24)
        self.assertEqual(profile["regions"], ["us-east-1"])

    def test_infrastructure_denied_is_retried_instead_of_claimed_success(self):
        marker = self.marker()
        with patch.object(self.table.meta.client, "transact_write_items", side_effect=aws_error("AccessDeniedException")):
            with self.assertRaises(ClientError):
                app.worker(self.job(marker), self.context)
        self.assertEqual(self.row()["status"], "QUEUED")
        self.assertEqual(self.histories(), [])

    def test_connection_race_at_claim_never_reads_the_old_account(self):
        marker = self.marker()
        transaction = self.table.meta.client.transact_write_items

        def reconnect(**kwargs):
            app.put({**self.profile, "connection_version": "v2"})
            return transaction(**kwargs)

        with patch.object(self.table.meta.client, "transact_write_items", side_effect=reconnect):
            app.worker(self.job(marker), self.context)
        self.sess.assert_not_called()
        self.collect.assert_not_called()
        self.assertEqual(self.row()["status"], "QUEUED")

    def test_budget_checked_before_sts_and_late_lease_is_capped_at_deadline(self):
        for seconds, lambda_ms in ((30, 200000), (900, 30000)):
            with self.subTest(seconds=seconds, lambda_ms=lambda_ms):
                marker = self.marker(deadline_at=self.now + seconds)
                self.context.get_remaining_time_in_millis.return_value = lambda_ms
                app.worker(self.job(marker), self.context)
                self.assertEqual(self.row()["status"], "TIMED_OUT")
                self.assertEqual(self.row()["error_code"], "TIME_BUDGET")
        self.sess.assert_not_called()
        marker = self.marker(deadline_at=self.now + 200)
        self.context.get_remaining_time_in_millis.return_value = 200000

        def collect(*args):
            self.assertEqual(self.row()["run_until"], self.now + 200)
            return {"counts": {}, "findings": [], "errors": [], "partial": False}

        self.collect.side_effect = collect
        app.worker(self.job(marker), self.context)
        self.assertEqual(self.row()["status"], "SUCCEEDED")

    def test_throttled_read_after_claim_releases_token_for_retry(self):
        marker = self.marker()
        get = app.get
        reads = 0

        def read(pk, sk):
            nonlocal reads
            if sk.startswith("RESULT#"):
                reads += 1
                if reads == 2:
                    raise aws_error("ProvisionedThroughputExceededException", "GetItem")
            return get(pk, sk)

        with patch.object(app, "get", side_effect=read):
            with self.assertRaises(ClientError):
                app.worker(self.job(marker), self.context)
        self.assertEqual(self.row()["run_until"], 0)
        app.worker(self.job(marker), self.context)
        self.assertEqual(self.row()["status"], "SUCCEEDED")

    def test_email_failure_keeps_committed_history_and_does_not_rescan(self):
        marker = self.marker()
        with patch.object(app, "notify", side_effect=RuntimeError("private email details")):
            app.worker(self.job(marker), self.context)
        app.worker(self.job(marker), self.context)
        self.assertEqual(self.row()["status"], "SUCCEEDED")
        self.assertEqual(len(self.histories()), 1)
        self.assertEqual(self.collect.call_count, 1)

    def envelope(self, marker, condition="RetriesExhausted", **overrides):
        value = {"requestPayload": self.job(marker),
                 "requestContext": {"condition": condition, "approximateInvokeCount": 3}, **overrides}
        return {"messageId": str(uuid.uuid4()), "body": json.dumps(value)}

    def test_failure_batch_handles_duplicate_old_invalid_and_expired_records(self):
        marker = self.marker()
        valid = self.envelope(marker)
        malformed = {"messageId": "bad", "body": "not json"}
        reply = app.recovery({"Records": [valid, valid, malformed]}, self.context)
        self.assertEqual(reply, {"batchItemFailures": [{"itemIdentifier": "bad"}]})
        self.assertEqual(self.row()["status"], "FAILED")
        self.assertEqual(self.row()["attempt_count"], 3)
        self.assertEqual(len(self.histories()), 1)
        next_marker = self.marker()
        app.recovery({"Records": [valid]}, self.context)
        self.assertEqual(self.row(), next_marker)
        app.recovery({"Records": [self.envelope(next_marker, "EventAgeExceeded")]}, self.context)
        self.assertEqual(self.row()["status"], "TIMED_OUT")

    def test_recovery_waits_for_valid_lease_and_retries_persistence_errors(self):
        marker = self.marker(status="RUNNING", run_until=self.now + 1)
        record = self.envelope(marker)
        reply = app.recovery({"Records": [record]}, self.context)
        self.assertEqual(reply["batchItemFailures"], [{"itemIdentifier": record["messageId"]}])
        self.assertEqual(self.histories(), [])
        marker["run_until"] = self.now
        app.put(marker)
        with patch.object(self.table.meta.client, "transact_write_items", side_effect=aws_error("TransactionCanceledException", CancellationReasons=[{"Code": "TransactionConflict"}])):
            reply = app.recovery({"Records": [record]}, self.context)
        self.assertEqual(len(reply["batchItemFailures"]), 1)
        self.assertEqual(self.row()["status"], "RUNNING")
        self.assertEqual(app.recovery({"Records": [record]}, self.context)["batchItemFailures"], [])
        self.assertEqual(self.row()["status"], "FAILED")

    def test_recovery_race_with_lease_is_not_acknowledged(self):
        marker = self.marker()
        transaction = self.table.meta.client.transact_write_items

        def claim(**kwargs):
            app.put({**marker, "status": "RUNNING", "run_token": "racer", "run_until": self.now + 330})
            return transaction(**kwargs)

        record = self.envelope(marker)
        with patch.object(self.table.meta.client, "transact_write_items", side_effect=claim):
            reply = app.recovery({"Records": [record]}, self.context)
        self.assertEqual(len(reply["batchItemFailures"]), 1)
        self.assertEqual(self.row()["status"], "RUNNING")

    def test_reconciler_finalizes_undispatched_job_once_with_pagination(self):
        marker = self.marker(deadline_at=self.now)
        with patch.object(self.table, "scan", side_effect=[
            {"Items": [], "LastEvaluatedKey": {"pk": "x", "sk": "x"}}, {"Items": [marker]},
        ]) as scan:
            self.assertEqual(app.reconcile({}, self.context)["timed_out_regions"], 1)
            self.assertIn("ExclusiveStartKey", scan.call_args.kwargs)
        self.assertEqual(app.reconcile({}, self.context)["timed_out_regions"], 0)
        self.assertEqual(self.row()["status"], "TIMED_OUT")
        self.assertEqual(len(self.histories()), 1)
        self.sess.assert_not_called()

    def test_deadline_worker_stops_before_assume_role_and_terminal_replay_is_safe(self):
        marker = self.marker(deadline_at=self.now)
        app.worker(self.job(marker), self.context)
        app.worker(self.job(marker), self.context)
        self.assertEqual(self.row()["status"], "TIMED_OUT")
        self.assertEqual(len(self.histories()), 1)
        self.sess.assert_not_called()

    def test_scheduler_infrastructure_failure_processes_remaining_tenants_then_retries(self):
        other = {**self.profile, "pk": "TENANT#bob"}
        app.put(other)
        real_enqueue = app.enqueue

        def enqueue(profile, *args, **kwargs):
            if profile["pk"] == self.profile["pk"]:
                raise aws_error("ProvisionedThroughputExceededException")
            return real_enqueue(profile, *args, **kwargs)

        with patch.object(self.table, "scan", return_value={"Items": [self.profile, other]}), patch.object(app, "enqueue", side_effect=enqueue):
            with self.assertRaises(RuntimeError):
                app.scheduler({}, self.context)
        self.assertEqual(self.invoke.call_count, 1)
        self.assertEqual(app.get(other["pk"], "RESULT#ap-southeast-1")["status"], "QUEUED")

    def test_api_prioritizes_active_job_then_cooldown_and_tenant_boundary(self):
        scan_id = app.enqueue(self.profile, self.now)
        self.assertEqual(app.api(event("POST", "/scans"), None)["statusCode"], 409)
        app.worker(self.job(self.row()), self.context)
        self.assertEqual(app.api(event("POST", "/scans"), None)["statusCode"], 429)
        self.assertEqual(app.api(event("GET", "/scans/" + scan_id, user="bob"), None)["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
