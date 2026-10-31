"""Local UI demo only. No boto3, AWS credentials, cloud reads or cloud writes.
Run: python demo.py, then open http://127.0.0.1:8080
"""
import argparse, base64, copy, json, re, sys, threading, time, uuid
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from rules import (config, evaluate_ebs, evaluate_ec2, evaluate_eip, evaluate_load_balancer,
                   evaluate_nat_gateway, evaluate_rds, evaluate_s3_multipart, evaluate_snapshot, finding_id)
WEB = Path(__file__).parent / 'web'
LOCK = threading.RLock()
SERVICE_GROUPS = ('compute','storage','database','network')
REGIONS = {'ap-southeast-1','ap-southeast-2','ap-northeast-1','us-east-1','us-west-2','eu-west-1'}
RESOURCE_GROUPS = {'EC2':'compute','EBS':'storage','EIP':'network','SNAPSHOT':'storage',
                   'S3_MULTIPART':'storage','RDS':'database','NAT_GATEWAY':'network','ALB':'network','NLB':'network'}
DEMO_COUNTS = {'EC2':4,'EBS':6,'EIP':2,'SNAPSHOT':8,'S3_MULTIPART':2,'RDS':3,'NAT_GATEWAY':2,'ALB':2,'NLB':2}
RETENTION_SECONDS = 30*86400
PROFILE = {'account_id':'123456789012','role_arn':'arn:aws:iam::123456789012:role/GuardianReadRole-demo',
           'regions':['ap-southeast-1'], 'service_groups':['compute','storage','database','network'],
           'external_id':'DEMO-ONLY-NOT-A-REAL-EXTERNAL-ID', 'connection_version':'demo-v1',
           'api_principal':'DEMO: API role ARN appears after real deployment', 'scan_principal':'DEMO: Worker role ARN appears after real deployment',
           'settings': config({}), 'notifications': {'enabled':False}, 'email_available':False}
FEEDBACK = {}
FINDING_OBSERVATIONS = {}

