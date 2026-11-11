"""Email report rendering: pure HTML/text, HTML escaping and scan states.

No AWS calls and no real email are made here.
"""
import unittest

from src.email_report import build_email

PROFILE = {"account_id": "123456789012", "external_id": "FIXTURE-EXTERNAL-ID"}
BASE_RESULT = {
    "region": "ap-southeast-1",
    "scan_id": "scan-fixture",
    "status": "SUCCEEDED",
    "completed_at": 1800000000,
    "counts": {"EBS": 4, "EC2": 2},
    "finding_count": 3,
    "findings": [],
}


def finding(kind="EBS", resource_id="vol-demo", level="REVIEW", rule="EBS_UNATTACHED",
            reason="Unattached volume; validate data retention", evidence=None):
    return {"type": kind, "resource_id": resource_id, "level": level, "rule_id": rule,
            "reason": reason, "evidence": evidence}


def result(status="SUCCEEDED", findings=None, **extra):
    payload = {**BASE_RESULT, "status": status, "findings": list(findings or [])}
    payload.update(extra)
    return payload


class EmailReport(unittest.TestCase):
    def test_zero_findings_has_clear_empty_state_and_no_button(self):
        content = build_email(PROFILE, result(findings=[], finding_count=0), web_url="")
        self.assertIn("Không có cảnh báo REVIEW", content["text"])
        self.assertIn("Không có cảnh báo REVIEW", content["html"])
        self.assertNotIn("Xem chi tiết trên Dashboard", content["html"])
        self.assertIn("0 tài nguyên", content["subject"])
        self.assertIn("Tổng findings của lượt quét: 0", content["text"])

    def test_single_finding_includes_service_reason_evidence_and_threshold(self):
        item = finding(evidence={"observed_hours": 49.5, "thresholds": {"orphan_hours": 24}})
        content = build_email(PROFILE, result(findings=[item]), web_url="https://guardian.example/")
        self.assertIn("Amazon EBS", content["text"])
        self.assertIn("vol-demo", content["text"])
        self.assertIn("Volume chưa gắn với EC2", content["text"])
        self.assertIn("Thời gian theo dõi 49,5 giờ", content["text"])
        self.assertIn("ngưỡng theo dõi 24 giờ", content["text"])
        self.assertIn("1 tài nguyên", content["subject"])
        self.assertEqual(content["html"].count("Xem chi tiết trên Dashboard"), 1)

    def test_top_resources_are_limited_to_five_but_service_stats_keep_everything(self):
        findings = [finding(resource_id="vol-%d" % index, evidence={"observed_hours": 30})
                    for index in range(7)]
        content = build_email(PROFILE, result(findings=findings), web_url="https://guardian.example/")
        for index in range(5):
            self.assertIn("vol-%d" % index, content["text"])
        for index in range(5, 7):
            self.assertNotIn("vol-%d" % index, content["text"])
        self.assertIn("7 cảnh báo / 7 tài nguyên", content["text"])
        self.assertIn("7 tài nguyên cần kiểm tra", content["subject"])

    def test_multiple_findings_on_one_resource_count_as_one_resource(self):
        findings = [
            finding(resource_id="vol-same", rule="EBS_UNATTACHED", evidence={"observed_hours": 30}),
            finding(resource_id="vol-same", rule="EBS_NO_SNAPSHOT",
                    reason="Old snapshot not referenced by listed AMIs; backup purpose requires review",
                    evidence={"age_days": 60}),
        ]
        content = build_email(PROFILE, result(findings=findings),
                              web_url="https://guardian.example/")
        self.assertIn("1 tài nguyên", content["subject"])
        self.assertIn("Tài nguyên cần kiểm tra (REVIEW): 1", content["text"])
        self.assertIn("Tổng findings của lượt quét: 3", content["text"])  # backend finding_count
        self.assertIn("2 cảnh báo / 1 tài nguyên", content["text"])
        self.assertEqual(content["html"].count("vol-same"), 1)

    def test_partial_scan_warns_and_lists_unscanned_services_with_distinct_hints(self):
        errors = [{"type": "EC2", "code": "AccessDenied"},
                  {"type": "RDS", "code": "SubscriptionRequiredException"}]
        content = build_email(PROFILE, result(status="PARTIAL", findings=[finding()], errors=errors),
                              web_url="https://guardian.example/")
        self.assertIn("Lượt quét chưa đầy đủ", content["text"])
        self.assertIn("thiếu quyền IAM", content["text"])
        self.assertIn("chưa kích hoạt subscription", content["text"])
        self.assertIn("AccessDenied", content["text"])
        self.assertIn("Lượt quét chưa đầy đủ", content["html"])
        self.assertIn("Dịch vụ chưa quét được", content["html"])
        self.assertIn("Dịch vụ gặp lỗi khi quét: 2", content["text"])

    def test_failed_scan_never_claims_the_account_is_safe(self):
        content = build_email(PROFILE, result(status="FAILED", findings=[]), web_url="")
        self.assertIn("Lượt quét không thành công", content["text"])
        self.assertIn("Không kết luận", content["text"])
        self.assertIn("Không kết luận", content["html"])
        self.assertNotIn("tài khoản của bạn an toàn", content["text"].lower())
        self.assertNotIn("không có vấn đề", content["text"].lower())
        self.assertNotIn("tài khoản của bạn an toàn", content["html"].lower())

    def test_long_resource_id_is_kept_and_wraps(self):
        long_id = "arn:aws:ec2:ap-southeast-1:123456789012:volume/" + "x" * 600
        content = build_email(PROFILE, result(findings=[finding(resource_id=long_id)]),
                              web_url="https://guardian.example/")
        self.assertIn(long_id, content["text"])
        self.assertIn(long_id, content["html"])
        self.assertIn("word-break:break-all", content["html"])

    def test_missing_or_null_evidence_is_handled(self):
        findings = [
            finding(resource_id="vol-no-evidence", evidence=None),
            finding(resource_id="vol-empty-evidence", evidence={}),
            finding(resource_id="vol-none-value", evidence={"size_gib": None}),
        ]
        content = build_email(PROFILE, result(findings=findings), web_url="")
        self.assertNotIn("None", content["text"] + content["html"])
        self.assertNotIn('"evidence"', content["text"] + content["html"])
        self.assertNotIn("Bằng chứng:", content["text"])

    def test_dangerous_values_are_escaped_in_html(self):
        malicious = finding(
            resource_id='"><script>window.x=1</script>',
            reason='<img src=x onerror="window.y=2">',
            evidence={"observed_hours": 10},
        )
        errors = [{"type": "<svg onload=alert(1)>", "code": "AccessDenied"}]
        content = build_email(
            {**PROFILE, "account_id": "<b>123</b>"},
            result(status="PARTIAL", findings=[malicious], errors=errors,
                   scan_id='<script>scan</script>'),
            web_url="javascript:alert(1)",
        )
        html = content["html"]
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("<img", html.lower())
        self.assertNotIn("<svg", html.lower())
        self.assertNotIn("onerror=", html.lower())
        self.assertNotIn("javascript:", html.lower())
        self.assertIn("&lt;script&gt;window.x=1", html)
        self.assertIn("&lt;b&gt;123&lt;/b&gt;", html)
        self.assertNotIn("onerror=", html.lower())
        self.assertNotIn("Xem chi tiết trên Dashboard", html)
        self.assertNotIn("FIXTURE-EXTERNAL-ID", content["text"] + html)

    def test_html_and_text_are_complete_documents(self):
        content = build_email(PROFILE, result(findings=[finding()], errors=[]),
                              web_url="https://guardian.example/")
        html, text = content["html"], content["text"]
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertTrue(html.rstrip().endswith("</html>"))
        self.assertIn('lang="vi"', html)
        self.assertIn("max-width:600px", html)
        self.assertIn("viewport", html)
        self.assertNotIn("<form", html.lower())
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("<img", html.lower())
        self.assertIn("CLOUD RESOURCE GUARDIAN", text)
        self.assertIn("Account ID: 123456789012", text)
        self.assertIn("Scan ID: scan-fixture", text)
        self.assertIn("không tự dừng hoặc xóa", text)
        self.assertIn("không tự dừng hoặc xóa", html)

    def test_values_are_utf8_safe(self):
        content = build_email(PROFILE, result(findings=[finding()]), web_url="")
        content["html"].encode("utf-8")
        content["text"].encode("utf-8")
        self.assertIn("Báo cáo tài nguyên AWS", content["html"])


if __name__ == "__main__":
    unittest.main()
