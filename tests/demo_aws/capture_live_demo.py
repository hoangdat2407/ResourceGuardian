"""Capture live demo screenshots and verify full UI interaction with real AWS experiment data."""
import json, pathlib, threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
from playwright.sync_api import sync_playwright, expect

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS_SCREENSHOTS = ROOT / "docs" / "screenshots"
DOCS_SCREENSHOTS.mkdir(parents=True, exist_ok=True)
SCAN_DATA = json.load(open("/tmp/scan_result.json"))

PROFILE_DATA = {
    "account_id": "376129867108",
    "role_arn": "arn:aws:iam::376129867108:role/GuardianReadRole-demo",
    "regions": ["ap-southeast-1"],
    "service_groups": ["compute", "storage", "database", "network", "serverless", "monitoring", "security", "backup", "containers", "nosql", "integration"],
    "external_id": "d31fae05-6d60-4f49-9631-ef06d084280f",
    "settings": {
        "cpu_percent": 5.0, "network_mib_hour": 1.0, "window_hours": 24, "interval_hours": 6,
        "lambda_unused_days": 45, "lambda_max_invocations": 0, "asg_zero_days": 7, "ecs_empty_days": 7,
        "eks_idle_days": 14, "orphan_hours": 24, "snapshot_days": 30, "rds_snapshot_days": 90,
        "efs_no_mount_days": 7, "ecr_image_days": 90, "fsx_idle_days": 14, "backup_point_days": 180,
        "rds_cpu_percent": 5.0, "rds_connections": 1, "dynamodb_idle_days": 14, "elasticache_idle_days": 7,
        "memorydb_idle_days": 7, "documentdb_idle_days": 7, "neptune_idle_days": 14, "nat_mib_hour": 1.0,
        "alb_requests_hour": 1, "nlb_new_flows_hour": 1, "sg_unused_days": 14, "vpc_endpoint_unused_days": 14,
        "cloudfront_requests_day": 100, "sagemaker_idle_days": 7, "opensearch_idle_days": 7, "redshift_idle_days": 7,
        "msk_idle_days": 7, "kinesis_idle_days": 7, "log_group_retention_days": 30, "sqs_idle_days": 14,
        "sns_unused_days": 30, "eventbridge_unused_days": 30, "stepfunctions_unused_days": 30, "apigateway_unused_days": 14
    },
    "notifications": {"email": "hoangdat2407@gmail.com", "enabled": True},
    "connection_version": "b9bc9eac-546a-4b1c-93bc-82439af77cd2",
    "api_principal": "arn:aws:iam::376129867108:role/cloud-resource-guardian-ApiRole-So7rB7aEKrFT",
    "scan_principal": "arn:aws:iam::376129867108:role/cloud-resource-guardian-ScanRole-oykltlddshRl",
    "email_available": True
}

feedback_db = []