def sample_findings(region, observed_at):
 # Synthetic inventory/metrics only; evaluators and their evidence schema are the real pure rules.
 now=datetime.fromtimestamp(observed_at,timezone.utc);cfg=PROFILE['settings'];hours=cfg['window_hours']
 end=now.replace(minute=0,second=0,microsecond=0);start=end-timedelta(hours=hours);created=now-timedelta(days=60)
 zeros=[0]*hours;network=[.09*1048576]*hours;missing=[0]*int(hours*.3)
 account=PROFILE['account_id'];rds_arn='arn:aws:rds:'+region+':'+account+':db:database-demo'
 alb_arn='arn:aws:elasticloadbalancing:'+region+':'+account+':loadbalancer/app/alb-demo/0000000000000001'
 nlb_arn='arn:aws:elasticloadbalancing:'+region+':'+account+':loadbalancer/net/nlb-demo/0000000000000002'
 samples=[
  (evaluate_ec2({'InstanceId':'i-0123456789abcdef0','LaunchTime':created,'State':{'Name':'running'}},[[1.7]*hours,network,network],cfg,start),'i-0123456789abcdef0'),
  (evaluate_ebs({'VolumeId':'vol-0a123456789bcdef0','Size':40,'State':'available','Attachments':[]},49.5,cfg),'vol-0a123456789bcdef0'),
  (evaluate_eip({'AllocationId':'eipalloc-0123456789abcdef0'},12,cfg),'eipalloc-0123456789abcdef0'),
  (evaluate_snapshot({'SnapshotId':'snap-0123456789abcdef0','StartTime':now-timedelta(days=65),'VolumeId':'vol-0b123456789bcdef0','VolumeSize':40,'State':'completed'},set(),True,cfg,now),'snap-0123456789abcdef0'),
  (evaluate_ec2({'InstanceId':'i-0fedcba9876543210','LaunchTime':created,'State':{'Name':'running'}},[missing,missing,missing],cfg,start),'i-0fedcba9876543210'),
  (evaluate_s3_multipart('guardian-demo',{'Key':'archive/demo.bin','UploadId':'demo-upload','Initiated':now-timedelta(days=8)},now),['guardian-demo','archive/demo.bin','demo-upload']),
  (evaluate_rds({'DBInstanceIdentifier':'database-demo','DBInstanceArn':rds_arn,'DBInstanceStatus':'available','InstanceCreateTime':created,'Engine':'postgres','DBInstanceClass':'db.t3.micro'},[zeros,zeros],cfg,start),rds_arn),
  (evaluate_nat_gateway({'NatGatewayId':'nat-demo','State':'available','CreateTime':created,'VpcId':'vpc-demo','SubnetId':'subnet-demo'},[zeros,zeros],cfg,start),'nat-demo'),
  (evaluate_load_balancer({'LoadBalancerName':'alb-demo','LoadBalancerArn':alb_arn,'Type':'application','State':{'Code':'active'},'CreatedTime':created,'Scheme':'internet-facing'},[zeros],cfg,start),alb_arn),
  (evaluate_load_balancer({'LoadBalancerName':'nlb-demo','LoadBalancerArn':nlb_arn,'Type':'network','State':{'Code':'active'},'CreatedTime':created,'Scheme':'internal'},[zeros],cfg,start),nlb_arn),
 ]
 statistics={'EC2':{'cpu':'Maximum','netin':'Sum','netout':'Sum'},'RDS':{'cpu':'Maximum','connections':'Maximum'},
             'NAT_GATEWAY':{'source':'Sum','destination':'Sum'},'ALB':{'requests':'Sum'},'NLB':{'flows':'Sum'}}
 findings=[]
 for item,identity in samples:
  if item is None:continue
  context={'account_id':account,'region':region,'evaluated_at':now.isoformat()}
  item.update(context,finding_id=finding_id(item['type'],region,identity));item['evidence'].update(context)
  if item['type'] in statistics:
   item['evidence'].update(observation_start=start.isoformat(),observation_end=end.isoformat(),metric_period_seconds=3600,metric_statistics=statistics[item['type']])
  findings.append(item)
 return findings

def observe_finding(item, observed_at):
 key=(PROFILE['connection_version'],item['region'],item['finding_id']);old=FINDING_OBSERVATIONS.get(key)
 first=old['first'] if old is not None and old['expires']>observed_at else observed_at
 last=max(observed_at,old['last']) if old is not None and old['expires']>observed_at else observed_at
 FINDING_OBSERVATIONS[key]={'first':first,'last':last,'expires':last+RETENTION_SECONDS}
 item.update(first_seen_at=datetime.fromtimestamp(first,timezone.utc).isoformat().replace('+00:00','Z'),
             last_seen_at=datetime.fromtimestamp(last,timezone.utc).isoformat().replace('+00:00','Z'))
def normalized_groups(value):
 if value is None:return list(SERVICE_GROUPS)
 if not isinstance(value,list) or not 1<=len(value)<=4 or any(not isinstance(group,str) or group not in SERVICE_GROUPS for group in value) or len(set(value))!=len(value):
  raise ValueError('Choose 1 to 4 unique supported service groups')
 return list(value)
def feedback_findings(candidates):
 visible=[];now=time.time()
 for finding in candidates:
  item=copy.deepcopy(finding);item.pop('acknowledged',None)
  record=FEEDBACK.get(item['finding_id'],{})
  if record.get('expires',float('inf'))<=now or record.get('region')!=item.get('region') or record.get('connection_version')!=PROFILE['connection_version']:record={}
  if record.get('kept') or record.get('ignore_until',0)>now:continue
  if record.get('acknowledged'):item['acknowledged']=True
  visible.append(item)
 return visible

def public_result(row, overlay=False):
 result=copy.deepcopy(row)
 if overlay and ('candidates' in row or 'findings' in row):
  result['findings']=feedback_findings(row.get('candidates',row.get('findings',[])));result['finding_count']=len(result['findings'])
 result.pop('candidates',None)
 return result

