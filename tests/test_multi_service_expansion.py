"""Comprehensive unit and integration tests for Multi-Service Scanner expansion (P0 & P1)."""
from datetime import datetime, timezone, timedelta
import json
import os
import pathlib
import sys
import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("TABLE", "test-table")
os.environ.setdefault("WORKER_FUNCTION", "test-worker")
os.environ.setdefault("API_PRINCIPAL", "test-api-role")
os.environ.setdefault("SCAN_PRINCIPAL", "test-worker-role")
with patch("boto3.resource"), patch("boto3.client"):
    import app

from rules import (
    config,
    evaluate_api_gateway,
    evaluate_auto_scaling_group,
    evaluate_backup_vault,
    evaluate_cloudfront_distribution,
    evaluate_documentdb_cluster,
    evaluate_dynamodb_table,
    evaluate_ecr_repository,
    evaluate_ecs_cluster,
    evaluate_ecs_service,
    evaluate_efs_file_system,
    evaluate_eip,
    evaluate_eks_cluster,
    evaluate_elasticache_cluster,
    evaluate_eventbridge_rule,
    evaluate_fsx_filesystem,
    evaluate_kinesis_stream,
    evaluate_lambda,
    evaluate_load_balancer,
    evaluate_log_group,
    evaluate_memorydb_cluster,
    evaluate_msk_cluster,
    evaluate_nat_gateway,
    evaluate_neptune_cluster,
    evaluate_opensearch_domain,
    evaluate_rds,
    evaluate_rds_snapshot,
    evaluate_redshift_cluster,
    evaluate_s3_multipart,
    evaluate_sagemaker_endpoint,
    evaluate_security_group,
    evaluate_snapshot,
    evaluate_sns_topic,
    evaluate_sqs_queue,
    evaluate_step_function,
    evaluate_vpc_endpoint,
    finding_id,
    RESOURCE_REGISTRY,
    RULE_METADATA,
    THRESHOLD_METADATA,
    LIMITS,
)
from collectors import collect_region


