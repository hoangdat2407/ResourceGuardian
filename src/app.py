import base64
import hashlib
import json
import logging
import os
import re
import time
import uuid
from decimal import Decimal
from datetime import datetime, timezone
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from botocore.config import Config
from rules import config, keep, evaluate_ec2, evaluate_ebs, evaluate_eip, evaluate_snapshot
from collectors import SDK_CONFIG, collect_region

log = logging.getLogger()
log.setLevel(logging.INFO)
table = boto3.resource("dynamodb").Table(os.environ["TABLE"])
invoker = boto3.client("lambda")
REGIONS = {"ap-southeast-1", "ap-southeast-2", "ap-northeast-1", "us-east-1", "us-west-2", "eu-west-1"}
SERVICE_GROUPS = ("compute", "storage", "database", "network")
STATIC_ROUTES = {
    "/me": {"GET"},
    "/connection": {"PUT"},
    "/settings": {"PUT"},
    "/scan": {"POST"},
    "/scans": {"POST"},
    "/findings": {"GET"},
    "/history": {"GET"},
    "/feedback": {"GET", "PUT"},
    "/notifications": {"PUT"},
    "/keep": {"PUT"},
    "/ignore": {"PUT"},
}
BODY_LIMIT = 10240
FINDING_ID_RE = re.compile(r"[0-9a-f]{64}")
FINDING_LIMIT = 50
CANDIDATE_LIMIT = 100
RESULT_BYTE_LIMIT = 300 * 1024
ACTIVE_STATES = ("QUEUED", "RUNNING")
TERMINAL_STATES = ("SUCCEEDED", "PARTIAL", "FAILED", "TIMED_OUT")
JOB_SECONDS = 900
RUN_SECONDS = 330
RETENTION_SECONDS = 30 * 86400


class ScanCooldown(Exception):
    pass


def tenant_key(event):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject or claims.get("token_use") != "access":
        raise PermissionError("Access token required")
    return "TENANT#" + subject


def route_for(method, path):
    methods = STATIC_ROUTES.get(path)
    if methods is not None:
        return path if method in methods else None, method not in methods
    if re.fullmatch(r"/scans/[^/]+", path):
        return ("scan_status" if method == "GET" else None), method != "GET"
    return None, False


def parse_body(event):
    raw = event.get("body") or ""
    if len(raw.encode("utf-8")) > BODY_LIMIT:
        raise ValueError("Request body exceeds 10240 bytes")
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def normalized_groups(value):
    if value is None:
        return list(SERVICE_GROUPS)
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= len(SERVICE_GROUPS)
        or any(not isinstance(group, str) or group not in SERVICE_GROUPS for group in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("Choose 1 to 4 unique supported service groups")
    return value


def normalize_profile(profile):
    result = dict(profile)
    result["settings"] = config(profile.get("settings", {}))
    result["service_groups"] = normalized_groups(profile.get("service_groups"))
    return result


def public_profile(profile):
    allowed = (
        "account_id", "role_arn", "regions", "service_groups", "external_id",
        "settings", "notifications", "connection_version",
    )
    result = {key: profile.get(key) for key in allowed}
    result["regions"] = result["regions"] or []
    result["service_groups"] = result["service_groups"] or list(SERVICE_GROUPS)
    result["notifications"] = result["notifications"] or {"enabled": False}
    result.update(
        api_principal=os.environ["API_PRINCIPAL"],
        scan_principal=os.environ["SCAN_PRINCIPAL"],
        email_available=bool(os.environ.get("SES_SENDER")),
    )
    return result

def normalized(x):
    return json.loads(json.dumps(x, default=lambda v: float(v) if isinstance(v, Decimal) else str(v)))

def put(item):
    table.put_item(Item=json.loads(json.dumps(item), parse_float=Decimal))

def get(pk, sk):
    return normalized(table.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item", {}))

def response(status, value):
    return {"statusCode": status, "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
            "body": json.dumps(normalized(value))}

def session(profile):
    c = boto3.client("sts", config=SDK_CONFIG).assume_role(
        RoleArn=profile["role_arn"], RoleSessionName="guardian-scan", ExternalId=profile["external_id"], DurationSeconds=900)["Credentials"]
    return boto3.Session(aws_access_key_id=c["AccessKeyId"], aws_secret_access_key=c["SecretAccessKey"], aws_session_token=c["SessionToken"])

def all_items(pk, prefix):
    # Bounded per-tenant data; still handle DynamoDB pagination.
    args = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix), "ConsistentRead": True}
    while True:
        page = table.query(**args)
        yield from normalized(page.get("Items", []))
        if not page.get("LastEvaluatedKey"): break
        args["ExclusiveStartKey"] = page["LastEvaluatedKey"]

def conditional_failure(error):
    """Never mistake transaction conflicts, throttling or unknown cancellation for ownership loss."""
    code = error.response["Error"]["Code"]
    if code == "ConditionalCheckFailedException":
        return True
    reasons = error.response.get("CancellationReasons", [])
    codes = [reason.get("Code", "None") for reason in reasons]
    return (code == "TransactionCanceledException" and "ConditionalCheckFailed" in codes
            and all(code in ("None", "ConditionalCheckFailed") for code in codes))


def transaction(actions):
    # The DynamoDB resource client serializes native Python values for transactions.
    actions = json.loads(json.dumps(actions), parse_float=Decimal)
    return table.meta.client.transact_write_items(TransactItems=actions)


def deadline(marker):
    return marker.get("deadline_at", marker.get("created_at", marker.get("started_at", 0)) + JOB_SECONDS)


def history_key(marker):
    return "HISTORY#{}#{}#{}".format(
        int(marker.get("created_at", marker.get("started_at", 0))), marker["region"], marker["scan_id"])


def scan_log(message, marker, error_code=None):
    # Deliberately exclude tenant identity, role, ExternalId and provider error text.
    log.info(json.dumps({"event": message, "scan_id": marker.get("scan_id"),
                         "region": marker.get("region"), "trigger": marker.get("trigger", "manual"),
                         "attempt_count": marker.get("attempt_count", 0), "error_code": error_code}))


