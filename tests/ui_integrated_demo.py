"""Browser acceptance against the real local demo handler, never AWS.

Main API responses use demo.py over HTTP. The browser only intercepts deliberate
503/pending faults; pagination fixtures are inserted into this process's RAM.
"""
import copy
from datetime import datetime
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import urllib.request
import uuid

from playwright.sync_api import expect, sync_playwright
from playwright.sync_api import Error as PlaywrightError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import demo

OUT = Path(os.environ.get('UI_QA_DIR', ROOT / '.preflight/duc-plan-09/ui-integrated'))
KINDS = {'EC2', 'EBS', 'EIP', 'SNAPSHOT', 'S3_MULTIPART', 'RDS', 'NAT_GATEWAY', 'ALB', 'NLB'}
REGIONS = ['ap-southeast-1', 'ap-southeast-2', 'us-east-1']


def utc_label(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S UTC')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), demo.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_address[1])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    checks, errors, requests = [], [], []
    faults = {'hold_put': False, 'held_put': None, 'fail_put': False, 'fail_history_page': False}
    source_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                     for name in ['demo.py', 'src/rules.py', 'web/app.js', 'web/index.html', 'web/styles.css',
                                  'tests/ui_integrated_demo.py', 'tests/ui_smoke.py']}

    def api(path, method='GET', data=None):
        request = urllib.request.Request(base + '/api' + path, method=method,
                                         headers={'Authorization': 'Bearer demo-local-only',
                                                  'Content-Type': 'application/json'},
                                         data=json.dumps(data).encode() if data is not None else None)
        with opener.open(request, timeout=5) as response:
            return json.load(response)

    def browser_route(route):
        parsed = urlsplit(route.request.url)
        path, query = parsed.path.removeprefix('/api'), parse_qs(parsed.query)
        requests.append({'method': route.request.method, 'path': path, 'query': query})
        if path == '/feedback' and route.request.method == 'PUT':
            if faults['hold_put']:
                faults['hold_put'], faults['held_put'] = False, route
                return
            if faults['fail_put']:
                faults['fail_put'] = False
                return route.fulfill(status=503, json={'error': 'Integration test: retry feedback'})
        if path == '/history' and query.get('next_token') and faults['fail_history_page']:
            faults['fail_history_page'] = False
            return route.fulfill(status=503, json={'error': 'Integration test: retry history page'})
        route.continue_()

    try:
        with sync_playwright() as playwright:
            launch = {'headless': True}
            if os.environ.get('CHROMIUM_EXECUTABLE'):
                launch['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
            browser = playwright.chromium.launch(**launch)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/**', browser_route)
            page.goto(base)
            page.locator('#start').click()
            expect(page.locator('#app')).to_be_visible()
            expect(page.locator('#total')).to_have_text('31')
            expect(page.locator('#review')).to_have_text('8')
            first_result = api('/findings')['results'][0]
            original = copy.deepcopy(first_result['findings'])
            original_scan = first_result['scan_id']
            assert {item['type'] for item in original} == KINDS
            assert len(original) == 10
            assert {item['level'] for item in original} == {'REVIEW', 'OBSERVING', 'INSUFFICIENT_DATA'}
            for item in original:
                for field in ['account_id', 'region', 'finding_id', 'rule_id', 'recommendation',
                              'first_seen_at', 'last_seen_at', 'evaluated_at']:
                    assert item.get(field), (item['type'], field)
                assert datetime.fromisoformat(item['first_seen_at'].replace('Z', '+00:00')) <= datetime.fromisoformat(item['last_seen_at'].replace('Z', '+00:00'))
            checks.append('Real demo HTTP returns nine resource types, ten findings, complete metadata, UTC observation stamps and all three finding levels')

            def navigate(name):
                page.locator('[data-page="' + name + '"]').click()
                expect(page.locator('#page-' + name)).to_be_visible()

            def row(item):
                target = page.locator('#findings-list tbody tr').filter(
                    has=page.locator('.finding-open[data-finding-id="' + item['finding_id'] + '"]'))
                if target.count() == 0:
                    return target
                try:
                    group = target.locator('xpath=ancestor::section[contains(@class,"finding-group")]')
                    toggle = group.locator('.group-toggle')
                    if toggle.count() and toggle.first.get_attribute('aria-expanded') == 'false':
                        toggle.first.click()
                except PlaywrightError:
                    pass
                return target

            def open_menu(item):
                target = row(item)
                if target.count() == 0:
                    return target
                try:
                    menu = target.locator('details.actions-menu')
                    if menu.count() and not menu.first.evaluate('(el)=>el.open'):
                        target.locator('.actions-summary').first.click()
                except PlaywrightError:
                    pass
                return target

            def manager(item):
                identity = json.dumps([item['region'], item['finding_id']], separators=(',', ':'))
                return page.locator('.feedback-record[data-feedback-key=' + json.dumps(identity) + ']')

            def value(key):
                return page.locator('#finding-detail-content [data-field="' + key + '"] dd')

            navigate('findings')
            expect(page.locator('#findings-list tbody tr')).to_have_count(10)
            nine = {item['type']: item for item in reversed(original)}
            current_evidence = {}
            for kind, item in nine.items():
                row(item).locator('.finding-open').click()
                expect(page.locator('#finding-dialog')).to_be_visible()
                expect(value('type')).to_have_text(kind)
                expect(value('account_id')).to_have_text(item['account_id'])
                expect(value('rule_id')).to_have_text(item['rule_id'])
                expect(value('first_seen_at')).to_have_text(utc_label(item['first_seen_at']))
                expect(value('last_seen_at')).to_have_text(utc_label(item['last_seen_at']))
                current_evidence[item['finding_id']] = page.locator('#finding-detail-content').inner_text()
                page.keyboard.press('Escape')
                expect(row(item).locator('.finding-open')).to_be_focused()
            zero = next((item, key) for item in original for key, data in item['evidence'].items()
                        if type(data) in (int, float) and data == 0 and key in ['cpu_p95', 'nat_mib_hour', 'requests_hour', 'new_flows_hour'])
            row(zero[0]).locator('.finding-open').click()
            expect(value(zero[1])).to_have_text(re.compile(r'^0(?:\s|$)'))
            page.keyboard.press('Escape')
            checks.append('All nine current findings open the shared evidence dialog; true zero and exact first/last stamps survive rendering, Escape restores keyboard focus')

            page.locator('#filter-group').select_option('network')
            page.locator('#filter-type').select_option('NAT_GATEWAY')
            page.locator('#filter-region').select_option(REGIONS[0])
            page.locator('#filter-level').select_option('REVIEW')
            page.locator('#filter-acknowledged').select_option('unacknowledged')
            page.locator('#search').fill(nine['NAT_GATEWAY']['resource_id'])
            expect(page.locator('#findings-list tbody tr')).to_have_count(1)
            page.locator('#filter-group').select_option('storage')
            expect(page.locator('#findings-list tbody tr')).to_have_count(0)
            for name in ['group', 'type', 'region', 'level', 'acknowledged']:
                page.locator('#filter-' + name).select_option('')
            page.locator('#search').fill('')
            checks.append('Six filters combine with AND against real demo results, including a contradictory empty combination')

            target = nine['EC2']
            faults['hold_put'] = True
            open_menu(target).locator('.feedback-ack').focus()
            page.keyboard.press('Enter')
            expect(row(target).locator('.feedback-ack')).to_be_disabled()
            assert not api('/feedback')['results']
            assert faults['held_put'] is not None
            faults['held_put'].continue_()
            faults['held_put'] = None
            expect(row(target).locator('.feedback-ack')).to_have_text('Bỏ đã xem')
            page.reload()
            expect(row(target).locator('.feedback-ack')).to_have_text('Bỏ đã xem')
            expect(page.locator('#findings-list tbody tr')).to_have_count(10)
            faults['fail_put'] = True
            open_menu(target).locator('.feedback-ack').click()
            expect(row(target).locator('.feedback-status')).to_contain_text('Chưa lưu được')
            assert api('/feedback')['results'][0]['acknowledged'] is True
            open_menu(target).locator('.feedback-ack').click()
            expect(row(target).locator('.feedback-ack')).to_have_text('Đánh dấu đã xem')
            checks.append('Acknowledged persists across refresh and remains visible; pending has no optimistic write, a 503 leaves the stored flag intact and retry reaches the real handler')

            open_menu(target).locator('.feedback-ack').click()
            expect(row(target).locator('.feedback-ack')).to_have_text('Bỏ đã xem')
            open_menu(target).locator('.feedback-keep').click()
            expect(row(target)).to_have_count(0)
            expect(manager(target)).to_be_visible()
            manager(target).locator('.feedback-unkeep').click()
            expect(row(target).locator('.feedback-ack')).to_have_text('Bỏ đã xem')
            for days in [1, 30]:
                open_menu(target).locator('.feedback-ignore').click()
                expect(page.locator('#ignore-dialog')).to_be_visible()
                page.locator('#ignore-days').fill(str(days))
                before = time.time()
                page.locator('#ignore-confirm').click()
                expect(page.locator('#ignore-dialog')).not_to_be_visible()
                expect(row(target)).to_have_count(0)
                expect(manager(target)).to_be_visible()
                saved = next(item for item in api('/feedback')['results'] if item['finding_id'] == target['finding_id'])
                assert before + int(days) * 86400 - 2 <= saved['ignore_until'] <= time.time() + int(days) * 86400 + 2
                assert saved['acknowledged'] is True and saved['kept'] is False
                manager(target).locator('.feedback-unignore').click()
                expect(row(target).locator('.feedback-ack')).to_have_text('Bỏ đã xem')
            checks.append('Keep/unkeep and one/thirty-day ignore/cancel work through real PUT and GET; clearing one flag preserves acknowledged and restores the retained candidate')

            navigate('overview')
            page.locator('#scan').click()
            expect(page.locator('#scan')).to_be_disabled()
            expect(page.locator('#scan-summary')).to_contain_text('Đang quét')
            expect(page.locator('#scan-summary')).to_contain_text('Hoàn tất', timeout=15000)
            fresh = api('/findings')['results'][0]
            assert fresh['scan_id'] != original_scan
            for item in fresh['findings']:
                old = next(old for old in original if old['finding_id'] == item['finding_id'])
                assert item['first_seen_at'] == old['first_seen_at']
                assert item['last_seen_at'] > old['last_seen_at']
            history = api('/scans/' + original_scan)['results'][0]
            assert history['findings'] == original
            navigate('history')
            page.locator('#history-list .history-open').last.click()
            expect(page.locator('#history-detail .history-region')).to_have_count(1)
            historical_button = page.locator('#history-detail .finding-open[data-finding-id="' + target['finding_id'] + '"]')
            historical_button.click()
            assert page.locator('#finding-detail-content').inner_text() == current_evidence[target['finding_id']]
            expect(page.locator('#finding-detail-context')).to_contain_text('Snapshot lịch sử')
            page.keyboard.press('Escape')
            assert page.locator('#history-detail .finding-feedback').count() == 0
            checks.append('A real queued/running/completed scan advances last_seen while retaining first_seen; saved history stays unchanged after feedback and uses the same read-only evidence renderer')

            navigate('settings')
            assert page.locator('#settings-fields input').count() == 40
            page.locator('#window_hours').fill('168')
            page.locator('#save-settings').click()
            expect(page.locator('#status')).to_contain_text('Đã lưu ngưỡng')
            page.reload()
            expect(page.locator('#window_hours')).to_have_value('168')
            expect(page.locator('#email-enabled')).to_be_disabled()
            expect(page.locator('#email-enabled')).not_to_be_checked()
            expect(page.locator('#save-email')).to_be_disabled()
            checks.append('All eleven setting fields exist, the 168-hour window survives reload and SES controls remain off')

            navigate('connection')
            for region in REGIONS[1:]:
                page.locator('#region-options input[value="' + region + '"]').check()
            assert page.locator('#service-group-options input:checked').count() == 4
            old_version = api('/me')['connection_version']
            page.locator('#connect').click()
            expect(page.locator('#connection-feedback')).to_contain_text('Tiếp tục bước 3')
            assert api('/me')['connection_version'] != old_version
            assert api('/findings')['results'] == [] and api('/history')['results'] == [] and api('/feedback')['results'] == []
            navigate('overview')
            page.locator('#scan').click()
            expect(page.locator('#scan-summary')).to_contain_text('Hoàn tất', timeout=15000)
            three = api('/findings')['results']
            assert len(three) == 3
            assert len({item['finding_id'] for record in three for item in record['findings']}) == 30
            new_target = next(item for item in three[0]['findings'] if item['resource_id'] == target['resource_id'])
            assert new_target['first_seen_at'] > target['first_seen_at']
            assert not new_target.get('acknowledged')
            checks.append('Reconnect clears feedback/results/history and starts a fresh observation namespace; a real three-region scan yields thirty region-scoped finding identities')

            # Deliberate local RAM fixtures exercise actual server pagination,
            # without adding any fixture-only endpoint to the demo product.
            with demo.LOCK:
                demo.HISTORY = []
                for number in range(15):
                    scan = str(uuid.uuid4())
                    for template in three:
                        record = copy.deepcopy(template)
                        record.update(scan_id=scan, started_at=int(time.time()) - number * 3600,
                                      completed_at=int(time.time()) - number * 3600 + 1)
                        demo.HISTORY.append(record)
                demo.FEEDBACK = {}
                for number in range(45):
                    ident = format(number + 1000, '064x')
                    demo.FEEDBACK[ident] = {'finding_id': ident, 'region': REGIONS[number % 3],
                                            'connection_version': demo.PROFILE['connection_version'],
                                            'kept': True, 'acknowledged': number % 2 == 0,
                                            'resource_id': 'vol-integration-' + str(number), 'type': 'EBS',
                                            'account_id': demo.PROFILE['account_id'], 'rule_id': 'EBS_UNATTACHED'}
                demo.FEEDBACK[format(1000, '064x')].pop('resource_id')
                demo.FEEDBACK[format(1001, '064x')]['resource_id'] = '<script>window.__demoXss=1</script>' + 'x' * 250
            navigate('history')
            expect(page.locator('#history-list .history-open')).to_have_count(20)
            page.locator('#history-list .history-open').nth(19).click()
            expect(page.locator('#history-detail .history-region')).to_have_count(3)
            faults['fail_history_page'] = True
            page.locator('#history-load-more').click()
            expect(page.locator('#history-summary')).to_contain_text('thử lại')
            expect(page.locator('#history-list .history-open')).to_have_count(20)
            expect(page.locator('#history-detail .history-region')).to_have_count(3)
            page.locator('#history-load-more').click()
            expect(page.locator('#history-list .history-open')).to_have_count(40)
            page.locator('#history-load-more').focus()
            page.keyboard.press('Enter')
            expect(page.locator('#history-list .history-open')).to_have_count(45)
            expect(page.locator('#history-load-more')).to_be_hidden()
            expect(page.locator('#history-summary')).to_be_focused()
            page.locator('#refresh-history').click()
            expect(page.locator('#history-list .history-open')).to_have_count(20)
            checks.append('The real demo paginates forty-five history rows across three regions; detail includes a region beyond page one, page errors retain data/selection and keyboard retry/reset recovers')

            navigate('findings')
            page.locator('#refresh-feedback').click()
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(20)
            page.locator('#feedback-load-more').click()
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(40)
            page.locator('#feedback-load-more').click()
            expect(page.locator('#feedback-list .feedback-record')).to_have_count(45)
            expect(page.locator('#feedback-load-more')).to_be_hidden()
            assert page.evaluate('window.__demoXss') is None
            expect(page.locator('#feedback-list')).to_contain_text('Feedback cũ thiếu metadata')
            checks.append('The real demo paginates forty-five managed feedback records, including legacy metadata and long HTML-like resource IDs rendered as safe text')

            # Keep the screenshots concise while retaining the same data schema.
            with demo.LOCK:
                demo.FEEDBACK = dict(list(demo.FEEDBACK.items())[:3])
                demo.HISTORY = demo.HISTORY[:3]
            screenshots = []
            for width in [320, 390, 768, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                for section in ['overview', 'findings', 'history', 'connection', 'settings']:
                    navigate(section)
                    if section == 'findings':
                        page.locator('#refresh-feedback').click()
                        expect(page.locator('#feedback-list .feedback-record')).to_have_count(3)
                        page.locator('#filter-type').select_option('S3_MULTIPART')
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, section)
                navigate('findings')
                page.locator('#filter-region').select_option(REGIONS[0])
                expect(page.locator('#findings-list tbody tr')).to_have_count(1)
                page.locator('#findings-list .finding-open').click()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, 'dialog')
                expect(page.locator('#finding-dialog')).to_be_visible()
                page.screenshot(path=str(OUT / ('integrated-evidence-' + str(width) + '.png')))
                screenshots.append('integrated-evidence-' + str(width) + '.png')
                page.get_by_role('heading', name='Bằng chứng chính (S3_MULTIPART)', exact=True).scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / ('integrated-evidence-scrolled-' + str(width) + '.png')))
                screenshots.append('integrated-evidence-scrolled-' + str(width) + '.png')
                page.keyboard.press('Escape')
                page.locator('#filter-region').select_option('')
                page.locator('#filter-type').select_option('')
                navigate('overview')
                page.screenshot(path=str(OUT / ('integrated-overview-' + str(width) + '.png')), full_page=True)
                screenshots.append('integrated-overview-' + str(width) + '.png')
            checks.append('All five pages and the evidence dialog fit 320/390/768/1440px with real demo state; twelve desktop/tablet/mobile screenshots including scrolled evidence and native keyboard focus')

            stale = browser.new_context()
            stale.add_init_script("sessionStorage.setItem('crg-token','expired-demo-token')")
            expired = stale.new_page()
            expired.goto(base)
            expect(expired.locator('#app')).to_be_hidden()
            expect(expired.locator('#login')).to_have_text('Đăng nhập')
            expect(expired.locator('#status')).to_contain_text('Đăng nhập demo')
            assert not errors, errors
            assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha for name, sha in source_hashes.items())
            checks.append('An expired local token returns to login; no browser page errors and tested source hashes stay unchanged')
            output = {'environment': 'REAL LOCAL DEMO HTTP - NOT AWS', 'checks': checks,
                      'request_count': len(requests), 'page_errors': errors, 'widths': [320, 390, 768, 1440],
                      'screenshots': screenshots, 'source_hashes': source_hashes,
                      'faults': 'Only deliberate pending/503 feedback and 503 history page were intercepted',
                      'pagination_setup': 'Forty-five records inserted into isolated process RAM; requests used actual demo endpoints'}
            (OUT / 'acceptance-results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            browser.close()
            print('Integrated demo UI PASS: ' + '; '.join(checks))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
