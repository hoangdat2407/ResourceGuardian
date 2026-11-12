"""Feedback browser acceptance with isolated local fixtures, never AWS.

Run with CHROMIUM_EXECUTABLE and UI_QA_DIR as for ui_scope_filters.py.
"""
import copy
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rules import config, finding_id

OUT = Path(os.environ.get('UI_QA_DIR', ROOT / '.preflight/ui-finding-feedback'))
REGION = 'ap-southeast-1'
ARN = 'arn:aws:iam::123456789012:role/GuardianReadRole-fixture'
KINDS = ['EC2', 'EBS', 'EIP', 'SNAPSHOT', 'RDS', 'NAT_GATEWAY', 'ALB', 'NLB', 'S3_MULTIPART']
PROFILE = {
    'account_id': '123456789012', 'role_arn': ARN, 'regions': [REGION],
    'external_id': 'FIXTURE-ONLY-EXTERNAL-ID',
    'api_principal': 'arn:aws:iam::123456789012:role/FixtureApiPrincipal',
    'scan_principal': 'arn:aws:iam::123456789012:role/FixtureScanPrincipal',
    'service_groups': ['compute', 'storage', 'database', 'network'],
    'settings': config({}), 'notifications': {'enabled': False}, 'email_available': False,
}


def fixture_findings():
    return [{
        'type': kind, 'resource_id': 'feedback-' + kind.lower(), 'region': REGION,
        'finding_id': finding_id(kind, REGION, 'feedback-' + kind.lower()),
        'account_id': PROFILE['account_id'], 'rule_id': kind + '_FIXTURE',
        'level': 'REVIEW', 'reason': 'Review intended workload for ' + kind,
        'recommendation': 'Review the resource with its owner.',
        'evaluated_at': '2026-10-30T12:00:00Z',
        'first_seen_at': '2026-10-29T12:00:00Z', 'last_seen_at': '2026-10-30T12:00:00Z',
        'evidence': {},
    } for kind in KINDS]


