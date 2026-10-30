"""Finding evidence browser acceptance using local API fixtures, never AWS.

Run with CHROMIUM_EXECUTABLE and UI_QA_DIR as for ui_scope_filters.py.
"""
import copy
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rules import (config, evaluate_ebs, evaluate_ec2, evaluate_eip,
                   evaluate_load_balancer, evaluate_nat_gateway, evaluate_rds,
                   evaluate_s3_multipart, evaluate_snapshot, finding_id)

OUT = Path(os.environ.get('UI_QA_DIR', ROOT / '.preflight/ui-finding-details'))
REGION = 'ap-southeast-1'
ARN = 'arn:aws:iam::999999999999:role/GuardianReadRole-fixture'
PROFILE = {
    'account_id': '999999999999', 'role_arn': ARN, 'regions': [REGION],
    'external_id': 'FIXTURE-ONLY-EXTERNAL-ID',
    'api_principal': 'arn:aws:iam::999999999999:role/FixtureApiPrincipal',
    'scan_principal': 'arn:aws:iam::999999999999:role/FixtureScanPrincipal',
    'service_groups': ['compute', 'storage', 'database', 'network'],
    'settings': config({'cpu_percent': 50, 'window_hours': 168,
                        'orphan_hours': 72, 'snapshot_days': 365}),
    'notifications': {'enabled': False}, 'email_available': False,
}
COMMON_KEYS = ['type', 'resource_id', 'account_id', 'region', 'finding_id',
               'rule_id', 'level', 'reason', 'recommendation', 'evaluated_at',
               'first_seen_at', 'last_seen_at']
METRIC_KEYS = ['window_hours', 'observation_start', 'observation_end',
               'metric_period_seconds', 'coverage', 'sample_counts',
               'required_samples', 'received_sample_counts', 'invalid_sample_counts',
               'missing_metrics', 'invalid_metrics', 'calculation_errors', 'data_issues',
               'metric_units', 'metric_statistics']
FIELDS = {
    'EC2': ['cpu_p95', 'network_mib_hour', 'launch_time'],
    'EBS': ['size_gib', 'observed_hours', 'threshold_hours'],
    'EIP': ['observed_hours', 'threshold_hours'],
    'SNAPSHOT': ['age_days', 'volume_id', 'logical_volume_gib', 'relationships_complete',
                 'relationship_scope', 'snapshot_started_at'],
    'RDS': ['cpu_p95', 'connections_p95', 'engine', 'instance_class', 'created_at'],
    'NAT_GATEWAY': ['nat_mib_hour', 'vpc_id', 'subnet_id', 'created_at'],
    'ALB': ['requests_hour', 'scheme', 'created_at'],
    'NLB': ['new_flows_hour', 'scheme', 'created_at'],
    'S3_MULTIPART': ['bucket', 'key', 'upload_id', 'initiated_at', 'age_days', 'threshold_days'],
}
THRESHOLDS = {
    'EC2': ['cpu_percent', 'network_mib_hour'], 'EBS': ['orphan_hours'],
    'EIP': ['orphan_hours'], 'SNAPSHOT': ['snapshot_days'],
    'RDS': ['rds_cpu_percent', 'rds_connections'], 'NAT_GATEWAY': ['nat_mib_hour'],
    'ALB': ['alb_requests_hour'], 'NLB': ['nlb_new_flows_hour'],
    'S3_MULTIPART': ['multipart_days'],
}


