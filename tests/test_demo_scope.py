"""Local demo scope/settings contract, without a browser, socket or AWS calls."""
import copy
import io
import json
import unittest
import uuid
from unittest.mock import MagicMock

import demo


class DemoScope(unittest.TestCase):
    def setUp(self):
        self.saved = copy.deepcopy((demo.PROFILE, demo.CURRENT, demo.HISTORY, demo.FEEDBACK, demo.READY_AT, demo.FINDING_OBSERVATIONS))
        self.addCleanup(self.restore)
        demo.FINDING_OBSERVATIONS = {}
        demo.READY_AT = 0
        self.connection = {
            "role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-demo",
            "regions": ["ap-southeast-1"],
        }

    def restore(self):
        demo.PROFILE, demo.CURRENT, demo.HISTORY, demo.FEEDBACK, demo.READY_AT, demo.FINDING_OBSERVATIONS = self.saved

    def request(self, method, path, body=None):
        payload = json.dumps(body).encode() if body is not None else b""
        handler = object.__new__(demo.Handler)
        handler.headers = {"Authorization": "Bearer demo-local-only", "Content-Length": str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        handler.reply = MagicMock()
        handler.handle_api(method, path)
        handler.reply.assert_called_once()
        code, value = handler.reply.call_args.args
        return code, copy.deepcopy(value)

    def test_storage_scope_round_trip_filters_existing_demo_counts_and_findings(self):
        code, _ = self.request("PUT", "/connection", {**self.connection, "service_groups": ["storage"]})
        self.assertEqual(code, 200)
        code, profile = self.request("GET", "/me")
        self.assertEqual(code, 200)
        self.assertEqual(profile["service_groups"], ["storage"])
        result = demo.complete("scope-scan", 1)
        demo.CURRENT = [result]
        code, response = self.request("GET", "/findings")
        self.assertEqual(code, 200)
        self.assertEqual(response["results"][0]["counts"], {"EBS": 6, "SNAPSHOT": 8, "S3_MULTIPART": 2})
        self.assertEqual({finding["type"] for finding in response["results"][0]["findings"]}, {"EBS", "SNAPSHOT", "S3_MULTIPART"})

    def test_each_group_only_uses_available_demo_data(self):
        for group, expected in (("compute", {"EC2"}), ("storage", {"EBS", "SNAPSHOT", "S3_MULTIPART"}),
                                ("database", {"RDS"}), ("network", {"EIP", "NAT_GATEWAY", "ALB", "NLB"})):
            with self.subTest(group=group):
                code, _ = self.request("PUT", "/connection", {**self.connection, "service_groups": [group]})
                self.assertEqual(code, 200)
                result = demo.complete("scope-scan", 1)
                self.assertEqual(set(result["counts"]), expected)
                self.assertEqual({finding["type"] for finding in result["findings"]}, expected)

    def test_invalid_groups_do_not_mutate_connection_or_cached_data(self):
        for groups in ([], ["storage", "storage"], ["analytics"], "storage", True, {},
                       ["storage", None], [*demo.SERVICE_GROUPS, "compute"]):
            with self.subTest(groups=groups):
                before = copy.deepcopy((demo.PROFILE, demo.CURRENT, demo.HISTORY, demo.FEEDBACK))
                code, _ = self.request("PUT", "/connection", {**self.connection, "service_groups": groups})
                self.assertEqual(code, 400)
                self.assertEqual((demo.PROFILE, demo.CURRENT, demo.HISTORY, demo.FEEDBACK), before)

    def test_omitted_groups_preserve_current_selection_and_legacy_defaults_to_all(self):
        demo.PROFILE["service_groups"] = ["storage", "network"]
        self.assertEqual(self.request("PUT", "/connection", self.connection)[0], 200)
        self.assertEqual(self.request("GET", "/me")[1]["service_groups"], ["storage", "network"])
        demo.PROFILE.pop("service_groups")
        self.assertEqual(self.request("GET", "/me")[1]["service_groups"], list(demo.SERVICE_GROUPS))
        self.assertEqual(self.request("PUT", "/connection", self.connection)[0], 200)
        self.assertEqual(demo.PROFILE["service_groups"], list(demo.SERVICE_GROUPS))

    def test_explicit_null_groups_uses_backend_default(self):
        demo.PROFILE["service_groups"] = ["storage"]
        self.assertEqual(self.request("PUT", "/connection", {**self.connection, "service_groups": None})[0], 200)
        self.assertEqual(demo.PROFILE["service_groups"], list(demo.SERVICE_GROUPS))

    def test_invalid_role_regions_and_connection_fields_do_not_mutate_profile(self):
        invalid = [
            {**self.connection, "role_arn": "arn:aws:iam::123456789012:role/OtherRole"},
            {**self.connection, "role_arn": None},
            {**self.connection, "regions": "ap-southeast-1"},
            {**self.connection, "regions": []},
            {**self.connection, "regions": ["ap-southeast-1"] * 2},
            {**self.connection, "regions": ["unsupported"]},
            {**self.connection, "regions": [None]},
            {**self.connection, "regions": sorted(demo.REGIONS)[:4]},
            {**self.connection, "unexpected": True},
        ]
        for body in invalid:
            with self.subTest(body=body):
                before = copy.deepcopy(demo.PROFILE)
                self.assertEqual(self.request("PUT", "/connection", body)[0], 400)
                self.assertEqual(demo.PROFILE, before)

    def test_scope_change_starts_new_connection_without_old_scan_or_feedback(self):
        old_version = demo.PROFILE["connection_version"]
        demo.CURRENT = [{"scan_id": "pending", "started_at": 1}]
        demo.READY_AT = float("inf")
        demo.FEEDBACK["old-finding"] = {"kept": True}
        self.assertEqual(self.request("PUT", "/connection", {**self.connection, "service_groups": ["storage"]})[0], 200)
        self.assertNotEqual(demo.PROFILE["connection_version"], old_version)
        self.assertEqual(str(uuid.UUID(demo.PROFILE["connection_version"])), demo.PROFILE["connection_version"])
        self.assertEqual((demo.CURRENT, demo.HISTORY, demo.FEEDBACK, demo.READY_AT), ([], [], {}, 0))
        self.assertEqual(demo.FINDING_OBSERVATIONS, {})
        demo.tick()

    def test_all_eleven_settings_save_reload_and_invalid_update_preserves_values(self):
        settings = {"cpu_percent": 7, "network_mib_hour": 2, "window_hours": 48,
                    "orphan_hours": 12, "snapshot_days": 60, "interval_hours": 4,
                    "rds_cpu_percent": 8, "rds_connections": 3, "nat_mib_hour": 4,
                    "alb_requests_hour": 5, "nlb_new_flows_hour": 6}
        self.assertEqual(self.request("PUT", "/settings", settings), (200, settings))
        self.assertEqual(self.request("GET", "/me")[1]["settings"], settings)
        self.assertEqual(self.request("PUT", "/settings", {"nlb_new_flows_hour": 0})[0], 400)
        self.assertEqual(demo.PROFILE["settings"], settings)


if __name__ == "__main__":
    unittest.main()
