"""Backend workflows against Moto DynamoDB with all target-account reads mocked."""
import copy
import importlib
import json
import os
import pathlib
import sys
import unittest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from tests.test_api import app, event
collectors = importlib.import_module("collectors")


class Workflows(unittest.TestCase):
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
        self.profile = {
            "pk": "TENANT#alice", "sk": "PROFILE", "external_id": "ext",
            "settings": app.config({}), "service_groups": list(app.SERVICE_GROUPS),
            "role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-demo",
            "account_id": "123456789012", "regions": ["ap-southeast-1"],
            "connection_version": "v1",
        }
        app.put(self.profile)
        self.context = MagicMock()
        self.context.get_remaining_time_in_millis.return_value = 200000
        self.instances, self.volumes, self.snapshots, self.images = [], [], [], []
        self.nats, self.rds_instances, self.load_balancers, self.uploads = [], [], [], []
        self.ec2, self.cw, self.s3, self.rds, self.elbv2 = (MagicMock() for _ in range(5))
        self.clients = {"ec2": self.ec2, "cloudwatch": self.cw, "s3": self.s3, "rds": self.rds, "elbv2": self.elbv2}
        self.sess = MagicMock()
        self.sess.client.side_effect = lambda service, **kwargs: self.clients[service]

        def ec2_paginator(operation):
            key, items = {
                "describe_instances": ("Reservations", [{"Instances": self.instances}]),
                "describe_volumes": ("Volumes", self.volumes),
                "describe_snapshots": ("Snapshots", self.snapshots),
                "describe_images": ("Images", self.images),
                "describe_nat_gateways": ("NatGateways", self.nats),
            }[operation]
            paginator = MagicMock()
            paginator.paginate.return_value = [{key: items}]
            return paginator

        def simple_paginator(mapping):
            def factory(operation):
                key, items = mapping[operation]
                paginator = MagicMock()
                paginator.paginate.return_value = [{key: items}]
                return paginator
            return factory

        self.ec2.get_paginator.side_effect = ec2_paginator
        self.ec2.describe_addresses.return_value = {"Addresses": []}
        self.s3.list_buckets.return_value = {"Buckets": []}
        self.s3.get_paginator.side_effect = simple_paginator({"list_multipart_uploads": ("Uploads", self.uploads)})
        self.rds.get_paginator.side_effect = simple_paginator({"describe_db_instances": ("DBInstances", self.rds_instances)})
        self.elbv2.get_paginator.side_effect = simple_paginator({"describe_load_balancers": ("LoadBalancers", self.load_balancers)})
        self.cw.get_metric_data.side_effect = self.empty_metrics
        self.session_patch = patch.object(app, "session", return_value=self.sess)
        self.session_patch.start()

    @staticmethod
    def empty_metrics(**kwargs):
        return {"MetricDataResults": [{"Id": query["Id"], "StatusCode": "Complete", "Values": [], "Timestamps": []} for query in kwargs["MetricDataQueries"]]}

    def tearDown(self):
        self.session_patch.stop()
        self.table_patch.stop()
        self.aws.stop()

    def scan(self, scan_id=None):
        scan_id = scan_id or str(uuid.uuid4())
        app.put({
            "pk": self.profile["pk"], "sk": "RESULT#ap-southeast-1", "scan_id": scan_id,
            "status": "QUEUED", "started_at": int(app.time.time()), "region": "ap-southeast-1",
            "connection_version": self.profile["connection_version"],
        })
        app.worker({"pk": self.profile["pk"], "region": "ap-southeast-1", "scan_id": scan_id, "connection_version": "v1"}, self.context)
        return app.get(self.profile["pk"], "RESULT#ap-southeast-1")

    def test_empty_scan_completes_and_history_written(self):
        result = self.scan()
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["counts"], {"EC2": 0, "EBS": 0, "SNAPSHOT": 0, "S3_MULTIPART": 0, "RDS": 0, "EIP": 0, "NAT_GATEWAY": 0, "ALB": 0, "NLB": 0})
        self.assertEqual(len(app.history(self.profile["pk"], self.profile)), 1)

    def test_unattached_volume_observation_then_review_and_reset(self):
        self.volumes.append({"VolumeId": "vol-demo", "State": "available", "Attachments": [], "Size": 40})
        clock = int(app.time.time())
        with patch.object(app.time, "time", return_value=clock):
            self.assertEqual(self.scan()["findings"][0]["level"], "OBSERVING")
        with patch.object(app.time, "time", return_value=clock + 25 * 3600):
            self.assertEqual(self.scan()["findings"][0]["level"], "REVIEW")
        self.volumes[0].update(Attachments=[{"InstanceId": "i-demo"}], State="in-use")
        self.assertEqual(self.scan()["findings"], [])

    def test_snapshot_referenced_by_ami_is_not_flagged(self):
        self.snapshots.append({"SnapshotId": "snap-used", "StartTime": datetime.now(timezone.utc) - timedelta(days=100), "State": "completed", "VolumeSize": 40})
        self.images.append({"BlockDeviceMappings": [{"Ebs": {"SnapshotId": "snap-used"}}]})
        self.assertFalse(any(item["type"] == "SNAPSHOT" for item in self.scan()["findings"]))

    def test_partial_permission_error_retains_ec2_results(self):
        self.instances.append({"InstanceId": "i-demo", "State": {"Name": "stopped"}, "LaunchTime": datetime.now(timezone.utc) - timedelta(days=4)})
        self.ec2.describe_addresses.side_effect = ClientError({"Error": {"Code": "UnauthorizedOperation", "Message": "denied"}}, "DescribeAddresses")
        result = self.scan()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["counts"]["EC2"], 1)
        self.assertIn({"type": "EIP", "code": "UnauthorizedOperation"}, result["errors"])

    def test_missing_ec2_and_rds_metrics_are_insufficient(self):
        self.instances.append({"InstanceId": "i-demo", "State": {"Name": "running"}, "LaunchTime": datetime.now(timezone.utc) - timedelta(days=4)})
        self.rds_instances.append({"DBInstanceIdentifier": "db-demo", "DBInstanceArn": "arn:db", "DBInstanceStatus": "available", "InstanceCreateTime": datetime.now(timezone.utc) - timedelta(days=4), "Engine": "postgres", "DBInstanceClass": "db.t4g.micro"})
        findings = self.scan()["findings"]
        self.assertEqual({item["type"]: item["level"] for item in findings}, {"EC2": "INSUFFICIENT_DATA", "RDS": "INSUFFICIENT_DATA"})

    def test_nat_real_zero_is_review(self):
        self.nats.append({"NatGatewayId": "nat-demo", "State": "available", "CreateTime": datetime.now(timezone.utc) - timedelta(days=4), "VpcId": "vpc-1", "SubnetId": "subnet-1"})
        timestamps = [datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=index + 1) for index in range(20)]
        self.cw.get_metric_data.side_effect = lambda **kwargs: {"MetricDataResults": [{"Id": query["Id"], "StatusCode": "Complete", "Values": [0] * 20, "Timestamps": timestamps} for query in kwargs["MetricDataQueries"]]}
        finding = next(item for item in self.scan()["findings"] if item["type"] == "NAT_GATEWAY")
        self.assertEqual(finding["level"], "REVIEW")
        self.assertEqual(finding["evidence"]["nat_mib_hour"], 0)

    def test_stale_s3_multipart_is_review_and_structurally_identified(self):
        self.s3.list_buckets.return_value = {"Buckets": [{"Name": "demo", "BucketRegion": "ap-southeast-1"}]}
        self.uploads.append({"Key": "a/b", "UploadId": "upload#1", "Initiated": datetime.now(timezone.utc) - timedelta(days=8)})
        finding = next(item for item in self.scan()["findings"] if item["type"] == "S3_MULTIPART")
        self.assertEqual(finding["resource_id"], "s3://demo/a/b")
        self.assertRegex(finding["finding_id"], r"^[0-9a-f]{64}$")

    def test_denied_elb_is_partial_while_other_counts_remain(self):
        self.elbv2.get_paginator.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "DescribeLoadBalancers")
        result = self.scan()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["counts"]["EC2"], 0)
        self.assertIn({"type": "ELB", "code": "AccessDenied"}, result["errors"])

    def test_metric_pagination_deduplicates_real_zero(self):
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=24)
        timestamp = start + timedelta(hours=1)
        self.cw.get_metric_data.side_effect = [
            {"MetricDataResults": [{"Id": "cpu", "StatusCode": "PartialData", "Timestamps": [timestamp], "Values": [0]}], "NextToken": "page2"},
            {"MetricDataResults": [{"Id": "cpu", "StatusCode": "Complete", "Timestamps": [timestamp], "Values": [0]}]},
        ]
        values = collectors.metric_series(self.cw, [{"Id": "cpu"}], start, end)
        self.assertEqual(values, {"cpu": [0]})

    def test_scan_id_is_scoped_to_authenticated_tenant(self):
        scan_id = str(uuid.uuid4())
        self.scan(scan_id)
        app.put({**self.profile, "pk": "TENANT#bob"})
        self.assertEqual(app.api(event("GET", "/scans/" + scan_id, user="bob"), None)["statusCode"], 404)

    def test_enqueue_invokes_worker_asynchronously(self):
        with patch.object(app, "invoker") as invoker:
            invoker.invoke.return_value = {"StatusCode": 202}
            scan_id = app.enqueue(self.profile, int(app.time.time()))
            self.assertTrue(scan_id)
            self.assertEqual(invoker.invoke.call_args.kwargs["InvocationType"], "Event")

    def test_transient_error_releases_lease_for_retry(self):
        scan_id = str(uuid.uuid4())
        app.put({"pk": self.profile["pk"], "sk": "RESULT#ap-southeast-1", "scan_id": scan_id, "status": "QUEUED", "region": "ap-southeast-1", "connection_version": "v1"})
        self.session_patch.stop()
        with patch.object(app, "session", side_effect=ClientError({"Error": {"Code": "Throttling", "Message": "temporary"}}, "AssumeRole")):
            with self.assertRaises(ClientError):
                app.worker({"pk": self.profile["pk"], "region": "ap-southeast-1", "scan_id": scan_id, "connection_version": "v1"}, self.context)
        self.assertEqual(app.get(self.profile["pk"], "RESULT#ap-southeast-1")["run_until"], 0)
        self.session_patch.start()

    def test_notification_deduplicates_unchanged_review_set(self):
        profile = {**self.profile, "notifications": {"enabled": True, "email": "verified@example.com"}}
        result = {"region": "ap-southeast-1", "findings": [{"type": "EBS", "resource_id": "vol-demo", "level": "REVIEW", "reason": "review"}]}
        with patch.dict(os.environ, SES_SENDER="owner@example.com"), patch.object(app.boto3, "client") as client:
            self.assertEqual(app.notify(profile, result), "SENT")
            self.assertEqual(app.notify(profile, result), "UNCHANGED")
            client.return_value.send_email.assert_called_once()

    def test_history_query_continues_beyond_three_filtered_pages(self):
        profile = {**self.profile, "connection_version": "current"}
        stale = {"pk": self.profile["pk"], "sk": "HISTORY#stale", "connection_version": "old", "expires": int(app.time.time()) + 100}
        current = {"pk": self.profile["pk"], "sk": "HISTORY#current", "connection_version": "current", "expires": int(app.time.time()) + 100}
        pages = [{"Items": [stale], "LastEvaluatedKey": {"pk": stale["pk"], "sk": "HISTORY#" + str(index)}} for index in range(4)] + [{"Items": [current]}]
        with patch.object(app, "table") as table:
            table.query.side_effect = pages
            rows, token = app.page_rows(self.profile["pk"], "HISTORY#", profile, 1)
        self.assertEqual(rows[0]["sk"], "HISTORY#current")
        self.assertIsNone(token)
        self.assertEqual(table.query.call_count, 5)

    def test_resource_and_finding_caps_are_partial(self):
        self.volumes.extend(
            {"VolumeId": "vol-" + str(index), "State": "available", "Attachments": [], "Size": 1}
            for index in range(101)
        )
        result = self.scan()
        self.assertEqual(result["counts"]["EBS"], 100)
        self.assertEqual(result["finding_count"], 100)
        self.assertEqual(len(result["findings"]), 50)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertIn({"type": "EBS", "code": "RESOURCE_LIMIT"}, result["errors"])

    def test_time_budget_marks_current_and_remaining_collectors(self):
        self.context.get_remaining_time_in_millis.return_value = 20000
        result = self.scan()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertTrue(result["errors"])
        self.assertTrue(all(error["code"] == "TIME_BUDGET" for error in result["errors"]))
        self.sess.client.assert_not_called()

    def test_s3_bucket_and_upload_pagination_preserves_upload_identity(self):
        self.s3.list_buckets.side_effect = [
            {"Buckets": [{"Name": "demo", "BucketRegion": "ap-southeast-1"}], "ContinuationToken": "next"},
            {"Buckets": []},
        ]
        paginator = MagicMock()
        initiated = datetime.now(timezone.utc) - timedelta(days=8)
        paginator.paginate.return_value = [
            {"Uploads": [{"Key": "same", "UploadId": "first", "Initiated": initiated}]},
            {"Uploads": [{"Key": "same", "UploadId": "second", "Initiated": initiated}]},
        ]
        self.s3.get_paginator.side_effect = None
        self.s3.get_paginator.return_value = paginator
        findings = [item for item in self.scan()["findings"] if item["type"] == "S3_MULTIPART"]
        self.assertEqual(len(findings), 2)
        self.assertNotEqual(findings[0]["finding_id"], findings[1]["finding_id"])
        self.assertEqual(self.s3.list_buckets.call_count, 2)
        paginator.paginate.assert_called_once_with(Bucket="demo", ExpectedBucketOwner="123456789012")

    def test_rds_alb_and_nlb_real_zero_are_review(self):
        old = datetime.now(timezone.utc) - timedelta(days=4)
        self.rds_instances.append({"DBInstanceIdentifier": "db-demo", "DBInstanceArn": "arn:db", "DBInstanceStatus": "available", "InstanceCreateTime": old, "Engine": "postgres", "DBInstanceClass": "db.t4g.micro"})
        self.load_balancers.extend([
            {"Type": "application", "State": {"Code": "active"}, "CreatedTime": old, "LoadBalancerName": "alb-demo", "LoadBalancerArn": "arn:aws:elasticloadbalancing:x:1:loadbalancer/app/alb-demo/id", "Scheme": "internet-facing"},
            {"Type": "network", "State": {"Code": "active"}, "CreatedTime": old, "LoadBalancerName": "nlb-demo", "LoadBalancerArn": "arn:aws:elasticloadbalancing:x:1:loadbalancer/net/nlb-demo/id", "Scheme": "internal"},
        ])
        timestamps = [datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=index + 1) for index in range(20)]
        self.cw.get_metric_data.side_effect = lambda **kwargs: {"MetricDataResults": [{"Id": query["Id"], "StatusCode": "Complete", "Values": [0] * 20, "Timestamps": timestamps} for query in kwargs["MetricDataQueries"]]}
        levels = {item["type"]: item["level"] for item in self.scan()["findings"]}
        self.assertEqual(levels["RDS"], "REVIEW")
        self.assertEqual(levels["ALB"], "REVIEW")
        self.assertEqual(levels["NLB"], "REVIEW")


if __name__ == "__main__":
    unittest.main()