def release_tenant(pk, scan_id, version):
    lock = get(pk, "LOCK")
    if lock.get("scan_id") != scan_id or lock.get("connection_version") != version:
        return
    actions = []
    for region in lock["regions"]:
        actions.append({"ConditionCheck": {
            "TableName": table.name, "Key": {"pk": pk, "sk": "RESULT#" + region},
            "ConditionExpression": "scan_id = :id AND connection_version = :v AND #s IN (:s, :p, :f, :t)",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":id": scan_id, ":v": version, ":s": "SUCCEEDED", ":p": "PARTIAL", ":f": "FAILED", ":t": "TIMED_OUT"},
        }})
    actions.append({"Delete": {
        "TableName": table.name, "Key": {"pk": pk, "sk": "LOCK"},
        "ConditionExpression": "scan_id = :id AND connection_version = :v",
        "ExpressionAttributeValues": {":id": scan_id, ":v": version},
    }})
    try:
        transaction(actions)
    except ClientError as error:
        if not conditional_failure(error):
            raise


def finish_scan(marker, status, *, result=None, run_token=None, error_code=None,
                error_message=None, require_current=True, attempts=None):
    """Commit the terminal RESULT and immutable HISTORY together under ownership checks."""
    now = int(time.time())
    row = {key: marker[key] for key in (
        "pk", "sk", "region", "scan_id", "connection_version", "created_at", "started_at", "trigger",
    ) if key in marker}
    row.update(status=status, started_at=marker.get("started_at", marker.get("created_at", now)),
               completed_at=now, deadline_at=deadline(marker),
               attempt_count=max(marker.get("attempt_count", 0), attempts or 0),
               expires=now + RETENTION_SECONDS, findings=[], counts={}, errors=[])
    if result:
        row.update(result)
    if error_code:
        row.update(error_code=error_code, error=error_message)
    values = {":id": marker["scan_id"], ":v": marker["connection_version"], ":q": "QUEUED", ":r": "RUNNING"}
    condition = "scan_id = :id AND connection_version = :v AND #s IN (:q, :r)"
    if run_token:
        condition += " AND run_token = :token"
        values[":token"] = run_token
    else:
        condition += " AND (attribute_not_exists(run_until) OR run_until <= :now)"
        values[":now"] = now
    actions = [
        {"Put": {"TableName": table.name, "Item": row, "ConditionExpression": condition,
                 "ExpressionAttributeNames": {"#s": "status"}, "ExpressionAttributeValues": values}},
        {"Put": {"TableName": table.name, "Item": {**visible_result(row), "sk": history_key(marker)},
                 "ConditionExpression": "attribute_not_exists(pk)"}},
    ]
    if require_current:
        actions.append({"ConditionCheck": {
            "TableName": table.name, "Key": {"pk": marker["pk"], "sk": "PROFILE"},
            "ConditionExpression": "connection_version = :v", "ExpressionAttributeValues": {":v": marker["connection_version"]},
        }})
    try:
        transaction(actions)
    except ClientError as error:
        if not conditional_failure(error):
            raise
        return None
    scan_log("scan_finished", row, error_code)
    release_tenant(row["pk"], row["scan_id"], row["connection_version"])
    return row


def enqueue(profile, now, trigger="manual"):
    profile = normalize_profile(profile)
    pk, version = profile["pk"], profile["connection_version"]
    current = get(pk, "PROFILE")
    if (current.get("connection_version") != version
            or normalize_profile(current)["settings"] != profile["settings"]):
        return None
    regions = profile.get("regions")
    if (not profile.get("role_arn") or not version or not isinstance(regions, list)
            or not 1 <= len(regions) <= 3 or any(r not in REGIONS for r in regions) or len(set(regions)) != len(regions)):
        raise ValueError("Invalid connected profile")
    # Recover expired markers before a new scan can replace them, including removed regions.
    for old in all_items(pk, "RESULT#"):
        if old.get("status") in ACTIVE_STATES:
            if deadline(old) > now or old.get("run_until", 0) > now:
                return None
            if not finish_scan(old, "TIMED_OUT", error_code="JOB_DEADLINE", error_message="Scan exceeded its 15 minute deadline", require_current=False):
                return None
    scan_id = str(uuid.uuid4())
    markers = [{"pk": pk, "sk": "RESULT#" + region, "scan_id": scan_id, "status": "QUEUED",
                "created_at": now, "started_at": now, "deadline_at": now + JOB_SECONDS,
                "region": region, "connection_version": version, "trigger": trigger, "attempt_count": 0}
               for region in regions]
    due_seconds = profile["settings"]["interval_hours"] * 3600 if trigger == "scheduled" else JOB_SECONDS
    settings_condition = "settings = :settings" if "settings" in current else "attribute_not_exists(settings)"
    profile_values = {":now": now, ":v": version, ":due": now - due_seconds}
    if "settings" in current:
        profile_values[":settings"] = current["settings"]
    actions = [
        {"Put": {"TableName": table.name,
                 "Item": {"pk": pk, "sk": "LOCK", "scan_id": scan_id, "connection_version": version,
                          "regions": regions, "lease_until": now + JOB_SECONDS + 30, "expires": now + JOB_SECONDS + 30},
                 "ConditionExpression": "attribute_not_exists(lease_until) OR lease_until <= :now",
                 "ExpressionAttributeValues": {":now": now}}},
        {"Update": {"TableName": table.name, "Key": {"pk": pk, "sk": "PROFILE"},
                    "UpdateExpression": "SET last_queued = :now",
                    "ConditionExpression": "connection_version = :v AND " + settings_condition + " AND (attribute_not_exists(last_queued) OR last_queued <= :due)",
                    "ExpressionAttributeValues": profile_values}},
    ]
    for marker in markers:
        actions.append({"Put": {"TableName": table.name, "Item": marker,
                               "ConditionExpression": "attribute_not_exists(pk) OR #s IN (:s, :p, :f, :t)",
                               "ExpressionAttributeNames": {"#s": "status"},
                               "ExpressionAttributeValues": {":s": "SUCCEEDED", ":p": "PARTIAL", ":f": "FAILED", ":t": "TIMED_OUT"}}})
    try:
        transaction(actions)
    except ClientError as error:
        if not conditional_failure(error):
            raise
        current = get(pk, "PROFILE")
        if trigger == "manual" and now - current.get("last_queued", 0) < JOB_SECONDS:
            # Active scan takes precedence over cooldown in the API contract.
            lock = get(pk, "LOCK")
            if lock.get("lease_until", 0) <= now:
                raise ScanCooldown()
        return None
    for marker in markers:
        job = {key: marker[key] for key in ("pk", "region", "scan_id", "connection_version", "trigger", "deadline_at")}
        try:
            reply = invoker.invoke(FunctionName=os.environ["WORKER_FUNCTION"], InvocationType="Event", Payload=json.dumps(job).encode())
            if reply["StatusCode"] != 202:
                raise RuntimeError("Worker event not accepted")
            scan_log("scan_dispatched", marker)
        except Exception:
            # An ambiguous invoke may have started a worker: only finalize an unclaimed marker.
            finish_scan(marker, "FAILED", error_code="DISPATCH_FAILED", error_message="Dispatch failed; try another scan later")
    return scan_id

