"""History pagination and scan-detail acceptance using local HTTP/API fixtures.

This suite never calls AWS. CHROMIUM_EXECUTABLE may select an installed browser;
UI_QA_DIR selects the ignored directory for screenshots and acceptance evidence.
"""
import copy
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import threading
from urllib.parse import parse_qs, unquote, urlsplit
import uuid

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rules import config
from ui_finding_details import fixture_findings

OUT = Path(os.environ.get('UI_QA_DIR', ROOT / '.preflight/ui-history-management'))
REGIONS = ['ap-southeast-1', 'ap-southeast-2', 'us-east-1']
ARN = 'arn:aws:iam::123456789012:role/GuardianReadRole-fixture'
TOKEN = 'opaque history cursor +/?= page:2'
PROFILE = {
    'account_id': '123456789012', 'role_arn': ARN, 'regions': REGIONS,
    'connection_version': 'history-v1', 'external_id': 'FIXTURE-ONLY-EXTERNAL-ID',
    'api_principal': 'arn:aws:iam::123456789012:role/FixtureApiPrincipal',
    'scan_principal': 'arn:aws:iam::123456789012:role/FixtureScanPrincipal',
    'service_groups': ['compute', 'storage', 'database', 'network'],
    'settings': config({}), 'notifications': {'enabled': False}, 'email_available': False,
}


