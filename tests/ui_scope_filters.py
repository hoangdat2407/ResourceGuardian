"""Browser acceptance for scan scope, settings and filters; local fixtures, not AWS."""
import copy
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import threading
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rules import DEFAULTS, LIMITS, config

OUT = Path(os.environ.get('UI_QA_DIR', ROOT / '.preflight/ui-scope-filters'))
GROUPS = ['compute', 'storage', 'database', 'network']
REGIONS = ['ap-southeast-1', 'ap-southeast-2', 'ap-northeast-1']
ARN = 'arn:aws:iam::123456789012:role/GuardianReadRole-fixture'
KINDS = ['EC2', 'EBS', 'EIP', 'SNAPSHOT', 'RDS', 'NAT_GATEWAY', 'S3_MULTIPART', 'ALB', 'NLB']
TYPE_GROUPS = {'EC2': 'compute', 'EBS': 'storage', 'SNAPSHOT': 'storage', 'S3_MULTIPART': 'storage',
               'RDS': 'database', 'EIP': 'network', 'NAT_GATEWAY': 'network', 'ALB': 'network', 'NLB': 'network'}
FILTERS = ['search', 'filter-type', 'filter-group', 'filter-region', 'filter-level', 'filter-acknowledged']
PROFILE = {
    'external_id': 'FIXTURE-ONLY-EXTERNAL-ID', 'role_arn': ARN, 'account_id': '123456789012',
    'api_principal': 'arn:aws:iam::123456789012:role/FixtureApiPrincipal',
    'scan_principal': 'arn:aws:iam::123456789012:role/FixtureScanPrincipal',
    'settings': dict(DEFAULTS), 'regions': list(REGIONS), 'service_groups': list(GROUPS),
    'notifications': {'enabled': False}, 'email_available': False,
}