def encode_token(key):
    raw = json.dumps(normalized(key), separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_token(value, pk, prefix):
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        key = json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid pagination token") from error
    if (
        not isinstance(key, dict)
        or set(key) != {"pk", "sk"}
        or key.get("pk") != pk
        or not isinstance(key.get("sk"), str)
        or not key["sk"].startswith(prefix)
    ):
        raise ValueError("Invalid pagination token")
    return key


def page_rows(pk, prefix, profile, limit, token=None):
    args = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix),
        "ConsistentRead": True,
        "ScanIndexForward": False,
    }
    if token:
        args["ExclusiveStartKey"] = decode_token(token, pk, prefix)
    rows = []
    last_key = None
    while len(rows) < limit:
        args["Limit"] = limit - len(rows)
        page = table.query(**args)
        for row in normalized(page.get("Items", [])):
            if row.get("connection_version") != profile.get("connection_version"):
                continue
            if prefix == "HISTORY#" and row.get("expires", 0) <= time.time():
                continue
            if prefix.startswith("FEEDBACK#") and row.get("expires", float("inf")) <= time.time():
                continue
            rows.append(row)
        last_key = page.get("LastEvaluatedKey")
        if len(rows) >= limit or not last_key:
            break
        args["ExclusiveStartKey"] = last_key
    return rows, encode_token(last_key) if last_key else None


def feedback_prefix(profile, region=None):
    prefix = "FEEDBACK#" + profile["connection_version"] + "#"
    return prefix + region + "#" if region else prefix


def feedback_records(pk, profile, region=None):
    now = time.time()
    return {
        row["finding_id"]: row
        for row in all_items(pk, feedback_prefix(profile, region))
        if isinstance(row.get("finding_id"), str)
        and row.get("expires", float("inf")) > now
    }


def feedback_findings(candidates, feedback, now):
    findings = []
    for finding in candidates:
        item = dict(finding)
        item.pop("acknowledged", None)
        record = feedback.get(item.get("finding_id"))
        if record and (record.get("kept") or record.get("ignore_until", 0) > now):
            continue
        if record and record.get("acknowledged"):
            item["acknowledged"] = True
        findings.append(item)
    return findings


def apply_feedback(row, feedback):
    result = dict(row)
    findings = feedback_findings(row.get("candidates", row.get("findings", [])), feedback, time.time())
    result["findings"] = findings[:FINDING_LIMIT]
    result["finding_count"] = len(findings)
    if len(findings) > FINDING_LIMIT:
        result["status"] = "PARTIAL"
        errors = list(row.get("errors", []))
        limit_error = {"type": "FINDING", "code": "RESOURCE_LIMIT"}
        if limit_error not in errors:
            errors.append(limit_error)
        result["errors"] = errors
    return visible_result(result)


def parse_limit(event):
    query = event.get("queryStringParameters") or {}
    raw = query.get("limit", "20")
    if isinstance(raw, bool) or not isinstance(raw, str) or not raw.isdigit():
        raise ValueError("limit must be an integer from 1 to 100")
    limit = int(raw)
    if not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 to 100")
    token = query.get("next_token")
    if token is not None and (not isinstance(token, str) or not token):
        raise ValueError("Invalid pagination token")
    return limit, token


def _valid_scan_id(value):
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError("Invalid scan ID") from error
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("Invalid scan ID")
    return value


def _upsert_feedback(pk, profile, body):
    allowed = {"region", "finding_id", "acknowledged", "kept", "ignoreUntil"}
    if set(body) - allowed or not {"region", "finding_id"} <= set(body):
        raise ValueError("Feedback fields are invalid")
    changed = set(body) & {"acknowledged", "kept", "ignoreUntil"}
    if not changed:
        raise ValueError("At least one feedback field is required")
    region, ident = body["region"], body["finding_id"]
    if region not in profile.get("regions", []) or not isinstance(ident, str) or not FINDING_ID_RE.fullmatch(ident):
        raise ValueError("Invalid region or finding ID")
    for field in ("acknowledged", "kept"):
        if field in body and type(body[field]) is not bool:
            raise ValueError(field + " must be a boolean")
    now = int(time.time())
    ignore_until = None
    if "ignoreUntil" in body and body["ignoreUntil"] is not None:
        value = body["ignoreUntil"]
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z", value):
            raise ValueError("ignoreUntil must be RFC3339 UTC")
        ignore_until = int(datetime.fromisoformat(value[:-1] + "+00:00").timestamp())
        if not now < ignore_until <= now + 30 * 86400:
            raise ValueError("ignoreUntil must be in the next 30 days")
    sk = feedback_prefix(profile, region) + ident
    existing = get(pk, sk)
    displayed = any(
        finding.get("finding_id") == ident
        for row in all_items(pk, "RESULT#")
        if row.get("region") == region and row.get("connection_version") == profile["connection_version"]
        for finding in row.get("candidates", row.get("findings", []))
    )
    if not displayed and not existing:
        return None
    record = {
        **existing,
        "pk": pk,
        "sk": sk,
        "region": region,
        "finding_id": ident,
        "connection_version": profile["connection_version"],
        "updated_at": now,
    }
    if "acknowledged" in body:
        record["acknowledged"] = body["acknowledged"]
    if "kept" in body:
        record["kept"] = body["kept"]
    if "ignoreUntil" in body:
        record["ignore_until"] = ignore_until or 0
    active = bool(record.get("acknowledged") or record.get("kept"))
    if not active:
        record["expires"] = record.get("ignore_until") if record.get("ignore_until", 0) > now else now
    else:
        record.pop("expires", None)
    put(record)
    return record


