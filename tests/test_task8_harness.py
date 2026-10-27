"""Offline safety and artifact checks. These tests never contact AWS."""
import importlib.util
import base64
import contextlib
import hashlib
import io
import json
import os
import pathlib
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import MagicMock, patch

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("task8_aws_harness", HERE / "task8_aws_harness.py")
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)
DEPLOY_SPEC = importlib.util.spec_from_file_location("task8_deployment", HERE.parent / "deploy.py")
deployment = importlib.util.module_from_spec(DEPLOY_SPEC)
DEPLOY_SPEC.loader.exec_module(deployment)


def manifest():
    return {
        "account_id": "123456789012", "region": "ap-southeast-1", "stack": harness.TEST_STACK,
        "reviewer": "reviewer-a", "executor": "executor-b", "final_zip_sha256": "a" * 64,
        "source_tree_sha256": "b" * 64,
        "users": [
            {"label": "alice", "token_env": "CRG_TASK8_ALICE_TOKEN", "role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-task8-alice", "regions": ["ap-southeast-1"]},
            {"label": "bob", "token_env": "CRG_TASK8_BOB_TOKEN", "role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-task8-bob", "regions": ["ap-southeast-1"]},
        ],
    }


def make_zip(path, extra=None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in (harness.ROOT / "src").glob("*.py"):
            archive.write(source, source.name)
        if extra:
            for name, value in extra.items():
                archive.writestr(name, value)


class HarnessSafetyTests(unittest.TestCase):
    def setUp(self):
        # Use an immutable source fixture while other agents edit the real tree.
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = pathlib.Path(directory.name)
        (root / "src").mkdir()
        for name in ("app.py", "rules.py", "collectors.py"):
            (root / "src" / name).write_text("# stable source fixture\n", encoding="utf-8")
        identity = {"git_sha": "f" * 40, "source_dirty": False, "source_tree_sha256": "b" * 64, "files": {}}
        root_patch = patch.object(harness, "ROOT", root)
        deploy_root_patch = patch.object(deployment, "ROOT", root)
        identity_patch = patch.object(harness, "source_identity", return_value=identity)
        root_patch.start()
        deploy_root_patch.start()
        identity_patch.start()
        self.addCleanup(root_patch.stop)
        self.addCleanup(deploy_root_patch.stop)
        self.addCleanup(identity_patch.stop)

    def test_manifest_requires_isolated_stack_distinct_users_roles_and_identities(self):
        self.assertEqual(harness.validate_manifest(manifest())["stack"], harness.TEST_STACK)
        mutations = [
            lambda value: value.update(stack="cloud-resource-guardian"),
            lambda value: value.update(region="us-east-1"),
            lambda value: value.update(executor=value["reviewer"]),
            lambda value: value["users"][1].update(token_env=value["users"][0]["token_env"]),
            lambda value: value["users"][1].update(role_arn=value["users"][0]["role_arn"]),
            lambda value: value["users"][0].update(role_arn="arn:aws:iam::999999999999:role/GuardianReadRole-task8-alice"),
            lambda value: value["users"][0].update(token_env="AWS_SECRET_ACCESS_KEY"),
            lambda value: value.update(access_token="must-not-be-in-manifest"),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                value = manifest()
                mutate(value)
                with self.assertRaises(ValueError):
                    harness.validate_manifest(value)

    def test_run_gate_fails_before_aws_session_is_constructed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest()), encoding="utf-8")
            with patch.dict(os.environ, {"CRG_TASK8_AWS": "0"}), patch.object(harness.boto3, "Session") as session:
                with self.assertRaisesRegex(ValueError, "Run requires"):
                    harness.main(["run", "--artifact", "unused.zip", "--manifest", str(path), "--allow-mutations", "--confirm-account", "123456789012"])
                session.assert_not_called()

    def test_dirty_source_is_rejected_for_aws_acceptance_before_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest()), encoding="utf-8")
            with patch.dict(os.environ, {"CRG_TASK8_AWS": "1"}), patch.object(harness, "source_identity", return_value={"source_dirty": True}), patch.object(harness.boto3, "Session") as session:
                with self.assertRaisesRegex(ValueError, "Commit the reviewed"):
                    harness.main(["run", "--artifact", "unused.zip", "--manifest", str(path), "--allow-mutations", "--confirm-account", "123456789012"])
                session.assert_not_called()

    def test_package_keeps_wrapper_out_of_final_and_pins_source_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = pathlib.Path(directory) / "input.zip"
            make_zip(artifact)
            output = pathlib.Path(directory) / "out"
            result = harness.package(artifact, output)
            self.assertEqual(result["final_zip_sha256"], harness.sha256(artifact.read_bytes()))
            with zipfile.ZipFile(output / "task8-final.zip") as archive:
                self.assertNotIn("task8_faults.py", archive.namelist())
                self.assertEqual(archive.read("app.py"), (harness.ROOT / "src/app.py").read_bytes())
            with zipfile.ZipFile(output / "task8-faults.zip") as archive:
                self.assertEqual(archive.read("task8_faults.py"), harness.FAULT_SOURCE.encode())
            self.assertEqual(json.loads((output / "artifacts.json").read_text())["source_tree_sha256"], result["source_tree_sha256"])

    def test_final_archive_rejects_wrapper_source_mismatch_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = pathlib.Path(directory) / "input.zip"
            for extra in ({"task8_faults.py": "test"}, {"../secret": "test"}, {".env": "must-not-ship"}, {"folder/.aws/credentials": "must-not-ship"}):
                make_zip(artifact, extra)
                with self.assertRaises(ValueError):
                    harness.checked_archive(artifact)
            with zipfile.ZipFile(artifact, "w") as archive:
                archive.writestr("app.py", "different source")
            with self.assertRaises(ValueError):
                harness.checked_archive(artifact)

    def test_fault_archive_cannot_change_dependencies_or_add_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = pathlib.Path(directory) / "input.zip"
            make_zip(artifact, {"boto3/__init__.py": "# pinned dependency"})
            output = pathlib.Path(directory) / "out"
            harness.package(artifact, output)
            fault = output / "task8-faults.zip"
            self.assertEqual(harness.checked_fault_archive(fault, artifact.read_bytes()), fault.read_bytes())
            changed = pathlib.Path(directory) / "changed.zip"
            with zipfile.ZipFile(fault) as source, zipfile.ZipFile(changed, "w") as target:
                for entry in source.infolist():
                    target.writestr(entry, "# changed dependency" if entry.filename == "boto3/__init__.py" else source.read(entry.filename))
            with self.assertRaisesRegex(ValueError, "changes a final source/dependency"):
                harness.checked_fault_archive(changed, artifact.read_bytes())

    def test_deploy_rejects_test_wrapper_before_constructing_aws_session(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = pathlib.Path(directory) / "bad.zip"
            make_zip(artifact, {"task8_faults.py": harness.FAULT_SOURCE})
            with patch.object(deployment.boto3, "Session") as session:
                with self.assertRaisesRegex(ValueError, "Test fault wrappers"):
                    deployment.main(["--domain-prefix", "task8-local-only", "--artifact", str(artifact), "--plan"])
                session.assert_not_called()

    def test_deploy_rejects_known_secret_filenames_before_any_aws_call(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = pathlib.Path(directory) / "bad.zip"
            make_zip(artifact, {".env.local": "must-not-ship"})
            with patch.object(deployment.boto3, "Session") as session:
                with self.assertRaisesRegex(ValueError, "Sensitive configuration"):
                    deployment.main(["--domain-prefix", "task8-local-only", "--artifact", str(artifact), "--plan"])
                session.assert_not_called()

    def test_deploy_plan_uses_exact_reviewed_zip_without_pip_or_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = pathlib.Path(directory) / "final.zip"
            make_zip(artifact)
            (deployment.ROOT / "template.yaml").write_text("Globals:\n  Function:\n    CodeUri: src/\nResources: {}\n", encoding="utf-8")
            session = MagicMock()
            s3, cfn, sts = MagicMock(), MagicMock(), MagicMock()
            session.client.side_effect = lambda name: {"s3": s3, "cloudformation": cfn, "sts": sts}[name]
            sts.get_caller_identity.return_value = {"Account": "123456789012"}
            cfn.describe_change_set.return_value = {"Changes": []}
            with contextlib.redirect_stdout(io.StringIO()), patch.object(deployment.boto3, "Session", return_value=session), patch.object(deployment.subprocess, "run") as pip:
                deployment.main(["--domain-prefix", "task8-local-only", "--stack", harness.TEST_STACK, "--artifact", str(artifact), "--plan"])
            self.assertEqual(s3.put_object.call_args.kwargs["Body"], artifact.read_bytes())
            s3.upload_file.assert_not_called()
            pip.assert_not_called()
            cfn.create_change_set.assert_called_once()
            cfn.execute_change_set.assert_not_called()

    def test_evidence_projection_omits_payload_credentials_and_internal_fields(self):
        row = {"scan_id": "safe-id", "region": "ap-southeast-1", "status": "FAILED", "error_code": "ACCESS_DENIED",
               "error": "untrusted raw credentials", "pk": "private", "findings": [{"resource_id": "private"}],
               "token": "secret", "requestPayload": {"credentials": "secret"}}
        safe = harness.safe_result(row)
        self.assertEqual(set(safe), {"scan_id", "region", "status", "error_code"})
        self.assertNotIn("secret", json.dumps(safe))

    def test_fault_installation_restores_final_artifact_when_scan_setup_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = pathlib.Path(directory) / "input.zip"
            make_zip(artifact)
            output = pathlib.Path(directory) / "out"
            result = harness.package(artifact, output)
            value = manifest()
            value.update(final_zip_sha256=result["final_zip_sha256"], source_tree_sha256=result["source_tree_sha256"])
            instance = harness.Harness(value, MagicMock(), artifact, pathlib.Path(directory) / "evidence.json")
            instance.users = [{"pk": "TENANT#alice"}]
            instance.resources = {"WorkerFunction": "test-worker", "RecoveryFunction": "test-recovery"}
            client = MagicMock()
            client.get_function_configuration.side_effect = [
                {"Handler": "app.worker", "Environment": {"Variables": {"TABLE": "test-table"}}},
                {"Handler": "app.recovery", "Environment": {"Variables": {"TABLE": "test-table"}}},
                {"Handler": "app.worker", "Environment": {"Variables": {"TABLE": "test-table"}}, "CodeSha256": base64.b64encode(hashlib.sha256(artifact.read_bytes()).digest()).decode()},
                {"Handler": "app.recovery", "Environment": {"Variables": {"TABLE": "test-table"}}, "CodeSha256": base64.b64encode(hashlib.sha256(artifact.read_bytes()).digest()).decode()},
            ]
            with patch.object(instance, "client", return_value=client), patch.object(instance, "prepare"), patch.object(instance, "wait_updated"), patch.object(instance, "start", side_effect=AssertionError("test setup failure")):
                with self.assertRaisesRegex(AssertionError, "test setup failure"):
                    instance.fault("transient", output / "task8-faults.zip")
            uploads = client.update_function_code.call_args_list
            self.assertEqual(len(uploads), 4)
            self.assertEqual(uploads[-2].kwargs["ZipFile"], artifact.read_bytes())
            self.assertEqual(uploads[-1].kwargs["ZipFile"], artifact.read_bytes())
            restored = client.update_function_configuration.call_args_list[-2:]
            self.assertEqual([call.kwargs["Handler"] for call in restored], ["app.worker", "app.recovery"])
            self.assertEqual(restored[0].kwargs["Environment"], {"Variables": {"TABLE": "test-table"}})
            self.assertTrue(instance.evidence["steps"][-1]["restored"])

    def test_hard_timeout_cannot_pass_from_event_expiry_without_worker_timeout(self):
        rows = [{"status": "TIMED_OUT", "error_code": "EVENT_AGE_EXCEEDED"}]
        deliveries = [{"event": "task8_failure_delivery", "condition": "EventAgeExceeded"}]
        with self.assertRaisesRegex(AssertionError, "platform timeout"):
            harness.verify_fault_evidence("hard-timeout", rows, [], deliveries)
        worker = [{"event": "task8_fault", "mode": "hard-timeout", "request_id": "request-a"}]
        with self.assertRaisesRegex(AssertionError, "platform timeout"):
            harness.verify_fault_evidence("hard-timeout", rows, worker, deliveries, False)
        harness.verify_fault_evidence("hard-timeout", rows, worker, deliveries, True)

    def test_exhausted_case_requires_actual_retry_delivery_and_error_code(self):
        workers = [{"event": "task8_fault", "mode": "exhausted", "request_id": "request-" + str(index)} for index in range(3)]
        deliveries = [{"event": "task8_failure_delivery", "condition": "RetriesExhausted", "invoke_count": 3}]
        with self.assertRaisesRegex(AssertionError, "did not come from failure recovery"):
            harness.verify_fault_evidence("exhausted", [{"status": "FAILED", "error_code": "DISPATCH_FAILED"}], workers, deliveries)
        with self.assertRaisesRegex(AssertionError, "three worker invocations"):
            harness.verify_fault_evidence("exhausted", [{"error_code": "RETRIES_EXHAUSTED"}], workers[:2], deliveries)
        harness.verify_fault_evidence("exhausted", [{"error_code": "RETRIES_EXHAUSTED"}], workers, deliveries)

    def test_platform_timeout_must_match_the_injected_worker_request_id(self):
        instance = object.__new__(harness.Harness)
        instance.resources = {"WorkerFunction": "test-worker"}
        instance.record = MagicMock()
        client = MagicMock()
        logs = [{"event": "task8_fault", "mode": "hard-timeout", "request_id": "request-a"}]
        unrelated = {"message": "REPORT RequestId: request-b Status: timeout", "logStreamName": "stream", "eventId": "event", "timestamp": 1000}
        client.get_paginator.return_value.paginate.return_value = [{"events": [unrelated]}]
        with patch.object(instance, "client", return_value=client):
            self.assertFalse(instance.platform_timeout("scan-a", logs, 1))
            matching = {**unrelated, "message": "REPORT RequestId: request-a Duration: 300000 ms Status: timeout"}
            client.get_paginator.return_value.paginate.return_value = [{"events": [matching]}]
            self.assertTrue(instance.platform_timeout("scan-a", logs, 1))
        instance.record.assert_called_once()
        self.assertEqual(instance.record.call_args.kwargs["request_id"], "request-a")


class FaultWrapperTests(unittest.TestCase):
    def setUp(self):
        self.app = types.ModuleType("app")
        self.app.worker = MagicMock(return_value={"processed": True})
        self.app.recovery = MagicMock(return_value={"batchItemFailures": []})
        self.app.table = MagicMock()
        self.app.collect_region = MagicMock()
        self.wrapper = types.ModuleType("task8_faults")
        with patch.dict(sys.modules, {"app": self.app}):
            exec(compile(harness.FAULT_SOURCE, "task8_faults.py", "exec"), self.wrapper.__dict__)
        self.context = types.SimpleNamespace(aws_request_id="request-id")
        self.job = {"pk": "TENANT#alice", "scan_id": "scan-a", "region": "ap-southeast-1", "connection_version": "v1"}
        self.env = {"TASK8_STACK": harness.TEST_STACK, "TASK8_TENANT": self.job["pk"], "TASK8_FAULT_MODE": "exhausted"}

    def test_fault_wrapper_is_inactive_for_other_stack_or_other_tenant(self):
        for overrides in ({"TASK8_STACK": "cloud-resource-guardian"}, {"TASK8_TENANT": "TENANT#other"}):
            with self.subTest(overrides=overrides), patch.dict(os.environ, {**self.env, **overrides}):
                self.assertEqual(self.wrapper.worker(dict(self.job), self.context), {"processed": True})
        self.app.table.update_item.assert_not_called()

    def test_transient_injection_fails_once_then_uses_real_worker(self):
        self.app.table.update_item.side_effect = [{"Attributes": {"task8_fault_attempt": 1}}, {"Attributes": {"task8_fault_attempt": 2}}]
        with patch.dict(os.environ, {**self.env, "TASK8_FAULT_MODE": "transient"}):
            with self.assertRaisesRegex(RuntimeError, "TASK8_TEST_TRANSIENT"):
                self.wrapper.worker(dict(self.job), self.context)
            self.assertEqual(self.wrapper.worker(dict(self.job), self.context), {"processed": True})
        self.app.worker.assert_called_once()
        self.assertIn("connection_version = :version", self.app.table.update_item.call_args.kwargs["ConditionExpression"])

    def test_consumer_fault_marks_only_target_tenant_for_retry(self):
        target = {"messageId": "target", "body": json.dumps({"requestPayload": self.job, "requestContext": {"condition": "RetriesExhausted"}})}
        other = {"messageId": "other", "body": json.dumps({"requestPayload": {**self.job, "pk": "TENANT#bob"}})}
        with patch.dict(os.environ, {**self.env, "TASK8_FAULT_MODE": "consumer"}):
            result = self.wrapper.recovery({"Records": [target, other]}, self.context)
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "target"}]})
        self.assertEqual(self.app.recovery.call_args.args[0], {"Records": [other]})


if __name__ == "__main__":
    unittest.main()