class TestP0Rules(unittest.TestCase):
    def setUp(self):
        self.cfg = config({})
        self.now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
        self.start = self.now - timedelta(hours=24)

    def test_lambda_rule_active_vs_idle(self):
        fn = {"FunctionName": "active-fn", "Runtime": "python3.12", "CodeSize": 100}
        self.assertIsNone(evaluate_lambda(fn, [100], self.cfg, self.start))

        idle_fn = {"FunctionName": "idle-fn", "Runtime": "python3.12", "CodeSize": 100}
        finding = evaluate_lambda(idle_fn, [0, 0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "LAMBDA_FUNCTION")
        self.assertEqual(finding["level"], "REVIEW")
        self.assertEqual(finding["rule_id"], "LAMBDA_UNUSED")

    def test_log_group_rule_retention(self):
        with_retention = {"logGroupName": "/aws/active", "retentionInDays": 14}
        self.assertIsNone(evaluate_log_group(with_retention, self.cfg))

        without_retention = {"logGroupName": "/aws/never-expire", "retentionInDays": None, "storedBytes": 1048576}
        finding = evaluate_log_group(without_retention, self.cfg)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "LOG_GROUP")
        self.assertEqual(finding["rule_id"], "LOG_GROUP_NO_RETENTION")
        self.assertEqual(finding["level"], "REVIEW")

    def test_security_group_attached_vs_unused(self):
        default_sg = {"GroupId": "sg-default", "GroupName": "default"}
        self.assertIsNone(evaluate_security_group(default_sg, set(), set(), 200, self.cfg))

        attached_sg = {"GroupId": "sg-attached", "GroupName": "web-sg"}
        self.assertIsNone(evaluate_security_group(attached_sg, {"sg-attached"}, set(), 200, self.cfg))

        unused_sg = {"GroupId": "sg-unused", "GroupName": "forgotten-sg", "VpcId": "vpc-1"}
        # Less than threshold -> OBSERVING
        obs_finding = evaluate_security_group(unused_sg, set(), set(), 10, self.cfg)
        self.assertEqual(obs_finding["level"], "OBSERVING")

        # Exceeds threshold -> REVIEW
        finding = evaluate_security_group(unused_sg, set(), set(), 200, self.cfg)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "SECURITY_GROUP")
        self.assertEqual(finding["level"], "REVIEW")
        self.assertEqual(finding["rule_id"], "SECURITY_GROUP_UNUSED")
    def test_rds_snapshot_old_vs_recent(self):
        recent = {
            "DBSnapshotIdentifier": "snap-recent",
            "SnapshotType": "manual",
            "Status": "available",
            "SnapshotCreateTime": self.now - timedelta(days=10),
        }
        self.assertIsNone(evaluate_rds_snapshot(recent, self.cfg, self.now))

        old = {
            "DBSnapshotIdentifier": "snap-old",
            "SnapshotType": "manual",
            "Status": "available",
            "SnapshotCreateTime": self.now - timedelta(days=100),
            "Engine": "postgres",
            "AllocatedStorage": 100,
        }
        finding = evaluate_rds_snapshot(old, self.cfg, self.now)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "RDS_SNAPSHOT")
        self.assertEqual(finding["level"], "REVIEW")
        self.assertEqual(finding["rule_id"], "RDS_SNAPSHOT_OLD")

    def test_dynamodb_idle_vs_active(self):
        active_table = {"TableName": "active-tbl", "TableStatus": "ACTIVE"}
        self.assertIsNone(evaluate_dynamodb_table(active_table, {"read": [10], "write": [5]}, self.cfg, self.start))

        idle_table = {"TableName": "idle-tbl", "TableStatus": "ACTIVE", "ItemCount": 100, "TableSizeBytes": 2048}
        finding = evaluate_dynamodb_table(idle_table, {"read": [0], "write": [0]}, self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "DYNAMODB_TABLE")
        self.assertEqual(finding["level"], "REVIEW")
        self.assertEqual(finding["rule_id"], "DYNAMODB_IDLE")

    def test_ecr_repository_lifecycle(self):
        with_policy = {"repositoryName": "app-repo"}
        self.assertIsNone(evaluate_ecr_repository(with_policy, True, 30, self.cfg))

        without_policy = {"repositoryName": "abandoned-repo", "registryId": "123"}
        finding = evaluate_ecr_repository(without_policy, False, 100, self.cfg)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "ECR_REPOSITORY")
        self.assertEqual(finding["rule_id"], "ECR_NO_LIFECYCLE")
        self.assertEqual(finding["level"], "REVIEW")

    def test_sqs_queue_traffic_and_dlq(self):
        # DLQ queues should never be flagged
        dlq_url = "https://sqs.ap-southeast-1.amazonaws.com/123/my-deadletter-queue"
        self.assertIsNone(evaluate_sqs_queue(dlq_url, {"ApproximateNumberOfMessages": "0"}, {"sent": [0], "received": [0]}, self.cfg, self.start))

        # Active queue
        active_url = "https://sqs.ap-southeast-1.amazonaws.com/123/active-queue"
        self.assertIsNone(evaluate_sqs_queue(active_url, {"ApproximateNumberOfMessages": "5"}, {"sent": [10], "received": [10]}, self.cfg, self.start))

        # Idle queue
        idle_url = "https://sqs.ap-southeast-1.amazonaws.com/123/idle-queue"
        finding = evaluate_sqs_queue(idle_url, {"ApproximateNumberOfMessages": "0"}, {"sent": [0], "received": [0]}, self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "SQS_QUEUE")
        self.assertEqual(finding["level"], "REVIEW")
        self.assertEqual(finding["rule_id"], "SQS_QUEUE_IDLE")


