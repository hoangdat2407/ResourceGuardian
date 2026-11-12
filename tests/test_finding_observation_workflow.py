"""Worker/API finding timestamps using Moto; account collectors remain mocked."""
import copy
import json
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws

from tests.test_api import app, event


def provider_error(code, operation="TransactWriteItems"):
    return ClientError({"Error": {"Code": code, "Message": "mock provider fault"}}, operation)


class FindingObservationWorkflow(unittest.TestCase):
    def setUp(self):
        aws = mock_aws()
        aws.start()
        self.addCleanup(aws.stop)
        self.table = boto3.resource("dynamodb", region_name="ap-southeast-1").create_table(
            TableName="finding-observation-workflow",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        self.now = 1793000000
        self.profile = {
            "pk": "TENANT#alice", "sk": "PROFILE", "regions": ["ap-southeast-1"],
            "connection_version": "v1", "external_id": "test-external-id",
            "role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-test",
            "account_id": "123456789012", "settings": app.config({}),
            "service_groups": list(app.SERVICE_GROUPS), "notifications": {"enabled": False},
        }
        self.clock = self.start_patch(app.time, "time", return_value=self.now)
        self.start_patch(app.time, "sleep", return_value=None)
        self.start_patch(app, "table", self.table)
        self.session = self.start_patch(app, "session", return_value=MagicMock())
        self.collect = self.start_patch(app, "collect_region")
        self.notify = self.start_patch(app, "notify", return_value="DISABLED")
        self.context = MagicMock()
        self.context.get_remaining_time_in_millis.return_value = 200000
        app.put(self.profile)

    def start_patch(self, target, name, *args, **kwargs):
        patcher = patch.object(target, name, *args, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    @staticmethod
    def iso(stamp):
        return datetime.fromtimestamp(stamp, timezone.utc).isoformat()

    def finding(self, ident=1, *, observed=None, region="ap-southeast-1", kind="EC2", level="REVIEW"):
        observed = int(self.clock.return_value) if observed is None else observed
        return {
            "finding_id": format(ident, "064x"), "type": kind, "resource_id": "resource-" + str(ident),
            "region": region, "account_id": "123456789012", "evaluated_at": self.iso(observed),
            "level": level, "rule_id": kind + "_TEST_RULE", "reason": "Test evidence",
            "recommendation": "Review with the resource owner", "evidence": {"test_metric": 0},
        }

    def new_job(self, *, at=None, profile=None, region=None, legacy=False):
        if at is not None:
            self.clock.return_value = at
        now = int(self.clock.return_value)
        profile = profile or self.profile
        region = region or profile["regions"][0]
        app.put(profile)
        marker = {
            "pk": profile["pk"], "sk": "RESULT#" + region, "region": region,
            "scan_id": str(uuid.uuid4()), "connection_version": profile["connection_version"],
            "status": "QUEUED", "created_at": now, "started_at": now,
            "deadline_at": now + app.JOB_SECONDS, "trigger": "manual", "attempt_count": 0,
        }
        if legacy:
            marker.pop("deadline_at")
        app.put(marker)
        return {key: marker[key] for key in ("pk", "region", "scan_id", "connection_version")}

    def process(self, job, findings, *, partial=False, errors=None, remaining_after_collection=None):
        counts = {}
        for finding in findings:
            counts[finding["type"]] = counts.get(finding["type"], 0) + 1
        collected = {"findings": findings, "counts": counts, "errors": errors or [], "partial": partial}

        def collect(*args, **kwargs):
            if remaining_after_collection is not None:
                self.context.get_remaining_time_in_millis.return_value = remaining_after_collection
            return collected

        self.collect.side_effect = collect
        app.worker(job, self.context)
        return app.get(job["pk"], "RESULT#" + job["region"])

    def scan(self, findings, *, at=None, profile=None, region=None, **kwargs):
        job = self.new_job(at=at, profile=profile, region=region)
        return self.process(job, findings, **kwargs)

    def registry(self, finding, profile=None):
        profile = profile or self.profile
        sk = "OBSF#{}#{}#{}".format(profile["connection_version"], finding["region"], finding["finding_id"])
        return app.get(profile["pk"], sk)

    def histories(self, pk=None):
        return list(app.all_items(pk or self.profile["pk"], "HISTORY#"))

    def history_for(self, scan_id, pk=None):
        return next(row for row in self.histories(pk) if row["scan_id"] == scan_id)

    def api(self, method, path, *, user="alice", body=None):
        reply = app.api(event(method, path, user=user, body=body), None)
        return reply["statusCode"], json.loads(reply["body"])

    def assert_times(self, finding, first, last):
        self.assertEqual(finding["first_seen_at"], self.iso(first))
        self.assertEqual(finding["last_seen_at"], self.iso(last))

    def test_all_nine_types_keep_first_across_scans_and_public_snapshots_match(self):
        kinds = ["EC2", "EBS", "EIP", "SNAPSHOT", "S3_MULTIPART", "RDS", "NAT_GATEWAY", "ALB", "NLB"]
        first_input = [self.finding(i, kind=kind, level="OBSERVING" if kind == "EBS" else "REVIEW")
                       for i, kind in enumerate(kinds)]
        original = copy.deepcopy(first_input)
        first = self.scan(first_input)
        self.assertEqual(first["status"], "SUCCEEDED")
        first_history = self.history_for(first["scan_id"])
        second_input = [self.finding(i, kind=kind, observed=self.now + 120) for i, kind in enumerate(kinds)]
        second = self.scan(second_input, at=self.now + 120)
        self.assertEqual(first_input, original)
        self.assertNotIn("first_seen_at", second_input[0])
        for finding in first["findings"]:
            self.assert_times(finding, self.now, self.now)
        for finding in second["findings"]:
            self.assert_times(finding, self.now, self.now + 120)
        self.assertEqual(next(item for item in second["findings"] if item["type"] == "EBS")["level"], "REVIEW")
        for path in ("/findings", "/scans/" + second["scan_id"], "/history"):
            with self.subTest(path=path):
                status, body = self.api("GET", path)
                self.assertEqual(status, 200)
                selected = next(row for row in body["results"] if row["scan_id"] == second["scan_id"])
                self.assertEqual(selected["findings"], second["findings"])
                self.assertTrue(all("candidates" not in row for row in body["results"]))
                self.assertNotIn("OBSF#", json.dumps(body))
        self.assertEqual(self.history_for(first["scan_id"]), first_history)

    def test_absence_failed_scan_and_partial_scan_preserve_first_until_thirty_days_without_observation(self):
        finding = self.finding()
        self.scan([finding])
        before = self.registry(finding)
        absent = self.scan([], at=self.now + 86400)
        self.assertEqual(absent["status"], "SUCCEEDED")
        self.assertEqual(self.registry(finding), before)
        self.session.side_effect = provider_error("AccessDenied", "AssumeRole")
        failed = self.scan([], at=self.now + 2 * 86400)
        self.assertEqual(failed["status"], "FAILED")
        self.assertEqual(self.registry(finding), before)
        self.session.side_effect = None
        observed = self.now + 3 * 86400
        partial = self.scan([self.finding(observed=observed)], at=observed, partial=True,
                            errors=[{"type": "RDS", "code": "AccessDenied"}])
        self.assertEqual(partial["status"], "PARTIAL")
        self.assert_times(partial["findings"][0], self.now, observed)
        expires = observed + app.RETENTION_SECONDS
        self.assertEqual(self.registry(finding)["expires"], expires)
        self.assertTrue(self.registry(finding))
        returned = self.scan([self.finding(observed=expires)], at=expires)
        self.assert_times(returned["findings"][0], expires, expires)

    def test_feedback_keep_and_ignore_update_registry_and_restore_timestamped_candidate(self):
        finding = self.finding()
        self.scan([finding])
        identity = {"region": finding["region"], "finding_id": finding["finding_id"]}
        self.assertEqual(self.api("PUT", "/feedback", body={**identity, "kept": True})[0], 200)
        kept = self.scan([self.finding(observed=self.now + 100)], at=self.now + 100)
        self.assertEqual(kept["findings"], [])
        self.assert_times(kept["candidates"][0], self.now, self.now + 100)
        kept_history = self.history_for(kept["scan_id"])
        self.assertEqual(self.registry(finding)["last_seen_at"], self.now + 100)
        self.assertEqual(self.api("PUT", "/feedback", body={**identity, "kept": False})[0], 200)
        restored = self.api("GET", "/findings")[1]["results"][0]["findings"][0]
        self.assert_times(restored, self.now, self.now + 100)
        until = self.iso(self.now + 500).replace("+00:00", "Z")
        self.assertEqual(self.api("PUT", "/feedback", body={**identity, "ignoreUntil": until})[0], 200)
        ignored = self.scan([self.finding(observed=self.now + 200)], at=self.now + 200)
        self.assertEqual(ignored["findings"], [])
        self.assertEqual(self.registry(finding)["last_seen_at"], self.now + 200)
        self.clock.return_value = self.now + 500
        restored = self.api("GET", "/findings")[1]["results"][0]["findings"][0]
        self.assert_times(restored, self.now, self.now + 200)
        self.assertEqual(self.history_for(kept["scan_id"]), kept_history)

    def test_legacy_resource_keep_and_ignore_are_applied_after_registry_updates(self):
        kept, ignored = self.finding(1), self.finding(2)
        for path, finding, extra in (("/keep", kept, {"enabled": True}), ("/ignore", ignored, {"days": 1})):
            self.assertEqual(self.api("PUT", path, body={"region": finding["region"],
                                                         "resource_id": finding["resource_id"], **extra})[0], 200)
        first = self.scan([kept, ignored])
        self.assertEqual(first["findings"], [])
        second = self.scan([self.finding(1, observed=self.now + 100), self.finding(2, observed=self.now + 100)],
                           at=self.now + 100)
        self.assertEqual(second["candidates"], [])
        for finding in (kept, ignored):
            self.assertEqual(self.registry(finding)["first_seen_at"], self.now)
            self.assertEqual(self.registry(finding)["last_seen_at"], self.now + 100)
        self.api("PUT", "/keep", body={"region": kept["region"], "resource_id": kept["resource_id"], "enabled": False})
        later = self.now + 86401
        returned = self.scan([self.finding(1, observed=later), self.finding(2, observed=later)], at=later)
        self.assertEqual(len(returned["findings"]), 2)
        for finding in returned["findings"]:
            self.assert_times(finding, self.now, later)

    def test_reconnect_tenant_and_region_isolate_observations_and_old_scan_access(self):
        finding = self.finding()
        original_scan = self.scan([finding])
        original_registry = self.registry(finding)
        connected = {**self.profile, "connection_version": "v2"}
        reconnected = self.scan([self.finding(observed=self.now + 100)], at=self.now + 100, profile=connected)
        self.assert_times(reconnected["findings"][0], self.now + 100, self.now + 100)
        self.assertEqual(self.api("GET", "/scans/" + original_scan["scan_id"])[0], 404)
        bob = {**self.profile, "pk": "TENANT#bob"}
        separate_tenant = self.scan([self.finding(observed=self.now + 200)], at=self.now + 200, profile=bob)
        self.assert_times(separate_tenant["findings"][0], self.now + 200, self.now + 200)
        self.assertEqual(self.api("GET", "/scans/" + original_scan["scan_id"], user="bob")[0], 404)
        other_region = {**self.profile, "regions": ["us-east-1"]}
        regional = self.scan([self.finding(observed=self.now + 300, region="us-east-1")],
                             at=self.now + 300, profile=other_region)
        self.assert_times(regional["findings"][0], self.now + 300, self.now + 300)
        self.assertEqual(self.registry(finding), original_registry)

    def test_none_from_registry_ownership_loss_stops_without_terminal_history_or_notification(self):
        job = self.new_job()

        def lost(marker, findings, time_check):
            app.put({**app.get(job["pk"], "RESULT#" + job["region"]), "run_token": "new-owner-token"})
            return None

        with patch.object(app, "record_finding_observations", side_effect=lost):
            row = self.process(job, [self.finding()])
        self.assertEqual(row["status"], "RUNNING")
        self.assertEqual(row["run_token"], "new-owner-token")
        self.assertGreater(row["run_until"], self.now)
        self.assertEqual(self.histories(), [])
        self.assertEqual(list(app.all_items(job["pk"], "OBSF#")), [])
        self.notify.assert_not_called()

    def test_partial_registry_commit_is_retried_without_losing_observed_first(self):
        job = self.new_job()
        findings = [self.finding(i) for i in range(120)]
        client = self.table.meta.client
        actual_write = client.transact_write_items
        registry_writes = 0

        def fail_second_registry_batch(**kwargs):
            nonlocal registry_writes
            if any(action.get("Put", {}).get("Item", {}).get("sk", "").startswith("OBSF#")
                   for action in kwargs["TransactItems"]):
                registry_writes += 1
                if registry_writes == 2:
                    raise provider_error("ProvisionedThroughputExceededException")
            return actual_write(**kwargs)

        with patch.object(client, "transact_write_items", side_effect=fail_second_registry_batch):
            with self.assertRaises(ClientError):
                self.process(job, findings)
        self.assertEqual(len(list(app.all_items(job["pk"], "OBSF#"))), 98)
        self.assertEqual(self.histories(), [])
        self.assertEqual(app.get(job["pk"], "RESULT#" + job["region"])["status"], "RUNNING")
        self.notify.assert_not_called()
        self.clock.return_value = self.now + 10
        row = self.process(job, [self.finding(i, observed=self.now + 10) for i in range(120)])
        self.assertEqual(row["status"], "PARTIAL")
        self.assertEqual(len(list(app.all_items(job["pk"], "OBSF#"))), 120)
        for i in range(120):
            registry = self.registry(self.finding(i))
            self.assertEqual(registry["first_seen_at"], self.now if i < 98 else self.now + 10)
            self.assertEqual(registry["last_seen_at"], self.now + 10)
        self.assertEqual(len(self.histories()), 1)

    def test_terminal_commit_failure_retries_with_first_from_prior_registry_commit(self):
        job = self.new_job()
        finding = self.finding()
        client = self.table.meta.client
        actual_write = client.transact_write_items

        def fail_terminal(**kwargs):
            if any(action.get("Put", {}).get("Item", {}).get("sk", "").startswith("HISTORY#")
                   for action in kwargs["TransactItems"]):
                raise provider_error("ProvisionedThroughputExceededException")
            return actual_write(**kwargs)

        with patch.object(client, "transact_write_items", side_effect=fail_terminal):
            with self.assertRaises(ClientError):
                self.process(job, [finding])
        self.assertEqual(self.registry(finding)["first_seen_at"], self.now)
        self.assertEqual(self.histories(), [])
        self.notify.assert_not_called()
        self.clock.return_value = self.now + 10
        row = self.process(job, [self.finding(observed=self.now + 10)])
        self.assertEqual(row["status"], "SUCCEEDED")
        self.assert_times(row["findings"][0], self.now, self.now + 10)
        self.assertEqual(len(self.histories()), 1)
        collections = self.collect.call_count
        self.clock.return_value = self.now + 20
        app.worker(job, self.context)
        self.assertEqual(self.collect.call_count, collections)
        self.assertEqual(self.registry(finding)["last_seen_at"], self.now + 10)

    def test_unprocessed_registry_keys_cannot_publish_success_or_unstamped_findings(self):
        job = self.new_job()

        def unprocessed(**kwargs):
            return {"Responses": {self.table.name: []}, "UnprocessedKeys": copy.deepcopy(kwargs["RequestItems"])}

        with patch.object(self.table.meta.client, "batch_get_item", side_effect=unprocessed) as read:
            with self.assertRaises(ClientError) as error:
                self.process(job, [self.finding()])
        self.assertEqual(error.exception.response["Error"]["Code"], "ProvisionedThroughputExceededException")
        self.assertEqual(read.call_count, 3)
        self.assertEqual(self.histories(), [])
        self.assertEqual(self.api("GET", "/scans/" + job["scan_id"])[1]["results"][0]["status"], "RUNNING")
        self.assertEqual(list(app.all_items(job["pk"], "OBSF#")), [])
        self.notify.assert_not_called()

    def test_partial_collection_with_fifty_nine_seconds_remaining_persists_timestamped_result(self):
        result = self.scan([self.finding()], partial=True,
                           errors=[{"type": "RDS", "code": "TIME_BUDGET"}], remaining_after_collection=59000)
        self.assertEqual(result["status"], "PARTIAL")
        self.assert_times(result["findings"][0], self.now, self.now)
        self.assertEqual(self.history_for(result["scan_id"])["findings"], result["findings"])
        self.assertEqual(self.registry(self.finding())["last_seen_at"], self.now)

    def test_nine_seconds_after_collection_finishes_timeout_atomically_without_unstamped_findings(self):
        with patch.object(self.table.meta.client, "batch_get_item", wraps=self.table.meta.client.batch_get_item) as read:
            result = self.scan([self.finding()], remaining_after_collection=9000)
        self.assertEqual(result["status"], "TIMED_OUT")
        self.assertEqual(result["error_code"], "TIME_BUDGET")
        self.assertEqual(result["findings"], [])
        history = self.history_for(result["scan_id"])
        self.assertEqual(history["status"], "TIMED_OUT")
        self.assertEqual(history["findings"], [])
        read.assert_not_called()
        self.assertEqual(list(app.all_items(self.profile["pk"], "OBSF#")), [])
        self.notify.assert_not_called()

    def test_existing_history_without_timestamps_is_not_backfilled_or_rewritten(self):
        old_id = str(uuid.uuid4())
        old = {"pk": self.profile["pk"], "sk": "HISTORY#{}#ap-southeast-1#{}".format(self.now - 100, old_id),
               "region": "ap-southeast-1", "scan_id": old_id, "connection_version": "v1",
               "status": "SUCCEEDED", "findings": [self.finding(observed=self.now - 100)],
               "expires": self.now + app.RETENTION_SECONDS}
        app.put(old)
        result = self.scan([self.finding()])
        self.assert_times(result["findings"][0], self.now, self.now)
        self.assertEqual(app.get(old["pk"], old["sk"]), old)
        status, body = self.api("GET", "/scans/" + old_id)
        self.assertEqual(status, 200)
        self.assertNotIn("first_seen_at", body["results"][0]["findings"][0])
        status, body = self.api("GET", "/history")
        self.assertEqual(status, 200)
        self.assertEqual(next(row for row in body["results"] if row["scan_id"] == old_id), old)

    def test_pruned_candidates_are_observed_before_cap_and_retain_first_when_they_return(self):
        result = self.scan([self.finding(i) for i in range(120)])
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(len(result["findings"]), app.FINDING_LIMIT)
        self.assertEqual(len(result["candidates"]), app.CANDIDATE_LIMIT)
        self.assertEqual(len(list(app.all_items(self.profile["pk"], "OBSF#"))), 120)
        pruned = self.finding(119)
        self.assertNotIn(pruned["finding_id"], {item["finding_id"] for item in result["candidates"]})
        returned = self.scan([self.finding(119, observed=self.now + 100)], at=self.now + 100)
        self.assert_times(returned["findings"][0], self.now, self.now + 100)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode("utf-8")), app.RESULT_BYTE_LIMIT)

    def test_legacy_marker_deadline_is_anchored_during_claim_and_never_extended_by_retry(self):
        job = self.new_job(legacy=True)
        self.session.side_effect = provider_error("InternalServerError", "AssumeRole")
        with self.assertRaises(ClientError):
            self.process(job, [self.finding()])
        before = app.get(job["pk"], "RESULT#" + job["region"])
        self.assertEqual(before["deadline_at"], self.now + app.JOB_SECONDS)
        self.session.side_effect = None
        self.clock.return_value = self.now + 100
        result = self.process(job, [self.finding(observed=self.now + 100)])
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["deadline_at"], before["deadline_at"])
        self.assert_times(result["findings"][0], self.now + 100, self.now + 100)


if __name__ == "__main__":
    unittest.main()
