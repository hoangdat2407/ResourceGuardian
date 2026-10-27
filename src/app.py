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

def enqueue(profile, now):
    pk = profile["pk"]
    # One lease per tenant prevents concurrent manual/scheduled jobs.
    try:
        table.update_item(Key={"pk": pk, "sk": "LOCK"},
            UpdateExpression="SET lease_until = :until",
            ConditionExpression="attribute_not_exists(lease_until) OR lease_until < :now",
            ExpressionAttributeValues={":until": now + 600, ":now": now})
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException": return None
        raise
    scan_id = str(uuid.uuid4())
    # Invoke only after all result markers exist. Lambda retries errors and sends
    # exhausted events to the failure queue configured in template.yaml.
    for region in profile["regions"]:
        put({"pk": pk, "sk": "RESULT#" + region, "scan_id": scan_id, "status": "QUEUED", "started_at": now, "region": region, "connection_version": profile["connection_version"]})
    for region in profile["regions"]:
        job = {"pk": pk, "region": region, "scan_id": scan_id, "connection_version": profile["connection_version"]}
        try:
            reply = invoker.invoke(FunctionName=os.environ["WORKER_FUNCTION"], InvocationType="Event", Payload=json.dumps(job).encode())
            if reply["StatusCode"] != 202: raise RuntimeError("Worker event not accepted")
        except Exception:
            log.exception("Could not dispatch region job")
            put({"pk": pk, "sk": "RESULT#" + region, "scan_id": scan_id, "status": "FAILED", "started_at": now,
                 "completed_at": now, "region": region, "connection_version": profile["connection_version"], "error": "Dispatch failed; try another scan later"})
    table.update_item(Key={"pk": pk, "sk": "PROFILE"}, UpdateExpression="SET last_queued = :now",
                      ExpressionAttributeValues={":now": now})
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


def apply_feedback(row, feedback):
    result = dict(row)
    findings = []
    now = time.time()
    for finding in row.get("findings", []):
        item = dict(finding)
        record = feedback.get(item.get("finding_id"))
        if record and (record.get("kept") or record.get("ignore_until", 0) > now):
            continue
        if record and record.get("acknowledged"):
            item["acknowledged"] = True
        findings.append(item)
    result["findings"] = findings
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
        for finding in row.get("findings", [])
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
            if old_version:
                for record in all_items(pk, "FEEDBACK#" + old_version + "#"):
                    if "expires" not in record:
                        record["expires"] = now + 30 * 86400
                        put(record)
            candidate["account_id"] = actual
            candidate["connection_version"] = str(uuid.uuid4())
            put(candidate)
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
            if now - profile.get("last_queued", 0) < 900:
                return response(429, {"error": "Wait 15 minutes between scans"})
            scan_id = enqueue(profile, now)
            return response(202 if scan_id else 409, {"scan_id": scan_id, "message": "Queued" if scan_id else "Scan lease is active"})
        if route == "/findings":
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
            return response(200, {"results": rows, "next_token": next_token})
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
    except ClientError:
        log.exception("AWS request failed")
        return response(502, {"error": "AWS request failed; check role permissions and CloudWatch logs"})


def visible_result(row):
    if row.get("status") in ("QUEUED", "RUNNING") and time.time() - row.get("started_at", time.time()) > 900:
        return {**row, "status": "TIMED_OUT", "error": "Scan did not complete within 15 minutes. Check Lambda failure queue and retry."}
    return row


def history(pk, profile):
    return page_rows(pk, "HISTORY#", profile, 20)[0]

