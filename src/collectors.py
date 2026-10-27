"""Read-only AWS inventory and metric collectors."""
from datetime import datetime, timezone, timedelta

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from rules import (
    evaluate_ebs,
    evaluate_ec2,
    evaluate_eip,
    evaluate_load_balancer,
    evaluate_nat_gateway,
    evaluate_rds,
    evaluate_s3_multipart,
    evaluate_snapshot,
    finding_id,
    keep,
)

SDK_CONFIG = Config(
    retries={"mode": "standard", "total_max_attempts": 3},
    connect_timeout=3,
    read_timeout=10,
)
RESOURCE_LIMIT = 100


def _pages(client, operation, time_check, **kwargs):
    pages = iter(client.get_paginator(operation).paginate(**kwargs))
    while True:
        # A for-loop fetches the next AWS page before entering its body.
        if time_check:
            time_check()
        try:
            page = next(pages)
        except StopIteration:
            return
        yield page


def collect_pages(client, operation, result_key, *, max_items=RESOURCE_LIMIT, transform=None, time_check=None, **kwargs):
    """Collect at most max_items and detect one extra item without reading another page."""
    values = []
    for page in _pages(client, operation, time_check, **kwargs):
        items = page.get(result_key, [])
        if transform:
            items = transform(items)
        remaining = max_items + 1 - len(values)
        values.extend(items[:remaining])
        if len(values) > max_items:
            return values[:max_items], True
    return values, False