def feedback_page(query):
 values=query.get('limit',['20'])
 if len(values)!=1 or not values[0].isdigit() or not 1<=int(values[0])<=100:raise ValueError('limit must be an integer from 1 to 100')
 limit=int(values[0]);version=PROFILE['connection_version'];after=None
 if 'next_token' in query:
  tokens=query['next_token']
  if len(tokens)!=1 or not tokens[0]:raise ValueError('Invalid pagination token')
  value=tokens[0]
  try:
   token=json.loads(base64.b64decode(value+'='*(-len(value)%4),altchars=b'-_',validate=True))
  except (ValueError,UnicodeDecodeError) as error:raise ValueError('Invalid pagination token') from error
  if not isinstance(token,dict) or set(token)!={'route','connection_version','region','finding_id'} or token.get('route')!='/feedback' or token.get('connection_version')!=version or token.get('region') not in PROFILE['regions'] or not isinstance(token.get('finding_id'),str) or not re.fullmatch(r'[0-9a-f]{64}',token['finding_id']):raise ValueError('Invalid pagination token')
  after=(token['region'],token['finding_id'])
 rows=sorted((record for record in FEEDBACK.values() if record.get('connection_version',version)==version and record.get('region') in PROFILE['regions'] and isinstance(record.get('finding_id'),str) and record.get('expires',float('inf'))>time.time()),key=lambda record:(record['region'],record['finding_id']),reverse=True)
 if after is not None:rows=[record for record in rows if (record['region'],record['finding_id'])<after]
 page=rows[:limit];next_token=None
 if len(rows)>limit:
  last=page[-1];cursor={'route':'/feedback','connection_version':version,'region':last['region'],'finding_id':last['finding_id']}
  next_token=base64.urlsafe_b64encode(json.dumps(cursor,separators=(',',':')).encode()).decode().rstrip('=')
 return {'results':copy.deepcopy(page),'next_token':next_token}

def history_key(row):
 return 'HISTORY#{}#{}#{}'.format(int(row.get('created_at',row.get('started_at',0))),row['region'],row['scan_id'])

def history_rows():
 return sorted((row for row in HISTORY if row.get('connection_version')==PROFILE['connection_version'] and row.get('region') in PROFILE['regions'] and row.get('expires',0)>time.time()),key=history_key,reverse=True)

def history_page(query):
 values=query.get('limit',['20'])
 if len(values)!=1 or not values[0].isdigit() or not 1<=int(values[0])<=100:raise ValueError('limit must be an integer from 1 to 100')
 limit=int(values[0]);version=PROFILE['connection_version'];after=None
 if 'next_token' in query:
  values=query['next_token']
  if len(values)!=1 or not values[0]:raise ValueError('Invalid pagination token')
  value=values[0]
  try:
   token=json.loads(base64.b64decode(value+'='*(-len(value)%4),altchars=b'-_',validate=True))
  except (ValueError,UnicodeDecodeError) as error:raise ValueError('Invalid pagination token') from error
  if not isinstance(token,dict) or set(token)!={'route','connection_version','key'} or token.get('route')!='/history' or token.get('connection_version')!=version or not isinstance(token.get('key'),str):raise ValueError('Invalid pagination token')
  parts=token['key'].split('#')
  if len(parts)!=4 or parts[0]!='HISTORY' or not parts[1].isdigit() or parts[2] not in PROFILE['regions'] or not parts[3]:raise ValueError('Invalid pagination token')
  after=token['key']
 rows=history_rows()
 if after is not None:rows=[row for row in rows if history_key(row)<after]
 page=rows[:limit];next_token=None
 if len(rows)>limit:
  cursor={'route':'/history','connection_version':version,'key':history_key(page[-1])}
  next_token=base64.urlsafe_b64encode(json.dumps(cursor,separators=(',',':')).encode()).decode().rstrip('=')
 return {'results':[public_result(row) for row in page],'next_token':next_token}

