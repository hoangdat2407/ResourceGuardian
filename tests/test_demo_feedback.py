"""Demo feedback contract through its HTTP handler; no socket or AWS calls."""
import copy
from datetime import datetime, timezone
import io
import json
import unittest
from unittest.mock import MagicMock, patch

import demo


class DemoFeedback(unittest.TestCase):
    def setUp(self):
        self.saved = copy.deepcopy((demo.PROFILE, demo.CURRENT, demo.HISTORY, demo.FEEDBACK, demo.READY_AT))
        self.addCleanup(self.restore)
        self.now = 1793361600
        clock = patch.object(demo.time, "time", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        demo.PROFILE["regions"] = ["ap-southeast-1"]
        demo.PROFILE["service_groups"] = list(demo.SERVICE_GROUPS)
        demo.FEEDBACK = {}
        demo.READY_AT = 0
        demo.CURRENT = [demo.complete("original-scan", self.now - 10)]
        demo.HISTORY = copy.deepcopy(demo.CURRENT)
        self.finding = demo.CURRENT[0]["candidates"][0]
        self.ident = self.finding["finding_id"]
        self.base = {"region": "ap-southeast-1", "finding_id": self.ident}

    def restore(self):
        demo.PROFILE, demo.CURRENT, demo.HISTORY, demo.FEEDBACK, demo.READY_AT = self.saved

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

    def update(self, **fields):
        return self.request("PUT", "/feedback", {**self.base, **fields})

    def findings(self):
        code, response = self.request("GET", "/findings")
        self.assertEqual(code, 200)
        return response["results"][0]["findings"]

    def until(self, seconds):
        return datetime.fromtimestamp(self.now + seconds, timezone.utc).isoformat().replace("+00:00", "Z")

    def test_acknowledgement_remains_visible_and_toggle_survives_refresh(self):
        self.assertEqual(self.update(acknowledged=True)[0], 200)
        for _ in range(2):
            current = next(finding for finding in self.findings() if finding["finding_id"] == self.ident)
            self.assertIs(current["acknowledged"], True)
        self.assertEqual(self.update(acknowledged=False)[0], 200)
        current = next(finding for finding in self.findings() if finding["finding_id"] == self.ident)
        self.assertNotIn("acknowledged", current)

    def test_keep_ignore_and_acknowledged_flags_are_independent(self):
        self.update(acknowledged=True)
        self.update(kept=True)
        self.update(ignoreUntil=self.until(7 * 86400))
        self.assertNotIn(self.ident, {finding["finding_id"] for finding in self.findings()})
        code, record = self.update(kept=False)
        self.assertEqual(code, 200)
        self.assertIs(record["acknowledged"], True)
        self.assertGreater(record["ignore_until"], self.now)
        self.assertNotIn(self.ident, {finding["finding_id"] for finding in self.findings()})
        self.update(ignoreUntil=None)
        current = next(finding for finding in self.findings() if finding["finding_id"] == self.ident)
        self.assertIs(current["acknowledged"], True)
        self.update(kept=True)
        self.update(acknowledged=False)
        self.assertTrue(demo.FEEDBACK[self.ident]["kept"])
        self.assertNotIn(self.ident, {finding["finding_id"] for finding in self.findings()})

    def test_feedback_and_overlay_do_not_rewrite_scan_or_history_snapshot(self):
        before_current, before_history = copy.deepcopy((demo.CURRENT, demo.HISTORY))
        self.update(acknowledged=True)
        self.update(kept=True)
        self.findings()
        self.assertEqual(demo.CURRENT, before_current)
        self.assertEqual(demo.HISTORY, before_history)
        for path in ("/history", "/scans/original-scan"):
            code, response = self.request("GET", path)
            self.assertEqual(code, 200)
            self.assertIn(self.ident, {finding["finding_id"] for finding in response["results"][0]["findings"]})
            self.assertTrue(all("candidates" not in row for row in response["results"]))
        self.assertNotIn("candidates", self.request("GET", "/findings")[1]["results"][0])

    def test_feedback_survives_new_scan_and_clearing_restores_retained_candidate(self):
        self.update(acknowledged=True)
        self.update(kept=True)
        self.assertEqual(self.request("POST", "/scans")[0], 202)
        demo.READY_AT = self.now
        demo.tick()
        self.assertNotIn(self.ident, {finding["finding_id"] for finding in self.findings()})
        saved = copy.deepcopy(demo.HISTORY[0])
        self.update(kept=False)
        current = next(finding for finding in self.findings() if finding["finding_id"] == self.ident)
        self.assertIs(current["acknowledged"], True)
        self.assertEqual(demo.HISTORY[0], saved)

    def test_metadata_only_comes_from_current_candidate_and_preserves_legacy_values(self):
        self.finding.update(account_id="111111111111", rule_id="EC2_TEST_RULE")
        code, record = self.update(acknowledged=True)
        self.assertEqual(code, 200)
        for field in ("type", "resource_id", "account_id", "rule_id"):
            self.assertEqual(record[field], self.finding[field])
        demo.CURRENT = []
        code, saved = self.update(kept=True)
        self.assertEqual(code, 200)
        for field in ("type", "resource_id", "account_id", "rule_id"):
            self.assertEqual(saved[field], record[field])
        self.assertEqual(self.request("GET", "/feedback")[1]["results"], [saved])

    def test_missing_metadata_is_not_invented_from_profile_or_rules(self):
        code, record = self.update(acknowledged=True)
        self.assertEqual(code, 200)
        self.assertEqual(record["type"], self.finding["type"])
        self.assertNotIn("account_id", record)
        self.assertNotIn("rule_id", record)

    def test_partial_candidate_metadata_preserves_previous_display_fields(self):
        demo.FEEDBACK[self.ident] = {**self.base, "type": "EC2", "resource_id": "i-legacy",
                                    "account_id": "111111111111", "rule_id": "LEGACY_RULE"}
        self.finding.update(account_id=None, rule_id="")
        code, record = self.update(acknowledged=True)
        self.assertEqual(code, 200)
        self.assertEqual(record["resource_id"], self.finding["resource_id"])
        self.assertEqual(record["account_id"], "111111111111")
        self.assertEqual(record["rule_id"], "LEGACY_RULE")

    def test_invalid_payloads_do_not_mutate_feedback_or_results(self):
        valid = {**self.base, "acknowledged": True}
        invalid = [{**valid, key: value} for key in ("acknowledged", "kept") for value in (1, 0, None, "true", [], {})]
        invalid += [{**valid, "type": "EBS"}, {**valid, "account_id": "999999999999"},
                    self.base, {"acknowledged": True}, {**valid, "region": "us-west-2"},
                    {**valid, "finding_id": "invalid"}, {**valid, "ignoreUntil": "2026-11-01T00:00:00+00:00"},
                    {**valid, "ignoreUntil": "2026-11-01T00:00:00"}, {**valid, "ignoreUntil": True},
                    {**valid, "ignoreUntil": self.until(0)}, {**valid, "ignoreUntil": self.until(30 * 86400 + 1)}]
        for payload in invalid:
            with self.subTest(payload=payload):
                before = copy.deepcopy((demo.CURRENT, demo.HISTORY, demo.FEEDBACK))
                self.assertEqual(self.request("PUT", "/feedback", payload)[0], 400)
                self.assertEqual((demo.CURRENT, demo.HISTORY, demo.FEEDBACK), before)

    def test_ignore_one_and_thirty_days_are_valid_and_expiry_does_not_need_cleanup(self):
        for days in (1, 30):
            with self.subTest(days=days):
                self.assertEqual(self.update(ignoreUntil=self.until(days * 86400))[0], 200)
                self.assertNotIn(self.ident, {finding["finding_id"] for finding in self.findings()})
        with patch.object(demo.time, "time", return_value=self.now + 30 * 86400):
            self.assertIn(self.ident, {finding["finding_id"] for finding in self.findings()})
            self.assertEqual(self.request("GET", "/feedback")[1]["results"], [])
        self.assertIn(self.ident, demo.FEEDBACK)

    def test_wrong_region_version_and_unstored_findings_cannot_create_feedback(self):
        demo.PROFILE["regions"].append("ap-southeast-2")
        self.assertEqual(self.request("PUT", "/feedback", {**self.base, "region": "ap-southeast-2", "kept": True})[0], 404)
        demo.CURRENT[0]["connection_version"] = "old-connection"
        self.assertEqual(self.update(kept=True)[0], 404)
        demo.CURRENT = []
        self.assertEqual(self.update(kept=True)[0], 404)
        self.assertEqual(demo.FEEDBACK, {})

    def test_same_resource_in_two_regions_has_independent_feedback(self):
        second_region = "ap-southeast-2"
        demo.PROFILE["regions"].append(second_region)
        demo.CURRENT.append(demo.complete("original-scan", self.now - 10, second_region))
        second_ident = demo.CURRENT[1]["candidates"][0]["finding_id"]
        self.assertNotEqual(second_ident, self.ident)
        self.update(kept=True)
        rows = self.request("GET", "/findings")[1]["results"]
        self.assertNotIn(self.ident, {finding["finding_id"] for finding in rows[0]["findings"]})
        self.assertIn(second_ident, {finding["finding_id"] for finding in rows[1]["findings"]})

    def test_pending_scan_has_no_regenerated_findings_before_completion(self):
        self.assertEqual(self.request("POST", "/scans")[0], 202)
        _, response = self.request("GET", "/findings")
        self.assertEqual(response["results"][0]["status"], "RUNNING")
        self.assertNotIn("findings", response["results"][0])


if __name__ == "__main__":
    unittest.main()