def api(event, context):
    try:
        pk = tenant_key(event)
    except PermissionError as error:
        return response(401, {"error": str(error)})
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "")
    route, wrong_method = route_for(method, path)
    if not route:
        return response(405 if wrong_method else 404, {"error": "Method not allowed" if wrong_method else "Route not found"})
    try:
        body = parse_body(event)
        profile = get(pk, "PROFILE")
        if not profile:
            initial = {
                "pk": pk,
                "sk": "PROFILE",
                "external_id": str(uuid.uuid4()),
                "settings": config({}),
                "service_groups": list(SERVICE_GROUPS),
            }
            try:
                table.put_item(Item=json.loads(json.dumps(initial), parse_float=Decimal), ConditionExpression="attribute_not_exists(pk)")
            except ClientError as error:
                if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
            profile = get(pk, "PROFILE")
        profile = normalize_profile(profile)
        if route == "/me":
            return response(200, public_profile(profile))
        if route == "/connection":
            if set(body) - {"role_arn", "regions", "service_groups"} or not {"role_arn", "regions"} <= set(body):
                raise ValueError("Connection fields are invalid")
            arn = body["role_arn"]
            if not isinstance(arn, str) or not re.fullmatch(r"arn:aws:iam::\d{12}:role/GuardianReadRole-[A-Za-z0-9+=,.@_-]{1,40}", arn):
                raise ValueError("Role name must be GuardianReadRole-<suffix> without a path")
            regions = body["regions"]
            if not isinstance(regions, list) or not 1 <= len(regions) <= 3 or len(set(regions)) != len(regions) or any(r not in REGIONS for r in regions):
                raise ValueError("Choose 1 to 3 supported regions")
            groups = normalized_groups(body.get("service_groups", profile["service_groups"]))
            candidate = {**profile, "role_arn": arn, "regions": regions, "service_groups": groups}
            actual = session(candidate).client("sts").get_caller_identity()["Account"]
            if actual != arn.split(":")[4]:
                raise ValueError("Account mismatch")
            now = int(time.time())
            old_version = profile.get("connection_version")
            candidate["account_id"] = actual
            candidate["connection_version"] = str(uuid.uuid4())
            fields = ("role_arn", "account_id", "regions", "service_groups", "connection_version")
            values = {":v" + str(i): candidate[field] for i, field in enumerate(fields)}
            condition = "attribute_not_exists(connection_version)"
            if old_version:
                condition = "connection_version = :old"
                values[":old"] = old_version
            try:
                table.update_item(
                    Key={"pk": pk, "sk": "PROFILE"},
                    UpdateExpression="SET " + ", ".join(field + " = :v" + str(i) for i, field in enumerate(fields)),
                    ConditionExpression=condition, ExpressionAttributeValues=values,
                )
            except ClientError as error:
                if conditional_failure(error):
                    return response(409, {"error": "Connection changed; refresh and try again"})
                raise
            if old_version:
                for record in all_items(pk, "FEEDBACK#" + old_version + "#"):
                    if "expires" not in record:
                        record["expires"] = now + RETENTION_SECONDS
                        put(record)
            return response(200, {"connected": True, "account_id": actual})
        if route == "/settings":
            if not body:
                raise ValueError("At least one setting is required")
            cfg = config(body, profile.get("settings", {}))
            table.update_item(
                Key={"pk": pk, "sk": "PROFILE"},
                UpdateExpression="SET settings = :s",
                ExpressionAttributeValues={":s": json.loads(json.dumps(cfg), parse_float=Decimal)},
            )
            return response(200, cfg)
        if route in ("/scan", "/scans"):
            if event.get("body"):
                raise ValueError("Scan request body must be empty")
            if not profile.get("role_arn"):
                raise ValueError("Connect AWS first")
            now = int(time.time())
            if get(pk, "LOCK").get("lease_until", 0) > now:
                return response(409, {"scan_id": None, "message": "Scan lease is active"})
            if now - profile.get("last_queued", 0) < 900:
                return response(429, {"error": "Wait 15 minutes between scans"})
            try:
                scan_id = enqueue(profile, now)
            except ScanCooldown:
                return response(429, {"error": "Wait 15 minutes between scans"})
            return response(202 if scan_id else 409, {"scan_id": scan_id, "message": "Queued" if scan_id else "Scan lease is active"})
        if route == "/findings":
            if not profile.get("connection_version"):
                return response(200, {"results": []})
            regions = set(profile.get("regions", []))
            feedback = feedback_records(pk, profile)
            rows = [
                apply_feedback(row, feedback)
                for row in all_items(pk, "RESULT#")
                if row.get("region") in regions and row.get("connection_version") == profile.get("connection_version")
            ]
            return response(200, {"results": rows})
        if route == "/history":
            limit, token = parse_limit(event)
            rows, next_token = page_rows(pk, "HISTORY#", profile, limit, token)
            return response(200, {"results": [visible_result(row) for row in rows], "next_token": next_token})
        if route == "scan_status":
            scan_id = _valid_scan_id(path.rsplit("/", 1)[-1])
            rows = [
                row for row in all_items(pk, "RESULT#")
                if row.get("scan_id") == scan_id and row.get("connection_version") == profile.get("connection_version")
            ]
            if not rows:
                rows = [
                    row for row in all_items(pk, "HISTORY#")
                    if row.get("scan_id") == scan_id
                    and row.get("connection_version") == profile.get("connection_version")
                    and row.get("expires", 0) > time.time()
                ]
            if not rows:
                return response(404, {"error": "Scan not found for this user"})
            return response(200, {"scan_id": scan_id, "results": [visible_result(row) for row in rows]})
        if route == "/feedback" and method == "GET":
            limit, token = parse_limit(event)
            if not profile.get("connection_version"):
                return response(200, {"results": [], "next_token": None})
            rows, next_token = page_rows(pk, feedback_prefix(profile), profile, limit, token)
            return response(200, {"results": rows, "next_token": next_token})
        if route == "/feedback":
            record = _upsert_feedback(pk, profile, body)
            return response(200, record) if record else response(404, {"error": "Finding not found"})
        if route == "/notifications":
            enabled = body.get("enabled")
            if type(enabled) is not bool:
                raise ValueError("enabled must be a boolean")
            if enabled and not os.environ.get("SES_SENDER"):
                raise ValueError("Email has not been configured by platform owner")
            notification = {"enabled": enabled}
            if enabled:
                auth = {key.lower(): value for key, value in event.get("headers", {}).items()}.get("authorization", "")
                if not auth.startswith("Bearer "):
                    raise ValueError("Access token missing")
                attributes = boto3.client("cognito-idp").get_user(AccessToken=auth[7:])["UserAttributes"]
                attributes = {item["Name"]: item["Value"] for item in attributes}
                if attributes.get("email_verified") != "true" or not attributes.get("email"):
                    raise ValueError("Verify Cognito email before enabling alerts")
                notification["email"] = attributes["email"]
            table.update_item(
                Key={"pk": pk, "sk": "PROFILE"},
                UpdateExpression="SET notifications = :n",
                ExpressionAttributeValues={":n": notification},
            )
            return response(200, notification)
        if route in ("/keep", "/ignore") and method == "PUT":
            if not profile.get("role_arn") or not profile.get("connection_version"):
                raise ValueError("Connect AWS first")
            region, rid = body.get("region", ""), body.get("resource_id", "")
            if region not in profile.get("regions", []) or not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", rid):
                raise ValueError("Invalid region or resource ID")
            if route == "/keep":
                enabled = body.get("enabled")
                if type(enabled) is not bool:
                    raise ValueError("enabled must be a boolean")
                put({"pk": pk, "sk": "KEEP#" + profile["connection_version"] + "#" + region + "#" + rid, "enabled": enabled})
                return response(200, {"kept": enabled})
            days = body.get("days", 7)
            if type(days) is not int or not 1 <= days <= 30:
                raise ValueError("Ignore duration must be 1 to 30 days")
            put({"pk": pk, "sk": "IGNORE#" + profile["connection_version"] + "#" + region + "#" + rid, "expires": int(time.time()) + days * 86400})
            return response(200, {"ignored": True})
        raise RuntimeError("Unreachable route")
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeEncodeError) as error:
        return response(400, {"error": str(error)})
    except ClientError as error:
        log.error("API AWS request failed code=%s", error.response["Error"]["Code"])
        return response(502, {"error": "AWS request failed; check role permissions and CloudWatch logs"})


