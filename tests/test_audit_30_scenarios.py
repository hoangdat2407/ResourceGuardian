"""Comprehensive QA Audit Test Suite for Cloud Resource Guardian.
Covers 30 mandatory scenarios: true positives, false positives, edge cases, error handling,
multi-tenant isolation, observation lifecycle, and time budget constraints.
"""
import copy
import json
import math
import os
import pathlib
import sys
import time
import unittest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import boto3
from botocore.exceptions import ClientError, ParamValidationError
from moto import mock_aws

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from tests.test_api import app, event
import rules
import collectors


class TestAudit30Scenarios(unittest.TestCase):
    def setUp(self):
        self.aws = mock_aws()
        self.aws.start()
        self.db = boto3.resource("dynamodb", region_name="ap-southeast-1")
        self.db.create_table(
            TableName="test-table",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        self.table_patch = patch.object(app, "table", self.db.Table("test-table"))
        self.table_patch.start()
        self.now = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
        self.clock_patch = patch.object(app.time, "time", return_value=self.now.timestamp())
        self.clock_patch.start()
        self.profile = {
            "pk": "TENANT#tenant-a",
            "sk": "PROFILE",
            "external_id": "ext-audit",
            "settings": app.config({}),
            "service_groups": list(app.SERVICE_GROUPS),
            "role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-audit",
            "account_id": "123456789012",
            "regions": ["ap-southeast-1"],
            "connection_version": "v1",
        }
        app.put(self.profile)
        self.context = MagicMock()
        self.context.get_remaining_time_in_millis.return_value = 250000

        self.instances, self.volumes, self.snapshots, self.images = [], [], [], []
        self.addresses, self.nats, self.rds_instances, self.load_balancers, self.uploads = [], [], [], [], []
        self.inventory_errors = {}
        self.custom_metrics = {}

        self.ec2 = MagicMock()
        self.cw = MagicMock()
        self.s3 = MagicMock()
        self.rds = MagicMock()
        self.elbv2 = MagicMock()
        self.clients = {"ec2": self.ec2, "cloudwatch": self.cw, "s3": self.s3, "rds": self.rds, "elbv2": self.elbv2}
        self.sess = MagicMock()
        self.sess.client.side_effect = lambda service, **kwargs: self.clients[service]

        def ec2_paginator(operation):
            if operation in self.inventory_errors:
                raise self.inventory_errors[operation]
            key, items = {
                "describe_instances": ("Reservations", [{"Instances": self.instances}]),
                "describe_volumes": ("Volumes", self.volumes),
                "describe_snapshots": ("Snapshots", self.snapshots),
                "describe_images": ("Images", self.images),
                "describe_nat_gateways": ("NatGateways", self.nats),
            }[operation]
            p = MagicMock()
            p.paginate.return_value = [{key: items}]
            return p

        def simple_paginator(mapping):
            def factory(operation):
                if operation in self.inventory_errors:
                    raise self.inventory_errors[operation]
                key, items = mapping[operation]
                p = MagicMock()
                p.paginate.return_value = [{key: items}]
                return p
            return factory

        self.ec2.get_paginator.side_effect = ec2_paginator
        self.ec2.describe_addresses.side_effect = lambda **kwargs: {"Addresses": self.addresses}
        self.s3.list_buckets.return_value = {"Buckets": []}
        self.s3.get_paginator.side_effect = simple_paginator({"list_multipart_uploads": ("Uploads", self.uploads)})
        self.rds.get_paginator.side_effect = simple_paginator({"describe_db_instances": ("DBInstances", self.rds_instances)})
        self.elbv2.get_paginator.side_effect = simple_paginator({"describe_load_balancers": ("LoadBalancers", self.load_balancers)})
        self.cw.get_metric_data.side_effect = self.fake_metrics

        self.session_patch = patch.object(app, "session", return_value=self.sess)
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.clock_patch.stop()
        self.table_patch.stop()
        self.aws.stop()

    def fake_metrics(self, **kwargs):
        queries = kwargs.get("MetricDataQueries", [])
        results = []
        for q in queries:
            ident = q["Id"]
            if ident in self.custom_metrics:
                vals, stamps = self.custom_metrics[ident]
            else:
                vals, stamps = [], []
            results.append({"Id": ident, "StatusCode": "Complete", "Values": vals, "Timestamps": stamps})
        return {"MetricDataResults": results}

    def run_worker_scan(self, scan_id=None, region="ap-southeast-1"):
        sid = scan_id or str(uuid.uuid4())
        app.put({
            "pk": self.profile["pk"],
            "sk": f"RESULT#{region}",
            "scan_id": sid,
            "status": "QUEUED",
            "started_at": int(app.time.time()),
            "region": region,
            "connection_version": self.profile.get("connection_version", "v1"),
        })
        app.worker({"pk": self.profile["pk"], "region": region, "scan_id": sid, "connection_version": self.profile.get("connection_version", "v1")}, self.context)
        return app.get(self.profile["pk"], f"RESULT#{region}")

    # =========================================================================
    # Scenario 1: EBS available, unattached, chưa đủ orphan_hours
    # =========================================================================
    def test_01_ebs_unattached_under_orphan_hours(self):
        self.volumes.append({"VolumeId": "vol-under-orphan", "State": "available", "Attachments": [], "Size": 50})
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "SUCCEEDED")
        self.assertEqual(len(res["findings"]), 1)
        finding = res["findings"][0]
        self.assertEqual(finding["type"], "EBS")
        self.assertEqual(finding["resource_id"], "vol-under-orphan")
        self.assertEqual(finding["level"], "OBSERVING")
        self.assertEqual(finding["rule_id"], "EBS_UNATTACHED")
        self.assertLess(finding["evidence"]["observed_hours"], 24)

    # =========================================================================
    # Scenario 2: EBS available, unattached, đã vượt orphan_hours
    # =========================================================================
    def test_02_ebs_unattached_exceeded_orphan_hours(self):
        self.volumes.append({"VolumeId": "vol-exceeded-orphan", "State": "available", "Attachments": [], "Size": 50})
        clock = int(app.time.time())
        # First scan anchors observation
        with patch.object(app.time, "time", return_value=clock - 26 * 3600):
            self.run_worker_scan()
        # Second scan 26 hours later
        with patch.object(app.time, "time", return_value=clock):
            res = self.run_worker_scan()
        self.assertEqual(res["status"], "SUCCEEDED")
        self.assertEqual(len(res["findings"]), 1)
        finding = res["findings"][0]
        self.assertEqual(finding["level"], "REVIEW")
        self.assertEqual(finding["rule_id"], "EBS_UNATTACHED")
        self.assertGreaterEqual(finding["evidence"]["observed_hours"], 24)

    # =========================================================================
    # Scenario 3: EBS đang attached nhưng EC2 CPU rất thấp
    # =========================================================================
    def test_03_ebs_attached_not_flagged(self):
        self.volumes.append({
            "VolumeId": "vol-attached",
            "State": "in-use",
            "Attachments": [{"InstanceId": "i-low-cpu", "Device": "/dev/sda1"}],
            "Size": 100,
        })
        res = self.run_worker_scan()
        ebs_findings = [f for f in res.get("findings", []) if f["type"] == "EBS"]
        self.assertEqual(ebs_findings, [])

    # =========================================================================
    # Scenario 4: EIP allocated, không association
    # =========================================================================
    def test_04_eip_unassociated(self):
        self.addresses.append({"AllocationId": "eipalloc-free", "PublicIp": "54.1.2.3"})
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "SUCCEEDED")
        self.assertEqual(len(res["findings"]), 1)
        finding = res["findings"][0]
        self.assertEqual(finding["type"], "EIP")
        self.assertEqual(finding["resource_id"], "eipalloc-free")
        self.assertEqual(finding["level"], "OBSERVING")
        self.assertEqual(finding["rule_id"], "EIP_UNASSOCIATED")

    # =========================================================================
    # Scenario 5: EIP đang association hợp lệ
    # =========================================================================
    def test_05_eip_associated_not_flagged(self):
        self.addresses.append({
            "AllocationId": "eipalloc-busy",
            "PublicIp": "54.1.2.4",
            "AssociationId": "eipassoc-active",
            "InstanceId": "i-some-instance",
        })
        res = self.run_worker_scan()
        eip_findings = [f for f in res.get("findings", []) if f["type"] == "EIP"]
        self.assertEqual(eip_findings, [])

    # =========================================================================
    # Scenario 6: EC2 chạy lâu ngày, CPU p95 thấp và network thấp
    # =========================================================================
    def test_06_ec2_low_utilization(self):
        self.instances.append({
            "InstanceId": "i-idle-ec2",
            "State": {"Name": "running"},
            "LaunchTime": self.now - timedelta(days=10),
        })
        end = self.now.replace(minute=0, second=0, microsecond=0)
        stamps = [end - timedelta(hours=i) for i in range(1, 25)]
        self.custom_metrics["cpu"] = ([1.2] * 24, stamps)
        self.custom_metrics["netin"] = ([50000] * 24, stamps)   # ~0.047 MiB/hr
        self.custom_metrics["netout"] = ([50000] * 24, stamps)
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "SUCCEEDED")
        self.assertEqual(len(res["findings"]), 1)
        finding = res["findings"][0]
        self.assertEqual(finding["type"], "EC2")
        self.assertEqual(finding["level"], "REVIEW")
        self.assertEqual(finding["rule_id"], "EC2_LOW_UTILIZATION")
        self.assertLess(finding["evidence"]["cpu_p95"], 5.0)
        self.assertLess(finding["evidence"]["network_mib_hour"], 1.0)

    # =========================================================================
    # Scenario 7: EC2 CPU thấp nhưng network cao (False positive prevention)
    # =========================================================================
    def test_07_ec2_low_cpu_high_network_not_idle(self):
        self.instances.append({
            "InstanceId": "i-high-net-ec2",
            "State": {"Name": "running"},
            "LaunchTime": self.now - timedelta(days=10),
        })
        end = self.now.replace(minute=0, second=0, microsecond=0)
        stamps = [end - timedelta(hours=i) for i in range(1, 25)]
        self.custom_metrics["cpu"] = ([1.0] * 24, stamps)
        self.custom_metrics["netin"] = ([50 * 1048576] * 24, stamps)  # 50 MiB/hr > 1 MiB threshold
        self.custom_metrics["netout"] = ([10 * 1048576] * 24, stamps)
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "SUCCEEDED")
        ec2_findings = [f for f in res.get("findings", []) if f["type"] == "EC2"]
        self.assertEqual(ec2_findings, [])

    # =========================================================================
    # Scenario 8: EC2 mới tạo, chưa đủ window
    # =========================================================================
    def test_08_ec2_younger_than_window(self):
        self.instances.append({
            "InstanceId": "i-newborn",
            "State": {"Name": "running"},
            "LaunchTime": self.now - timedelta(hours=2),  # Created 2 hours ago (< 24h)
        })
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "SUCCEEDED")
        self.assertEqual(len(res["findings"]), 1)
        finding = res["findings"][0]
        self.assertEqual(finding["level"], "INSUFFICIENT_DATA")
        self.assertEqual(finding["reason"], "Instance younger than observation window")

    # =========================================================================
    # Scenario 9: EC2 thiếu 30% metric samples
    # =========================================================================
    def test_09_ec2_missing_samples_insufficient_data(self):
        self.instances.append({
            "InstanceId": "i-sparse-metrics",
            "State": {"Name": "running"},
            "LaunchTime": self.now - timedelta(days=10),
        })
        end = self.now.replace(minute=0, second=0, microsecond=0)
        # 16 samples out of 24 = ~66.7% coverage < 80% (ceil(24 * 0.8) = 20 required)
        stamps = [end - timedelta(hours=i) for i in range(1, 17)]
        self.custom_metrics["cpu"] = ([1.0] * 16, stamps)
        self.custom_metrics["netin"] = ([1000] * 16, stamps)
        self.custom_metrics["netout"] = ([1000] * 16, stamps)
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "SUCCEEDED")
        self.assertEqual(len(res["findings"]), 1)
        finding = res["findings"][0]
        self.assertEqual(finding["level"], "INSUFFICIENT_DATA")
        self.assertEqual(finding["reason"], "Missing CloudWatch metrics; not classified as idle")
        self.assertIn("cpu", finding["evidence"]["missing_metrics"])
        self.assertLess(finding["evidence"]["sample_counts"]["cpu"], 20)

    # =========================================================================
    # Scenario 10: Snapshot cũ không được AMI nào tham chiếu
    # =========================================================================
    def test_10_snapshot_old_unreferenced(self):
        self.snapshots.append({
            "SnapshotId": "snap-abandoned",
            "State": "completed",
            "StartTime": self.now - timedelta(days=45),
            "VolumeSize": 50,
            "VolumeId": "vol-orig",
        })
        self.images = []  # No AMIs
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "SUCCEEDED")
        snap_findings = [f for f in res["findings"] if f["type"] == "SNAPSHOT"]
        self.assertEqual(len(snap_findings), 1)
        self.assertEqual(snap_findings[0]["level"], "REVIEW")
        self.assertEqual(snap_findings[0]["rule_id"], "SNAPSHOT_OLD_UNREFERENCED")

    # =========================================================================
    # Scenario 11: Snapshot đang được AMI sử dụng
    # =========================================================================
    def test_11_snapshot_referenced_by_ami_not_flagged(self):
        self.snapshots.append({
            "SnapshotId": "snap-used",
            "State": "completed",
            "StartTime": self.now - timedelta(days=60),
            "VolumeSize": 50,
        })
        self.images.append({
            "ImageId": "ami-active",
            "BlockDeviceMappings": [{"Ebs": {"SnapshotId": "snap-used"}}],
        })
        res = self.run_worker_scan()
        snap_findings = [f for f in res.get("findings", []) if f["type"] == "SNAPSHOT"]
        self.assertEqual(snap_findings, [])

    # =========================================================================
    # Scenario 12: Snapshot của AWS Backup
    # =========================================================================
    def test_12_snapshot_aws_backup_not_flagged(self):
        self.snapshots.append({
            "SnapshotId": "snap-backup-1",
            "State": "completed",
            "StartTime": self.now - timedelta(days=60),
            "VolumeSize": 50,
            "Description": "Created by AWS:BACKUP job",
        })
        self.snapshots.append({
            "SnapshotId": "snap-backup-2",
            "State": "completed",
            "StartTime": self.now - timedelta(days=60),
            "VolumeSize": 50,
            "Tags": [{"Key": "aws:backup:job-id", "Value": "123"}],
        })
        res = self.run_worker_scan()
        snap_findings = [f for f in res.get("findings", []) if f["type"] == "SNAPSHOT"]
        self.assertEqual(snap_findings, [])

    # =========================================================================
    # Scenario 13: S3 multipart upload hơn 7 ngày chưa hoàn thành
    # =========================================================================
    def test_13_s3_multipart_stale(self):
        self.s3.list_buckets.return_value = {"Buckets": [{"Name": "audit-bucket", "BucketRegion": "ap-southeast-1"}]}
        self.uploads.append({
            "Key": "huge-dataset.tar.gz",
            "UploadId": "upload-old-123",
            "Initiated": self.now - timedelta(days=12),
        })
        res = self.run_worker_scan()
        s3_findings = [f for f in res["findings"] if f["type"] == "S3_MULTIPART"]
        self.assertEqual(len(s3_findings), 1)
        self.assertEqual(s3_findings[0]["level"], "REVIEW")
        self.assertEqual(s3_findings[0]["rule_id"], "S3_STALE_MULTIPART")
        self.assertGreater(s3_findings[0]["evidence"]["age_days"], 7.0)

    # =========================================================================
    # Scenario 14: S3 multipart upload mới tạo
    # =========================================================================
    def test_14_s3_multipart_recent_not_flagged(self):
        self.s3.list_buckets.return_value = {"Buckets": [{"Name": "audit-bucket", "BucketRegion": "ap-southeast-1"}]}
        self.uploads.append({
            "Key": "fresh-file.bin",
            "UploadId": "upload-fresh-456",
            "Initiated": self.now - timedelta(days=2),  # 2 days old (< 7)
        })
        res = self.run_worker_scan()
        s3_findings = [f for f in res.get("findings", []) if f["type"] == "S3_MULTIPART"]
        self.assertEqual(s3_findings, [])

    # =========================================================================
    # Scenario 15: RDS có CPU thấp, ít connection
    # =========================================================================
    def test_15_rds_low_utilization(self):
        self.rds_instances.append({
            "DBInstanceIdentifier": "db-idle",
            "DBInstanceStatus": "available",
            "InstanceCreateTime": self.now - timedelta(days=10),
            "DBInstanceArn": "arn:aws:rds:ap-southeast-1:123456789012:db:db-idle",
            "Engine": "postgres",
            "DBInstanceClass": "db.t3.micro",
        })
        end = self.now.replace(minute=0, second=0, microsecond=0)
        stamps = [end - timedelta(hours=i) for i in range(1, 25)]
        self.custom_metrics["cpu"] = ([1.1] * 24, stamps)
        self.custom_metrics["connections"] = ([0] * 24, stamps)
        res = self.run_worker_scan()
        rds_findings = [f for f in res["findings"] if f["type"] == "RDS"]
        self.assertEqual(len(rds_findings), 1)
        self.assertEqual(rds_findings[0]["level"], "REVIEW")
        self.assertEqual(rds_findings[0]["rule_id"], "RDS_LOW_UTILIZATION")

    # =========================================================================
    # Scenario 16: RDS CPU thấp nhưng connection cao
    # =========================================================================
    def test_16_rds_high_connections_not_idle(self):
        self.rds_instances.append({
            "DBInstanceIdentifier": "db-busy-connections",
            "DBInstanceStatus": "available",
            "InstanceCreateTime": self.now - timedelta(days=10),
            "DBInstanceArn": "arn:aws:rds:ap-southeast-1:123456789012:db:db-busy",
        })
        end = self.now.replace(minute=0, second=0, microsecond=0)
        stamps = [end - timedelta(hours=i) for i in range(1, 25)]
        self.custom_metrics["cpu"] = ([1.0] * 24, stamps)
        self.custom_metrics["connections"] = ([25] * 24, stamps)  # 25 connections > 1 threshold
        res = self.run_worker_scan()
        rds_findings = [f for f in res.get("findings", []) if f["type"] == "RDS"]
        self.assertEqual(rds_findings, [])

    # =========================================================================
    # Scenario 17: NAT Gateway ít traffic nhưng đủ dữ liệu
    # =========================================================================
    def test_17_nat_gateway_low_traffic(self):
        self.nats.append({
            "NatGatewayId": "nat-idle-gw",
            "State": "available",
            "CreateTime": self.now - timedelta(days=5),
            "VpcId": "vpc-1",
            "SubnetId": "subnet-1",
        })
        end = self.now.replace(minute=0, second=0, microsecond=0)
        stamps = [end - timedelta(hours=i) for i in range(1, 25)]
        self.custom_metrics["source"] = ([1000] * 24, stamps)
        self.custom_metrics["destination"] = ([2000] * 24, stamps)
        res = self.run_worker_scan()
        nat_findings = [f for f in res["findings"] if f["type"] == "NAT_GATEWAY"]
        self.assertEqual(len(nat_findings), 1)
        self.assertEqual(nat_findings[0]["level"], "REVIEW")
        self.assertEqual(nat_findings[0]["rule_id"], "NAT_LOW_UTILIZATION")
        self.assertLess(nat_findings[0]["evidence"]["nat_mib_hour"], 1.0)

    # =========================================================================
    # Scenario 18: ALB không có request, đủ thời gian quan sát
    # =========================================================================
    def test_18_alb_zero_requests(self):
        self.load_balancers.append({
            "LoadBalancerName": "alb-silent",
            "Type": "application",
            "State": {"Code": "active"},
            "CreatedTime": self.now - timedelta(days=10),
            "LoadBalancerArn": "arn:aws:elasticloadbalancing:ap-southeast-1:123456789012:loadbalancer/app/alb-silent/123",
            "Scheme": "internet-facing",
        })
        end = self.now.replace(minute=0, second=0, microsecond=0)
        stamps = [end - timedelta(hours=i) for i in range(1, 25)]
        self.custom_metrics["requests"] = ([0] * 24, stamps)  # Real 0 requests
        res = self.run_worker_scan()
        alb_findings = [f for f in res["findings"] if f["type"] == "ALB"]
        self.assertEqual(len(alb_findings), 1)
        self.assertEqual(alb_findings[0]["level"], "REVIEW")
        self.assertEqual(alb_findings[0]["rule_id"], "ALB_LOW_UTILIZATION")
        self.assertEqual(alb_findings[0]["evidence"]["requests_hour"], 0.0)

    # =========================================================================
    # Scenario 19: NLB có lưu lượng cao
    # =========================================================================
    def test_19_nlb_high_traffic_not_flagged(self):
        self.load_balancers.append({
            "LoadBalancerName": "nlb-busy",
            "Type": "network",
            "State": {"Code": "active"},
            "CreatedTime": self.now - timedelta(days=10),
            "LoadBalancerArn": "arn:aws:elasticloadbalancing:ap-southeast-1:123456789012:loadbalancer/net/nlb-busy/456",
        })
        end = self.now.replace(minute=0, second=0, microsecond=0)
        stamps = [end - timedelta(hours=i) for i in range(1, 25)]
        self.custom_metrics["flows"] = ([1500] * 24, stamps)  # 1500 flows/hr > 1 threshold
        res = self.run_worker_scan()
        nlb_findings = [f for f in res.get("findings", []) if f["type"] == "NLB"]
        self.assertEqual(nlb_findings, [])

    # =========================================================================
    # Scenario 20: Tài nguyên mang tag guardian:keep=true
    # =========================================================================
    def test_20_keep_tag_suppresses_findings(self):
        keep_tag = [{"Key": "guardian:keep", "Value": "true"}]
        self.volumes.append({"VolumeId": "vol-kept", "State": "available", "Attachments": [], "Size": 20, "Tags": keep_tag})
        self.addresses.append({"AllocationId": "eipalloc-kept", "PublicIp": "54.1.1.1", "Tags": keep_tag})
        self.instances.append({"InstanceId": "i-kept", "State": {"Name": "running"}, "LaunchTime": self.now - timedelta(days=5), "Tags": keep_tag})
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "SUCCEEDED")
        self.assertEqual(res.get("findings", []), [])

    # =========================================================================
    # Scenario 21: AWS AccessDenied ở một service trong một region
    # =========================================================================
    def test_21_partial_error_on_access_denied(self):
        self.instances.append({"InstanceId": "i-good", "State": {"Name": "running"}, "LaunchTime": self.now - timedelta(days=5)})
        # Make describe_volumes fail with AccessDenied
        self.inventory_errors["describe_volumes"] = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Not authorized to describe volumes"}},
            "DescribeVolumes",
        )
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "PARTIAL")
        # Verify partial status is recorded
        errs = res.get("errors", [])
        self.assertTrue(any(e["type"] == "EBS" and e["code"] == "AccessDenied" for e in errs))
        # EC2 count should still be collected
        self.assertEqual(res["counts"]["EC2"], 1)

    # =========================================================================
    # Scenario 22: Throttling từ AWS API
    # =========================================================================
    def test_22_throttling_error_handling(self):
        self.inventory_errors["describe_instances"] = ClientError(
            {"Error": {"Code": "RequestLimitExceeded", "Message": "Rate exceeded"}},
            "DescribeInstances",
        )
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "PARTIAL")
        errs = res.get("errors", [])
        self.assertTrue(any(e["type"] == "EC2" and e["code"] == "RequestLimitExceeded" for e in errs))

    # =========================================================================
    # Scenario 23: Collector gặp phân trang nhiều trang
    # =========================================================================
    def test_23_pagination_multi_page_collection(self):
        page1 = [{"VolumeId": f"vol-p1-{i}", "State": "available", "Attachments": [], "Size": 10} for i in range(25)]
        page2 = [{"VolumeId": f"vol-p2-{i}", "State": "available", "Attachments": [], "Size": 10} for i in range(15)]
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Volumes": page1}, {"Volumes": page2}]
        self.ec2.get_paginator.side_effect = lambda op: paginator if op == "describe_volumes" else MagicMock(paginate=lambda **kw: [{op.split("_")[1].title(): []}])
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "SUCCEEDED")
        self.assertEqual(res["counts"]["EBS"], 40)

    # =========================================================================
    # Scenario 24: Inventory có hơn 100 resources (Cap to 100 & PARTIAL)
    # =========================================================================
    def test_24_inventory_cap_100_triggers_partial(self):
        page = [{"VolumeId": f"vol-bulk-{i}", "State": "available", "Attachments": [], "Size": 10} for i in range(110)]
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Volumes": page}]
        self.ec2.get_paginator.side_effect = lambda op: paginator if op == "describe_volumes" else MagicMock(paginate=lambda **kw: [{op.split("_")[1].title(): []}])
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "PARTIAL")
        self.assertEqual(res["counts"]["EBS"], 100)
        self.assertTrue(any(e["type"] == "EBS" and e["code"] == "RESOURCE_LIMIT" for e in res.get("errors", [])))

    # =========================================================================
    # Scenario 25: CloudWatch không trả metrics (Missing metrics != 0)
    # =========================================================================
    def test_25_cloudwatch_no_metrics_never_assumed_zero(self):
        self.instances.append({
            "InstanceId": "i-dead-cw",
            "State": {"Name": "running"},
            "LaunchTime": self.now - timedelta(days=10),
        })
        # Empty CloudWatch results (0 samples returned)
        self.custom_metrics.clear()
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "SUCCEEDED")
        finding = res["findings"][0]
        self.assertEqual(finding["level"], "INSUFFICIENT_DATA")
        self.assertNotIn("cpu_p95", finding["evidence"])
        self.assertEqual(finding["evidence"]["sample_counts"]["cpu"], 0)

    # =========================================================================
    # Scenario 26: Worker chạm time budget
    # =========================================================================
    def test_26_worker_hits_time_budget(self):
        # Context starts with enough time, but drops below 60s during collection
        times = [150000, 150000, 45000]
        self.context.get_remaining_time_in_millis.side_effect = lambda: times.pop(0) if times else 45000
        res = self.run_worker_scan()
        self.assertEqual(res["status"], "PARTIAL")
        errs = res.get("errors", [])
        self.assertTrue(any(e["code"] == "TIME_BUDGET" for e in errs))

    # =========================================================================
    # Scenario 27: Hai scan được kích hoạt đồng thời
    # =========================================================================
    def test_27_concurrent_scans_rejected_with_409(self):
        with patch.object(app.invoker, "invoke", return_value={"StatusCode": 202}):
            # First scan starts
            req1 = app.api(event("POST", "/scans", user="tenant-a"), None)
            self.assertEqual(req1["statusCode"], 202)
            sid = json.loads(req1["body"])["scan_id"]
            self.assertTrue(sid)

            # Second scan while first is active returns 409 Conflict
            req2 = app.api(event("POST", "/scans", user="tenant-a"), None)
            self.assertEqual(req2["statusCode"], 409)
            body2 = json.loads(req2["body"])
            self.assertEqual(body2["message"], "Scan lease is active")

    # =========================================================================
    # Scenario 28: Tenant A cố truy cập finding/scan của Tenant B
    # =========================================================================
    def test_28_cross_tenant_isolation(self):
        # Create scan for Tenant A
        sid = str(uuid.uuid4())
        self.run_worker_scan(scan_id=sid)

        # Profile for Tenant B
        profile_b = {
            "pk": "TENANT#tenant-b",
            "sk": "PROFILE",
            "external_id": "ext-b",
            "settings": app.config({}),
            "service_groups": list(app.SERVICE_GROUPS),
            "role_arn": "arn:aws:iam::999999999999:role/GuardianReadRole-b",
            "account_id": "999999999999",
            "regions": ["ap-southeast-1"],
            "connection_version": "v1",
        }
        app.put(profile_b)

        # Tenant B requests Tenant A's scan status -> 404
        req_b = app.api(event("GET", f"/scans/{sid}", user="tenant-b"), None)
        self.assertEqual(req_b["statusCode"], 404)

        # Tenant B lists findings -> empty (does not see Tenant A findings)
        findings_b = app.api(event("GET", "/findings", user="tenant-b"), None)
        self.assertEqual(json.loads(findings_b["body"])["results"], [])

    # =========================================================================
    # Scenario 29: Thay đổi connection_version làm reset observation
    # =========================================================================
    def test_29_connection_version_reset(self):
        self.volumes.append({"VolumeId": "vol-rotate", "State": "available", "Attachments": [], "Size": 20})
        # Scan under v1
        self.run_worker_scan()
        obs_key_v1 = f"OBS#v1#ap-southeast-1#EBS#vol-rotate"
        self.assertIsNotNone(app.get(self.profile["pk"], obs_key_v1).get("first"))

        # Rotate to connection_version v2
        self.profile["connection_version"] = "v2"
        app.put(self.profile)

        # Scan under v2
        res2 = self.run_worker_scan()
        obs_key_v2 = f"OBS#v2#ap-southeast-1#EBS#vol-rotate"
        v2_record = app.get(self.profile["pk"], obs_key_v2)
        self.assertIsNotNone(v2_record.get("first"))
        # Finding is still OBSERVING under v2 because observation window restarted
        self.assertEqual(res2["findings"][0]["level"], "OBSERVING")

    # =========================================================================
    # Scenario 30: Finding bị ignore, hết hạn ignore và xuất hiện lại
    # =========================================================================
    def test_30_ignore_expiry_lifecycle(self):
        self.volumes.append({"VolumeId": "vol-ignore-test", "State": "available", "Attachments": [], "Size": 20})
        res = self.run_worker_scan()
        fid = res["findings"][0]["finding_id"]

        clock = int(app.time.time())
        # Set ignore for 1 day
        ignore_payload = {
            "region": "ap-southeast-1",
            "finding_id": fid,
            "ignoreUntil": datetime.fromtimestamp(clock + 86400, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        put_fb = app.api(event("PUT", "/feedback", user="tenant-a", body=ignore_payload), None)
        self.assertEqual(put_fb["statusCode"], 200)

        # During ignore window (now + 1 hour) -> finding is HIDDEN from /findings
        with patch.object(app.time, "time", return_value=clock + 3600):
            view_during = app.api(event("GET", "/findings", user="tenant-a"), None)
            hidden_findings = json.loads(view_during["body"])["results"][0]["findings"]
            self.assertEqual(hidden_findings, [])

        # After ignore window expires (now + 2 days) -> finding REAPPEARS
        with patch.object(app.time, "time", return_value=clock + 2 * 86400):
            view_after = app.api(event("GET", "/findings", user="tenant-a"), None)
            visible_findings = json.loads(view_after["body"])["results"][0]["findings"]
            self.assertEqual(len(visible_findings), 1)
            self.assertEqual(visible_findings[0]["finding_id"], fid)


if __name__ == "__main__":
    unittest.main()
