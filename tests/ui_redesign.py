"""Frontend acceptance tests with isolated local HTTP/API fixtures. NOT real AWS.
Run with the same CHROMIUM_EXECUTABLE and UI_QA_DIR as ui_smoke.py.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('UI_QA_DIR', ROOT / '.preflight/ui-redesign'))
OUT.mkdir(parents=True, exist_ok=True)
PORT = 8774
BASE = f'http://127.0.0.1:{PORT}'
PROFILE = dict(external_id='FIXTURE-ONLY-EXTERNAL-ID-123456789',
    api_principal='arn:aws:iam::123456789012:role/FixtureApiPrincipal',
    scan_principal='arn:aws:iam::123456789012:role/FixtureScanPrincipal',
    settings=dict(cpu_percent=5, network_mib_hour=1, window_hours=24,
                  orphan_hours=24, snapshot_days=30, interval_hours=6),
    notifications={'enabled': False}, email_available=False)
ARN = 'arn:aws:iam::123456789012:role/GuardianReadRole-fixture'
ROW = dict(region='ap-southeast-1', status='SUCCEEDED', completed_at=1791700000,
           counts={'EC2': 0, 'EBS': 0, 'EIP': 0, 'SNAPSHOT': 0}, findings=[])
server = subprocess.Popen([sys.executable, '-m', 'http.server', str(PORT), '--bind', '127.0.0.1',
                           '--directory', str(ROOT/'web')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
checks = []
try:
    for _ in range(50):
        try:
            opener.open(BASE, timeout=.2)
            break
        except Exception:
            time.sleep(.1)
    else:
        raise RuntimeError('Local static server did not start')
    with sync_playwright() as p:
        launch = {'headless': True, 'downloads_path': str(OUT/'downloads')}
        if os.environ.get('CHROMIUM_EXECUTABLE'):
            launch['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
        browser = p.chromium.launch(**launch)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000},
                                      permissions=['clipboard-read', 'clipboard-write'], reduced_motion='reduce')
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        state = dict(profile=copy.deepcopy(PROFILE), rows=[], history=[], requests=[], connection_error=False,
                     findings_error=False, history_error=False, scan_error=False)
        def route_api(route):
            path = route.request.url.split('/api')[-1]
            state['requests'].append((route.request.method, path, route.request.post_data))
            status, data = 200, {}
            if path == '/me':
                data = state['profile']
            elif path == '/findings':
                status, data = (503, {'error': 'Service unavailable'}) if state['findings_error'] else (200, {'results': state['rows']})
            elif path == '/history':
                status, data = (503, {'error': 'Service unavailable'}) if state['history_error'] else (200, {'results': state['history']})
            elif path == '/connection':
                if state['connection_error']:
                    status, data = 502, {'error': 'AWS request failed; check role permissions and CloudWatch logs'}
                else:
                    body = route.request.post_data_json
                    assert set(body) == {'role_arn', 'regions'}
                    state['profile'].update(body, account_id='123456789012')
                    state['rows'] = []
                    data = {'connected': True, 'account_id': '123456789012'}
            elif path == '/scans':
                if state['scan_error']:
                    status, data = 429, {'error': 'Wait 15 minutes between scans'}
                else:
                    state['rows'] = [dict(region='ap-southeast-1', status='QUEUED', started_at=int(time.time()))]
                    status, data = 202, {'scan_id': 'fixture-scan'}
            else:
                raise AssertionError(f'Unexpected fixture route: {path}')
            route.fulfill(status=status, content_type='application/json', body=json.dumps(data))
        page.route('**/config.json', lambda r: r.fulfill(json={'api': '/api', 'demo': True}))
        page.route('**/api/**', route_api)
        page.goto(BASE)
        page.evaluate('window.scrollTo(0,0)'); page.screenshot(path=str(OUT/'welcome-desktop.png'), full_page=True)
        page.locator('#start').click()
        expect(page.locator('#overview-state')).to_contain_text('Bắt đầu bằng kết nối AWS')
        for ident in ['total', 'review', 'observing', 'insufficient', 'nav-count']:
            expect(page.locator('#'+ident)).to_have_text('—')
        expect(page.locator('#scan')).to_be_disabled()
        page.evaluate('window.scrollTo(0,0)'); page.screenshot(path=str(OUT/'new-user-desktop.png'), full_page=True)
        checks.append('New user: unknown metrics, disabled scan, actionable onboarding')
        page.locator('[data-page="connection"]').click()
        expect(page.locator('#page-connection')).to_be_visible()
        for name, key in [('ApiPrincipal', 'api_principal'), ('ScanPrincipal', 'scan_principal'), ('ExternalId', 'external_id')]:
            page.get_by_role('button', name='Sao chép '+name, exact=True).click()
            assert page.evaluate('navigator.clipboard.readText()') == PROFILE[key]
        with page.expect_download() as download:
            page.locator('#download-template').click()
        assert Path(download.value.path()).read_bytes() == (ROOT/'target-role.yaml').read_bytes()
        page.evaluate('window.scrollTo(0,0)'); page.screenshot(path=str(OUT/'connection-desktop.png'), full_page=True)
        checks.append('Exact copy of all three parameters; downloaded template byte-identical')
        page.locator('#role').fill(PROFILE['api_principal'])
        page.locator('#connect').click()
        expect(page.locator('#connection-feedback')).to_contain_text('Không dùng principal ARN')
        assert not any(r[1]=='/connection' for r in state['requests'])
        page.locator('#role').fill(ARN)
        page.locator('#region-options input:checked').uncheck()
        page.locator('#connect').click()
        expect(page.locator('#connection-feedback')).to_contain_text('Chọn từ 1 đến 3 region')
        page.locator('#region-options input[value="ap-southeast-1"]').check()
        state['connection_error'] = True
        page.locator('#connect').click()
        expect(page.locator('#connection-feedback')).to_contain_text('ExternalId')
        expect(page.locator('#role')).to_have_value(ARN)
        page.evaluate('window.scrollTo(0,0)'); page.screenshot(path=str(OUT/'connection-error-desktop.png'), full_page=True)
        state['connection_error'] = False
        page.locator('#connect').click()
        expect(page.locator('#connection-feedback')).to_contain_text('Tiếp tục bước 3')
        expect(page.locator('#first-scan')).to_be_enabled()
        checks.append('Principal ARN/zero-region rejection; denied role recovery; connection payload unchanged')
        page.locator('#first-scan').click()
        expect(page.locator('#page-overview')).to_be_visible()
        expect(page.locator('#scan-summary')).to_contain_text('Đang chờ')
        expect(page.locator('#scan')).to_be_disabled()
        expect(page.locator('#review')).to_have_text('—')
        assert len([r for r in state['requests'] if r[1]=='/scans']) == 1
        page.evaluate('window.scrollTo(0,0)'); page.screenshot(path=str(OUT/'queued-desktop.png'), full_page=True)
        for scan_state, label in [('RUNNING','Đang quét'),('FAILED','Lỗi'),('TIMED_OUT','Quá hạn'),('PARTIAL','Chưa đầy đủ'),('SUCCEEDED','Hoàn tất')]:
            row=copy.deepcopy(ROW)
            row['status']=scan_state
            if scan_state in ['RUNNING','FAILED','TIMED_OUT']:
                row.pop('counts')
            if scan_state=='FAILED':
                row['error']='Cannot access AWS; reconnect and check role permissions'
            if scan_state=='TIMED_OUT':
                row['error']='Scan did not complete within 15 minutes. Check Lambda failure queue and retry.'
            if scan_state=='PARTIAL':
                row['errors']=[{'type':'EC2','code':'AccessDenied'}]
            state['rows']=[row]
            page.locator('#refresh').click()
            expect(page.locator('#scan-summary')).to_contain_text(label)
            expect(page.locator('#total')).to_have_text('0' if scan_state in ['PARTIAL','SUCCEEDED'] else '—')
            page.evaluate('window.scrollTo(0,0)'); page.screenshot(path=str(OUT/(scan_state.lower()+'-desktop.png')), full_page=True)
        state['rows']=[dict(ROW,status='PARTIAL',counts={},errors=[{'type':'EC2','code':'AccessDenied'}])]
        page.locator('#refresh').click()
        expect(page.locator('#total')).to_have_text('—')
        expect(page.locator('#review')).to_have_text('—')
        state['scan_error']=True
        page.locator('#scan').click()
        expect(page.locator('#status')).to_contain_text('Chưa đủ 15 phút')
        expect(page.locator('#scan')).to_be_enabled()
        checks.append('First scan once; queued/running/failed/timed-out/partial/success-zero; cooldown error')
        state['findings_error']=True
        page.locator('#refresh').click()
        expect(page.locator('#overview-state')).to_contain_text('Không tải được kết quả mới')
        state['findings_error']=False
        state['rows']=[copy.deepcopy(ROW)]
        page.locator('#refresh').click()
        expect(page.locator('#overview-state')).to_contain_text('Kết quả đã sẵn sàng')
        page.locator('[data-page="history"]').click()
        expect(page.locator('#history-list')).to_contain_text('Chưa có lịch sử')
        state['history_error']=True
        page.locator('#refresh-history').click()
        expect(page.locator('#history-list')).to_contain_text('Không tải được lịch sử')
        state['history_error']=False
        state['history']=[dict(ROW, status='PARTIAL', errors=[{'type':'EC2','code':'AccessDenied'}])]
        page.locator('#refresh-history').click()
        page.locator('#history-list button').click()
        expect(page.locator('#history-detail')).to_contain_text('EC2: AccessDenied')
        expect(page.locator('#history-detail')).to_contain_text('chưa hoàn tất đầy đủ')
        page.evaluate('window.scrollTo(0,0)'); page.screenshot(path=str(OUT/'history-desktop.png'), full_page=True)
        page.locator('[data-page="settings"]').click()
        expect(page.locator('#email-enabled')).to_be_disabled()
        expect(page.locator('#save-email')).to_be_disabled()
        checks.append('API/history errors and retry; partial-history evidence; SES stays disabled')
        # XSS safety, evidence, filter reset and each page at narrow, mobile, tablet, desktop widths.
        state['rows']=[dict(ROW, findings=[dict(type='EC2',resource_id='i-fixture',level='REVIEW',
            reason='<img src=x onerror="window.bad=true">', rule_id='EC2_LOW_UTILIZATION',
            recommendation='Xác minh tải và mục đích của instance.',
            evidence={'cpu_p95':1,'window_hours':168,'thresholds':{'cpu_percent':5,'network_mib_hour':1},
                      'sample_counts':{'cpu':168,'netin':168,'netout':168},'required_samples':135})])]
        page.locator('[data-page="overview"]').click()
        page.locator('#refresh').click()
        expect(page.locator('#review')).to_have_text('1')
        assert page.locator('#priority-list img').count()==0
        page.locator('[data-page="findings"]').click()
        page.locator('#search').fill('no match')
        expect(page.locator('#findings-list')).to_contain_text('Không khớp bộ lọc')
        page.locator('#search').fill('')
        for width in [320,390,768,1440]:
            page.set_viewport_size({'width':width,'height':900})
            for section in ['overview','findings','history','connection','settings']:
                page.locator(f'[data-page="{section}"]').click()
                expect(page.locator('#page-'+section)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width,section)
                if width in [390,1440]:
                    page.evaluate('window.scrollTo(0,0)'); page.screenshot(path=str(OUT/f'{section}-{width}.png'),full_page=True)
        page.keyboard.press('Tab')
        assert page.evaluate('document.activeElement !== document.body')
        checks.append('Safe text rendering; empty filter; all five pages at 320/390/768/1440; keyboard focus')
        assert not errors, errors
        browser.close()
    (OUT/'acceptance-results.json').write_text(json.dumps({'environment':'LOCAL FIXTURES — NOT AWS','checks':checks,'page_errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Frontend acceptance PASS:\n'+'\n'.join(checks))
finally:
    server.terminate()
    server.wait(timeout=5)
