"""Playwright UI smoke tests against the local demo, not real AWS.
Run after installing requirements-dev.txt and playwright install chromium.
Optional CHROMIUM_EXECUTABLE points to an existing Chromium executable.
"""
import os, pathlib, subprocess, sys, time, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright, expect
ROOT=pathlib.Path(__file__).resolve().parents[1]
PORT=8773
server=subprocess.Popen([sys.executable,str(ROOT/'demo.py'),'--port',str(PORT)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
 for _ in range(50):
  try:opener.open(f'http://127.0.0.1:{PORT}/config.json',timeout=.2);break
  except Exception:time.sleep(.1)
 else:raise RuntimeError('Demo server did not start')
 with sync_playwright() as p:
  kwargs={'headless':True,'args':['--no-sandbox','--disable-dev-shm-usage']}
  if os.environ.get('CHROMIUM_EXECUTABLE'):kwargs['executable_path']=os.environ['CHROMIUM_EXECUTABLE']
  browser=p.chromium.launch(**kwargs)
  context=browser.new_context(viewport={'width':1440,'height':1000});page=context.new_page();errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(f'http://127.0.0.1:{PORT}/');page.locator('#start').click()
  expect(page.locator('#app')).to_be_visible();expect(page.locator('#review')).to_have_text('3');expect(page.locator('#total')).to_have_text('20')
  out=pathlib.Path(os.environ.get('UI_QA_DIR','/tmp/crg-ui-qa'));out.mkdir(parents=True,exist_ok=True)
  page.screenshot(path=str(out/'desktop.png'),full_page=True)
  page.locator('[data-page="findings"]').click();expect(page.locator('#findings-list tbody tr')).to_have_count(5)
  page.locator('#filter-type').select_option('EBS');expect(page.locator('#findings-list tbody tr')).to_have_count(1)
  page.locator('#findings-list button').click();expect(page.locator('#status')).to_contain_text('Đã bỏ qua')
  page.locator('[data-page="settings"]').click();page.locator('#cpu_percent').fill('7');page.locator('#save-settings').click();expect(page.locator('#status')).to_contain_text('Đã lưu ngưỡng')
  page.locator('#email-enabled').check();page.locator('#save-email').click();expect(page.locator('#email-note')).to_contain_text('demo@example.com')
  page.locator('[data-page="connection"]').click();expect(page.locator('#role')).to_have_value('arn:aws:iam::123456789012:role/GuardianReadRole-demo')
  for r in ['ap-southeast-2','ap-northeast-1','us-east-1']:page.locator('#region-options input[value="'+r+'"]').check()
  page.locator('#connect').click();expect(page.locator('#status')).to_contain_text('Chọn từ 1 đến 3 region')
  for r in ['ap-southeast-2','ap-northeast-1','us-east-1']:page.locator('#region-options input[value="'+r+'"]').uncheck()
  page.locator('[data-page="overview"]').click();page.locator('#scan').click()
  expect(page.locator('#scan-summary')).to_contain_text('Đang quét');expect(page.locator('#scan')).to_be_disabled()
  expect(page.locator('#scan-summary')).to_contain_text('Hoàn tất',timeout=15000);expect(page.locator('#review')).to_have_text('2')
  page.locator('[data-page="findings"]').click();page.locator('#filter-type').select_option('');expect(page.locator('#findings-list tbody tr')).to_have_count(4)
  feedback=page.evaluate("async()=>await (await fetch('/api/feedback',{headers:{Authorization:'Bearer demo-local-only'}})).json()")
  assert len(feedback['results'])==1,feedback
  record=feedback['results'][0]
  cleared=page.evaluate("""async r=>await (await fetch('/api/feedback',{method:'PUT',headers:{Authorization:'Bearer demo-local-only','Content-Type':'application/json'},body:JSON.stringify({region:r.region,finding_id:r.finding_id,ignoreUntil:null})})).json()""",record)
  assert cleared['ignore_until']==0,cleared
  page.evaluate("refresh()");expect(page.locator('#findings-list tbody tr')).to_have_count(5)
  page.locator('#search').fill('snapshot');expect(page.locator('#findings-list tbody tr')).to_have_count(1)
  page.locator('[data-page="history"]').click();expect(page.locator('#history-list tr')).to_have_count(3)
  page.locator('#history-list button').first.click();expect(page.locator('#history-detail table')).to_be_visible()
  mobile=browser.new_context(viewport={'width':390,'height':844},is_mobile=True);mp=mobile.new_page();mp.goto(f'http://127.0.0.1:{PORT}/');mp.locator('#start').click();expect(mp.locator('#app')).to_be_visible()
  assert mp.evaluate('document.documentElement.scrollWidth <= innerWidth'),'Mobile viewport has horizontal overflow'
  mp.screenshot(path=str(out/'mobile.png'),full_page=True)
  # A stale token must return to login instead of leaving the app visible.
  stale=browser.new_context();stale.add_init_script("sessionStorage.setItem('crg-token','expired-demo-token')")
  sp=stale.new_page();sp.goto(f'http://127.0.0.1:{PORT}/');expect(sp.locator('#status')).to_contain_text('Đăng nhập demo');expect(sp.locator('#app')).to_be_hidden();expect(sp.locator('#login')).to_have_text('Đăng nhập')
  assert not errors,errors
  browser.close();print('UI smoke PASS: dashboard, filters, feedback hide/list/clear, settings, email preference, region validation, scan polling, history, mobile, expired session.')
finally:
 server.terminate();server.wait(timeout=5)
