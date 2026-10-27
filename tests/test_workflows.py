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
        self.now = datetime(2026, 10, 26, 9, 17, tzinfo=timezone.utc)
        self.clock_patch = patch.object(app.time, "time", return_value=self.now.timestamp())
        self.clock_patch.start()
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
        self.clock_patch.stop()
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
        kind = 'EBS' if rid.startswith('vol-') else 'EIP'
        return app.get(self.profile["pk"], "OBS#" + self.profile["connection_version"] + "#ap-southeast-1#" + kind + "#" + rid)

    def add_orphan(self, kind, rid):
        if kind == "EBS":
            item = {"VolumeId": rid, "State": "available", "Attachments": [], "Size": 40}
            self.volumes.append(item)
        else:
            item = {"AllocationId": rid}
            self.addresses.append(item)
        return item

    def add_metric_resources(self):
        old = self.now - timedelta(days=8)
        self.instances.append({'InstanceId': 'i-demo', 'State': {'Name': 'running'}, 'LaunchTime': old})
        self.rds_instances.append({'DBInstanceIdentifier': 'db-demo', 'DBInstanceArn': 'arn:db',
                                   'DBInstanceStatus': 'available', 'InstanceCreateTime': old,
                                   'Engine': 'postgres', 'DBInstanceClass': 'db.t4g.micro'})
        self.nats.append({'NatGatewayId': 'nat-demo', 'State': 'available', 'CreateTime': old,
                          'VpcId': 'vpc-demo', 'SubnetId': 'subnet-demo'})
        for name, kind, path in (('alb-demo', 'application', 'app'), ('nlb-demo', 'network', 'net')):
            self.load_balancers.append({'Type': kind, 'State': {'Code': 'active'}, 'CreatedTime': old,
                                        'LoadBalancerName': name, 'Scheme': 'internet-facing',
                                        'LoadBalancerArn': 'arn:aws:elasticloadbalancing:ap-southeast-1:123456789012:loadbalancer/' + path + '/' + name + '/id'})

    @staticmethod
    def zero_metric_response(**kwargs):
        timestamps = [kwargs['EndTime'] - timedelta(hours=hour + 1) for hour in range(24)]
        return {'MetricDataResults': [{'Id': query['Id'], 'StatusCode': 'Complete',
                                       'Values': [0] * 24, 'Timestamps': timestamps}
                                      for query in kwargs['MetricDataQueries']]}

    def test_all_nine_types_have_context_thresholds_and_persisted_explanations(self):
        settings = {'cpu_percent': 7, 'network_mib_hour': 2, 'rds_cpu_percent': 8,
                    'rds_connections': 3, 'nat_mib_hour': 4, 'alb_requests_hour': 5,
                    'nlb_new_flows_hour': 6, 'orphan_hours': 12, 'snapshot_days': 60}
        self.profile['settings'] = app.config(settings)
        app.put(self.profile)
        self.add_metric_resources()
        self.add_orphan('EBS', 'vol-demo')
        self.add_orphan('EIP', 'eipalloc-demo')
        self.snapshots.append({'SnapshotId': 'snap-demo', 'State': 'completed', 'VolumeSize': 40,
                               'StartTime': self.now - timedelta(days=100)})
        self.s3.list_buckets.return_value = {'Buckets': [{'Name': 'demo', 'BucketRegion': 'ap-southeast-1'}]}
        self.uploads.append({'Key': 'nested/object', 'UploadId': 'upload-demo', 'Initiated': self.now - timedelta(days=8)})
        self.cw.get_metric_data.side_effect = self.zero_metric_response
        result = self.scan_at(int(self.now.timestamp()))
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertEqual(result['errors'], [])
        findings = {item['type']: item for item in result['findings']}
        self.assertEqual(set(findings), {'EC2', 'EBS', 'EIP', 'SNAPSHOT', 'RDS', 'S3_MULTIPART', 'NAT_GATEWAY', 'ALB', 'NLB'})
        thresholds = {
            'EC2': {'cpu_percent': 7, 'network_mib_hour': 2},
            'RDS': {'rds_cpu_percent': 8, 'rds_connections': 3},
            'NAT_GATEWAY': {'nat_mib_hour': 4}, 'ALB': {'alb_requests_hour': 5},
            'NLB': {'nlb_new_flows_hour': 6}, 'EBS': {'orphan_hours': 12},
            'EIP': {'orphan_hours': 12}, 'SNAPSHOT': {'snapshot_days': 60},
            'S3_MULTIPART': {'multipart_days': 7},
        }
        statistics = {'EC2': {'cpu': 'Maximum', 'netin': 'Sum', 'netout': 'Sum'},
                      'RDS': {'cpu': 'Maximum', 'connections': 'Maximum'},
                      'NAT_GATEWAY': {'source': 'Sum', 'destination': 'Sum'},
                      'ALB': {'requests': 'Sum'}, 'NLB': {'flows': 'Sum'}}
        for kind, finding in findings.items():
            with self.subTest(kind=kind):
                for key in ('rule_id', 'reason', 'recommendation', 'resource_id', 'finding_id'):
                    self.assertTrue(finding[key])
                evidence = finding['evidence']
                self.assertEqual(evidence['thresholds'], thresholds[kind])
                for key, value in {'account_id': '123456789012', 'region': 'ap-southeast-1',
                                   'evaluated_at': self.now.isoformat()}.items():
                    self.assertEqual(finding[key], value)
                    self.assertEqual(evidence[key], value)
                if kind in statistics:
                    end = self.now.replace(minute=0)
                    self.assertEqual(evidence['observation_start'], (end - timedelta(hours=24)).isoformat())
                    self.assertEqual(evidence['observation_end'], end.isoformat())
                    self.assertEqual(evidence['metric_period_seconds'], 3600)
                    self.assertEqual(evidence['metric_statistics'], statistics[kind])
                    self.assertEqual(evidence['sample_counts'], dict.fromkeys(statistics[kind], 24))
                    self.assertEqual(evidence['missing_metrics'], [])
                    self.assertEqual(evidence['invalid_metrics'], [])
                    self.assertEqual(evidence['calculation_errors'], [])
        for path in ('/findings', '/scans/' + result['scan_id'], '/history'):
            with self.subTest(path=path):
                reply = app.api(event('GET', path), None)
                self.assertEqual(reply['statusCode'], 200)
                rows = json.loads(reply['body'])['results']
                stored = next(row for row in rows if row['scan_id'] == result['scan_id'])
                self.assertNotIn('candidates', stored)
                self.assertEqual(stored['findings'], result['findings'])
                json.dumps(stored, allow_nan=False)

    def test_young_or_missing_creation_metric_resources_do_not_query_cloudwatch(self):
        self.add_metric_resources()
        resources = [(self.instances[0], 'LaunchTime'), (self.rds_instances[0], 'InstanceCreateTime'),
                     (self.nats[0], 'CreateTime'), *[(item, 'CreatedTime') for item in self.load_balancers]]
        for issue in ('RESOURCE_TOO_YOUNG', 'MISSING_CREATION_TIME'):
            with self.subTest(issue=issue):
                for resource, key in resources:
                    if issue == 'RESOURCE_TOO_YOUNG':
                        resource[key] = self.now - timedelta(hours=1)
                    else:
                        resource.pop(key, None)
                self.cw.reset_mock()
                result = self.scan()
                self.assertEqual(result['status'], 'SUCCEEDED')
                self.assertEqual({finding['type'] for finding in result['findings']}, {'EC2', 'RDS', 'NAT_GATEWAY', 'ALB', 'NLB'})
                for finding in result['findings']:
                    self.assertEqual(finding['level'], 'INSUFFICIENT_DATA')
                    self.assertIn(issue, finding['evidence']['data_issues'])
                self.cw.get_metric_data.assert_not_called()

    def test_s3_seven_day_boundary_is_strict_using_scan_clock(self):
        self.s3.list_buckets.return_value = {'Buckets': [{'Name': 'demo', 'BucketRegion': 'ap-southeast-1'}]}
        for seconds, expected in ((7 * 86400 - 1, 0), (7 * 86400, 0), (7 * 86400 + 1, 1)):
            with self.subTest(age_seconds=seconds):
                self.uploads[:] = [{'Key': 'object', 'UploadId': 'upload-demo', 'Initiated': self.now - timedelta(seconds=seconds)}]
                result = self.scan_at(int(self.now.timestamp()))
                self.assertEqual(len(result['findings']), expected)
                if expected:
                    self.assertEqual(result['findings'][0]['level'], 'REVIEW')

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
        self.snapshots.append({"SnapshotId": "snap-used", "StartTime": self.now - timedelta(days=100), "State": "completed", "VolumeSize": 40})
        self.images.append({"BlockDeviceMappings": [{"Ebs": {"SnapshotId": "snap-used"}}]})
        self.assertFalse(any(item["type"] == "SNAPSHOT" for item in self.scan()["findings"]))

    def test_snapshot_referenced_by_disabled_ami_is_not_flagged(self):
        for rid in ("snap-disabled-ami", "snap-unused"):
            self.snapshots.append({"SnapshotId": rid, "StartTime": self.now - timedelta(days=100), "State": "completed", "VolumeSize": 40})
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
        self.instances.append({"InstanceId": "i-demo", "State": {"Name": "stopped"}, "LaunchTime": self.now - timedelta(days=4)})
        self.ec2.describe_addresses.side_effect = ClientError({"Error": {"Code": "UnauthorizedOperation", "Message": "denied"}}, "DescribeAddresses")
        result = self.scan()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["counts"]["EC2"], 1)
        self.assertIn({"type": "EIP", "code": "UnauthorizedOperation"}, result["errors"])

    def test_missing_ec2_and_rds_metrics_are_insufficient(self):
        self.instances.append({"InstanceId": "i-demo", "State": {"Name": "running"}, "LaunchTime": self.now - timedelta(days=4)})
        self.rds_instances.append({"DBInstanceIdentifier": "db-demo", "DBInstanceArn": "arn:db", "DBInstanceStatus": "available", "InstanceCreateTime": self.now - timedelta(days=4), "Engine": "postgres", "DBInstanceClass": "db.t4g.micro"})
        findings = self.scan()["findings"]
        self.assertEqual({item["type"]: item["level"] for item in findings}, {"EC2": "INSUFFICIENT_DATA", "RDS": "INSUFFICIENT_DATA"})

    def test_nat_real_zero_is_review(self):
        self.nats.append({"NatGatewayId": "nat-demo", "State": "available", "CreateTime": self.now - timedelta(days=4), "VpcId": "vpc-1", "SubnetId": "subnet-1"})
        timestamps = [self.now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=index + 1) for index in range(20)]
        self.cw.get_metric_data.side_effect = lambda **kwargs: {"MetricDataResults": [{"Id": query["Id"], "StatusCode": "Complete", "Values": [0] * 20, "Timestamps": timestamps} for query in kwargs["MetricDataQueries"]]}
        finding = next(item for item in self.scan()["findings"] if item["type"] == "NAT_GATEWAY")
        self.assertEqual(finding["level"], "REVIEW")
        self.assertEqual(finding["evidence"]["nat_mib_hour"], 0)

    def test_stale_s3_multipart_is_review_and_structurally_identified(self):
        self.s3.list_buckets.return_value = {"Buckets": [{"Name": "demo", "BucketRegion": "ap-southeast-1"}]}
        self.uploads.append({"Key": "a/b", "UploadId": "upload#1", "Initiated": self.now - timedelta(days=8)})
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
        end = self.now
        start = end - timedelta(hours=24)
        timestamp = start + timedelta(hours=1)
        self.cw.get_metric_data.side_effect = [
            {"MetricDataResults": [{"Id": "cpu", "StatusCode": "PartialData", "Timestamps": [timestamp], "Values": [0]}], "NextToken": "page2"},
            {"MetricDataResults": [{"Id": "cpu", "StatusCode": "Complete", "Timestamps": [timestamp], "Values": [0]}]},
        ]
        values = collectors.metric_series(self.cw, [{"Id": "cpu"}], start, end)
        self.assertEqual(values, {"cpu": [0]})

    def test_metric_series_ignores_outside_window_and_keeps_real_boundary_zero(self):
        end = self.now.replace(minute=0)
        start = end - timedelta(hours=24)
        self.cw.get_metric_data.side_effect = None
        self.cw.get_metric_data.return_value = {'MetricDataResults': [{
            'Id': 'cpu', 'StatusCode': 'Complete',
            'Timestamps': [start - timedelta(hours=1), start, end - timedelta(hours=1), end],
            'Values': [100, 0, 1, 100],
        }]}
        self.assertEqual(collectors.metric_series(self.cw, [{'Id': 'cpu'}], start, end), {'cpu': [0, 1]})

    def test_metric_series_rejects_samples_outside_hourly_grid(self):
        end = self.now.replace(minute=0)
        start = end - timedelta(hours=24)
        self.cw.get_metric_data.side_effect = None
        for offset in (timedelta(minutes=1), timedelta(seconds=1), timedelta(microseconds=1)):
            with self.subTest(offset=offset):
                self.cw.get_metric_data.return_value = {'MetricDataResults': [{
                    'Id': 'cpu', 'StatusCode': 'Complete',
                    'Timestamps': [start + offset], 'Values': [0],
                }]}
                with self.assertRaisesRegex(ValueError, 'hourly grid'):
                    collectors.metric_series(self.cw, [{'Id': 'cpu'}], start, end)

    def test_dense_minute_samples_cannot_claim_hourly_coverage_for_metric_rules(self):
        self.add_metric_resources()
        self.add_orphan('EBS', 'vol-demo')
        cases = (
            ('AWS/EC2', 'EC2', 'EC2'), ('AWS/RDS', 'RDS', 'RDS'),
            ('AWS/NATGateway', 'NAT_GATEWAY', 'NAT_GATEWAY'),
            ('AWS/ApplicationELB', 'ALB', 'ELB'), ('AWS/NetworkELB', 'NLB', 'ELB'),
        )
        all_types = {'EC2', 'EBS', 'RDS', 'NAT_GATEWAY', 'ALB', 'NLB'}
        for namespace, kind, error_type in cases:
            with self.subTest(kind=kind):
                def metrics(**kwargs):
                    response = self.zero_metric_response(**kwargs)
                    if kwargs['MetricDataQueries'][0]['MetricStat']['Metric']['Namespace'] == namespace:
                        for series in response['MetricDataResults']:
                            series['Timestamps'] = [kwargs['EndTime'] - timedelta(minutes=index + 1)
                                                    for index in range(24)]
                    return response

                self.cw.get_metric_data.side_effect = metrics
                result = self.scan()
                self.assertEqual(result['status'], 'PARTIAL')
                self.assertIn({'type': error_type, 'code': 'METRIC_DATA_ERROR'}, result['errors'])
                findings = {item['type']: item for item in result['findings']}
                self.assertNotIn(kind, findings)
                # An ALB error ends the shared ELB collector before NLB evaluation.
                excluded = {kind, 'NLB'} if kind == 'ALB' else {kind}
                self.assertEqual(set(findings), all_types - excluded)
                self.assertEqual(findings['EBS']['level'], 'OBSERVING')
                self.assertTrue(all(item['level'] == 'REVIEW' for name, item in findings.items()
                                    if name != 'EBS'))

    def test_metric_series_rejects_malformed_status_and_conflicting_duplicates(self):
        end = self.now.replace(minute=0)
        start = end - timedelta(hours=24)
        valid = {'Id': 'cpu', 'StatusCode': 'Complete', 'Timestamps': [start], 'Values': [0]}
        malformed = (
            None, {'MetricDataResults': {}}, {'MetricDataResults': [None]},
            {'MetricDataResults': [{**valid, 'Id': 'unexpected'}]},
            {'MetricDataResults': [{**valid, 'StatusCode': 'InternalError'}]},
            {'MetricDataResults': [{**valid, 'StatusCode': 'Forbidden'}]},
            {'MetricDataResults': [{**valid, 'StatusCode': None}]},
            {'MetricDataResults': [{**valid, 'Values': []}]},
            {'MetricDataResults': [{**valid, 'Values': None}]},
            {'MetricDataResults': [{**valid, 'Timestamps': ['2026-10-01T00:00:00Z']}]},
            {'MetricDataResults': [{**valid, 'Timestamps': [start.replace(tzinfo=None)]}]},
            {'MetricDataResults': [{**valid, 'Timestamps': [start, start], 'Values': [0, 1]}]},
            {'MetricDataResults': [{**valid, 'Timestamps': [start, start], 'Values': [0, False]}]},
            {'MetricDataResults': [valid], 'NextToken': 123},
        )
        self.cw.get_metric_data.side_effect = None
        for page in malformed:
            with self.subTest(page=page):
                self.cw.get_metric_data.return_value = page
                with self.assertRaises(ValueError):
                    collectors.metric_series(self.cw, [{'Id': 'cpu'}], start, end)
        self.cw.get_metric_data.side_effect = [
            {'MetricDataResults': [valid], 'NextToken': 'repeated'},
            {'MetricDataResults': [valid], 'NextToken': 'repeated'},
        ]
        with self.assertRaises(ValueError):
            collectors.metric_series(self.cw, [{'Id': 'cpu'}], start, end)

    def test_malformed_cloudwatch_response_is_partial_without_false_idle_finding(self):
        self.add_metric_resources()
        self.add_orphan('EBS', 'vol-demo')

        def metrics(**kwargs):
            if kwargs['MetricDataQueries'][0]['MetricStat']['Metric']['Namespace'] == 'AWS/RDS':
                return {'MetricDataResults': [{'Id': 'cpu', 'StatusCode': 'Forbidden', 'Values': [], 'Timestamps': []}]}
            return self.zero_metric_response(**kwargs)

        self.cw.get_metric_data.side_effect = metrics
        result = self.scan()
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertIn({'type': 'RDS', 'code': 'METRIC_DATA_ERROR'}, result['errors'])
        self.assertEqual({item['type'] for item in result['findings']}, {'EC2', 'EBS', 'NAT_GATEWAY', 'ALB', 'NLB'})
        self.assertTrue(all(item['level'] == 'REVIEW' for item in result['findings'] if item['type'] != 'EBS'))

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
        app.put({"pk": self.profile["pk"], "sk": "RESULT#ap-southeast-1", "scan_id": scan_id,
                 "status": "QUEUED", "started_at": int(app.time.time()), "region": "ap-southeast-1", "connection_version": "v1"})
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
        self.assertEqual(result['total_candidate_count'], 100)
        self.assertEqual(len(result['candidates']), 100)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertIn({"type": "EBS", "code": "RESOURCE_LIMIT"}, result["errors"])

    def test_candidate_byte_budget_reports_partial_and_keeps_history_readable(self):
        findings = [
            {'type': 'EBS', 'resource_id': 'vol-' + str(index), 'region': 'ap-southeast-1',
             'finding_id': collectors.finding_id('EBS', 'ap-southeast-1', 'vol-' + str(index)),
             'level': 'REVIEW', 'rule_id': 'EBS_UNATTACHED', 'reason': 'Unattached volume',
             'recommendation': 'Confirm retention with owner', 'evidence': {'details': 'x' * (40 * 1024)}}
            for index in range(5)
        ]
        with patch.object(app, 'collect_region', return_value={'counts': {'EBS': 5}, 'findings': findings,
                                                             'errors': [], 'partial': False}):
            result = self.scan()
        retained = len(result['candidates'])
        self.assertGreater(retained, 0)
        self.assertLess(retained, len(findings))
        self.assertEqual(result['total_candidate_count'], 5)
        self.assertEqual(result['finding_count'], retained)
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertIn({'type': 'FINDING', 'code': 'CANDIDATE_LIMIT'}, result['errors'])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode('utf-8')), app.RESULT_BYTE_LIMIT)
        detail = json.loads(app.api(event('GET', '/scans/' + result['scan_id']), None)['body'])['results'][0]
        self.assertEqual(detail['findings'], result['findings'])
        self.assertNotIn('candidates', detail)

    def test_time_budget_marks_current_and_remaining_collectors(self):
        remaining_calls = 0
        def remaining():
            nonlocal remaining_calls
            remaining_calls += 1
            return 200000 if remaining_calls == 1 else 20000

        self.context.get_remaining_time_in_millis.side_effect = remaining
        result = self.scan()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertTrue(result["errors"])
        self.assertTrue(all(error["code"] == "TIME_BUDGET" for error in result["errors"]))
        self.assertGreater(remaining_calls, 1)
        self.sess.client.assert_not_called()

    def test_s3_bucket_and_upload_pagination_preserves_upload_identity(self):
        self.s3.list_buckets.side_effect = [
            {"Buckets": [{"Name": "demo", "BucketRegion": "ap-southeast-1"}], "ContinuationToken": "next"},
            {"Buckets": []},
        ]
        paginator = MagicMock()
        initiated = self.now - timedelta(days=8)
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
        old = self.now - timedelta(days=4)
        self.rds_instances.append({"DBInstanceIdentifier": "db-demo", "DBInstanceArn": "arn:db", "DBInstanceStatus": "available", "InstanceCreateTime": old, "Engine": "postgres", "DBInstanceClass": "db.t4g.micro"})
        self.load_balancers.extend([
            {"Type": "application", "State": {"Code": "active"}, "CreatedTime": old, "LoadBalancerName": "alb-demo", "LoadBalancerArn": "arn:aws:elasticloadbalancing:x:1:loadbalancer/app/alb-demo/id", "Scheme": "internet-facing"},
            {"Type": "network", "State": {"Code": "active"}, "CreatedTime": old, "LoadBalancerName": "nlb-demo", "LoadBalancerArn": "arn:aws:elasticloadbalancing:x:1:loadbalancer/net/nlb-demo/id", "Scheme": "internal"},
        ])
        timestamps = [self.now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=index + 1) for index in range(20)]
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

    def test_expired_or_future_observations_restart_orphan_window(self):
        clock = int(self.now.timestamp())
        self.add_orphan('EBS', 'vol-demo')
        self.add_orphan('EIP', 'eipalloc-demo')
        for issue, overrides in (
            ('expired', {'expires': clock}),
            ('future_last', {'last': clock + 1}),
            ('future_first', {'first': clock + 1}),
        ):
            with self.subTest(issue=issue):
                for kind, ident in (('EBS', 'vol-demo'), ('EIP', 'eipalloc-demo')):
                    app.put({'pk': self.profile['pk'], 'sk': 'OBS#v1#ap-southeast-1#' + kind + '#' + ident,
                             'first': clock - 30 * 3600, 'last': clock - 3600,
                             'expires': clock + 7 * 86400, **overrides})
                restarted = self.scan_at(clock)
                self.assertEqual({item['type']: item['level'] for item in restarted['findings']},
                                 {'EBS': 'OBSERVING', 'EIP': 'OBSERVING'})
                for item in restarted['findings']:
                    self.assertEqual(item['evidence']['observed_hours'], 0)
                    self.assertEqual(self.observation(item['resource_id'])['first'], clock)
                at_threshold = self.scan_at(clock + 24 * 3600)
                self.assertEqual({item['type']: item['level'] for item in at_threshold['findings']},
                                 {'EBS': 'REVIEW', 'EIP': 'REVIEW'})

    def test_observation_migrates_native_legacy_prefix_and_separates_resource_types(self):
        clock = int(self.now.timestamp())
        self.add_orphan('EBS', 'vol-demo')
        legacy_key = 'OBS#v1#ap-southeast-1#vol-demo'
        app.put({'pk': self.profile['pk'], 'sk': legacy_key, 'first': clock - 30 * 3600,
                 'last': clock - 3600, 'expires': clock + 86400})
        result = self.scan_at(clock)
        self.assertEqual(result['findings'][0]['level'], 'REVIEW')
        self.assertEqual(self.observation('vol-demo')['first'], clock - 30 * 3600)
        self.assertEqual(app.get(self.profile['pk'], legacy_key), {})
        self.volumes.clear()
        self.add_orphan('EBS', 'shared-id')
        self.add_orphan('EIP', 'shared-id')
        self.scan_at(clock)
        self.volumes[0].update(State='in-use', Attachments=[{'InstanceId': 'i-demo'}])
        next_scan = self.scan_at(clock + 24 * 3600)
        self.assertEqual([(item['type'], item['level']) for item in next_scan['findings']], [('EIP', 'REVIEW')])
        self.assertEqual(app.get(self.profile['pk'], 'OBS#v1#ap-southeast-1#EBS#shared-id'), {})
        self.assertEqual(app.get(self.profile['pk'], 'OBS#v1#ap-southeast-1#EIP#shared-id')['first'], clock)

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
        self.snapshots.append({"SnapshotId": "snap-demo", "StartTime": self.now - timedelta(days=100), "State": "completed", "VolumeSize": 40})
        self.images.extend({"ImageId": "ami-%03d" % index} for index in range(101))
        result = self.scan()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["findings"], [])
        self.assertIn({"type": "SNAPSHOT", "code": "INVENTORY_TRUNCATED"}, result["errors"])

    def test_snapshot_ami_access_denied_keeps_other_service_evidence(self):
        self.add_orphan("EBS", "vol-demo")
        self.snapshots.append({"SnapshotId": "snap-demo", "StartTime": self.now - timedelta(days=100), "State": "completed", "VolumeSize": 40})
        self.inventory_errors["describe_images"] = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "DescribeImages")
        result = self.scan()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual([f["type"] for f in result["findings"]], ["EBS"])
        self.assertIn({"type": "SNAPSHOT", "code": "AccessDenied"}, result["errors"])

    def test_findings_keep_legacy_and_new_fields_through_api_and_history(self):
        clock = int(app.time.time())
        self.add_orphan("EBS", "vol-demo")
        self.add_orphan("EIP", "eipalloc-demo")
        self.instances.append({"InstanceId": "i-demo", "State": {"Name": "running"}, "LaunchTime": self.now - timedelta(days=8)})
        end = self.now.replace(minute=0, second=0, microsecond=0)
        timestamps = [end - timedelta(hours=hour + 1) for hour in range(24)]
        self.cw.get_metric_data.side_effect = lambda **kwargs: {"MetricDataResults": [{"Id": ident, "StatusCode": "Complete", "Values": [0] * 24, "Timestamps": timestamps} for ident in ("cpu", "netin", "netout")]}
        self.snapshots.append({"SnapshotId": "snap-demo", "StartTime": self.now - timedelta(days=100), "State": "completed", "VolumeSize": 40})
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
        self.instances.append({"InstanceId": "i-demo", "State": {"Name": "running"}, "LaunchTime": self.now - timedelta(days=8)})
        end = self.now.replace(minute=0, second=0, microsecond=0)
        timestamps = [end - timedelta(hours=hour + 1) for hour in range(24)]
        for value in (float("nan"), float("inf"), -1):
            with self.subTest(value=value):
                self.cw.get_metric_data.side_effect = lambda **kwargs: {"MetricDataResults": [{"Id": ident, "StatusCode": "Complete", "Values": [value] + [0] * 23 if ident == "cpu" else [0] * 24, "Timestamps": timestamps} for ident in ("cpu", "netin", "netout")]}
                self.scan_sequence += 1
                result = self.scan(f"{self.scan_sequence:08d}-0000-0000-0000-000000000000")
                self.assertEqual(result["findings"][0]["level"], "INSUFFICIENT_DATA")
                evidence = result['findings'][0]['evidence']
                self.assertEqual(evidence['sample_counts'], {'cpu': 23, 'netin': 24, 'netout': 24})
                self.assertEqual(evidence['invalid_metrics'], ['cpu'])
                self.assertEqual(evidence['missing_metrics'], [])
                self.assertEqual(evidence['calculation_errors'], [])
                json.dumps(result, allow_nan=False)

    def test_invalid_rds_nat_alb_and_nlb_metrics_persist_as_insufficient(self):
        old = self.now - timedelta(days=4)
        self.rds_instances.append({"DBInstanceIdentifier": "db-demo", "DBInstanceArn": "arn:db", "DBInstanceStatus": "available", "InstanceCreateTime": old, "Engine": "postgres", "DBInstanceClass": "db.t4g.micro"})
        self.nats.append({"NatGatewayId": "nat-demo", "State": "available", "CreateTime": old, "VpcId": "vpc-1", "SubnetId": "subnet-1"})
        self.load_balancers.extend([
            {"Type": "application", "State": {"Code": "active"}, "CreatedTime": old, "LoadBalancerName": "alb-demo", "LoadBalancerArn": "arn:aws:elasticloadbalancing:x:1:loadbalancer/app/alb-demo/id", "Scheme": "internet-facing"},
            {"Type": "network", "State": {"Code": "active"}, "CreatedTime": old, "LoadBalancerName": "nlb-demo", "LoadBalancerArn": "arn:aws:elasticloadbalancing:x:1:loadbalancer/net/nlb-demo/id", "Scheme": "internal"},
        ])
        end = self.now.replace(minute=0, second=0, microsecond=0)
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
                    for finding in result['findings']:
                        evidence = finding['evidence']
                        invalid_names = set(evidence['sample_counts']) & set(invalid_ids)
                        self.assertEqual(set(evidence['invalid_metrics']), invalid_names)
                        self.assertEqual(evidence['missing_metrics'], [])
                        self.assertEqual(evidence['calculation_errors'], [])
                        self.assertEqual(evidence['coverage'], round(23 / 24, 3))
                        self.assertEqual(evidence['sample_counts'], {key: 23 if key in invalid_names else 24 for key in evidence['sample_counts']})
                    detail = json.loads(app.api(event('GET', '/scans/' + result['scan_id']), None)['body'])
                    self.assertEqual(detail['results'][0]['findings'], result['findings'])
                    self.assertNotIn('candidates', detail['results'][0])
                    json.dumps(result, allow_nan=False)

    def test_aggregate_overflow_diagnostics_survive_history_without_raw_samples(self):
        self.add_metric_resources()

        def metrics(**kwargs):
            page = self.zero_metric_response(**kwargs)
            for row in page['MetricDataResults']:
                if row['Id'] in {'netin', 'netout', 'source', 'destination', 'requests', 'flows'}:
                    row['Values'] = [1e308] * 24
            return page

        self.cw.get_metric_data.side_effect = metrics
        result = self.scan()
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertEqual(result['errors'], [])
        self.assertEqual({finding['type'] for finding in result['findings']}, {'EC2', 'RDS', 'NAT_GATEWAY', 'ALB', 'NLB'})
        for finding in result['findings']:
            with self.subTest(kind=finding['type']):
                evidence = finding['evidence']
                if finding['type'] == 'RDS':
                    self.assertEqual(finding['level'], 'REVIEW')
                    continue
                self.assertEqual(finding['level'], 'INSUFFICIENT_DATA')
                self.assertEqual(evidence['calculation_errors'], ['AGGREGATE_OVERFLOW'])
                self.assertTrue(evidence['invalid_metrics'])
                self.assertEqual(evidence['missing_metrics'], [])
                self.assertTrue(all(count == 24 for count in evidence['sample_counts'].values()))
                self.assertNotIn('values', evidence)
                self.assertNotIn('samples', evidence)
        for path in ('/scans/' + result['scan_id'], '/history'):
            reply = app.api(event('GET', path), None)
            stored = next(row for row in json.loads(reply['body'])['results'] if row['scan_id'] == result['scan_id'])
            self.assertEqual(stored['findings'], result['findings'])
            self.assertNotIn('candidates', stored)
            json.dumps(stored, allow_nan=False)

    def test_nat_unequal_direction_sample_counts_use_each_direction_average(self):
        self.nats.append({"NatGatewayId": "nat-demo", "State": "available", "CreateTime": self.now - timedelta(days=4), "VpcId": "vpc-1", "SubnetId": "subnet-1"})
        end = self.now.replace(minute=0, second=0, microsecond=0)
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
            "CreateTime": self.now - timedelta(days=5),
            "VpcId": "vpc-net-1",
            "SubnetId": "subnet-net-1",
        })
        self.load_balancers.append({
            "Type": "application",
            "LoadBalancerName": "alb-net-1",
            "LoadBalancerArn": "arn:aws:elasticloadbalancing:ap-southeast-1:123456789012:loadbalancer/app/alb-net-1/111",
            "State": {"Code": "active"},
            "CreatedTime": self.now - timedelta(days=5),
            "Scheme": "internet-facing",
        })
        self.load_balancers.append({
            "Type": "network",
            "LoadBalancerName": "nlb-net-1",
            "LoadBalancerArn": "arn:aws:elasticloadbalancing:ap-southeast-1:123456789012:loadbalancer/net/nlb-net-1/222",
            "State": {"Code": "active"},
            "CreatedTime": self.now - timedelta(days=5),
            "Scheme": "internet-facing",
        })
        end = self.now.replace(minute=0, second=0, microsecond=0)
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
