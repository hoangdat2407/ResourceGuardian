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
    def test_subject_uses_actual_unique_review_resources(self):
        findings = [finding(resource_id="vol-%d" % index) for index in range(7)]
        findings.append(finding(resource_id="vol-0", rule="EBS_SECOND_RULE"))
        content = build_email(PROFILE, result(findings=findings))
        self.assertEqual(
            content["subject"],
            "[Cloud Resource Guardian] 7 tài nguyên cần kiểm tra",
        )

    def test_three_kpis_cover_all_finding_statuses(self):
        findings = [
            finding(resource_id="vol-review"),
            finding(kind="LAMBDA_FUNCTION", resource_id="fn-observing", level="OBSERVING",
                    reason="Resource younger than observation window"),
            finding(kind="CLOUDFRONT_DISTRIBUTION", resource_id="dist-missing",
                    level="INSUFFICIENT_DATA",
                    reason="Missing CloudWatch metrics for CloudFront; not classified as idle"),
        ]
        content = build_email(PROFILE, result(findings=findings))
        for expected in (
            "Cần kiểm tra: 1",
            "Đang quan sát: 1",
            "Thiếu dữ liệu: 1",
            "vol-review",
            "fn-observing",
            "dist-missing",
        ):
            self.assertIn(expected, content["text"])
        self.assertNotIn("Tổng findings", content["text"] + content["html"])
        self.assertNotIn("Dịch vụ quét lỗi", content["text"] + content["html"])

    def test_top_resources_are_limited_to_five(self):
        findings = [finding(resource_id="vol-%d" % index) for index in range(7)]
        content = build_email(
            PROFILE,
            result(findings=findings),
            web_url="https://guardian.example/",
        )
        for index in range(5):
            self.assertIn("vol-%d" % index, content["text"])
        for index in range(5, 7):
            self.assertNotIn("vol-%d" % index, content["text"])
        self.assertIn("Còn 2 tài nguyên khác trên Dashboard.", content["text"])
        self.assertIn("Còn 2 tài nguyên khác trên Dashboard.", content["html"])

    def test_multiple_findings_on_one_resource_are_counted_once(self):
        findings = [
            finding(resource_id="vol-same", rule="EBS_UNATTACHED"),
            finding(resource_id="vol-same", rule="EBS_SECOND_RULE",
                    reason="Old snapshot not referenced by listed AMIs; backup purpose requires review"),
        ]
        content = build_email(PROFILE, result(findings=findings))
        self.assertIn("1 tài nguyên cần kiểm tra", content["subject"])
        self.assertIn("Cần kiểm tra: 1", content["text"])
        self.assertEqual(content["html"].count("vol-same"), 1)

    def test_resource_rows_are_simple_and_omit_technical_details(self):
        content = build_email(PROFILE, result(findings=[{
            **finding(evidence={"observed_hours": 49.5, "thresholds": {"orphan_hours": 24}}),
            "finding_id": "finding-secret",
            "stack_trace": "Traceback: secret",
        }]))
        combined = content["text"] + content["html"]
        self.assertIn("Amazon EBS", combined)
        self.assertIn("Volume chưa gắn với EC2", combined)
        for forbidden in (
            "EBS_UNATTACHED",
            "finding-secret",
            "observed_hours",
            "49.5",
            "49,5",
            "orphan_hours",
            "Traceback",
            "evidence",
        ):
            self.assertNotIn(forbidden, combined)

    def test_long_arn_is_shortened(self):
        long_id = "arn:aws:ec2:ap-southeast-1:123456789012:volume/" + "x" * 100
        content = build_email(
            PROFILE,
            result(findings=[finding(resource_id=long_id)]),
        )
        combined = content["text"] + content["html"]
        self.assertNotIn(long_id, combined)
        self.assertNotIn("arn:aws:", combined)
        self.assertIn("…", combined)

    def test_partial_scan_is_explicit_without_raw_error_codes(self):
        content = build_email(
            PROFILE,
            result(
                status="PARTIAL",
                findings=[finding()],
                errors=[{"type": "EC2", "code": "AccessDenied", "stack_trace": "secret"}],
            ),
            web_url="https://guardian.example/",
        )
        combined = content["text"] + content["html"]
        self.assertIn("Lượt quét chưa đầy đủ", content["text"])
        self.assertIn("Lượt quét chưa đầy đủ", content["html"])
        self.assertNotIn("quét thành công toàn bộ", combined.lower())
        self.assertNotIn("AccessDenied", combined)
        self.assertNotIn("stack_trace", combined)

    def test_failed_scan_never_claims_the_account_is_safe(self):
        content = build_email(PROFILE, result(status="FAILED", findings=[]))
        combined = content["text"] + content["html"]
        self.assertIn("Lượt quét không thành công", combined)
        self.assertEqual(
            content["subject"],
            "[Cloud Resource Guardian] Lượt quét không thành công",
        )
        self.assertNotIn("tài khoản aws an toàn", combined.lower())

    def test_zero_findings_uses_concise_template_without_zero_kpis(self):
        content = build_email(
            PROFILE,
            result(findings=[], finding_count=0),
            web_url="https://guardian.example/",
        )
        self.assertEqual(
            content["subject"],
            "[Cloud Resource Guardian] 0 tài nguyên cần kiểm tra",
        )
        self.assertIn("Không có tài nguyên cần kiểm tra", content["text"])
        self.assertNotIn("TỔNG QUAN", content["text"])
        self.assertNotIn("Tài nguyên nổi bật", content["html"])
        self.assertNotIn(">0</div>", content["html"])
        self.assertEqual(content["html"].count("Xem chi tiết trên Dashboard"), 1)

    def test_dashboard_link_is_escaped_and_drops_query_and_fragment(self):
        malicious = finding(
            resource_id='"><script>window.x=1</script>',
            reason='<img src=x onerror="window.y=2">',
        )
        content = build_email(
            PROFILE,
            result(findings=[malicious]),
            web_url="https://guardian.example/resources?access_token=secret#fragment",
        )
        html = content["html"]
        self.assertIn('href="https://guardian.example/resources"', html)
        for forbidden in ("access_token", "secret", "<script", "<img", "onerror=", "javascript:"):
            self.assertNotIn(forbidden, html.lower())
        self.assertIn("&lt;script&gt;window.x=1", html)
        self.assertNotIn("FIXTURE-EXTERNAL-ID", content["text"] + html)

    def test_unsafe_dashboard_links_are_omitted(self):
        for web_url in ("javascript:alert(1)", "http://guardian.example/"):
            with self.subTest(web_url=web_url):
                content = build_email(
                    PROFILE,
                    result(findings=[finding()]),
                    web_url=web_url,
                )
                self.assertNotIn(
                    "Xem chi tiết trên Dashboard",
                    content["text"] + content["html"],
                )

    def test_html_and_plain_text_are_equivalent_complete_documents(self):
        content = build_email(
            PROFILE,
            result(findings=[finding()], errors=[]),
            web_url="https://guardian.example/",
        )
        html, text = content["html"], content["text"]
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertTrue(html.rstrip().endswith("</html>"))
        self.assertIn('lang="vi"', html)
        self.assertIn("max-width:600px", html)
        self.assertIn("viewport", html)
        self.assertNotIn("<style", html.lower())
        self.assertNotIn("<form", html.lower())
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("<img", html.lower())
        for expected in (
            "Cloud Resource Guardian",
            "Kết quả quét tài nguyên AWS",
            "Hoàn tất",
            "Amazon EBS",
            "vol-demo",
            "Xem chi tiết trên Dashboard",
            "không tự dừng hoặc xóa",
        ):
            self.assertIn(expected, html)
            self.assertIn(expected, text)
        html.encode("utf-8")
        text.encode("utf-8")

if __name__ == "__main__":
    unittest.main()
