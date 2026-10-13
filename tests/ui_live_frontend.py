"""Post-publish public frontend verification, not authenticated AWS scan testing.

Reads current release state created by the AWS MCP workflow. No AWS SDK/CLI,
credentials, sign-up, password submission, API mutation or fixture injection.
"""
import hashlib,json,os,pathlib,urllib.request
from urllib.parse import parse_qs,urlsplit
from playwright.sync_api import sync_playwright,expect

ROOT=pathlib.Path(__file__).resolve().parents[1]
STATE=json.loads((ROOT/'.preflight/publish-state.json').read_text(encoding='utf-8'))
WEB=STATE['outputs']['WebUrl']
OUT=ROOT/'.preflight/live-redesign'
OUT.mkdir(exist_ok=True)
checks={'url':WEB,'kind':'Public live frontend only; no authenticated scan','assets':{},'browser':[]}
for name in ['index.html','app.js','styles.css','target-role.yaml','config.json']:
    with urllib.request.urlopen(WEB+name,timeout=30) as response:
        data=response.read()
        assert response.status==200
        assert data==(ROOT/'web'/name).read_bytes(), 'Live bytes differ: '+name
        checks['assets'][name]={'status':response.status,'sha256':hashlib.sha256(data).hexdigest(),'content_type':response.headers.get('Content-Type')}
config=json.loads((ROOT/'web/config.json').read_text(encoding='utf-8'))
assert not config.get('demo') and config['redirect']==WEB
assert config['api']==STATE['outputs']['ApiUrl']
with sync_playwright() as p:
    options={'headless':True}
    if os.environ.get('CHROMIUM_EXECUTABLE'):options['executable_path']=os.environ['CHROMIUM_EXECUTABLE']
    browser=p.chromium.launch(**options)
    for width in [1440,390]:
        context=browser.new_context(viewport={'width':width,'height':1000 if width==1440 else 844})
        page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(WEB,wait_until='networkidle')
        expect(page.locator('#welcome')).to_be_visible()
        expect(page.locator('#app')).to_be_hidden()
        expect(page.locator('#demo-banner')).to_be_hidden()
        expect(page.locator('#start')).to_have_text('Đăng nhập để bắt đầu')
        expect(page.locator('#welcome h1')).to_contain_text('Bằng chứng thì không')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(OUT/f'welcome-{width}.png'),full_page=True)
        page.locator('#start').click()
        page.wait_for_url(config['auth']+'/**',timeout=30000)
        page.wait_for_load_state('networkidle')
        query=parse_qs(urlsplit(page.url).query)
        assert query['client_id']==[config['clientId']]
        assert query['redirect_uri']==[WEB]
        assert query['response_type']==['code']
        assert query['code_challenge_method']==['S256']
        assert len(query['code_challenge'][0])==43 and query.get('state')
        expect(page.locator('input[type="password"]:visible')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(OUT/f'login-{width}.png'),full_page=True)
        assert not errors,errors
        checks['browser'].append({'width':width,'welcome':'PASS','login_form':'PASS','pkce':'S256','overflow':False,'page_errors':errors})
        context.close()
    browser.close()
(OUT/'results.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
print('Live frontend PASS: five exact assets; real config/no demo; desktop/mobile welcome and Cognito login; PKCE S256; no JS errors or overflow.')
print('Not tested: authenticated login completion, AssumeRole, worker scan, detection rules on real AWS resources.')
