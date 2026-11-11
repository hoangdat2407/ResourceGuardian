"""Scan selection acceptance: one scan at a time, never mixed, using local fixtures.

Run with CHROMIUM_EXECUTABLE and UI_QA_DIR as for ui_smoke.py. Never calls AWS.
"""
import copy
import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading

from playwright.sync_api import expect, sync_playwright
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('UI_QA_DIR', ROOT / '.preflight/ui-scan-selection'))
OUT.mkdir(parents=True, exist_ok=True)
REGION = 'ap-southeast-1'
SCAN_A = '11111111-1111-4111-8111-111111111111'
SCAN_B = '22222222-2222-4222-8222-222222222222'
SCAN_C = '33333333-3333-4333-8333-333333333333'
PROFILE = {
    'account_id': '123456789012', 'role_arn': 'arn:aws:iam::123456789012:role/GuardianReadRole-fixture',
    'regions': [REGION], 'service_groups': ['compute', 'storage'], 'external_id': 'FIXTURE-ONLY-EXTERNAL-ID',
    'api_principal': 'arn:aws:iam::123456789012:role/FixtureApiPrincipal',
    'scan_principal': 'arn:aws:iam::123456789012:role/FixtureScanPrincipal',
    'settings': {}, 'notifications': {'enabled': False}, 'email_available': False,
}


def finding(finding_id, resource_id, level, reason, kind='EBS'):
    return {'finding_id': finding_id, 'type': kind, 'resource_id': resource_id, 'region': REGION,
            'account_id': PROFILE['account_id'], 'level': level, 'reason': reason,
            'rule_id': 'EBS_UNATTACHED', 'recommendation': 'Kiểm tra mục đích sử dụng.',
            'evidence': {'observed_hours': 30, 'thresholds': {'orphan_hours': 24}},
            'first_seen_at': '2026-10-28T00:00:00Z', 'last_seen_at': '2026-10-30T00:00:00Z',
            'evaluated_at': '2026-10-30T00:00:00Z'}


FINDINGS_A = [finding('a' * 64, 'vol-scan-a-1', 'REVIEW', 'Unattached volume; validate data retention'),
              finding('b' * 64, 'vol-scan-a-2', 'OBSERVING', 'Unattached volume; validate data retention')]
FINDINGS_B = [finding('c' * 64, 'vol-scan-b-1', 'REVIEW', 'Unattached volume; validate data retention')]