def fixture_findings():
    """Generate the nine current evaluator schemas, then add collector context."""
    now = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    start, created = now - timedelta(hours=24), now - timedelta(days=60)
    cfg, zeros = config({}), [0] * 24
    items = [
        evaluate_ec2({'InstanceId': 'i-fixture', 'LaunchTime': created,
                      'State': {'Name': 'running'}}, [zeros, zeros, zeros], cfg, start),
        evaluate_ebs({'VolumeId': 'vol-fixture', 'Size': 40,
                      'State': 'available', 'Attachments': []}, 24, cfg),
        evaluate_eip({'AllocationId': 'eipalloc-fixture'}, 0, cfg),
        evaluate_snapshot({'SnapshotId': 'snap-fixture', 'StartTime': created,
                           'VolumeId': 'vol-source', 'VolumeSize': 40,
                           'State': 'completed'}, set(), True, cfg, now),
        evaluate_rds({'DBInstanceIdentifier': 'database-fixture', 'DBInstanceStatus': 'available',
                      'InstanceCreateTime': created, 'Engine': 'postgres',
                      'DBInstanceClass': 'db.t3.micro'}, [zeros, zeros], cfg, start),
        evaluate_nat_gateway({'NatGatewayId': 'nat-fixture', 'State': 'available',
                              'CreateTime': created, 'VpcId': 'vpc-fixture',
                              'SubnetId': 'subnet-fixture'}, [zeros, zeros], cfg, start),
        evaluate_load_balancer({'LoadBalancerName': 'alb-fixture', 'Type': 'application',
                                'State': {'Code': 'active'}, 'CreatedTime': created,
                                'Scheme': 'internet-facing'}, [zeros], cfg, start),
        evaluate_load_balancer({'LoadBalancerName': 'nlb-fixture', 'Type': 'network',
                                'State': {'Code': 'active'}, 'CreatedTime': created,
                                'Scheme': 'internal'}, [zeros], cfg, start),
        evaluate_s3_multipart('fixture-bucket', {'Key': 'archive/fixture.bin',
                              'UploadId': 'fixture-upload',
                              'Initiated': now - timedelta(days=8)}, now),
    ]
    stats = {'EC2': {'cpu': 'Maximum', 'netin': 'Sum', 'netout': 'Sum'},
             'RDS': {'cpu': 'Maximum', 'connections': 'Maximum'},
             'NAT_GATEWAY': {'source': 'Sum', 'destination': 'Sum'},
             'ALB': {'requests': 'Sum'}, 'NLB': {'flows': 'Sum'}}
    for item in items:
        assert item is not None
        context = {'account_id': '111111111111', 'region': REGION, 'evaluated_at': now.isoformat()}
        item.update(context, finding_id=finding_id(item['type'], REGION, item['resource_id']),
                    first_seen_at='2026-10-28T12:00:00+00:00',
                    last_seen_at='2026-10-30T12:00:00+00:00')
        item['evidence'].update(context)
        if item['type'] in stats:
            item['evidence'].update(observation_start=start.isoformat(), observation_end=now.isoformat(),
                                    metric_period_seconds=3600, metric_statistics=stats[item['type']])
    return items


