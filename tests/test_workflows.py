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
  self.instances=[];self.volumes=[];self.snapshots=[];self.images=[]
  def paginate(operation):
   paginator=MagicMock()
   keys={'describe_instances':('Reservations',[{'Instances':self.instances}]),'describe_volumes':('Volumes',self.volumes), 'describe_snapshots':('Snapshots',self.snapshots),'describe_images':('Images',self.images)}
   key,items=keys[operation];paginator.paginate.return_value=[{key:items}];return paginator
  self.ec2.get_paginator.side_effect=paginate;self.ec2.describe_addresses.return_value={'Addresses':[]}
  self.session_patch=patch.object(app,'session',return_value=self.sess);self.session_patch.start()
 def tearDown(self):self.session_patch.stop();self.table_patch.stop();self.aws.stop()
 def scan(self,sid='11111111-1111-1111-1111-111111111111'):
  app.put({'pk':self.profile['pk'],'sk':'RESULT#ap-southeast-1','scan_id':sid,'status':'QUEUED','started_at':int(app.time.time()),'region':'ap-southeast-1','connection_version':self.profile['connection_version']})
  app.worker({'pk':self.profile['pk'],'region':'ap-southeast-1','scan_id':sid,'connection_version':self.profile['connection_version']},self.context)
  return app.get(self.profile['pk'],'RESULT#ap-southeast-1')
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

if __name__=='__main__':unittest.main()
