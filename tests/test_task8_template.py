"""Operational invariants for Task 8's failure and reconciliation paths."""
import unittest

from tests.test_read_only import load


class Task8Infrastructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = load("template.yaml")["Resources"]

    def properties(self, name):
        return self.resources[name]["Properties"]

    def actions(self, role):
        statements = self.properties(role)["Policies"][0]["PolicyDocument"]["Statement"]
        return {
            action: statement["Resource"]
            for statement in statements
            if isinstance(statement, dict)
            for action in (statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]])
        }

    def test_worker_failure_reaches_consumer_then_operations_dlq(self):
        worker = self.properties("WorkerFunction")
        source = self.properties("DeadLetters")
        consumer = self.properties("RecoveryFunction")
        event = consumer["Events"]["FailedScans"]["Properties"]
        self.assertEqual(worker["EventInvokeConfig"]["DestinationConfig"]["OnFailure"]["Destination"], "DeadLetters.Arn")
        self.assertEqual(event["Queue"], "DeadLetters.Arn")
        self.assertEqual(event["FunctionResponseTypes"], ["ReportBatchItemFailures"])
        self.assertLessEqual(event["BatchSize"], 10)
        self.assertGreaterEqual(source["VisibilityTimeout"], 6 * consumer["Timeout"])
        self.assertEqual(source["RedrivePolicy"], {"deadLetterTargetArn": "OperationsDeadLetters.Arn", "maxReceiveCount": 5})
        for name in ("DeadLetters", "OperationsDeadLetters"):
            self.assertEqual(self.properties(name)["MessageRetentionPeriod"], 14 * 86400)
            self.assertTrue(self.properties(name)["SqsManagedSseEnabled"])

    def test_schedule_delivery_and_execution_failures_have_separate_routes(self):
        for name, interval in (("ScheduleFunction", "rate(1 hour)"), ("ReconcileFunction", "rate(5 minutes)")):
            function = self.properties(name)
            schedule = function["Events"]["Tick"]["Properties"]
            self.assertEqual(schedule["Schedule"], interval)
            self.assertTrue(schedule["Enabled"])
            self.assertEqual(schedule["DeadLetterConfig"]["Arn"], "OperationsDeadLetters.Arn")
            self.assertEqual(function["EventInvokeConfig"]["DestinationConfig"]["OnFailure"]["Destination"], "OperationsDeadLetters.Arn")
            self.assertGreater(schedule["RetryPolicy"]["MaximumRetryAttempts"], 0)
            self.assertEqual(self.actions(function["Role"].split(".")[0])["sqs:SendMessage"], "OperationsDeadLetters.Arn")
        statement = self.properties("OperationsQueuePolicy")["PolicyDocument"]["Statement"][0]
        self.assertEqual(statement["Principal"], {"Service": "events.amazonaws.com"})
        self.assertEqual(statement["Resource"], "OperationsDeadLetters.Arn")
        self.assertEqual(set(statement["Condition"]["ArnEquals"]["aws:SourceArn"]), {"ScheduleFunctionTick.Arn", "ReconcileFunctionTick.Arn"})

    def test_recovery_and_reconciliation_cannot_scan_target_accounts(self):
        for role in ("RecoveryRole", "ReconcileRole"):
            actions = self.actions(role)
            self.assertNotIn("sts:AssumeRole", actions)
            self.assertNotIn("lambda:InvokeFunction", actions)
            self.assertTrue(all(action.startswith(("dynamodb:", "sqs:")) for action in actions))
            self.assertTrue(all(scope == "Data.Arn" for action, scope in actions.items() if action.startswith("dynamodb:")))
        recovery = self.actions("RecoveryRole")
        for action in ("sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"):
            self.assertEqual(recovery[action], "DeadLetters.Arn")
        self.assertNotIn("sqs:ReceiveMessage", self.actions("ReconcileRole"))

    def test_transaction_condition_checks_use_table_scoped_permissions(self):
        for role in ("ApiRole", "ScanRole", "ScheduleRole", "RecoveryRole", "ReconcileRole"):
            actions = self.actions(role)
            self.assertEqual(actions["dynamodb:ConditionCheckItem"], "Data.Arn")
            self.assertEqual(actions["dynamodb:DeleteItem"], "Data.Arn")
            self.assertNotIn("dynamodb:TransactWriteItems", actions)

    def test_alarms_cover_lost_failures_and_unhandled_messages(self):
        lambda_metrics = self.properties("DestinationDeliveryAlarm")["Metrics"]
        functions = {
            metric["MetricStat"]["Metric"]["Dimensions"][0]["Value"]
            for metric in lambda_metrics if "MetricStat" in metric
        }
        self.assertEqual(functions, {"WorkerFunction", "ScheduleFunction", "ReconcileFunction"})
        for metric in lambda_metrics:
            if "MetricStat" in metric:
                self.assertEqual(metric["MetricStat"]["Metric"]["MetricName"], "DestinationDeliveryFailures")
        event_metrics = self.properties("EventDeliveryAlarm")["Metrics"]
        self.assertEqual({m["MetricStat"]["Metric"]["MetricName"] for m in event_metrics if "MetricStat" in m}, {"InvocationsFailedToBeSentToDlq"})
        backlog = self.properties("OperationsBacklogAlarm")
        self.assertEqual(backlog["MetricName"], "ApproximateNumberOfMessagesVisible")
        self.assertEqual(backlog["Dimensions"], [{"Name": "QueueName", "Value": "OperationsDeadLetters.QueueName"}])
        self.assertEqual(backlog["Threshold"], 1)

    def test_worker_execution_contract_is_unchanged(self):
        worker = self.properties("WorkerFunction")
        self.assertEqual(worker["Timeout"], 300)
        self.assertEqual(worker["EventInvokeConfig"]["MaximumEventAgeInSeconds"], 600)
        self.assertEqual(worker["EventInvokeConfig"]["MaximumRetryAttempts"], 2)


if __name__ == "__main__":
    unittest.main()
