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
from botocore.exceptions import ClientError, ParamValidationError
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
        self.addresses = []
        self.nats, self.rds_instances, self.load_balancers, self.uploads = [], [], [], []
        self.inventory_errors = {}
        self.scan_sequence = 0
        self.ec2, self.cw, self.s3, self.rds, self.elbv2 = (MagicMock() for _ in range(5))
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
            paginator = MagicMock()
            paginator.paginate.return_value = [{key: items}]
            return paginator

        def simple_paginator(mapping):
            def factory(operation):
                if operation in self.inventory_errors:
                    raise self.inventory_errors[operation]
                key, items = mapping[operation]
                paginator = MagicMock()
                paginator.paginate.return_value = [{key: items}]
                return paginator
            return factory

        self.ec2.get_paginator.side_effect = ec2_paginator
        def safe_describe_addresses(**kwargs):
            if "MaxResults" in kwargs:
                raise ParamValidationError(report='Parameter validation failed:\nUnknown parameter in input: "MaxResults"')
            return {"Addresses": self.addresses}

        self.ec2.describe_addresses.side_effect = safe_describe_addresses
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
            "connection_version": self.profile.get("connection_version", "v1"),
        })
        app.worker({"pk": self.profile["pk"], "region": "ap-southeast-1", "scan_id": scan_id, "connection_version": self.profile.get("connection_version", "v1")}, self.context)
        return app.get(self.profile["pk"], "RESULT#ap-southeast-1")

    def scan_at(self, now):
        self.scan_sequence += 1
        with patch.object(app.time, "time", return_value=now):
            return self.scan(str(uuid.uuid4()))

    def keep_resource(self, rid, enabled, user="alice", **extra):
        return app.api(
            event("PUT", "/keep", user=user, body={"region": "ap-southeast-1", "resource_id": rid, "enabled": enabled, **extra}),
            None,
        )

    def observation(self, rid):
        return app.get(self.profile["pk"], "OBS#" + self.profile["connection_version"] + "#ap-southeast-1#" + rid)

    def add_orphan(self, kind, rid):
        if kind == "EBS":
            item = {"VolumeId": rid, "State": "available", "Attachments": [], "Size": 40}
            self.volumes.append(item)
        else:
            item = {"AllocationId": rid}
            self.addresses.append(item)
        return item

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

    def test_new_connection_does_not_inherit_old_observation(self):
        self.volumes.append({"VolumeId": "vol-demo", "State": "available", "Attachments": [], "Size": 40})
        app.put({"pk": self.profile["pk"], "sk": "OBS#old-connection#ap-southeast-1#vol-demo", "first": int(app.time.time()) - 30 * 3600, "last": int(app.time.time())})
        self.assertEqual(self.scan()["findings"][0]["level"], "OBSERVING")

    def test_snapshot_referenced_by_ami_is_not_flagged(self):
        self.snapshots.append({"SnapshotId": "snap-used", "StartTime": datetime.now(timezone.utc) - timedelta(days=100), "State": "completed", "VolumeSize": 40})
        self.images.append({"BlockDeviceMappings": [{"Ebs": {"SnapshotId": "snap-used"}}]})
        self.assertFalse(any(item["type"] == "SNAPSHOT" for item in self.scan()["findings"]))

    def test_snapshot_referenced_by_disabled_ami_is_not_flagged(self):
        for rid in ("snap-disabled-ami", "snap-unused"):
            self.snapshots.append({"SnapshotId": rid, "StartTime": datetime.now(timezone.utc) - timedelta(days=100), "State": "completed", "VolumeSize": 40})
        disabled_image = {"ImageId": "ami-disabled", "State": "disabled", "BlockDeviceMappings": [{"Ebs": {"SnapshotId": "snap-disabled-ami"}}]}
        image_paginator = MagicMock()
        image_paginator.paginate.side_effect = lambda **kwargs: [{"Images": [disabled_image] if kwargs.get("IncludeDisabled") is True else []}]
        default_paginator = self.ec2.get_paginator.side_effect
        self.ec2.get_paginator.side_effect = lambda operation: image_paginator if operation == "describe_images" else default_paginator(operation)
        result = self.scan()
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual([finding["resource_id"] for finding in result["findings"]], ["snap-unused"])
        self.assertEqual(result["findings"][0]["level"], "REVIEW")
        self.assertTrue(result["findings"][0]["evidence"]["relationships_complete"])
        image_paginator.paginate.assert_called_once_with(Owners=["self"], IncludeDisabled=True)

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

    def test_notification_uses_cognito_verified_email_not_body(self):
        e = event("PUT", "/notifications", body={"enabled": True, "email": "attacker@example.com"})
        e["headers"] = {"authorization": "Bearer valid-token"}
        with patch.dict(os.environ, SES_SENDER="owner@example.com"), patch.object(app.boto3, "client") as client:
            client.return_value.get_user.return_value = {"UserAttributes": [{"Name": "email", "Value": "verified@example.com"}, {"Name": "email_verified", "Value": "true"}]}
            r = app.api(e, None)
            self.assertEqual(r["statusCode"], 200)
            self.assertEqual(json.loads(r["body"])["email"], "verified@example.com")

    def test_history_query_continues_beyond_three_filtered_pages(self):
        profile = {**self.profile, "connection_version": "current"}
        for i in range(35):
            app.put({"pk": self.profile["pk"], "sk": f"HISTORY#{1000 + i}", "connection_version": "old", "expires": int(app.time.time()) + 100})
        app.put({"pk": self.profile["pk"], "sk": "HISTORY#9999", "connection_version": "current", "expires": int(app.time.time()) + 100})
        rows = app.history(self.profile["pk"], profile)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["connection_version"], "current")

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

    def test_keep_toggle_is_idempotent_and_preserves_disabled_record(self):
        key = "KEEP#v1#ap-southeast-1#vol-demo"
        for enabled in (True, True, False, False):
            with self.subTest(enabled=enabled):
                reply = self.keep_resource("vol-demo", enabled)
                self.assertEqual(reply["statusCode"], 200)
                self.assertEqual(json.loads(reply["body"]), {"kept": enabled})
                self.assertIs(app.get(self.profile["pk"], key)["enabled"], enabled)

    def test_keep_uses_authenticated_tenant_and_current_connection(self):
        app.put({**self.profile, "pk": "TENANT#bob"})
        self.assertEqual(self.keep_resource("vol-demo", True, user="bob", tenant="alice", pk=self.profile["pk"])["statusCode"], 200)
        self.assertEqual(app.get(self.profile["pk"], "KEEP#v1#ap-southeast-1#vol-demo"), {})
        self.assertTrue(app.get("TENANT#bob", "KEEP#v1#ap-southeast-1#vol-demo")["enabled"])
        self.add_orphan("EBS", "vol-demo")
        self.assertEqual(self.scan()["findings"][0]["level"], "OBSERVING")
        self.assertEqual(self.keep_resource("vol-demo", True)["statusCode"], 200)
        self.profile["connection_version"] = "v2"
        app.put(self.profile)
        result = self.scan("22222222-2222-2222-2222-222222222222")
        self.assertEqual(result["findings"][0]["level"], "OBSERVING")
        self.assertEqual(app.get(self.profile["pk"], "KEEP#v2#ap-southeast-1#vol-demo"), {})
        self.assertEqual(self.keep_resource("vol-demo", False)["statusCode"], 200)
        self.assertTrue(app.get(self.profile["pk"], "KEEP#v1#ap-southeast-1#vol-demo")["enabled"])

    def test_keep_rejects_invalid_input_without_writing_exception(self):
        for body in ({"enabled": "true"}, {"enabled": 1}, {"enabled": None}, {"enabled": False, "region": "us-east-1"}, {"enabled": True, "resource_id": "vol/demo"}):
            with self.subTest(body=body):
                request = {"region": "ap-southeast-1", "resource_id": "vol-demo", **body}
                self.assertEqual(app.api(event("PUT", "/keep", body=request), None)["statusCode"], 400)
        self.assertEqual(list(app.all_items(self.profile["pk"], "KEEP#")), [])
        for missing in ("role_arn", "connection_version"):
            with self.subTest(missing=missing):
                disconnected = {k: v for k, v in self.profile.items() if k != missing}
                app.put(disconnected)
                self.assertEqual(self.keep_resource("vol-demo", True)["statusCode"], 400)
        self.assertEqual(list(app.all_items(self.profile["pk"], "KEEP#")), [])

    def test_ebs_and_eip_observation_boundaries_and_usage_reset(self):
        clock = int(app.time.time())
        volume = self.add_orphan("EBS", "vol-demo")
        address = self.add_orphan("EIP", "eipalloc-demo")
        for offset, expected in ((0, "OBSERVING"), (24 * 3600 - 1, "OBSERVING"), (24 * 3600, "REVIEW")):
            with self.subTest(offset=offset):
                result = self.scan_at(clock + offset)
                self.assertEqual({f["type"]: f["level"] for f in result["findings"]}, {"EBS": expected, "EIP": expected})
                for rid in ("vol-demo", "eipalloc-demo"):
                    self.assertEqual(self.observation(rid)["first"], clock)
        volume.update(State="in-use", Attachments=[{"InstanceId": "i-demo"}])
        address["AssociationId"] = "eipassoc-demo"
        self.assertEqual(self.scan_at(clock + 25 * 3600)["findings"], [])
        for rid in ("vol-demo", "eipalloc-demo"):
            self.assertEqual(self.observation(rid), {})
        volume.update(State="available", Attachments=[])
        address.pop("AssociationId")
        result = self.scan_at(clock + 26 * 3600)
        self.assertEqual({f["type"]: f["level"] for f in result["findings"]}, {"EBS": "OBSERVING", "EIP": "OBSERVING"})
        for rid in ("vol-demo", "eipalloc-demo"):
            self.assertEqual(self.observation(rid)["first"], clock + 26 * 3600)

    def test_observation_resets_after_gap_over_48_hours(self):
        clock = int(app.time.time())
        self.add_orphan("EBS", "vol-demo")
        self.add_orphan("EIP", "eipalloc-demo")
        self.scan_at(clock)
        at_boundary = self.scan_at(clock + 48 * 3600)
        self.assertTrue(all(f["level"] == "REVIEW" for f in at_boundary["findings"]))
        later = clock + 96 * 3600 + 1
        after_gap = self.scan_at(later)
        self.assertTrue(all(f["level"] == "OBSERVING" for f in after_gap["findings"]))
        for rid in ("vol-demo", "eipalloc-demo"):
            self.assertEqual(self.observation(rid)["first"], later)

    def test_all_exceptions_hide_findings_but_preserve_orphan_observation(self):
        clock = int(app.time.time())
        for kind in ("EBS", "EIP"):
            for exception in ("tag", "keep", "ignore"):
                with self.subTest(kind=kind, exception=exception):
                    self.volumes.clear()
                    self.addresses.clear()
                    rid = ("vol-" if kind == "EBS" else "eipalloc-") + exception
                    resource = self.add_orphan(kind, rid)
                    ignore_key = "IGNORE#v1#ap-southeast-1#" + rid
                    if exception == "tag":
                        resource["Tags"] = [{"Key": "guardian:keep", "Value": "true"}]
                    elif exception == "keep":
                        self.assertEqual(self.keep_resource(rid, True)["statusCode"], 200)
                    else:
                        app.put({"pk": self.profile["pk"], "sk": ignore_key, "expires": clock + 24 * 3600})
                    for offset in (0, 3600):
                        self.assertEqual(self.scan_at(clock + offset)["findings"], [])
                        self.assertEqual(self.observation(rid)["first"], clock)
                        self.assertEqual(self.observation(rid)["last"], clock + offset)
                    if exception == "tag":
                        resource["Tags"] = []
                    elif exception == "keep":
                        self.assertEqual(self.keep_resource(rid, False)["statusCode"], 200)
                    result = self.scan_at(clock + 24 * 3600)
                    self.assertEqual(len(result["findings"]), 1)
                    self.assertEqual(result["findings"][0]["level"], "REVIEW")
                    self.assertEqual(self.observation(rid)["first"], clock)

    def test_orphan_usage_resets_observation_even_while_kept(self):
        clock = int(app.time.time())
        volume = self.add_orphan("EBS", "vol-demo")
        address = self.add_orphan("EIP", "eipalloc-demo")
        for rid in ("vol-demo", "eipalloc-demo"):
            self.keep_resource(rid, True)
        self.assertEqual(self.scan_at(clock)["findings"], [])
        volume.update(State="in-use", Attachments=[{"InstanceId": "i-demo"}])
        address["AssociationId"] = "eipassoc-demo"
        self.assertEqual(self.scan_at(clock + 3600)["findings"], [])
        for rid in ("vol-demo", "eipalloc-demo"):
            self.assertEqual(self.observation(rid), {})

    def test_unkeep_does_not_override_active_ignore_or_tag(self):
        clock = int(app.time.time())
        volume = self.add_orphan("EBS", "vol-demo")
        self.keep_resource("vol-demo", True)
        with patch.object(app.time, "time", return_value=clock):
            self.assertEqual(app.api(event("PUT", "/ignore", body={"region": "ap-southeast-1", "resource_id": "vol-demo", "days": 1}), None)["statusCode"], 200)
        self.assertEqual(self.scan_at(clock)["findings"], [])
        self.keep_resource("vol-demo", False)
        self.assertEqual(self.scan_at(clock + 24 * 3600 - 1)["findings"], [])
        self.assertEqual(self.scan_at(clock + 24 * 3600)["findings"][0]["level"], "REVIEW")
        volume["Tags"] = [{"Key": "guardian:keep", "Value": "true"}]
        self.assertEqual(self.scan_at(clock + 25 * 3600)["findings"], [])

    def test_snapshot_incomplete_ami_inventory_never_produces_review(self):
        self.snapshots.append({"SnapshotId": "snap-demo", "StartTime": datetime.now(timezone.utc) - timedelta(days=100), "State": "completed", "VolumeSize": 40})
        self.images.extend({"ImageId": "ami-%03d" % index} for index in range(101))
        result = self.scan()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["findings"], [])
        self.assertIn({"type": "SNAPSHOT", "code": "INVENTORY_TRUNCATED"}, result["errors"])

    def test_snapshot_ami_access_denied_keeps_other_service_evidence(self):
        self.add_orphan("EBS", "vol-demo")
        self.snapshots.append({"SnapshotId": "snap-demo", "StartTime": datetime.now(timezone.utc) - timedelta(days=100), "State": "completed", "VolumeSize": 40})
        self.inventory_errors["describe_images"] = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "DescribeImages")
        result = self.scan()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual([f["type"] for f in result["findings"]], ["EBS"])
        self.assertIn({"type": "SNAPSHOT", "code": "AccessDenied"}, result["errors"])

    def test_findings_keep_legacy_and_new_fields_through_api_and_history(self):
        clock = int(app.time.time())
        self.add_orphan("EBS", "vol-demo")
        self.add_orphan("EIP", "eipalloc-demo")
        self.instances.append({"InstanceId": "i-demo", "State": {"Name": "running"}, "LaunchTime": datetime.now(timezone.utc) - timedelta(days=8)})
        end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        timestamps = [end - timedelta(hours=hour + 1) for hour in range(24)]
        self.cw.get_metric_data.side_effect = lambda **kwargs: {"MetricDataResults": [{"Id": ident, "StatusCode": "Complete", "Values": [0] * 24, "Timestamps": timestamps} for ident in ("cpu", "netin", "netout")]}
        self.snapshots.append({"SnapshotId": "snap-demo", "StartTime": datetime.now(timezone.utc) - timedelta(days=100), "State": "completed", "VolumeSize": 40})
        first = self.scan_at(clock)
        findings = first["findings"]
        required = {"type", "resource_id", "region", "level", "reason", "evidence", "rule_id", "recommendation"}
        self.assertEqual({f["type"] for f in findings}, {"EC2", "EBS", "EIP", "SNAPSHOT"})
        for finding in findings:
            self.assertTrue(required <= finding.keys())
            self.assertTrue(finding["rule_id"])
            self.assertTrue(finding["recommendation"])
            self.assertIsInstance(finding["evidence"], dict)
        second = self.scan_at(clock + 1)
        for path in ("/findings", "/scans/" + first["scan_id"], "/history"):
            with self.subTest(path=path), patch.object(app.time, "time", return_value=clock + 1):
                reply = app.api(event("GET", path), None)
                self.assertEqual(reply["statusCode"], 200)
                rows = json.loads(reply["body"])["results"]
                selected = next(row for row in rows if row["scan_id"] == first["scan_id"]) if path != "/findings" else rows[0]
                self.assertEqual(selected["findings"], findings if path != "/findings" else second["findings"])

    def test_nonfinite_or_negative_metrics_remain_json_safe(self):
        self.instances.append({"InstanceId": "i-demo", "State": {"Name": "running"}, "LaunchTime": datetime.now(timezone.utc) - timedelta(days=8)})
        end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        timestamps = [end - timedelta(hours=hour + 1) for hour in range(24)]
        for value in (float("nan"), float("inf"), -1):
            with self.subTest(value=value):
                self.cw.get_metric_data.side_effect = lambda **kwargs: {"MetricDataResults": [{"Id": ident, "StatusCode": "Complete", "Values": [value] + [0] * 23 if ident == "cpu" else [0] * 24, "Timestamps": timestamps} for ident in ("cpu", "netin", "netout")]}
                self.scan_sequence += 1
                result = self.scan(f"{self.scan_sequence:08d}-0000-0000-0000-000000000000")
                self.assertEqual(result["findings"][0]["level"], "INSUFFICIENT_DATA")
                json.dumps(result, allow_nan=False)

    def test_invalid_rds_nat_alb_and_nlb_metrics_persist_as_insufficient(self):
        old = datetime.now(timezone.utc) - timedelta(days=4)
        self.rds_instances.append({"DBInstanceIdentifier": "db-demo", "DBInstanceArn": "arn:db", "DBInstanceStatus": "available", "InstanceCreateTime": old, "Engine": "postgres", "DBInstanceClass": "db.t4g.micro"})
        self.nats.append({"NatGatewayId": "nat-demo", "State": "available", "CreateTime": old, "VpcId": "vpc-1", "SubnetId": "subnet-1"})
        self.load_balancers.extend([
            {"Type": "application", "State": {"Code": "active"}, "CreatedTime": old, "LoadBalancerName": "alb-demo", "LoadBalancerArn": "arn:aws:elasticloadbalancing:x:1:loadbalancer/app/alb-demo/id", "Scheme": "internet-facing"},
            {"Type": "network", "State": {"Code": "active"}, "CreatedTime": old, "LoadBalancerName": "nlb-demo", "LoadBalancerArn": "arn:aws:elasticloadbalancing:x:1:loadbalancer/net/nlb-demo/id", "Scheme": "internal"},
        ])
        end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        timestamps = [end - timedelta(hours=hour + 1) for hour in range(24)]
        invalid_values = (("negative", -1), ("boolean", False), ("null", None), ("string", "0"), ("nan", float("nan")), ("infinity", float("inf")), ("huge_integer", 10 ** 1000))
        expected = {kind: "INSUFFICIENT_DATA" for kind in ("RDS", "NAT_GATEWAY", "ALB", "NLB")}
        for label, value in invalid_values:
            for invalid_ids in (("cpu", "source", "requests", "flows"), ("connections", "destination", "requests", "flows")):
                with self.subTest(value=label, invalid_ids=invalid_ids):
                    self.cw.get_metric_data.side_effect = lambda **kwargs: {
                        "MetricDataResults": [
                            {"Id": query["Id"], "StatusCode": "Complete", "Values": [value] + [0] * 23 if query["Id"] in invalid_ids else [0] * 24, "Timestamps": timestamps}
                            for query in kwargs["MetricDataQueries"]
                        ]
                    }
                    result = self.scan()
                    self.assertEqual(result["status"], "SUCCEEDED")
                    self.assertEqual(result["errors"], [])
                    self.assertEqual({item["type"]: item["level"] for item in result["findings"]}, expected)
                    json.dumps(result, allow_nan=False)

    def test_nat_unequal_direction_sample_counts_use_each_direction_average(self):
        self.nats.append({"NatGatewayId": "nat-demo", "State": "available", "CreateTime": datetime.now(timezone.utc) - timedelta(days=4), "VpcId": "vpc-1", "SubnetId": "subnet-1"})
        end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        timestamps = [end - timedelta(hours=hour + 1) for hour in range(24)]
        for source_count, destination_count in ((24, 20), (20, 24)):
            with self.subTest(source_count=source_count, destination_count=destination_count):
                counts = {"source": source_count, "destination": destination_count}
                self.cw.get_metric_data.side_effect = lambda **kwargs: {
                    "MetricDataResults": [
                        {"Id": query["Id"], "StatusCode": "Complete", "Values": [0.48 * 1048576] * counts[query["Id"]], "Timestamps": timestamps[:counts[query["Id"]]]}
                        for query in kwargs["MetricDataQueries"]
                    ]
                }
                result = self.scan()
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertEqual(result["errors"], [])
                self.assertEqual(len(result["findings"]), 1)
                finding, = result["findings"]
                self.assertEqual(finding["type"], "NAT_GATEWAY")
                self.assertEqual(finding["level"], "REVIEW")
                self.assertAlmostEqual(finding["evidence"]["nat_mib_hour"], 0.96)
                json.dumps(result, allow_nan=False)

    def test_describe_addresses_called_without_max_results(self):
        self.addresses.append({"AllocationId": "eipalloc-test", "PublicIp": "203.0.113.10"})
        result = self.scan()
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["counts"]["EIP"], 1)
        self.ec2.describe_addresses.assert_called_with()

    def test_network_group_scan_full_pipeline(self):
        self.addresses.append({"AllocationId": "eipalloc-net-1", "PublicIp": "198.51.100.1"})
        self.nats.append({
            "NatGatewayId": "nat-net-1",
            "State": "available",
            "CreateTime": datetime.now(timezone.utc) - timedelta(days=5),
            "VpcId": "vpc-net-1",
            "SubnetId": "subnet-net-1",
        })
        self.load_balancers.append({
            "Type": "application",
            "LoadBalancerName": "alb-net-1",
            "LoadBalancerArn": "arn:aws:elasticloadbalancing:ap-southeast-1:123456789012:loadbalancer/app/alb-net-1/111",
            "State": {"Code": "active"},
            "CreatedTime": datetime.now(timezone.utc) - timedelta(days=5),
            "Scheme": "internet-facing",
        })
        self.load_balancers.append({
            "Type": "network",
            "LoadBalancerName": "nlb-net-1",
            "LoadBalancerArn": "arn:aws:elasticloadbalancing:ap-southeast-1:123456789012:loadbalancer/net/nlb-net-1/222",
            "State": {"Code": "active"},
            "CreatedTime": datetime.now(timezone.utc) - timedelta(days=5),
            "Scheme": "internet-facing",
        })
        end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        timestamps = [end - timedelta(hours=i + 1) for i in range(24)]
        self.cw.get_metric_data.side_effect = lambda **kwargs: {
            "MetricDataResults": [
                {"Id": query["Id"], "StatusCode": "Complete", "Values": [0] * 24, "Timestamps": timestamps}
                for query in kwargs["MetricDataQueries"]
            ]
        }
        result = self.scan()
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["counts"]["EIP"], 1)
        self.assertEqual(result["counts"]["NAT_GATEWAY"], 1)
        self.assertEqual(result["counts"]["ALB"], 1)
        self.assertEqual(result["counts"]["NLB"], 1)
        finding_types = {f["type"] for f in result["findings"]}
        self.assertEqual(finding_types, {"EIP", "NAT_GATEWAY", "ALB", "NLB"})


if __name__ == "__main__":
    unittest.main()
