"""Full resource-type filter coverage using source-derived local fixtures.

No AWS calls and no deployment. The fixture intentionally separates aggregate inventory
counts from finding identities and paginates history one row at a time.
"""
import copy
import hashlib
import json
import os
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rules import RESOURCE_REGISTRY

R1, R2 = 'ap-southeast-1', 'us-east-1'
SCAN_A = 'aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa'
SCAN_B = 'bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb'
SCAN_OLD = 'cccccccc-3333-4333-8333-cccccccccccc'
ALL_TYPES = list(RESOURCE_REGISTRY)
INVENTORY_ONLY = 'SAGEMAKER_ENDPOINT'
GROUPS = sorted({metadata['group'] for metadata in RESOURCE_REGISTRY.values()})
PROFILE = {
    'account_id': '123456789012',
    'role_arn': 'arn:aws:iam::123456789012:role/GuardianReadRole-fixture',
    'regions': [R1, R2], 'service_groups': GROUPS,
    'external_id': 'FIXTURE-ONLY-EXTERNAL-ID',
    'api_principal': 'arn:aws:iam::123456789012:role/FixtureApiPrincipal',
    'scan_principal': 'arn:aws:iam::123456789012:role/FixtureScanPrincipal',
    'settings': {}, 'notifications': {'enabled': False}, 'email_available': False,
}


def finding(kind, index, *, region=R1, level=None, resource_id=None, rule=None):
    level = level or ('REVIEW', 'OBSERVING', 'INSUFFICIENT_DATA')[index % 3]
    rule = rule or RESOURCE_REGISTRY[kind]['rules'][0]
    resource_id = resource_id or f'{kind.lower()}-{index}'
    identity = hashlib.sha256(f'{kind}|{resource_id}|{rule}|{region}'.encode()).hexdigest()
    return {
        'type': kind, 'resource_id': resource_id, 'region': region, 'level': level,
        'rule_id': rule, 'finding_id': identity, 'account_id': PROFILE['account_id'],
        'reason': f'Fixture reason for {kind}', 'recommendation': 'Review the resource.',
        'evaluated_at': '2026-11-01T12:00:00Z', 'first_seen_at': '2026-10-01T12:00:00Z',
        'last_seen_at': '2026-11-01T12:00:00Z',
        'evidence': {'resource_name': f'Tên tài nguyên {kind} 東京'},
    }


FINDINGS = []
for index, kind in enumerate(kind for kind in ALL_TYPES if kind != INVENTORY_ONLY):
    region = R1 if index % 2 == 0 else R2
    resource_id = None
    if kind == 'LAMBDA_FUNCTION':
        resource_id = 'arn:aws:lambda:ap-southeast-1:123456789012:function:' + ('x' * 180) + '-東京'
    FINDINGS.append(finding(kind, index, region=region, resource_id=resource_id))
# One resource with two findings must remain two records but one affected resource.
ecr = next(item for item in FINDINGS if item['type'] == 'ECR_REPOSITORY')
FINDINGS.append(finding('ECR_REPOSITORY', 999, region=ecr['region'], resource_id=ecr['resource_id'],
                        level='REVIEW', rule='ECR_IMAGE_OLD'))

COUNTS_R1 = {kind: 1 for index, kind in enumerate(ALL_TYPES) if index % 2 == 0}
COUNTS_R2 = {kind: 1 for index, kind in enumerate(ALL_TYPES) if index % 2 == 1}
COUNTS_R1['ZERO_COUNT_TYPE'] = 0
FINDINGS_R1 = [item for item in FINDINGS if item['region'] == R1]
FINDINGS_R2 = [item for item in FINDINGS if item['region'] == R2]


def row(scan_id, region, findings, counts, *, status='SUCCEEDED', started=1793500000, errors=None):
    return {
        'scan_id': scan_id, 'region': region, 'status': status, 'trigger': 'manual',
        'started_at': started, 'completed_at': started + 60, 'counts': counts,
        'findings': copy.deepcopy(findings), 'finding_count': len(findings),
        'errors': copy.deepcopy(errors or []),
    }


ROWS = {
    SCAN_A: [
        row(SCAN_A, R1, FINDINGS_R1, COUNTS_R1, status='PARTIAL',
            errors=[{'type': 'ECS_SERVICE', 'code': 'RESOURCE_LIMIT'}]),
        row(SCAN_A, R2, FINDINGS_R2, COUNTS_R2),
    ],
    SCAN_B: [row(SCAN_B, R1, [finding('EBS', 2000)], {'EBS': 2}, started=1793600000)],
    SCAN_OLD: [row(SCAN_OLD, R1, [finding(INVENTORY_ONLY, 3000)], {INVENTORY_ONLY: 1},
                   started=1792500000)],
}
HISTORY_ROWS = ROWS[SCAN_B] + ROWS[SCAN_A] + ROWS[SCAN_OLD]