def complete(scan_id, started, region='ap-southeast-1'):
 groups=normalized_groups(PROFILE.get('service_groups'));observed_at=int(time.time())
 candidates=[]
 for finding in sample_findings(region,observed_at):
  if RESOURCE_GROUPS[finding['type']] not in groups:continue
  observe_finding(finding,observed_at);candidates.append(finding)
 counts={kind:count for kind,count in DEMO_COUNTS.items() if RESOURCE_GROUPS[kind] in groups}
 visible=feedback_findings(candidates)
 return {'scan_id':scan_id,'region':region,'account_id':PROFILE['account_id'],'connection_version':PROFILE['connection_version'],'trigger':'manual','status':'SUCCEEDED','started_at':started,'completed_at':observed_at,
         'counts':counts,'candidates':candidates,'findings':visible,'finding_count':len(visible),
         'total_candidate_count':len(candidates),'errors':[],
         'notification':'DISABLED','expires':observed_at+RETENTION_SECONDS}
CURRENT=[complete(str(uuid.uuid4()),int(time.time()))]
HISTORY=copy.deepcopy(CURRENT)
READY_AT=0

def tick():
 global CURRENT,READY_AT
 if READY_AT and time.time()>=READY_AT:
  CURRENT=[complete(CURRENT[0]['scan_id'],CURRENT[0]['started_at'],r) for r in PROFILE['regions']]
  HISTORY[:0]=copy.deepcopy(CURRENT);HISTORY[:]=history_rows();READY_AT=0
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
  if path.startswith('/api/'):return self.handle_api('GET',self.path[4:])
  return super().do_GET()
 def do_POST(self):self.handle_api('POST',urlparse(self.path).path[4:])
 def do_PUT(self):self.handle_api('PUT',urlparse(self.path).path[4:])
 def handle_api(self,method,path):
  global CURRENT,READY_AT
  if self.headers.get('Authorization')!='Bearer demo-local-only':return self.reply(401,{'error':'Đăng nhập demo để tiếp tục.'})
  with LOCK:
   tick()
   try:
    parsed=urlparse(path);path=parsed.path;query=parse_qs(parsed.query,keep_blank_values=True)
    length=int(self.headers.get('Content-Length','0'))
    if length>10000:return self.reply(413,{'error':'Request too large'})
    body=json.loads(self.rfile.read(length) or b'{}')
    if not isinstance(body,dict):raise ValueError('Expected a JSON object')
    if path=='/me' and method=='GET':return self.reply(200,{**PROFILE,'service_groups':normalized_groups(PROFILE.get('service_groups'))})
    if path=='/findings':
     return self.reply(200,{'results':[public_result(row,overlay=True) for row in CURRENT]})
    if path=='/history':return self.reply(200,history_page(query))
    if path.startswith('/scans/'):
     scan_id=path.rsplit('/',1)[-1];rows={}
     for row in history_rows()+CURRENT:
      if row.get('scan_id')==scan_id and row.get('connection_version')==PROFILE['connection_version'] and row.get('region') in PROFILE['regions']:
       rows.setdefault(row['region'],public_result(row))
     return self.reply(200 if rows else 404,{'scan_id':scan_id,'results':list(rows.values())})
    if path=='/scans' and method=='POST':
     if READY_AT:return self.reply(409,{'error':'Demo đang chạy một lần quét.'})
     sid=str(uuid.uuid4());now=int(time.time());CURRENT=[{'scan_id':sid,'region':r,'connection_version':PROFILE['connection_version'],'trigger':'manual','status':'QUEUED','started_at':now} for r in PROFILE['regions']];READY_AT=time.time()+3
     return self.reply(202,{'scan_id':sid,'message':'Demo queued'})
    if path=='/settings' and method=='PUT':PROFILE['settings']=config(body,PROFILE['settings']);return self.reply(200,PROFILE['settings'])
    if path=='/connection' and method=='PUT':
     if set(body)-{'role_arn','regions','service_groups'} or not {'role_arn','regions'}<=set(body):raise ValueError('Connection fields are invalid')
     arn=body['role_arn'];regions=body['regions']
     if not isinstance(arn,str) or not re.fullmatch(r'arn:aws:iam::\d{12}:role/GuardianReadRole-[A-Za-z0-9+=,.@_-]{1,40}',arn):raise ValueError('Nhập ARN mẫu hợp lệ cho demo.')
     if not isinstance(regions,list) or not 1<=len(regions)<=3 or any(not isinstance(region,str) or region not in REGIONS for region in regions) or len(set(regions))!=len(regions):raise ValueError('Chọn 1–3 region hợp lệ, không trùng nhau.')
     groups=normalized_groups(body.get('service_groups',PROFILE.get('service_groups')))
     candidate={**PROFILE,'role_arn':arn,'account_id':arn.split(':')[4],'regions':list(regions),'service_groups':groups,'connection_version':str(uuid.uuid4())}
     PROFILE.update(candidate);CURRENT=[];READY_AT=0;HISTORY.clear();FEEDBACK.clear();FINDING_OBSERVATIONS.clear()
     return self.reply(200,{'connected':True,'demo':True})
    if path=='/notifications' and method=='PUT':
     if type(body.get('enabled')) is not bool:raise ValueError('enabled must be a boolean')
     if body['enabled']:raise ValueError('Email has not been configured by platform owner')
     PROFILE['notifications']={'enabled':False}
     return self.reply(200,PROFILE['notifications'])
    if path=='/feedback' and method=='PUT':
     if set(body)-{'region','finding_id','acknowledged','kept','ignoreUntil'} or not {'region','finding_id'}<=set(body):raise ValueError('Feedback fields are invalid')
     if not set(body)&{'acknowledged','kept','ignoreUntil'}:raise ValueError('At least one feedback field is required')
     ident=body['finding_id'];region=body['region']
     if region not in PROFILE['regions'] or not isinstance(ident,str) or not re.fullmatch(r'[0-9a-f]{64}',ident):raise ValueError('Invalid region or finding ID')
     for field in ('acknowledged','kept'):
      if field in body and type(body[field]) is not bool:raise ValueError(field+' must be a boolean')
     now=int(time.time());ignore_until=0
     if 'ignoreUntil' in body and body['ignoreUntil'] is not None:
      value=body['ignoreUntil']
      if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z',value):raise ValueError('ignoreUntil must be RFC3339 UTC')
      ignore_until=int(datetime.fromisoformat(value[:-1]+'+00:00').timestamp())
      if not now<ignore_until<=now+30*86400:raise ValueError('ignoreUntil must be in the next 30 days')
     candidate=next((finding for row in CURRENT if row.get('region')==region and row.get('connection_version')==PROFILE['connection_version'] for finding in row.get('candidates',row.get('findings',[])) if finding.get('finding_id')==ident),None)
     existing=FEEDBACK.get(ident,{})
     if existing and (existing.get('region')!=region or existing.get('connection_version',PROFILE['connection_version'])!=PROFILE['connection_version']):existing={}
     if candidate is None and not existing:return self.reply(404,{'error':'Finding not found'})
     record={**existing,'region':region,'finding_id':ident,'connection_version':PROFILE['connection_version'],'updated_at':now}
     if candidate is not None:
      for field in ('type','resource_id','account_id','rule_id'):
       if isinstance(candidate.get(field),str) and candidate[field]:record[field]=candidate[field]
     if 'acknowledged' in body:record['acknowledged']=body['acknowledged']
     if 'kept' in body:record['kept']=body['kept']
     if 'ignoreUntil' in body:record['ignore_until']=ignore_until
     if record.get('acknowledged') or record.get('kept'):record.pop('expires',None)
     else:record['expires']=record.get('ignore_until') if record.get('ignore_until',0)>now else now
     FEEDBACK[ident]=record
     return self.reply(200,record)
    if path=='/feedback' and method=='GET':return self.reply(200,feedback_page(query))
    return self.reply(404,{'error':'Route not found'})
   except (ValueError,KeyError,TypeError) as e:return self.reply(400,{'error':str(e)})
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8080);args=p.parse_args()
 server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
 print('DEMO only — no AWS access. Open http://127.0.0.1:'+str(args.port),flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:server.server_close()
