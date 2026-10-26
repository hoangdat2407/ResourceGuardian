"""Local security and API contract checks using mocks, not AWS integration tests."""
import importlib
import json
import os
import pathlib
import sys
import time
import unittest
import uuid
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
os.environ.update(TABLE="test-table", WORKER_FUNCTION="test-worker", API_PRINCIPAL="test-api-role", SCAN_PRINCIPAL="test-worker-role")
with patch("boto3.resource"), patch("boto3.client"):
    app = importlib.import_module("app")


def event(method, path, user="alice", body=None, token_use="access", query=None):
    value = {
        "rawPath": path,
        "body": None if body is None else json.dumps(body),
        "queryStringParameters": query,
        "requestContext": {
            "http": {"method": method},
            "authorizer": {"jwt": {"claims": {"sub": user, "token_use": token_use}}},
        },
    }
    return value


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "pk": "TENANT#alice", "sk": "PROFILE", "external_id": "test-external-id",
            "settings": app.config({}), "regions": ["ap-southeast-1"],
            "service_groups": list(app.SERVICE_GROUPS), "connection_version": "v1",
        }

    def test_body_cannot_select_another_tenant(self):
        with patch.object(app, "get", return_value=self.profile), patch.object(app, "all_items", return_value=[]) as query:
            reply = app.api(event("GET", "/findings", body={"tenant": "bob", "pk": "TENANT#bob"}), None)
        self.assertEqual(reply["statusCode"], 200)
        self.assertTrue(all(call.args[0] == "TENANT#alice" for call in query.call_args_list))

    def test_non_access_or_invalid_subject_is_rejected(self):
        with patch.object(app, "get") as get:
            self.assertEqual(app.api(event("GET", "/findings", token_use="id"), None)["statusCode"], 401)
            invalid = event("GET", "/findings")
            invalid["requestContext"]["authorizer"]["jwt"]["claims"]["sub"] = 42
            self.assertEqual(app.api(invalid, None)["statusCode"], 401)
            get.assert_not_called()

    def test_unknown_route_and_wrong_method_do_not_provision(self):
        with patch.object(app, "get") as get:
            self.assertEqual(app.api(event("GET", "/unknown"), None)["statusCode"], 404)
            self.assertEqual(app.api(event("POST", "/me"), None)["statusCode"], 405)
            get.assert_not_called()

    def test_me_is_allowlisted_and_normalizes_old_profile(self):
        internal = {**self.profile, "settings": {key: value for key, value in list(app.config({}).items())[:6]}, "service_groups": None, "lease_until": 1, "secret": "x"}
        with patch.object(app, "get", return_value=internal):
            body = json.loads(app.api(event("GET", "/me"), None)["body"])
        self.assertNotIn("pk", body)
        self.assertNotIn("lease_until", body)
        self.assertNotIn("secret", body)
        self.assertEqual(body["service_groups"], list(app.SERVICE_GROUPS))
        self.assertIn("rds_cpu_percent", body["settings"])

    def test_settings_merge_preserves_new_fields(self):
        with patch.object(app, "get", return_value=self.profile), patch.object(app, "table") as table:
            reply = app.api(event("PUT", "/settings", body={"cpu_percent": 8}), None)
        body = json.loads(reply["body"])
        self.assertEqual(body["cpu_percent"], 8)
        self.assertIn("rds_connections", body)
        table.update_item.assert_called_once()

    def test_connection_validates_allowlist_account_and_rotates(self):
        sts = MagicMock()
        sts.client.return_value.get_caller_identity.return_value = {"Account": "123456789012"}
        payload = {"role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-demo", "regions": ["ap-southeast-1"], "service_groups": ["compute"]}
        with patch.object(app, "get", return_value=self.profile), patch.object(app, "session", return_value=sts), patch.object(app, "all_items", return_value=[]), patch.object(app, "put") as put:
            reply = app.api(event("PUT", "/connection", body=payload), None)
        self.assertEqual(reply["statusCode"], 200)
        saved = put.call_args.args[0]
        self.assertEqual(saved["service_groups"], ["compute"])
        self.assertNotEqual(saved["connection_version"], "v1")

    def test_connection_account_mismatch_is_rejected(self):
        sts = MagicMock()
        sts.client.return_value.get_caller_identity.return_value = {"Account": "999999999999"}
        payload = {"role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-demo", "regions": ["ap-southeast-1"]}
        with patch.object(app, "get", return_value=self.profile), patch.object(app, "session", return_value=sts), patch.object(app, "put") as put:
            reply = app.api(event("PUT", "/connection", body=payload), None)
        self.assertEqual(reply["statusCode"], 400)
        put.assert_not_called()

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

    def test_body_validation_and_scan_empty_body(self):
        oversized = event("PUT", "/settings", body={})
        oversized["body"] = "é" * 6000
        with patch.object(app, "get") as get:
            self.assertEqual(app.api(oversized, None)["statusCode"], 400)
            get.assert_not_called()
        with patch.object(app, "get", return_value={**self.profile, "role_arn": "arn"}), patch.object(app, "enqueue"):
            self.assertEqual(app.api(event("POST", "/scans", body={}), None)["statusCode"], 400)

    def test_scan_202_409_and_429(self):
        profile = {**self.profile, "role_arn": "arn", "last_queued": 0}
        with patch.object(app, "get", return_value=profile), patch.object(app, "enqueue", return_value="scan"):
            self.assertEqual(app.api(event("POST", "/scans"), None)["statusCode"], 202)
        with patch.object(app, "get", return_value=profile), patch.object(app, "enqueue", return_value=None):
            self.assertEqual(app.api(event("POST", "/scans"), None)["statusCode"], 409)
        with patch.object(app, "get", return_value={**profile, "last_queued": int(time.time())}), patch.object(app, "enqueue") as enqueue:
            self.assertEqual(app.api(event("POST", "/scans"), None)["statusCode"], 429)
            enqueue.assert_not_called()

    def test_scan_id_requires_canonical_uuid4(self):
        valid = str(uuid.uuid4())
        row = {"scan_id": valid, "connection_version": "v1", "expires": int(time.time()) + 10}
        with patch.object(app, "get", return_value=self.profile), patch.object(app, "all_items", return_value=[row]):
            self.assertEqual(app.api(event("GET", "/scans/" + valid), None)["statusCode"], 200)
        for invalid in ("11111111-1111-1111-1111-111111111111", valid.upper(), "-" * 36):
            with patch.object(app, "get", return_value=self.profile):
                self.assertEqual(app.api(event("GET", "/scans/" + invalid), None)["statusCode"], 400)

    def test_feedback_lifecycle_and_findings_overlay(self):
        ident = "a" * 64
        finding = {"finding_id": ident, "type": "EBS", "resource_id": "vol-1", "level": "REVIEW"}
        result = {"region": "ap-southeast-1", "connection_version": "v1", "findings": [finding]}
        stored = {}

        def fake_get(pk, sk):
            return self.profile if sk == "PROFILE" else stored.get(sk, {})

        def fake_put(item):
            stored[item["sk"]] = item

        def fake_items(pk, prefix):
            if prefix == "RESULT#":
                return [result]
            return [value for key, value in stored.items() if key.startswith(prefix)]

        until = datetime_iso(time.time() + 3600)
        with patch.object(app, "get", side_effect=fake_get), patch.object(app, "put", side_effect=fake_put), patch.object(app, "all_items", side_effect=fake_items):
            reply = app.api(event("PUT", "/feedback", body={"region": "ap-southeast-1", "finding_id": ident, "acknowledged": True}), None)
            self.assertEqual(reply["statusCode"], 200)
            visible = json.loads(app.api(event("GET", "/findings"), None)["body"])["results"][0]["findings"]
            self.assertTrue(visible[0]["acknowledged"])
            app.api(event("PUT", "/feedback", body={"region": "ap-southeast-1", "finding_id": ident, "ignoreUntil": until}), None)
            hidden = json.loads(app.api(event("GET", "/findings"), None)["body"])["results"][0]["findings"]
            self.assertEqual(hidden, [])
            app.api(event("PUT", "/feedback", body={"region": "ap-southeast-1", "finding_id": ident, "ignoreUntil": None}), None)
            visible = json.loads(app.api(event("GET", "/findings"), None)["body"])["results"][0]["findings"]
            self.assertEqual(len(visible), 1)

    def test_findings_and_feedback_are_empty_before_connecting(self):
        profile = {key: value for key, value in self.profile.items() if key != "connection_version"}
        for route in ("/findings", "/feedback"):
            with self.subTest(route=route), patch.object(app, "get", return_value=profile), patch.object(app, "all_items") as query:
                reply = app.api(event("GET", route), None)
                self.assertEqual(reply["statusCode"], 200)
                self.assertEqual(json.loads(reply["body"])["results"], [])
                query.assert_not_called()

    def test_feedback_clear_restores_worker_candidate_without_rewriting_history(self):
        clock = int(time.time())
        ident = "a" * 64
        finding = {"finding_id": ident, "type": "EBS", "resource_id": "vol-demo", "level": "REVIEW"}
        collected = {"findings": [finding], "counts": {"EBS": 1}, "errors": [], "partial": False}
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 200000
        for field, active, clear in (("kept", True, False), ("ignoreUntil", datetime_iso(clock + 3600), None)):
            with self.subTest(field=field):
                stored = {"PROFILE": self.profile}

                def fake_get(pk, sk):
                    return dict(stored.get(sk, {}))

                def fake_put(item):
                    stored[item["sk"]] = dict(item)

                def fake_items(pk, prefix):
                    return [value for key, value in stored.items() if key.startswith(prefix)]

                def scan(scan_id):
                    stored["RESULT#ap-southeast-1"] = {
                        "pk": self.profile["pk"], "sk": "RESULT#ap-southeast-1", "status": "QUEUED",
                        "scan_id": scan_id, "started_at": clock, "connection_version": "v1",
                    }
                    app.scan({"pk": self.profile["pk"], "region": "ap-southeast-1", "scan_id": scan_id, "connection_version": "v1"}, context)

                with patch.object(app, "get", side_effect=fake_get), patch.object(app, "put", side_effect=fake_put), patch.object(app, "all_items", side_effect=fake_items), patch.object(app, "table") as table, patch.object(app, "session"), patch.object(app, "collect_region", return_value=collected), patch.object(app.time, "time", return_value=clock):
                    table.put_item.side_effect = lambda **kwargs: fake_put(kwargs["Item"])
                    scan("first")
                    payload = {"region": "ap-southeast-1", "finding_id": ident, field: active}
                    self.assertEqual(app.api(event("PUT", "/feedback", body=payload), None)["statusCode"], 200)
                    scan("second")
                    self.assertEqual(stored["RESULT#ap-southeast-1"]["findings"], [])
                    snapshot = next(value for key, value in stored.items() if key.startswith("HISTORY#") and value["scan_id"] == "second")
                    self.assertNotIn("candidates", snapshot)
                    if field == "ignoreUntil":
                        for offset, expected in ((3599, []), (3600, [finding])):
                            with patch.object(app.time, "time", return_value=clock + offset):
                                current = json.loads(app.api(event("GET", "/findings"), None)["body"])["results"][0]
                                self.assertEqual(current["findings"], expected)
                        self.assertEqual(snapshot["findings"], [])
                    payload[field] = clear
                    self.assertEqual(app.api(event("PUT", "/feedback", body=payload), None)["statusCode"], 200)
                    current = json.loads(app.api(event("GET", "/findings"), None)["body"])["results"][0]
                    self.assertEqual(current["findings"], [finding])
                    self.assertEqual(current["finding_count"], 1)
                    self.assertNotIn("candidates", current)
                    self.assertEqual(snapshot["findings"], [])

    def test_feedback_overlay_caps_restored_candidates_and_preserves_snapshot(self):
        findings = [{"finding_id": f"{index:064x}", "resource_id": f"vol-{index}"} for index in range(60)]
        row = {"status": "SUCCEEDED", "findings": [], "candidates": findings, "finding_count": 0}
        visible = app.apply_feedback(row, {})
        self.assertEqual(visible["finding_count"], 60)
        self.assertEqual(len(visible["findings"]), 50)
        self.assertEqual(visible["status"], "PARTIAL")
        self.assertNotIn("candidates", visible)
        self.assertEqual(row["findings"], [])

    def test_scan_status_and_history_never_expose_private_candidates(self):
        scan_id = str(uuid.uuid4())
        row = {
            "status": "SUCCEEDED", "scan_id": scan_id, "connection_version": "v1",
            "findings": [], "candidates": [{"finding_id": "a" * 64}],
        }
        for path in ("/scans/" + scan_id, "/history"):
            with self.subTest(path=path), patch.object(app, "get", return_value=self.profile), patch.object(app, "all_items", return_value=[row]), patch.object(app, "page_rows", return_value=([row], None)):
                reply = app.api(event("GET", path), None)
                self.assertEqual(reply["statusCode"], 200)
                self.assertNotIn("candidates", json.loads(reply["body"])["results"][0])
        self.assertIn("candidates", row)

    def test_feedback_rejects_unknown_finding_and_cross_region(self):
        payload = {"region": "ap-southeast-2", "finding_id": "a" * 64, "kept": True}
        with patch.object(app, "get", return_value=self.profile), patch.object(app, "put") as put:
            self.assertEqual(app.api(event("PUT", "/feedback", body=payload), None)["statusCode"], 400)
            put.assert_not_called()

    def test_pagination_token_rejects_cross_tenant_and_route(self):
        token = app.encode_token({"pk": "TENANT#bob", "sk": "HISTORY#1"})
        with self.assertRaises(ValueError):
            app.decode_token(token, "TENANT#alice", "HISTORY#")
        token = app.encode_token({"pk": "TENANT#alice", "sk": "FEEDBACK#v1#x"})
        with self.assertRaises(ValueError):
            app.decode_token(token, "TENANT#alice", "HISTORY#")

    def test_provider_error_is_generic(self):
        error = ClientError({"Error": {"Code": "AccessDenied", "Message": "secret provider detail"}}, "AssumeRole")
        payload = {"role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-demo", "regions": ["ap-southeast-1"]}
        with patch.object(app, "get", return_value=self.profile), patch.object(app, "session", side_effect=error):
            reply = app.api(event("PUT", "/connection", body=payload), None)
        self.assertEqual(reply["statusCode"], 502)
        self.assertNotIn("secret provider detail", reply["body"])

    def test_revoked_role_returns_failed_worker_status(self):
        error = ClientError({"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "AssumeRole")
        job = {"pk": "TENANT#alice", "region": "ap-southeast-1", "scan_id": "s1", "connection_version": "v1"}
        with patch.object(app, "scan", side_effect=error), patch.object(app, "table") as table:
            result = app.worker(job, None)
        self.assertEqual(table.put_item.call_args.kwargs["Item"]["status"], "FAILED")
        self.assertEqual(result, {"failed": True})


def datetime_iso(timestamp):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    unittest.main()