class TestP1Rules(unittest.TestCase):
    def setUp(self):
        self.cfg = config({})
        self.now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
        self.start = self.now - timedelta(hours=24)

    def test_elasticache_idle(self):
        cluster = {"CacheClusterId": "idle-redis", "CacheClusterStatus": "available", "Engine": "redis"}
        finding = evaluate_elasticache_cluster(cluster, [0, 0, 0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "ELASTICACHE_CLUSTER")
        self.assertEqual(finding["level"], "REVIEW")

    def test_efs_no_mount_target(self):
        fs = {"FileSystemId": "fs-12345", "LifeCycleState": "available", "NumberOfMountTargets": 0}
        finding = evaluate_efs_file_system(fs, self.cfg)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "EFS_FILE_SYSTEM")
        self.assertEqual(finding["level"], "REVIEW")

    def test_ecs_cluster_empty(self):
        cluster = {"clusterName": "empty-ecs", "status": "ACTIVE", "runningTasksCount": 0, "activeServicesCount": 0, "registeredContainerInstancesCount": 0}
        finding = evaluate_ecs_cluster(cluster, self.cfg)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "ECS_CLUSTER")
        self.assertEqual(finding["level"], "REVIEW")

    def test_ecs_service_idle(self):
        srv = {"serviceName": "zero-task-service", "status": "ACTIVE", "desiredCount": 0, "runningCount": 0}
        finding = evaluate_ecs_service(srv, self.cfg)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "ECS_SERVICE")
        self.assertEqual(finding["level"], "REVIEW")

    def test_auto_scaling_group_zero_capacity(self):
        asg = {"AutoScalingGroupName": "zero-asg", "DesiredCapacity": 0, "MinSize": 0, "Instances": []}
        finding = evaluate_auto_scaling_group(asg, self.cfg)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "AUTO_SCALING_GROUP")
        self.assertEqual(finding["level"], "REVIEW")

    def test_api_gateway_unused(self):
        api_item = {"id": "api-123", "name": "unused-api"}
        finding = evaluate_api_gateway(api_item, [0, 0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "API_GATEWAY")
        self.assertEqual(finding["level"], "REVIEW")

    def test_sns_topic_unused(self):
        finding = evaluate_sns_topic("arn:aws:sns:ap-southeast-1:123:silent-topic", {"SubscriptionsConfirmed": "0"}, [0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "SNS_TOPIC")
        self.assertEqual(finding["level"], "REVIEW")

    def test_eventbridge_rule_disabled_or_no_targets(self):
        disabled_rule = {"Name": "disabled-rule", "State": "DISABLED"}
        finding = evaluate_eventbridge_rule(disabled_rule, [], self.cfg)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "EVENTBRIDGE_RULE")
        self.assertEqual(finding["level"], "REVIEW")

    def test_step_function_unused(self):
        sm = {"name": "unused-sm", "stateMachineArn": "arn:aws:states:ap-southeast-1:123:stateMachine:unused-sm"}
        finding = evaluate_step_function(sm, [0, 0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "STEP_FUNCTION")
        self.assertEqual(finding["level"], "REVIEW")

    def test_vpc_endpoint_unused(self):
        vpce = {"VpcEndpointId": "vpce-123", "State": "available"}
        finding = evaluate_vpc_endpoint(vpce, [0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "VPC_ENDPOINT")
        self.assertEqual(finding["level"], "REVIEW")


class TestP2Rules(unittest.TestCase):
    def setUp(self):
        self.cfg = config({}, include_extended=True)
        self.now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
        self.start = self.now - timedelta(hours=24)

    def test_sagemaker_endpoint_idle(self):
        ep = {"EndpointName": "churn-model-ep", "EndpointStatus": "InService"}
        finding = evaluate_sagemaker_endpoint(ep, [0, 0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "SAGEMAKER_ENDPOINT")
        self.assertEqual(finding["level"], "REVIEW")

    def test_opensearch_domain_idle(self):
        dom = {"DomainName": "logs-search", "Processing": False}
        finding = evaluate_opensearch_domain(dom, [0, 0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "OPENSEARCH_DOMAIN")
        self.assertEqual(finding["level"], "REVIEW")

    def test_redshift_cluster_idle(self):
        cl = {"ClusterIdentifier": "analytics-wh", "ClusterStatus": "available"}
        finding = evaluate_redshift_cluster(cl, [0, 0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "REDSHIFT_CLUSTER")
        self.assertEqual(finding["level"], "REVIEW")

    def test_msk_cluster_idle(self):
        msk = {"ClusterName": "events-kafka", "State": "ACTIVE"}
        finding = evaluate_msk_cluster(msk, [0, 0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "MSK_CLUSTER")
        self.assertEqual(finding["level"], "REVIEW")

    def test_kinesis_stream_idle(self):
        kin = {"StreamName": "clickstream", "StreamStatus": "ACTIVE"}
        finding = evaluate_kinesis_stream(kin, [0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "KINESIS_STREAM")
        self.assertEqual(finding["level"], "REVIEW")

    def test_cloudfront_low_traffic(self):
        cf = {"Id": "E12345", "Enabled": True, "Status": "Deployed"}
        # Low traffic -> REVIEW
        finding = evaluate_cloudfront_distribution(cf, [10], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "CLOUDFRONT_DISTRIBUTION")
        self.assertEqual(finding["level"], "REVIEW")

        # Missing metrics -> INSUFFICIENT_DATA
        missing = evaluate_cloudfront_distribution(cf, [], self.cfg, self.start)
        self.assertIsNotNone(missing)
        self.assertEqual(missing["level"], "INSUFFICIENT_DATA")
    def test_backup_vault_expired_recovery_points(self):
        vault = {"BackupVaultName": "default-vault"}
        finding = evaluate_backup_vault(vault, 5, 20, self.cfg)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "BACKUP_VAULT")
        self.assertEqual(finding["level"], "REVIEW")

    def test_eks_cluster_no_workers(self):
        eks_cl = {"name": "k8s-dev", "status": "ACTIVE"}
        finding = evaluate_eks_cluster(eks_cl, 0, 0, self.cfg)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "EKS_CLUSTER")
        self.assertEqual(finding["level"], "REVIEW")

    def test_fsx_filesystem_idle(self):
        fsx_item = {"FileSystemId": "fs-9999", "Lifecycle": "AVAILABLE"}
        finding = evaluate_fsx_filesystem(fsx_item, [0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "FSX_FILE_SYSTEM")
        self.assertEqual(finding["level"], "REVIEW")

    def test_memorydb_cluster_idle(self):
        mem = {"Name": "mem-cluster", "Status": "available"}
        finding = evaluate_memorydb_cluster(mem, [0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "MEMORYDB_CLUSTER")
        self.assertEqual(finding["level"], "REVIEW")

    def test_documentdb_cluster_idle(self):
        docdb = {"DBClusterIdentifier": "doc-cluster", "Status": "available", "Engine": "docdb"}
        finding = evaluate_documentdb_cluster(docdb, [0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "DOCUMENTDB_CLUSTER")
        self.assertEqual(finding["level"], "REVIEW")

    def test_neptune_cluster_idle(self):
        nep = {"DBClusterIdentifier": "graph-cluster", "Status": "available", "Engine": "neptune"}
        finding = evaluate_neptune_cluster(nep, [0], self.cfg, self.start)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["type"], "NEPTUNE_CLUSTER")
        self.assertEqual(finding["level"], "REVIEW")

class TestThresholdValidationAndPersistence(unittest.TestCase):
    def test_all_metadata_fields_have_valid_bounds(self):
        for field, meta in THRESHOLD_METADATA.items():
            self.assertIn("min", meta)
            self.assertIn("max", meta)
            self.assertIn("default", meta)
            self.assertIn("integer", meta)
            self.assertIn("group", meta)
            self.assertIn("rule", meta)
            self.assertIn("label", meta)
            self.assertTrue(meta["min"] <= meta["default"] <= meta["max"])
            if meta["integer"]:
                self.assertIsInstance(meta["default"], int)

    def test_config_merges_partial_update_safely(self):
        initial = config({}, include_extended=True)
        self.assertEqual(initial["lambda_unused_days"], 30)
        self.assertEqual(initial["sg_unused_days"], 7)

        # Partial update modifies requested keys, keeps existing
        updated = config({"lambda_unused_days": 45, "sg_unused_days": 14}, initial)
        self.assertEqual(updated["lambda_unused_days"], 45)
        self.assertEqual(updated["sg_unused_days"], 14)
        self.assertEqual(updated["cpu_percent"], 5)  # original preserved

    def test_out_of_bounds_threshold_rejected(self):
        with self.assertRaises(ValueError):
            config({"lambda_unused_days": 500})  # max 90

        with self.assertRaises(ValueError):
            config({"sg_unused_days": 0})  # min 1

        with self.assertRaises(ValueError):
            config({"rds_snapshot_days": 3.5})  # must be integer


if __name__ == "__main__":
    unittest.main()
