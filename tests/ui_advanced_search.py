"""Advanced search/filter acceptance: dates, history scope, diff, families.

Local fixtures only. No AWS calls, no deployment.
"""
import copy
import hashlib
import json
import os
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('UI_QA_DIR', ROOT / '.preflight/ui-advanced-search'))
OUT.mkdir(parents=True, exist_ok=True)
R1, R2 = 'ap-southeast-1', 'ap-southeast-2'
S_NOW = '99999999-1111-4111-8111-999999999999'
S_PREV = '88888888-2222-4222-8222-888888888888'
S_PARTIAL = '77777777-3333-4333-8333-777777777777'
S_HIST1 = '66666666-4444-4444-8444-666666666666'
S_HIST2 = '55555555-5555-4555-8555-555555555555'
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


def finding(kind, rid, level, rule, reason, region=R1, evidence=None, evaluated='2026-10-30T10:00:00Z',
            last_seen=None, acknowledged=False, resource_type=None):
    return {'type': kind, 'resource_id': rid, 'region': region, 'level': level, 'rule_id': rule,
            'reason': reason, 'evidence': evidence or {}, 'finding_id': fid(kind + rid + rule),
            'account_id': PROFILE['account_id'], 'recommendation': 'Kiểm tra mục đích sử dụng.',
            'first_seen_at': '2026-10-20T00:00:00Z', 'last_seen_at': last_seen or evaluated,
            'evaluated_at': evaluated, 'acknowledged': acknowledged}


UNATTACHED = 'Unattached volume; validate data retention'
NOW_R1 = [
    finding('EBS', 'vol-shared', 'REVIEW', 'EBS_UNATTACHED', UNATTACHED,
            evidence={'observed_hours': 48, 'thresholds': {'orphan_hours': 24}},
            evaluated='2026-10-30T17:30:00Z', last_seen='2026-10-30T17:30:00Z'),
    finding('EC2', 'i-new', 'REVIEW', 'EC2_LOW_UTILIZATION',
            'Low CPU and network; confirm intended workload',
            evidence={'cpu_p95': 1.5}, evaluated='2026-10-29T08:00:00Z'),
    finding('EBS', 'vol-level', 'REVIEW', 'EBS_UNATTACHED', UNATTACHED,
            evidence={'observed_hours': 90}, evaluated='2026-10-29T09:00:00Z'),
    finding('LAMBDA_FUNCTION', 'fn-orders', 'INSUFFICIENT_DATA', 'LAMBDA_UNUSED',
            'Missing CloudWatch metrics; not classified as idle',
            evidence={'function_name': 'orders-worker'}, evaluated='2026-10-28T08:00:00Z'),
    finding('S3_MULTIPART', 'archive-bucket/logs.bin', 'REVIEW', 'S3_STALE_MULTIPART',
            'Multipart upload older than 7 days; confirm whether it is still needed',
            evidence={'bucket': 'archive-bucket', 'key': 'logs.bin', 'observed_hours': 10},
            evaluated='2026-10-27T08:00:00Z'),
    finding('RDS', 'db-prod', 'REVIEW', 'RDS_LOW_UTILIZATION',
            'Low database activity; confirm intended workload',
            evidence={'cpu_p95': 2}, evaluated='2026-10-26T08:00:00Z'),
    finding('RDS', 'db-prod', 'REVIEW', 'RDS_HIGH_CONNECTIONS',
            'Low database activity; confirm intended workload',
            evidence={'connections_p95': 1}, evaluated='2026-10-26T08:00:00Z', acknowledged=True),
]
NOW_R2 = [
    finding('EIP', 'eip-region-two', 'REVIEW', 'EIP_UNASSOCIATED',
            'Unassociated public IPv4; may be intentionally reserved',
            region=R2, evidence={'observed_hours': 12}, evaluated='2026-10-25T08:00:00Z'),
]
PREV_R1 = [
    finding('EBS', 'vol-shared', 'REVIEW', 'EBS_UNATTACHED', UNATTACHED,
            evaluated='2026-10-20T10:00:00Z'),
    finding('EBS', 'vol-level', 'OBSERVING', 'EBS_UNATTACHED', UNATTACHED,
            evaluated='2026-10-20T10:00:00Z'),
    finding('EC2', 'i-old', 'REVIEW', 'EC2_LOW_UTILIZATION',
            'Low CPU and network; confirm intended workload',
            evaluated='2026-10-20T10:00:00Z'),
]
PREV_R2 = [
    finding('EIP', 'eip-region-two', 'REVIEW', 'EIP_UNASSOCIATED',
            'Unassociated public IPv4; may be intentionally reserved',
            region=R2, evaluated='2026-10-20T10:00:00Z'),
]
PARTIAL_R1 = [
    finding('EBS', 'vol-partial', 'REVIEW', 'EBS_UNATTACHED', UNATTACHED,
            evaluated='2026-10-18T10:00:00Z'),
]
HIST1_R1 = [
    finding('EBS', 'vol-shared', 'REVIEW', 'EBS_UNATTACHED', UNATTACHED,
            evaluated='2026-10-15T10:00:00Z'),
    finding('EBS', 'vol-lastpage', 'REVIEW', 'EBS_UNATTACHED', UNATTACHED,
            evaluated='2026-10-15T11:00:00Z'),
]
HIST2_R1 = [
    finding('EBS', 'vol-shared', 'REVIEW', 'EBS_UNATTACHED', UNATTACHED,
            evaluated='2026-10-10T10:00:00Z'),
]


