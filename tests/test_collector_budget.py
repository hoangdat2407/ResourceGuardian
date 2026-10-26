"""Time-budget regressions with AWS page fetches observed at iterator advancement."""
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import collectors
from rules import config


class CollectorBudget(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 26, 9, tzinfo=timezone.utc)
        self.expired = False

    def check(self):
        if self.expired:
            raise TimeoutError("No collection budget remains")

    def collect(self, clients, groups):
        session = MagicMock()
        session.client.side_effect = lambda service, **kwargs: clients[service]
        return collectors.collect_region(
            session, "ap-southeast-1", "123456789012", config({}), groups,
            self.now, self.check, lambda *args: 48,
        )

    @staticmethod
    def paginator(client, pages):
        paginator = MagicMock()
        paginator.paginate.side_effect = lambda **kwargs: pages()
        client.get_paginator.return_value = paginator
        return paginator

    def test_inventory_checks_before_initial_page_request(self):
        client = MagicMock()
        fetched = []

        def pages():
            fetched.append("first")
            yield {"Volumes": []}

        self.paginator(client, pages)
        self.expired = True
        with self.assertRaises(TimeoutError):
            collectors.collect_pages(client, "describe_volumes", "Volumes", time_check=self.check)
        self.assertEqual(fetched, [])

    def test_inventory_checks_before_fetching_next_page(self):
        client = MagicMock()
        fetched = []

        def pages():
            fetched.append("first")
            self.expired = True
            yield {"Volumes": [{"VolumeId": "vol-first"}]}
            fetched.append("second")
            yield {"Volumes": [{"VolumeId": "vol-second"}]}

        self.paginator(client, pages)
        with self.assertRaises(TimeoutError):
            collectors.collect_pages(client, "describe_volumes", "Volumes", time_check=self.check)
        self.assertEqual(fetched, ["first"])

    def test_metric_pagination_never_fetches_after_budget_expires(self):
        cw = MagicMock()

        def response(**kwargs):
            self.expired = True
            return {"MetricDataResults": [{"Id": "cpu", "StatusCode": "Complete", "Values": [0], "Timestamps": [self.now - timedelta(hours=1)]}], "NextToken": "page-2"}

        cw.get_metric_data.side_effect = response
        with self.assertRaises(TimeoutError):
            collectors.metric_series(cw, [{"Id": "cpu"}], self.now - timedelta(hours=24), self.now, time_check=self.check)
        self.assertEqual(cw.get_metric_data.call_count, 1)

    def test_metric_budget_exhaustion_does_not_invent_zero_findings(self):
        ec2, cw = MagicMock(), MagicMock()
        self.paginator(ec2, lambda: iter([{"Reservations": [{"Instances": [{"InstanceId": "i-demo", "State": {"Name": "running"}, "LaunchTime": self.now - timedelta(days=8)}]}]}]))

        def response(**kwargs):
            self.expired = True
            return {"MetricDataResults": [], "NextToken": "page-2"}

        cw.get_metric_data.side_effect = response
        result = self.collect({"ec2": ec2, "cloudwatch": cw}, ["compute"])
        self.assertTrue(result["partial"])
        self.assertEqual(result["findings"], [])
        self.assertIn({"type": "EC2", "code": "TIME_BUDGET"}, result["errors"])
        self.assertEqual(cw.get_metric_data.call_count, 1)

    def test_s3_bucket_pagination_stops_before_second_aws_request(self):
        ec2, s3 = MagicMock(), MagicMock()
        self.paginator(ec2, lambda: iter([{}]))

        def response(**kwargs):
            self.expired = True
            return {"Buckets": [{"Name": "demo"}], "ContinuationToken": "page-2"}

        s3.list_buckets.side_effect = response
        result = self.collect({"ec2": ec2, "s3": s3}, ["storage"])
        self.assertTrue(result["partial"])
        self.assertIn({"type": "S3_MULTIPART", "code": "TIME_BUDGET"}, result["errors"])
        self.assertEqual(s3.list_buckets.call_count, 1)
        s3.get_paginator.assert_not_called()

    def test_s3_upload_pages_keep_valid_findings_when_next_page_times_out(self):
        ec2, s3 = MagicMock(), MagicMock()
        self.paginator(ec2, lambda: iter([{}]))
        s3.list_buckets.return_value = {"Buckets": [{"Name": "demo"}]}
        fetched = []

        def pages():
            fetched.append("first")
            self.expired = True
            yield {"Uploads": [{"Key": "old/object", "UploadId": "upload-1", "Initiated": self.now - timedelta(days=8)}]}
            fetched.append("second")
            yield {"Uploads": []}

        self.paginator(s3, pages)
        result = self.collect({"ec2": ec2, "s3": s3}, ["storage"])
        self.assertEqual(fetched, ["first"])
        self.assertTrue(result["partial"])
        self.assertEqual(result["counts"]["S3_MULTIPART"], 1)
        self.assertEqual([item["resource_id"] for item in result["findings"]], ["s3://demo/old/object"])
        self.assertIn({"type": "S3_MULTIPART", "code": "TIME_BUDGET"}, result["errors"])

    def test_s3_checks_budget_between_buckets(self):
        ec2, s3 = MagicMock(), MagicMock()
        self.paginator(ec2, lambda: iter([{}]))
        s3.list_buckets.return_value = {"Buckets": [{"Name": "first"}, {"Name": "second"}]}
        requested = []
        paginator = MagicMock()

        def pages(**kwargs):
            requested.append(kwargs["Bucket"])
            yield {"Uploads": []}
            self.expired = True

        paginator.paginate.side_effect = pages
        s3.get_paginator.return_value = paginator
        result = self.collect({"ec2": ec2, "s3": s3}, ["storage"])
        self.assertEqual(requested, ["first"])
        self.assertTrue(result["partial"])

    def test_load_balancer_inventory_checks_before_next_page(self):
        ec2, elbv2 = MagicMock(), MagicMock()
        ec2.describe_addresses.return_value = {"Addresses": [{"AllocationId": "eipalloc-valid"}]}
        self.paginator(ec2, lambda: iter([{"NatGateways": []}]))
        fetched = []

        def pages():
            fetched.append("first")
            self.expired = True
            yield {"LoadBalancers": []}
            fetched.append("second")
            yield {"LoadBalancers": []}

        self.paginator(elbv2, pages)
        result = self.collect({"ec2": ec2, "elbv2": elbv2}, ["network"])
        self.assertEqual(fetched, ["first"])
        self.assertTrue(result["partial"])
        self.assertEqual([item["type"] for item in result["findings"]], ["EIP"])
        self.assertIn({"type": "ELB", "code": "TIME_BUDGET"}, result["errors"])

    def test_sdk_attempt_limit_counts_initial_request(self):
        self.assertEqual(collectors.SDK_CONFIG.retries, {"mode": "standard", "total_max_attempts": 3})
        self.assertLessEqual(3 * (collectors.SDK_CONFIG.connect_timeout + collectors.SDK_CONFIG.read_timeout), 45)


if __name__ == "__main__":
    unittest.main()