def scheduler(event, context):
    args = {}
    count = 0
    while True:
        page = table.scan(**args)
        for p in normalized(page.get("Items", [])):
            if p.get("sk") != "PROFILE" or not p.get("role_arn"): continue
            p = normalize_profile(p)
            now = int(time.time())
            if now - p.get("last_queued", 0) >= p["settings"]["interval_hours"] * 3600:
                if enqueue(p, now): count += 1
        if not page.get("LastEvaluatedKey"): break
        args["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return {"queued_tenants": count}

def scan(job, context):
    pk, region = job["pk"], job["region"]
    marker = get(pk, "RESULT#" + region)
    if marker.get("scan_id") != job["scan_id"] or marker.get("status") in ("SUCCEEDED", "PARTIAL", "FAILED"):
        return
    profile = normalize_profile(get(pk, "PROFILE"))
    if region not in profile.get("regions", []) or job.get("connection_version") != profile.get("connection_version"):
        return
    now = int(time.time())
    run_token = str(uuid.uuid4())
    try:
        table.update_item(
            Key={"pk": pk, "sk": "RESULT#" + region},
            UpdateExpression="SET #state = :running, run_until = :until, run_token = :token",
            ConditionExpression="scan_id = :id AND (attribute_not_exists(run_until) OR run_until < :now)",
            ExpressionAttributeNames={"#state": "status"},
            ExpressionAttributeValues={":running": "RUNNING", ":until": now + 330, ":token": run_token, ":id": job["scan_id"], ":now": now},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        latest = get(pk, "RESULT#" + region)
        if latest.get("scan_id") != job["scan_id"] or latest.get("status") in ("SUCCEEDED", "PARTIAL", "FAILED"):
            return
        raise RuntimeError("Duplicate event while worker lease is active; retry later") from error
    job["_run_token"] = run_token
    sess = session(profile)

    def observed(kind, ident, bad):
        sk = "OBS#" + profile["connection_version"] + "#" + region + "#" + ident
        old = get(pk, sk)
        if not bad:
            if old:
                table.delete_item(Key={"pk": pk, "sk": sk})
            return 0
        first = old.get("first", now) if now - old.get("last", now) <= 48 * 3600 else now
        put({"pk": pk, "sk": sk, "first": first, "last": now, "expires": now + 7 * 86400})
        return (now - first) / 3600

    def time_check():
        if context.get_remaining_time_in_millis() < 30000:
            raise TimeoutError("Scan stopped before Lambda timeout")

    collected = collect_region(
        sess, region, profile.get("account_id", ""), profile["settings"],
        profile["service_groups"], datetime.now(timezone.utc), time_check, observed,
    )
    skip = {r["sk"].rsplit("#", 1)[1] for r in all_items(pk, "IGNORE#" + profile["connection_version"] + "#" + region + "#") if r.get("expires", 0) > now}
    skip.update(r["sk"].rsplit("#", 1)[1] for r in all_items(pk, "KEEP#" + profile["connection_version"] + "#" + region + "#") if r.get("enabled") is True)
    feedback = feedback_records(pk, profile, region)
    actionable = [
        finding for finding in collected["findings"]
        if finding.get("resource_id") not in skip
        and not feedback.get(finding["finding_id"], {}).get("kept")
        and feedback.get(finding["finding_id"], {}).get("ignore_until", 0) <= now
    ]
    errors = list(collected["errors"])
    too_many_findings = len(actionable) > 50
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
        "findings": actionable[:50], "finding_count": len(actionable), "errors": errors,
        "note": "Limit 100 resources/type and 50 displayed findings/region. Only selected regions scanned.",
        "expires": now + 30 * 86400,
    }
    table.put_item(
        Item=json.loads(json.dumps(result), parse_float=Decimal),
        ConditionExpression="scan_id = :id AND run_token = :token",
        ExpressionAttributeValues={":id": job["scan_id"], ":token": run_token},
    )
    result["notification"] = notify(profile, result)
    table.update_item(
        Key={"pk": pk, "sk": "RESULT#" + region}, UpdateExpression="SET notification = :n",
        ConditionExpression="scan_id = :id",
        ExpressionAttributeValues={":n": result["notification"], ":id": job["scan_id"]},
    )
    put({**result, "sk": "HISTORY#" + str(now) + "#" + region + "#" + job["scan_id"]})

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
    try:
        scan(job, context)
        return {"scan_id": job["scan_id"], "processed": True}
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "ConditionalCheckFailedException": return {"skipped": True}
        if code in ("AccessDenied", "AccessDeniedException", "InvalidClientTokenId", "ExpiredToken"):
            try:
                item = {"pk": job["pk"], "sk": "RESULT#" + job["region"], "region": job["region"], "scan_id": job["scan_id"],
                        "connection_version": job.get("connection_version"), "status": "FAILED",
                        "error": "Cannot access AWS; reconnect and check role permissions", "completed_at": int(time.time())}
                table.put_item(Item=item, ConditionExpression="scan_id = :id", ExpressionAttributeValues={":id": job["scan_id"]})
            except ClientError: log.exception("Could not persist failure status")
            return {"failed": True}
        log.exception("Scan failed; async invocation will retry")
        raise
    finally:
        if job.get("_run_token"):
            try:
                table.update_item(Key={"pk": job["pk"], "sk": "RESULT#" + job["region"]},
                    UpdateExpression="SET run_until = :zero",
                    ConditionExpression="scan_id = :id AND run_token = :token",
                    ExpressionAttributeValues={":zero": 0, ":id": job["scan_id"], ":token": job["_run_token"]})
            except ClientError as e:
                if e.response["Error"]["Code"] != "ConditionalCheckFailedException": log.exception("Could not release worker lease")