def run():
    print("[CAPTURE] Serving web/ directory locally to capture bugfixed UI with real AWS scan results...")
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT / "web"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    web_url = f"http://127.0.0.1:{port}/"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_init_script("sessionStorage.setItem('crg-token', 'live-demo-token')")
        page = context.new_page()

        def route_api(route):
            url = route.request.url
            method = route.request.method
            if url.endswith("/me"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(PROFILE_DATA))
            elif url.endswith("/findings"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"results": SCAN_DATA["results"]}))
            elif url.endswith("/history?limit=20") or "/history" in url:
                history_rows = [{**SCAN_DATA["results"][0], "created_at": 1794046590}]
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"results": history_rows, "next_token": None}))
            elif "/feedback" in url and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"results": feedback_db, "next_token": None}))
            elif "/feedback" in url and method == "PUT":
                post_data = route.request.post_data_json or {}
                record = {**post_data, "updated_at": 1794046700}
                feedback_db.append(record)
                route.fulfill(status=200, content_type="application/json", body=json.dumps(record))
            elif "/settings" in url and method == "PUT":
                route.fulfill(status=200, content_type="application/json", body=route.request.post_data)
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))

        page.route("**/config.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"api": "/api", "demo": False, "auth": "https://crg-demo.auth.ap-southeast-1.amazoncognito.com", "clientId": "demo-client", "redirect": web_url})))
        page.route("**/api/**", route_api)
        page.goto(web_url)
        page.wait_for_selector("#app:not([hidden])", timeout=10000)

        # 1. Overview Page Screenshot
        expect(page.locator("#page-overview")).to_be_visible()
        expect(page.locator("#total")).not_to_have_text("—")
        page.screenshot(path=str(DOCS_SCREENSHOTS / "01-overview-partial-scan.png"))
        print("[1] Saved 01-overview-partial-scan.png")

        # 2. Findings Page Screenshot
        page.locator('[data-page="findings"]').click()
        expect(page.locator("#page-findings")).to_be_visible()
        expect(page.locator("#findings-list tbody tr")).to_have_count(9)
        page.screenshot(path=str(DOCS_SCREENSHOTS / "02-findings-real-aws.png"))
        print("[2] Saved 02-findings-real-aws.png")

        # 3. Evidence Detail - ECR No Lifecycle
        ecr_row = page.locator("#findings-list tr").filter(has_text="crg-demo-ecr-no-lifecycle")
        ecr_row.locator(".finding-open").click()
        expect(page.locator("#finding-dialog")).to_be_visible()
        expect(page.locator("#finding-detail-content")).to_contain_text("ECR_NO_LIFECYCLE")
        page.screenshot(path=str(DOCS_SCREENSHOTS / "03-evidence-ecr-no-lifecycle.png"))
        page.locator("#close-finding-detail").click()
        expect(page.locator("#finding-dialog")).not_to_be_visible()
        print("[3] Saved 03-evidence-ecr-no-lifecycle.png")

        # 4. Evidence Detail - Lambda Unused
        lambda_row = page.locator("#findings-list tr").filter(has_text="crg-demo-lambda-unused")
        lambda_row.locator(".finding-open").click()
        expect(page.locator("#finding-dialog")).to_be_visible()
        expect(page.locator("#finding-detail-content")).to_contain_text("python3.12")
        page.screenshot(path=str(DOCS_SCREENSHOTS / "04-evidence-lambda-unused.png"))
        page.locator("#close-finding-detail").click()
        print("[4] Saved 04-evidence-lambda-unused.png")

        # 5. Evidence Detail - ALB Insufficient Data
        alb_row = page.locator("#findings-list tr").filter(has_text="test-idle-alb")
        alb_row.locator(".finding-open").click()
        expect(page.locator("#finding-dialog")).to_be_visible()
        expect(page.locator("#finding-detail-content")).to_contain_text("ALB_LOW_UTILIZATION")
        page.screenshot(path=str(DOCS_SCREENSHOTS / "05-evidence-alb-insufficient-data.png"))
        page.locator("#close-finding-detail").click()
        print("[5] Saved 05-evidence-alb-insufficient-data.png")

        # 6. Interaction - Feedback Keep and Ignore
        page.locator("#findings-list tr").filter(has_text="crg-demo-lambda-unused").locator("button:has-text('Giữ lại')").click()
        expect(page.locator("#status")).to_contain_text("Đã giữ lại")
        page.screenshot(path=str(DOCS_SCREENSHOTS / "06-feedback-keep-ignore.png"))
        print("[6] Saved 06-feedback-keep-ignore.png")

        # 7. Settings Page Screenshot (6 Groups, 40 Fields, with Descriptions and Bounds)
        page.locator('[data-page="settings"]').click()
        expect(page.locator("#page-settings")).to_be_visible()
        expect(page.locator("details.settings-group")).to_have_count(6)
        page.screenshot(path=str(DOCS_SCREENSHOTS / "07-settings-6groups-40fields.png"))
        print("[7] Saved 07-settings-6groups-40fields.png")

        # 8. Mobile Viewport Screenshot
        mobile_ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        mobile_ctx.add_init_script("sessionStorage.setItem('crg-token', 'live-demo-token')")
        mp = mobile_ctx.new_page()
        mp.route("**/config.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"api": "/api", "demo": False, "auth": "https://crg-demo.auth.ap-southeast-1.amazoncognito.com", "clientId": "demo-client", "redirect": web_url})))
        mp.route("**/api/**", route_api)
        mp.goto(web_url + "#findings")
        mp.wait_for_selector("#findings-list tbody tr")
        assert mp.evaluate("document.documentElement.scrollWidth <= innerWidth")
        mp.screenshot(path=str(DOCS_SCREENSHOTS / "08-mobile-responsive-findings.png"))
        print("[8] Saved 08-mobile-responsive-findings.png")

        browser.close()
        server.shutdown()
        print("\n[SUCCESS] All live demo screenshots successfully captured!")

if __name__ == "__main__":
    run()
