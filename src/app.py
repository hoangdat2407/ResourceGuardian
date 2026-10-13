import os, json, time, uuid, re, logging, hashlib
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from botocore.config import Config
from rules import config, keep, idle

log = logging.getLogger()
log.setLevel(logging.INFO)
table = boto3.resource("dynamodb").Table(os.environ["TABLE"])
invoker = boto3.client("lambda")
SDK_CONFIG = Config(retries={"mode": "standard", "max_attempts": 5}, connect_timeout=5, read_timeout=20)
REGIONS = {"ap-southeast-1", "ap-southeast-2", "ap-northeast-1", "us-east-1", "us-west-2", "eu-west-1"}

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

def api(event, context):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not claims.get("sub") or claims.get("token_use") != "access": return response(401, {"error": "Access token required"})
    pk = "TENANT#" + claims["sub"]  # Never accept tenant identity from request parameters.
    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "")
    profile = get(pk, "PROFILE")
    if not profile:
        initial = {"pk": pk, "sk": "PROFILE", "external_id": str(uuid.uuid4()), "settings": config({})}
        try:
            table.put_item(Item=json.loads(json.dumps(initial), parse_float=Decimal), ConditionExpression="attribute_not_exists(pk)")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
        profile = get(pk, "PROFILE")
    try:
        body = json.loads(event.get("body") or "{}")
        if not isinstance(body, dict): raise ValueError("Expected a JSON object")
        if path == "/me" and method == "GET":
            return response(200, {**profile, "api_principal": os.environ["API_PRINCIPAL"], "scan_principal": os.environ["SCAN_PRINCIPAL"], "email_available": bool(os.environ.get("SES_SENDER"))})
        if path == "/connection" and method == "PUT":
            arn = body.get("role_arn", "")
            if not isinstance(arn, str) or not re.fullmatch(r"arn:aws:iam::\d{12}:role/GuardianReadRole-[A-Za-z0-9+=,.@_-]{1,40}", arn):
                raise ValueError("Role name must be GuardianReadRole-<suffix> without a path")
            regions = body.get("regions", [])
            if not isinstance(regions, list) or not 1 <= len(regions) <= 3 or len(set(regions)) != len(regions) or any(r not in REGIONS for r in regions):
                raise ValueError("Choose 1 to 3 supported regions")
            candidate = {**profile, "role_arn": arn, "regions": regions}
            actual = session(candidate).client("sts").get_caller_identity()["Account"]
            if actual != arn.split(":")[4]: raise ValueError("Account mismatch")
            candidate["account_id"] = actual
            candidate["connection_version"] = str(uuid.uuid4())
            put(candidate)
            return response(200, {"connected": True, "account_id": actual})
        if path == "/settings" and method == "PUT":
            cfg = config(body)
            table.update_item(Key={"pk": pk, "sk": "PROFILE"}, UpdateExpression="SET settings = :s",
                ExpressionAttributeValues={":s": json.loads(json.dumps(cfg), parse_float=Decimal)})
            return response(200, cfg)
        if path in ("/scan", "/scans") and method == "POST":
            if not profile.get("role_arn"): raise ValueError("Connect AWS first")
            now = int(time.time())
            if now - profile.get("last_queued", 0) < 900: return response(429, {"error": "Wait 15 minutes between scans"})
            scan_id = enqueue(profile, now)
            return response(202 if scan_id else 409, {"scan_id": scan_id, "message": "Queued" if scan_id else "Scan lease is active"})
        if path == "/findings" and method == "GET":
            regions = set(profile.get("regions", []))
            return response(200, {"results": [visible_result(r) for r in all_items(pk, "RESULT#") if r.get("region") in regions and r.get("connection_version") == profile.get("connection_version")]})
        if path == "/history" and method == "GET":
            return response(200, {"results": history(pk, profile)})
        if path.startswith("/scans/") and method == "GET":
            scan_id = path.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[a-f0-9-]{36}", scan_id): raise ValueError("Invalid scan ID")
            rows = [r for r in all_items(pk, "RESULT#") if r.get("scan_id") == scan_id
                    and r.get("connection_version") == profile.get("connection_version")]
            if not rows:
                rows = [r for r in history(pk, profile) if r.get("scan_id") == scan_id]
            if not rows: return response(404, {"error": "Scan not found for this user"})
            return response(200, {"scan_id": scan_id, "results": [visible_result(r) for r in rows]})
        if path == "/notifications" and method == "PUT":
            enabled = body.get("enabled")
            if type(enabled) is not bool: raise ValueError("enabled must be a boolean")
            if enabled and not os.environ.get("SES_SENDER"): raise ValueError("Email has not been configured by platform owner")
            notify = {"enabled": enabled}
            if enabled:
                # Destination is the Cognito-verified address, never an arbitrary body field.
                auth = {k.lower(): v for k, v in event.get("headers", {}).items()}.get("authorization", "")
                if not auth.startswith("Bearer "): raise ValueError("Access token missing")
                attrs = boto3.client("cognito-idp").get_user(AccessToken=auth[7:])["UserAttributes"]
                attrs = {x["Name"]: x["Value"] for x in attrs}
                if attrs.get("email_verified") != "true" or not attrs.get("email"): raise ValueError("Verify Cognito email before enabling alerts")
                notify["email"] = attrs["email"]
            table.update_item(Key={"pk": pk, "sk": "PROFILE"}, UpdateExpression="SET notifications = :n",
                ExpressionAttributeValues={":n": notify})
            return response(200, notify)
        if path == "/ignore" and method == "PUT":
            region, rid = body.get("region", ""), body.get("resource_id", "")
            if region not in profile.get("regions", []) or not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", rid):
                raise ValueError("Invalid region or resource ID")
            days = body.get("days", 7)
            if type(days) is not int or not 1 <= days <= 30: raise ValueError("Ignore duration must be 1 to 30 days")
            put({"pk": pk, "sk": "IGNORE#" + profile["connection_version"] + "#" + region + "#" + rid, "expires": int(time.time()) + days * 86400})
            return response(200, {"ignored": True})
        return response(404, {"error": "Route not found"})
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        return response(400, {"error": str(e)})
    except ClientError:
        log.exception("AWS request failed")
        return response(502, {"error": "AWS request failed; check role permissions and CloudWatch logs"})

