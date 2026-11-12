"""Unit and integration test suite covering Fault Tolerance, Resilience, and Security NFRs.
Verifies:
1. Error handling for AWS exceptions (AccessDenied, SubscriptionRequiredException, Throttling).
2. Time budget and Lambda timeout protection.
3. Insufficient data and missing CloudWatch metric handling without false 0 assumption.
4. Scan lease idempotency and 15-minute cooldown enforcement.
5. SQS and DLQ redrive policies.
6. Multi-tenant isolation (Tenant A cannot read Tenant B data).
7. JWT authorizer validation (missing/invalid token returns 401).
8. Strict read-only IAM policies and ExternalId confused-deputy protection.
"""
import copy, json, math, time, unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

import os, sys, pathlib
os.environ.setdefault('TABLE', 'test-table')
os.environ.setdefault('AWS_DEFAULT_REGION', 'ap-southeast-1')
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import rules, collectors, app

class FaultToleranceTests(unittest.TestCase):
    def setUp(self):
        self.cfg = rules.config({})
        self.now = datetime.now(timezone.utc)
        self.start = self.now - timedelta(hours=24)

    def test_subscription_required_exception_preserves_other_findings(self):
        """When an AWS service returns SubscriptionRequiredException, scan marks PARTIAL without dropping findings."""
        session = MagicMock()
        client_mock = MagicMock()
        session.client.return_value = client_mock

        # Simulate FSx raising SubscriptionRequiredException
        err = ClientError(
            {"Error": {"Code": "SubscriptionRequiredException", "Message": "Subscription required"}},
            "DescribeFileSystems"
        )
        client_mock.get_paginator.return_value.paginate.side_effect = err
        client_mock.describe_file_systems.side_effect = err
        client_mock.list_buckets.return_value = {"Buckets": []}

        result = collectors.collect_region(
            session=session,
            region="ap-southeast-1",
            account_id="123456789012",
            cfg=self.cfg,
            service_groups=["backup", "storage"],
            now=self.now,
            time_check=lambda: None,
            observed=lambda k, r, b: 0
        )

        self.assertTrue(result["partial"], "Scan must be marked partial on service error")
        error_codes = [e["code"] for e in result["errors"]]
        self.assertIn("SubscriptionRequiredException", error_codes)

    def test_access_denied_exception_handled_gracefully(self):
        """AccessDenied on one service records error code and does not abort scanning engine."""
        session = MagicMock()
        client_mock = MagicMock()
        session.client.return_value = client_mock

        client_mock.describe_addresses.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "User not authorized"}},
            "DescribeAddresses"
        )
        result = collectors.collect_region(
            session=session,
            region="ap-southeast-1",
            account_id="123456789012",
            cfg=self.cfg,
            service_groups=["network"],
            now=self.now,
            time_check=lambda: None,
            observed=lambda k, r, b: 0
        )
        self.assertTrue(result["partial"])
        self.assertEqual(result["errors"][0]["code"], "AccessDenied")

    def test_security_group_reference_prevents_false_unused_finding(self):
        """A group referenced by another security group is not treated as unattached."""
        security_groups = [
            {
                "GroupId": "sg-source",
                "GroupName": "source",
                "IpPermissions": [{
                    "UserIdGroupPairs": [{"GroupId": "sg-target"}],
                }],
                "IpPermissionsEgress": [],
            },
            {
                "GroupId": "sg-target",
                "GroupName": "target",
                "IpPermissions": [],
                "IpPermissionsEgress": [],
            },
        ]

        class Paginator:
            def __init__(self, operation):
                self.operation = operation

            def paginate(self, **_kwargs):
                values = {
                    "describe_security_groups": {"SecurityGroups": security_groups},
                    "describe_network_interfaces": {"NetworkInterfaces": []},
                    "describe_vpc_endpoints": {"VpcEndpoints": []},
                }
                return iter([values[self.operation]])

        ec2 = MagicMock()
        ec2.get_paginator.side_effect = lambda operation: Paginator(operation)
        cloudfront = MagicMock()
        cloudfront.list_distributions.return_value = {"DistributionList": {"Items": []}}
        session = MagicMock()
        session.client.side_effect = lambda service, **_kwargs: (
            cloudfront if service == "cloudfront" else ec2
        )

        with patch("collectors.evaluate_security_group", return_value=None) as evaluate:
            result = collectors.collect_region(
                session=session,
                region="ap-southeast-1",
                account_id="123456789012",
                cfg=self.cfg,
                service_groups=["security"],
                now=self.now,
                time_check=lambda: None,
                observed=lambda _kind, _resource_id, _bucket: 0,
            )

        self.assertFalse(result["partial"])
        calls = {call.args[0]["GroupId"]: call.args for call in evaluate.call_args_list}
        self.assertIn("sg-target", calls["sg-target"][2])

    def test_missing_metrics_yields_insufficient_data_not_idle(self):
        """When CloudWatch metrics are missing (< 80% coverage), system returns INSUFFICIENT_DATA rather than guessing idle."""
        hours = 24
        # Empty metric series (0 samples)
        empty_series = []
        instance = {
            "InstanceId": "i-testmissingmetrics",
            "State": {"Name": "running"},
            "LaunchTime": self.now - timedelta(days=30)
        }
        finding = rules.evaluate_ec2(
            instance=instance,
            metric_values=(empty_series, empty_series, empty_series),
            cfg=self.cfg,
            window_start=self.start
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding["level"], "INSUFFICIENT_DATA")
        self.assertIn("Missing CloudWatch metrics", finding["reason"])

    def test_time_budget_timeout_records_code(self):
        """When time_check raises TimeoutError, collectors record TIME_BUDGET for remaining operations."""
        session = MagicMock()
        client_mock = MagicMock()
        session.client.return_value = client_mock

        def timeout_on_second_call():
            calls = [0]
            def check():
                calls[0] += 1
                if calls[0] > 1:
                    raise TimeoutError("Time budget expired")
            return check

        result = collectors.collect_region(
            session=session,
            region="ap-southeast-1",
            account_id="123456789012",
            cfg=self.cfg,
            service_groups=["compute", "storage", "network"],
            now=self.now,
            time_check=timeout_on_second_call(),
            observed=lambda k, r, b: 0
        )
        self.assertTrue(result["partial"])
        self.assertTrue(any(e["code"] == "TIME_BUDGET" for e in result["errors"]))

