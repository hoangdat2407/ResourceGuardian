"""Backend workflow tests: real boto3 DynamoDB client against Moto, AWS reads mocked.
These do not establish real Cognito authentication, STS trust, or SES delivery.
"""
import copy, json, os, sys, pathlib, unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import boto3
from moto import mock_aws
from botocore.exceptions import ClientError
from test_api import app, event

class Workflows(unittest.TestCase):
 def setUp(self):
  self.aws=mock_aws();self.aws.start()
  self.db=boto3.resource('dynamodb',region_name='ap-southeast-1')
  self.db.create_table(TableName='test-table',KeySchema=[{'AttributeName':'pk','KeyType':'HASH'},{'AttributeName':'sk','KeyType':'RANGE'}],AttributeDefinitions=[{'AttributeName':'pk','AttributeType':'S'},{'AttributeName':'sk','AttributeType':'S'}],BillingMode='PAY_PER_REQUEST')
  self.table_patch=patch.object(app,'table',self.db.Table('test-table'));self.table_patch.start()
  self.profile={'pk':'TENANT#alice','sk':'PROFILE','external_id':'ext','settings':app.config({}), 'role_arn':'arn:aws:iam::123456789012:role/GuardianReadRole-demo','regions':['ap-southeast-1'],'connection_version':'v1'}
  app.put(self.profile)
  self.context=MagicMock();self.context.get_remaining_time_in_millis.return_value=200000
  self.ec2=MagicMock();self.cw=MagicMock();self.sess=MagicMock()
  self.sess.client.side_effect=lambda service,**kw:self.ec2 if service=='ec2' else self.cw
  self.instances=[];self.volumes=[];self.snapshots=[];self.images=[];self.addresses=[];self.inventory_errors={};self.scan_sequence=0
  def paginate(operation):
   if operation in self.inventory_errors:raise self.inventory_errors[operation]
   paginator=MagicMock()
   keys={'describe_instances':('Reservations',[{'Instances':self.instances}]),'describe_volumes':('Volumes',self.volumes), 'describe_snapshots':('Snapshots',self.snapshots),'describe_images':('Images',self.images)}
   key,items=keys[operation];paginator.paginate.return_value=[{key:items}];return paginator
  self.ec2.get_paginator.side_effect=paginate;self.ec2.describe_addresses.return_value={'Addresses':self.addresses}
  self.session_patch=patch.object(app,'session',return_value=self.sess);self.session_patch.start()
 def tearDown(self):self.session_patch.stop();self.table_patch.stop();self.aws.stop()
 def scan(self,sid='11111111-1111-1111-1111-111111111111'):
  app.put({'pk':self.profile['pk'],'sk':'RESULT#ap-southeast-1','scan_id':sid,'status':'QUEUED','started_at':int(app.time.time()),'region':'ap-southeast-1','connection_version':self.profile['connection_version']})
  app.worker({'pk':self.profile['pk'],'region':'ap-southeast-1','scan_id':sid,'connection_version':self.profile['connection_version']},self.context)
  return app.get(self.profile['pk'],'RESULT#ap-southeast-1')
 def scan_at(self,now):
  self.scan_sequence+=1
  with patch.object(app.time,'time',return_value=now):return self.scan('%08d-0000-0000-0000-000000000000'%self.scan_sequence)
 def keep_resource(self,rid,enabled,user='alice',**extra):
  return app.api(event('PUT','/keep',user=user,body={'region':'ap-southeast-1','resource_id':rid,'enabled':enabled,**extra}),None)
 def observation(self,rid):return app.get(self.profile['pk'],'OBS#'+self.profile['connection_version']+'#ap-southeast-1#'+rid)
 def add_orphan(self,kind,rid):
  if kind=='EBS':
   item={'VolumeId':rid,'State':'available','Attachments':[],'Size':40};self.volumes.append(item)
  else:
   item={'AllocationId':rid};self.addresses.append(item)
  return item
 def test_empty_scan_completes_and_history_written(self):
  r=self.scan();self.assertEqual(r['status'],'SUCCEEDED');self.assertEqual(r['counts'],{'EC2':0,'EBS':0,'EIP':0,'SNAPSHOT':0})
  self.assertEqual(len(app.history(self.profile['pk'],self.profile)),1)
 def test_unattached_volume_observation_then_review(self):
  self.volumes.append({'VolumeId':'vol-demo','State':'available','Attachments':[],'Size':40})
  clock=int(app.time.time())
  with patch.object(app.time,'time',return_value=clock):r=self.scan()
  self.assertEqual(r['findings'][0]['level'],'OBSERVING')
  with patch.object(app.time,'time',return_value=clock+25*3600):r=self.scan('22222222-2222-2222-2222-222222222222')
  self.assertEqual(r['findings'][0]['level'],'REVIEW')
  self.volumes[0]['Attachments']=[{'InstanceId':'i-demo'}];self.volumes[0]['State']='in-use'
  r=self.scan('33333333-3333-3333-3333-333333333333');self.assertEqual(r['findings'],[])
 def test_new_connection_does_not_inherit_old_observation(self):
  self.volumes.append({'VolumeId':'vol-demo','State':'available','Attachments':[],'Size':40})
  app.put({'pk':self.profile['pk'],'sk':'OBS#old-connection#ap-southeast-1#vol-demo','first':int(app.time.time())-30*3600,'last':int(app.time.time())})
  self.assertEqual(self.scan()['findings'][0]['level'],'OBSERVING')
 def test_snapshot_referenced_by_ami_is_not_flagged(self):
  self.snapshots.append({'SnapshotId':'snap-used','StartTime':datetime.now(timezone.utc)-timedelta(days=100),'State':'completed','VolumeSize':40})
  self.images.append({'BlockDeviceMappings':[{'Ebs':{'SnapshotId':'snap-used'}}]})
  self.assertEqual(self.scan()['findings'],[])
 def test_snapshot_referenced_by_disabled_ami_is_not_flagged(self):
  for rid in ('snap-disabled-ami','snap-unused'):
   self.snapshots.append({'SnapshotId':rid,'StartTime':datetime.now(timezone.utc)-timedelta(days=100),'State':'completed','VolumeSize':40})
  disabled_image={'ImageId':'ami-disabled','State':'disabled','BlockDeviceMappings':[{'Ebs':{'SnapshotId':'snap-disabled-ami'}}]}
  image_paginator=MagicMock()
  # AWS omits disabled AMIs unless this request explicitly includes them.
  image_paginator.paginate.side_effect=lambda **kwargs:[{'Images':[disabled_image] if kwargs.get('IncludeDisabled') is True else []}]
  default_paginator=self.ec2.get_paginator.side_effect
  self.ec2.get_paginator.side_effect=lambda operation:image_paginator if operation=='describe_images' else default_paginator(operation)
  result=self.scan()
  self.assertEqual(result['status'],'SUCCEEDED')
  self.assertEqual([finding['resource_id'] for finding in result['findings']],['snap-unused'])
  self.assertEqual(result['findings'][0]['level'],'REVIEW')
  self.assertTrue(result['findings'][0]['evidence']['relationships_complete'])
  image_paginator.paginate.assert_called_once_with(Owners=['self'],IncludeDisabled=True)
 def test_partial_permission_error_retains_useful_results(self):
  self.ec2.describe_addresses.side_effect=ClientError({'Error':{'Code':'UnauthorizedOperation','Message':'denied'}},'DescribeAddresses')
  r=self.scan();self.assertEqual(r['status'],'PARTIAL');self.assertEqual(r['errors'],[{'type':'EIP','code':'UnauthorizedOperation'}])
 def test_missing_metrics_never_classified_idle(self):
  self.instances.append({'InstanceId':'i-demo','State':{'Name':'running'},'LaunchTime':datetime.now(timezone.utc)-timedelta(days=4)})
  self.cw.get_metric_data.return_value={'MetricDataResults':[{'Id':k,'StatusCode':'Complete','Values':[],'Timestamps':[]} for k in ['cpu','netin','netout']]}
  r=self.scan();self.assertEqual(r['findings'][0]['level'],'INSUFFICIENT_DATA')
 def test_metrics_paginate_and_deduplicate_real_zeros(self):
  end=datetime.now(timezone.utc);start=end-timedelta(hours=24);ts=start+timedelta(hours=1)
  self.cw.get_metric_data.side_effect=[{'MetricDataResults':[{'Id':'cpu','StatusCode':'PartialData','Timestamps':[ts],'Values':[0]}],'NextToken':'page2'}, {'MetricDataResults':[{'Id':'cpu','StatusCode':'Complete','Timestamps':[ts],'Values':[0]}]}]
  v=app.metrics(self.cw,'i-demo',start,end);self.assertEqual(v,[[0],[],[]]);self.assertEqual(self.cw.get_metric_data.call_count,2)
 def test_scan_id_is_scoped_to_authenticated_tenant(self):
  sid='11111111-1111-1111-1111-111111111111';self.scan(sid)
  app.put({**self.profile,'pk':'TENANT#bob'})
  reply=app.api(event('GET','/scans/'+sid,user='bob'),None);self.assertEqual(reply['statusCode'],404)
 def test_enqueue_invokes_worker_asynchronously(self):
  with patch.object(app,'invoker') as inv:
   inv.invoke.return_value={'StatusCode':202};sid=app.enqueue(self.profile,int(app.time.time()))
   self.assertTrue(sid);self.assertEqual(inv.invoke.call_args.kwargs['InvocationType'],'Event')
   self.assertEqual(json.loads(inv.invoke.call_args.kwargs['Payload'])['pk'],'TENANT#alice')
 def test_terminal_marker_prevents_duplicate_scan(self):
  sid='11111111-1111-1111-1111-111111111111';self.scan(sid);self.sess.client.reset_mock()
  app.worker({'pk':self.profile['pk'],'region':'ap-southeast-1','scan_id':sid,'connection_version':'v1'},self.context)
  self.sess.client.assert_not_called()
 def test_transient_error_releases_lease_for_retry(self):
  sid='11111111-1111-1111-1111-111111111111'
  app.put({'pk':self.profile['pk'],'sk':'RESULT#ap-southeast-1','scan_id':sid,'status':'QUEUED','region':'ap-southeast-1','connection_version':'v1'})
  self.session_patch.stop()
  with patch.object(app,'session',side_effect=ClientError({'Error':{'Code':'Throttling','Message':'temporary'}},'AssumeRole')):
   with self.assertRaises(ClientError):app.worker({'pk':self.profile['pk'],'region':'ap-southeast-1','scan_id':sid,'connection_version':'v1'},self.context)
  self.assertEqual(app.get(self.profile['pk'],'RESULT#ap-southeast-1')['run_until'],0)
  self.session_patch.start()
 def test_notification_deduplicates_unchanged_review_set(self):
  p={**self.profile,'notifications':{'enabled':True,'email':'verified@example.com'}}
  r={'region':'ap-southeast-1','findings':[{'type':'EBS','resource_id':'vol-demo','level':'REVIEW','reason':'review'}]}
  with patch.dict(os.environ,SES_SENDER='owner@example.com'),patch.object(app.boto3,'client') as client:
   self.assertEqual(app.notify(p,r),'SENT');self.assertEqual(app.notify(p,r),'UNCHANGED')
   client.return_value.send_email.assert_called_once()
 def test_notification_uses_cognito_verified_email_not_body(self):
  e=event('PUT','/notifications',body={'enabled':True,'email':'attacker@example.com'});e['headers']={'authorization':'Bearer valid-token'}
  with patch.dict(os.environ,SES_SENDER='owner@example.com'),patch.object(app.boto3,'client') as client:
   client.return_value.get_user.return_value={'UserAttributes':[{'Name':'email','Value':'verified@example.com'},{'Name':'email_verified','Value':'true'}]}
   r=app.api(e,None);self.assertEqual(r['statusCode'],200);self.assertEqual(json.loads(r['body'])['email'],'verified@example.com')
 def test_keep_toggle_is_idempotent_and_preserves_disabled_record(self):
  key='KEEP#v1#ap-southeast-1#vol-demo'
  for enabled in (True,True,False,False):
   with self.subTest(enabled=enabled):
    reply=self.keep_resource('vol-demo',enabled)
    self.assertEqual(reply['statusCode'],200)
    self.assertEqual(json.loads(reply['body']),{'kept':enabled})
    self.assertIs(app.get(self.profile['pk'],key)['enabled'],enabled)
 def test_keep_uses_authenticated_tenant_and_current_connection(self):
  app.put({**self.profile,'pk':'TENANT#bob'})
  self.assertEqual(self.keep_resource('vol-demo',True,user='bob',tenant='alice',pk=self.profile['pk'])['statusCode'],200)
  self.assertEqual(app.get(self.profile['pk'],'KEEP#v1#ap-southeast-1#vol-demo'),{})
  self.assertTrue(app.get('TENANT#bob','KEEP#v1#ap-southeast-1#vol-demo')['enabled'])
  self.add_orphan('EBS','vol-demo')
  self.assertEqual(self.scan()['findings'][0]['level'],'OBSERVING')
  self.assertEqual(self.keep_resource('vol-demo',True)['statusCode'],200)
  self.profile['connection_version']='v2';app.put(self.profile)
  result=self.scan('22222222-2222-2222-2222-222222222222')
  self.assertEqual(result['findings'][0]['level'],'OBSERVING')
  self.assertEqual(app.get(self.profile['pk'],'KEEP#v2#ap-southeast-1#vol-demo'),{})
  self.assertEqual(self.keep_resource('vol-demo',False)['statusCode'],200)
  self.assertTrue(app.get(self.profile['pk'],'KEEP#v1#ap-southeast-1#vol-demo')['enabled'])
 def test_keep_rejects_invalid_input_without_writing_exception(self):
  for body in ({'enabled':'true'},{'enabled':1},{'enabled':None},{'enabled':False,'region':'us-east-1'},{'enabled':True,'resource_id':'vol/demo'}):
   with self.subTest(body=body):
    request={'region':'ap-southeast-1','resource_id':'vol-demo',**body}
    self.assertEqual(app.api(event('PUT','/keep',body=request),None)['statusCode'],400)
  self.assertEqual(list(app.all_items(self.profile['pk'],'KEEP#')),[])
  for missing in ('role_arn','connection_version'):
   with self.subTest(missing=missing):
    disconnected={k:v for k,v in self.profile.items() if k!=missing};app.put(disconnected)
    self.assertEqual(self.keep_resource('vol-demo',True)['statusCode'],400)
  self.assertEqual(list(app.all_items(self.profile['pk'],'KEEP#')),[])
 def test_ebs_and_eip_observation_boundaries_and_usage_reset(self):
  clock=int(app.time.time())
  volume=self.add_orphan('EBS','vol-demo');address=self.add_orphan('EIP','eipalloc-demo')
  for offset,expected in ((0,'OBSERVING'),(24*3600-1,'OBSERVING'),(24*3600,'REVIEW')):
   with self.subTest(offset=offset):
    result=self.scan_at(clock+offset)
    self.assertEqual({f['type']:f['level'] for f in result['findings']},{'EBS':expected,'EIP':expected})
    for rid in ('vol-demo','eipalloc-demo'):self.assertEqual(self.observation(rid)['first'],clock)
  volume.update(State='in-use',Attachments=[{'InstanceId':'i-demo'}]);address['AssociationId']='eipassoc-demo'
  self.assertEqual(self.scan_at(clock+25*3600)['findings'],[])
  for rid in ('vol-demo','eipalloc-demo'):self.assertEqual(self.observation(rid),{})
  volume.update(State='available',Attachments=[]);address.pop('AssociationId')
  result=self.scan_at(clock+26*3600)
  self.assertEqual({f['type']:f['level'] for f in result['findings']},{'EBS':'OBSERVING','EIP':'OBSERVING'})
  for rid in ('vol-demo','eipalloc-demo'):self.assertEqual(self.observation(rid)['first'],clock+26*3600)
 def test_observation_resets_after_gap_over_48_hours(self):
  clock=int(app.time.time());self.add_orphan('EBS','vol-demo');self.add_orphan('EIP','eipalloc-demo')
  self.scan_at(clock)
  at_boundary=self.scan_at(clock+48*3600)
  self.assertTrue(all(f['level']=='REVIEW' for f in at_boundary['findings']))
  later=clock+96*3600+1
  after_gap=self.scan_at(later)
  self.assertTrue(all(f['level']=='OBSERVING' for f in after_gap['findings']))
  for rid in ('vol-demo','eipalloc-demo'):self.assertEqual(self.observation(rid)['first'],later)
 def test_all_exceptions_hide_findings_but_preserve_orphan_observation(self):
  clock=int(app.time.time())
  for kind in ('EBS','EIP'):
   for exception in ('tag','keep','ignore'):
    with self.subTest(kind=kind,exception=exception):
     self.volumes.clear();self.addresses.clear()
     rid=('vol-' if kind=='EBS' else 'eipalloc-')+exception
     resource=self.add_orphan(kind,rid)
     ignore_key='IGNORE#v1#ap-southeast-1#'+rid
     if exception=='tag':resource['Tags']=[{'Key':'guardian:keep','Value':'true'}]
     elif exception=='keep':self.assertEqual(self.keep_resource(rid,True)['statusCode'],200)
     else:app.put({'pk':self.profile['pk'],'sk':ignore_key,'expires':clock+24*3600})
     for offset in (0,3600):
      self.assertEqual(self.scan_at(clock+offset)['findings'],[])
      self.assertEqual(self.observation(rid)['first'],clock)
      self.assertEqual(self.observation(rid)['last'],clock+offset)
     if exception=='tag':resource['Tags']=[]
     elif exception=='keep':self.assertEqual(self.keep_resource(rid,False)['statusCode'],200)
     result=self.scan_at(clock+24*3600)
     self.assertEqual(len(result['findings']),1)
     self.assertEqual(result['findings'][0]['level'],'REVIEW')
     self.assertEqual(self.observation(rid)['first'],clock)
 def test_orphan_usage_resets_observation_even_while_kept(self):
  clock=int(app.time.time());volume=self.add_orphan('EBS','vol-demo');address=self.add_orphan('EIP','eipalloc-demo')
  for rid in ('vol-demo','eipalloc-demo'):self.keep_resource(rid,True)
  self.assertEqual(self.scan_at(clock)['findings'],[])
  volume.update(State='in-use',Attachments=[{'InstanceId':'i-demo'}]);address['AssociationId']='eipassoc-demo'
  self.assertEqual(self.scan_at(clock+3600)['findings'],[])
  for rid in ('vol-demo','eipalloc-demo'):self.assertEqual(self.observation(rid),{})
 def test_unkeep_does_not_override_active_ignore_or_tag(self):
  clock=int(app.time.time());volume=self.add_orphan('EBS','vol-demo')
  self.keep_resource('vol-demo',True)
  with patch.object(app.time,'time',return_value=clock):
   self.assertEqual(app.api(event('PUT','/ignore',body={'region':'ap-southeast-1','resource_id':'vol-demo','days':1}),None)['statusCode'],200)
  self.assertEqual(self.scan_at(clock)['findings'],[])
  self.keep_resource('vol-demo',False)
  self.assertEqual(self.scan_at(clock+24*3600-1)['findings'],[])
  self.assertEqual(self.scan_at(clock+24*3600)['findings'][0]['level'],'REVIEW')
  volume['Tags']=[{'Key':'guardian:keep','Value':'true'}]
  self.assertEqual(self.scan_at(clock+25*3600)['findings'],[])
 def test_snapshot_incomplete_ami_inventory_never_produces_review(self):
  self.snapshots.append({'SnapshotId':'snap-demo','StartTime':datetime.now(timezone.utc)-timedelta(days=100),'State':'completed','VolumeSize':40})
  self.images.extend({'ImageId':'ami-%03d'%index} for index in range(101))
  result=self.scan()
  self.assertEqual(result['status'],'PARTIAL');self.assertEqual(result['findings'],[])
  self.assertIn({'type':'SNAPSHOT','code':'INVENTORY_TRUNCATED'},result['errors'])
 def test_snapshot_ami_access_denied_keeps_other_service_evidence(self):
  self.add_orphan('EBS','vol-demo')
  self.snapshots.append({'SnapshotId':'snap-demo','StartTime':datetime.now(timezone.utc)-timedelta(days=100),'State':'completed','VolumeSize':40})
  self.inventory_errors['describe_images']=ClientError({'Error':{'Code':'AccessDenied','Message':'denied'}},'DescribeImages')
  result=self.scan()
  self.assertEqual(result['status'],'PARTIAL')
  self.assertEqual([f['type'] for f in result['findings']],['EBS'])
  self.assertIn({'type':'SNAPSHOT','code':'AccessDenied'},result['errors'])
 def test_findings_keep_legacy_and_new_fields_through_api_and_history(self):
  clock=int(app.time.time());self.add_orphan('EBS','vol-demo');self.add_orphan('EIP','eipalloc-demo')
  self.instances.append({'InstanceId':'i-demo','State':{'Name':'running'},'LaunchTime':datetime.now(timezone.utc)-timedelta(days=8)})
  end=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
  timestamps=[end-timedelta(hours=hour+1) for hour in range(24)]
  self.cw.get_metric_data.return_value={'MetricDataResults':[{'Id':ident,'StatusCode':'Complete','Values':[0]*24,'Timestamps':timestamps} for ident in ('cpu','netin','netout')]}
  self.snapshots.append({'SnapshotId':'snap-demo','StartTime':datetime.now(timezone.utc)-timedelta(days=100),'State':'completed','VolumeSize':40})
  first=self.scan_at(clock);findings=first['findings']
  required={'type','resource_id','region','level','reason','evidence','rule_id','recommendation'}
  self.assertEqual({f['type'] for f in findings},{'EC2','EBS','EIP','SNAPSHOT'})
  for finding in findings:
   self.assertTrue(required<=finding.keys());self.assertTrue(finding['rule_id']);self.assertTrue(finding['recommendation'])
   self.assertIsInstance(finding['evidence'],dict)
  second=self.scan_at(clock+1)
  for path in ('/findings','/scans/'+first['scan_id'],'/history'):
   with self.subTest(path=path),patch.object(app.time,'time',return_value=clock+1):
    reply=app.api(event('GET',path),None);self.assertEqual(reply['statusCode'],200)
    rows=json.loads(reply['body'])['results']
    selected=next(row for row in rows if row['scan_id']==first['scan_id']) if path!='/findings' else rows[0]
    self.assertEqual(selected['findings'],findings if path!='/findings' else second['findings'])
 def test_nonfinite_or_negative_metrics_remain_json_safe(self):
  self.instances.append({'InstanceId':'i-demo','State':{'Name':'running'},'LaunchTime':datetime.now(timezone.utc)-timedelta(days=8)})
  end=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
  timestamps=[end-timedelta(hours=hour+1) for hour in range(24)]
  for value in (float('nan'),float('inf'),-1):
   with self.subTest(value=value):
    self.cw.get_metric_data.return_value={'MetricDataResults':[{'Id':ident,'StatusCode':'Complete','Values':[value]+[0]*23 if ident=='cpu' else [0]*24,'Timestamps':timestamps} for ident in ('cpu','netin','netout')]}
    self.scan_sequence+=1
    result=self.scan('%08d-0000-0000-0000-000000000000'%self.scan_sequence)
    self.assertEqual(result['findings'][0]['level'],'INSUFFICIENT_DATA')
    json.dumps(result,allow_nan=False)

if __name__=='__main__':unittest.main()