def visible_result(row):
    if row.get("status") in ("QUEUED", "RUNNING") and time.time() - row.get("started_at", time.time()) > 900:
        return {**row, "status": "TIMED_OUT", "error": "Scan did not complete within 15 minutes. Check Lambda failure queue and retry."}
    return row

def history(pk, profile):
    # Newest first, at most 20 completed regional scans from this connection.
    args = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("HISTORY#"),
            "ConsistentRead": True, "ScanIndexForward": False, "Limit": 60}
    rows = []
    for _ in range(3):
        page = table.query(**args)
        rows.extend(r for r in normalized(page.get("Items", []))
                    if r.get("connection_version") == profile.get("connection_version") and r.get("expires", 0) > time.time())
        if len(rows) >= 20 or not page.get("LastEvaluatedKey"): break
        args["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return rows[:20]

def scheduler(event, context):
    args = {}
    count = 0
    while True:
        page = table.scan(**args)
        for p in normalized(page.get("Items", [])):
            if p.get("sk") != "PROFILE" or not p.get("role_arn"): continue
            now = int(time.time())
            if now - p.get("last_queued", 0) >= p["settings"]["interval_hours"] * 3600:
                if enqueue(p, now): count += 1
        if not page.get("LastEvaluatedKey"): break
        args["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return {"queued_tenants": count}

def collect(ec2, operation, key, **args):
    values = []
    # MVP intentionally bounded. Report partial inventory instead of claiming full coverage.
    for page in ec2.get_paginator(operation).paginate(**args):
        items = page.get(key, [])
        if key == "Reservations": items = [i for r in items for i in r.get("Instances", [])]
        values.extend(items)
        if len(values) > 100: return values[:100], True
    return values, False

def metrics(cw, instance_id, start, end):
    queries = []
    for metric, statistic, ident in [("CPUUtilization", "Maximum", "cpu"), ("NetworkIn", "Sum", "netin"), ("NetworkOut", "Sum", "netout")]:
        queries.append({"Id": ident, "MetricStat": {"Metric": {"Namespace": "AWS/EC2", "MetricName": metric,
            "Dimensions": [{"Name": "InstanceId", "Value": instance_id}]}, "Period": 3600, "Stat": statistic}, "ReturnData": True})
    args = {"MetricDataQueries": queries, "StartTime": start, "EndTime": end, "ScanBy": "TimestampAscending"}
    values = {"cpu": {}, "netin": {}, "netout": {}}
    while True:
        page = cw.get_metric_data(**args)
        for r in page.get("MetricDataResults", []):
            ident = r["Id"]
            if r.get("StatusCode") not in ("Complete", "PartialData"): raise ValueError("Metric API failed for " + ident)
            # Deduplicate page timestamps; count only real samples, including zero.
            for ts, value in zip(r.get("Timestamps", []), r.get("Values", [])):
                if start <= ts < end: values[ident][ts] = value
        if not page.get("NextToken"): break
        args["NextToken"] = page["NextToken"]
    return [list(values[k].values()) for k in ("cpu", "netin", "netout")]

def scan(job, context):
    pk, region = job["pk"], job["region"]
    marker = get(pk, "RESULT#" + region)
    if marker.get("scan_id") != job["scan_id"] or marker.get("status") in ("SUCCEEDED", "PARTIAL", "FAILED"): return
    profile = get(pk, "PROFILE")
    if region not in profile.get("regions", []) or job.get("connection_version") != profile.get("connection_version"): return
    now = int(time.time())
    run_token = str(uuid.uuid4())
    try:
        table.update_item(Key={"pk": pk, "sk": "RESULT#" + region},
            UpdateExpression="SET #state = :running, run_until = :until, run_token = :token",
            ConditionExpression="scan_id = :id AND (attribute_not_exists(run_until) OR run_until < :now)",
            ExpressionAttributeNames={"#state": "status"},
            ExpressionAttributeValues={":running": "RUNNING", ":until": now + 330, ":token": run_token, ":id": job["scan_id"], ":now": now})
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
        latest = get(pk, "RESULT#" + region)
        if latest.get("scan_id") != job["scan_id"] or latest.get("status") in ("SUCCEEDED", "PARTIAL", "FAILED"): return
        raise RuntimeError("Duplicate event while worker lease is active; retry later") from e
    job["_run_token"] = run_token
    cfg = profile["settings"]
    sess = session(profile)
    ec2, cw = sess.client("ec2", region_name=region, config=SDK_CONFIG), sess.client("cloudwatch", region_name=region, config=SDK_CONFIG)
    findings, errors, counts = [], [], {}
    partial = False
    skip = {r["sk"].rsplit("#", 1)[1] for r in all_items(pk, "IGNORE#" + profile["connection_version"] + "#" + region + "#") if r["expires"] > now}
    def add(kind, rid, reason, evidence=None, level="REVIEW"):
        if rid not in skip:
            findings.append({"type": kind, "resource_id": rid, "region": region, "reason": reason,
                             "evidence": evidence or {}, "level": level})
    def observed(rid, bad):
        sk = "OBS#" + profile["connection_version"] + "#" + region + "#" + rid
        old = get(pk, sk)
        if not bad:
            if old: table.delete_item(Key={"pk": pk, "sk": sk})
            return 0
        first = old.get("first", now) if now - old.get("last", now) <= 48 * 3600 else now
        put({"pk": pk, "sk": sk, "first": first, "last": now, "expires": now + 7 * 86400})
        return (now - first) / 3600
    def time_check():
        if context.get_remaining_time_in_millis() < 30000: raise TimeoutError("Scan stopped before Lambda timeout")
    # Fail each service section independently, retaining useful evidence.
    for kind in ("EC2", "EBS", "EIP", "SNAPSHOT"):
        try:
            time_check()
            if kind == "EC2":
                resources, truncated = collect(ec2, "describe_instances", "Reservations")
                counts[kind] = len(resources); partial |= truncated
                end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
                start = end - timedelta(hours=cfg["window_hours"])
                for i in resources:
                    time_check()
                    if keep(i.get("Tags", [])) or i["State"]["Name"] != "running": continue
                    rid = i["InstanceId"]
                    if i["LaunchTime"] > start:
                        add(kind, rid, "Instance younger than observation window", level="INSUFFICIENT_DATA"); continue
                    status, evidence = idle(*metrics(cw, rid, start, end), cfg["window_hours"], cfg)
                    if status != "OK": add(kind, rid, "Low CPU and network; confirm intended workload" if status == "REVIEW" else "Missing CloudWatch metrics; not classified as idle", evidence, status)
            elif kind == "EBS":
                resources, truncated = collect(ec2, "describe_volumes", "Volumes")
                counts[kind] = len(resources); partial |= truncated
                for v in resources:
                    time_check()
                    rid = v["VolumeId"]; bad = v["State"] == "available" and not v["Attachments"] and not keep(v.get("Tags", []))
                    hours = observed(rid, bad)
                    if bad: add(kind, rid, "Unattached volume; validate data retention", {"size_gib": v["Size"], "observed_hours": round(hours, 1)}, "REVIEW" if hours >= cfg["orphan_hours"] else "OBSERVING")
            elif kind == "EIP":
                resources = ec2.describe_addresses()["Addresses"]
                counts[kind] = min(len(resources), 100); partial |= len(resources) > 100
                for a in resources[:100]:
                    time_check()
                    rid = a.get("AllocationId")
                    if not rid: continue
                    bad = not a.get("AssociationId") and not keep(a.get("Tags", []))
                    hours = observed(rid, bad)
                    if bad: add(kind, rid, "Unassociated public IPv4; may be intentionally reserved", {"observed_hours": round(hours, 1)}, "REVIEW" if hours >= cfg["orphan_hours"] else "OBSERVING")
            else:
                resources, truncated = collect(ec2, "describe_snapshots", "Snapshots", OwnerIds=["self"])
                images, image_trunc = collect(ec2, "describe_images", "Images", Owners=["self"])
                counts[kind] = len(resources); partial |= truncated or image_trunc
                used = {b.get("Ebs", {}).get("SnapshotId") for image in images for b in image.get("BlockDeviceMappings", [])}
                for s in resources:
                    time_check()
                    rid = s["SnapshotId"]; days = (datetime.now(timezone.utc) - s["StartTime"]).total_seconds() / 86400
                    if image_trunc: continue  # Cannot safely claim no AMI reference.
                    if keep(s.get("Tags", [])) or rid in used or "aws:backup" in s.get("Description", "").lower() or any(t.get("Key", "").startswith("aws:backup") for t in s.get("Tags", [])): continue
                    if days >= cfg["snapshot_days"] and s["State"] == "completed":
                        add(kind, rid, "Old snapshot not referenced by listed AMIs; backup purpose requires review", {"age_days": int(days), "volume_id": s.get("VolumeId"), "logical_volume_gib": s["VolumeSize"]})
        except (ClientError, TimeoutError, ValueError) as e:
            partial = True
            errors.append({"type": kind, "code": e.response["Error"]["Code"] if isinstance(e, ClientError) else ("TIME_BUDGET" if isinstance(e, TimeoutError) else "METRIC_DATA_ERROR")})
    current_profile = get(pk, "PROFILE")
    if current_profile.get("connection_version") != profile.get("connection_version"): return
    result = {"pk": pk, "sk": "RESULT#" + region, "region": region, "scan_id": job["scan_id"],
        "status": "PARTIAL" if partial or len(findings) > 50 else "SUCCEEDED", "started_at": marker.get("started_at", now), "completed_at": int(time.time()), "connection_version": profile["connection_version"],
        "counts": counts, "findings": findings[:50], "finding_count": len(findings), "errors": errors,
        "note": "Limit 100 resources/type and 50 displayed findings/region. Only selected regions scanned.", "expires": now + 30 * 86400}
    # Do not overwrite a newer scan when retries arrive out of order.
    table.put_item(Item=json.loads(json.dumps(result), parse_float=Decimal),
        ConditionExpression="scan_id = :id AND run_token = :token", ExpressionAttributeValues={":id": job["scan_id"], ":token": run_token})
    result["notification"] = notify(profile, result)
    table.update_item(Key={"pk": pk, "sk": "RESULT#" + region}, UpdateExpression="SET notification = :n",
        ConditionExpression="scan_id = :id", ExpressionAttributeValues={":n": result["notification"], ":id": job["scan_id"]})
    put({**result, "sk": "HISTORY#" + str(now) + "#" + region + "#" + job["scan_id"]})

def notify(profile, result):
    settings = profile.get("notifications", {})
    sender = os.environ.get("SES_SENDER", "")
    if not settings.get("enabled") or not sender: return "DISABLED"
    candidates = sorted({f["type"] + ":" + f["resource_id"] for f in result["findings"] if f["level"] == "REVIEW"})
    # Track even an empty set, so resources that resolve then reappear alert again.
    digest = hashlib.sha256(json.dumps(candidates).encode()).hexdigest()
    key = "NOTICE#" + profile["connection_version"] + "#" + result["region"]
    previous = get(profile["pk"], key)
    if previous.get("fingerprint") == digest: return "UNCHANGED"
    if not candidates:
        put({"pk": profile["pk"], "sk": key, "fingerprint": digest})
        return "NO_NEW_FINDINGS"
    try:
        lines = ["Cloud Resource Guardian", "Region: " + result["region"], "Các tài nguyên cần kiểm tra:"]
        lines += [f['type'] + " " + f['resource_id'] + ": " + f['reason'] for f in result["findings"] if f["level"] == "REVIEW"]
        lines += ["Mở dashboard: " + os.environ.get("WEB_URL", ""), "Đây là ứng viên cần kiểm tra; hệ thống không tự dừng hoặc xóa."]
        boto3.client("ses", config=SDK_CONFIG).send_email(Source=sender, Destination={"ToAddresses": [settings["email"]]},
            Message={"Subject": {"Data": "Cloud Resource Guardian: tài nguyên cần kiểm tra", "Charset": "UTF-8"},
                     "Body": {"Text": {"Data": "\n".join(lines), "Charset": "UTF-8"}}})
        put({"pk": profile["pk"], "sk": key, "fingerprint": digest, "sent_at": int(time.time())})
        return "SENT"
    except ClientError:
        log.exception("Email delivery request failed")
        return "FAILED"  # Scan result remains available; retry email on next scan.

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
