"""Feedback management acceptance through local HTTP/API fixtures, never AWS."""
import copy
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rules import config

OUT = Path(os.environ.get('UI_QA_DIR', ROOT / '.preflight/ui-feedback-management'))
REGION = 'ap-southeast-1'
ARN = 'arn:aws:iam::123456789012:role/GuardianReadRole-fixture'
TOKEN = 'opaque cursor +/?= page:2'
PROFILE = {
    'account_id': '123456789012', 'role_arn': ARN, 'regions': [REGION],
    'external_id': 'FIXTURE-ONLY-EXTERNAL-ID',
    'api_principal': 'arn:aws:iam::123456789012:role/FixtureApiPrincipal',
    'scan_principal': 'arn:aws:iam::123456789012:role/FixtureScanPrincipal',
    'service_groups': ['compute', 'storage', 'database', 'network'],
    'settings': config({}), 'notifications': {'enabled': False}, 'email_available': False,
}


def fixtures():
    now = int(time.time())
    records, candidates = [], []
    for index in range(25):
        ident = format(index + 1, '064x')
        candidate = {
            'finding_id': ident, 'region': REGION, 'type': 'EBS',
            'resource_id': 'vol-management-' + str(index), 'account_id': PROFILE['account_id'],
            'rule_id': 'EBS_UNATTACHED', 'level': 'REVIEW', 'reason': 'Review data retention',
            'recommendation': 'Review the volume with its owner.', 'evidence': {'size_gib': 40},
            'first_seen_at': '2026-10-29T12:00:00Z', 'last_seen_at': '2026-10-30T12:00:00Z',
        }
        record = {key: candidate[key] for key in ['finding_id', 'region', 'type', 'resource_id', 'account_id', 'rule_id']}
        record.update(kept=True, acknowledged=True, ignore_until=0, updated_at=now)
        records.append(record)
        if index != 24:
            candidates.append(candidate)
    records[0]['ignore_until'] = now + 7 * 86400
    records[1].update(kept=False, ignore_until=now + 7 * 86400)
    for index in [2, 24]:
        for key in ['type', 'resource_id', 'account_id', 'rule_id']:
            records[index].pop(key)
    return records, candidates


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'web')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_address[1])
    original_records, original_candidates = fixtures()
    state = {
        'profile': copy.deepcopy(PROFILE), 'records': copy.deepcopy(original_records),
        'candidates': copy.deepcopy(original_candidates), 'history': copy.deepcopy(original_candidates),
        'requests': [], 'page_error': False, 'put_error': False, 'findings_error': False,
        'hold_get': False, 'held_get': None, 'hold_put': False, 'held_put': None,
        'first_page': None, 'second_page': None, 'unauthorized': False, 'fixture_errors': [],
    }
    checks, errors = [], []

    def record_for(ident):
        return next(record for record in state['records'] if record['finding_id'] == ident)

    def active(record):
        return record.get('kept') or record.get('ignore_until', 0) > time.time()

    def visible_findings():
        found = []
        for candidate in state['candidates']:
            record = record_for(candidate['finding_id'])
            if active(record):
                continue
            item = copy.deepcopy(candidate)
            item['acknowledged'] = record.get('acknowledged', False)
            found.append(item)
        return found

    def result(items):
        return {'results': [{'region': REGION, 'scan_id': 'management-scan', 'status': 'SUCCEEDED',
                             'completed_at': 1793361600, 'counts': {'EBS': 25}, 'findings': copy.deepcopy(items)}]}

    def feedback_page(token):
        if state['first_page'] is not None:
            items = state['first_page'] if token is None else state['second_page']
        else:
            # The duplicate across the boundary models a dataset updated between requests.
            items = state['records'][:20] if token is None else state['records'][19:]
        return {'results': copy.deepcopy(items), 'next_token': TOKEN if token is None else None}

    def validate_put(body):
        changed = set(body) & {'acknowledged', 'kept', 'ignoreUntil'}
        assert len(changed) == 1 and set(body) == {'region', 'finding_id'} | changed, body
        assert body['region'] == REGION, body
        record_for(body['finding_id'])
        for key in ['acknowledged', 'kept']:
            if key in body:
                assert type(body[key]) is bool, body
        if body.get('ignoreUntil') is not None:
            value = body['ignoreUntil']
            assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z', value), body
            expiry = datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
            assert time.time() < expiry <= time.time() + 30 * 86400 + 2, body

    def save(body):
        record = record_for(body['finding_id'])
        for field in ['acknowledged', 'kept']:
            if field in body:
                record[field] = body[field]
        if 'ignoreUntil' in body:
            record['ignore_until'] = (int(datetime.fromisoformat(body['ignoreUntil'].replace('Z', '+00:00')).timestamp())
                                      if body['ignoreUntil'] is not None else 0)
        record['updated_at'] = int(time.time())
        return copy.deepcopy(record)

    def route_api(route):
        request = route.request
        parsed = urlsplit(request.url)
        path, query = parsed.path.removeprefix('/api'), parse_qs(parsed.query)
        body = request.post_data_json if request.post_data else None
        state['requests'].append({'method': request.method, 'path': path, 'query': copy.deepcopy(query),
                                  'url': request.url, 'body': copy.deepcopy(body)})
        status, reply = 200, {}
        try:
            if state['unauthorized']:
                status, reply = 401, {'error': 'Access token required'}
            elif path == '/me':
                reply = state['profile']
            elif path == '/findings':
                status, reply = ((503, {'error': 'Findings temporarily unavailable'}) if state['findings_error']
                                 else (200, result(visible_findings())))
            elif path == '/history':
                reply = {**result(state['history']), 'next_token': None}
            elif path.startswith('/scans/'):
                reply = result(state['history'])
            elif path == '/feedback' and request.method == 'GET':
                assert query.get('limit') == ['20'], query
                assert set(query) <= {'limit', 'next_token'}, query
                token = query.get('next_token', [None])[0]
                assert token in [None, TOKEN], token
                reply = feedback_page(token)
                if state['hold_get']:
                    assert state['held_get'] is None
                    state['held_get'] = (route, copy.deepcopy(reply))
                    state['hold_get'] = False
                    return
                if state['page_error'] and token:
                    status, reply = 503, {'error': 'Feedback page unavailable'}
            elif path == '/feedback' and request.method == 'PUT':
                validate_put(body)
                if state['hold_put']:
                    assert state['held_put'] is None
                    state['held_put'] = (route, copy.deepcopy(body))
                    state['hold_put'] = False
                    return
                status, reply = ((503, {'error': 'Feedback update unavailable'}) if state['put_error'] else (200, save(body)))
            elif path == '/connection' and request.method == 'PUT':
                assert set(body) == {'role_arn', 'regions', 'service_groups'}
                state['profile'].update(body)
                state['records'], state['candidates'], state['history'] = [], [], []
                state['first_page'], state['second_page'] = [], []
                reply = {'connected': True, 'account_id': PROFILE['account_id']}
            else:
                raise AssertionError('Unexpected fixture request: ' + request.method + ' ' + path)
        except Exception as error:
            state['fixture_errors'].append(str(error))
            status, reply = 500, {'error': 'Fixture rejected request: ' + str(error)}
        route.fulfill(status=status, content_type='application/json', body=json.dumps(reply))

    def feedback_gets():
        return [entry for entry in state['requests'] if entry['method'] == 'GET' and entry['path'] == '/feedback']

    def puts():
        return [entry['body'] for entry in state['requests'] if entry['method'] == 'PUT' and entry['path'] == '/feedback']

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

            def group(item):
                identity = json.dumps([item['region'], item['finding_id']], separators=(',', ':'))
                return page.locator('.feedback-record[data-feedback-key=' + json.dumps(identity) + ']')

            def current(item):
                return page.locator('#findings-list tbody tr').filter(
                    has=page.locator('code').filter(has_text=item['resource_id']))

            def reset():
                assert state['held_get'] is None and state['held_put'] is None
                state.update(profile=copy.deepcopy(PROFILE), records=copy.deepcopy(original_records),
                             candidates=copy.deepcopy(original_candidates), history=copy.deepcopy(original_candidates),
                             page_error=False, put_error=False, findings_error=False, first_page=None,
                             second_page=None, hold_get=False, hold_put=False, unauthorized=False)
                page.goto(base + '/#findings')
                page.reload()
                page.locator('#feedback-tab').click()
                expect(page.locator('#feedback-list .feedback-record')).to_have_count(20)

            page.goto(base + '/#findings')
            page.locator('#results-tab').focus()
            page.keyboard.press('ArrowRight')
            expect(page.locator('#feedback-tab')).to_be_focused()
            expect(page.locator('#feedback-tab')).to_have_attribute('aria-selected', 'true')
            page.keyboard.press('Home')
            expect(page.locator('#results-tab')).to_be_focused()
            expect(page.locator('#results-tab')).to_have_attribute('aria-selected', 'true')
            page.keyboard.press('End')
            expect(page.locator('#feedback-tab')).to_be_focused()
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(20)
            checks.append('Result and feedback tabs support Arrow, Home and End keyboard navigation')
            legacy = original_records[2]
            expect(group(legacy)).to_contain_text(legacy['finding_id'])
            expect(group(legacy)).to_contain_text(REGION)
            enriched = original_records[0]
            for field in ['type', 'resource_id', 'account_id', 'rule_id']:
                expect(group(enriched)).to_contain_text(enriched[field])
            expect(page.locator('#feedback-load-more')).to_be_visible()
            state['page_error'] = True
            page.locator('#feedback-load-more').click()
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(20)
            expect(page.locator('#feedback-summary')).to_contain_text(re.compile('lỗi|không|thử', re.I))
            state['page_error'] = False
            page.locator('#feedback-load-more').click()
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(25)
            identities = page.locator('#feedback-list .feedback-record').evaluate_all('(rows)=>rows.map(row=>row.dataset.feedbackKey)')
            assert len(set(identities)) == 25
            assert feedback_gets()[-1]['query']['next_token'] == [TOKEN]
            page.locator('#refresh-feedback').click()
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(20)
            assert 'next_token' not in feedback_gets()[-1]['query']
            checks.append('Twenty-plus feedback records, metadata and legacy identity, opaque pagination, deduplication, retry preserves rows and refresh resets cursor')

            reset()
            page.locator('#feedback-load-more').focus()
            page.keyboard.press('Enter')
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(25)
            expect(page.locator('#feedback-load-more')).to_be_hidden()
            expect(page.locator('#feedback-summary')).to_be_focused()
            # Loading disables the initiating control, so keyboard focus has a persistent target.
            state['hold_get'] = True
            page.locator('#refresh-feedback').focus()
            with page.expect_request('**/api/feedback?**'):
                page.keyboard.press('Enter')
            expect(page.locator('#refresh-feedback')).to_be_disabled()
            expect(page.locator('#feedback-summary')).to_be_focused()
            pending, snapshot = state['held_get']
            state['held_get'] = None
            pending.fulfill(json=snapshot)
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(20)
            expect(page.locator('#feedback-summary')).to_be_focused()
            # An idle render preserves a still-enabled page control.
            page.locator('#refresh-feedback').focus()
            page.evaluate('renderFeedback()')
            expect(page.locator('#refresh-feedback')).to_be_focused()
            # Completion must not steal focus after the user moves elsewhere while awaiting a page.
            state['hold_get'] = True
            with page.expect_request('**/api/feedback?**'):
                page.keyboard.press('Enter')
            page.locator('#feedback-tab').focus()
            pending, snapshot = state['held_get']
            state['held_get'] = None
            pending.fulfill(json=snapshot)
            expect(page.locator('#refresh-feedback')).to_be_enabled()
            expect(page.locator('#feedback-tab')).to_be_focused()
            checks.append('Keyboard pagination and reload retain focus when controls disable or disappear, preserve enabled controls and never pull focus back from elsewhere')

            reset()
            ack_only = [{**record, 'kept': False, 'ignore_until': int(time.time()) - 60}
                        for record in state['records'][:20]]
            state['first_page'], state['second_page'] = ack_only, [state['records'][20]]
            page.locator('#refresh-feedback').click()
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(0)
            expect(page.locator('#feedback-load-more')).to_be_visible()
            page.locator('#feedback-load-more').click()
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(1)
            checks.append('Acknowledged-only or expired-ignore filtered-empty page retains the next cursor and later active feedback remains reachable')

            reset()
            item = original_records[0]
            candidate = original_candidates[0]
            expect(current(candidate)).to_have_count(0)
            group(item).locator('.feedback-unkeep').click()
            expect(group(item)).to_have_count(1)
            expect(current(candidate)).to_have_count(0)
            assert puts()[-1] == {'region': REGION, 'finding_id': item['finding_id'], 'kept': False}
            saved = record_for(item['finding_id'])
            assert saved['acknowledged'] is True and saved['ignore_until'] > time.time() and saved['kept'] is False
            group(item).locator('.feedback-unignore').click()
            expect(group(item)).to_have_count(0)
            expect(current(candidate)).to_have_count(1)
            expect(current(candidate).locator('.feedback-ack')).to_have_text('Bỏ đã xem')
            assert puts()[-1] == {'region': REGION, 'finding_id': item['finding_id'], 'ignoreUntil': None}
            assert record_for(item['finding_id'])['acknowledged'] is True
            assert state['history'] == original_candidates
            page.locator('[data-page="history"]').click()
            page.locator('#history-list .history-open').click()
            expect(page.locator('#history-detail tbody tr')).to_have_count(len(original_candidates))
            assert page.locator('#history-detail .finding-feedback').count() == 0
            checks.append('Unkeep and cancel-ignore change only one flag; combined flags keep a finding hidden until both clear, then retained candidate returns with acknowledged and history intact')

            reset()
            item = original_records[24]
            page.locator('#feedback-load-more').click()
            expect(group(item)).to_have_count(1)
            group(item).locator('.feedback-unkeep').click()
            expect(group(item)).to_have_count(0)
            expect(page.locator('#status')).to_contain_text(re.compile('quét.*mới|quét lại', re.I))
            expect(page.locator('#status')).not_to_contain_text(re.compile('đã (khôi phục|hiện lại)', re.I))
            assert state['history'] == original_candidates
            checks.append('Legacy feedback without a retained candidate remains manageable and clear reports a new scan instead of claiming restoration')

            reset()
            item = original_records[0]
            for days in [1, 30]:
                selector = group(item).locator('.feedback-manage-days')
                assert selector.locator('option').evaluate_all('(items)=>items.map(item=>item.value)') == [str(value) for value in range(1, 31)]
                selector.select_option(str(days))
                before = time.time()
                group(item).locator('.feedback-extend').click()
                expect(group(item).locator('.feedback-extend')).to_be_enabled()
                body = puts()[-1]
                assert set(body) == {'region', 'finding_id', 'ignoreUntil'}
                until = datetime.fromisoformat(body['ignoreUntil'].replace('Z', '+00:00')).timestamp()
                assert abs(until - before - days * 86400) < 3
                assert record_for(item['finding_id'])['kept'] is True
                assert record_for(item['finding_id'])['acknowledged'] is True
            checks.append('Change-ignore-expiry uses UTC one-to-thirty-day boundaries without clearing kept or acknowledged')

            reset()
            item = original_records[1]
            state['hold_put'] = True
            with page.expect_request('**/api/feedback'):
                group(item).locator('.feedback-unignore').click()
            expect(group(item)).to_have_count(1)
            expect(group(item).locator('.feedback-unignore')).to_be_disabled()
            expect(group(item).locator('.feedback-manage-days')).to_be_disabled()
            expect(group(item).locator('.feedback-extend')).to_be_disabled()
            expect(group(item).locator('.feedback-status')).to_contain_text('Đang lưu')
            group(item).screenshot(path=str(OUT / 'management-pending-1440.png'))
            page.evaluate('refresh()')
            expect(group(item).locator('.feedback-unignore')).to_be_disabled()
            pending, body = state['held_put']
            state['held_put'] = None
            pending.fulfill(status=503, json={'error': 'Feedback update unavailable'})
            expect(group(item).locator('.feedback-unignore')).to_be_enabled()
            expect(group(item).locator('.feedback-status')).to_contain_text('Feedback update unavailable')
            group(item).screenshot(path=str(OUT / 'management-error-1440.png'))
            assert record_for(item['finding_id'])['ignore_until'] > time.time()
            group(item).locator('.feedback-unignore').click()
            expect(group(item)).to_have_count(0)
            expect(current(original_candidates[1])).to_have_count(1)
            checks.append('Pending management never updates optimistically, survives findings refresh, disables identity controls and retries a failed PUT')

            reset()
            item = original_records[1]
            state['findings_error'] = True
            count = len(puts())
            group(item).locator('.feedback-unignore').click()
            expect(group(item)).to_have_count(0)
            expect(page.locator('#status')).to_contain_text(re.compile('lưu|tải', re.I))
            assert len(puts()) == count + 1 and record_for(item['finding_id'])['ignore_until'] == 0
            state['findings_error'] = False
            page.evaluate('refresh()')
            expect(current(original_candidates[1])).to_have_count(1)
            assert len(puts()) == count + 1
            checks.append('Successful clear followed by failed findings reload stays saved and recovers without repeating PUT')

            for response_status in [200, 503]:
                reset()
                item = original_records[19]
                state['hold_get'] = True
                with page.expect_request('**/api/feedback?**'):
                    page.evaluate('''window.__managerGetDone=false;
                        void loadFeedback(true).catch(()=>{}).finally(()=>window.__managerGetDone=true);''')
                group(item).locator('.feedback-unkeep').click()
                expect(group(item)).to_have_count(0)
                pending, snapshot = state['held_get']
                state['held_get'] = None
                pending.fulfill(status=response_status, json=snapshot if response_status == 200 else
                                {'error': 'OLD_MANAGER_GET_MUST_NOT_APPEAR'})
                page.wait_for_function('window.__managerGetDone === true')
                expect(group(item)).to_have_count(0)
                expect(page.locator('#feedback-summary')).not_to_contain_text('OLD_MANAGER_GET_MUST_NOT_APPEAR')
                expect(page.locator('#status')).not_to_contain_text('OLD_MANAGER_GET_MUST_NOT_APPEAR')
            checks.append('Feedback GET success/error started before a successful clear cannot resurrect the old record or replace the new status')

            for response_status in [200, 503]:
                reset()
                item = original_records[1]
                page.evaluate('''()=>{window.__managerPutDone=false;
                    window.__realManagerSave=saveFindingFeedback;
                    saveFindingFeedback=(...args)=>window.__realManagerSave(...args)
                        .finally(()=>window.__managerPutDone=true);}''')
                state['hold_put'] = True
                with page.expect_request('**/api/feedback'):
                    group(item).locator('.feedback-unignore').click()
                page.evaluate('''async payload=>{await api('/connection','PUT',payload);await init();}''',
                              {'role_arn': ARN, 'regions': [REGION], 'service_groups': ['storage']})
                expect(page.locator('#feedback-list .feedback-record')).to_have_count(0)
                fresh = {**original_records[3], 'resource_id': 'vol-new-connection'}
                state['records'], state['first_page'], state['second_page'] = [fresh], [fresh], []
                page.evaluate('loadFeedback()')
                expect(page.locator('#feedback-list .feedback-record')).to_have_count(1)
                pending, body = state['held_put']
                state['held_put'] = None
                reply = {**item, 'ignore_until': 0} if response_status == 200 else {'error': 'OLD_MANAGER_PUT_MUST_NOT_APPEAR'}
                pending.fulfill(status=response_status, json=reply)
                page.wait_for_function('window.__managerPutDone === true')
                expect(group(fresh)).to_have_count(1)
                expect(group(item)).to_have_count(0)
                expect(page.locator('#status')).not_to_contain_text('OLD_MANAGER_PUT_MUST_NOT_APPEAR')
            checks.append('Old-connection management PUT success/error is discarded after reconnect and cannot change the new feedback scope')

            reset()
            state['hold_get'] = True
            with page.expect_request('**/api/feedback?**'):
                page.evaluate('''window.__managerScopeGetDone=false;
                    void loadFeedback(true).catch(()=>{}).finally(()=>window.__managerScopeGetDone=true);''')
            page.evaluate('''async payload=>{await api('/connection','PUT',payload);await init();}''',
                          {'role_arn': ARN, 'regions': [REGION], 'service_groups': ['storage']})
            fresh = {**original_records[3], 'resource_id': 'vol-new-feedback-scope'}
            state['records'], state['first_page'], state['second_page'] = [fresh], [fresh], []
            page.evaluate('loadFeedback()')
            expect(group(fresh)).to_have_count(1)
            pending, snapshot = state['held_get']
            state['held_get'] = None
            pending.fulfill(json=snapshot)
            page.wait_for_function('window.__managerScopeGetDone === true')
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(1)
            expect(group(fresh)).to_have_count(1)
            checks.append('Late feedback pagination from a previous connection cannot append rows or restore an old cursor')

            reset()
            # A second tab may clear feedback between the two independent GET snapshots.
            item = original_records[0]
            snapshot = copy.deepcopy(item)
            record_for(item['finding_id']).update(kept=False, ignore_until=0)
            state['first_page'], state['second_page'] = [snapshot], []
            page.evaluate('refresh()')
            page.locator('#refresh-feedback').click()
            expect(group(item)).to_have_count(1)
            page.locator('#results-tab').click()
            expect(current(original_candidates[0])).to_have_count(1)
            before_errors = len(errors)
            current_row = current(original_candidates[0])
            current_row.locator('.actions-summary').click()
            current_row.locator('.feedback-ignore').click()
            expect(page.locator('#ignore-dialog')).to_be_visible()
            page.locator('#ignore-days').fill('30')
            page.locator('#ignore-cancel').click()
            expect(page.locator('#ignore-dialog')).not_to_be_visible()
            page.locator('#feedback-tab').click()
            assert not puts() or puts()[-1].get('finding_id') != item['finding_id'] or 'ignoreUntil' not in puts()[-1]
            expect(group(item).locator('.feedback-manage-days')).to_have_value('7')
            assert len(errors) == before_errors, errors[before_errors:]
            checks.append('Independent current and management snapshots of one identity keep their expiry selectors safe and separate')

            reset()
            long_record = state['records'][0]
            long_record['resource_id'] = 'vol-<img src=x onerror=window.__managerXss=1>-' + 'x' * 800
            long_record['rule_id'] = '<script>window.__managerXss=2</script>'
            page.locator('#refresh-feedback').click()
            expect(group(long_record)).to_contain_text(long_record['resource_id'])
            assert page.locator('#feedback-list img,#feedback-list script,#feedback-list svg').count() == 0
            assert not page.evaluate('window.__managerXss || 0')
            # Keep screenshots useful: show three active records and include the legacy fallback.
            state['first_page'], state['second_page'] = state['records'][:3], []
            page.locator('#refresh-feedback').click()
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(3)
            for width in [320, 390, 768, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.locator('#feedback-list').scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                page.screenshot(path=str(OUT / f'management-{width}.png'), full_page=True)
            group(long_record).locator('.feedback-unkeep').focus()
            expect(group(long_record).locator('.feedback-unkeep')).to_be_focused()
            page.keyboard.press('Tab')
            expect(group(long_record).locator('.feedback-unignore')).to_be_focused()
            page.keyboard.press('Tab')
            expect(group(long_record).locator('.feedback-manage-days')).to_be_focused()
            checks.append('Metadata and long HTML-like IDs remain safe text; manager fits 320/390/768/1440 and keyboard follows management controls')

            state['unauthorized'] = True
            group(long_record).locator('.feedback-unkeep').click()
            expect(page.locator('#app')).to_be_hidden()
            assert not errors, errors
            assert not state['fixture_errors'], state['fixture_errors']
            checks.append('Expired-session management returns to login without a false successful update')
            output = {'environment': 'LOCAL HTTP/API FIXTURES - NOT AWS', 'checks': checks,
                      'page_errors': errors, 'fixture_errors': state['fixture_errors'],
                      'request_count': len(state['requests']), 'put_count': len(puts()),
                      'screenshots': 6, 'widths': [320, 390, 768, 1440]}
            (OUT / 'acceptance-results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            browser.close()
            print('Feedback management UI PASS: ' + '; '.join(checks))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
