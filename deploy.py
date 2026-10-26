"""Package Lambda and deploy the AWS SAM template using a local AWS profile.
No Docker or SAM CLI required. Python and AWS CLI v2 (for SSO login) are enough.
Use --plan to create a reviewable CloudFormation change set without executing it.
"""
import argparse, hashlib, io, json, pathlib, shutil, subprocess, sys, tempfile, time, zipfile
import boto3
from botocore.exceptions import ClientError
import yaml
from publish import publish
ROOT=pathlib.Path(__file__).resolve().parent
class CfnLoader(yaml.SafeLoader):pass
ALIASES={'Ref':'Ref','Sub':'Fn::Sub','GetAtt':'Fn::GetAtt','If':'Fn::If','Not':'Fn::Not','Equals':'Fn::Equals'}
def intrinsic(loader,tag,node):
 value=loader.construct_scalar(node) if isinstance(node,yaml.ScalarNode) else loader.construct_sequence(node) if isinstance(node,yaml.SequenceNode) else loader.construct_mapping(node)
 if tag=='GetAtt' and isinstance(value,str):value=value.split('.',1)
 return {ALIASES.get(tag,'Fn::'+tag):value}
CfnLoader.add_multi_constructor('!',intrinsic)

def artifact_bytes(path):
 """Read and validate a reviewed ZIP before any AWS call; preserve exact bytes."""
 data=pathlib.Path(path).read_bytes()
 with zipfile.ZipFile(io.BytesIO(data)) as archive:
  names=archive.namelist()
  if len(names)!=len(set(names)):raise ValueError('Artifact contains duplicate ZIP entries')
  for name in names:
   entry=pathlib.PurePosixPath(name)
   if name.startswith(('/', '\\')) or '..' in entry.parts or '\\' in name:raise ValueError('Unsafe artifact ZIP entry')
   if any(part=='.env' or part.startswith('.env.') for part in entry.parts) or entry.name in {'credentials', 'credentials.json', '.pypirc', 'id_rsa', 'id_ed25519'} or '.aws' in entry.parts:raise ValueError('Sensitive configuration/key filename in artifact')
   if entry.name=='task8_faults.py':raise ValueError('Test fault wrappers cannot be deployed with deploy.py')
  for source in (ROOT/'src').glob('*.py'):
   if archive.read(source.name)!=source.read_bytes():raise ValueError('Artifact source does not match checkout: '+source.name)
 return data

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--profile',default='guardian-lab');p.add_argument('--region',default='ap-southeast-1')
 p.add_argument('--stack',default='cloud-resource-guardian');p.add_argument('--domain-prefix',required=True)
 p.add_argument('--sender-email',default='');p.add_argument('--plan',action='store_true')
 p.add_argument('--artifact',type=pathlib.Path,help='Use this reviewed deployment ZIP without rebuilding it; fault wrappers are rejected')
 args=p.parse_args(argv)
 reviewed=artifact_bytes(args.artifact) if args.artifact else None
 session=boto3.Session(profile_name=args.profile,region_name=args.region)
 account=session.client('sts').get_caller_identity()['Account'];print('Deploy target:',account,args.region,args.stack,flush=True)
 s3=session.client('s3');cfn=session.client('cloudformation');bucket=f'crg-artifacts-{account}-{args.region}'
 try:s3.head_bucket(Bucket=bucket)
 except ClientError as e:
  if e.response['Error']['Code'] not in ('404','NoSuchBucket','NotFound'):raise
  kw={'Bucket':bucket}
  if args.region!='us-east-1':kw['CreateBucketConfiguration']={'LocationConstraint':args.region}
  s3.create_bucket(**kw)
 s3.put_public_access_block(Bucket=bucket,PublicAccessBlockConfiguration={k:True for k in ['BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets']})
 s3.put_bucket_encryption(Bucket=bucket,ServerSideEncryptionConfiguration={'Rules':[{'ApplyServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]})
 # Unique artifact keys retain the previous bundle for CloudFormation rollback.
 stamp=str(time.time_ns());key=f'{args.stack}/{stamp}/lambda.zip'
 if reviewed is not None:
  s3.put_object(Bucket=bucket,Key=key,Body=reviewed)
  print('Reviewed artifact SHA-256:',hashlib.sha256(reviewed).hexdigest(),flush=True)
 else:
  with tempfile.TemporaryDirectory() as d:
   target=pathlib.Path(d)/'package';shutil.copytree(ROOT/'src',target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
   subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','--only-binary=:all:',
                   '--platform','manylinux2014_x86_64','--python-version','3.12','--implementation','cp','--abi','cp312',
                   '--target',str(target),'-r',str(ROOT/'src/requirements.txt')],check=True)
   archive=pathlib.Path(d)/'lambda.zip'
   with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for f in target.rglob('*'):
     if f.is_file() and '__pycache__' not in f.parts:z.write(f,f.relative_to(target))
   s3.upload_file(str(archive),bucket,key)
 template=yaml.load((ROOT/'template.yaml').read_text(),Loader=CfnLoader)
 template['Globals']['Function']['CodeUri']={'Bucket':bucket,'Key':key}
 try:cfn.describe_stacks(StackName=args.stack);kind='UPDATE'
 except ClientError as e:
  if 'does not exist' not in e.response['Error'].get('Message',''):raise
  kind='CREATE'
 name='guardian-'+stamp
 cfn.create_change_set(StackName=args.stack,ChangeSetName=name,ChangeSetType=kind,
  TemplateBody=json.dumps(template),Capabilities=['CAPABILITY_IAM','CAPABILITY_AUTO_EXPAND'],
  Parameters=[{'ParameterKey':'DomainPrefix','ParameterValue':args.domain_prefix},{'ParameterKey':'SenderEmail','ParameterValue':args.sender_email}])
 try:cfn.get_waiter('change_set_create_complete').wait(StackName=args.stack,ChangeSetName=name,WaiterConfig={'Delay':5,'MaxAttempts':120})
 except Exception:
  details=cfn.describe_change_set(StackName=args.stack,ChangeSetName=name)
  print('Change set status:',details['Status'],details.get('StatusReason',''))
  if 'didn\'t contain changes' in details.get('StatusReason',''):return
  raise
 details=cfn.describe_change_set(StackName=args.stack,ChangeSetName=name)
 for item in details.get('Changes',[]):
  r=item['ResourceChange'];print(r['Action'],r['LogicalResourceId'],r['ResourceType'], 'replacement='+r.get('Replacement','False'))
 if args.plan:
  print('Plan ready. Execute this reviewed change set with:')
  print('aws cloudformation execute-change-set --stack-name',args.stack,'--change-set-name',name,'--region',args.region,'--profile',args.profile)
  print('After CREATE_COMPLETE / UPDATE_COMPLETE, run publish.py. Artifacts uploaded to',bucket)
  return
 print('Creating/updating AWS infrastructure. CloudFront can take several minutes.',flush=True)
 cfn.execute_change_set(StackName=args.stack,ChangeSetName=name)
 waiter='stack_create_complete' if kind=='CREATE' else 'stack_update_complete'
 try:cfn.get_waiter(waiter).wait(StackName=args.stack,WaiterConfig={'Delay':15,'MaxAttempts':120})
 except Exception:
  for e in cfn.describe_stack_events(StackName=args.stack)['StackEvents'][:15]:
   if 'FAILED' in e['ResourceStatus']:print(e['LogicalResourceId'],e.get('ResourceStatusReason',''))
  raise
 publish(session,args.stack)
if __name__=='__main__':main()
