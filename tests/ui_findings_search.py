"""Search, filter and sorting acceptance for the findings page.

Local fixtures only; no AWS calls. Covers combined filters, chart sync,
sorting, reset, scan switching and truncation messaging.
"""
import copy
import hashlib
import json
import os
import re
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('UI_QA_DIR', ROOT / '.preflight/ui-findings-search'))
OUT.mkdir(parents=True, exist_ok=True)
R1, R2 = 'ap-southeast-1', 'ap-southeast-2'
SCAN_A = 'aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa'
SCAN_B = 'bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb'
PROFILE = {
    'account_id': '123456789012', 'role_arn': 'arn:aws:iam::123456789012:role/GuardianReadRole-fixture',
    'regions': [R1, R2], 'service_groups': ['compute', 'storage', 'database', 'network'],
    'external_id': 'FIXTURE-ONLY-EXTERNAL-ID',
    'api_principal': 'arn:aws:iam::123456789012:role/FixtureApiPrincipal',
    'scan_principal': 'arn:aws:iam::123456789012:role/FixtureScanPrincipal',
    'settings': {}, 'notifications': {'enabled': False}, 'email_available': False,
}


def fid(seed):
    return hashlib.sha256(seed.encode()).hexdigest()


def finding(kind, rid, level, rule, reason, region=R1, evidence=None,
            last_seen='2026-10-30T00:00:00Z', acknowledged=False):
    return {'type': kind, 'resource_id': rid, 'region': region, 'level': level,
            'rule_id': rule, 'reason': reason, 'evidence': evidence or {},
            'finding_id': fid(kind + rid + rule), 'account_id': PROFILE['account_id'],
            'recommendation': 'Kiểm tra mục đích sử dụng.',
            'first_seen_at': '2026-10-28T00:00:00Z', 'last_seen_at': last_seen,
            'evaluated_at': last_seen, 'acknowledged': acknowledged}


UNATTACHED = 'Unattached volume; validate data retention'
FINDINGS_R1 = [
    finding('EBS', 'vol-aaa', 'REVIEW', 'EBS_UNATTACHED', UNATTACHED,
            evidence={'observed_hours': 48, 'thresholds': {'orphan_hours': 24}},
            last_seen='2026-10-31T00:00:00Z'),
    finding('EBS', 'vol-aaa', 'REVIEW', 'EBS_NO_SNAPSHOT', UNATTACHED,
            evidence={'observed_hours': 52}, last_seen='2026-10-31T00:00:00Z'),
    finding('EBS', 'vol-ccc', 'REVIEW', 'EBS_UNATTACHED', UNATTACHED,
            evidence={'observed_hours': 30}, last_seen='2026-10-30T00:00:00Z'),
    finding('EBS', 'vol-bbb', 'OBSERVING', 'EBS_UNATTACHED', UNATTACHED,
            evidence={'observed_hours': 6}, last_seen='2026-10-29T00:00:00Z'),
    finding('EC2', 'i-111', 'REVIEW', 'EC2_LOW_UTILIZATION',
            'Low CPU and network; confirm intended workload',
            evidence={'cpu_p95': 1.5}, acknowledged=True),
    finding('LAMBDA_FUNCTION', 'fn-1', 'REVIEW', 'LAMBDA_UNUSED',
            'Unused Lambda function with 0 invocations and no event source mappings',
            evidence={'function_name': 'process-orders'}),
    finding('RDS', 'db-1', 'REVIEW', 'RDS_LOW_UTILIZATION',
            'Low database activity; confirm intended workload', evidence={'cpu_p95': 2}),
    finding('S3_MULTIPART', 'archive-bucket/logs.bin', 'INSUFFICIENT_DATA', 'S3_STALE_MULTIPART',
            'Multipart initiation time unavailable; not classified as stale',
            evidence={'bucket': 'archive-bucket'}),
]
FINDINGS_R2 = [
    finding('EBS', 'vol-region-two', 'REVIEW', 'EBS_UNATTACHED', UNATTACHED, region=R2),
]
FINDINGS_B = [
    finding('EBS', 'vol-zzz', 'REVIEW', 'EBS_UNATTACHED', UNATTACHED,
            evidence={'observed_hours': 40}, last_seen=''),
]
for item in FINDINGS_B:
    item.pop('last_seen_at', None)
    item.pop('evaluated_at', None)


def row(scan_id, region, findings, counts, started):
    return {'region': region, 'scan_id': scan_id, 'status': 'SUCCEEDED', 'trigger': 'manual',
            'started_at': started, 'completed_at': started + 60, 'counts': counts,
            'finding_count': 40 if scan_id == SCAN_A and region == R1 else len(findings),
            'errors': [{'type': 'FINDING', 'code': 'RESOURCE_LIMIT'}] if scan_id == SCAN_A and region == R1 else [],
            'findings': copy.deepcopy(findings)}


