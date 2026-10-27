"""Manual, post-deploy AWS evidence harness. Disabled unless CRG_AWS_E2E=1."""
import json
import os
import pathlib
import time
import unittest
import urllib.error
import urllib.request
from urllib.parse import urlencode
from datetime import datetime, timezone

ENABLED = os.environ.get("CRG_AWS_E2E") == "1"
REQUIRED_TYPES = {"EC2", "EBS", "EIP", "SNAPSHOT", "S3_MULTIPART"}
OPTIONAL_TYPES = {"RDS", "NAT_GATEWAY", "ALB", "NLB"}
SKIP_REASONS = {"RESOURCE_NOT_AVAILABLE", "COST_NOT_APPROVED"}


@unittest.skipUnless(ENABLED, "Set CRG_AWS_E2E=1 only after the reviewed manual release gate")
class AwsEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = (
            "CRG_AWS_E2E_API_URL",
            "CRG_AWS_E2E_ACCESS_TOKEN",
            "CRG_AWS_E2E_SECOND_ACCESS_TOKEN",
            "CRG_AWS_E2E_MANIFEST",
            "CRG_AWS_E2E_EVIDENCE",
        )
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise AssertionError("Missing required AWS E2E inputs: " + ", ".join(missing))
        cls.base_url = os.environ["CRG_AWS_E2E_API_URL"].rstrip("/")
        cls.token = os.environ["CRG_AWS_E2E_ACCESS_TOKEN"]
        cls.second_token = os.environ["CRG_AWS_E2E_SECOND_ACCESS_TOKEN"]
        cls.evidence_path = pathlib.Path(os.environ["CRG_AWS_E2E_EVIDENCE"])
        cls.manifest = json.loads(pathlib.Path(os.environ["CRG_AWS_E2E_MANIFEST"]).read_text(encoding="utf-8"))
        cls._validate_manifest()
        cls.evidence = {"started_at": cls._timestamp(), "api_url": cls.base_url, "steps": []}

    @classmethod
    def _validate_manifest(cls):
        manifest = cls.manifest
        required_keys = {"role_arn", "regions", "settings", "required_findings", "optional_findings"}
        if set(manifest) != required_keys:
            raise AssertionError("Manifest must contain exactly: " + ", ".join(sorted(required_keys)))
        required = manifest["required_findings"]
        if len(required) != len(REQUIRED_TYPES) or {item.get("type") for item in required} != REQUIRED_TYPES:
            raise AssertionError("required_findings must contain EC2, EBS, EIP, SNAPSHOT and S3_MULTIPART exactly")
        optional = manifest["optional_findings"]
        if len(optional) != len(OPTIONAL_TYPES) or {item.get("type") for item in optional} != OPTIONAL_TYPES:
            raise AssertionError("optional_findings must contain RDS, NAT_GATEWAY, ALB and NLB exactly")
        for item in required:
            if set(item) != {"type", "region", "resource_id", "allowed_levels"} or not item["allowed_levels"]:
                raise AssertionError("Each required finding needs type, region, resource_id and allowed_levels")
        for item in optional:
            has_expected = {"region", "resource_id", "allowed_levels"} <= set(item)
            has_skip = item.get("skip_reason") in SKIP_REASONS
            if has_expected == has_skip:
                raise AssertionError("Each optional finding needs expected resource fields or one exact skip_reason")

    @staticmethod
    def _timestamp():
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @classmethod
    def request(cls, method, path, body=None, token=None, expected=None):
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            cls.base_url + path,
            data=payload,
            method=method,
            headers={"Authorization": "Bearer " + (token or cls.token), "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as reply:
                status = reply.status
                value = json.loads(reply.read())
        except urllib.error.HTTPError as error:
            status = error.code
            value = json.loads(error.read())
        if expected is not None and status != expected:
            raise AssertionError(f"{method} {path}: expected {expected}, got {status}: {value}")
        cls.evidence["steps"].append({"at": cls._timestamp(), "method": method, "path": path, "status": status})
        return status, value

    @classmethod
    def pages(cls, path, token=None):
        rows, seen = [], set()
        while True:
            _, page = cls.request("GET", path, token=token, expected=200)
            rows.extend(page["results"])
            cursor = page.get("next_token")
            if not cursor:
                return rows
            if cursor in seen:
                raise AssertionError("API repeated a pagination token")
            seen.add(cursor)
            path = path.split("?", 1)[0] + "?" + urlencode({"limit": 1, "next_token": cursor})

    def test_deployed_read_only_scan_and_tenant_boundary(self):
        _, connection = self.request("PUT", "/connection", {"role_arn": self.manifest["role_arn"], "regions": self.manifest["regions"], "service_groups": ["compute", "storage", "database", "network"]}, expected=200)
        self.request("PUT", "/settings", self.manifest["settings"], expected=200)
        _, queued = self.request("POST", "/scans", expected=202)
        scan_id = queued["scan_id"]
        deadline = time.time() + 900
        rows = []
        while time.time() < deadline:
            _, status = self.request("GET", "/scans/" + scan_id, expected=200)
            rows = status["results"]
            if ({row.get("region") for row in rows} == set(self.manifest["regions"])
                    and len(rows) == len(self.manifest["regions"])
                    and all(row.get("scan_id") == scan_id and row.get("status") in {"SUCCEEDED", "PARTIAL", "FAILED", "TIMED_OUT"} for row in rows)):
                break
            time.sleep(5)
        else:
            self.fail("Scan did not reach a terminal state within 15 minutes")
        self.assertTrue(all(row.get("status") == "SUCCEEDED" for row in rows), rows)
        self.request("GET", "/scans/" + scan_id, token=self.second_token, expected=404)
        _, current = self.request("GET", "/findings", expected=200)
        self.assertEqual({row.get("region") for row in current["results"]}, set(self.manifest["regions"]))
        self.assertTrue(all(row.get("scan_id") == scan_id for row in current["results"]), current)
        # RESULT becomes terminal before notification and HISTORY publication.
        history_deadline = time.monotonic() + 120
        while True:
            history = self.pages("/history?limit=1")
            if {row.get("region") for row in history if row.get("scan_id") == scan_id} == set(self.manifest["regions"]):
                break
            if time.monotonic() >= history_deadline:
                self.fail("Completed scan was not recorded in every configured region within 2 minutes")
            time.sleep(2)
        other_history = self.pages("/history?limit=1", token=self.second_token)
        self.assertFalse(any(row.get("scan_id") == scan_id for row in other_history))
        findings = [finding for row in current["results"] for finding in row.get("findings", [])]
        for finding in findings:
            if finding.get("reason") == "Missing CloudWatch metrics; not classified as idle":
                self.assertEqual(finding.get("level"), "INSUFFICIENT_DATA")
        by_key = {(finding.get("type"), finding.get("region"), finding.get("resource_id")): finding for finding in findings}
        checks = []
        for expected in self.manifest["required_findings"]:
            key = (expected["type"], expected["region"], expected["resource_id"])
            self.assertIn(key, by_key, "Required AWS finding absent: " + repr(key))
            self.assertIn(by_key[key]["level"], expected["allowed_levels"])
            checks.append({"type": expected["type"], "result": "PASS", "finding_id": by_key[key]["finding_id"]})
        for expected in self.manifest["optional_findings"]:
            if "skip_reason" in expected:
                checks.append({"type": expected["type"], "result": "SKIPPED", "reason": expected["skip_reason"]})
                continue
            key = (expected["type"], expected["region"], expected["resource_id"])
            self.assertIn(key, by_key, "Optional service declared for evidence but finding absent: " + repr(key))
            self.assertIn(by_key[key]["level"], expected["allowed_levels"])
            checks.append({"type": expected["type"], "result": "PASS", "finding_id": by_key[key]["finding_id"]})
        self.evidence.update(
            completed_at=self._timestamp(),
            account_id=connection.get("account_id"),
            regions=self.manifest["regions"],
            scan_id=scan_id,
            regional_status=[{"region": row.get("region"), "status": row.get("status"), "errors": row.get("errors", [])} for row in rows],
            history_rows=len(history),
            scanner_checks=checks,
            credentials_redacted=True,
        )
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        self.evidence_path.write_text(json.dumps(self.evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
