"""Prevent the manual AWS gate from accepting incomplete or stale evidence."""
import copy
import unittest
from unittest.mock import patch

from tests import test_aws_e2e as aws_e2e


class EvidenceGate(unittest.TestCase):
    def manifest(self):
        return {
            "role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-demo",
            "regions": ["ap-southeast-1"],
            "settings": {},
            "required_findings": [
                {"type": kind, "region": "ap-southeast-1", "resource_id": kind,
                 "allowed_levels": ["REVIEW"]} for kind in sorted(aws_e2e.REQUIRED_TYPES)
            ],
            "optional_findings": [
                {"type": kind, "skip_reason": "COST_NOT_APPROVED"} for kind in sorted(aws_e2e.OPTIONAL_TYPES)
            ],
        }

    def test_duplicate_service_cannot_substitute_for_distinct_evidence(self):
        for group in ("required_findings", "optional_findings"):
            manifest = self.manifest()
            manifest[group].append(copy.deepcopy(manifest[group][0]))
            with self.subTest(group=group), patch.object(aws_e2e.AwsEndToEnd, "manifest", manifest, create=True):
                with self.assertRaises(AssertionError):
                    aws_e2e.AwsEndToEnd._validate_manifest()

    def test_history_pagination_retains_all_regions(self):
        pages = [
            (200, {"results": [{"region": "ap-southeast-1"}], "next_token": "a+/="}),
            (200, {"results": [{"region": "ap-southeast-2"}], "next_token": None}),
        ]
        with patch.object(aws_e2e.AwsEndToEnd, "request", side_effect=pages) as request:
            rows = aws_e2e.AwsEndToEnd.pages("/history?limit=1")
        self.assertEqual({row["region"] for row in rows}, {"ap-southeast-1", "ap-southeast-2"})
        self.assertEqual(request.call_args.args[1], "/history?limit=1&next_token=a%2B%2F%3D")

    def test_repeated_cursor_fails_instead_of_hanging_release_gate(self):
        with patch.object(aws_e2e.AwsEndToEnd, "request", return_value=(200, {"results": [], "next_token": "loop"})):
            with self.assertRaisesRegex(AssertionError, "repeated"):
                aws_e2e.AwsEndToEnd.pages("/history?limit=1")