def row(items, scan_id='fixture-scan'):
    return {'region': REGION, 'status': 'SUCCEEDED', 'scan_id': scan_id,
            'completed_at': 1793361600, 'counts': {item['type']: 1 for item in items},
            'findings': copy.deepcopy(items)}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'web')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_address[1])
    original = fixture_findings()
    state = {'profile': copy.deepcopy(PROFILE), 'rows': [row(original)],
             'history': [row(original)], 'requests': [], 'fixture_errors': [], 'unauthorized': False}
    checks, errors = [], []

    def route_api(route):
        request = route.request
        path = urlsplit(request.url).path.removeprefix('/api')
        state['requests'].append({'method': request.method, 'path': path})
        status, result = 200, {}
        try:
            if state['unauthorized']:
                status, result = 401, {'error': 'Access token required'}
            elif path == '/me':
                result = state['profile']
            elif path == '/findings':
                result = {'results': state['rows']}
            elif path == '/history':
                result = {'results': state['history'], 'next_token': None}
            elif path == '/connection' and request.method == 'PUT':
                body = request.post_data_json
                assert set(body) == {'role_arn', 'regions', 'service_groups'}, body
                state['profile'].update(body)
                state['rows'], state['history'] = [], []
                result = {'connected': True, 'account_id': state['profile']['account_id']}
            else:
                raise AssertionError('Unexpected fixture request: ' + request.method + ' ' + path)
        except Exception as error:
            state['fixture_errors'].append(str(error))
            status, result = 500, {'error': 'Fixture rejected request: ' + str(error)}
        route.fulfill(status=status, content_type='application/json', body=json.dumps(result))

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
            expect(page.locator('#findings-list tbody tr')).to_have_count(9)
            dialog = page.locator('#finding-dialog')
            content = page.locator('#finding-detail-content')

            def value(key):
                return content.locator('[data-field="' + key + '"] dd')

            def detail_button(container, resource_id):
                return page.locator(container + ' tbody tr').filter(
                    has=page.locator('code').filter(has_text=resource_id)).locator('.finding-open')

            def open_current(item):
                button = detail_button('#findings-list', item['resource_id'])
                button.click()
                expect(dialog).to_be_visible()
                return button

            def close():
                page.locator('#close-finding-detail').click()
                expect(dialog).not_to_be_visible()

            def snapshot():
                return content.locator('[data-field]').evaluate_all(
                    '(rows)=>Object.fromEntries(rows.map(row=>[row.dataset.field,row.querySelector("dd").textContent]))')

            snapshots = {}
            for item in original:
                open_current(item)
                for key in COMMON_KEYS:
                    expect(value(key)).to_have_count(1)
                    assert 'Chưa có dữ liệu' not in value(key).inner_text(), (item['type'], key)
                expect(value('account_id')).to_have_text('111111111111')
                expect(value('rule_id')).to_have_text(item['rule_id'])
                expect(value('recommendation')).to_have_text(item['recommendation'])
                expect(value('first_seen_at')).to_contain_text('2026-10-28')
                expect(value('last_seen_at')).to_contain_text('2026-10-30')
                for key in FIELDS[item['type']]:
                    expect(value(key)).to_have_count(1)
                    assert 'Chưa có dữ liệu' not in value(key).inner_text(), (item['type'], key)
                for key in THRESHOLDS[item['type']]:
                    expect(value('thresholds.' + key)).to_have_count(1)
                    assert 'Chưa có dữ liệu' not in value('thresholds.' + key).inner_text(), (item['type'], key)
                if item['type'] in ['EC2', 'RDS', 'NAT_GATEWAY', 'ALB', 'NLB']:
                    for key in METRIC_KEYS:
                        expect(value(key)).to_have_count(1)
                        assert 'Chưa có dữ liệu' not in value(key).inner_text(), (item['type'], key)
                    expect(value('window_hours')).to_contain_text('24')
                    expect(value('coverage')).to_contain_text('100')
                    expect(value('metric_period_seconds')).to_contain_text('3600')
                units = {'cpu_p95': '%', 'network_mib_hour': 'MiB/giờ',
                         'size_gib': 'GiB', 'logical_volume_gib': 'GiB',
                         'observed_hours': 'giờ', 'age_days': 'ngày',
                         'connections_p95': 'kết nối', 'nat_mib_hour': 'MiB/giờ',
                         'requests_hour': 'request/giờ', 'new_flows_hour': 'flow mới/giờ'}
                for key in FIELDS[item['type']]:
                    if key in units:
                        expect(value(key)).to_contain_text(units[key])
                snapshots[item['type']] = snapshot()
                close()
            checks.append('All nine real evaluator schemas, common identity/rule/recommendation/timestamps, type evidence and metric diagnostics')

            for width in [1440, 390]:
                page.set_viewport_size({'width': width, 'height': 900})
                open_current(original[0])
                page.screenshot(path=str(OUT / f'ec2-current-{width}.png'))
                value('coverage').scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / f'ec2-metrics-{width}.png'))
                close()
            page.set_viewport_size({'width': 1440, 'height': 1000})
            checks.append('Normal EC2 identity and scrolled metric evidence screenshots at 1440/390; four additional screenshots')

            open_current(original[0])
            expect(value('cpu_p95')).to_contain_text('0')
            expect(value('cpu_p95')).to_contain_text('%')
            expect(value('network_mib_hour')).to_contain_text('0')
            expect(value('network_mib_hour')).to_contain_text('MiB')
            expect(value('thresholds.cpu_percent')).to_contain_text('5')
            assert '50' not in value('thresholds.cpu_percent').inner_text()
            close()
            open_current(original[2])
            expect(value('observed_hours')).to_contain_text('0')
            expect(value('level')).to_contain_text('quan sát')
            close()
            open_current(original[3])
            expect(value('relationships_complete')).to_contain_text('Có')
            close()
            checks.append('Real numeric zero, percent/MiB/hour/day units, observing duration and true relationship coverage preserved')

            # A newer current result and different profile settings cannot rewrite history evidence.
            newer = copy.deepcopy(original)
            for item in newer:
                item.update(account_id='222222222222', first_seen_at='2026-10-29T12:00:00+00:00',
                            last_seen_at='2026-10-31T12:00:00+00:00')
                item['evidence']['window_hours'] = 48
                item['evidence']['thresholds'] = {'cpu_percent': 20}
            state['rows'] = [row(newer, 'newer-scan')]
            page.evaluate('refresh()')
            page.locator('[data-page="history"]').click()
            page.locator('#history-list button').click()
            expect(page.locator('#history-detail tbody tr')).to_have_count(9)
            for item in original:
                detail_button('#history-detail', item['resource_id']).click()
                expect(dialog).to_be_visible()
                assert snapshot() == snapshots[item['type']], item['type']
                assert page.locator('#finding-dialog button').count() == 1, 'History detail must not add feedback controls'
                close()
            checks.append('Current and history use the same renderer; saved account/threshold/window/first-last remain unchanged after newer results')

            # Legacy rows do not inherit profile account/settings or guess first/last from evaluated_at.
            legacy = {'type': 'EC2', 'resource_id': 'i-legacy', 'finding_id': 'legacy-id',
                      'level': 'INSUFFICIENT_DATA', 'reason': 'Legacy finding', 'evidence': None,
                      'evaluated_at': '2026-10-30T12:00:00+00:00',
                      'first_seen_at': None, 'last_seen_at': 'invalid-time'}
            state['rows'] = [row([legacy])]
            page.locator('[data-page="findings"]').click()
            page.evaluate('refresh()')
            open_current(legacy)
            for key in ['account_id', 'rule_id', 'recommendation', 'first_seen_at', 'last_seen_at',
                        'cpu_p95', 'network_mib_hour', 'coverage', 'thresholds.cpu_percent']:
                expect(value(key)).to_contain_text('Chưa có dữ liệu')
            assert 'Invalid Date' not in content.inner_text()
            assert PROFILE['account_id'] not in content.inner_text()
            close()
            # Evidence-level legacy context is accepted; offset timestamps display UTC.
            legacy.update(evidence={'account_id': '333333333333', 'evaluated_at': '2026-10-30T19:00:00+07:00',
                                    'cpu_p95': 0, 'network_mib_hour': 0, 'coverage': 0,
                                    'thresholds': {'cpu_percent': 0, 'network_mib_hour': 0},
                                    'missing_metrics': ['cpu'], 'invalid_metrics': [], 'data_issues': []},
                          evaluated_at=None, first_seen_at='2026-10-30T19:00:00+07:00',
                          last_seen_at='2026-10-30T12:00:00')
            state['rows'] = [row([legacy])]
            page.evaluate('refresh()')
            open_current(legacy)
            expect(value('account_id')).to_have_text('333333333333')
            expect(value('coverage')).to_contain_text('0%')
            expect(value('first_seen_at')).to_contain_text('12:00')
            expect(value('last_seen_at')).to_contain_text('Chưa có dữ liệu')
            expect(value('thresholds.cpu_percent')).to_contain_text('0')
            expect(value('missing_metrics')).to_contain_text('cpu')
            close()
            checks.append('Legacy/null evidence, absent metadata, invalid or timezone-less dates stay missing; evidence context fallback and zero coverage retained')

            for kind, old_key, old_value, threshold in [
                    ('EBS', 'threshold_hours', 0, 'orphan_hours'),
                    ('SNAPSHOT', 'snapshot_days', 45, 'snapshot_days'),
                    ('S3_MULTIPART', 'threshold_days', 7, 'multipart_days')]:
                item = copy.deepcopy(next(item for item in original if item['type'] == kind))
                item['evidence'].pop('thresholds')
                item['evidence'][old_key] = old_value
                if kind == 'SNAPSHOT':
                    item['evidence']['relationships_complete'] = False
                state['rows'] = [row([item])]
                page.evaluate('refresh()')
                open_current(item)
                expect(value('thresholds.' + threshold)).to_contain_text(str(old_value))
                if kind == 'SNAPSHOT':
                    expect(value('relationships_complete')).to_have_text('Không')
                close()
            checks.append('Legacy evidence threshold fields remain readable, including numeric zero; false relationship completeness is explicit')

            long_item = copy.deepcopy(original[-1])
            long_item['resource_id'] = 's3://fixture/<img src=x onerror=window.__detailXss=1>/' + 'x' * 1200
            long_item['reason'] = '<script>window.__detailXss=2</script> long reason'
            long_item['recommendation'] = '<svg onload=window.__detailXss=3> review manually'
            long_item['evidence'].update(key='path/<img src=x onerror=window.__detailXss=4>/' + 'k' * 1200,
                                         upload_id='u' * 1000)
            state['rows'], state['history'] = [row([long_item])], [row([long_item])]
            page.evaluate('refresh()')
            opener = open_current(long_item)
            expect(value('resource_id')).to_have_text(long_item['resource_id'])
            expect(value('reason')).to_have_text(long_item['reason'])
            expect(value('recommendation')).to_have_text(long_item['recommendation'])
            assert dialog.locator('img,script,svg').count() == 0
            assert not page.evaluate('window.__detailXss || 0')
            for _ in range(5):
                page.keyboard.press('Tab')
                focus = page.evaluate('''()=>({inside: document.getElementById("finding-dialog").contains(document.activeElement),
                                             tag: document.activeElement.tagName, id: document.activeElement.id,
                                             documentFocus: document.hasFocus()})''')
                assert focus['inside'] or not focus['documentFocus'], focus
            page.locator('#scan').evaluate('(button)=>button.focus()')
            assert page.evaluate('document.activeElement.id !== "scan"'), 'Underlying page must remain inert while modal'
            page.locator('#close-finding-detail').focus()
            expect(page.locator('#close-finding-detail')).to_be_focused()
            page.keyboard.press('Escape')
            expect(dialog).not_to_be_visible()
            expect(opener).to_be_focused()
            checks.append('Long resource/key/upload IDs and HTML stay safe text; modal keyboard containment, Escape and focus return')

            # Polling can replace the opener while the modal stays open.
            for dismissal in ['Escape', 'close-button']:
                open_current(long_item)
                page.evaluate('refresh()')
                expect(dialog).to_be_visible()
                if dismissal == 'Escape':
                    page.keyboard.press('Escape')
                    expect(dialog).not_to_be_visible()
                else:
                    close()
                expect(detail_button('#findings-list', long_item['resource_id'])).to_be_focused()
            open_current(long_item)
            state['rows'] = []
            page.evaluate('refresh()')
            close()
            assert page.evaluate('''()=>document.activeElement.matches('button,input,select,a') &&
                                        document.activeElement.getClientRects().length > 0 &&
                                        !document.activeElement.closest('#finding-dialog')'''), 'Disappeared opener needs a visible focus fallback'
            state['rows'] = [row([long_item])]
            page.evaluate('refresh()')
            checks.append('Polling replacement restores focus to the matching finding after Escape/close; removed finding receives a visible fallback')

            for width in [320, 390, 768, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.locator('[data-page="findings"]').click()
                open_current(long_item)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                assert dialog.evaluate('(el)=>el.scrollWidth <= el.clientWidth'), width
                page.screenshot(path=str(OUT / f'current-{width}.png'))
                close()
                page.locator('[data-page="history"]').click()
                page.locator('#history-list button').click()
                detail_button('#history-detail', long_item['resource_id']).click()
                expect(dialog).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                assert dialog.evaluate('(el)=>el.scrollWidth <= el.clientWidth'), width
                page.screenshot(path=str(OUT / f'history-{width}.png'))
                close()
            checks.append('Current/history detail with long IDs at 320/390/768/1440; eight screenshots and no horizontal overflow')

            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.locator('[data-page="findings"]').click()
            open_current(long_item)
            page.evaluate("location.hash = '#overview'")
            expect(dialog).not_to_be_visible()
            # Overview priority also opens the shared detail.
            page.locator('#priority-list .finding-open').click()
            expect(dialog).to_be_visible()
            expect(value('resource_id')).to_have_text(long_item['resource_id'])
            page.evaluate('init()')
            expect(dialog).not_to_be_visible()
            page.locator('[data-page="findings"]').click()
            open_current(long_item)
            page.evaluate("""async payload=>{await api('/connection','PUT',payload); await init();}""",
                          {'role_arn': ARN, 'regions': [REGION], 'service_groups': ['compute']})
            expect(dialog).not_to_be_visible()
            expect(page.locator('#findings-list tbody tr')).to_have_count(0)
            state['rows'] = [row([long_item])]
            page.evaluate('refresh()')
            open_current(long_item)
            state['unauthorized'] = True
            page.evaluate('refresh().catch(()=>{})')
            expect(dialog).not_to_be_visible()
            expect(page.locator('#app')).to_be_hidden()
            checks.append('Priority detail uses shared renderer; navigation/init/reconnect/401 dismiss stale detail and auth returns to login')

            assert not errors, errors
            assert not state['fixture_errors'], state['fixture_errors']
            result = {'environment': 'LOCAL HTTP/API FIXTURES - NOT AWS', 'checks': checks,
                      'page_errors': errors, 'fixture_errors': state['fixture_errors'],
                      'request_count': len(state['requests']), 'screenshots': 12,
                      'widths': [320, 390, 768, 1440]}
            (OUT / 'acceptance-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            browser.close()
            print('Finding detail UI PASS: ' + '; '.join(checks))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
