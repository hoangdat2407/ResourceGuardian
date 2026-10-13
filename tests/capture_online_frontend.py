"""Read-only HTTPS snapshot of the documented site. Does not publish or call AWS APIs.
This is a public-asset snapshot, not a substitute for verifying the stack Outputs
and object inventory via AWS MCP immediately before a release.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WEB = 'https://d3qn9wabid8ws0.cloudfront.net/'
out = ROOT / '.preflight' / ('online-backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
out.mkdir(parents=True, exist_ok=False)
manifest = {'source': WEB, 'scope': 'Public entrypoint and its three dependencies; not S3 inventory',
            'stack_outputs_verified_this_session': False, 'files': {}}
for name in ['index.html', 'app.js', 'styles.css', 'config.json']:
    req = urllib.request.Request(WEB + name, headers={'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read()
        manifest['files'][name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'content_type': response.headers.get('Content-Type'), 'cache_control': response.headers.get('Cache-Control'),
            'etag': response.headers.get('ETag')}
    (out/name).write_bytes(data)
cfg = json.loads((out/'config.json').read_bytes())
assert not cfg.get('demo'), 'Online config unexpectedly contains demo mode'
assert cfg['redirect'] == WEB
assert (out/'config.json').read_bytes() == (ROOT/'web/config.json').read_bytes(), 'Local config differs; do not publish'
assert all(name in (out/'index.html').read_text(encoding='utf-8-sig') for name in ['styles.css', 'app.js'])
manifest['production_config_matches_local_bytes'] = True
(out/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('Read-only snapshot saved:', out)
print('Production config byte-identical; no demo; no upload/invalidation performed.')