def visible_result(row):
    row = {key: value for key, value in row.items() if key != "candidates"}
    if row.get("status") in ACTIVE_STATES and time.time() >= deadline(row):
        return {**row, "status": "TIMED_OUT", "error": "Scan did not complete within 15 minutes. Check Lambda failure queue and retry."}
    return row


def history(pk, profile):
    return page_rows(pk, "HISTORY#", profile, 20)[0]

def scheduler(event, context):
    args = {"ConsistentRead": True}
    count, failed = 0, False
    log.info("Scheduler tick id=%s source=%s time=%s", event.get("id"), event.get("source"), event.get("time"))
    while True:
        page = table.scan(**args)
        for p in normalized(page.get("Items", [])):
            if p.get("sk") != "PROFILE" or not p.get("role_arn"): continue
            try:
                p = normalize_profile(p)
                now = int(time.time())
                if now - p.get("last_queued", 0) >= p["settings"]["interval_hours"] * 3600:
                    if enqueue(p, now, trigger="scheduled"):
                        count += 1
            except (ValueError, TypeError, KeyError):
                log.warning("Scheduler skipped invalid profile")
            except Exception as error:
                failed = True
                log.error("Scheduler tenant failed error_type=%s", type(error).__name__)
        if not page.get("LastEvaluatedKey"): break
        args["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    if failed:
        raise RuntimeError("Scheduler infrastructure failure; independent tenants processed")
    return {"queued_tenants": count}

def scan(job, context):
    pk, region = job["pk"], job["region"]
    marker = get(pk, "RESULT#" + region)
    if (marker.get("scan_id") != job["scan_id"]
            or marker.get("connection_version") != job.get("connection_version")):
        return
    if marker.get("status") in TERMINAL_STATES:
        release_tenant(pk, job["scan_id"], job["connection_version"])
        return
    profile = normalize_profile(get(pk, "PROFILE"))
    if region not in profile.get("regions", []) or job.get("connection_version") != profile.get("connection_version"):
        return
    now = int(time.time())
    if now >= deadline(marker):
        finish_scan(marker, "TIMED_OUT", error_code="JOB_DEADLINE", error_message="Scan exceeded its 15 minute deadline")
        return
    run_token = str(uuid.uuid4())
    try:
        transaction([
            {"Update": {
                "TableName": table.name, "Key": {"pk": pk, "sk": "RESULT#" + region},
                "UpdateExpression": "SET #state = :running, run_until = :until, run_token = :token ADD attempt_count :one",
                "ConditionExpression": "scan_id = :id AND connection_version = :v AND #state IN (:queued, :running) AND (attribute_not_exists(run_until) OR run_until <= :now)",
                "ExpressionAttributeNames": {"#state": "status"},
                "ExpressionAttributeValues": {":queued": "QUEUED", ":running": "RUNNING", ":until": min(now + RUN_SECONDS, deadline(marker)),
                                            ":token": run_token, ":id": job["scan_id"], ":v": job["connection_version"], ":now": now, ":one": 1},
            }},
            {"ConditionCheck": {
                "TableName": table.name, "Key": {"pk": pk, "sk": "PROFILE"},
                "ConditionExpression": "connection_version = :v AND contains(regions, :region)",
                "ExpressionAttributeValues": {":v": job["connection_version"], ":region": region},
            }},
        ])
    except ClientError as error:
        if not conditional_failure(error):
            raise
        latest = get(pk, "RESULT#" + region)
        current = get(pk, "PROFILE")
        if (latest.get("scan_id") != job["scan_id"] or latest.get("status") in TERMINAL_STATES
                or latest.get("connection_version") != job.get("connection_version")
                or current.get("connection_version") != job.get("connection_version")
                or region not in current.get("regions", [])):
            return
        raise RuntimeError("Duplicate event while worker lease is active; retry later") from error
    job["_run_token"] = run_token
    marker = get(pk, "RESULT#" + region)
    if marker.get("run_token") != run_token:
        return
    scan_log("scan_started", marker)
    if context.get_remaining_time_in_millis() < 60000 or time.time() >= deadline(marker) - 60:
        finish_scan(marker, "TIMED_OUT", run_token=run_token, error_code="TIME_BUDGET",
                    error_message="Insufficient time remaining to start AWS collection safely")
        return
    try:
        sess = session(profile)
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("AccessDenied", "AccessDeniedException", "InvalidClientTokenId", "ExpiredToken"):
            raise
        finish_scan(marker, "FAILED", run_token=run_token, error_code="ASSUME_ROLE_DENIED",
                    error_message="Cannot access AWS; reconnect and check role permissions")
        return {"failed": True}

    def observed(kind, ident, bad):
        prefix = "OBS#" + profile["connection_version"] + "#" + region + "#"
        sk = prefix + kind + "#" + ident
        old = get(pk, sk)
        # Old observations lacked the resource type. Only native AWS prefixes
        # identify their owner safely during this one-way migration.
        legacy_sk = prefix + ident
        legacy_prefix = {"EBS": "vol-", "EIP": "eipalloc-"}.get(kind)
        legacy = get(pk, legacy_sk) if legacy_prefix and ident.startswith(legacy_prefix) else {}
        if not old:
            old = legacy
        if not bad:
            if old:
                table.delete_item(Key={"pk": pk, "sk": sk})
            if legacy:
                table.delete_item(Key={"pk": pk, "sk": legacy_sk})
            return 0
        recent = old.get("expires", now + 1) > now and 0 <= now - old.get("last", now) <= 48 * 3600
        first = old.get("first", now) if recent and old.get("first", now) <= now else now
        put({"pk": pk, "sk": sk, "first": first, "last": now, "expires": now + 7 * 86400})
        if legacy:
            table.delete_item(Key={"pk": pk, "sk": legacy_sk})
        return (now - first) / 3600

    def time_check():
        if context.get_remaining_time_in_millis() < 60000 or time.time() >= deadline(marker) - 60:
            raise TimeoutError("Scan stopped before Lambda timeout")

    collected = collect_region(
        sess, region, profile.get("account_id", ""), profile["settings"],
        profile["service_groups"], datetime.fromtimestamp(now, timezone.utc), time_check, observed,
    )
    skip = {r["sk"].rsplit("#", 1)[1] for r in all_items(pk, "IGNORE#" + profile["connection_version"] + "#" + region + "#") if r.get("expires", 0) > now}
    skip.update(r["sk"].rsplit("#", 1)[1] for r in all_items(pk, "KEEP#" + profile["connection_version"] + "#" + region + "#") if r.get("enabled") is True)
    feedback = feedback_records(pk, profile, region)
    candidates = [
        finding for finding in collected["findings"]
        if finding.get("resource_id") not in skip
    ]
    actionable = feedback_findings(candidates, feedback, now)
    # Retain feedback-hidden candidates so clearing feedback can restore them
    # immediately. Keep currently displayed findings first when storage is full.
    retained, seen = [], set()
    displayed_ids = {finding["finding_id"] for finding in actionable[:FINDING_LIMIT]}
    preferred = [finding for finding in candidates if finding["finding_id"] in displayed_ids]
    for finding in preferred + candidates:
        if finding["finding_id"] not in seen:
            seen.add(finding["finding_id"])
            retained.append(finding)
    truncated_candidates = len(retained) > CANDIDATE_LIMIT
    retained = retained[:CANDIDATE_LIMIT]
    errors = list(collected["errors"])
    too_many_findings = len(actionable) > FINDING_LIMIT
    if too_many_findings:
        errors.append({"type": "FINDING", "code": "RESOURCE_LIMIT"})
    current_profile = get(pk, "PROFILE")
    if current_profile.get("connection_version") != profile.get("connection_version"):
        return
    result = {
        "pk": pk, "sk": "RESULT#" + region, "region": region, "scan_id": job["scan_id"],
        "status": "PARTIAL" if collected["partial"] or too_many_findings else "SUCCEEDED",
        "started_at": marker.get("started_at", now), "completed_at": int(time.time()),
        "connection_version": profile["connection_version"], "counts": collected["counts"],
        "findings": actionable[:FINDING_LIMIT], "finding_count": len(actionable), "errors": errors,
        "candidates": retained, "total_candidate_count": len(candidates),
        "note": "Limit 100 resources/type and 50 displayed findings/region. Only selected regions scanned.",
        "expires": now + 30 * 86400,
    }
    # DynamoDB allows 400 KiB per item. Leave room for its attribute encoding
    # and notification metadata, and report every retention limit as partial.
    while True:
        retained_findings = feedback_findings(retained, feedback, now)
        result["findings"] = retained_findings[:FINDING_LIMIT]
        result["finding_count"] = len(retained_findings)
        if truncated_candidates:
            result["status"] = "PARTIAL"
            limit_error = {"type": "FINDING", "code": "CANDIDATE_LIMIT"}
            if limit_error not in errors:
                errors.append(limit_error)
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= RESULT_BYTE_LIMIT or not retained:
            break
        retained.pop()
        truncated_candidates = True
    result["notification"] = "PENDING" if profile.get("notifications", {}).get("enabled") and os.environ.get("SES_SENDER") else "DISABLED"
    saved = finish_scan(marker, result["status"], result=result, run_token=run_token)
    if saved:
        # Email is best effort after the durable scan commit; it cannot trigger another inventory pass.
        try:
            notification = notify(profile, saved)
            actions = []
            for sk in (saved["sk"], history_key(marker)):
                actions.append({"Update": {"TableName": table.name, "Key": {"pk": pk, "sk": sk},
                    "UpdateExpression": "SET notification = :n", "ConditionExpression": "scan_id = :id AND connection_version = :v",
                    "ExpressionAttributeValues": {":n": notification, ":id": job["scan_id"], ":v": profile["connection_version"]}}})
            transaction(actions)
        except Exception as error:
            scan_log("notification_failed", saved, type(error).__name__)

def notify(profile, result):
    settings = profile.get("notifications", {})
    sender = os.environ.get("SES_SENDER", "")
    if not settings.get("enabled") or not sender:
        return "DISABLED"
    recipient = settings.get("email")
    if not recipient:
        return "DISABLED"
    candidates = [finding for finding in result["findings"] if finding["level"] == "REVIEW"]
    identities = sorted({
        json.dumps([finding["type"], finding["resource_id"], finding.get("rule_id", "")])
        for finding in candidates
    })
    digest = hashlib.sha256(json.dumps(identities).encode()).hexdigest()
    # A new verified recipient must not inherit another recipient's dedup state.
    recipient_key = hashlib.sha256(recipient.encode()).hexdigest()
    key = "NOTICE#" + profile["connection_version"] + "#" + result["region"] + "#" + recipient_key
    now = int(time.time())
    try:
        previous = get(profile["pk"], key)
    except (ClientError, BotoCoreError):
        log.exception("Could not read notification state; no SES request made")
        return "STATE_FAILED"
    if previous.get("fingerprint") == digest:
        return "UNCHANGED"
    if previous.get("status") == "SENDING" and previous.get("cooldown_until", 0) > now:
        return "IN_PROGRESS"
    if candidates and previous.get("cooldown_until", 0) > now:
        return "COOLDOWN"

    token = str(uuid.uuid4())
    record = {**previous, "pk": profile["pk"], "sk": key, "attempt_token": token}
    if candidates:
        record.update(
            status="SENDING", attempted_at=now, attempt_fingerprint=digest,
            cooldown_until=now + config(profile.get("settings", {}))["interval_hours"] * 3600,
            scan_id=result.get("scan_id", ""),
        )
        record.pop("message_id", None)
        record.pop("error_code", None)
    else:
        # Resolution resets dedup, but never resets the last attempt's cooldown.
        record["fingerprint"] = digest
        record.setdefault("status", "NO_NEW_FINDINGS")
        if record["status"] == "SENDING":
            record.update(status="UNKNOWN", error_code="AcceptanceNotRecorded")
    condition = "attempt_token = :previous" if previous.get("attempt_token") else "attribute_not_exists(attempt_token)"
    claim = {"ConditionExpression": condition}
    if previous.get("attempt_token"):
        claim["ExpressionAttributeValues"] = {":previous": previous["attempt_token"]}
    try:
        table.put_item(Item=json.loads(json.dumps(record), parse_float=Decimal), **claim)
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return "IN_PROGRESS"
        log.exception("Could not claim notification; no SES request made")
        return "STATE_FAILED"
    except BotoCoreError:
        log.exception("Could not claim notification; no SES request made")
        return "STATE_FAILED"
    if not candidates:
        return "NO_NEW_FINDINGS"

    lines = [
        "Cloud Resource Guardian",
        "Account: " + profile.get("account_id", "unknown"),
        "Region: " + result["region"],
        "Scan: " + result.get("scan_id", "unknown"),
        "Scan status: " + result.get("status", "unknown"),
        "Completed (UTC): " + datetime.fromtimestamp(result.get("completed_at", now), timezone.utc).isoformat(),
        "Resource counts: " + json.dumps(result.get("counts", {}), sort_keys=True),
        "Displayed REVIEW findings: " + str(len(candidates)),
        "Total findings (all levels): " + str(result.get("finding_count", len(result["findings"]))),
        "Các tài nguyên cần kiểm tra:",
    ]
    for finding in candidates:
        lines.append(finding["type"] + " " + finding["resource_id"] + ": " + finding["reason"])
        if finding.get("rule_id"):
            lines.append("  Rule: " + finding["rule_id"])
        if finding.get("evidence"):
            lines.append("  Evidence: " + json.dumps(finding["evidence"], sort_keys=True, default=str))
    if result.get("errors"):
        lines.append("Scan warnings: " + json.dumps(result["errors"], sort_keys=True))
    lines += [
        result.get("note", "Only selected regions and displayed findings are included."),
        "Mở dashboard: " + os.environ.get("WEB_URL", ""),
        "Đây là ứng viên cần kiểm tra; hệ thống không tự dừng hoặc xóa.",
    ]
    status, message_id, error_code = "SENT", "", ""
    try:
        # SES has no idempotency key: SDK retries could duplicate an accepted send.
        ses_config = SDK_CONFIG.merge(Config(retries={"total_max_attempts": 1}))
        reply = boto3.client("ses", config=ses_config).send_email(
            Source=sender, Destination={"ToAddresses": [recipient]},
            Message={"Subject": {"Data": "Cloud Resource Guardian: tài nguyên cần kiểm tra", "Charset": "UTF-8"},
                     "Body": {"Text": {"Data": "\n".join(lines), "Charset": "UTF-8"}}},
        )
        message_id = reply.get("MessageId", "")
        if not message_id:
            status, error_code = "UNKNOWN", "MissingMessageId"
    except ClientError as error:
        error_code = error.response["Error"]["Code"]
        http_status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        status = "UNKNOWN" if http_status >= 500 or error_code in ("RequestTimeout", "RequestTimeoutException") else "FAILED"
        log.exception("SES request ended with status %s", status)
    except BotoCoreError as error:
        # A lost response does not prove SES rejected the message.
        status, error_code = "UNKNOWN", type(error).__name__
        log.exception("SES acceptance is unknown")

    record["status"] = status
    if status == "SENT":
        record.update(
            fingerprint=digest, message_id=message_id, sent_at=int(time.time()),
            last_message_id=message_id, last_sent_at=int(time.time()),
        )
    else:
        record["error_code"] = error_code
    try:
        table.put_item(
            Item=json.loads(json.dumps(record), parse_float=Decimal), ConditionExpression="attempt_token = :token",
            ExpressionAttributeValues={":token": token},
        )
    except (ClientError, BotoCoreError):
        # The durable SENDING claim still enforces cooldown. Retrying later can
        # duplicate mail if SES accepted it: SES and DynamoDB are not atomic.
        log.exception("Could not persist SES status %s (MessageId=%s)", status, message_id)
        return "SENT_UNRECORDED" if status == "SENT" else status
    return status

def worker(job, context):
    job = dict(job)
    job.pop("_run_token", None)
    try:
        outcome = scan(job, context)
        return outcome or {"scan_id": job["scan_id"], "processed": True}
    except Exception as error:
        scan_log("scan_retry", job, type(error).__name__)
        raise
    finally:
        if job.get("_run_token"):
            try:
                table.update_item(
                    Key={"pk": job["pk"], "sk": "RESULT#" + job["region"]},
                    UpdateExpression="SET run_until = :zero",
                    ConditionExpression="scan_id = :id AND connection_version = :v AND run_token = :token",
                    ExpressionAttributeValues={":zero": 0, ":id": job["scan_id"], ":v": job["connection_version"], ":token": job["_run_token"]},
                )
            except ClientError as error:
                if not conditional_failure(error):
                    # The lease will expire even if its best-effort early release fails.
                    scan_log("lease_release_failed", job, error.response["Error"]["Code"])


def failure_record(envelope):
    if not isinstance(envelope, dict):
        raise ValueError("Invalid failure envelope")
    job, request = envelope.get("requestPayload"), envelope.get("requestContext")
    if not isinstance(job, dict) or not isinstance(request, dict):
        raise ValueError("Invalid failure envelope")
    if (not isinstance(job.get("pk"), str) or not job["pk"].startswith("TENANT#")
            or job.get("region") not in REGIONS or not isinstance(job.get("connection_version"), str)
            or not job["connection_version"]):
        raise ValueError("Invalid failed job")
    _valid_scan_id(job.get("scan_id"))
    condition = request.get("condition")
    attempts = request.get("approximateInvokeCount", 0)
    if condition not in ("RetriesExhausted", "EventAgeExceeded") or type(attempts) is not int or attempts < 0:
        raise ValueError("Invalid failure context")
    marker = get(job["pk"], "RESULT#" + job["region"])
    if (marker.get("scan_id") != job["scan_id"]
            or marker.get("connection_version") != job["connection_version"]):
        return
    if marker.get("status") in TERMINAL_STATES:
        release_tenant(marker["pk"], marker["scan_id"], marker["connection_version"])
        return
    profile = get(job["pk"], "PROFILE")
    if profile.get("connection_version") != job["connection_version"]:
        return
    if marker.get("run_until", 0) > time.time():
        raise RuntimeError("Worker still holds its lease")
    expired = condition == "EventAgeExceeded" or time.time() >= deadline(marker)
    saved = finish_scan(marker, "TIMED_OUT" if expired else "FAILED", attempts=attempts,
                        error_code="EVENT_AGE_EXCEEDED" if expired else "RETRIES_EXHAUSTED",
                        error_message="Scan event expired" if expired else "Worker failed after bounded retries; inspect scan logs")
    if not saved:
        # A worker can claim the marker between our read and conditional transaction.
        latest = get(job["pk"], "RESULT#" + job["region"])
        if (latest.get("scan_id") == job["scan_id"] and latest.get("status") in ACTIVE_STATES
                and latest.get("connection_version") == job["connection_version"]):
            raise RuntimeError("Scan finalization raced with a worker; retry recovery")


def recovery(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            failure_record(json.loads(record["body"]))
        except Exception as error:
            # Never log the body, invocation payload or response stack from the destination envelope.
            log.warning("Recovery record failed error_type=%s", type(error).__name__)
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def reconcile(event, context):
    args = {"ConsistentRead": True, "FilterExpression": "begins_with(sk, :prefix) AND #s IN (:q, :r)",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":prefix": "RESULT#", ":q": "QUEUED", ":r": "RUNNING"}}
    completed, failed = 0, False
    while True:
        page = table.scan(**args)
        for marker in normalized(page.get("Items", [])):
            try:
                if marker.get("status") not in ACTIVE_STATES or not marker.get("sk", "").startswith("RESULT#"):
                    continue
                if time.time() >= deadline(marker) and marker.get("run_until", 0) <= time.time():
                    if finish_scan(marker, "TIMED_OUT", error_code="JOB_DEADLINE",
                                   error_message="Scan exceeded its 15 minute deadline", require_current=False):
                        completed += 1
            except (ValueError, TypeError, KeyError):
                log.warning("Reconciler skipped invalid marker")
            except Exception as error:
                failed = True
                scan_log("reconcile_failed", marker, type(error).__name__)
        if not page.get("LastEvaluatedKey"):
            break
        args["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    if failed:
        raise RuntimeError("Reconciliation infrastructure failure; independent scans processed")
    return {"timed_out_regions": completed}