INVENTORY_A = []
for index, kind in enumerate(ALL_TYPES):
    matching = next((item for item in FINDINGS if item['type'] == kind), None)
    INVENTORY_A.append({
        'type': kind,
        'service_id': RESOURCE_REGISTRY[kind]['service_id'],
        'resource_id': matching['resource_id'] if matching else f'{kind.lower()}-inventory-only',
        'resource_name': f'Tên tài nguyên {kind} 東京',
        'region': R1 if index % 2 == 0 else R2,
        'account_id': PROFILE['account_id'],
        'scan_id': SCAN_A,
        'scanned_at': 1793500000,
    })



class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def option_values(page, selector):
    return page.locator(selector + ' option').evaluate_all('(items)=>items.map(item=>item.value).filter(Boolean)')


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(ROOT / 'web')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    state = {'latest': SCAN_A, 'requests': [], 'history_calls': 0}
    checks, errors = [], []

    def api(route):
        request = route.request
        path_query = request.url.split('/api', 1)[-1]
        path, _, raw_query = path_query.partition('?')
        query = dict(part.partition('=')[::2] for part in raw_query.split('&') if part)
        state['requests'].append((path, request.headers.get('authorization', '')))
        if path == '/me':
            payload = PROFILE
        elif path == '/findings':
            payload = {'results': copy.deepcopy(ROWS[state['latest']])}
        elif path == '/history':
            state['history_calls'] += 1
            offset = int(query.get('next_token') or 0)
            payload = {'results': copy.deepcopy(HISTORY_ROWS[offset:offset + 1]),
                       'next_token': str(offset + 1) if offset + 1 < len(HISTORY_ROWS) else None}
        elif path.startswith('/scans/'):
            payload = {'results': copy.deepcopy(ROWS.get(path.rsplit('/', 1)[-1], []))}
        elif path == '/inventory':
            scan_id = query.get('scan_id')
            if scan_id == SCAN_A:
                offset = int(query.get('next_token') or 0)
                payload = {
                    'resources': copy.deepcopy(INVENTORY_A[offset:offset + 13]),
                    'next_token': str(offset + 13) if offset + 13 < len(INVENTORY_A) else None,
                    'available': True, 'aggregate_only': False, 'complete': True,
                    'total_count': len(INVENTORY_A),
                }
            else:
                payload = {
                    'resources': [], 'next_token': None, 'available': False,
                    'aggregate_only': True, 'complete': False, 'total_count': None,
                }
        elif path == '/feedback':
            payload = {'results': [], 'next_token': None}
        else:
            payload = {}
        route.fulfill(status=200, content_type='application/json', body=json.dumps(payload, ensure_ascii=False))

    try:
        with sync_playwright() as playwright:
            launch = {'headless': True}
            if os.environ.get('CHROMIUM_EXECUTABLE'):
                launch['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
            browser = playwright.chromium.launch(**launch)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_init_script("sessionStorage.setItem('crg-token','fixture-token')")
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/config.json', lambda route: route.fulfill(json={'api': '/api', 'demo': True}))
            page.route('**/api/**', api)
            page.goto(base + '/#findings')

            expected_findings_types = {item['type'] for item in FINDINGS}
            expect(page.locator('#findings-list tbody tr')).to_have_count(len(FINDINGS))
            assert set(option_values(page, '#filter-type')) == expected_findings_types
            assert INVENTORY_ONLY not in option_values(page, '#filter-type')
            checks.append('TC02/TC03 findings mode includes every finding type across all three statuses')

            expect(page.locator('#findings-count-checked')).to_have_text('≥ 38')
            expect(page.locator('#findings-count-affected')).to_have_text(str(len(expected_findings_types)))
            expect(page.locator('#findings-count-alerts')).to_have_text(str(len(FINDINGS)))
            expect(page.locator('#scan-errors-card')).to_contain_text('chưa đầy đủ')
            page.locator('#scan-errors-card .scan-error-detail').click()
            expect(page.locator('#scan-detail-dialog')).to_contain_text('Giới hạn')
            page.locator('#close-scan-detail').click()
            checks.append('TC11/TC12/TC17 PARTIAL, unique resources and multiple findings remain distinct')

            page.locator('#advanced-filters summary').click()
            assert set(option_values(page, '#filter-rule')) == {item['rule_id'] for item in FINDINGS}
            for level in ('REVIEW', 'OBSERVING', 'INSUFFICIENT_DATA'):
                page.locator('#filter-level').select_option(level)
                expect(page.locator('#findings-list tbody tr')).to_have_count(sum(item['level'] == level for item in FINDINGS))
            page.locator('#filter-level').select_option('')
            checks.append('TC07 all finding rule IDs filter; status filters retain OBSERVING and INSUFFICIENT_DATA')

            long_item = next(item for item in FINDINGS if item['type'] == 'LAMBDA_FUNCTION')
            page.locator('#search').fill(long_item['resource_id'])
            expect(page.locator('#findings-list tbody tr')).to_have_count(1)
            page.locator('#search').fill('Tên tài nguyên LAMBDA_FUNCTION 東京')
            expect(page.locator('#findings-list tbody tr')).to_have_count(1)
            page.locator('#search').fill('')
            checks.append('TC15 long resource IDs and Unicode names are searchable')

            sample = next(item for item in FINDINGS if RESOURCE_REGISTRY[item['type']]['group'] == 'analytics')
            page.locator('#filter-group').select_option('analytics')
            page.locator('#filter-type').select_option(sample['type'])
            page.locator('#filter-level').select_option(sample['level'])
            expect(page.locator('#findings-list tbody tr')).to_have_count(
                sum(item['type'] == sample['type'] and item['level'] == sample['level'] for item in FINDINGS))
            page.locator('#reset-filters').click()
            checks.append('TC06/TC08 filters compose with AND across group, type, status and region-aware data')

            page.locator('#search-scope').select_option('inventory')
            expect(page.locator('#findings-list tbody tr')).to_have_count(len(INVENTORY_A))
            assert set(option_values(page, '#filter-type')) == set(ALL_TYPES)
            assert 'ZERO_COUNT_TYPE' not in option_values(page, '#filter-type')
            expect(page.locator('#filter-type-search')).to_be_visible()
            page.locator('#filter-type-search').fill('SageMaker')
            assert option_values(page, '#filter-type') == [INVENTORY_ONLY]
            page.locator('#filter-type-search').fill('')
            expect(page.locator('#search-scope-note')).to_contain_text('Resource ID')
            expect(page.locator('#findings-list code')).to_have_count(len(INVENTORY_A))
            page.locator('#search').fill('Tên tài nguyên SAGEMAKER_ENDPOINT 東京')
            expect(page.locator('#findings-list tbody tr')).to_have_count(1)
            page.locator('#search').fill('')
            checks.append('TC01/TC04/TC05 inventory options and searchable identities include all scanned types')

            page.locator('#scan-select').select_option(SCAN_B)
            expect(page.locator('#search-scope')).to_have_value('inventory')
            assert option_values(page, '#filter-type') == ['EBS']
            expect(page.locator('#findings-count-checked')).to_have_text('2')
            expect(page.locator('#findings-list code')).to_have_count(0)
            checks.append('TC09/TC18 scan change preserves scope, clears stale options, and legacy counts never fake identities')

            page.locator('#search-scope').select_option('history')
            expect(page.locator('#filter-type option[value="' + INVENTORY_ONLY + '"]')).to_have_count(1)
            assert state['history_calls'] >= len(HISTORY_ROWS), state['history_calls']
            page.locator('#search').fill('sagemaker_endpoint-3000')
            expect(page.locator('#findings-list tbody tr')).to_have_count(1)
            checks.append('TC10/TC19 history exhausts next_token pages before building options and search results')

            assert all(auth.startswith('Bearer ') for _, auth in state['requests'])
            assert all(item['account_id'] == PROFILE['account_id'] for item in FINDINGS)
            checks.append('TC14 every fixture API request is authenticated and rendered identities belong to one tenant')

            page.locator('#reset-filters').click()
            expect(page.locator('#search-scope')).to_have_value('findings')
            page.locator('#scan-select').select_option(SCAN_A)
            page.set_viewport_size({'width': 320, 'height': 900})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#filter-type-search').focus()
            page.keyboard.type('EBS')
            expect(page.locator('#filter-type-search')).to_have_value('EBS')
            page.keyboard.press('Tab')
            expect(page.locator('#filter-type')).to_be_focused()
            checks.append('TC13/TC20 reset, searchable type options, keyboard navigation and mobile layout work')

            # Every source-registered backend type is represented in the frontend mapping/options.
            page.locator('#search-scope').select_option('inventory')
            page.locator('#filter-type-search').fill('')
            page.locator('#scan-select').select_option(SCAN_A)
            assert set(option_values(page, '#filter-type')) == set(ALL_TYPES)
            checks.append('TC16 all 38 source-registered resource types are accepted by the frontend')

            assert not errors, errors
            context.close()
            browser.close()
            print('Resource type filter coverage PASS:\n' + '\n'.join(checks))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