def fixture_row(items, scan_id='feedback-scan'):
    return {'region': REGION, 'status': 'SUCCEEDED', 'scan_id': scan_id,
            'completed_at': 1793361600, 'counts': {kind: 1 for kind in KINDS},
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
    state = {'profile': copy.deepcopy(PROFILE), 'rows': [fixture_row(original)],
             'history': [fixture_row(original)], 'records': {}, 'requests': [],
             'hold_put': False, 'held': None, 'put_error': False,
             'hold_findings': False, 'held_findings': None,
             'findings_error': False, 'unauthorized': False, 'fixture_errors': []}
    checks, errors = [], []

    def visible_rows():
        rows = copy.deepcopy(state['rows'])
        for row in rows:
            visible = []
            for finding in row['findings']:
                record = state['records'].get((row['region'], finding['finding_id']), {})
                if record.get('kept') or record.get('ignore_until', 0) > time.time():
                    continue
                finding.pop('acknowledged', None)
                if record.get('acknowledged'):
                    finding['acknowledged'] = True
                visible.append(finding)
            row['findings'] = visible
        return rows

    def save_feedback(body):
        identity = (body['region'], body['finding_id'])
        candidate = next(item for row in state['rows'] if row['region'] == body['region']
                         for item in row['findings'] if item['finding_id'] == body['finding_id'])
        record = copy.deepcopy(state['records'].get(identity, {}))
        record.update(region=identity[0], finding_id=identity[1])
        record.update({key: candidate[key] for key in ['type', 'resource_id', 'account_id', 'rule_id']})
        for key in ['acknowledged', 'kept']:
            if key in body:
                record[key] = body[key]
        if 'ignoreUntil' in body:
            record['ignore_until'] = int(datetime.fromisoformat(body['ignoreUntil'].replace('Z', '+00:00')).timestamp())
        state['records'][identity] = record
        return record

    def validate_feedback(body):
        assert isinstance(body, dict), body
        changed = set(body) & {'acknowledged', 'kept', 'ignoreUntil'}
        assert len(changed) == 1 and set(body) == {'region', 'finding_id'} | changed, body
        assert body['region'] == REGION and isinstance(body['finding_id'], str), body
        assert any(item['finding_id'] == body['finding_id'] for row in state['rows'] for item in row['findings']), body
        for key in ['acknowledged', 'kept']:
            if key in body:
                assert type(body[key]) is bool, body
        if 'ignoreUntil' in body:
            assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z', body['ignoreUntil']), body
            stamp = datetime.fromisoformat(body['ignoreUntil'].replace('Z', '+00:00')).timestamp()
            assert time.time() < stamp <= time.time() + 30 * 86400 + 2, body

    def route_api(route):
        request = route.request
        path = urlsplit(request.url).path.removeprefix('/api')
        body = request.post_data_json if request.post_data else None
        state['requests'].append({'method': request.method, 'path': path, 'body': copy.deepcopy(body)})
        status, result = 200, {}
        try:
            if state['unauthorized']:
                status, result = 401, {'error': 'Access token required'}
            elif path == '/me':
                result = state['profile']
            elif path == '/findings':
                if state['hold_findings']:
                    assert state['held_findings'] is None
                    state['held_findings'] = (route, {'results': visible_rows()})
                    state['hold_findings'] = False
                    return
                status, result = ((503, {'error': 'Service unavailable'}) if state['findings_error']
                                  else (200, {'results': visible_rows()}))
            elif path == '/feedback' and request.method == 'GET':
                result = {'results': list(state['records'].values()), 'next_token': None}
            elif path == '/history':
                result = {'results': state['history'], 'next_token': None}
            elif path.startswith('/scans/'):
                result = {'results': [row for row in state['history'] if row.get('scan_id') == path.rsplit('/', 1)[-1]]}
            elif path == '/feedback' and request.method == 'PUT':
                validate_feedback(body)
                if state['hold_put']:
                    assert state['held'] is None
                    state['held'] = (route, copy.deepcopy(body))
                    state['hold_put'] = False
                    return
                status, result = ((503, {'error': 'Feedback service unavailable'}) if state['put_error']
                                  else (200, save_feedback(body)))
            elif path == '/scans' and request.method == 'POST':
                assert body is None
                state['rows'][0]['scan_id'] = 'feedback-next-scan'
                status, result = 202, {'scan_id': 'feedback-next-scan'}
            elif path == '/connection' and request.method == 'PUT':
                assert set(body) == {'role_arn', 'regions', 'service_groups'}
                state['profile'].update(body)
                state['rows'], state['history'], state['records'] = [], [], {}
                result = {'connected': True, 'account_id': PROFILE['account_id']}
            else:
                raise AssertionError('Unexpected fixture request: ' + request.method + ' ' + path)
        except Exception as error:
            state['fixture_errors'].append(str(error))
            status, result = 500, {'error': 'Fixture rejected request: ' + str(error)}
        route.fulfill(status=status, content_type='application/json', body=json.dumps(result))

    def puts():
        return [item['body'] for item in state['requests'] if item['path'] == '/feedback' and item['method'] == 'PUT']

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

            def row(item, container='#findings-list'):
                return page.locator(container + ' tbody tr').filter(
                    has=page.locator('code').filter(has_text=item['resource_id']))

            def action(item, cls, container='#findings-list'):
                return row(item, container).locator('.' + cls)

            def expand(item, container='#findings-list'):
                target = row(item, container)
                group = target.locator('xpath=ancestor::section[contains(@class,"finding-group")]')
                toggle = group.locator('.group-toggle')
                if toggle.count() and toggle.first.get_attribute('aria-expanded') == 'false':
                    toggle.first.click()
                menu = target.locator('details.actions-menu')
                if menu.count() and not menu.first.evaluate('(el)=>el.open'):
                    target.locator('.actions-summary').first.click()
                return target

            def click_action(item, cls, container='#findings-list'):
                expand(item, container).locator('.' + cls).click()

            def reset():
                assert state['held'] is None and state['held_findings'] is None
                state.update(profile=copy.deepcopy(PROFILE), rows=[fixture_row(original)], history=[fixture_row(original)], records={},
                             hold_put=False, put_error=False, hold_findings=False, findings_error=False, unauthorized=False)
                page.goto(base + '/#findings')
                page.reload()
                expect(page.locator('#findings-list tbody tr')).to_have_count(9)

            def release(status=200, stale=False):
                pending, body = state['held']
                state['held'] = None
                result = {'error': 'Feedback service unavailable'}
                if status == 200:
                    result = ({'region': body['region'], 'finding_id': body['finding_id'],
                               **{key: body[key] for key in ['acknowledged', 'kept'] if key in body}}
                              if stale else save_feedback(body))
                pending.fulfill(status=status, content_type='application/json', body=json.dumps(result))

            expect(page.locator('#findings-list tbody tr')).to_have_count(9)
            page.locator('#advanced-filters summary').click()
            for item in original:
                click_action(item, 'feedback-ack')
                expect(action(item, 'feedback-ack')).to_have_text('Bỏ đã xem')
                assert puts()[-1] == {'region': REGION, 'finding_id': item['finding_id'], 'acknowledged': True}
                expect(row(item)).to_have_count(1)
                click_action(item, 'feedback-ack')
                expect(action(item, 'feedback-ack')).to_have_text('Đánh dấu đã xem')
                assert puts()[-1] == {'region': REGION, 'finding_id': item['finding_id'], 'acknowledged': False}
            checks.append('Acknowledged toggle for all nine types sends one exact flag, retains findings and uses no client metadata')

            item = original[0]
            click_action(item, 'feedback-ack')
            expect(action(item, 'feedback-ack')).to_have_text('Bỏ đã xem')
            page.locator('#filter-acknowledged').select_option('acknowledged')
            expect(page.locator('#findings-list tbody tr')).to_have_count(1)
            page.reload()
            expect(action(item, 'feedback-ack')).to_have_text('Bỏ đã xem')
            page.locator('[data-page="overview"]').click()
            expect(action(item, 'feedback-ack', '#priority-list')).to_have_text('Bỏ đã xem')
            page.locator('[data-page="findings"]').click()
            click_action(item, 'feedback-keep')
            expect(row(item)).to_have_count(0)
            record = state['records'][(REGION, item['finding_id'])]
            assert record['acknowledged'] is True and record['kept'] is True
            assert puts()[-1] == {'region': REGION, 'finding_id': item['finding_id'], 'kept': True}
            page.reload()
            expect(row(item)).to_have_count(0)
            page.locator('#scan').click()
            expect(row(item)).to_have_count(0)
            assert state['records'][(REGION, item['finding_id'])]['acknowledged'] is True
            checks.append('Acknowledged persists across reload and priority view; keep hides immediately, persists next scan, and preserves acknowledged')

            for item, days in [(original[1], 7), (original[2], 1), (original[3], 30)]:
                click_action(item, 'feedback-ignore')
                expect(page.locator('#ignore-dialog')).to_be_visible()
                expect(page.locator('#ignore-days')).to_have_value('7')
                page.locator('#ignore-days').fill(str(days))
                before = time.time()
                page.locator('#ignore-confirm').click()
                expect(page.locator('#ignore-dialog')).not_to_be_visible()
                page.wait_for_timeout(300)
                expect(row(item)).to_have_count(0)
                body = puts()[-1]
                assert set(body) == {'region', 'finding_id', 'ignoreUntil'} and body['finding_id'] == item['finding_id']
                until = datetime.fromisoformat(body['ignoreUntil'].replace('Z', '+00:00')).timestamp()
                assert abs(until - before - days * 86400) < 3, (days, until, before)
                assert state['records'][(REGION, item['finding_id'])]['ignore_until'] > time.time()
            page.reload()
            for item in original[:4]:
                expect(row(item)).to_have_count(0)
            checks.append('Ignore defaults to seven days; selectable one-through-thirty days sends UTC expiry and hides only after success, persisting on reload')

            page.locator('[data-page="history"]').click()
            page.locator('#history-list .history-open').click()
            expect(page.locator('#history-detail tbody tr')).to_have_count(9)
            assert page.locator('#history-detail .finding-feedback').count() == 0
            assert page.locator('#history-detail .feedback-ack, #history-detail .feedback-keep, #history-detail .feedback-ignore').count() == 0
            assert state['history'] == [fixture_row(original)]
            checks.append('New feedback leaves saved history snapshots unchanged and history has no mutation controls')

            reset()
            item, other = original[0], original[1]
            state['hold_put'] = True
            with page.expect_request('**/api/feedback'):
                click_action(item, 'feedback-ack')
            expect(action(item, 'feedback-ack')).to_be_disabled()
            expect(action(item, 'feedback-keep')).to_be_disabled()
            expect(action(item, 'feedback-ignore')).to_be_disabled()
            expect(action(item, 'feedback-status')).to_contain_text('Đang lưu')
            expect(action(other, 'feedback-ack')).to_be_enabled()
            assert not state['records']
            page.locator('[data-page="overview"]').click()
            expect(action(item, 'feedback-ack', '#priority-list')).to_be_disabled()
            expect(action(item, 'feedback-status', '#priority-list')).to_contain_text('Đang lưu')
            page.locator('[data-page="findings"]').click()
            page.evaluate('refresh()')
            expect(row(item)).to_have_count(1)
            expect(action(item, 'feedback-ack')).to_be_disabled()
            expect(action(item, 'feedback-status')).to_contain_text('Đang lưu')
            release(status=503)
            expect(action(item, 'feedback-ack')).to_be_enabled()
            expect(action(item, 'feedback-status')).to_contain_text('Feedback service unavailable')
            expect(action(item, 'feedback-ack')).to_have_text('Đánh dấu đã xem')
            assert not state['records']
            click_action(item, 'feedback-ack')
            expect(action(item, 'feedback-ack')).to_have_text('Bỏ đã xem')
            assert state['records'][(REGION, item['finding_id'])]['acknowledged'] is True
            checks.append('Held request never updates optimistically; identity controls stay disabled through poll rerender; failed save stays retryable and retry succeeds')

            for operation, old_status in [('feedback-ack', 200), ('feedback-keep', 200), ('feedback-keep', 503)]:
                reset()
                item = original[0]
                state['hold_findings'] = True
                with page.expect_request('**/api/findings'):
                    page.evaluate('''window.__oldFeedbackGetDone=false;
                        void refresh().catch(()=>{}).finally(()=>window.__oldFeedbackGetDone=true);''')
                click_action(item, operation)
                if operation == 'feedback-ack':
                    expect(action(item, 'feedback-ack')).to_have_text('Bỏ đã xem')
                else:
                    expect(row(item)).to_have_count(0)
                pending, snapshot_reply = state['held_findings']
                state['held_findings'] = None
                reply = snapshot_reply if old_status == 200 else {'error': 'OLD_GET_MUST_NOT_APPEAR'}
                pending.fulfill(status=old_status, content_type='application/json', body=json.dumps(reply))
                page.wait_for_function('window.__oldFeedbackGetDone === true')
                if operation == 'feedback-ack':
                    expect(action(item, 'feedback-ack')).to_have_text('Bỏ đã xem')
                else:
                    expect(row(item)).to_have_count(0)
                expect(page.locator('#status')).not_to_contain_text('OLD_GET_MUST_NOT_APPEAR')
            checks.append('Held findings success/error from before a successful feedback write cannot undo acknowledged or resurrect a kept finding')

            reset()
            item = original[0]
            state['findings_error'] = True
            count_before = len(puts())
            click_action(item, 'feedback-ack')
            expect(action(item, 'feedback-ack')).to_have_text('Bỏ đã xem')
            expect(action(item, 'feedback-ack')).to_be_enabled()
            assert len(puts()) == count_before + 1
            assert state['records'][(REGION, item['finding_id'])]['acknowledged'] is True
            expect(page.locator('#status')).to_contain_text(re.compile('lưu|xem', re.I))
            state['findings_error'] = False
            page.locator('[data-page="overview"]').click()
            page.locator('#refresh').click()
            page.locator('[data-page="findings"]').click()
            expect(action(item, 'feedback-ack')).to_have_text('Bỏ đã xem')
            assert len(puts()) == count_before + 1
            checks.append('Successful PUT followed by failed refresh keeps saved state and reload can recover without duplicate PUT')

            reset()
            item = original[0]
            # An existing expired ignore flag must not be cleared by acknowledged.
            identity = (REGION, item['finding_id'])
            state['records'][identity] = {'ignore_until': int(time.time()) - 10, 'kept': False}
            expired = state['records'][identity]['ignore_until']
            click_action(item, 'feedback-ack')
            expect(action(item, 'feedback-ack')).to_have_text('Bỏ đã xem')
            assert state['records'][identity]['ignore_until'] == expired
            click_action(item, 'feedback-ignore')
            page.locator('#ignore-confirm').click()
            expect(row(item)).to_have_count(0)
            assert state['records'][identity]['acknowledged'] is True
            assert state['records'][identity]['kept'] is False
            checks.append('Each feedback request changes only its selected flag and does not clear independent acknowledged, keep or ignore flags')

            for response_status in [200, 503]:
                reset()
                item = original[0]
                page.evaluate('''()=>{window.__heldFeedbackDone=false;
                    window.__nativeSaveFindingFeedback=saveFindingFeedback;
                    saveFindingFeedback=(...args)=>window.__nativeSaveFindingFeedback(...args)
                        .finally(()=>window.__heldFeedbackDone=true);}''')
                state['hold_put'] = True
                with page.expect_request('**/api/feedback'):
                    click_action(item, 'feedback-ack')
                page.evaluate("""async payload=>{await api('/connection','PUT',payload); await init();}""",
                              {'role_arn': ARN, 'regions': [REGION], 'service_groups': ['compute']})
                expect(page.locator('#findings-list tbody tr')).to_have_count(0)
                state['rows'] = [fixture_row([original[1]], 'new-scope')]
                page.evaluate('refresh()')
                expect(row(original[1])).to_have_count(1)
                release(status=response_status, stale=True)
                page.wait_for_function('window.__heldFeedbackDone === true')
                expect(row(original[1])).to_have_count(1)
                expect(action(original[1], 'feedback-ack')).to_have_text('Đánh dấu đã xem')
                expect(row(item)).to_have_count(0)
                expect(page.locator('#status')).not_to_contain_text('Feedback service unavailable')
            checks.append('Held feedback success and error from an old connection cannot mutate new-scope findings or show stale errors')

            reset()
            long_item = state['rows'][0]['findings'][0]
            long_item['resource_id'] = 'feedback-resource-' + 'x' * 600
            page.evaluate('refresh()')
            for width in [320, 390, 768, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.locator('[data-page="findings"]').click()
                expand(long_item)
                expect(action(long_item, 'feedback-ack')).to_be_visible()
                expect(action(long_item, 'feedback-keep')).to_be_visible()
                expect(action(long_item, 'feedback-ignore')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                page.screenshot(path=str(OUT / f'findings-{width}.png'), full_page=True)
                page.locator('[data-page="overview"]').click()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                page.screenshot(path=str(OUT / f'priority-{width}.png'), full_page=True)
            page.locator('[data-page="findings"]').click()
            expand(long_item)
            action(long_item, 'feedback-ack').focus()
            expect(action(long_item, 'feedback-ack')).to_be_focused()
            page.keyboard.press('Tab')
            expect(action(long_item, 'feedback-keep')).to_be_focused()
            page.keyboard.press('Tab')
            expect(action(long_item, 'feedback-ignore')).to_be_focused()
            checks.append('Feedback controls and long resource IDs fit 320/390/768/1440 widths; eight screenshots and keyboard order')

            state['unauthorized'] = True
            click_action(long_item, 'feedback-ack')
            expect(page.locator('#app')).to_be_hidden()
            expect(page.locator('#welcome')).to_be_visible()
            assert not errors, errors
            assert not state['fixture_errors'], state['fixture_errors']
            checks.append('Expired-session save returns to login without pretending feedback succeeded')
            result = {'environment': 'LOCAL HTTP/API FIXTURES - NOT AWS', 'checks': checks,
                      'page_errors': errors, 'fixture_errors': state['fixture_errors'],
                      'request_count': len(state['requests']), 'put_count': len(puts()),
                      'screenshots': 8, 'widths': [320, 390, 768, 1440]}
            (OUT / 'acceptance-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            browser.close()
            print('Finding feedback UI PASS: ' + '; '.join(checks))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
