"""Finding observation retention against Moto; no target-account AWS reads."""
import copy
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws

from tests.test_api import app


def provider_error(code, operation="TransactWriteItems"):
    return ClientError({"Error": {"Code": code, "Message": "test provider fault"}}, operation)


class FindingObservations(unittest.TestCase):
    def setUp(self):
        self.aws = mock_aws()
        self.aws.start()
        self.addCleanup(self.aws.stop)
        self.table = boto3.resource("dynamodb", region_name="ap-southeast-1").create_table(
            TableName="finding-observations-test",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table_patch = patch.object(app, "table", self.table)
        table_patch.start()
        self.addCleanup(table_patch.stop)
        self.now = 1793000000
        clock_patch = patch.object(app.time, "time", return_value=self.now)
        self.clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)
        sleep_patch = patch.object(app.time, "sleep", return_value=None)
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)
        self.active = self.marker()
        self.budget = MagicMock()

    def marker(self, **overrides):
        marker = {
            "pk": "TENANT#alice", "sk": "RESULT#ap-southeast-1", "region": "ap-southeast-1",
            "scan_id": str(uuid.uuid4()), "connection_version": "v1", "status": "RUNNING",
            "created_at": self.now, "started_at": self.now, "run_token": str(uuid.uuid4()),
            "run_until": self.now + 330, "deadline_at": self.now + 900,
        }
        marker.update(overrides)
        marker["sk"] = "RESULT#" + marker["region"]
        app.put({"pk": marker["pk"], "sk": "PROFILE", "regions": [marker["region"]],
                 "connection_version": marker["connection_version"]})
        app.put(marker)
        return marker

    def finding(self, ident=1, observed=None, region="ap-southeast-1"):
        observed = self.now if observed is None else observed
        return {"finding_id": format(ident, "064x"), "region": region,
                "evaluated_at": datetime.fromtimestamp(observed, timezone.utc).isoformat(),
                "type": "EC2", "resource_id": "i-test", "level": "REVIEW", "evidence": {"cpu_p95": 0}}

    def key(self, finding, marker=None):
        marker = marker or self.active
        return {"pk": marker["pk"],
                "sk": "OBSF#{}#{}#{}".format(marker["connection_version"], marker["region"], finding["finding_id"])}

    def seed(self, finding, first, last, marker=None):
        row = {**self.key(finding, marker), "first_seen_at": first, "last_seen_at": last,
               "expires": last + app.RETENTION_SECONDS}
        app.put(row)
        return row

    def stored(self, finding, marker=None):
        key = self.key(finding, marker)
        return app.get(key["pk"], key["sk"])

    def registry_rows(self):
        return [app.normalized(row) for row in self.table.scan()["Items"] if row["sk"].startswith("OBSF#")]

    def record(self, findings, marker=None, time_check=None):
        return app.record_finding_observations(marker or self.active, findings, time_check or self.budget)

    def test_first_observation_and_replay_are_idempotent_without_input_mutation(self):
        findings = [self.finding()]
        original = copy.deepcopy(findings)
        expected = {findings[0]["finding_id"]: {"first_seen_at": self.now, "last_seen_at": self.now}}
        self.assertEqual(self.record(findings), expected)
        stored = self.stored(findings[0])
        self.assertEqual(stored["expires"], self.now + app.RETENTION_SECONDS)
        self.assertEqual(self.record(findings), expected)
        self.assertEqual(self.stored(findings[0]), stored)
        self.assertEqual(findings, original)

    def test_returning_finding_keeps_first_and_extends_expiry_from_actual_observation(self):
        finding = self.finding()
        first, last = self.now - 40 * 86400, self.now - 29 * 86400
        self.seed(finding, first, last)
        self.assertEqual(self.record([finding])[finding["finding_id"]],
                         {"first_seen_at": first, "last_seen_at": self.now})
        self.assertEqual(self.stored(finding)["expires"], self.now + app.RETENTION_SECONDS)

    def test_exact_thirty_day_expiry_resets_even_when_ttl_has_not_deleted_item(self):
        finding = self.finding()
        self.seed(finding, self.now - app.RETENTION_SECONDS - 100, self.now - app.RETENTION_SECONDS)
        self.assertTrue(self.stored(finding))
        self.assertEqual(self.record([finding])[finding["finding_id"]],
                         {"first_seen_at": self.now, "last_seen_at": self.now})

    def test_older_observation_never_moves_last_or_expiry_backwards(self):
        finding = self.finding(observed=self.now - 100)
        first, last = self.now - 200, self.now - 50
        before = self.seed(finding, first, last)
        self.assertEqual(self.record([finding])[finding["finding_id"]],
                         {"first_seen_at": first, "last_seen_at": last})
        self.assertEqual(self.stored(finding), before)

    def test_no_findings_do_not_read_write_or_refresh_existing_observation(self):
        finding = self.finding()
        before = self.seed(finding, self.now - 1000, self.now - 500)
        with patch.object(self.table.meta.client, "batch_get_item") as read, \
                patch.object(self.table.meta.client, "transact_write_items") as write:
            self.assertEqual(self.record([]), {})
        read.assert_not_called()
        write.assert_not_called()
        self.assertEqual(self.stored(finding), before)

    def test_tenant_connection_and_region_have_independent_first_observations(self):
        finding = self.finding()
        before = self.seed(finding, self.now - 1000, self.now - 500)
        cases = [{"pk": "TENANT#bob"}, {"connection_version": "v2"}, {"region": "us-east-1"}]
        for changes in cases:
            with self.subTest(changes=changes):
                marker = self.marker(**changes)
                item = self.finding(region=marker["region"])
                self.assertEqual(self.record([item], marker)[item["finding_id"]],
                                 {"first_seen_at": self.now, "last_seen_at": self.now})
        self.assertEqual(self.stored(finding), before)

    def test_duplicate_ids_use_latest_observation_and_large_scan_is_bounded_per_request(self):
        findings = [self.finding(i, observed=self.now - 20) for i in range(205)]
        findings += [self.finding(1, observed=self.now - 30), self.finding(1, observed=self.now - 5)]
        original = copy.deepcopy(findings)
        client = self.table.meta.client
        with patch.object(client, "batch_get_item", wraps=client.batch_get_item) as reads, \
                patch.object(client, "transact_write_items", wraps=client.transact_write_items) as writes:
            result = self.record(findings)
        self.assertEqual(len(result), 205)
        self.assertEqual(result[self.finding(1)["finding_id"]]["last_seen_at"], self.now - 5)
        self.assertEqual(findings, original)
        self.assertGreaterEqual(reads.call_count, 3)
        self.assertGreaterEqual(writes.call_count, 3)
        written_ids = []
        for call in reads.call_args_list:
            request = call.kwargs["RequestItems"][self.table.name]
            self.assertTrue(request["ConsistentRead"])
            self.assertLessEqual(len(request["Keys"]), 100)
        for call in writes.call_args_list:
            actions = call.kwargs["TransactItems"]
            mutations = [action for action in actions if "Put" in action or "Update" in action]
            checks = [action["ConditionCheck"] for action in actions if "ConditionCheck" in action]
            self.assertLessEqual(len(actions), 100)
            self.assertLessEqual(len(mutations), 98)
            self.assertEqual(len(checks), 2)
            self.assertEqual({item["Key"]["sk"] for item in checks}, {self.active["sk"], "PROFILE"})
            written_ids.extend(action["Put"]["Item"]["sk"] if "Put" in action else action["Update"]["Key"]["sk"]
                               for action in mutations)
        self.assertEqual(len(written_ids), len(set(written_ids)))
        self.assertEqual(len(written_ids), 205)

    def test_unprocessed_keys_are_retried_without_resetting_the_unread_first(self):
        first, second = self.finding(1), self.finding(2)
        row1 = self.seed(first, self.now - 1000, self.now - 500)
        row2 = self.seed(second, self.now - 2000, self.now - 1000)
        client = self.table.meta.client
        actual_read = client.batch_get_item
        attempts = []

        def read(**kwargs):
            attempts.append(copy.deepcopy(kwargs))
            if len(attempts) == 1:
                return {"Responses": {self.table.name: [row1]},
                        "UnprocessedKeys": {self.table.name: {"Keys": [self.key(second)], "ConsistentRead": True}}}
            return actual_read(**kwargs)

        with patch.object(client, "batch_get_item", side_effect=read):
            result = self.record([first, second])
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[1]["RequestItems"][self.table.name]["Keys"], [self.key(second)])
        self.assertTrue(attempts[1]["RequestItems"][self.table.name]["ConsistentRead"])
        self.assertEqual(result[first["finding_id"]]["first_seen_at"], row1["first_seen_at"])
        self.assertEqual(result[second["finding_id"]]["first_seen_at"], row2["first_seen_at"])

    def test_exhausted_unprocessed_keys_raise_after_three_attempts_without_any_writes(self):
        finding = self.finding()
        before = self.seed(finding, self.now - 1000, self.now - 500)
        reply = {"Responses": {self.table.name: []},
                 "UnprocessedKeys": {self.table.name: {"Keys": [self.key(finding)], "ConsistentRead": True}}}
        with patch.object(self.table.meta.client, "batch_get_item", side_effect=lambda **kwargs: copy.deepcopy(reply)) as read, \
                patch.object(self.table.meta.client, "transact_write_items") as write:
            with self.assertRaises(ClientError) as error:
                self.record([finding])
        self.assertEqual(error.exception.response["Error"]["Code"], "ProvisionedThroughputExceededException")
        self.assertEqual(read.call_count, 3)
        write.assert_not_called()
        self.assertEqual(self.stored(finding), before)

    def test_later_read_batch_failure_cannot_leave_early_observation_writes(self):
        client = self.table.meta.client
        actual_read = client.batch_get_item
        requests = 0

        def read(**kwargs):
            nonlocal requests
            requests += 1
            if requests == 2:
                raise provider_error("InternalServerError", "BatchGetItem")
            return actual_read(**kwargs)

        with patch.object(client, "batch_get_item", side_effect=read), \
                patch.object(client, "transact_write_items") as write:
            with self.assertRaises(ClientError):
                self.record([self.finding(i) for i in range(120)])
        write.assert_not_called()
        self.assertEqual(self.registry_rows(), [])

    def test_malformed_batch_response_is_not_treated_as_missing_registry_data(self):
        finding = self.finding()
        before = self.seed(finding, self.now - 1000, self.now - 500)
        unknown = {**before, "sk": self.key(self.finding(999))["sk"]}
        replies = [
            {}, {"Responses": None},
            {"Responses": {self.table.name: [unknown]}},
            {"Responses": {self.table.name: [before]},
             "UnprocessedKeys": {self.table.name: {"Keys": [self.key(finding)], "ConsistentRead": True}}},
        ]
        for reply in replies:
            with self.subTest(reply=reply), \
                    patch.object(self.table.meta.client, "batch_get_item", return_value=reply), \
                    patch.object(self.table.meta.client, "transact_write_items") as write:
                with self.assertRaises(ValueError):
                    self.record([finding])
                write.assert_not_called()
        self.assertEqual(self.stored(finding), before)

    def test_lease_transfer_between_read_and_write_prevents_stale_worker_side_effects(self):
        client = self.table.meta.client
        actual_write = client.transact_write_items

        def transferred(**kwargs):
            app.put({**self.active, "run_token": "new-worker-token"})
            return actual_write(**kwargs)

        with patch.object(client, "transact_write_items", side_effect=transferred):
            self.assertIsNone(self.record([self.finding()]))
        self.assertEqual(self.registry_rows(), [])

    def test_marker_and_profile_ownership_guards_all_reject_without_registry_writes(self):
        changes = [
            {"run_token": "other-token"}, {"run_until": self.now}, {"deadline_at": self.now},
            {"status": "SUCCEEDED"}, {"scan_id": str(uuid.uuid4())}, {"connection_version": "old"},
        ]
        for changeset in changes:
            with self.subTest(marker=changeset):
                app.put({**self.active, **changeset})
                self.assertIsNone(self.record([self.finding()]))
                self.assertEqual(self.registry_rows(), [])
        app.put(self.active)
        for profile in ({"connection_version": "v2", "regions": [self.active["region"]]},
                        {"connection_version": "v1", "regions": ["us-east-1"]}):
            with self.subTest(profile=profile):
                app.put({"pk": self.active["pk"], "sk": "PROFILE", **profile})
                self.assertIsNone(self.record([self.finding()]))
                self.assertEqual(self.registry_rows(), [])

    def test_snapshot_race_is_retriable_and_never_overwrites_a_newer_last(self):
        finding = self.finding(observed=self.now - 25)
        self.seed(finding, self.now - 1000, self.now - 50)
        newer = {**self.key(finding), "first_seen_at": self.now - 1000,
                 "last_seen_at": self.now - 10, "expires": self.now - 10 + app.RETENTION_SECONDS}
        client = self.table.meta.client
        actual_write = client.transact_write_items

        def advanced(**kwargs):
            app.put(newer)
            return actual_write(**kwargs)

        with patch.object(client, "transact_write_items", side_effect=advanced):
            with self.assertRaises(ClientError):
                self.record([finding])
        self.assertEqual(self.stored(finding), newer)
        self.assertEqual(self.record([finding])[finding["finding_id"]],
                         {"first_seen_at": newer["first_seen_at"], "last_seen_at": newer["last_seen_at"]})

    def test_missing_snapshot_race_cannot_replace_a_concurrently_created_first(self):
        finding = self.finding()
        concurrent = {**self.key(finding), "first_seen_at": self.now - 100,
                      "last_seen_at": self.now - 50, "expires": self.now - 50 + app.RETENTION_SECONDS}
        client = self.table.meta.client
        actual_write = client.transact_write_items

        def created(**kwargs):
            app.put(concurrent)
            return actual_write(**kwargs)

        with patch.object(client, "transact_write_items", side_effect=created):
            with self.assertRaises(ClientError):
                self.record([finding])
        self.assertEqual(self.stored(finding), concurrent)
        self.assertEqual(self.record([finding])[finding["finding_id"]],
                         {"first_seen_at": concurrent["first_seen_at"], "last_seen_at": self.now})

    def test_ttl_deletion_after_snapshot_is_retried_using_fresh_registry_state(self):
        finding = self.finding()
        self.seed(finding, self.now - app.RETENTION_SECONDS - 100, self.now - app.RETENTION_SECONDS)
        client = self.table.meta.client
        actual_write = client.transact_write_items

        def deleted(**kwargs):
            self.table.delete_item(Key=self.key(finding))
            return actual_write(**kwargs)

        with patch.object(client, "transact_write_items", side_effect=deleted):
            with self.assertRaises(ClientError):
                self.record([finding])
        self.assertEqual(self.stored(finding), {})
        self.assertEqual(self.record([finding])[finding["finding_id"]],
                         {"first_seen_at": self.now, "last_seen_at": self.now})

    def test_ownership_lost_after_one_write_batch_preserves_committed_observations(self):
        findings = [self.finding(i) for i in range(120)]
        client = self.table.meta.client
        actual_write = client.transact_write_items
        requests = 0

        def transferred(**kwargs):
            nonlocal requests
            requests += 1
            if requests == 2:
                app.put({**self.active, "run_token": "new-worker-token"})
            return actual_write(**kwargs)

        with patch.object(client, "transact_write_items", side_effect=transferred):
            self.assertIsNone(self.record(findings))
        self.assertEqual(len(self.registry_rows()), 98)
        self.assertEqual(app.get(self.active["pk"], self.active["sk"])["run_token"], "new-worker-token")

    def test_mixed_conditional_and_transaction_conflict_is_not_swallowed_as_ownership_loss(self):
        error = ClientError({"Error": {"Code": "TransactionCanceledException", "Message": "mixed cancellation"},
                             "CancellationReasons": [{"Code": "ConditionalCheckFailed"}, {"Code": "TransactionConflict"}]},
                            "TransactWriteItems")

        def conflict(**kwargs):
            app.put({**self.active, "run_token": "new-worker-token"})
            raise error

        with patch.object(self.table.meta.client, "transact_write_items", side_effect=conflict):
            with self.assertRaises(ClientError) as caught:
                self.record([self.finding()])
        self.assertIs(caught.exception, error)
        self.assertEqual(self.registry_rows(), [])

    def test_committed_observation_batch_survives_later_failure_and_replay_is_safe(self):
        findings = [self.finding(i) for i in range(120)]
        client = self.table.meta.client
        actual_write = client.transact_write_items
        requests = 0

        def write(**kwargs):
            nonlocal requests
            requests += 1
            if requests == 2:
                raise provider_error("ProvisionedThroughputExceededException")
            return actual_write(**kwargs)

        with patch.object(client, "transact_write_items", side_effect=write):
            with self.assertRaises(ClientError):
                self.record(findings)
        self.assertEqual(len(self.registry_rows()), 98)
        result = self.record(findings)
        self.assertEqual(len(self.registry_rows()), 120)
        self.assertEqual(len(result), 120)
        self.assertTrue(all(row == {"first_seen_at": self.now, "last_seen_at": self.now} for row in result.values()))

    def test_time_budget_exhaustion_before_first_read_has_no_side_effects(self):
        with patch.object(self.table.meta.client, "batch_get_item") as read, \
                patch.object(self.table.meta.client, "transact_write_items") as write:
            with self.assertRaises(TimeoutError):
                self.record([self.finding()], time_check=MagicMock(side_effect=TimeoutError("budget")))
        read.assert_not_called()
        write.assert_not_called()

    def test_time_budget_is_checked_again_before_a_write_batch(self):
        client = self.table.meta.client
        with patch.object(client, "batch_get_item", wraps=client.batch_get_item) as read, \
                patch.object(client, "transact_write_items") as write:
            def check():
                if read.call_count:
                    raise TimeoutError("budget exhausted after reading")

            with self.assertRaises(TimeoutError):
                self.record([self.finding()], time_check=check)
        self.assertEqual(read.call_count, 1)
        write.assert_not_called()

    def test_time_budget_between_write_batches_preserves_only_the_committed_batch(self):
        client = self.table.meta.client
        with patch.object(client, "transact_write_items", wraps=client.transact_write_items) as write:
            def check():
                if write.call_count:
                    raise TimeoutError("budget exhausted after first write batch")

            with self.assertRaises(TimeoutError):
                self.record([self.finding(i) for i in range(120)], time_check=check)
        self.assertEqual(write.call_count, 1)
        self.assertEqual(len(self.registry_rows()), 98)

    def test_invalid_finding_input_is_rejected_before_any_io(self):
        good = self.finding()
        bad = [None, {}, {**good, "finding_id": "escape#key"}, {**good, "finding_id": 42},
               {**good, "region": "us-east-1"}, {**good, "evaluated_at": "2026-10-26T12:00:00"},
               {**good, "evaluated_at": "invalid"}, {**good, "evaluated_at": None}]
        for finding in bad:
            with self.subTest(finding=finding), \
                    patch.object(self.table.meta.client, "batch_get_item") as read, \
                    patch.object(self.table.meta.client, "transact_write_items") as write:
                with self.assertRaises(ValueError):
                    self.record([finding])
                read.assert_not_called()
                write.assert_not_called()

    def test_malformed_stored_observation_fails_closed_without_overwriting_it(self):
        finding = self.finding()
        good = {**self.key(finding), "first_seen_at": self.now - 100, "last_seen_at": self.now - 50,
                "expires": self.now - 50 + app.RETENTION_SECONDS}
        malformed = [{key: val for key, val in good.items() if key != "first_seen_at"},
                     {**good, "last_seen_at": True}, {**good, "first_seen_at": None},
                     {**good, "first_seen_at": self.now}, {**good, "expires": "invalid"},
                     {**good, "expires": good["expires"] + 1}]
        for row in malformed:
            with self.subTest(row=row):
                app.put(row)
                with patch.object(self.table.meta.client, "transact_write_items") as write:
                    with self.assertRaises(ValueError):
                        self.record([finding])
                write.assert_not_called()
                self.assertEqual(self.stored(finding), row)


if __name__ == "__main__":
    unittest.main()