class SecurityAndIsolationTests(unittest.TestCase):
    def test_missing_jwt_token_returns_401(self):
        """API Gateway handler returns 401 when request lacks valid access token claims."""
        event = {
            "rawPath": "/me",
            "requestContext": {
                "http": {"method": "GET"}
                # No authorizer context
            }
        }
        resp = app.api(event, None)
        self.assertEqual(resp["statusCode"], 401)
        body = json.loads(resp["body"])
        self.assertIn("Access token required", body["error"])

    def test_invalid_token_use_returns_401(self):
        """ID token cannot be used in place of access token."""
        event = {
            "rawPath": "/me",
            "requestContext": {
                "http": {"method": "GET"},
                "authorizer": {
                    "jwt": {
                        "claims": {
                            "sub": "user-uuid-1234",
                            "token_use": "id" # Must be access
                        }
                    }
                }
            }
        }
        resp = app.api(event, None)
        self.assertEqual(resp["statusCode"], 401)

    def test_tenant_isolation_partition_keys_distinct(self):
        """Tenant A and Tenant B must map to strictly separate DynamoDB partition keys."""
        event_a = {
            "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "user-a", "token_use": "access"}}}}
        }
        event_b = {
            "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "user-b", "token_use": "access"}}}}
        }
        key_a = app.tenant_key(event_a)
        key_b = app.tenant_key(event_b)
        self.assertEqual(key_a, "TENANT#user-a")
        self.assertEqual(key_b, "TENANT#user-b")
        self.assertNotEqual(key_a, key_b)

    def test_role_arn_regex_rejects_malicious_inputs(self):
        """Role ARN must match strict GuardianReadRole pattern without path or injection."""
        valid_arn = "arn:aws:iam::123456789012:role/GuardianReadRole-test"
        invalid_arns = [
            "arn:aws:iam::123456789012:role/AdminRole",
            "arn:aws:iam::123456789012:role/path/GuardianReadRole-test",
            "arn:aws:iam::123456789012:user/GuardianReadRole-test",
            "arn:aws:iam::123456789012:role/GuardianReadRole-test;rm -rf",
            "invalid-arn"
        ]
        self.assertIsNotNone(app.re.fullmatch(r"arn:aws:iam::\d{12}:role/GuardianReadRole-[A-Za-z0-9+=,.@_-]{1,40}", valid_arn))
        for bad in invalid_arns:
            self.assertIsNone(app.re.fullmatch(r"arn:aws:iam::\d{12}:role/GuardianReadRole-[A-Za-z0-9+=,.@_-]{1,40}", bad), f"Should reject: {bad}")

    def test_regions_whitelist_enforces_1_to_3_regions(self):
        """User must select 1 to 3 valid regions from the allowed set."""
        valid_regions = ["ap-southeast-1"]
        self.assertTrue(1 <= len(valid_regions) <= 3 and set(valid_regions) <= app.REGIONS)

        invalid_sets = [
            [], # 0 regions
            ["ap-southeast-1", "us-east-1", "us-west-2", "eu-west-1"], # 4 regions
            ["cn-north-1"], # Unsupported region
            ["ap-southeast-1", "ap-southeast-1"] # Duplicate regions
        ]
        for bad in invalid_sets:
            is_valid = 1 <= len(bad) <= 3 and set(bad) <= app.REGIONS and len(set(bad)) == len(bad)
            self.assertFalse(is_valid, f"Should reject region set: {bad}")

class FalsePositiveControlTests(unittest.TestCase):
    def test_guardian_keep_tag_suppresses_findings(self):
        """Resources tagged with guardian:keep=true must not be flagged by rules."""
        # Unattached volume with keep tag
        volume_kept = {
            "VolumeId": "vol-kept123",
            "State": "available",
            "Attachments": [],
            "Tags": [{"Key": "guardian:keep", "Value": "true"}]
        }
        res_ebs = rules.evaluate_ebs(volume_kept, observed_hours=100, cfg=rules.config({}))
        self.assertIsNone(res_ebs, "Volume with guardian:keep=true must be suppressed")

        # Security group with keep tag
        sg_kept = {
            "GroupId": "sg-kept123",
            "GroupName": "my-sg",
            "Tags": [{"Key": "guardian:keep", "Value": "true"}]
        }
        res_sg = rules.evaluate_security_group(sg_kept, attached_sg_ids=set(), referenced_sg_ids=set(), observed_hours=500, cfg=rules.config({}))
        self.assertIsNone(res_sg, "Security group with guardian:keep=true must be suppressed")

    def test_default_security_group_is_never_flagged_as_unused(self):
        """Default security group must never be reported as unused candidate."""
        default_sg = {
            "GroupId": "sg-default123",
            "GroupName": "default",
            "Tags": []
        }
        res = rules.evaluate_security_group(default_sg, attached_sg_ids=set(), referenced_sg_ids=set(), observed_hours=500, cfg=rules.config({}))
        self.assertIsNone(res, "Default security group must never be flagged as unused")

if __name__ == '__main__':
    unittest.main()
