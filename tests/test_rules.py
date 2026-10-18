import datetime
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from rules import (
    DEFAULTS,
    alb_idle,
    config,
    finding_id,
    idle,
    keep,
    nat_idle,
    nlb_idle,
    rds_idle,
    stale_multipart,
)


class RulesTest(unittest.TestCase):
    def test_missing_is_not_zero(self):
        self.assertEqual(idle([], [], [], 24, config({}))[0], "INSUFFICIENT_DATA")

    def test_low_usage(self):
        self.assertEqual(idle([1] * 24, [100] * 24, [100] * 24, 24, config({}))[0], "REVIEW")

    def test_spike_not_idle(self):
        self.assertEqual(idle([1] * 22 + [80] * 2, [0] * 24, [0] * 24, 24, config({}))[0], "OK")

    def test_network_not_idle(self):
        self.assertEqual(idle([1] * 24, [2 * 1048576] * 24, [0] * 24, 24, config({}))[0], "OK")

    def test_config_bounds_and_types(self):
        boundaries = {
            "cpu_percent": (1, 50),
            "network_mib_hour": (0.1, 100),
            "window_hours": (24, 72),
            "orphan_hours": (1, 168),
            "snapshot_days": (7, 365),
            "interval_hours": (1, 24),
            "rds_cpu_percent": (1, 50),
            "rds_connections": (1, 1000),
            "nat_mib_hour": (0.1, 10000),
            "alb_requests_hour": (1, 1000000),
            "nlb_new_flows_hour": (1, 1000000),
        }
        for field, (low, high) in boundaries.items():
            with self.subTest(field=field, edge="low"):
                self.assertEqual(config({field: low})[field], low)
            with self.subTest(field=field, edge="high"):
                self.assertEqual(config({field: high})[field], high)
            with self.subTest(field=field, edge="below"):
                with self.assertRaises(ValueError):
                    config({field: low - 1})
            with self.subTest(field=field, edge="above"):
                with self.assertRaises(ValueError):
                    config({field: high + 1})

    def test_config_rejects_invalid(self):
        invalid = (
            {"window_hours": 2},
            {"cpu_percent": True},
            {"cpu_percent": float("nan")},
            {"cpu_percent": float("inf")},
            {"tenant": "a"},
            {"interval_hours": 1.5},
            [],
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    config(value)

    def test_config_merges_old_profile_and_update(self):
        old = {key: DEFAULTS[key] for key in tuple(DEFAULTS)[:6]}
        merged = config({"cpu_percent": 8}, old)
        self.assertEqual(merged["cpu_percent"], 8)
        self.assertEqual(merged["rds_connections"], DEFAULTS["rds_connections"])

    def test_keep(self):
        self.assertTrue(keep([{"Key": "guardian:keep", "Value": "TRUE"}]))
        self.assertFalse(keep([]))

    def test_rds_rule(self):
        cfg = config({})
        self.assertEqual(rds_idle([0] * 20, [0] * 20, 24, cfg)[0], "REVIEW")
        self.assertEqual(rds_idle([0] * 19, [0] * 20, 24, cfg)[0], "INSUFFICIENT_DATA")
        self.assertEqual(rds_idle([0] * 20, [2] * 20, 24, cfg)[0], "OK")

    def test_average_metric_rules(self):
        cfg = config({})
        self.assertEqual(nat_idle([0] * 20, [0] * 20, 24, cfg)[0], "REVIEW")
        self.assertEqual(nat_idle([0] * 19, [0] * 20, 24, cfg)[0], "INSUFFICIENT_DATA")
        self.assertEqual(nat_idle([2 * 1048576] * 20, [0] * 20, 24, cfg)[0], "OK")
        self.assertEqual(alb_idle([0] * 20, 24, cfg)[0], "REVIEW")
        self.assertEqual(alb_idle([1] * 20, 24, cfg)[0], "OK")
        self.assertEqual(nlb_idle([0] * 20, 24, cfg)[0], "REVIEW")
        self.assertEqual(nlb_idle([1] * 20, 24, cfg)[0], "OK")

    def test_strict_multipart_age(self):
        now = datetime.datetime(2026, 1, 8, tzinfo=datetime.timezone.utc)
        self.assertEqual(stale_multipart(now - datetime.timedelta(days=7), now)[0], "OK")
        self.assertEqual(
            stale_multipart(now - datetime.timedelta(days=7, seconds=1), now)[0],
            "REVIEW",
        )

    def test_finding_id_uses_structured_identity(self):
        first = finding_id("S3_MULTIPART", "ap-southeast-1", ["a", "b/c", "d"])
        second = finding_id("S3_MULTIPART", "ap-southeast-1", ["a/b", "c", "d"])
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
