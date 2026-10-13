"""Local UI demo only. No boto3, AWS credentials, cloud reads or cloud writes.
Run: python demo.py, then open http://127.0.0.1:8080
"""
import argparse, copy, json, sys, threading, time, uuid
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from rules import config
WEB = Path(__file__).parent / 'web'
LOCK = threading.RLock()
PROFILE = {'account_id':'123456789012','role_arn':'arn:aws:iam::123456789012:role/GuardianReadRole-demo',
           'regions':['ap-southeast-1'], 'external_id':'DEMO-ONLY-NOT-A-REAL-EXTERNAL-ID',
           'api_principal':'DEMO: API role ARN appears after real deployment', 'scan_principal':'DEMO: Worker role ARN appears after real deployment',
           'settings': config({}), 'notifications': {'enabled':False}, 'email_available':True}
IGNORE = set()
FINDINGS = [
 {'type':'EC2','resource_id':'i-0123456789abcdef0','level':'REVIEW','reason':'Low CPU and network; confirm intended workload','evidence':{'cpu_p95':1.7,'network_mib_hour':.18,'coverage':1}},
 {'type':'EBS','resource_id':'vol-0a123456789bcdef0','level':'REVIEW','reason':'Unattached volume; validate data retention','evidence':{'size_gib':40,'observed_hours':49.5}},
 {'type':'EIP','resource_id':'eipalloc-0123456789abcdef0','level':'OBSERVING','reason':'Unassociated public IPv4; may be intentionally reserved','evidence':{'observed_hours':12}},
 {'type':'SNAPSHOT','resource_id':'snap-0123456789abcdef0','level':'REVIEW','reason':'Old snapshot not referenced by listed AMIs; backup purpose requires review','evidence':{'age_days':65,'volume_id':'vol-0b123456789bcdef0','logical_volume_gib':40}},
 {'type':'EC2','resource_id':'i-0fedcba9876543210','level':'INSUFFICIENT_DATA','reason':'Missing CloudWatch metrics; not classified as idle','evidence':{'coverage':.3}}
]
def complete(scan_id, started):
 return {'scan_id':scan_id,'region':'ap-southeast-1','status':'SUCCEEDED','started_at':started,'completed_at':int(time.time()),
         'counts':{'EC2':4,'EBS':6,'EIP':2,'SNAPSHOT':8},'findings':[copy.deepcopy(f) for f in FINDINGS if f['resource_id'] not in IGNORE],
         'notification':'DEMO_ONLY','expires':int(time.time())+86400*30}
CURRENT=[complete(str(uuid.uuid4()),int(time.time())-3600)]
CURRENT[0]['completed_at']=int(time.time())-3500
HISTORY=copy.deepcopy(CURRENT)
READY_AT=0

def tick():
 global CURRENT,READY_AT
 if READY_AT and time.time()>=READY_AT:
  CURRENT=[{**complete(CURRENT[0]['scan_id'],CURRENT[0]['started_at']), 'region':r} for r in PROFILE['regions']]
  HISTORY[:0]=copy.deepcopy(CURRENT);del HISTORY[20:];READY_AT=0
 elif READY_AT:
  for r in CURRENT:r['status']='RUNNING'

class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*args,**kw):super().__init__(*args,directory=str(WEB),**kw)
 def log_message(self,*args):pass
 def reply(self,code,data):
  b=json.dumps(data).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def do_GET(self):
  path=urlparse(self.path).path
  if path=='/config.json':return self.reply(200,{'api':'/api','demo':True})
  if path.startswith('/api/'):return self.handle_api('GET',path[4:])
  return super().do_GET()
 def do_POST(self):self.handle_api('POST',urlparse(self.path).path[4:])
 def do_PUT(self):self.handle_api('PUT',urlparse(self.path).path[4:])
 def handle_api(self,method,path):
  global CURRENT,READY_AT
  if self.headers.get('Authorization')!='Bearer demo-local-only':return self.reply(401,{'error':'Đăng nhập demo để tiếp tục.'})
  with LOCK:
   tick()
   try:
    length=int(self.headers.get('Content-Length','0'))
    if length>10000:return self.reply(413,{'error':'Request too large'})
    body=json.loads(self.rfile.read(length) or b'{}')
    if path=='/me' and method=='GET':return self.reply(200,PROFILE)
    if path=='/findings':return self.reply(200,{'results':CURRENT})
    if path=='/history':return self.reply(200,{'results':HISTORY})
    if path.startswith('/scans/'):
     rows=[r for r in CURRENT+HISTORY if r['scan_id']==path.rsplit('/',1)[-1]]
     return self.reply(200 if rows else 404,{'results':rows})
    if path=='/scans' and method=='POST':
     if READY_AT:return self.reply(409,{'error':'Demo đang chạy một lần quét.'})
     sid=str(uuid.uuid4());now=int(time.time());CURRENT=[{'scan_id':sid,'region':r,'status':'QUEUED','started_at':now} for r in PROFILE['regions']];READY_AT=time.time()+3
     return self.reply(202,{'scan_id':sid,'message':'Demo queued'})
    if path=='/settings' and method=='PUT':PROFILE['settings']=config(body);return self.reply(200,PROFILE['settings'])
    if path=='/connection' and method=='PUT':
     if not body.get('role_arn','').startswith('arn:aws:iam::'):raise ValueError('Nhập ARN mẫu hợp lệ cho demo.')
     if not 1<=len(body.get('regions',[]))<=3:raise ValueError('Chọn 1–3 region.')
     PROFILE.update(role_arn=body['role_arn'],regions=body['regions']);CURRENT=[]
     return self.reply(200,{'connected':True,'demo':True})
    if path=='/notifications' and method=='PUT':
     PROFILE['notifications']={'enabled':bool(body.get('enabled')),'email':'demo@example.com'}
     return self.reply(200,PROFILE['notifications'])
    if path=='/ignore' and method=='PUT':IGNORE.add(body['resource_id']);return self.reply(200,{'ignored':True})
    return self.reply(404,{'error':'Route not found'})
   except (ValueError,KeyError,TypeError) as e:return self.reply(400,{'error':str(e)})
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8080);args=p.parse_args()
 server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
 print('DEMO only — no AWS access. Open http://127.0.0.1:'+str(args.port),flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:server.server_close()
