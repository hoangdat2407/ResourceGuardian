"""Collector regressions for real ECR age, missing metrics, and global ownership."""
from datetime import datetime, timedelta, timezone
import pathlib
import sys
import unittest
from unittest.mock import MagicMock

from botocore.exceptions import ClientError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from collectors import collect_region
from rules import (
    config,
    evaluate_documentdb_cluster,
    evaluate_dynamodb_table,
    evaluate_lambda,
    evaluate_neptune_cluster,
)


class Paginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **_kwargs):
        if isinstance(self.pages, Exception):
            raise self.pages
        return iter(self.pages)


class EcrClient:
    def __init__(self, now, image_error=None):
        self.now = now
        self.image_error = image_error

    def get_paginator(self, operation):
        if operation == "describe_repositories":
            return Paginator([{"repositories": [{"repositoryName": "app", "registryId": "123456789012"}]}])
        if operation == "describe_images":
            if self.image_error:
                return Paginator(self.image_error)
            return Paginator([{"imageDetails": [
                {"imagePushedAt": self.now - timedelta(days=10)},
                {"imagePushedAt": self.now - timedelta(days=120)},
            ]}])
        raise KeyError(operation)

    def get_lifecycle_policy(self, **_kwargs):
        return {"lifecyclePolicyText": "{}"}


class Session:
    def __init__(self, clients):
        self.clients = clients
        self.calls = []

    def client(self, name, **_kwargs):
        self.calls.append(name)
        if name not in self.clients:
            raise KeyError(name)
        return self.clients[name]


class SqsDeniedClient:
    def get_paginator(self, operation):
        if operation == "list_queues":
            return Paginator([{"QueueUrls": ["https://sqs.ap-southeast-1.amazonaws.com/123456789012/work"]}])
        raise KeyError(operation)

    def get_queue_attributes(self, **_kwargs):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetQueueAttributes")


class BackupClient:
    def get_paginator(self, operation):
        if operation == "list_backup_vaults":
            return Paginator([{"BackupVaultList": [
                {"BackupVaultName": "vault", "BackupVaultArn": "arn:aws:backup:ap-southeast-1:123456789012:backup-vault:vault"}
            ]}])
        if operation == "list_recovery_points_by_backup_vault":
            return Paginator([
                {"RecoveryPoints": [{"Status": "COMPLETED"}]},
                {"RecoveryPoints": [{"Status": "EXPIRED"}, {"Status": "COMPLETED"}]},
            ])
        raise KeyError(operation)



class CollectorHardeningTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
        self.cfg = config({}, include_extended=True)

    def collect(self, session, groups, region="ap-southeast-1", global_region=None):
        return collect_region(
            session, region, "123456789012", self.cfg, groups, self.now,
            lambda: None, lambda *_args: 0, global_region=global_region,
        )

    def test_ecr_image_age_uses_describe_images_timestamp(self):
        result = self.collect(Session({"ecr": EcrClient(self.now)}), {"backup"})
        findings = [item for item in result["findings"] if item["type"] == "ECR_REPOSITORY"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule_id"], "ECR_IMAGE_OLD")
        self.assertEqual(findings[0]["evidence"]["oldest_image_age_days"], 120)
        self.assertEqual(result["inventory"][0]["resource_id"], "app")

    def test_ecr_describe_images_denial_is_partial_not_fake_zero(self):
        denied = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "DescribeImages")
        result = self.collect(Session({"ecr": EcrClient(self.now, denied)}), {"backup"})
        self.assertTrue(result["partial"])
        self.assertIn({"type": "ECR", "code": "AccessDenied"}, result["errors"])
        self.assertEqual(result["counts"]["ECR_REPOSITORY"], 1)
        self.assertEqual(result["findings"], [])
        self.assertEqual([item["resource_id"] for item in result["inventory"]], ["app"])

    def test_cloudfront_runs_only_in_deterministic_global_owner_region(self):
        cloudfront = MagicMock()
        cloudfront.get_paginator.return_value.paginate.return_value = iter([
            {"DistributionList": {"Items": []}}
        ])
        session = Session({"cloudfront": cloudfront})
        non_owner = self.collect(session, {"security"}, region="ap-southeast-1", global_region="us-east-1")
        self.assertNotIn("cloudfront", session.calls)
        self.assertNotIn("CLOUDFRONT_DISTRIBUTION", non_owner["counts"])

        owner_session = Session({"cloudfront": cloudfront})
        owner = self.collect(owner_session, {"security"}, region="us-east-1", global_region="us-east-1")
        self.assertEqual(owner["counts"]["CLOUDFRONT_DISTRIBUTION"], 0)
        self.assertEqual(owner_session.calls.count("cloudfront"), 1)


    def test_required_subrequest_access_denial_is_reported_partial(self):
        result = self.collect(Session({"sqs": SqsDeniedClient()}), {"integration"})
        self.assertTrue(result["partial"])
        self.assertIn({"type": "SQS_QUEUE", "code": "AccessDenied"}, result["errors"])
        self.assertEqual(result["counts"]["SQS_QUEUE"], 1)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["inventory"][0]["resource_id"], "work")

    def test_backup_recovery_point_pagination_counts_later_pages(self):
        result = self.collect(Session({"backup": BackupClient()}), {"backup"})
        finding = next(item for item in result["findings"] if item["type"] == "BACKUP_VAULT")
        self.assertEqual(finding["evidence"]["total_recovery_points"], 3)
        self.assertEqual(finding["evidence"]["expired_recovery_points"], 1)
    def test_missing_extended_metrics_are_insufficient_not_review(self):
        start = self.now - timedelta(hours=24)
        cases = [
            evaluate_lambda({"FunctionName": "fn"}, [], self.cfg, start),
            evaluate_dynamodb_table({"TableName": "table", "TableStatus": "ACTIVE"}, {"read": [], "write": []}, self.cfg, start),
            evaluate_documentdb_cluster({"DBClusterIdentifier": "doc", "Status": "available", "Engine": "docdb"}, [], self.cfg, start),
            evaluate_neptune_cluster({"DBClusterIdentifier": "graph", "Status": "available", "Engine": "neptune"}, [], self.cfg, start),
        ]
        self.assertTrue(all(item and item["level"] == "INSUFFICIENT_DATA" for item in cases))
        self.assertTrue(all("NO_CLOUDWATCH_METRICS" in item["evidence"]["data_issues"] for item in cases))


if __name__ == "__main__":
    unittest.main()
