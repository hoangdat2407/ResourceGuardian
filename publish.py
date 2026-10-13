"""Publish the frontend after deploy. Uses a local AWS profile, never accepts secrets."""
import argparse, json, pathlib, time
import boto3

def publish(session, stack):
 out=session.client('cloudformation').describe_stacks(StackName=stack)['Stacks'][0]['Outputs']
 o={x['OutputKey']:x['OutputValue'] for x in out}
 cfg={'api':o['ApiUrl'],'clientId':o['CognitoClientId'],'auth':o['CognitoDomain'],'redirect':o['WebUrl']}
 s3=session.client('s3')
 s3.put_object(Bucket=o['WebBucket'],Key='config.json',Body=json.dumps(cfg).encode(),ContentType='application/json',CacheControl='no-store')
 for filename,mime in [('index.html','text/html; charset=utf-8'),('styles.css','text/css; charset=utf-8'),('app.js','application/javascript; charset=utf-8')]:
  s3.put_object(Bucket=o['WebBucket'],Key=filename,Body=pathlib.Path(__file__).with_name('web').joinpath(filename).read_bytes(),ContentType=mime,CacheControl='no-store')
 session.client('cloudfront').create_invalidation(DistributionId=o['DistributionId'],InvalidationBatch={'Paths':{'Quantity':1,'Items':['/*']},'CallerReference':str(time.time_ns())})
 print('WebUrl:',o['WebUrl'],flush=True)
 return o
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stack',default='cloud-resource-guardian');p.add_argument('--region',default='ap-southeast-1');p.add_argument('--profile',default='guardian-lab');args=p.parse_args()
 publish(boto3.Session(profile_name=args.profile,region_name=args.region),args.stack)
