"""Resource overview acceptance: stats, service chart, accordions, filters, statuses.

Local fixtures only — never calls AWS. Run like the other UI suites:
  CHROMIUM_EXECUTABLE=/usr/bin/chromium UI_QA_DIR=/tmp/qa .venv/bin/python tests/ui_resource_overview.py
"""
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
OUT = Path(os.environ.get('UI_QA_DIR', ROOT / '.preflight/ui-resource-overview'))
OUT.mkdir(parents=True, exist_ok=True)
REGION = 'ap-southeast-1'
SCAN_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
SCAN_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
SCAN_C = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
SCAN_D = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
PROFILE = {
    'account_id': '123456789012', 'role_arn': 'arn:aws:iam::123456789012:role/GuardianReadRole-fixture',
    'regions': [REGION, 'ap-southeast-2'], 'service_groups': ['compute', 'storage', 'database', 'network'],
    'external_id': 'FIXTURE-ONLY-EXTERNAL-ID',
    'api_principal': 'arn:aws:iam::123456789012:role/FixtureApiPrincipal',
    'scan_principal': 'arn:aws:iam::123456789012:role/FixtureScanPrincipal',
    'settings': {}, 'notifications': {'enabled': False}, 'email_available': False,
}
COUNT_A = {'EBS': 6, 'EC2': 4, 'EIP': 2, 'NAT_GATEWAY': 2, 'LAMBDA_FUNCTION': 1, 'RDS': 3,
           'ALB': 2, 'NLB': 2, 'S3_MULTIPART': 2}


def fid(seed):
    return hashlib.sha256(seed.encode()).hexdigest()


def finding(kind, resource_id, level, rule, reason, region=REGION):
    return {'type': kind, 'resource_id': resource_id, 'region': region,
            'finding_id': fid(kind + resource_id + rule), 'account_id': PROFILE['account_id'],
            'level': level, 'rule_id': rule, 'reason': reason,
            'recommendation': 'Kiểm tra mục đích sử dụng và chủ sở hữu tài nguyên.',
            'evaluated_at': '2026-10-30T00:00:00Z', 'first_seen_at': '2026-10-28T00:00:00Z',
            'last_seen_at': '2026-10-30T00:00:00Z',
            'evidence': {'observed_hours': 30, 'thresholds': {'orphan_hours': 24}}}


FINDINGS_A = [
    # EBS: 4 cảnh báo trên 3 tài nguyên (vol-a có 2 finding khác rule)
    finding('EBS', 'vol-a', 'REVIEW', 'EBS_UNATTACHED', 'Unattached volume; validate data retention'),
    finding('EBS', 'vol-a', 'REVIEW', 'EBS_NO_SNAPSHOT', 'Unattached volume; validate data retention'),
    finding('EBS', 'vol-b', 'REVIEW', 'EBS_UNATTACHED', 'Unattached volume; validate data retention'),
    finding('EBS', 'vol-c', 'REVIEW', 'EBS_UNATTACHED', 'Unattached volume; validate data retention'),
    # EC2: 2 REVIEW + 1 OBSERVING
    finding('EC2', 'i-review-1', 'REVIEW', 'EC2_LOW_UTILIZATION', 'Low CPU and network; confirm intended workload'),
    finding('EC2', 'i-review-2', 'REVIEW', 'EC2_LOW_UTILIZATION', 'Low CPU and network; confirm intended workload'),
    finding('EC2', 'i-observe', 'OBSERVING', 'EC2_LOW_UTILIZATION', 'Low CPU and network; confirm intended workload'),
    # EIP REVIEW
    finding('EIP', 'eip-1', 'REVIEW', 'EIP_UNASSOCIATED', 'Unassociated public IPv4; may be intentionally reserved'),
    # Lambda INSUFFICIENT_DATA
    finding('LAMBDA_FUNCTION', 'fn-1', 'INSUFFICIENT_DATA', 'LAMBDA_UNUSED', 'Missing CloudWatch metrics; not classified as idle'),
    # Other services REVIEW (for the chart limit of six)
    finding('NAT_GATEWAY', 'nat-1', 'REVIEW', 'NAT_LOW_UTILIZATION', 'Low NAT traffic; confirm intended workload'),
    finding('RDS', 'db-1', 'REVIEW', 'RDS_LOW_UTILIZATION', 'Low database activity; confirm intended workload'),
    finding('ALB', 'alb-1', 'REVIEW', 'ALB_LOW_UTILIZATION', 'Low ALB request volume; confirm intended workload'),
    finding('NLB', 'nlb-1', 'REVIEW', 'NLB_LOW_UTILIZATION', 'Low NLB flow volume; confirm intended workload'),
    finding('S3_MULTIPART', 'bucket/key', 'REVIEW', 'S3_STALE_MULTIPART', 'Multipart upload older than 7 days; confirm whether it is still needed'),
]
FINDINGS_B = [finding('EBS', 'vol-z', 'REVIEW', 'EBS_UNATTACHED', 'Unattached volume; validate data retention')]
FOREIGN = [finding('EBS', 'vol-other-account', 'REVIEW', 'EBS_UNATTACHED', 'Unattached volume; validate data retention', region='eu-west-1')]


