"""Read-only AWS inventory and metric collectors."""
from datetime import datetime, timezone, timedelta

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from rules import RULE_METADATA, alb_idle, finding_id, idle, keep, nat_idle, nlb_idle, rds_idle, stale_multipart

SDK_CONFIG = Config(
    retries={"mode": "standard", "max_attempts": 5},
    connect_timeout=5,
    read_timeout=20,
)
RESOURCE_LIMIT = 100


def collect_pages(client, operation, result_key, *, max_items=RESOURCE_LIMIT, transform=None, **kwargs):
    """Collect at most max_items and detect one extra item without reading another page."""
    values = []
    for page in client.get_paginator(operation).paginate(**kwargs):
        items = page.get(result_key, [])
        if transform:
            items = transform(items)
        remaining = max_items + 1 - len(values)
        values.extend(items[:remaining])
        if len(values) > max_items:
            return values[:max_items], True
    return values, False


def metric_series(cw, queries, start, end):
    args = {
        "MetricDataQueries": queries,
        "StartTime": start,
        "EndTime": end,
        "ScanBy": "TimestampAscending",
    }
    values = {query["Id"]: {} for query in queries}
    while True:
        page = cw.get_metric_data(**args)
        for result in page.get("MetricDataResults", []):
            ident = result["Id"]
            if result.get("StatusCode") not in ("Complete", "PartialData"):
                raise ValueError("Metric API failed for " + ident)
            for timestamp, value in zip(result.get("Timestamps", []), result.get("Values", [])):
                if start <= timestamp < end:
                    values[ident][timestamp] = value
        token = page.get("NextToken")
        if not token:
            break
        args["NextToken"] = token
    return {ident: list(series.values()) for ident, series in values.items()}


def _queries(namespace, dimension_name, dimension_value, metrics):
    return [
        {
            "Id": ident,
            "MetricStat": {
                "Metric": {
                    "Namespace": namespace,
                    "MetricName": name,
                    "Dimensions": [{"Name": dimension_name, "Value": dimension_value}],
                },
                "Period": 3600,
                "Stat": statistic,
            },
            "ReturnData": True,
        }
        for name, statistic, ident in metrics
    ]


def _error_code(error):
    if isinstance(error, ClientError):
        return error.response["Error"]["Code"]
    if isinstance(error, TimeoutError):
        return "TIME_BUDGET"
    if isinstance(error, BotoCoreError):
        return error.__class__.__name__
    return "METRIC_DATA_ERROR"

