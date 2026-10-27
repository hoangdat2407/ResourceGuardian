"""Opt-in Task 8 AWS checks for the isolated task8-test stack.

`package` is offline. `inspect` makes read-only AWS calls. `run` writes test
fixtures and calls the test API; it requires both an environment switch and
explicit CLI confirmation. No command provisions stacks, users or read roles.
"""
import argparse
import base64
import concurrent.futures
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEST_STACK = "cloud-resource-guardian-task8-test"
TERMINAL = {"SUCCEEDED", "PARTIAL", "FAILED", "TIMED_OUT"}
GOOD = {"SUCCEEDED", "PARTIAL"}
FAULTS = {"transient", "exhausted", "hard-timeout", "consumer"}
SCENARIOS = ("smoke", "schedule", "race", "duplicate", "reconnect", "orphan", *sorted(FAULTS), "final-smoke")
SAFE_RESULT = (
    "region", "scan_id", "status", "trigger", "created_at", "started_at",
    "completed_at", "deadline_at", "attempt_count", "error_code", "expires",
)
SDK_CONFIG = Config(retries={"mode": "standard", "total_max_attempts": 3}, connect_timeout=5, read_timeout=15)

# This module is inserted only into the fault ZIP, never src/ or the final ZIP.
# It deliberately avoids logging the job, envelope, profile or credentials.
FAULT_SOURCE = '''"""Task 8 fault injection. Isolated test artifacts only."""
import json
import logging
import os
import time
import app

log = logging.getLogger()
log.setLevel(logging.INFO)

def _enabled(pk):
    return (os.environ.get("TASK8_STACK") == "cloud-resource-guardian-task8-test"
            and pk == os.environ.get("TASK8_TENANT"))

def worker(job, context):
    mode = os.environ.get("TASK8_FAULT_MODE", "")
    if not _enabled(job.get("pk")) or mode not in {"transient", "exhausted", "hard-timeout", "consumer"}:
        return app.worker(job, context)
    log.info(json.dumps({"event": "task8_fault", "mode": mode, "scan_id": job.get("scan_id"),
                         "region": job.get("region"), "request_id": context.aws_request_id}))
    if mode == "transient":
        reply = app.table.update_item(
            Key={"pk": job["pk"], "sk": "RESULT#" + job["region"]},
            UpdateExpression="ADD task8_fault_attempt :one",
            ConditionExpression="scan_id = :id AND connection_version = :version",
            ExpressionAttributeValues={":one": 1, ":id": job["scan_id"], ":version": job["connection_version"]},
            ReturnValues="UPDATED_NEW")
        if int(reply["Attributes"]["task8_fault_attempt"]) == 1:
            raise RuntimeError("TASK8_TEST_TRANSIENT")
    elif mode in {"exhausted", "consumer"}:
        raise RuntimeError("TASK8_TEST_EXHAUSTED")
    else:
        original = app.collect_region
        def block(*args, **kwargs):
            time.sleep(context.get_remaining_time_in_millis() / 1000 + 5)
        app.collect_region = block
        try:
            return app.worker(job, context)
        finally:
            app.collect_region = original
    return app.worker(job, context)

def recovery(event, context):
    failed = []
    accepted = []
    for record in event.get("Records", []):
        try:
            envelope = json.loads(record.get("body", ""))
            job = envelope.get("requestPayload", {})
            details = envelope.get("requestContext", {})
        except (ValueError, AttributeError):
            accepted.append(record)
            continue
        if _enabled(job.get("pk")):
            log.info(json.dumps({"event": "task8_failure_delivery", "scan_id": job.get("scan_id"),
                                 "region": job.get("region"), "request_id": context.aws_request_id,
                                 "worker_request_id": details.get("requestId"),
                                 "condition": details.get("condition"),
                                 "invoke_count": details.get("approximateInvokeCount"),
                                 "message_id": record.get("messageId"),
                                 "receive_count": record.get("attributes", {}).get("ApproximateReceiveCount")}))
            if os.environ.get("TASK8_FAULT_MODE") == "consumer":
                failed.append({"itemIdentifier": record["messageId"]})
                continue
        accepted.append(record)
    if accepted:
        failed.extend(app.recovery({"Records": accepted}, context).get("batchItemFailures", []))
    return {"batchItemFailures": failed}
'''


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def source_identity():
    paths = [*sorted((ROOT / "src").glob("*.py")), ROOT / "src/requirements.txt", ROOT / "template.yaml"]
    files = {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()) for path in paths}
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--", "src", "template.yaml"], cwd=ROOT, text=True).strip())
    return {"git_sha": git_sha, "source_dirty": dirty, "source_tree_sha256": sha256(json.dumps(files, sort_keys=True).encode()), "files": files}