def fixtures():
    items, rows = fixture_findings(), []
    for index in range(25):
        rows.append({
            'scan_id': str(uuid.UUID(int=index + 1, version=4)), 'region': REGIONS[0],
            'status': 'SUCCEEDED', 'trigger': 'manual' if index % 2 == 0 else 'scheduled',
            'started_at': 1793448000 - index * 3600, 'completed_at': 1793448060 - index * 3600,
            'counts': {'EBS': 1}, 'findings': copy.deepcopy(items[:1]),
        })
    rows[0]['findings'] = copy.deepcopy(items)
    rows[0]['counts'] = {item['type']: 1 for item in items}
    # Same scan in three regions must survive row dedup; two are on the next page.
    for index, region in [(20, REGIONS[1]), (21, REGIONS[2])]:
        rows[index].update(scan_id=rows[0]['scan_id'], region=region, trigger='manual',
                           started_at=rows[0]['started_at'], completed_at=rows[0]['completed_at'])
        for item in rows[index]['findings']:
            item['region'] = region
    rows[20].update(status='PARTIAL', errors=[{'type': 'RDS', 'code': 'ACCESS_DENIED'}])
    rows[21].update(status='TIMED_OUT', error='Scan did not complete within 15 minutes. Check Lambda failure queue and retry.',
                    error_code='JOB_DEADLINE_EXCEEDED', request_id='fixture-worker-request')
    rows[23].pop('trigger')
    rows[23].pop('started_at')
    rows[23].pop('completed_at')
    rows[24].update(status='FAILED', error='Failure <img src=x onerror=window.__historyXss=1> ' + 'x' * 500,
                    errors=[{'type': '<script>window.__historyXss=2</script>', 'code': 'ACCESS_DENIED'}])
    return rows


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'web')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_address[1])
    original = fixtures()
    state = {
        'profile': copy.deepcopy(PROFILE), 'history': copy.deepcopy(original), 'requests': [],
        'page_error': False, 'detail_error': False, 'first_error': False,
        'hold_history': False, 'held_history': None, 'hold_scan': False, 'held_scan': None,
        'kept_id': None,
        'unauthorized': False, 'kept': False, 'fixture_errors': [],
    }
    checks, errors = [], []

    def route_api(route):
        request = route.request
        parsed = urlsplit(request.url)
        path, query = parsed.path.removeprefix('/api'), parse_qs(parsed.query)
        body = request.post_data_json if request.post_data else None
        state['requests'].append({'method': request.method, 'path': path, 'query': copy.deepcopy(query),
                                  'body': copy.deepcopy(body)})
        status, reply = 200, {}
        try:
            if state['unauthorized']:
                status, reply = 401, {'error': 'Access token required'}
            elif path == '/me':
                reply = state['profile']
            elif path == '/findings':
                current = copy.deepcopy(original[0])
                if state['kept']:
                    current['findings'] = [item for item in current['findings']
                                           if item['finding_id'] != state['kept_id']]
                reply = {'results': [current]}
            elif path == '/history':
                assert query.get('limit') == ['20'], query
                assert set(query) <= {'limit', 'next_token'}, query
                token = query.get('next_token', [None])[0]
                assert token in [None, TOKEN], token
                rows = state['history'][:20] if token is None else state['history'][19:]
                reply = {'results': copy.deepcopy(rows),
                         'next_token': TOKEN if token is None and len(state['history']) > 20 else None}
                if state['hold_history']:
                    assert state['held_history'] is None
                    state['held_history'] = (route, copy.deepcopy(reply))
                    state['hold_history'] = False
                    return
                if state['first_error'] or (state['page_error'] and token):
                    status, reply = 503, {'error': 'History temporarily unavailable'}
            elif path.startswith('/scans/'):
                scan_id = unquote(path.rsplit('/', 1)[-1])
                rows = [row for row in state['history'] if row.get('scan_id') == scan_id]
                reply = {'scan_id': scan_id, 'results': copy.deepcopy(rows)}
                if state['hold_scan']:
                    assert state['held_scan'] is None
                    state['held_scan'] = (route, copy.deepcopy(reply))
                    state['hold_scan'] = False
                    return
                if state['detail_error']:
                    status, reply = 503, {'error': 'Scan detail temporarily unavailable'}
            elif path == '/feedback' and request.method == 'GET':
                reply = {'results': [], 'next_token': None}
            elif path == '/feedback' and request.method == 'PUT':
                assert set(body) == {'region', 'finding_id', 'kept'}, body
                assert body['kept'] is True
                state['kept'] = True
                state['kept_id'] = body['finding_id']
                reply = {**body, 'updated_at': 1793449000}
            else:
                raise AssertionError('Unexpected fixture request: ' + request.method + ' ' + path)
        except Exception as error:
            state['fixture_errors'].append(str(error))
            status, reply = 500, {'error': 'Fixture rejected request: ' + str(error)}
        route.fulfill(status=status, content_type='application/json', body=json.dumps(reply))

    def history_gets():
        return [entry for entry in state['requests'] if entry['method'] == 'GET' and entry['path'] == '/history']

    try:
        with sync_playwright() as playwright:
            launch = {'headless': True}
            executable = os.environ.get('CHROMIUM_EXECUTABLE') or os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH')
            if executable:
                launch['executable_path'] = executable
            browser = playwright.chromium.launch(**launch)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            context.add_init_script("sessionStorage.setItem('crg-token','demo-local-only')")
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/config.json', lambda route: route.fulfill(json={'api': '/api', 'demo': True}))
            page.route('**/api/**', route_api)

            def row_button(row):
                key = json.dumps([row['scan_id'], row['region']], separators=(',', ':'))
                return page.locator('#history-list .history-open[data-history-key=' + json.dumps(key) + ']')

            def reset():
                assert state['held_history'] is None and state['held_scan'] is None
                state.update(profile=copy.deepcopy(PROFILE), history=copy.deepcopy(original),
                             page_error=False, detail_error=False, first_error=False,
                             hold_history=False, hold_scan=False, unauthorized=False, kept=False)
                page.goto(base + '/#history')
                page.reload()
                expect(page.locator('#history-list .history-open')).to_have_count(20)

            def release(key, status=200):
                route, reply = state[key]
                state[key] = None
                route.fulfill(status=status, json=reply if status == 200 else {'error': 'Delayed old request failed'})
                page.wait_for_timeout(100)

            page.goto(base + '/#history')
            expect(page.locator('#history-list .history-open')).to_have_count(20)
            expect(page.locator('#history-load-more')).to_be_visible()
            row_button(original[0]).click()
            expect(page.locator('#history-detail .history-region')).to_have_count(3)
            detail = page.locator('#history-detail')
            expect(detail).to_contain_text(original[0]['scan_id'])
            expect(detail).to_contain_text('Thủ công')
            for region in REGIONS:
                expect(detail).to_contain_text(region)
            for text in ['RDS', 'ACCESS_DENIED', 'JOB_DEADLINE_EXCEEDED', 'fixture-worker-request']:
                expect(detail).to_contain_text(text)
            for field in ['started_at', 'completed_at']:
                expected_time = page.evaluate("epoch=>new Date(epoch*1000).toLocaleString('vi-VN')", original[0][field])
                expect(detail.locator('.history-region').first.locator('[data-field="' + field + '"] dd')).to_have_text(expected_time)
            assert page.locator('#history-detail .finding-feedback').count() == 0
            checks.append('A selected scan loads every region even when other regions are beyond the first history page; trigger, timing, status and regional errors remain read-only')

            for item in original[0]['findings']:
                page.locator('#history-detail .history-region').first.locator('tbody tr').filter(
                    has=page.locator('code').filter(has_text=item['resource_id'])).locator('.finding-open').click()
                expect(page.locator('#finding-dialog')).to_be_visible()
                expect(page.locator('#finding-detail-content [data-field="type"] dd')).to_have_text(item['type'])
                expect(page.locator('#finding-detail-content [data-field="first_seen_at"] dd')).not_to_have_text('Chưa có dữ liệu')
                if item['type'] == 'EC2':
                    expect(page.locator('#finding-detail-content [data-field="cpu_p95"] dd')).to_have_text(re.compile(r'^0(?:[\s%]|$)'))
                page.locator('#close-finding-detail').click()
            checks.append('All nine finding schemas use the shared historical evidence dialog, preserving true zero and observation timestamps')

            state['page_error'] = True
            page.locator('#history-load-more').click()
            expect(page.locator('#history-summary')).to_contain_text(re.compile('lỗi|không|thử', re.I))
            expect(page.locator('#history-list .history-open')).to_have_count(20)
            expect(detail.locator('.history-region')).to_have_count(3)
            page.screenshot(path=str(OUT / 'history-page-error-1440.png'), full_page=True)
            state['page_error'] = False
            page.locator('#history-load-more').focus()
            page.keyboard.press('Enter')
            expect(page.locator('#history-list .history-open')).to_have_count(25)
            expect(page.locator('#history-load-more')).to_be_hidden()
            expect(page.locator('#history-summary')).to_be_focused()
            identities = page.locator('#history-list .history-open').evaluate_all('(rows)=>rows.map(row=>row.dataset.historyKey)')
            assert len(set(identities)) == 25
            assert row_button(original[20]).count() == row_button(original[21]).count() == 1
            checks.append('Opaque next_token survives page-error retry, loaded rows and detail remain intact, duplicates merge by scan and region, and the last-page keyboard focus stays meaningful')

            page.locator('#refresh-history').focus()
            page.keyboard.press('Enter')
            expect(page.locator('#history-list .history-open')).to_have_count(20)
            assert 'next_token' not in history_gets()[-1]['query']
            expect(page.locator('#history-load-more')).to_be_visible()
            checks.append('Reload resets the opaque cursor and replaces the accumulated history with the newest first page')

            state['detail_error'] = True
            row_button(original[1]).click()
            expect(page.locator('.history-detail-retry')).to_be_visible()
            state['detail_error'] = False
            state['hold_scan'] = True
            page.locator('.history-detail-retry').focus()
            page.keyboard.press('Enter')
            page.wait_for_timeout(100)
            assert state['held_scan'] is not None
            expect(detail).to_be_focused()
            release('held_scan')
            expect(detail.locator('.history-region')).to_have_count(1)
            expect(detail).to_be_focused()
            expect(detail).to_contain_text('Theo lịch')
            expect(detail).to_contain_text(original[1]['scan_id'])
            state['detail_error'] = True
            row_button(original[1]).click()
            expect(page.locator('.history-detail-retry')).to_be_visible()
            state['detail_error'] = False
            state['hold_scan'] = True
            page.locator('.history-detail-retry').focus()
            page.keyboard.press('Enter')
            page.wait_for_timeout(100)
            assert state['held_scan'] is not None
            page.locator('#refresh-history').focus()
            release('held_scan')
            expect(page.locator('#refresh-history')).to_be_focused()
            checks.append('A failed scan-detail request retries without discarding history; pending retry preserves meaningful keyboard focus and completion respects user-moved focus')

            state['hold_scan'] = True
            row_button(original[0]).click()
            page.wait_for_function('document.querySelector(".history-detail-loading") !== null')
            row_button(original[1]).click()
            expect(detail).to_contain_text(original[1]['scan_id'])
            expect(detail.locator('.history-region')).to_have_count(1)
            page.locator('#refresh-history').focus()
            release('held_scan')
            expect(detail).to_contain_text(original[1]['scan_id'])
            expect(detail.locator('.history-region')).to_have_count(1)
            expect(page.locator('#refresh-history')).to_be_focused()
            checks.append('A late response from an earlier scan selection cannot replace the newer detail or steal focus')

            reset()
            state['hold_history'] = True
            page.locator('#history-load-more').click()
            page.wait_for_timeout(100)
            assert state['held_history'] is not None
            state['profile']['connection_version'] = 'history-v2'
            fresh = copy.deepcopy(original[2])
            fresh.update(scan_id=str(uuid.UUID(int=999, version=4)), region=REGIONS[1])
            state['history'] = [fresh]
            page.evaluate('init()')
            expect(page.locator('#history-list .history-open')).to_have_count(1)
            release('held_history')
            expect(row_button(fresh)).to_have_count(1)
            expect(page.locator('#history-list .history-open')).to_have_count(1)
            expect(page.locator('#history-load-more')).to_be_hidden()
            checks.append('A history page from the previous connection cannot append rows or restore its cursor after reinitialization')

            reset()
            state['hold_scan'] = True
            row_button(original[0]).click()
            page.wait_for_timeout(100)
            assert state['held_scan'] is not None
            state['profile']['connection_version'] = 'history-v3'
            state['history'] = []
            page.evaluate('init()')
            expect(page.locator('#history-list .history-open')).to_have_count(0)
            release('held_scan', 503)
            expect(detail).to_be_empty()
            expect(page.locator('.history-detail-retry')).to_have_count(0)
            checks.append('A late failure from an obsolete connection cannot revive scan detail or its retry control')

            reset()
            state['hold_scan'] = True
            row_button(original[0]).click()
            page.wait_for_timeout(100)
            assert state['held_scan'] is not None
            page.locator('#refresh-history').click()
            expect(detail).to_be_empty()
            release('held_scan')
            expect(detail).to_be_empty()
            checks.append('Reloading history invalidates an in-flight detail response instead of reopening the old selection')

            reset()
            before = copy.deepcopy(state['history'])
            page.locator('[data-page="findings"]').click()
            page.wait_for_timeout(300)
            before_keep = page.locator('#findings-list .feedback-keep').count()
            page.locator('#findings-list .actions-summary').first.click()
            page.locator('#findings-list .feedback-keep').first.click()
            expect(page.locator('#findings-list .feedback-keep')).to_have_count(before_keep - 1)
            page.locator('[data-page="history"]').click()
            row_button(original[0]).click()
            expect(detail.locator('.history-region')).to_have_count(3)
            expect(detail.locator('.history-region').first.locator('.finding-open')).to_have_count(9)
            assert state['history'] == before
            assert not any(entry['method'] != 'GET' and entry['path'].startswith(('/history', '/scans/'))
                           for entry in state['requests'])
            checks.append('Current finding feedback hides current candidates while history and its evidence snapshot remain unchanged')

            reset()
            page.locator('#history-load-more').click()
            expect(page.locator('#history-list .history-open')).to_have_count(25)
            row_button(original[23]).click()
            expect(detail).to_contain_text('Chưa có dữ liệu')
            legacy = copy.deepcopy(original[23])
            legacy.pop('scan_id')
            state['history'] = [legacy]
            page.locator('#refresh-history').click()
            expect(page.locator('#history-list .history-open')).to_have_count(1)
            scans_before = sum(entry['path'].startswith('/scans/') for entry in state['requests'])
            page.locator('#history-list .history-open').click()
            expect(detail.locator('.history-region')).to_have_count(1)
            expect(detail).to_contain_text('Dữ liệu cũ thiếu Scan ID')
            assert scans_before == sum(entry['path'].startswith('/scans/') for entry in state['requests'])
            checks.append('A legacy record without scan ID displays its saved region snapshot without an invalid scan-status request')

            # Keep screenshot artifacts readable while the full pagination scenario stays covered above.
            state['history'] = [copy.deepcopy(original[index]) for index in [0, 23, 24]]
            page.locator('#refresh-history').click()
            expect(page.locator('#history-list .history-open')).to_have_count(3)
            row_button(original[24]).click()
            expect(detail).to_contain_text(original[24]['error'])
            assert page.locator('#history-list img,#history-list script,#history-detail img,#history-detail script').count() == 0
            assert not page.evaluate('window.__historyXss || 0')
            for width in [320, 390, 768, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                detail.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                page.screenshot(path=str(OUT / f'history-{width}.png'), full_page=True)
            checks.append('Legacy missing metadata and long HTML-like errors render as safe text without horizontal overflow at 320/390/768/1440')

            reset()
            state['hold_history'] = True
            page.locator('#refresh-history').focus()
            page.keyboard.press('Enter')
            page.wait_for_timeout(100)
            assert state['held_history'] is not None
            expect(page.locator('#history-summary')).to_be_focused()
            page.locator('[data-page="findings"]').focus()
            release('held_history')
            expect(page.locator('[data-page="findings"]')).to_be_focused()
            checks.append('Reload moves disabled-control focus to the persistent summary, and completion preserves focus moved by the user')

            reset()
            state['first_error'] = True
            page.locator('#refresh-history').click()
            expect(page.locator('#history-summary')).to_contain_text(re.compile('lỗi|không|thử', re.I))
            expect(page.locator('#history-list .history-open')).to_have_count(20)
            state['first_error'] = False
            page.locator('#refresh-history').click()
            expect(page.locator('#history-list .history-open')).to_have_count(20)
            expect(page.locator('#history-summary')).not_to_have_class(re.compile('error'))
            checks.append('A first-page refresh error retains previous rows and a subsequent retry recovers')

            state['unauthorized'] = True
            row_button(original[0]).click()
            expect(page.locator('#app')).to_be_hidden()
            assert not errors, errors
            assert not state['fixture_errors'], state['fixture_errors']
            checks.append('An expired session during detail lookup returns to login without claiming a successful scan load')
            output = {'environment': 'LOCAL HTTP/API FIXTURES - NOT AWS', 'checks': checks,
                      'page_errors': errors, 'fixture_errors': state['fixture_errors'],
                      'request_count': len(state['requests']), 'history_gets': len(history_gets()),
                      'scan_gets': sum(entry['path'].startswith('/scans/') for entry in state['requests']),
                      'screenshots': 5, 'widths': [320, 390, 768, 1440]}
            (OUT / 'acceptance-results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            browser.close()
            print('History management UI PASS: ' + '; '.join(checks))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
