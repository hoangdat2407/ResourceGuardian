"""Local security/contract checks using mocks, not AWS integration tests."""
import unittest, sys, pathlib, os, json, importlib
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
os.environ.update(TABLE='test-table', WORKER_FUNCTION='test-worker', API_PRINCIPAL='test-api-role', SCAN_PRINCIPAL='test-worker-role')
with patch('boto3.resource'), patch('boto3.client'):
    app = importlib.import_module('app')

def event(method, path, user='alice', body=None, token_use='access'):
    return {'rawPath':path,'body':json.dumps(body or {}), 'requestContext':{'http':{'method':method},
            'authorizer':{'jwt':{'claims':{'sub':user,'token_use':token_use}}}}}

class ApiTest(unittest.TestCase):
    def setUp(self):
        self.profile={'pk':'TENANT#alice','sk':'PROFILE','external_id':'test-external-id','settings':app.config({}),
                      'regions':['ap-southeast-1'],'connection_version':'v1'}

    def test_body_cannot_select_another_tenant(self):
        with patch.object(app,'get',return_value=self.profile) as get, patch.object(app,'all_items',return_value=[]) as query:
            r=app.api(event('GET','/findings',body={'tenant':'bob','pk':'TENANT#bob'}),None)
            self.assertEqual(r['statusCode'],200)
            get.assert_called_once_with('TENANT#alice','PROFILE')
            query.assert_called_once_with('TENANT#alice','RESULT#')

    def test_id_token_is_rejected(self):
        with patch.object(app,'get') as get:
            self.assertEqual(app.api(event('GET','/findings',token_use='id'),None)['statusCode'],401)
            get.assert_not_called()

    def test_missing_identity_rejected(self):
        self.assertEqual(app.api({'requestContext':{}},None)['statusCode'],401)

    def test_old_connection_results_are_hidden(self):
        rows=[{'region':'ap-southeast-1','connection_version':'v0'},{'region':'ap-southeast-1','connection_version':'v1'}]
        with patch.object(app,'get',return_value=self.profile), patch.object(app,'all_items',return_value=rows):
            r=json.loads(app.api(event('GET','/findings'),None)['body'])
            self.assertEqual(len(r['results']),1)
            self.assertEqual(r['results'][0]['connection_version'],'v1')

    def test_invalid_role_never_reaches_sts(self):
        with patch.object(app,'get',return_value=self.profile), patch.object(app,'session') as sts:
            r=app.api(event('PUT','/connection',body={'role_arn':'arn:aws:iam::123456789012:role/Admin','regions':['ap-southeast-1']}),None)
            self.assertEqual(r['statusCode'],400); sts.assert_not_called()

    def test_invalid_setting_is_not_written(self):
        with patch.object(app,'get',return_value=self.profile), patch.object(app,'table') as table:
            r=app.api(event('PUT','/settings',body={'window_hours':-1}),None)
            self.assertEqual(r['statusCode'],400);table.update_item.assert_not_called()

    def test_extreme_integer_settings_are_rejected_without_writing(self):
        for field in self.profile['settings']:
            for sign in (-1,1):
                with self.subTest(field=field,sign=sign), patch.object(app,'get',return_value=self.profile), patch.object(app,'table') as table:
                    r=app.api(event('PUT','/settings',body={field:sign*10**400}),None)
                    self.assertEqual(r['statusCode'],400)
                    table.update_item.assert_not_called()

    def test_keep_is_scoped_to_identity_and_connection(self):
        profile={**self.profile,'role_arn':'arn:aws:iam::123456789012:role/GuardianReadRole-demo'}
        for enabled in (True,False):
            with self.subTest(enabled=enabled), patch.object(app,'get',return_value=profile) as get, patch.object(app,'put') as put:
                r=app.api(event('PUT','/keep',body={'region':'ap-southeast-1','resource_id':'vol-demo',
                    'enabled':enabled,'pk':'TENANT#bob','connection_version':'other'}),None)
                self.assertEqual(r['statusCode'],200)
                self.assertEqual(json.loads(r['body']),{'kept':enabled})
                get.assert_called_once_with('TENANT#alice','PROFILE')
                put.assert_called_once_with({'pk':'TENANT#alice','sk':'KEEP#v1#ap-southeast-1#vol-demo','enabled':enabled})

    def test_keep_rejects_invalid_input_without_writing(self):
        profile={**self.profile,'role_arn':'arn:aws:iam::123456789012:role/GuardianReadRole-demo'}
        valid={'region':'ap-southeast-1','resource_id':'vol-demo','enabled':True}
        invalid=[{**valid,'enabled':value} for value in (None,0,1,'true',[],{})]
        invalid += [{**valid,'region':'us-east-1'},{**valid,'resource_id':'vol#escape'},
                    {**valid,'resource_id':''},{**valid,'resource_id':None},{**valid,'resource_id':'a'*81}]
        for body in invalid:
            with self.subTest(body=body), patch.object(app,'get',return_value=profile), patch.object(app,'put') as put:
                self.assertEqual(app.api(event('PUT','/keep',body=body),None)['statusCode'],400)
                put.assert_not_called()

    def test_keep_requires_current_connection(self):
        connected={**self.profile,'role_arn':'arn:aws:iam::123456789012:role/GuardianReadRole-demo'}
        for field in ('role_arn','connection_version'):
            profile={k:v for k,v in connected.items() if k!=field}
            with self.subTest(field=field), patch.object(app,'get',return_value=profile), patch.object(app,'put') as put:
                r=app.api(event('PUT','/keep',body={'region':'ap-southeast-1','resource_id':'vol-demo','enabled':True}),None)
                self.assertEqual(r['statusCode'],400);put.assert_not_called()

    def test_keep_rejects_id_token_before_reading_or_writing(self):
        with patch.object(app,'get') as get, patch.object(app,'put') as put:
            self.assertEqual(app.api(event('PUT','/keep',token_use='id',body={'enabled':True}),None)['statusCode'],401)
            get.assert_not_called();put.assert_not_called()

    def test_settings_accepts_seven_days_but_rejects_outside_window(self):
        for hours,expected in ((24,200),(168,200),(23,400),(169,400),(24.5,400)):
            with self.subTest(hours=hours), patch.object(app,'get',return_value=self.profile), patch.object(app,'table') as table:
                r=app.api(event('PUT','/settings',body={'window_hours':hours}),None)
                self.assertEqual(r['statusCode'],expected)
                if expected==200:
                    self.assertEqual(json.loads(r['body'])['window_hours'],hours)
                    table.update_item.assert_called_once()
                else:table.update_item.assert_not_called()

    def test_revoked_role_returns_error_not_success(self):
        from botocore.exceptions import ClientError
        error=ClientError({'Error':{'Code':'AccessDenied','Message':'Denied'}},'AssumeRole')
        job={'pk':'TENANT#alice','region':'ap-southeast-1','scan_id':'s1','connection_version':'v1'}
        with patch.object(app,'scan',side_effect=error), patch.object(app,'table') as table:
            result=app.worker(job,None)
            self.assertEqual(table.put_item.call_args.kwargs['Item']['status'],'FAILED')
            self.assertEqual(result,{'failed':True})

if __name__=='__main__':unittest.main()