def collect_region(session, region, account_id, cfg, service_groups, now, time_check, observed):
    """Collect selected services in one region without performing AWS mutations."""
    counts, findings, errors = {}, [], []
    partial = False
    end = now.replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=cfg["window_hours"])
    clients = {}

    def client(name):
        if name not in clients:
            clients[name] = session.client(name, region_name=region, config=SDK_CONFIG)
        return clients[name]

    def add(kind, resource_id, stable_identity, reason, evidence=None, level="REVIEW"):
        rule_info = RULE_METADATA.get(kind, (kind, ""))
        findings.append({
            "finding_id": finding_id(kind, region, stable_identity),
            "type": kind,
            "resource_id": resource_id,
            "region": region,
            "reason": reason,
            "evidence": evidence or {},
            "level": level,
            "rule_id": rule_info[0],
            "recommendation": rule_info[1],
        })

    def limited(kind, truncated):
        nonlocal partial
        if truncated:
            partial = True
            errors.append({"type": kind, "code": "RESOURCE_LIMIT"})

    def ec2_instances():
        resources, truncated = collect_pages(
            client("ec2"), "describe_instances", "Reservations",
            transform=lambda reservations: [item for reservation in reservations for item in reservation.get("Instances", [])],
        )
        counts["EC2"] = len(resources)
        limited("EC2", truncated)
        for instance in resources:
            time_check()
            if keep(instance.get("Tags", [])) or instance.get("State", {}).get("Name") != "running":
                continue
            resource_id = instance["InstanceId"]
            if instance["LaunchTime"] > start:
                add("EC2", resource_id, resource_id, "Instance younger than observation window", level="INSUFFICIENT_DATA")
                continue
            queries = _queries("AWS/EC2", "InstanceId", resource_id, [
                ("CPUUtilization", "Maximum", "cpu"),
                ("NetworkIn", "Sum", "netin"),
                ("NetworkOut", "Sum", "netout"),
            ])
            series = metric_series(client("cloudwatch"), queries, start, end)
            status, evidence = idle(series["cpu"], series["netin"], series["netout"], cfg["window_hours"], cfg)
            if status != "OK":
                reason = "Low CPU and network; confirm intended workload" if status == "REVIEW" else "Missing CloudWatch metrics; not classified as idle"
                add("EC2", resource_id, resource_id, reason, evidence, status)

    def ebs_volumes():
        resources, truncated = collect_pages(client("ec2"), "describe_volumes", "Volumes")
        counts["EBS"] = len(resources)
        limited("EBS", truncated)
        for volume in resources:
            time_check()
            resource_id = volume["VolumeId"]
            bad = volume.get("State") == "available" and not volume.get("Attachments")
            hours = observed("EBS", resource_id, bad)
            if bad and not keep(volume.get("Tags", [])):
                add("EBS", resource_id, resource_id, "Unattached volume; validate data retention", {"size_gib": volume["Size"], "observed_hours": round(hours, 1), "threshold_hours": cfg["orphan_hours"]}, "REVIEW" if hours >= cfg["orphan_hours"] else "OBSERVING")
    def eip_addresses():
        addresses = client("ec2").describe_addresses().get("Addresses", [])
        truncated = len(addresses) > RESOURCE_LIMIT
        resources = addresses[:RESOURCE_LIMIT] if truncated else addresses
        counts["EIP"] = len(resources)
        limited("EIP", truncated)
        for address in resources:
            time_check()
            resource_id = address.get("AllocationId")
            if not resource_id:
                continue
            bad = not address.get("AssociationId")
            hours = observed("EIP", resource_id, bad)
            if bad and not keep(address.get("Tags", [])):
                add("EIP", resource_id, resource_id, "Unassociated public IPv4; may be intentionally reserved", {"observed_hours": round(hours, 1), "threshold_hours": cfg["orphan_hours"]}, "REVIEW" if hours >= cfg["orphan_hours"] else "OBSERVING")

    def snapshots():
        resources, truncated = collect_pages(client("ec2"), "describe_snapshots", "Snapshots", OwnerIds=["self"])
        images, images_truncated = collect_pages(client("ec2"), "describe_images", "Images", Owners=["self"], IncludeDisabled=True)
        counts["SNAPSHOT"] = len(resources)
        limited("SNAPSHOT", truncated)
        if images_truncated:
            limited("SNAPSHOT", True)
            errors[-1]["code"] = "INVENTORY_TRUNCATED"
            return
        used = {mapping.get("Ebs", {}).get("SnapshotId") for image in images for mapping in image.get("BlockDeviceMappings", [])}
        for snapshot in resources:
            time_check()
            resource_id = snapshot["SnapshotId"]
            days = (now - snapshot["StartTime"]).total_seconds() / 86400
            tags = snapshot.get("Tags", [])
            if keep(tags) or resource_id in used or "aws:backup" in snapshot.get("Description", "").lower() or any(tag.get("Key", "").startswith("aws:backup") for tag in tags):
                continue
            if days >= cfg["snapshot_days"] and snapshot.get("State") == "completed":
                add("SNAPSHOT", resource_id, resource_id, "Old snapshot not referenced by listed AMIs; backup purpose requires review", {"age_days": int(days), "snapshot_days": cfg["snapshot_days"], "volume_id": snapshot.get("VolumeId"), "logical_volume_gib": snapshot["VolumeSize"], "relationships_complete": True})

    def s3_multipart():
        s3 = client("s3")
        buckets, token = [], None
        while True:
            args = {"BucketRegion": region, "MaxBuckets": 1000}
            if token:
                args["ContinuationToken"] = token
            page = s3.list_buckets(**args)
            buckets.extend(bucket for bucket in page.get("Buckets", []) if not bucket.get("BucketRegion") or bucket.get("BucketRegion") == region)
            token = page.get("ContinuationToken")
            if not token:
                break
        uploads, truncated = [], False
        for bucket in buckets:
            try:
                paginator = s3.get_paginator("list_multipart_uploads")
                for page in paginator.paginate(Bucket=bucket["Name"], ExpectedBucketOwner=account_id):
                    room = RESOURCE_LIMIT + 1 - len(uploads)
                    uploads.extend((bucket["Name"], upload) for upload in page.get("Uploads", [])[:room])
                    if len(uploads) > RESOURCE_LIMIT:
                        uploads, truncated = uploads[:RESOURCE_LIMIT], True
                        break
                if truncated:
                    break
            except ClientError as error:
                nonlocal partial
                partial = True
                errors.append({"type": "S3_MULTIPART", "code": _error_code(error), "resource_id": bucket["Name"]})
        counts["S3_MULTIPART"] = len(uploads)
        limited("S3_MULTIPART", truncated)
        for bucket, upload in uploads:
            time_check()
            status, evidence = stale_multipart(upload["Initiated"], now)
            if status == "REVIEW":
                evidence.update(bucket=bucket, key=upload["Key"], upload_id=upload["UploadId"], initiated_at=upload["Initiated"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"))
                add("S3_MULTIPART", "s3://" + bucket + "/" + upload["Key"], [bucket, upload["Key"], upload["UploadId"]], "Multipart upload older than 7 days; confirm whether it is still needed", evidence)

    def rds_instances():
        resources, truncated = collect_pages(client("rds"), "describe_db_instances", "DBInstances")
        counts["RDS"] = len(resources)
        limited("RDS", truncated)
        for instance in resources:
            time_check()
            if instance.get("DBInstanceStatus") != "available" or instance.get("InstanceCreateTime", now) > start or keep(instance.get("TagList", [])):
                continue
            resource_id = instance["DBInstanceIdentifier"]
            queries = _queries("AWS/RDS", "DBInstanceIdentifier", resource_id, [("CPUUtilization", "Maximum", "cpu"), ("DatabaseConnections", "Maximum", "connections")])
            series = metric_series(client("cloudwatch"), queries, start, end)
            status, evidence = rds_idle(series["cpu"], series["connections"], cfg["window_hours"], cfg)
            if status != "OK":
                evidence = evidence or {}
                evidence.update(engine=instance.get("Engine"), instance_class=instance.get("DBInstanceClass"))
                add("RDS", resource_id, instance["DBInstanceArn"], "Low database activity; confirm intended workload" if status == "REVIEW" else "Missing CloudWatch metrics; not classified as idle", evidence, status)

    def nat_gateways():
        resources, truncated = collect_pages(client("ec2"), "describe_nat_gateways", "NatGateways")
        counts["NAT_GATEWAY"] = len(resources)
        limited("NAT_GATEWAY", truncated)
        for gateway in resources:
            time_check()
            if gateway.get("State") != "available" or gateway.get("CreateTime", now) > start or keep(gateway.get("Tags", [])):
                continue
            resource_id = gateway["NatGatewayId"]
            queries = _queries("AWS/NATGateway", "NatGatewayId", resource_id, [("BytesInFromSource", "Sum", "source"), ("BytesInFromDestination", "Sum", "destination")])
            series = metric_series(client("cloudwatch"), queries, start, end)
            status, evidence = nat_idle(series["source"], series["destination"], cfg["window_hours"], cfg)
            if status != "OK":
                evidence = evidence or {}
                evidence.update(vpc_id=gateway.get("VpcId"), subnet_id=gateway.get("SubnetId"))
                add("NAT_GATEWAY", resource_id, resource_id, "Low NAT traffic; confirm intended workload" if status == "REVIEW" else "Missing CloudWatch metrics; not classified as idle", evidence, status)

    def load_balancers():
        partitions = {"ALB": [], "NLB": []}
        for page in client("elbv2").get_paginator("describe_load_balancers").paginate():
            for item in page.get("LoadBalancers", []):
                kind = {"application": "ALB", "network": "NLB"}.get(item.get("Type"))
                if kind and len(partitions[kind]) <= RESOURCE_LIMIT:
                    partitions[kind].append(item)
            if all(len(items) > RESOURCE_LIMIT for items in partitions.values()):
                break
        for kind, items in partitions.items():
            truncated = len(items) > RESOURCE_LIMIT
            items = items[:RESOURCE_LIMIT]
            counts[kind] = len(items)
            limited(kind, truncated)
            for load_balancer in items:
                time_check()
                if load_balancer.get("State", {}).get("Code") != "active" or load_balancer.get("CreatedTime", now) > start:
                    continue
                resource_id = load_balancer["LoadBalancerName"]
                dimension = load_balancer["LoadBalancerArn"].split("loadbalancer/", 1)[-1]
                if kind == "ALB":
                    queries = _queries("AWS/ApplicationELB", "LoadBalancer", dimension, [("RequestCount", "Sum", "requests")])
                    series = metric_series(client("cloudwatch"), queries, start, end)
                    status, evidence = alb_idle(series["requests"], cfg["window_hours"], cfg)
                    reason = "Low ALB request volume; confirm intended workload"
                else:
                    queries = _queries("AWS/NetworkELB", "LoadBalancer", dimension, [("NewFlowCount", "Sum", "flows")])
                    series = metric_series(client("cloudwatch"), queries, start, end)
                    status, evidence = nlb_idle(series["flows"], cfg["window_hours"], cfg)
                    reason = "Low NLB flow volume; confirm intended workload"
                if status != "OK":
                    evidence = evidence or {}
                    evidence["scheme"] = load_balancer.get("Scheme")
                    add(kind, resource_id, load_balancer["LoadBalancerArn"], reason if status == "REVIEW" else "Missing CloudWatch metrics; not classified as idle", evidence, status)

    operations = []
    if "compute" in service_groups:
        operations.append(("EC2", ec2_instances))
    if "storage" in service_groups:
        operations.extend((("EBS", ebs_volumes), ("SNAPSHOT", snapshots), ("S3_MULTIPART", s3_multipart)))
    if "database" in service_groups:
        operations.append(("RDS", rds_instances))
    if "network" in service_groups:
        operations.extend((("EIP", eip_addresses), ("NAT_GATEWAY", nat_gateways), ("ELB", load_balancers)))

    for index, (kind, operation) in enumerate(operations):
        try:
            time_check()
            operation()
        except TimeoutError:
            partial = True
            errors.append({"type": kind, "code": "TIME_BUDGET"})
            errors.extend({"type": remaining, "code": "TIME_BUDGET"} for remaining, _ in operations[index + 1:])
            break
        except (ClientError, BotoCoreError, ValueError) as error:
            partial = True
            errors.append({"type": kind, "code": _error_code(error)})

    return {"counts": counts, "findings": findings, "errors": errors, "partial": partial}