def metric_series(cw, queries, start, end, *, time_check=None):
    """Read all metric pages, retaining raw sample values for rule diagnostics."""
    args = {
        "MetricDataQueries": queries,
        "StartTime": start,
        "EndTime": end,
        "ScanBy": "TimestampAscending",
    }
    values = {query["Id"]: {} for query in queries}
    tokens = set()
    while True:
        if time_check:
            time_check()
        page = cw.get_metric_data(**args)
        if not isinstance(page, dict) or not isinstance(page.get("MetricDataResults", []), list):
            raise ValueError("Malformed metric API response")
        for result in page.get("MetricDataResults", []):
            if not isinstance(result, dict):
                raise ValueError("Malformed metric result")
            ident = result.get("Id")
            if not isinstance(ident, str) or ident not in values:
                raise ValueError("Unexpected metric result ID")
            if result.get("StatusCode") not in ("Complete", "PartialData"):
                raise ValueError("Metric API failed for " + ident)
            timestamps, samples = result.get("Timestamps", []), result.get("Values", [])
            if not isinstance(timestamps, list) or not isinstance(samples, list) or len(timestamps) != len(samples):
                raise ValueError("Malformed metric series for " + ident)
            for timestamp, value in zip(timestamps, samples):
                if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
                    raise ValueError("Malformed metric timestamp for " + ident)
                if start <= timestamp < end:
                    if (timestamp - start).total_seconds() % 3600:
                        raise ValueError("Metric timestamp is not on the hourly grid for " + ident)
                    if timestamp in values[ident]:
                        previous = values[ident][timestamp]
                        numeric_pair = type(previous) in (int, float) and type(value) in (int, float)
                        if (type(previous) is not type(value) and not numeric_pair) or previous != value:
                            raise ValueError("Conflicting metric samples for " + ident)
                    else:
                        values[ident][timestamp] = value
        token = page.get("NextToken")
        if token is None or token == "":
            break
        if not isinstance(token, str) or token in tokens:
            raise ValueError("Invalid metric pagination token")
        tokens.add(token)
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

    def add(finding, stable_identity):
        if finding is None:
            return
        kind = finding["type"]
        context = {
            "account_id": account_id,
            "region": region,
            "evaluated_at": now.astimezone(timezone.utc).isoformat(),
        }
        evidence = {**finding["evidence"], **context}
        if kind in {"EC2", "RDS", "NAT_GATEWAY", "ALB", "NLB"}:
            evidence.update(
                observation_start=start.astimezone(timezone.utc).isoformat(),
                observation_end=end.astimezone(timezone.utc).isoformat(),
                metric_period_seconds=3600,
                metric_statistics={
                    "EC2": {"cpu": "Maximum", "netin": "Sum", "netout": "Sum"},
                    "RDS": {"cpu": "Maximum", "connections": "Maximum"},
                    "NAT_GATEWAY": {"source": "Sum", "destination": "Sum"},
                    "ALB": {"requests": "Sum"},
                    "NLB": {"flows": "Sum"},
                }[kind],
            )
        findings.append({
            **finding,
            **context,
            "finding_id": finding_id(kind, region, stable_identity),
            "evidence": evidence,
        })

    def limited(kind, truncated):
        nonlocal partial
        if truncated:
            partial = True
            errors.append({"type": kind, "code": "RESOURCE_LIMIT"})

    def has_full_window(created_at):
        return (
            isinstance(created_at, datetime)
            and created_at.tzinfo is not None
            and created_at.utcoffset() is not None
            and created_at <= start
        )

    def ec2_instances():
        resources, truncated = collect_pages(
            client("ec2"), "describe_instances", "Reservations",
            transform=lambda reservations: [item for reservation in reservations for item in reservation.get("Instances", [])],
            time_check=time_check,
        )
        counts["EC2"] = len(resources)
        limited("EC2", truncated)
        for instance in resources:
            time_check()
            if keep(instance.get("Tags", [])) or instance.get("State", {}).get("Name") != "running":
                continue
            resource_id = instance["InstanceId"]
            metric_values = ([], [], [])
            if has_full_window(instance.get("LaunchTime")):
                queries = _queries("AWS/EC2", "InstanceId", resource_id, [
                    ("CPUUtilization", "Maximum", "cpu"),
                    ("NetworkIn", "Sum", "netin"),
                    ("NetworkOut", "Sum", "netout"),
                ])
                series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
                metric_values = (series["cpu"], series["netin"], series["netout"])
            add(evaluate_ec2(instance, metric_values, cfg, start), resource_id)

    def ebs_volumes():
        resources, truncated = collect_pages(client("ec2"), "describe_volumes", "Volumes", time_check=time_check)
        counts["EBS"] = len(resources)
        limited("EBS", truncated)
        for volume in resources:
            time_check()
            resource_id = volume["VolumeId"]
            bad = volume.get("State") == "available" and not volume.get("Attachments")
            hours = observed("EBS", resource_id, bad)
            add(evaluate_ebs(volume, hours, cfg), resource_id)

    def eip_addresses():
        time_check()
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
            add(evaluate_eip(address, hours, cfg), resource_id)

    def snapshots():
        resources, truncated = collect_pages(client("ec2"), "describe_snapshots", "Snapshots", time_check=time_check, OwnerIds=["self"])
        counts["SNAPSHOT"] = len(resources)
        limited("SNAPSHOT", truncated)
        images, images_truncated = collect_pages(client("ec2"), "describe_images", "Images", time_check=time_check, Owners=["self"], IncludeDisabled=True)
        if images_truncated:
            limited("SNAPSHOT", True)
            errors[-1]["code"] = "INVENTORY_TRUNCATED"
            return
        used = {mapping.get("Ebs", {}).get("SnapshotId") for image in images for mapping in image.get("BlockDeviceMappings", [])}
        for snapshot in resources:
            time_check()
            resource_id = snapshot["SnapshotId"]
            add(evaluate_snapshot(snapshot, used, True, cfg, now), resource_id)

    def s3_multipart():
        s3 = client("s3")
        buckets, token = [], None
        while True:
            time_check()
            args = {"BucketRegion": region, "MaxBuckets": 1000}
            if token:
                args["ContinuationToken"] = token
            page = s3.list_buckets(**args)
            buckets.extend(bucket for bucket in page.get("Buckets", []) if not bucket.get("BucketRegion") or bucket.get("BucketRegion") == region)
            token = page.get("ContinuationToken")
            if not token:
                break
        count, truncated = 0, False
        counts["S3_MULTIPART"] = count
        for bucket in buckets:
            try:
                for page in _pages(s3, "list_multipart_uploads", time_check, Bucket=bucket["Name"], ExpectedBucketOwner=account_id):
                    for upload in page.get("Uploads", []):
                        if count == RESOURCE_LIMIT:
                            truncated = True
                            break
                        count += 1
                        counts["S3_MULTIPART"] = count
                        add(evaluate_s3_multipart(bucket["Name"], upload, now), [bucket["Name"], upload["Key"], upload["UploadId"]])
                    if truncated:
                        break
                if truncated:
                    break
            except ClientError as error:
                nonlocal partial
                partial = True
                errors.append({"type": "S3_MULTIPART", "code": _error_code(error), "resource_id": bucket["Name"]})
        limited("S3_MULTIPART", truncated)

    def rds_instances():
        resources, truncated = collect_pages(client("rds"), "describe_db_instances", "DBInstances", time_check=time_check)
        counts["RDS"] = len(resources)
        limited("RDS", truncated)
        for instance in resources:
            time_check()
            if instance.get("DBInstanceStatus") != "available" or keep(instance.get("TagList", [])):
                continue
            resource_id = instance["DBInstanceIdentifier"]
            metric_values = ([], [])
            if has_full_window(instance.get("InstanceCreateTime")):
                queries = _queries("AWS/RDS", "DBInstanceIdentifier", resource_id, [("CPUUtilization", "Maximum", "cpu"), ("DatabaseConnections", "Maximum", "connections")])
                series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
                metric_values = (series["cpu"], series["connections"])
            add(evaluate_rds(instance, metric_values, cfg, start), instance["DBInstanceArn"])

    def nat_gateways():
        resources, truncated = collect_pages(client("ec2"), "describe_nat_gateways", "NatGateways", time_check=time_check)
        counts["NAT_GATEWAY"] = len(resources)
        limited("NAT_GATEWAY", truncated)
        for gateway in resources:
            time_check()
            if gateway.get("State") != "available" or keep(gateway.get("Tags", [])):
                continue
            resource_id = gateway["NatGatewayId"]
            metric_values = ([], [])
            if has_full_window(gateway.get("CreateTime")):
                queries = _queries("AWS/NATGateway", "NatGatewayId", resource_id, [("BytesInFromSource", "Sum", "source"), ("BytesInFromDestination", "Sum", "destination")])
                series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
                metric_values = (series["source"], series["destination"])
            add(evaluate_nat_gateway(gateway, metric_values, cfg, start), resource_id)

    def load_balancers():
        partitions = {"ALB": [], "NLB": []}
        for page in _pages(client("elbv2"), "describe_load_balancers", time_check):
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
                if load_balancer.get("State", {}).get("Code") != "active":
                    continue
                metric_values = ([],)
                if has_full_window(load_balancer.get("CreatedTime")):
                    dimension = load_balancer["LoadBalancerArn"].split("loadbalancer/", 1)[-1]
                    if kind == "ALB":
                        queries = _queries("AWS/ApplicationELB", "LoadBalancer", dimension, [("RequestCount", "Sum", "requests")])
                        metric_id = "requests"
                    else:
                        queries = _queries("AWS/NetworkELB", "LoadBalancer", dimension, [("NewFlowCount", "Sum", "flows")])
                        metric_id = "flows"
                    series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
                    metric_values = (series[metric_id],)
                add(evaluate_load_balancer(load_balancer, metric_values, cfg, start), load_balancer["LoadBalancerArn"])

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