ROWS = {
    SCAN_A: [row(SCAN_A, R1, FINDINGS_R1, {'EBS': 6, 'EC2': 2, 'RDS': 1, 'LAMBDA_FUNCTION': 1, 'S3_MULTIPART': 1}, 1793000000),
             row(SCAN_A, R2, FINDINGS_R2, {'EBS': 1}, 1793000000)],
    SCAN_B: [row(SCAN_B, R1, FINDINGS_B, {'EBS': 1}, 1794000000)],
}
ALL_A = FINDINGS_R1 + FINDINGS_R2


def unique_resources(items):
    return {(item['type'], item['resource_id']) for item in items}


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(ROOT / 'web')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_address[1])
    state = {'latest': SCAN_A, 'requests': []}
    checks, errors = [], []

    def api(route):
        request = route.request
        path = request.url.split('/api')[-1].split('?')[0]
        state['requests'].append((request.method, path))
        if path == '/me':
            payload = PROFILE
        elif path == '/findings':
            payload = {'results': copy.deepcopy(ROWS[state['latest']])}
        elif path == '/history':
            payload = {'results': copy.deepcopy(ROWS[SCAN_B] + ROWS[SCAN_A]), 'next_token': None}
        elif path.startswith('/scans/'):
            payload = {'results': copy.deepcopy(ROWS.get(path.rsplit('/', 1)[-1], []))}
        elif path == '/feedback':
            payload = {'results': [], 'next_token': None}
        else:
            payload = {}
        route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))

    def rows(container='#findings-list'):
        return page.locator(container + ' tbody tr')

    def expand(level, service):
        group = page.locator('#findings-list section.service-group[data-level="' + level + '"][data-service="' + service + '"]')
        toggle = group.locator('.group-toggle')
        if toggle.count() and toggle.get_attribute('aria-expanded') == 'false':
            toggle.click()
        return group

    def filter_ids():
        return {key: page.locator('#filter-' + key).input_value() for key in
                ['type', 'group', 'region', 'level', 'acknowledged']}

    try:
        with sync_playwright() as playwright:
            launch = {'headless': True}
            if os.environ.get('CHROMIUM_EXECUTABLE'):
                launch['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
            browser = playwright.chromium.launch(**launch)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_init_script("sessionStorage.setItem('crg-token','demo-local-only')")
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/config.json', lambda route: route.fulfill(json={'api': '/api', 'demo': True}))
            page.route('**/api/**', api)
            page.goto(base + '/#findings')
            expect(rows()).to_have_count(len(ALL_A))

            # 6: resource and finding counts are both explicit and different.
            total_resources, total_findings = len(unique_resources(ALL_A)), len(ALL_A)
            scope = page.locator('#findings-scope')
            expect(scope).to_contain_text('%d tài nguyên' % total_resources)
            expect(scope).to_contain_text('%d cảnh báo' % total_findings)
            # 11: truncated backend data must not be presented as a complete search.
            expect(scope).to_contain_text('Chỉ tìm kiếm trên')
            checks.append('scope separates resources/findings and discloses truncated data')

            search = page.locator('#search')
            cases = [
                ('vol-aaa', 2),
                ('Amazon EBS', len([f for f in ALL_A if f['type'] == 'EBS'])),
                ('EC2_LOW_UTILIZATION', 1),
                ('Volume chưa gắn', len([f for f in ALL_A if f['type'] == 'EBS'])),
                ('process-orders', 1),
                ('unused lambda', 1),
            ]
            for query, expected in cases:
                search.fill(query)
                expect(rows()).to_have_count(expected)
            search.fill('')
            checks.append('search covers resource ID, service name, rule ID, Vietnamese reason and resource name')

            page.locator('#advanced-filters summary').click()
            expect(page.locator('#filter-type')).to_be_visible()

            # 2/7: primary service + status filters, advanced region, and chart sync.
            page.locator('#filter-type').select_option('EBS')
            page.locator('#filter-level').select_option('REVIEW')
            expect(rows()).to_have_count(4)
            expect(page.locator('.service-bar')).to_have_count(1)
            page.locator('#filter-region').select_option(R2)
            expect(rows()).to_have_count(1)
            expect(rows().first).to_contain_text('vol-region-two')
            page.locator('#filter-region').select_option('')
            page.locator('#filter-level').select_option('OBSERVING')
            expect(rows()).to_have_count(1)
            expect(rows().first).to_contain_text('vol-bbb')
            page.locator('#filter-level').select_option('')
            page.locator('#filter-type').select_option('')
            page.locator('#filter-acknowledged').select_option('acknowledged')
            expect(rows()).to_have_count(1)
            expect(rows().first).to_contain_text('i-111')
            page.locator('#filter-acknowledged').select_option('unacknowledged')
            expect(rows()).to_have_count(len(ALL_A) - 1)
            page.locator('#filter-acknowledged').select_option('')
            checks.append('service/status/region/ack filters combine and stay in sync with the chart')

            # 3: advanced resource-group filter.
            page.locator('#filter-group').select_option('storage')
            expected_storage = len([f for f in ALL_A if f['type'] in ('EBS', 'SNAPSHOT', 'S3_MULTIPART')])
            expect(rows()).to_have_count(expected_storage)
            page.locator('#filter-group').select_option('')
            checks.append('advanced resource-group filter narrows the same data set')

            # 4: sorting service name and resource ID.
            order = page.locator('#sort-order')
            order.select_option('service-desc')
            first_group = page.locator('#findings-list section.service-group').first
            expect(first_group).to_have_attribute('data-service', 'LAMBDA_FUNCTION')
            order.select_option('resource-desc')
            ebs = expand('REVIEW', 'EBS')
            expect(ebs.locator('tbody tr code').first).to_have_text('vol-region-two')
            order.select_option('observed-desc')
            ebs = expand('REVIEW', 'EBS')
            expect(ebs.locator('tbody tr code').first).to_have_text('vol-aaa')
            order.select_option('default')
            checks.append('sorting by service and resource ID reorders groups and rows')

            # 5: reset restores every filter and the default sort.
            search.fill('vol-aaa')
            page.locator('#filter-type').select_option('EBS')
            page.locator('#filter-level').select_option('REVIEW')
            order.select_option('service-asc')
            page.locator('#reset-filters').click()
            assert search.input_value() == '', search.input_value()
            assert filter_ids() == {key: '' for key in filter_ids()}, filter_ids()
            assert order.input_value() == 'default', order.input_value()
            expect(rows()).to_have_count(len(ALL_A))
            checks.append('reset button clears search, filters and sorting')

            # 8: chart click applies the matching service filter and opens its group.
            page.locator('#filter-level').select_option('OBSERVING')
            page.locator('.service-bar[data-service="EBS"]').click()
            assert page.locator('#filter-service').input_value() == 'EBS' and filter_ids()['level'] == '', filter_ids()
            expect(page.locator('.service-bar')).to_have_count(1)
            expect(page.locator('#findings-list section.service-group[data-level="REVIEW"][data-service="EBS"] .group-toggle')).to_have_attribute('aria-expanded', 'true')
            page.locator('#reset-filters').click()
            checks.append('chart click applies the service filter and keeps chart/accordion consistent')

            # 12: empty state with a reset action.
            page.locator('#filter-type').select_option('RDS')
            page.locator('#filter-region').select_option(R2)
            expect(page.locator('#findings-list')).to_contain_text('Không khớp bộ lọc')
            page.locator('.empty-reset').click()
            expect(rows()).to_have_count(len(ALL_A))
            checks.append('empty state explains no match and reset restores results')

            # 9/10: scan switch resets filters, never mixes scans, statuses stay reachable.
            search.fill('vol-aaa')
            page.locator('#filter-type').select_option('EBS')
            order.select_option('resource-desc')
            state['latest'] = SCAN_B
            page.locator('#scan-select').select_option(SCAN_B)
            expect(rows()).to_have_count(1)
            expect(rows().first).to_contain_text('vol-zzz')
            assert search.input_value() == '' and filter_ids()['type'] == '' and page.locator('#filter-service').input_value() == '' and order.input_value() == 'default'
            expect(page.locator('#sort-order option[value="observed-desc"]')).to_have_attribute('disabled', '')
            state['latest'] = SCAN_A
            page.locator('#scan-select').select_option(SCAN_A)
            expect(rows()).to_have_count(len(ALL_A))
            expect(page.locator('#findings-list')).not_to_contain_text('vol-zzz')
            expect(page.locator('#findings-list section[data-level="OBSERVING"]')).to_have_count(1)
            expect(page.locator('#findings-list section[data-level="INSUFFICIENT_DATA"]')).to_have_count(1)
            checks.append('scan switch resets filters, avoids mixed data and keeps every status reachable')

            # 14: keyboard access to search/reset and no overflow on mobile.
            search.focus()
            page.keyboard.type('vol-ccc')
            expect(rows()).to_have_count(1)
            page.locator('#reset-filters').focus()
            page.keyboard.press('Enter')
            expect(rows()).to_have_count(len(ALL_A))
            for width in (390, 320):
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                page.screenshot(path=str(OUT / ('search-%s.png' % width)), full_page=True)
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.screenshot(path=str(OUT / 'search-1440.png'), full_page=True)
            checks.append('keyboard search/reset work and the filter bar fits 390/320px')

            assert not errors, errors
            checks.append('no JavaScript runtime errors')
            (OUT / 'acceptance-results.json').write_text(json.dumps(
                {'environment': 'LOCAL FIXTURES — NOT AWS', 'checks': checks, 'page_errors': errors},
                ensure_ascii=False, indent=2), encoding='utf-8')
            browser.close()
            print('Findings search/filter PASS:\n' + '\n'.join(checks))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