def row(scan_id, findings, counts, status='SUCCEEDED', trigger='manual', started=1793000000):
    return {'region': REGION, 'scan_id': scan_id, 'status': status, 'trigger': trigger,
            'started_at': started, 'completed_at': started + 60, 'counts': counts,
            'findings': list(findings), 'errors': [{'type': 'EC2', 'code': 'AccessDenied'}] if status == 'PARTIAL' else []}


FINDINGS_D = [finding('EBS', 'vol-d-%02d' % index, 'REVIEW', 'EBS_UNATTACHED',
                       'Unattached volume; validate data retention') for index in range(12)]

ROWS = {
    SCAN_A: [row(SCAN_A, FINDINGS_A, COUNT_A)],
    SCAN_B: [row(SCAN_B, FINDINGS_B, {'EBS': 2}, started=1793100000)],
    SCAN_C: [row(SCAN_C, [], {}, status='PARTIAL', trigger='scheduled', started=1793200000)],
    SCAN_D: [row(SCAN_D, FINDINGS_D, {'EBS': 12}, started=1793300000)],
}


def unique(items, level):
    return {(item['type'], item['resource_id'], item['region']) for item in items if item['level'] == level}


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(ROOT / 'web')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_address[1])
    state = {'profile': json.loads(json.dumps(PROFILE)), 'latest': SCAN_A, 'records': {}, 'requests': [], 'errors': []}
    checks = []
    page_errors = []

    def api(route):
        request = route.request
        path = request.url.split('/api')[-1].split('?')[0]
        body = request.post_data_json if request.post_data else None
        state['requests'].append((request.method, path, body))
        payload = {}
        if path == '/me':
            payload = state['profile']
        elif path == '/findings':
            rows = json.loads(json.dumps(ROWS[state['latest']]))
            if state['latest'] == SCAN_A:
                foreign = json.loads(json.dumps(ROWS[SCAN_A][0]))
                foreign.update(region='eu-west-1', findings=json.loads(json.dumps(FOREIGN)))
                rows.append(foreign)
            for r in rows:
                kept = []
                for item in r['findings']:
                    record = state['records'].get(item['finding_id'], {})
                    if record.get('kept') or record.get('ignore_until', 0) > time.time():
                        continue
                    if record.get('acknowledged'):
                        item['acknowledged'] = True
                    kept.append(item)
                r['findings'] = kept
            payload = {'results': rows}
        elif path == '/history':
            payload = {'results': [json.loads(json.dumps(ROWS[s]))[0] for s in (SCAN_D, SCAN_C, SCAN_B, SCAN_A)], 'next_token': None}
        elif path.startswith('/scans/'):
            scan = path.rsplit('/', 1)[-1]
            payload = {'results': json.loads(json.dumps(ROWS.get(scan, [])))}
        elif path == '/feedback' and request.method == 'GET':
            payload = {'results': list(state['records'].values()), 'next_token': None}
        elif path == '/feedback' and request.method == 'PUT':
            record = {'region': body['region'], 'finding_id': body['finding_id'],
                      'type': 'EBS', 'resource_id': 'vol-a', 'account_id': PROFILE['account_id'],
                      'rule_id': 'EBS_UNATTACHED', 'acknowledged': False, 'kept': False, 'ignore_until': 0}
            if 'kept' in body:
                record['kept'] = body['kept']
            if 'acknowledged' in body:
                record['acknowledged'] = body['acknowledged']
            if 'ignoreUntil' in body:
                record['ignore_until'] = int(time.time()) + 7 * 86400 if body['ignoreUntil'] else 0
            state['records'][body['finding_id']] = record
            payload = record
        route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))

    def expand(container, resource_id):
        target = page.locator(container + ' tbody tr').filter(has=page.locator('code').filter(has_text=resource_id))
        group = target.locator('xpath=ancestor::section[contains(@class,"finding-group")]')
        toggle = group.locator('.group-toggle')
        if toggle.count() and toggle.first.get_attribute('aria-expanded') == 'false':
            toggle.first.click()
        return target

    try:
        with sync_playwright() as playwright:
            launch = {'headless': True}
            if os.environ.get('CHROMIUM_EXECUTABLE'):
                launch['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
            browser = playwright.chromium.launch(**launch)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_init_script("sessionStorage.setItem('crg-token','demo-local-only')")
            page = context.new_page()
            page.on('pageerror', lambda error: page_errors.append(str(error)))
            page.route('**/config.json', lambda route: route.fulfill(json={'api': '/api', 'demo': True}))
            page.route('**/api/**', api)
            page.goto(base + '/#findings')
            expect(page.locator('#findings-list tbody tr')).to_have_count(len(FINDINGS_A))

            # 1/3/6: scan totals come from backend counts; cards count unique resources; scope labels the list.
            expect(page.locator('#findings-count-checked')).to_have_text(str(sum(COUNT_A.values())))
            expect(page.locator('#findings-count-review')).to_have_text(str(len(unique(FINDINGS_A, 'REVIEW'))))
            expect(page.locator('#findings-count-observing')).to_have_text(str(len(unique(FINDINGS_A, 'OBSERVING'))))
            expect(page.locator('#findings-count-insufficient')).to_have_text(str(len(unique(FINDINGS_A, 'INSUFFICIENT_DATA'))))
            expect(page.locator('#resource-overview-context')).to_contain_text('123456789012')
            expect(page.locator('#findings-scope')).to_contain_text(str(len(FINDINGS_A)) + ' cảnh báo')
            assert page.locator('#findings-list').inner_text().count('vol-other-account') == 0, 'foreign region leaked'
            checks.append('cards use backend total and unique resources; scope labels findings; foreign region ignored')

            # 2/4/5: chart and accordions derive from the same REVIEW findings.
            expect(page.locator('.service-chart-card h2')).to_have_text('Tài nguyên cần kiểm tra theo dịch vụ')
            expect(page.locator('.chart-subtitle')).to_contain_text('tài nguyên duy nhất')
            expect(page.locator('.chart-subtitle')).to_contain_text('Thanh dài nhất')
            bars = page.locator('.service-bar')
            expect(bars).to_have_count(6)
            first = bars.first
            expect(first.locator('.service-bar-label')).to_have_text('Amazon EBS')
            expect(first.locator('.service-bar-count')).to_have_text('3 tài nguyên cần kiểm tra')
            expect(bars.nth(1).locator('.service-bar-count')).to_have_text('2 tài nguyên cần kiểm tra')
            expect(page.locator('#service-chart-total')).to_contain_text('cảnh báo REVIEW')
            # service name and count share the first grid row; the bar track sits below
            box_label = first.locator('.service-bar-label').bounding_box()
            box_count = first.locator('.service-bar-count').bounding_box()
            box_track = first.locator('.service-bar-track').bounding_box()
            assert abs(box_label['y'] - box_count['y']) < 6, (box_label, box_count)
            assert box_track['y'] > box_count['y'] + box_count['height'] - 1, (box_track, box_count)
            expected_order = ['Amazon EBS', 'Amazon EC2', 'Amazon RDS', 'Amazon S3', 'Application Load Balancer',
                              'Elastic IP']
            labels = page.locator('.service-bar-label').all_text_contents()
            assert labels == expected_order, labels
            widths = [page.locator('.service-bar-fill').nth(i).evaluate('(el)=>parseFloat(el.style.width)') for i in range(3)]
            assert abs(widths[0] - 100) < .01 and abs(widths[1] - 200 / 3) < .5 and abs(widths[2] - 100 / 3) < .5, widths
            page.locator('#service-chart-more').click()
            expect(page.locator('.service-bar')).to_have_count(8)
            expect(page.locator('#service-chart-more')).to_have_text('Thu gọn bớt dịch vụ')
            page.locator('#service-chart-more').click()
            expect(page.locator('.service-bar')).to_have_count(6)
            checks.append('chart: 6 of 7 services, sorted, proportional widths, expandable')

            ebs_group = page.locator('#findings-list section.service-group[data-level="REVIEW"][data-service="EBS"]')
            expect(ebs_group).to_be_visible()
            expect(ebs_group.locator('.group-toggle')).to_have_attribute('aria-expanded', 'true')
            expect(ebs_group.locator('.group-service-counts')).to_contain_text('4 cảnh báo')
            expect(ebs_group.locator('.group-service-counts')).to_contain_text('3 tài nguyên')
            # 4: two findings on one resource keep distinct finding IDs and open separately.
            vol_a = expand('#findings-list', 'vol-a')
            expect(vol_a).to_have_count(2)
            ids = vol_a.evaluate_all('(rows)=>rows.map(r=>r.querySelector(".finding-open").dataset.findingId)')
            assert len(set(ids)) == 2, ids
            for finding_id in ids:
                vol_a.locator('.finding-open[data-finding-id="' + finding_id + '"]').first.click()
                expect(page.locator('#finding-dialog')).to_be_visible()
                expect(page.locator('#finding-detail-content [data-field="finding_id"] dd')).to_have_text(finding_id)
                page.keyboard.press('Escape')
                expect(page.locator('#finding-dialog')).not_to_be_visible()
            checks.append('accordion groups by service with alerts/resources counts; multi-finding resource keeps every finding')

            # 7: OBSERVING and INSUFFICIENT_DATA remain available and distinguishable.
            expect(page.locator('.status-heading.status-observing')).to_contain_text('Đang quan sát')
            expect(page.locator('.status-heading.status-insufficient')).to_contain_text('Thiếu dữ liệu')
            expect(page.locator('#findings-list section[data-level="OBSERVING"]')).to_have_count(1)
            expect(page.locator('#findings-list section[data-level="INSUFFICIENT_DATA"]')).to_have_count(1)
            checks.append('OBSERVING and INSUFFICIENT_DATA sections present')

            # 13: keyboard accordion operation.
            toggle = page.locator('#findings-list section[data-level="OBSERVING"] .group-toggle')
            expect(toggle).to_have_attribute('aria-expanded', 'false')
            toggle.focus()
            page.keyboard.press('Enter')
            expect(toggle).to_have_attribute('aria-expanded', 'true')
            expect(page.locator('#findings-list section[data-level="OBSERVING"] .finding-group-body')).to_be_visible()
            page.keyboard.press('Enter')
            expect(toggle).to_have_attribute('aria-expanded', 'false')
            checks.append('accordion toggles with keyboard and exposes aria-expanded')

            # 6: filters update the list and the chart without rewriting scan totals.
            page.locator('#filter-region').select_option('ap-southeast-2')
            expect(page.locator('#findings-list')).to_contain_text('Không khớp bộ lọc')
            expect(page.locator('#findings-count-checked')).to_have_text(str(sum(COUNT_A.values())))
            expect(page.locator('#findings-count-review')).to_have_text(str(len(unique(FINDINGS_A, 'REVIEW'))))
            expect(page.locator('.service-bar')).to_have_count(0)
            expect(page.locator('#findings-scope')).to_contain_text('đang áp dụng bộ lọc')
            page.locator('#filter-region').select_option(REGION)
            expect(page.locator('#findings-list tbody tr')).to_have_count(len(FINDINGS_A))
            page.locator('#filter-level').select_option('INSUFFICIENT_DATA')
            expect(page.locator('#findings-list tbody tr')).to_have_count(1)
            page.locator('#filter-level').select_option('')
            checks.append('filters narrow list/chart but keep scan totals labelled')

            # Clicking a chart service expands and focuses that accordion group.
            page.locator('.service-bar[data-service="EC2"]').click()
            expect(page.locator('#findings-list section[data-service="EC2"][data-level="REVIEW"] .group-toggle')).to_have_attribute('aria-expanded', 'true')
            expect(page.locator('#filter-service')).to_have_value('EC2')
            page.locator('#reset-filters').click()
            checks.append('chart bar applies the matching service filter and opens its accordion')

            # 8: keep still works and removes the finding; feedback manager shows it.
            target = expand('#findings-list', 'vol-b')
            target.locator('.actions-summary').click()
            target.locator('.feedback-keep').click()
            expect(page.locator('#findings-list')).not_to_contain_text('vol-b')
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(1)
            puts = [body for method, path, body in state['requests'] if method == 'PUT' and path == '/feedback']
            assert puts[-1] == {'region': REGION, 'finding_id': fid('EBSvol-bEBS_UNATTACHED'), 'kept': True}, puts[-1]
            checks.append('keep hides the finding and is stored through the existing API')

            # 9: partial scan cannot claim a safe account and shows missing totals.
            state['latest'] = SCAN_C
            page.evaluate('selectedScanId=null; refresh()')
            expect(page.locator('#scan-errors-card')).to_be_visible()
            expect(page.locator('#findings-count-checked')).to_have_text('—')
            expect(page.locator('#findings-count-review')).to_have_text('—')
            expect(page.locator('.chart-note')).to_contain_text('chưa đầy đủ')
            expect(page.locator('.chart-note')).to_have_class(re.compile('chart-note-warning'))
            expect(page.locator('#findings-list')).not_to_contain_text('an toàn')
            checks.append('PARTIAL scan shows errors, unknown totals and no safety claim')

            # 1/14: switching scans replaces overview, chart and list; switching back restores scan A only.
            state['latest'] = SCAN_B
            page.locator('#scan-select').select_option(SCAN_B)
            expect(page.locator('#findings-count-checked')).to_have_text('2')
            expect(page.locator('#findings-count-review')).to_have_text('1')
            expect(page.locator('#findings-list')).to_contain_text('vol-z')
            expect(page.locator('#findings-list')).not_to_contain_text('vol-a')
            expect(page.locator('.service-bar')).to_have_count(1)
            page.locator('#scan-select').select_option(SCAN_A)
            expect(page.locator('#findings-count-checked')).to_have_text(str(sum(COUNT_A.values())))
            # Scan A is now a saved snapshot (a newer scan exists), so it shows its stored findings.
            expect(page.locator('#findings-list tbody tr')).to_have_count(len(FINDINGS_A))
            expect(page.locator('#findings-list')).not_to_contain_text('vol-z')
            checks.append('scan switching updates cards, chart and list with no cross-scan data')

            # 5b: long service groups page in tens with a keyboard-safe "Xem thêm".
            state['latest'] = SCAN_D
            page.locator('#scan-select').select_option(SCAN_D)
            expect(page.locator('#findings-count-review')).to_have_text('12')
            expect(page.locator('#findings-list tbody tr')).to_have_count(10)
            more = page.locator('#findings-list .group-more')
            expect(more).to_have_text('Xem thêm 2 cảnh báo')
            more.click()
            expect(page.locator('#findings-list tbody tr')).to_have_count(12)
            expect(page.locator('#findings-list .group-more')).to_have_count(0)
            assert page.evaluate("document.activeElement.classList.contains('group-toggle')"), 'focus lost after group expansion'
            checks.append('long service group shows 10 findings and loads the rest, keeping focus')

            # 12: narrow viewport never overflows.
            for width in [390, 320]:
                page.set_viewport_size({'width': width, 'height': 900})
                expect(page.locator('.stat-cards')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                page.screenshot(path=str(OUT / f'resource-overview-{width}.png'), full_page=True)
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.screenshot(path=str(OUT / 'resource-overview-1440.png'), full_page=True)
            checks.append('no horizontal overflow at 390/320px')

            # 11: no runtime errors during the whole flow.
            assert not page_errors, page_errors
            checks.append('no JavaScript runtime errors')

            (OUT / 'acceptance-results.json').write_text(json.dumps(
                {'environment': 'LOCAL FIXTURES — NOT AWS', 'checks': checks, 'page_errors': page_errors},
                ensure_ascii=False, indent=2), encoding='utf-8')
            browser.close()
            print('Resource overview PASS:\n' + '\n'.join(checks))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