def fixture_rows():
    rows = [{'region': region, 'status': 'PARTIAL' if index == 0 else 'SUCCEEDED',
             'completed_at': 1793000000, 'counts': {}, 'findings': [],
             'errors': [{'type': 'EC2', 'code': 'AccessDenied'}] if index == 0 else []}
            for index, region in enumerate(REGIONS)]
    for index, kind in enumerate(KINDS):
        row = rows[index // 3]
        finding = {
            'finding_id': format(index + 1, '064x'), 'type': kind, 'resource_id': 'fixture-' + kind.lower(),
            'region': row['region'], 'account_id': PROFILE['account_id'],
            'level': 'OBSERVING' if kind == 'EBS' else 'INSUFFICIENT_DATA' if kind in ['RDS', 'NLB'] else 'REVIEW',
            'acknowledged': kind in ['EC2', 'SNAPSHOT', 'ALB'], 'reason': kind + ' fixture evidence',
            'rule_id': kind + '_FIXTURE', 'recommendation': 'Review the observed resource.',
            'evaluated_at': '2026-10-26T09:00:00+00:00',
            'first_seen_at': '2026-10-25T09:00:00+00:00', 'last_seen_at': '2026-10-26T09:00:00+00:00',
            'evidence': {'cpu_p95': 0, 'coverage': 1} if kind == 'EC2' else
                        {'missing_metrics': ['cpu'], 'coverage': 0} if kind == 'RDS' else {},
        }
        row['findings'].append(finding)
        row['counts'][kind] = 1
    return rows


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'web')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_address[1])
    state = {'profile': copy.deepcopy(PROFILE), 'rows': fixture_rows(), 'requests': [],
             'findings_error': False, 'fixture_errors': [], 'hold_path': None, 'pending_routes': {}}
    checks, errors = [], []

    def route_api(route):
        request = route.request
        path = urlsplit(request.url).path.removeprefix('/api')
        body = request.post_data_json if request.post_data else None
        state['requests'].append({'method': request.method, 'path': path, 'body': copy.deepcopy(body)})
        if request.method == 'GET' and state['hold_path'] == path:
            state['pending_routes'][path] = route
            state['hold_path'] = None
            return
        status, result = 200, {}
        try:
            if path == '/me':
                result = state['profile']
            elif path == '/findings':
                status, result = (503, {'error': 'Service unavailable'}) if state['findings_error'] else (200, {'results': state['rows']})
            elif path == '/feedback' and request.method == 'GET':
                result = {'results': [], 'next_token': None}
            elif path == '/history':
                result = {'results': state['rows']}
            elif path == '/connection' and request.method == 'PUT':
                assert set(body) == {'role_arn', 'regions', 'service_groups'}, body
                assert body['role_arn'] == ARN
                assert 1 <= len(body['regions']) <= 3 and set(body['regions']) <= set(REGIONS)
                assert body['service_groups'] and set(body['service_groups']) <= set(GROUPS)
                assert len(body['service_groups']) == len(set(body['service_groups']))
                state['profile'].update(copy.deepcopy(body))
                state['rows'] = []
                result = {'connected': True, 'account_id': PROFILE['account_id']}
            elif path == '/settings' and request.method == 'PUT':
                assert set(body) == set(DEFAULTS), body
                state['profile']['settings'] = config(body, state['profile']['settings'])
                result = state['profile']['settings']
            else:
                raise AssertionError('Unexpected fixture request: ' + request.method + ' ' + path)
        except Exception as error:
            state['fixture_errors'].append(str(error))
            status, result = 500, {'error': 'Fixture rejected request: ' + str(error)}
        route.fulfill(status=status, content_type='application/json', body=json.dumps(result))

    def requests_to(path):
        return [item for item in state['requests'] if item['path'] == path and item['method'] == 'PUT']

    try:
        with sync_playwright() as playwright:
            launch = {'headless': True}
            if os.environ.get('CHROMIUM_EXECUTABLE'):
                launch['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
            browser = playwright.chromium.launch(**launch)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            context.add_init_script("sessionStorage.setItem('crg-token','demo-local-only')")
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/config.json', lambda route: route.fulfill(json={'api': '/api', 'demo': True}))
            page.route('**/api/**', route_api)
            page.goto(base + '/#findings')
            expect(page.locator('#app')).to_be_visible()
            expect(page.locator('#findings-list tbody tr')).to_have_count(9)

            def navigate(section):
                page.locator('[data-page="' + section + '"]').click()
                expect(page.locator('#page-' + section)).to_be_visible()

            def reset_filters():
                page.locator('#search').fill('')
                for ident in FILTERS[1:]:
                    page.locator('#' + ident).select_option('')

            def visible_ids():
                return set(page.locator('#findings-list tbody tr code').all_text_contents())

            def assert_filtered(expected):
                expect(page.locator('#findings-list tbody tr')).to_have_count(len(expected))
                assert visible_ids() == {item['resource_id'] for item in expected}, (visible_ids(), expected)

            all_findings = [finding for row in fixture_rows() for finding in row['findings']]
            type_values = page.locator('#filter-type option').evaluate_all('(items)=>items.map(item=>item.value)')
            assert set(type_values) == {'', *KINDS}, type_values
            group_values = page.locator('#filter-group option').evaluate_all('(items)=>items.map(item=>item.value)')
            assert set(group_values) == {'', *GROUPS}, group_values
            region_values = page.locator('#filter-region option').evaluate_all('(items)=>items.map(item=>item.value)')
            assert set(region_values) == {'', *REGIONS}, region_values
            for kind in KINDS:
                page.locator('#filter-type').select_option(kind)
                assert_filtered([item for item in all_findings if item['type'] == kind])
            reset_filters()
            for group in GROUPS:
                page.locator('#filter-group').select_option(group)
                assert_filtered([item for item in all_findings if TYPE_GROUPS[item['type']] == group])
            reset_filters()
            for region in REGIONS:
                page.locator('#filter-region').select_option(region)
                assert_filtered([item for item in all_findings if item['region'] == region])
            reset_filters()
            for level in ['REVIEW', 'OBSERVING', 'INSUFFICIENT_DATA']:
                page.locator('#filter-level').select_option(level)
                assert_filtered([item for item in all_findings if item['level'] == level])
            reset_filters()
            for acknowledged in [True, False]:
                page.locator('#filter-acknowledged').select_option('acknowledged' if acknowledged else 'unacknowledged')
                assert_filtered([item for item in all_findings if item['acknowledged'] == acknowledged])
            reset_filters()
            page.locator('#filter-group').select_option('network')
            page.locator('#filter-region').select_option('ap-northeast-1')
            page.locator('#filter-level').select_option('REVIEW')
            page.locator('#filter-acknowledged').select_option('acknowledged')
            page.locator('#search').fill('FIXTURE-ALB')
            assert_filtered([item for item in all_findings if item['type'] == 'ALB'])
            page.locator('#search').fill('no matching resource')
            expect(page.locator('#findings-list')).to_contain_text('Không khớp bộ lọc')
            expect(page.locator('#findings-scope')).to_contain_text(re.compile(r'chưa.*đầy đủ', re.I))
            checks.append('Nine types; four groups; three regions; level/ack/search AND filters; partial empty-result warning')

            reset_filters()
            navigate('overview')
            state['findings_error'] = True
            page.locator('#refresh').click()
            expect(page.locator('#overview-state')).to_contain_text('Không tải được kết quả mới')
            navigate('findings')
            expect(page.locator('#findings-scope')).to_contain_text('chưa được cập nhật')
            state['findings_error'] = False
            state['rows'] = [{'region': REGIONS[0], 'status': 'FAILED', 'counts': {}, 'findings': [],
                              'error': 'Cannot access AWS; reconnect and check role permissions'}]
            navigate('overview')
            page.locator('#refresh').click()
            expect(page.locator('#overview-state')).to_contain_text('chưa quét thành công')
            expect(page.locator('#total')).to_have_text('—')
            navigate('findings')
            expect(page.locator('#findings-scope')).to_contain_text('không dùng kết quả')
            state['rows'] = [{'region': REGIONS[0], 'status': 'SUCCEEDED', 'counts': {'EC2': 0}, 'findings': []}]
            navigate('overview')
            page.locator('#refresh').click()
            expect(page.locator('#total')).to_have_text('0')
            expect(page.locator('#review')).to_have_text('0')
            state['rows'] = [{'region': REGIONS[0], 'status': 'PARTIAL', 'counts': {}, 'findings': [],
                              'errors': [{'type': 'RDS', 'code': 'AccessDenied'}]}]
            page.locator('#refresh').click()
            expect(page.locator('#total')).to_have_text('—')
            expect(page.locator('#scan-summary')).to_contain_text('RDS: AccessDenied')
            checks.append('Fetch failure and FAILED remain inconclusive; successful zero differs from missing counts/PARTIAL')

            state['rows'] = fixture_rows()
            page.locator('#refresh').click()
            navigate('findings')
            page.locator('#filter-region').select_option('ap-northeast-1')
            page.locator('#filter-type').select_option('RDS')
            navigate('connection')
            expect(page.locator('#service-group-options input[type="checkbox"]')).to_have_count(11)
            for checkbox in page.locator('#service-group-options input[type="checkbox"]').all():
                checkbox.uncheck()
            before = len(requests_to('/connection'))
            page.locator('#connect').click()
            expect(page.locator('#connection-feedback')).to_contain_text(re.compile('dịch vụ', re.I))
            assert len(requests_to('/connection')) == before, 'Empty service selection must not reach API'
            for group in ['storage', 'network']:
                page.locator('#service-group-options input[value="' + group + '"]').check()
            page.locator('#region-options input[value="ap-northeast-1"]').uncheck()
            with page.expect_response('**/api/connection') as saved:
                page.locator('#connect').click()
            assert saved.value.status == 200, state['fixture_errors']
            expect(page.locator('#connection-feedback')).to_contain_text('Tiếp tục bước 3')
            payload = requests_to('/connection')[-1]['body']
            assert payload == {'role_arn': ARN, 'regions': REGIONS[:2], 'service_groups': ['storage', 'network']}, payload
            assert page.locator('#service-group-options input:checked').evaluate_all('(items)=>items.map(item=>item.value)') == ['storage', 'network']
            navigate('findings')
            for ident in FILTERS:
                expect(page.locator('#' + ident)).to_have_value('')
            assert set(page.locator('#filter-region option').evaluate_all('(items)=>items.map(item=>item.value)')) == {'', *REGIONS[:2]}
            page.reload()
            navigate('connection')
            assert page.locator('#service-group-options input:checked').evaluate_all('(items)=>items.map(item=>item.value)') == ['storage', 'network']
            state['profile'].pop('service_groups')
            page.reload()
            expect(page.locator('#service-group-options input:checked')).to_have_count(4)
            checks.append('Zero groups blocked; exact scope payload; selected groups persist; reconnect resets filters; legacy profile defaults four groups')

            navigate('settings')
            expect(page.locator('#settings-fields input[type="number"]')).to_have_count(len(LIMITS))
            for group in page.locator('details.settings-group').all():
                if not group.evaluate('(el)=>el.open'):
                    group.locator('summary').click()
            window_label = page.locator('#window_hours').locator('../..').inner_text()
            assert 'EC2' not in window_label and 'metric' in window_label.lower(), window_label
            for key, (minimum, maximum, integer) in LIMITS.items():
                control = page.locator('#' + key)
                assert float(control.get_attribute('min')) == minimum, key
                assert float(control.get_attribute('max')) == maximum, key
                assert control.get_attribute('required') is not None, key
                assert control.get_attribute('step') == ('1' if integer else 'any'), key
                original = control.input_value()
                for bound in [minimum, maximum]:
                    control.fill(str(bound))
                    assert control.evaluate('(input)=>input.validity.valid'), (key, bound)
                control.fill(original)
                invalid_values = [minimum - (1 if integer else .01), maximum + 1]
                if integer:
                    invalid_values.append(minimum + .5)
                for invalid in invalid_values:
                    count = len(requests_to('/settings'))
                    control.fill(str(invalid))
                    page.locator('#save-settings').click()
                    assert not control.evaluate('(input)=>input.validity.valid'), (key, invalid)
                    assert len(requests_to('/settings')) == count, (key, invalid, 'Invalid settings reached API')
                control.fill(original)
            values = dict(DEFAULTS, cpu_percent=5.5, network_mib_hour=.125, window_hours=168,
                          orphan_hours=48, snapshot_days=45, interval_hours=12, rds_cpu_percent=4.25,
                          rds_connections=2, nat_mib_hour=.23456, alb_requests_hour=100, nlb_new_flows_hour=5)
            for key, value in values.items():
                page.locator('#' + key).fill(str(value))
                assert page.locator('#' + key).evaluate('(input)=>input.validity.valid'), key
            with page.expect_response('**/api/settings') as saved:
                page.locator('#save-settings').click()
            assert saved.value.status == 200, state['fixture_errors']
            expect(page.locator('#status')).to_contain_text('Đã lưu ngưỡng')
            assert requests_to('/settings')[-1]['body'] == values
            page.reload()
            navigate('settings')
            for key, value in values.items():
                assert float(page.locator('#' + key).input_value()) == value, key
            checks.append('All eleven backend setting limits; exact boundaries; integers; arbitrary valid decimals; invalid values never PUT; save/reload')

            for path, response_status in [('/findings', 200), ('/findings', 503), ('/history', 200), ('/history', 503)]:
                state['profile'].update(service_groups=list(GROUPS), regions=list(REGIONS))
                state['rows'] = fixture_rows()
                page.reload()
                navigate('overview')
                expect(page.locator('#findings-list tbody tr')).to_have_count(9)
                if path == '/history':
                    navigate('history')
                    expect(page.locator('#history-list tbody tr')).to_have_count(3)
                    page.locator('#history-list .history-open').first.click()
                    expect(page.locator('#history-detail table')).to_be_visible()
                state['hold_path'] = path
                operation = 'refresh' if path == '/findings' else 'loadHistory'
                with page.expect_request('**/api' + path + ('?*' if path == '/history' else '')):
                    page.evaluate("window.__oldScopeDone=false; void " + operation +
                                  "().catch(()=>{}).finally(()=>window.__oldScopeDone=true)")
                navigate('connection')
                for group in GROUPS:
                    checkbox = page.locator('#service-group-options input[value="' + group + '"]')
                    checkbox.set_checked(group == 'compute')
                for region in REGIONS:
                    page.locator('#region-options input[value="' + region + '"]').set_checked(region == REGIONS[0])
                with page.expect_response('**/api/connection') as reconnected:
                    page.locator('#connect').click()
                assert reconnected.value.status == 200
                expect(page.locator('#connection-feedback')).to_contain_text('Tiếp tục bước 3')
                expect(page.locator('#overview-state')).to_contain_text('lần quét đầu tiên')
                expect(page.locator('#history-list')).to_be_empty()
                expect(page.locator('#history-detail')).to_be_empty()
                old_row = {'region': REGIONS[1], 'status': 'RUNNING' if path == '/findings' else 'PARTIAL',
                           'completed_at': 1793000000, 'counts': {}, 'findings': [],
                           'errors': [{'type': 'STALE_SCOPE', 'code': 'MUST_NOT_RENDER'}]}
                old_reply = {'results': [old_row]} if response_status == 200 else {'error': 'Service unavailable'}
                page.evaluate("""window.__oldScopePolls=[];
                    window.__scopeNativeSetTimeout=window.setTimeout;
                    window.setTimeout=(fn,delay,...args)=>{
                      if(delay===5000)window.__oldScopePolls.push(delay);
                      return window.__scopeNativeSetTimeout(fn,delay,...args);
                    };""")
                assert path in state['pending_routes'], (path, response_status, 'Old request was not held')
                state['pending_routes'].pop(path).fulfill(status=response_status, content_type='application/json',
                                                         body=json.dumps(old_reply))
                page.wait_for_function('window.__oldScopeDone === true')
                expect(page.locator('#overview-state')).to_contain_text('lần quét đầu tiên')
                expect(page.locator('#scan-summary')).not_to_contain_text(REGIONS[1])
                expect(page.locator('#findings-list tbody tr')).to_have_count(0)
                expect(page.locator('#history-list')).to_be_empty()
                expect(page.locator('#history-detail')).to_be_empty()
                expect(page.locator('#status')).not_to_contain_text('Service unavailable')
                assert set(page.locator('#filter-region option').evaluate_all('(items)=>items.map(item=>item.value)')) == {'', REGIONS[0]}
                assert page.evaluate('window.__oldScopePolls') == [], (path, response_status, 'Old scope restarted polling')
            checks.append('Held old findings/history success and 503 cannot overwrite reconnect scope, restore old history, or restart polling')

            state['profile'].update(service_groups=list(GROUPS), regions=list(REGIONS))
            state['rows'] = fixture_rows()
            page.reload()
            for width in [320, 390, 768, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                for section in ['findings', 'connection', 'settings']:
                    navigate(section)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, section)
                    if section == 'findings':
                        for ident in FILTERS:
                            expect(page.locator('#' + ident)).to_be_visible()
                    page.evaluate('window.scrollTo(0,0)')
                    page.screenshot(path=str(OUT / (section + '-' + str(width) + '.png')), full_page=True)
            for section, selector, expected_keys in [
                    ('findings', '#search', set(FILTERS)),
                    ('connection', '#service-group-options input', set(GROUPS)),
                    ('settings', '#cpu_percent', set(LIMITS))]:
                navigate(section)
                if section == 'settings':
                    for group in page.locator('details.settings-group').all():
                        if not group.evaluate('(el)=>el.open'):
                            group.locator('summary').click()
                    page.wait_for_timeout(100)
                page.locator(selector).first.focus()
                focused = set()
                for _ in range(len(expected_keys) * 4):
                    focused.add(page.evaluate('document.activeElement.id || document.activeElement.value'))
                    if expected_keys <= focused:
                        break
                    page.keyboard.press('Tab')
                assert expected_keys <= focused, (section, expected_keys - focused)
            checks.append('Six filters/scope/settings at 320/390/768/1440; twelve screenshots; keyboard access and no horizontal overflow')
            assert not state['fixture_errors'], state['fixture_errors']
            assert not errors, errors
            browser.close()
        report = {'environment': 'LOCAL HTTP/API FIXTURES - NOT AWS', 'checks': checks,
                  'page_errors': errors, 'fixture_errors': state['fixture_errors'], 'request_count': len(state['requests'])}
        (OUT / 'acceptance-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Scope/filter acceptance PASS:\n' + '\n'.join(checks))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