def result_row(scan_id, findings, status='SUCCEEDED', counts=None, errors=None, started_at=1793000000,
               completed_at=1793000060, trigger='manual'):
    return {'region': REGION, 'scan_id': scan_id, 'status': status, 'started_at': started_at,
            'completed_at': completed_at, 'trigger': trigger,
            'counts': counts if counts is not None else {'EBS': len(findings) + 3},
            'findings': copy.deepcopy(findings), 'errors': errors or []}


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    rows = {
        SCAN_A: [result_row(SCAN_A, FINDINGS_A, counts={'EBS': 5})],
        SCAN_B: [result_row(SCAN_B, FINDINGS_B, counts={'EBS': 4})],
        SCAN_C: [result_row(SCAN_C, [], status='PARTIAL', counts={},
                            errors=[{'type': 'EC2', 'code': 'AccessDenied'}], trigger='scheduled')],
    }
    state = {'profile': copy.deepcopy(PROFILE), 'latest': SCAN_B, 'requests': []}
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(ROOT / 'web')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_address[1])

    def api(route):
        request = route.request
        path = request.url.split('/api')[-1].split('?')[0]
        state['requests'].append((request.method, path))
        if path == '/me':
            payload = state['profile']
        elif path == '/findings':
            payload = {'results': copy.deepcopy(rows[state['latest']])}
        elif path == '/feedback':
            payload = {'results': [], 'next_token': None}
        elif path == '/history':
            payload = {'results': copy.deepcopy(rows[SCAN_A] + rows[SCAN_B] + rows[SCAN_C]), 'next_token': None}
        elif path.startswith('/scans/'):
            payload = {'results': copy.deepcopy(rows.get(path.rsplit('/', 1)[-1], []))}
        else:
            payload = {}
        route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))

    checks, errors = [], []
    try:
        with sync_playwright() as playwright:
            launch = {'headless': True}
            if os.environ.get('CHROMIUM_EXECUTABLE'):
                launch['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
            browser = playwright.chromium.launch(**launch)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000},
                                          permissions=['clipboard-read', 'clipboard-write'])
            context.add_init_script("sessionStorage.setItem('crg-token','demo-local-only')")
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/config.json', lambda route: route.fulfill(json={'api': '/api', 'demo': True}))
            page.route('**/api/**', api)
            page.goto(base + '/#overview')

            # TC01: dashboard is built from the latest scan only.
            expect(page.locator('#scan-summary')).to_contain_text(SCAN_B)
            expect(page.locator('#review')).to_have_text('1')
            expect(page.locator('#total')).to_have_text('4')
            checks.append('TC01 dashboard shows latest scan id, totals and REVIEW count')

            page.locator('[data-page="findings"]').click()
            expect(page.locator('#scan-select')).to_have_value(SCAN_B)
            expect(page.locator('#scan-snapshot-banner')).to_contain_text(SCAN_B)
            expect(page.locator('#findings-list tbody tr')).to_have_count(1)
            expect(page.locator('#findings-list')).to_contain_text('vol-scan-b-1')
            expect(page.locator('#findings-count-review')).to_have_text('1')
            expect(page.locator('#findings-count-observing')).to_have_text('0')
            expect(page.locator('#findings-count-insufficient')).to_have_text('0')
            checks.append('TC04 counts match the visible findings of scan B')

            # TC02: selecting scan A refreshes the whole view.
            page.locator('#scan-select').select_option(SCAN_A)
            expect(page.locator('#scan-snapshot-banner')).to_contain_text(SCAN_A)
            expect(page.locator('#findings-list tbody tr')).to_have_count(2)
            expect(page.locator('#findings-list')).to_contain_text('vol-scan-a-1')
            expect(page.locator('#findings-list')).not_to_contain_text('vol-scan-b-1')
            expect(page.locator('#findings-count-review')).to_have_text('1')
            expect(page.locator('#findings-count-observing')).to_have_text('1')
            checks.append('TC02 scan A shows only A findings and A counts')

            # TC03: switching back must not leave any A data behind.
            page.locator('#scan-select').select_option(SCAN_B)
            expect(page.locator('#findings-list')).to_contain_text('vol-scan-b-1')
            expect(page.locator('#findings-list')).not_to_contain_text('vol-scan-a')
            expect(page.locator('#findings-count-observing')).to_have_text('0')
            expect(page.locator('#scan-snapshot-banner')).to_contain_text('Thủ công')
            checks.append('TC03 switching scan leaves no previous-scan rows or counts')

            # TC05: detail belongs to the selected scan and resource.
            page.locator('#findings-list .finding-open').first.click()
            expect(page.locator('#finding-dialog')).to_be_visible()
            value = page.locator('#finding-detail-content [data-field="resource_id"] dd')
            expect(value).to_have_text('vol-scan-b-1')
            expect(page.locator('#finding-detail-content [data-field="scan_id"] dd')).to_have_text(SCAN_B)
            page.locator('#close-finding-detail').click()
            expect(page.locator('#finding-dialog')).not_to_be_visible()
            checks.append('TC05 finding detail matches the selected scan and resource')

            # A scheduled partial scan can still be viewed, with its errors.
            page.locator('#scan-select').select_option(SCAN_C)
            expect(page.locator('#scan-errors-card')).to_be_visible()
            expect(page.locator('#scan-errors-card')).to_contain_text('AccessDenied')
            expect(page.locator('#findings-list')).to_contain_text('Không có cảnh báo')
            expect(page.locator('#scan-snapshot-banner')).to_contain_text('Chưa đầy đủ')
            expect(page.locator('#scan-snapshot-banner')).to_contain_text('Theo lịch')
            checks.append('TC14 partial scan is viewable and exposes collection errors and trigger')

            page.locator('#scan-select').select_option(SCAN_B)
            page.locator('.copy-btn').click()
            assert page.evaluate('navigator.clipboard.readText()') == SCAN_B
            checks.append('TC10 scan id is copyable from the findings header')

            page.set_viewport_size({'width': 390, 'height': 844})
            page.locator('[data-page="findings"]').click()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(OUT / 'scan-selection-mobile.png'), full_page=True)
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.screenshot(path=str(OUT / 'scan-selection-desktop.png'), full_page=True)
            checks.append('TC11 no horizontal overflow while switching scans at 390px')

            assert not errors, errors
            (OUT / 'acceptance-results.json').write_text(json.dumps(
                {'environment': 'LOCAL FIXTURES — NOT AWS', 'checks': checks, 'page_errors': errors},
                ensure_ascii=False, indent=2), encoding='utf-8')
            browser.close()
            print('Scan selection PASS:\n' + '\n'.join(checks))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
