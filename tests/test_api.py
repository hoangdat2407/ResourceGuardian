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

    def test_revoked_role_returns_error_not_success(self):
        from botocore.exceptions import ClientError
        error=ClientError({'Error':{'Code':'AccessDenied','Message':'Denied'}},'AssumeRole')
        job={'pk':'TENANT#alice','region':'ap-southeast-1','scan_id':'s1','connection_version':'v1'}
        with patch.object(app,'scan',side_effect=error), patch.object(app,'table') as table:
            result=app.worker(job,None)
            self.assertEqual(table.put_item.call_args.kwargs['Item']['status'],'FAILED')
            self.assertEqual(result,{'failed':True})

if __name__=='__main__':unittest.main()