def row(scan_id, region, findings, status='SUCCEEDED', started=1793000000, counts=None, errors=None):
    return {'region': region, 'scan_id': scan_id, 'status': status, 'trigger': 'manual',
            'started_at': started, 'completed_at': started + 60,
            'counts': counts if counts is not None else {'EBS': 10, 'EC2': 4, 'RDS': 3},
            'finding_count': len(findings), 'errors': errors or [],
            'findings': copy.deepcopy(findings)}


ROWS = {
    S_NOW: [row(S_NOW, R1, NOW_R1, started=1794000000), row(S_NOW, R2, NOW_R2, started=1794000000)],
    S_PREV: [row(S_PREV, R1, PREV_R1, started=1793000000), row(S_PREV, R2, PREV_R2, started=1793000000)],
    S_PARTIAL: [row(S_PARTIAL, R1, PARTIAL_R1, status='PARTIAL', started=1792000000,
                    counts={}, errors=[{'type': 'EC2', 'code': 'AccessDenied'}])],
    S_HIST1: [row(S_HIST1, R1, HIST1_R1, started=1791000000)],
    S_HIST2: [row(S_HIST2, R1, HIST2_R1, started=1790000000)],
}
HISTORY_ROWS = ROWS[S_NOW] + ROWS[S_PREV] + ROWS[S_PARTIAL] + ROWS[S_HIST1] + ROWS[S_HIST2]
ALL_NOW = NOW_R1 + NOW_R2


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(ROOT / 'web')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_address[1])
    state = {'latest': S_NOW, 'requests': []}
    checks, errors = [], []

    def api(route):
        request = route.request
        url = request.url
        path = url.split('/api')[-1].split('?')[0]
        query = {}
        if '?' in url:
            for part in url.split('?', 1)[1].split('&'):
                key, _, value = part.partition('=')
                query[key] = value
        state['requests'].append({'method': request.method, 'path': path, 'auth': request.headers.get('authorization', '')})
        if path == '/me':
            payload = PROFILE
        elif path == '/findings':
            payload = {'results': copy.deepcopy(ROWS[state['latest']])}
        elif path == '/history':
            start = int(query.get('next_token') or 0)
            page = copy.deepcopy(HISTORY_ROWS[start:start + 3])
            next_token = str(start + 3) if start + 3 < len(HISTORY_ROWS) else None
            payload = {'results': page, 'next_token': next_token}
        elif path.startswith('/scans/'):
            payload = {'results': copy.deepcopy(ROWS.get(path.rsplit('/', 1)[-1], []))}
        elif path == '/feedback':
            payload = {'results': [], 'next_token': None}
        else:
            payload = {}
        route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))

    def rows():
        return page.locator('#findings-list tbody tr')

    def expand(level, service):
        group = page.locator('#findings-list section.service-group[data-level="' + level + '"][data-service="' + service + '"]')
        toggle = group.locator('.group-toggle')
        if toggle.count() and toggle.get_attribute('aria-expanded') == 'false':
            toggle.click()
        return group

    def set_date(name, value):
        page.locator('#date-' + name).fill(value)

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
            expect(rows()).to_have_count(len(ALL_NOW))

            # TC01/TC02: resource ID and resource name (evidence) search.
            page.locator('#search').fill('vol-shared')
            expect(rows()).to_have_count(1)
            page.locator('#search').fill('orders-worker')
            expect(rows()).to_have_count(1)
            expect(rows().first).to_contain_text('fn-orders')
            # Finding ID, rule ID, region and multi-token search.
            page.locator('#search').fill(fid('EBSvol-sharedEBS_UNATTACHED'))
            expect(rows()).to_have_count(1)
            page.locator('#search').fill('EBS_UNATTACHED   region:ap-southeast-1')
            expect(rows()).to_have_count(0)
            page.locator('#search').fill('ap-southeast-2')
            expect(rows()).to_have_count(1)
            expect(rows().first).to_contain_text('eip-region-two')
            page.locator('#search').fill('')
            checks.append('TC01/TC02 search covers resource ID, resource name, finding/rule ID and region')

            # TC03: combine service family, type, level, region, rule and ack.
            page.locator('#filter-service').select_option('EBS')
            page.locator('#filter-level').select_option('REVIEW')
            page.locator('#filter-region').select_option(R1)
            expect(rows()).to_have_count(2)
            page.locator('#filter-type').select_option('RDS')
            expect(rows()).to_have_count(0)
            page.locator('#filter-type').select_option('')
            page.locator('#filter-rule').select_option('EBS_UNATTACHED')
            expect(rows()).to_have_count(2)
            page.locator('#filter-acknowledged').select_option('acknowledged')
            expect(rows()).to_have_count(0)
            page.locator('#reset-filters').click()
            expect(rows()).to_have_count(len(ALL_NOW))
            checks.append('TC03 combined service/type/level/region/rule/ack filters')

            # TC04/TC05: VN date boundaries and invalid range.
            set_date('from', '2026-10-31')
            expect(rows()).to_have_count(1)
            expect(rows().first).to_contain_text('vol-shared')
            set_date('from', '')
            set_date('to', '2026-10-30')
            expect(rows()).to_have_count(len(ALL_NOW) - 1)
            expect(page.locator('#findings-list')).not_to_contain_text('vol-shared')
            set_date('from', '2026-11-05')
            set_date('to', '2026-10-01')
            expect(page.locator('#date-error')).to_be_visible()
            expect(page.locator('#date-error')).to_contain_text('Từ ngày phải trước')
            page.locator('#reset-filters').click()
            checks.append('TC04/TC05 dates use Vietnam day boundaries and reject inverted ranges')

            # TC09: two findings on one resource vs unique resource count.
            scope = page.locator('#findings-scope')
            expect(scope).to_contain_text('7/7 tài nguyên')
            expect(scope).to_contain_text('%d cảnh báo' % len(ALL_NOW))
            expect(page.locator('#findings-list')).to_contain_text('db-prod')
            checks.append('TC09 one resource with two findings is counted once')

            # TC10: status filters keep all three levels available.
            page.locator('#filter-level').select_option('OBSERVING')
            expect(rows()).to_have_count(0)
            page.locator('#filter-level').select_option('INSUFFICIENT_DATA')
            expect(rows()).to_have_count(1)
            expect(rows().first).to_contain_text('fn-orders')
            page.locator('#filter-level').select_option('REVIEW')
            expect(rows()).to_have_count(len(ALL_NOW) - 1)
            page.locator('#reset-filters').click()
            checks.append('TC10 evaluation statuses filter independently from scan status')

            # TC11: no fake severity controls; scan status is a separate dimension.
            assert page.locator('#filter-severity').count() == 0
            expect(page.locator('#filter-scan-status')).to_be_visible()
            page.locator('#filter-scan-status').select_option('FAILED')
            expect(rows()).to_have_count(0)
            page.locator('#reset-filters').click()
            checks.append('TC11 no severity model is invented; scan and finding status stay separate')

            # Diff filters require the previous scan and must not compare partial scans.
            page.locator('#filter-diff').select_option('new')
            expect(page.locator('#findings-list')).to_contain_text('i-new')
            expect(page.locator('#findings-list')).not_to_contain_text('vol-shared')
            page.locator('#filter-diff').select_option('existing')
            expect(page.locator('#findings-list')).to_contain_text('vol-shared')
            page.locator('#filter-diff').select_option('changed')
            expect(page.locator('#findings-list')).to_contain_text('vol-level')
            page.locator('#filter-diff').select_option('')
            checks.append('new/existing/changed derive from the previous completed scan only')

            # TC06/TC07: switching scan updates data; no old resource leaks.
            page.locator('#scan-select').select_option(S_PREV)
            expect(page.locator('#findings-list')).to_contain_text('i-old')
            expect(page.locator('#findings-list')).not_to_contain_text('i-new')
            page.locator('#scan-select').select_option(S_NOW)
            expect(page.locator('#findings-list')).not_to_contain_text('i-old')
            checks.append('TC06/TC07 scan switching replaces results without mixing scans')

            # TC08: history scope loads every page before searching.
            page.locator('#search-scope').select_option('history')
            expect(page.locator('#history-status')).to_contain_text('Đã tải')
            expect(page.locator('#history-status')).to_contain_text(str(len(HISTORY_ROWS)) + ' bản ghi')
            page.locator('#search').fill('vol-lastpage')
            expect(rows()).to_have_count(1)
            expect(rows().first).to_contain_text('vol-lastpage')
            expect(rows().first).to_contain_text('Lượt quét')
            page.locator('#search').fill('vol-shared')
            expect(rows()).to_have_count(4)
            expect(page.locator('#findings-scope')).to_contain_text('lần xuất hiện')
            expect(page.locator('#findings-scope')).to_contain_text('1/10 tài nguyên')
            page.locator('#search').fill('')
            # History date range filters by completed scan time (VN boundaries).
            set_date('from', '2026-10-03')
            set_date('to', '2026-10-03')
            expect(rows()).to_have_count(len(HIST1_R1))
            page.locator('#reset-filters').click()
            expect(page.locator('#search-scope')).to_have_value('current')
            checks.append('TC08 history mode paginates to the end and dates use scan completion time')

            # TC12: partial scan (now available from the fully loaded history) keeps its warning.
            page.locator('#scan-select').select_option(S_PARTIAL)
            expect(page.locator('#scan-errors-card')).to_be_visible()
            expect(page.locator('#scan-errors-card')).to_contain_text('AccessDenied')
            expect(page.locator('#findings-scope')).to_contain_text('chưa đầy đủ')
            page.locator('#scan-select').select_option(S_NOW)
            expect(page.locator('#findings-list')).to_contain_text('vol-shared')
            checks.append('TC12 partial scan shows collection errors and no safe-account claim')

            # TC13: reset clears all filters and returns to current scan mode.
            page.locator('#filter-service').select_option('RDS')
            page.locator('#filter-scan-status').select_option('SUCCEEDED')
            set_date('from', '2026-10-01')
            page.locator('#search').fill('db')
            page.locator('#reset-filters').click()
            assert page.locator('#filter-service').input_value() == ''
            assert page.locator('#filter-scan-status').input_value() == ''
            assert page.locator('#date-from').input_value() == ''
            assert page.locator('#search').input_value() == ''
            expect(rows()).to_have_count(len(ALL_NOW))
            checks.append('TC13 reset clears every filter and restores the current-scan scope')

            # TC14: every API call is authenticated; rendered accounts stay in tenant.
            assert all(entry['auth'].startswith('Bearer ') for entry in state['requests'] if entry['path'] != ''), 'missing auth'
            page.locator('#search').fill('')
            text=page.locator('#findings-list').inner_text()
            assert 'Account: 999999999999' not in text
            assert 'Account: ' + PROFILE['account_id'] in text
            checks.append('TC14 all requests are authenticated and only tenant account data is rendered')

            # TC16: keyboard search and reset; PRM-friendly controls.
            page.locator('#search').focus()
            page.keyboard.type('vol-level')
            expect(rows()).to_have_count(1)
            page.locator('#reset-filters').focus()
            page.keyboard.press('Enter')
            expect(rows()).to_have_count(len(ALL_NOW))
            checks.append('TC16 search and reset work from the keyboard')

            # TC15: mobile layout.
            for width in (390, 320):
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                page.screenshot(path=str(OUT / ('advanced-%s.png' % width)), full_page=True)
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.screenshot(path=str(OUT / 'advanced-1440.png'), full_page=True)
            checks.append('TC15 no horizontal overflow at 390/320px')

            assert not errors, errors
            checks.append('no JavaScript runtime errors')
            (OUT / 'acceptance-results.json').write_text(json.dumps(
                {'environment': 'LOCAL FIXTURES — NOT AWS', 'checks': checks, 'page_errors': errors},
                ensure_ascii=False, indent=2), encoding='utf-8')
            browser.close()
            print('Advanced search PASS:\n' + '\n'.join(checks))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