def checked_archive(path):
    data = pathlib.Path(path).read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Final ZIP contains duplicate entries")
        for name in names:
            if name.startswith(("/", "\\")) or ".." in pathlib.PurePosixPath(name).parts or "\\" in name:
                raise ValueError("Unsafe ZIP entry")
            entry = pathlib.PurePosixPath(name)
            if any(part == ".env" or part.startswith(".env.") for part in entry.parts) or entry.name in {"credentials", "credentials.json", ".pypirc", "id_rsa", "id_ed25519"} or ".aws" in entry.parts:
                raise ValueError("Deployment ZIP contains a sensitive configuration/key filename")
            if entry.name == "task8_faults.py":
                raise ValueError("Final ZIP must not contain a Task 8 fault wrapper")
        for source in (ROOT / "src").glob("*.py"):
            if archive.read(source.name) != source.read_bytes():
                raise ValueError("Final ZIP source does not match checkout: " + source.name)
    return data


def checked_fault_archive(path, final_bytes):
    data = pathlib.Path(path).read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as fault, zipfile.ZipFile(io.BytesIO(final_bytes)) as final:
        names = fault.namelist()
        if len(names) != len(set(names)) or set(names) != set(final.namelist()) | {"task8_faults.py"}:
            raise ValueError("Fault ZIP must contain only the final ZIP entries plus the wrapper")
        if fault.read("task8_faults.py") != FAULT_SOURCE.encode():
            raise ValueError("Fault wrapper does not match this harness")
        if any(fault.read(name) != final.read(name) for name in final.namelist()):
            raise ValueError("Fault artifact changes a final source/dependency")
    return data


def package(artifact, output_dir):
    final_bytes = checked_archive(artifact)
    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / "task8-final.zip"
    fault_path = output_dir / "task8-faults.zip"
    if final_path.resolve() == pathlib.Path(artifact).resolve():
        raise ValueError("Use an output directory distinct from the input artifact")
    final_path.write_bytes(final_bytes)
    with zipfile.ZipFile(io.BytesIO(final_bytes)) as source, zipfile.ZipFile(fault_path, "w", zipfile.ZIP_DEFLATED) as target:
        for entry in source.infolist():
            target.writestr(entry, source.read(entry.filename))
        target.writestr("task8_faults.py", FAULT_SOURCE.encode("utf-8"))
    manifest = {
        **source_identity(), "packaged_at": utc_now(), "final_zip_sha256": sha256(final_bytes),
        "fault_zip_sha256": sha256(fault_path.read_bytes()), "fault_wrapper_in_final": False,
    }
    (output_dir / "artifacts.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def validate_manifest(value):
    required = {"account_id", "region", "stack", "reviewer", "executor", "users", "final_zip_sha256", "source_tree_sha256"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Manifest fields must be exactly: " + ", ".join(sorted(required)))
    if value["stack"] != TEST_STACK or value["region"] != "ap-southeast-1":
        raise ValueError("Harness only accepts the isolated Task 8 stack in ap-southeast-1")
    if not isinstance(value["account_id"], str) or not re.fullmatch(r"\d{12}", value["account_id"]):
        raise ValueError("account_id must be a 12 digit string")
    if any(not isinstance(value[key], str) or not value[key].strip() for key in ("reviewer", "executor")) or value["reviewer"] == value["executor"]:
        raise ValueError("Distinct reviewer and executor identities are required")
    for name in ("final_zip_sha256", "source_tree_sha256"):
        if not isinstance(value[name], str) or not re.fullmatch(r"[0-9a-f]{64}", value[name]):
            raise ValueError(name + " must be a lowercase SHA-256")
    users = value["users"]
    if not isinstance(users, list) or len(users) != 2:
        raise ValueError("Exactly two real test users are required")
    for user in users:
        if not isinstance(user, dict) or set(user) != {"label", "token_env", "role_arn", "regions"}:
            raise ValueError("Each user needs label, token_env, role_arn and regions")
        if not isinstance(user["label"], str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", user["label"]):
            raise ValueError("Invalid test user label")
        if not isinstance(user["token_env"], str) or not re.fullmatch(r"CRG_TASK8_[A-Z0-9_]+_TOKEN", user["token_env"]):
            raise ValueError("Tokens must be read from a named CRG_TASK8_*_TOKEN environment variable")
        pattern = r"arn:aws:iam::" + value["account_id"] + r":role/GuardianReadRole-task8-[A-Za-z0-9_-]{1,30}"
        if not isinstance(user["role_arn"], str) or not re.fullmatch(pattern, user["role_arn"]):
            raise ValueError("Use dedicated GuardianReadRole-task8-* roles in the confirmed account")
        if user["regions"] != [value["region"]]:
            raise ValueError("Test fixtures are restricted to the stack region")
    for name in ("label", "token_env", "role_arn"):
        if users[0][name] == users[1][name]:
            raise ValueError("Test users must have distinct " + name)
    return value


def safe_result(row):
    return {key: row[key] for key in SAFE_RESULT if key in row}


def verify_fault_evidence(mode, rows, worker_logs, recovery_logs, platform_timeout=False):
    invocations = {row.get("request_id") for row in worker_logs
                   if row.get("event") == "task8_fault" and row.get("mode") == mode and row.get("request_id")}
    deliveries = [row for row in recovery_logs if row.get("event") == "task8_failure_delivery"]
    if mode == "transient":
        if len(invocations) < 2:
            raise AssertionError("Transient case did not show a real retry of the injected worker")
    elif mode == "exhausted":
        if len(invocations) != 3 or not any(row.get("condition") == "RetriesExhausted" and row.get("invoke_count") == 3 for row in deliveries):
            raise AssertionError("Exhausted case did not show three worker invocations and actual RetriesExhausted delivery")
        if not rows or any(row.get("error_code") != "RETRIES_EXHAUSTED" for row in rows):
            raise AssertionError("Exhausted result did not come from failure recovery")
    elif mode == "hard-timeout":
        if not invocations or not platform_timeout:
            raise AssertionError("Hard-timeout case needs an injected worker invocation and its platform timeout record")
    elif mode == "consumer":
        if not any(int(row.get("receive_count") or 0) >= 5 for row in deliveries):
            raise AssertionError("Consumer case did not show five failed receives before redrive")
    if mode != "transient" and not deliveries:
        raise AssertionError("No actual Lambda OnFailure delivery diagnostic found")


def decode_claims(token):
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError, UnicodeDecodeError) as error:
        raise ValueError("Malformed test access token") from error
    if not isinstance(claims, dict):
        raise ValueError("Malformed test access token claims")
    return claims


class Harness:
    def __init__(self, manifest, session, artifact, evidence_path):
        self.manifest = validate_manifest(manifest)
        self.session = session
        self.final_bytes = checked_archive(artifact)
        self.identity = source_identity()
        if sha256(self.final_bytes) != manifest["final_zip_sha256"] or self.identity["source_tree_sha256"] != manifest["source_tree_sha256"]:
            raise ValueError("Manifest artifact/source hashes do not match the final checkout")
        self.evidence_path = pathlib.Path(evidence_path)
        self.evidence = {
            "started_at": utc_now(), "stack": manifest["stack"], "region": manifest["region"],
            "account_id": manifest["account_id"], "reviewer": manifest["reviewer"],
            "executor": manifest["executor"], **self.identity,
            "final_zip_sha256": manifest["final_zip_sha256"], "steps": [], "status": "STARTED",
        }
        self.clients = {}
        self.resources = {}
        self.users = []

    def client(self, name):
        if name not in self.clients:
            self.clients[name] = self.session.client(name, config=SDK_CONFIG)
        return self.clients[name]

    def record(self, event, **details):
        self.evidence["steps"].append({"at": utc_now(), "event": event, **details})
        self.save()

    def save(self):
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        self.evidence_path.write_text(json.dumps(self.evidence, indent=2, default=str) + "\n", encoding="utf-8")

    def inspect(self):
        account = self.client("sts").get_caller_identity()["Account"]
        if account != self.manifest["account_id"]:
            raise ValueError("Current AWS identity does not match confirmed account")
        cfn = self.client("cloudformation")
        stack = cfn.describe_stacks(StackName=TEST_STACK)["Stacks"][0]
        if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
            raise ValueError("Test stack is not stable")
        outputs = {item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])}
        for page in cfn.get_paginator("list_stack_resources").paginate(StackName=TEST_STACK):
            for item in page["StackResourceSummaries"]:
                self.resources[item["LogicalResourceId"]] = item["PhysicalResourceId"]
        needed = {"Data", "WorkerFunction", "ScheduleFunction", "RecoveryFunction", "ReconcileFunction", "DeadLetters", "OperationsDeadLetters", "UserPool"}
        if not needed <= set(self.resources):
            raise ValueError("Test stack does not have the Task 8 resources")
        self.base_url = outputs["ApiUrl"].rstrip("/")
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme != "https" or parsed.query or parsed.fragment or parsed.username or not parsed.hostname.endswith(".execute-api.ap-southeast-1.amazonaws.com"):
            raise ValueError("API URL must be the stack's regional API Gateway HTTPS endpoint")
        pool = self.client("cognito-idp").describe_user_pool(UserPoolId=self.resources["UserPool"])["UserPool"]
        if not pool.get("AdminCreateUserConfig", {}).get("AllowAdminCreateUserOnly"):
            raise ValueError("Test UserPool must be admin-only")
        user_count = sum(len(page.get("Users", [])) for page in self.client("cognito-idp").get_paginator("list_users").paginate(UserPoolId=self.resources["UserPool"]))
        if user_count > 5:
            raise ValueError("Test UserPool has more than 5 internal users")
        worker = self.client("lambda").get_function_configuration(FunctionName=self.resources["WorkerFunction"])
        if worker.get("Environment", {}).get("Variables", {}).get("SES_SENDER"):
            raise ValueError("SES must be disabled on the isolated test stack")
        if worker["Timeout"] != 300:
            raise ValueError("Task 8 worker timeout must be 300 seconds")
        expected_code = base64.b64encode(hashlib.sha256(self.final_bytes).digest()).decode()
        for logical, handler in (("ApiFunction", "app.api"), ("WorkerFunction", "app.worker"),
                                 ("ScheduleFunction", "app.scheduler"), ("RecoveryFunction", "app.recovery"),
                                 ("ReconcileFunction", "app.reconcile")):
            current = self.client("lambda").get_function_configuration(FunctionName=self.resources[logical])
            if current["CodeSha256"] != expected_code or current["Handler"] != handler:
                raise ValueError("Deploy the final artifact before running the harness: " + logical)
        self.table = self.session.resource("dynamodb", config=SDK_CONFIG).Table(self.resources["Data"])
        async_config = self.client("lambda").get_function_event_invoke_config(FunctionName=self.resources["WorkerFunction"])
        if async_config.get("MaximumRetryAttempts") != 2 or async_config.get("MaximumEventAgeInSeconds") != 600:
            raise ValueError("Worker async retry/age configuration does not match Task 8")
        attributes = self.client("sqs").get_queue_attributes(QueueUrl=self.resources["DeadLetters"], AttributeNames=["VisibilityTimeout", "MessageRetentionPeriod", "RedrivePolicy"])["Attributes"]
        redrive = json.loads(attributes.get("RedrivePolicy", "{}"))
        if attributes.get("VisibilityTimeout") != "180" or attributes.get("MessageRetentionPeriod") != "1209600" or str(redrive.get("maxReceiveCount")) != "5":
            raise ValueError("Failure queue visibility/retention/redrive does not match Task 8")
        self.record("preflight", stack_id=stack["StackId"], user_count=user_count, source_dirty=self.identity["source_dirty"], worker_code_sha256=worker["CodeSha256"])

    def authenticate_users(self):
        pool = self.resources["UserPool"]
        issuer = "https://cognito-idp." + self.manifest["region"] + ".amazonaws.com/" + pool
        for fixture in self.manifest["users"]:
            token = os.environ.get(fixture["token_env"])
            if not token:
                raise ValueError("Missing token environment variable: " + fixture["token_env"])
            claims = decode_claims(token)
            if claims.get("token_use") != "access" or claims.get("iss") != issuer:
                raise ValueError("Use access tokens from the isolated test UserPool")
            verified = self.client("cognito-idp").get_user(AccessToken=token)
            attributes = {item["Name"]: item["Value"] for item in verified["UserAttributes"]}
            subject = attributes.get("sub")
            if not subject or subject != claims.get("sub"):
                raise ValueError("Test token subject is invalid")
            user = {**fixture, "token": token, "pk": "TENANT#" + subject}
            self.users.append(user)
            self.request(user, "GET", "/me", expected={200})
        if self.users[0]["pk"] == self.users[1]["pk"]:
            raise ValueError("Two distinct authenticated test users are required")
        self.record("two_users_authenticated", labels=[user["label"] for user in self.users])

    def request(self, user, method, path, body=None, expected=None):
        payload = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base_url + path, data=payload, method=method,
                                         headers={"Authorization": "Bearer " + user["token"], "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=35) as reply:
                status, headers, raw = reply.status, reply.headers, reply.read()
        except urllib.error.HTTPError as error:
            status, headers, raw = error.code, error.headers, error.read()
        value = json.loads(raw)
        self.record("api", label=user["label"], method=method, path=path, status=status,
                    request_id=headers.get("apigw-requestid") or headers.get("x-amzn-requestid"))
        if expected is not None and status not in expected:
            raise AssertionError(f"Unexpected API status for {method} {path}: {status}")
        return status, value

    def query(self, pk, prefix):
        args = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix), "ConsistentRead": True}
        rows = []
        while True:
            page = self.table.query(**args)
            rows.extend(page.get("Items", []))
            if not page.get("LastEvaluatedKey"):
                return rows
            args["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def profile(self, user):
        return self.table.get_item(Key={"pk": user["pk"], "sk": "PROFILE"}, ConsistentRead=True).get("Item", {})

    def prepare(self, user):
        # Role trust and ExternalId are prepared externally and reviewed first.
        profile = self.profile(user)
        active = [row for row in self.query(user["pk"], "RESULT#") if row.get("status") not in TERMINAL]
        if active:
            raise ValueError("Finish/reconcile existing test scans before modifying fixtures")
        if profile.get("role_arn") != user["role_arn"] or profile.get("regions") != user["regions"]:
            self.request(user, "PUT", "/connection", {"role_arn": user["role_arn"], "regions": user["regions"],
                                                       "service_groups": ["compute", "storage", "database", "network"]}, expected={200})
        self.request(user, "PUT", "/notifications", {"enabled": False}, expected={200})
        self.make_due(user)

    def make_due(self, user, scheduled=False):
        profile = self.profile(user)
        if not profile.get("connection_version"):
            raise ValueError("Test user is not connected")
        if any(row.get("status") not in TERMINAL for row in self.query(user["pk"], "RESULT#")):
            raise ValueError("Refusing to reset fixture cooldown while a scan is active")
        self.table.update_item(Key={"pk": user["pk"], "sk": "PROFILE"}, UpdateExpression="SET last_queued = :due",
                               ConditionExpression="connection_version = :version",
                               ExpressionAttributeValues={":due": int(time.time()) - (25 * 3600 if scheduled else 901), ":version": profile["connection_version"]})
        self.record("fixture_due", label=user["label"], scheduled=scheduled)

    def start(self, user):
        _, reply = self.request(user, "POST", "/scans", expected={202})
        return reply["scan_id"]

    def wait_scan(self, user, scan_id, allowed=GOOD, timeout=1230):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            _, reply = self.request(user, "GET", "/scans/" + scan_id, expected={200})
            rows = reply["results"]
            persisted = [row for row in self.query(user["pk"], "RESULT#") if row.get("scan_id") == scan_id]
            # API's derived timeout is not evidence of durable terminal storage.
            if len(persisted) == len(user["regions"]) and all(row.get("status") in TERMINAL for row in persisted):
                if any(row["status"] not in allowed for row in persisted):
                    self.record("unexpected_terminal", results=[safe_result(row) for row in persisted])
                    raise AssertionError("Unexpected durable terminal state")
                history = [row for row in self.query(user["pk"], "HISTORY#") if row.get("scan_id") == scan_id]
                if sorted(row.get("region") for row in history) != sorted(user["regions"]):
                    raise AssertionError("Expected exactly one history row per region")
                if any(row.get("status") != next(item["status"] for item in persisted if item["region"] == row["region"]) for row in history):
                    raise AssertionError("History state does not match result state")
                for row in persisted + history:
                    if not all(key in row for key in ("started_at", "completed_at", "expires", "connection_version")):
                        raise AssertionError("Final result/history metadata is incomplete")
                    if int(row["expires"]) < int(row["completed_at"]) + 29 * 86400:
                        raise AssertionError("Terminal TTL is shorter than the 30 day contract")
                self.record("durable_scan", label=user["label"], scan_id=scan_id, results=[safe_result(row) for row in persisted], history_count=len(history))
                return persisted
            time.sleep(5)
        raise TimeoutError("Timed out waiting for durable result and history")

    def invoke(self, logical, event, asynchronous=False):
        reply = self.client("lambda").invoke(FunctionName=self.resources[logical], InvocationType="Event" if asynchronous else "RequestResponse", Payload=json.dumps(event).encode())
        self.record("lambda_invoke", logical_id=logical, asynchronous=asynchronous, request_id=reply.get("ResponseMetadata", {}).get("RequestId"), status=reply["StatusCode"])
        if reply.get("FunctionError"):
            raise AssertionError("Direct Lambda invocation failed: " + logical)
        if asynchronous:
            return None
        return json.loads(reply["Payload"].read())

    def logs(self, logical, scan_id, since):
        group = "/aws/lambda/" + self.resources[logical]
        references = []
        args = {"logGroupName": group, "startTime": int(since * 1000), "filterPattern": '"' + scan_id + '"'}
        for page in self.client("logs").get_paginator("filter_log_events").paginate(**args):
            for event in page.get("events", []):
                # Persist only reference and a strict allowlist of wrapper diagnostics.
                reference = {"log_group": group, "log_stream": event["logStreamName"], "event_id": event["eventId"], "timestamp": event["timestamp"]}
                message = event.get("message", "")
                start = message.find('{"event": "task8_')
                if start >= 0:
                    try:
                        detail = json.loads(message[start:])
                        allowed = ("event", "mode", "scan_id", "region", "request_id", "worker_request_id", "condition", "invoke_count", "message_id", "receive_count")
                        reference.update({key: detail[key] for key in allowed if key in detail})
                    except ValueError:
                        pass
                references.append(reference)
        self.record("log_references", scan_id=scan_id, logical_id=logical, references=references)
        return references

    def platform_timeout(self, scan_id, worker_logs, since):
        group = "/aws/lambda/" + self.resources["WorkerFunction"]
        request_ids = {row["request_id"] for row in worker_logs
                       if row.get("event") == "task8_fault" and row.get("mode") == "hard-timeout" and row.get("request_id")}
        for request_id in request_ids:
            args = {"logGroupName": group, "startTime": int(since * 1000), "filterPattern": '"' + request_id + '"'}
            for page in self.client("logs").get_paginator("filter_log_events").paginate(**args):
                for event in page.get("events", []):
                    message = event.get("message", "").lower()
                    if request_id.lower() in message and ("task timed out" in message or ("report" in message and "status: timeout" in message)):
                        self.record("platform_timeout", scan_id=scan_id, request_id=request_id, log_group=group,
                                    log_stream=event["logStreamName"], event_id=event["eventId"], timestamp=event["timestamp"])
                        return True
        return False

    def smoke(self):
        for index, user in enumerate(self.users):
            self.prepare(user)
            scan_id = self.start(user)
            self.wait_scan(user, scan_id)
            self.request(self.users[1 - index], "GET", "/scans/" + scan_id, expected={404})
            _, history = self.request(user, "GET", "/history?limit=100", expected={200})
            if not any(row.get("scan_id") == scan_id for row in history["results"]):
                raise AssertionError("Current user cannot read its scan history")

    def schedule(self, timeout):
        user = self.users[0]
        self.prepare(user)
        before = {row.get("scan_id") for row in self.query(user["pk"], "RESULT#")}
        started = time.time()
        self.make_due(user, scheduled=True)
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            rows = [row for row in self.query(user["pk"], "RESULT#") if row.get("scan_id") not in before and row.get("trigger") == "scheduled"]
            if rows:
                scan_id = rows[0]["scan_id"]
                self.wait_scan(user, scan_id)
                rule = self.resources.get("ScheduleFunctionTick")
                if not rule:
                    raise ValueError("Cannot resolve the real EventBridge schedule rule")
                # Allow CloudWatch metric ingestion; no direct scheduler invocation occurs here.
                for _ in range(24):
                    reply = self.client("cloudwatch").get_metric_statistics(Namespace="AWS/Events", MetricName="Invocations",
                        Dimensions=[{"Name": "RuleName", "Value": rule}], StartTime=datetime.fromtimestamp(started - 60, timezone.utc),
                        EndTime=datetime.now(timezone.utc), Period=60, Statistics=["Sum"])
                    if sum(point["Sum"] for point in reply.get("Datapoints", [])) > 0:
                        self.record("eventbridge_tick", scan_id=scan_id, rule=rule, start=started, invocation_sum=sum(point["Sum"] for point in reply["Datapoints"]))
                        self.logs("ScheduleFunction", scan_id, started)
                        return
                    time.sleep(5)
                raise AssertionError("No real EventBridge invocation metric in the observation window")
            time.sleep(10)
        raise TimeoutError("No due scheduled scan observed; allow at least one hourly tick")

    def race(self):
        user = self.users[0]
        self.prepare(user)
        old_ids = {row.get("scan_id") for row in self.query(user["pk"], "RESULT#")}
        old_history = {row["sk"] for row in self.query(user["pk"], "HISTORY#")}
        self.make_due(user, scheduled=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            tasks = [pool.submit(self.request, user, "POST", "/scans", expected={202, 409, 429}),
                     pool.submit(self.invoke, "ScheduleFunction", {"source": "task8-harness"}),
                     pool.submit(self.invoke, "ScheduleFunction", {"source": "task8-harness"})]
            for task in tasks:
                task.result()
        rows = [row for row in self.query(user["pk"], "RESULT#") if row.get("scan_id") not in old_ids]
        ids = {row["scan_id"] for row in rows}
        if len(ids) != 1:
            raise AssertionError("Manual/scheduler race did not select exactly one scan")
        scan_id = next(iter(ids))
        self.wait_scan(user, scan_id)
        histories = [row for row in self.query(user["pk"], "HISTORY#") if row["sk"] not in old_history]
        if {row["scan_id"] for row in histories} != ids:
            raise AssertionError("Race created more than one accepted scan")
        self.record("manual_scheduler_race", scan_id=scan_id)

    def duplicate(self):
        user = self.users[0]
        self.prepare(user)
        scan_id = self.start(user)
        markers = [row for row in self.query(user["pk"], "RESULT#") if row.get("scan_id") == scan_id]
        for row in markers:
            job = {key: row[key] for key in ("pk", "region", "scan_id", "connection_version", "trigger", "deadline_at") if key in row}
            self.invoke("WorkerFunction", job, asynchronous=True)
        self.wait_scan(user, scan_id)
        completed = self.query(user["pk"], "RESULT#")
        for row in markers:
            self.invoke("WorkerFunction", {key: row[key] for key in ("pk", "region", "scan_id", "connection_version")})
        if self.query(user["pk"], "RESULT#") != completed:
            raise AssertionError("A terminal scan changed after a duplicate worker invocation")
        for row in markers:
            job = {key: row[key] for key in ("pk", "region", "scan_id", "connection_version")}
            envelope = {"requestPayload": job, "requestContext": {"condition": "RetriesExhausted", "approximateInvokeCount": 3}}
            records = [{"messageId": "terminal-duplicate", "eventSource": "aws:sqs", "body": json.dumps(envelope)},
                       {"messageId": "malformed", "eventSource": "aws:sqs", "body": "{invalid"}]
            reply = self.invoke("RecoveryFunction", {"Records": records})
            if reply.get("batchItemFailures") != [{"itemIdentifier": "malformed"}]:
                raise AssertionError("Recovery partial-batch response does not isolate malformed records")
        if self.query(user["pk"], "RESULT#") != completed:
            raise AssertionError("A terminal scan changed after duplicate failure delivery")
        self.record("duplicate_worker", scan_id=scan_id)

    def orphan(self):
        user = self.users[0]
        self.prepare(user)
        profile = self.profile(user)
        now = int(time.time())
        # Test-only fixture: a marker committed before a process stopped before
        # dispatch. No worker/reconciler is invoked directly by this scenario.
        self.table.update_item(Key={"pk": user["pk"], "sk": "PROFILE"}, UpdateExpression="SET last_queued = :now",
                               ConditionExpression="connection_version = :version",
                               ExpressionAttributeValues={":now": now, ":version": profile["connection_version"]})
        scan_id = str(uuid.uuid4())
        for region in user["regions"]:
            marker = {"pk": user["pk"], "sk": "RESULT#" + region, "scan_id": scan_id,
                      "region": region, "connection_version": profile["connection_version"],
                      "status": "QUEUED", "created_at": now - 901, "started_at": now - 901,
                      "deadline_at": now - 1, "attempt_count": 0, "trigger": "scheduled"}
            self.table.put_item(Item=marker,
                ConditionExpression="attribute_not_exists(pk) OR (#state IN (:success, :partial, :failed, :timeout) AND connection_version = :version)",
                ExpressionAttributeNames={"#state": "status"}, ExpressionAttributeValues={":success": "SUCCEEDED", ":partial": "PARTIAL",
                    ":failed": "FAILED", ":timeout": "TIMED_OUT", ":version": profile["connection_version"]})
        self.record("orphan_fixture", scan_id=scan_id, synthetic_fixture=True, worker_invoked=False)
        self.wait_scan(user, scan_id, allowed={"TIMED_OUT"}, timeout=450)
        self.logs("ReconcileFunction", scan_id, now)

    def reconnect(self):
        user = self.users[0]
        self.prepare(user)
        scan_id = self.start(user)
        markers = [row for row in self.query(user["pk"], "RESULT#") if row.get("scan_id") == scan_id]
        old_version = self.profile(user)["connection_version"]
        self.request(user, "PUT", "/connection", {"role_arn": user["role_arn"], "regions": user["regions"], "service_groups": ["compute", "storage", "database", "network"]}, expected={200})
        new_version = self.profile(user)["connection_version"]
        if old_version == new_version:
            raise AssertionError("Reconnect did not rotate the connection version")
        self.request(user, "GET", "/scans/" + scan_id, expected={404})
        for marker in markers:
            self.invoke("WorkerFunction", {key: marker[key] for key in ("pk", "region", "scan_id", "connection_version")})
        _, current = self.request(user, "GET", "/findings", expected={200})
        if any(row.get("connection_version") == old_version for row in current["results"]):
            raise AssertionError("Old connection results leaked through the API")
        self.record("reconnect_isolation", old_scan_id=scan_id, connection_rotated=True)

    def wait_updated(self, logical):
        self.client("lambda").get_waiter("function_updated_v2").wait(FunctionName=self.resources[logical], WaiterConfig={"Delay": 2, "MaxAttempts": 150})

    def fault(self, mode, fault_zip):
        user = self.users[0]
        self.prepare(user)
        fault_bytes = checked_fault_archive(fault_zip, self.final_bytes)
        self.evidence["fault_zip_sha256"] = sha256(fault_bytes)
        # Only the two test functions are changed; restoration always uses the pinned final ZIP.
        saved = {}
        since = time.time()
        try:
            for logical, handler in (("WorkerFunction", "task8_faults.worker"), ("RecoveryFunction", "task8_faults.recovery")):
                cfg = self.client("lambda").get_function_configuration(FunctionName=self.resources[logical])
                saved[logical] = {"Handler": cfg["Handler"], "Environment": {"Variables": dict(cfg.get("Environment", {}).get("Variables", {}))}}
                self.client("lambda").update_function_code(FunctionName=self.resources[logical], ZipFile=fault_bytes)
                self.wait_updated(logical)
                variables = {**saved[logical]["Environment"]["Variables"], "TASK8_STACK": TEST_STACK, "TASK8_TENANT": user["pk"], "TASK8_FAULT_MODE": mode}
                self.client("lambda").update_function_configuration(FunctionName=self.resources[logical], Handler=handler, Environment={"Variables": variables})
                self.wait_updated(logical)
            scan_id = self.start(user)
            rows = []
            if mode == "consumer":
                self.wait_dlq(scan_id, timeout=2400)
            else:
                allowed = GOOD if mode == "transient" else {"FAILED"} if mode == "exhausted" else {"TIMED_OUT"}
                rows = self.wait_scan(user, scan_id, allowed=allowed)
            # Log ingestion can lag behind durable completion/redrive. Require
            # the scenario-specific oracle before PASS, retrying only evidence reads.
            last_error = None
            for _ in range(24):
                references = self.logs("RecoveryFunction", scan_id, since)
                worker_logs = self.logs("WorkerFunction", scan_id, since)
                timeout_seen = self.platform_timeout(scan_id, worker_logs, since) if mode == "hard-timeout" else False
                try:
                    verify_fault_evidence(mode, rows, worker_logs, references, timeout_seen)
                except AssertionError as error:
                    last_error = error
                    time.sleep(5)
                else:
                    last_error = None
                    break
            if last_error:
                raise last_error
            self.record("fault_case", mode=mode, scan_id=scan_id)
        finally:
            errors = []
            for logical, cfg in saved.items():
                try:
                    self.client("lambda").update_function_code(FunctionName=self.resources[logical], ZipFile=self.final_bytes)
                    self.wait_updated(logical)
                    self.client("lambda").update_function_configuration(FunctionName=self.resources[logical], **cfg)
                    self.wait_updated(logical)
                    actual = self.client("lambda").get_function_configuration(FunctionName=self.resources[logical])
                    final_hash = base64.b64encode(hashlib.sha256(self.final_bytes).digest()).decode()
                    if actual.get("CodeSha256") != final_hash or actual.get("Handler") != cfg["Handler"] or actual.get("Environment", {}).get("Variables", {}) != cfg["Environment"]["Variables"]:
                        raise RuntimeError("Restored function does not match the final artifact/configuration")
                except Exception as error:
                    errors.append({"logical_id": logical, "error_type": type(error).__name__})
            self.record("fault_restore", restored=not errors, errors=errors)
            if errors:
                raise RuntimeError("Fault artifact restoration needs operator attention")
        # Consumer fault leaves the original message untouched in the operations DLQ.
        # A normal final scan is a separate command so reconciliation can finish first.

    def wait_dlq(self, scan_id, timeout):
        queue = self.resources["OperationsDeadLetters"]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reply = self.client("sqs").receive_message(QueueUrl=queue, MaxNumberOfMessages=10, WaitTimeSeconds=10,
                                                       VisibilityTimeout=0, MessageSystemAttributeNames=["ApproximateReceiveCount"])
            for message in reply.get("Messages", []):
                try:
                    envelope = json.loads(message["Body"])
                except ValueError:
                    continue
                if envelope.get("requestPayload", {}).get("scan_id") == scan_id:
                    self.record("operations_dlq_message", scan_id=scan_id, message_id=message["MessageId"],
                                receive_count=message.get("Attributes", {}).get("ApproximateReceiveCount"),
                                condition=envelope.get("requestContext", {}).get("condition"), message_preserved=True)
                    return
            time.sleep(5)
        raise TimeoutError("Consumer failure was not observed in the operations DLQ")


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("command", choices=("package", "inspect", "run"))
    cli.add_argument("--artifact", required=True, help="Pinned deployment ZIP without fault wrapper")
    cli.add_argument("--output-dir", default=str(ROOT / ".preflight/task8-artifacts"))
    cli.add_argument("--manifest", help="Reviewed test environment manifest; never contains tokens")
    cli.add_argument("--profile", help="Named boto3 profile; omit for the normal AWS credential chain")
    cli.add_argument("--evidence", help="New sanitized evidence JSON; defaults to a unique file under .preflight")
    cli.add_argument("--scenario", choices=SCENARIOS, default="smoke")
    cli.add_argument("--fault-zip", help="Offline-generated task8-faults.zip")
    cli.add_argument("--schedule-wait", type=int, default=4200, help="Seconds to observe one real hourly EventBridge tick")
    cli.add_argument("--allow-mutations", action="store_true")
    cli.add_argument("--confirm-account", help="Explicit account confirmation for test fixture writes")
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "package":
        result = package(args.artifact, args.output_dir)
        print(json.dumps(result, indent=2))
        return 0
    if not args.manifest:
        raise ValueError("--manifest is required for AWS inspection or execution")
    manifest = validate_manifest(json.loads(pathlib.Path(args.manifest).read_text(encoding="utf-8")))
    if args.command == "run":
        if os.environ.get("CRG_TASK8_AWS") != "1" or not args.allow_mutations or args.confirm_account != manifest["account_id"]:
            raise ValueError("Run requires CRG_TASK8_AWS=1, --allow-mutations and matching --confirm-account")
        if source_identity()["source_dirty"]:
            raise ValueError("Commit the reviewed src/template revision before AWS acceptance")
        if args.scenario in FAULTS and not args.fault_zip:
            raise ValueError("Fault scenarios require --fault-zip generated by package")
    session = boto3.Session(profile_name=args.profile, region_name=manifest["region"])
    evidence = args.evidence or str(ROOT / ".preflight/task8-evidence" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + (args.scenario if args.command == "run" else "inspect") + ".json"))
    if pathlib.Path(evidence).exists():
        raise ValueError("Evidence path already exists; choose a new path to preserve prior results")
    harness = Harness(manifest, session, args.artifact, evidence)
    try:
        harness.inspect()
        if args.command == "run":
            harness.authenticate_users()
            if args.scenario in ("smoke", "final-smoke"):
                harness.smoke()
            elif args.scenario == "schedule":
                harness.schedule(args.schedule_wait)
            elif args.scenario in FAULTS:
                harness.fault(args.scenario, args.fault_zip)
            else:
                getattr(harness, args.scenario)()
        harness.evidence.update(status="PASS", completed_at=utc_now(), scenario=args.scenario if args.command == "run" else "inspect")
        harness.save()
        print("PASS; sanitized evidence: " + str(harness.evidence_path))
        return 0
    except Exception as error:
        harness.evidence.update(status="FAIL", completed_at=utc_now(), error_type=type(error).__name__)
        harness.save()
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as failure:
        # Do not print exception bodies from SDK/HTTP responses or token parsing.
        print("Task 8 harness failed: " + type(failure).__name__ + ". See sanitized evidence/runbook.")
        raise SystemExit(1)
