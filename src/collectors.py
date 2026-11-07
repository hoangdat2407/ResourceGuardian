"""Read-only AWS inventory and metric collectors."""
from datetime import datetime, timezone, timedelta

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from rules import (
    evaluate_api_gateway,
    evaluate_auto_scaling_group,
    evaluate_backup_vault,
    evaluate_cloudfront_distribution,
    evaluate_documentdb_cluster,
    evaluate_dynamodb_table,
    evaluate_ebs,
    evaluate_ec2,
    evaluate_ecr_repository,
    evaluate_ecs_cluster,
    evaluate_ecs_service,
    evaluate_efs_file_system,
    evaluate_eip,
    evaluate_eks_cluster,
    evaluate_elasticache_cluster,
    evaluate_eventbridge_rule,
    evaluate_fsx_filesystem,
    evaluate_kinesis_stream,
    evaluate_lambda,
    evaluate_load_balancer,
    evaluate_log_group,
    evaluate_memorydb_cluster,
    evaluate_msk_cluster,
    evaluate_nat_gateway,
    evaluate_neptune_cluster,
    evaluate_opensearch_domain,
    evaluate_rds,
    evaluate_rds_snapshot,
    evaluate_redshift_cluster,
    evaluate_s3_multipart,
    evaluate_sagemaker_endpoint,
    evaluate_security_group,
    evaluate_snapshot,
    evaluate_sns_topic,
    evaluate_sqs_queue,
    evaluate_step_function,
    evaluate_vpc_endpoint,
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
    try:
        pages = iter(client.get_paginator(operation).paginate(**kwargs))
    except (KeyError, AttributeError):
        return
    while True:
        if time_check:
            time_check()
        try:
            page = next(pages)
        except (StopIteration, KeyError):
            return
        yield page


def collect_pages(client, operation, result_key, *, max_items=RESOURCE_LIMIT, transform=None, time_check=None, **kwargs):
    values = []
    try:
        for page in _pages(client, operation, time_check, **kwargs):
            items = page.get(result_key, [])
            if transform:
                items = transform(items)
            remaining = max_items + 1 - len(values)
            values.extend(items[:remaining])
            if len(values) > max_items:
                return values[:max_items], True
    except (KeyError, AttributeError):
        return [], False
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
            try:
                clients[name] = session.client(name, region_name=region, config=SDK_CONFIG)
            except KeyError:
                clients[name] = None
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


    def lambda_functions():
        c = client("lambda")
        if c is None:
            return
        resources, truncated = collect_pages(c, "list_functions", "Functions", time_check=time_check)
        counts["LAMBDA_FUNCTION"] = len(resources)
        limited("LAMBDA_FUNCTION", truncated)
        for fn in resources:
            time_check()
            tags = fn.get("Tags") or []
            if isinstance(tags, dict):
                tags = [{"Key": k, "Value": v} for k, v in tags.items()]
            if keep(tags):
                continue
            fn_name = fn["FunctionName"]
            esm_count = 0
            try:
                esm_resp = client("lambda").list_event_source_mappings(FunctionName=fn_name)
                esm_count = len(esm_resp.get("EventSourceMappings", []))
            except (ClientError, BotoCoreError):
                pass
            has_policy = False
            try:
                client("lambda").get_policy(FunctionName=fn_name)
                has_policy = True
            except (ClientError, BotoCoreError):
                pass
            queries = _queries("AWS/Lambda", "FunctionName", fn_name, [("Invocations", "Sum", "invocations")])
            series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
            metric_values = series.get("invocations", [])
            add(evaluate_lambda(fn, metric_values, cfg, start, esm_count, has_policy), fn["FunctionName"])

    def log_groups():
        c = client("logs")
        if c is None:
            return
        resources, truncated = collect_pages(c, "describe_log_groups", "logGroups", time_check=time_check)
        counts["LOG_GROUP"] = len(resources)
        limited("LOG_GROUP", truncated)
        for lg in resources:
            time_check()
            add(evaluate_log_group(lg, cfg), lg["logGroupName"])

    def security_groups():
        c = client("ec2")
        if c is None:
            return
        try:
            resources, truncated = collect_pages(c, "describe_security_groups", "SecurityGroups", time_check=time_check)
            if not resources:
                return
            enis, _ = collect_pages(c, "describe_network_interfaces", "NetworkInterfaces", time_check=time_check)
        except (KeyError, AttributeError):
            return
        counts["SECURITY_GROUP"] = len(resources)
        limited("SECURITY_GROUP", truncated)
        attached_sg_ids = {
            group["GroupId"]
            for eni in enis
            for group in eni.get("Groups", [])
            if "GroupId" in group
        }
        referenced_sg_ids = set()
        for sg in resources:
            time_check()
            is_unused = (sg["GroupId"] not in attached_sg_ids) and (sg["GroupId"] not in referenced_sg_ids) and (sg.get("GroupName") != "default")
            hours = observed("SECURITY_GROUP", sg["GroupId"], is_unused)
            add(evaluate_security_group(sg, attached_sg_ids, referenced_sg_ids, hours, cfg), sg["GroupId"])
    def rds_snapshots():
        c = client("rds")
        if c is None:
            return
        try:
            resources, truncated = collect_pages(c, "describe_db_snapshots", "DBSnapshots", SnapshotType="manual", time_check=time_check)
        except (KeyError, AttributeError):
            return
        if not resources:
            return
        counts["RDS_SNAPSHOT"] = len(resources)
        limited("RDS_SNAPSHOT", truncated)
        for snap in resources:
            time_check()
            add(evaluate_rds_snapshot(snap, cfg, now), snap["DBSnapshotIdentifier"])
    def dynamodb_tables():
        c = client("dynamodb")
        if c is None:
            return
        resources, truncated = collect_pages(c, "list_tables", "TableNames", time_check=time_check)
        counts["DYNAMODB_TABLE"] = len(resources)
        limited("DYNAMODB_TABLE", truncated)
        for table_name in resources:
            time_check()
            try:
                desc = c.describe_table(TableName=table_name).get("Table", {})
            except (ClientError, BotoCoreError):
                continue
            queries = [
                {"Id": "read", "MetricStat": {"Metric": {"Namespace": "AWS/DynamoDB", "MetricName": "ConsumedReadCapacityUnits", "Dimensions": [{"Name": "TableName", "Value": table_name}]}, "Period": 3600, "Stat": "Sum"}},
                {"Id": "write", "MetricStat": {"Metric": {"Namespace": "AWS/DynamoDB", "MetricName": "ConsumedWriteCapacityUnits", "Dimensions": [{"Name": "TableName", "Value": table_name}]}, "Period": 3600, "Stat": "Sum"}}
            ]
            series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
            add(evaluate_dynamodb_table(desc, series, cfg, start), table_name)

    def ecr_repositories():
        c = client("ecr")
        if c is None:
            return
        resources, truncated = collect_pages(c, "describe_repositories", "repositories", time_check=time_check)
        counts["ECR_REPOSITORY"] = len(resources)
        limited("ECR_REPOSITORY", truncated)
        for repo in resources:
            time_check()
            repo_name = repo["repositoryName"]
            has_lifecycle = False
            try:
                c.get_lifecycle_policy(repositoryName=repo_name)
                has_lifecycle = True
            except (ClientError, BotoCoreError):
                pass
            add(evaluate_ecr_repository(repo, has_lifecycle, 0, cfg), repo_name)

    def sqs_queues():
        c = client("sqs")
        if c is None:
            return
        try:
            urls = c.list_queues().get("QueueUrls", [])
        except (ClientError, BotoCoreError):
            return
        truncated = len(urls) > RESOURCE_LIMIT
        urls = urls[:RESOURCE_LIMIT]
        counts["SQS_QUEUE"] = len(urls)
        limited("SQS_QUEUE", truncated)
        for url in urls:
            time_check()
            qname = url.split("/")[-1]
            attrs = {}
            try:
                attrs = c.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"]).get("Attributes", {})
            except (ClientError, BotoCoreError):
                pass
            queries = [
                {"Id": "sent", "MetricStat": {"Metric": {"Namespace": "AWS/SQS", "MetricName": "NumberOfMessagesSent", "Dimensions": [{"Name": "QueueName", "Value": qname}]}, "Period": 3600, "Stat": "Sum"}},
                {"Id": "received", "MetricStat": {"Metric": {"Namespace": "AWS/SQS", "MetricName": "NumberOfMessagesReceived", "Dimensions": [{"Name": "QueueName", "Value": qname}]}, "Period": 3600, "Stat": "Sum"}}
            ]
            series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
            add(evaluate_sqs_queue(url, attrs, series, cfg, start), url)

    def elasticache_clusters():
        c = client("elasticache")
        if c is None:
            return
        resources, truncated = collect_pages(c, "describe_cache_clusters", "CacheClusters", time_check=time_check)
        counts["ELASTICACHE_CLUSTER"] = len(resources)
        limited("ELASTICACHE_CLUSTER", truncated)
        for cluster in resources:
            time_check()
            cid = cluster["CacheClusterId"]
            queries = _queries("AWS/ElastiCache", "CacheClusterId", cid, [("CurrConnections", "Maximum", "conns")])
            series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
            add(evaluate_elasticache_cluster(cluster, series.get("conns", []), cfg, start), cluster["CacheClusterId"])

    def efs_filesystems():
        c = client("efs")
        if c is None:
            return
        resources, truncated = collect_pages(c, "describe_file_systems", "FileSystems", time_check=time_check)
        counts["EFS_FILE_SYSTEM"] = len(resources)
        limited("EFS_FILE_SYSTEM", truncated)
        for fs in resources:
            time_check()
            add(evaluate_efs_file_system(fs, cfg), fs["FileSystemId"])

    def ecs_resources():
        c = client("ecs")
        if c is None:
            return
        try:
            arns = c.list_clusters().get("clusterArns", [])
        except (ClientError, BotoCoreError):
            return
        if not arns:
            return
        try:
            clusters = c.describe_clusters(clusters=arns[:100]).get("clusters", [])
        except (ClientError, BotoCoreError):
            return
        counts["ECS_CLUSTER"] = len(clusters)
        for cluster in clusters:
            time_check()
            add(evaluate_ecs_cluster(cluster, cfg), cluster["clusterArn"])
            try:
                srv_arns = c.list_services(cluster=cluster["clusterArn"]).get("serviceArns", [])
                if srv_arns:
                    services = c.describe_services(cluster=cluster["clusterArn"], services=srv_arns[:10]).get("services", [])
                    for srv in services:
                        add(evaluate_ecs_service(srv, cfg), srv["serviceArn"])
            except (ClientError, BotoCoreError):
                pass

    def auto_scaling_groups():
        c = client("autoscaling")
        if c is None:
            return
        resources, truncated = collect_pages(c, "describe_auto_scaling_groups", "AutoScalingGroups", time_check=time_check)
        counts["AUTO_SCALING_GROUP"] = len(resources)
        limited("AUTO_SCALING_GROUP", truncated)
        for asg in resources:
            time_check()
            add(evaluate_auto_scaling_group(asg, cfg), asg.get("AutoScalingGroupARN", asg["AutoScalingGroupName"]))

    def api_gateways():
        c = client("apigateway")
        c2 = client("apigatewayv2")
        apis = []
        if c is not None:
            try:
                apis.extend(c.get_rest_apis().get("items", []))
            except (ClientError, BotoCoreError):
                pass
        if c2 is not None:
            try:
                apis.extend(c2.get_apis().get("Items", []))
            except (ClientError, BotoCoreError):
                pass
        counts["API_GATEWAY"] = len(apis)
        for api_item in apis[:RESOURCE_LIMIT]:
            time_check()
            aid = api_item.get("id") or api_item.get("ApiId", "")
            queries = _queries("AWS/ApiGateway", "ApiId", aid, [("Count", "Sum", "requests")])
            series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
            add(evaluate_api_gateway(api_item, series.get("requests", []), cfg, start), aid)

    def sns_topics():
        c = client("sns")
        if c is None:
            return
        resources, truncated = collect_pages(c, "list_topics", "Topics", time_check=time_check)
        counts["SNS_TOPIC"] = len(resources)
        limited("SNS_TOPIC", truncated)
        for topic in resources:
            time_check()
            t_arn = topic["TopicArn"]
            t_name = t_arn.split(":")[-1]
            attrs = {}
            try:
                attrs = c.get_topic_attributes(TopicArn=t_arn).get("Attributes", {})
            except (ClientError, BotoCoreError):
                pass
            queries = _queries("AWS/SNS", "TopicName", t_name, [("NumberOfMessagesPublished", "Sum", "published")])
            series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
            add(evaluate_sns_topic(t_arn, attrs, series.get("published", []), cfg, start), t_arn)

    def eventbridge_rules():
        c = client("events")
        if c is None:
            return
        resources, truncated = collect_pages(c, "list_rules", "Rules", time_check=time_check)
        counts["EVENTBRIDGE_RULE"] = len(resources)
        limited("EVENTBRIDGE_RULE", truncated)
        for rule_item in resources:
            time_check()
            targets = []
            try:
                targets = c.list_targets_by_rule(Rule=rule_item["Name"]).get("Targets", [])
            except (ClientError, BotoCoreError):
                pass
            add(evaluate_eventbridge_rule(rule_item, targets, cfg), rule_item.get("Arn", rule_item["Name"]))

    def step_functions():
        c = client("stepfunctions")
        if c is None:
            return
        resources, truncated = collect_pages(c, "list_state_machines", "stateMachines", time_check=time_check)
        counts["STEP_FUNCTION"] = len(resources)
        limited("STEP_FUNCTION", truncated)
        for sm in resources:
            time_check()
            sm_arn = sm["stateMachineArn"]
            queries = _queries("AWS/States", "StateMachineArn", sm_arn, [("ExecutionsStarted", "Sum", "execs")])
            series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
            add(evaluate_step_function(sm, series.get("execs", []), cfg, start), sm_arn)

    def vpc_endpoints():
        c = client("ec2")
        if c is None:
            return
        resources, truncated = collect_pages(c, "describe_vpc_endpoints", "VpcEndpoints", time_check=time_check)
        counts["VPC_ENDPOINT"] = len(resources)
        limited("VPC_ENDPOINT", truncated)
        for vpce in resources:
            time_check()
            add(evaluate_vpc_endpoint(vpce, [], cfg, start), vpce["VpcEndpointId"])


    def sagemaker_endpoints():
        c = client("sagemaker")
        if c is None:
            return
        try:
            resources, truncated = collect_pages(c, "list_endpoints", "Endpoints", StatusEquals="InService", time_check=time_check)
        except (KeyError, AttributeError):
            return
        counts["SAGEMAKER_ENDPOINT"] = len(resources)
        limited("SAGEMAKER_ENDPOINT", truncated)
        for ep in resources:
            time_check()
            name = ep["EndpointName"]
            queries = _queries("AWS/SageMaker", "EndpointName", name, [("Invocations", "Sum", "invocations")])
            series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
            add(evaluate_sagemaker_endpoint(ep, series.get("invocations", []), cfg, start), ep.get("EndpointArn", name))

    def opensearch_domains():
        c = client("opensearch")
        if c is None:
            return
        try:
            names = [item["DomainName"] for item in c.list_domain_names().get("DomainNames", [])]
        except (KeyError, AttributeError):
            return
        if not names:
            return
        counts["OPENSEARCH_DOMAIN"] = len(names)
        try:
            domains = c.describe_domains(DomainNames=names[:100]).get("DomainStatusList", [])
        except (KeyError, AttributeError):
            return
        for d in domains:
            time_check()
            name = d["DomainName"]
            queries = _queries("AWS/ES", "DomainName", name, [("SearchRate", "Sum", "search"), ("IndexingRate", "Sum", "index")])
            series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
            requests = series.get("search", []) + series.get("index", [])
            add(evaluate_opensearch_domain(d, requests, cfg, start), d.get("ARN", name))

    def redshift_clusters():
        c = client("redshift")
        if c is None:
            return
        try:
            resources, truncated = collect_pages(c, "describe_clusters", "Clusters", time_check=time_check)
        except (KeyError, AttributeError):
            return
        counts["REDSHIFT_CLUSTER"] = len(resources)
        limited("REDSHIFT_CLUSTER", truncated)
        for rc in resources:
            time_check()
            cid = rc["ClusterIdentifier"]
            queries = _queries("AWS/Redshift", "ClusterIdentifier", cid, [("DatabaseConnections", "Sum", "conns")])
            series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
            add(evaluate_redshift_cluster(rc, series.get("conns", []), cfg, start), cid)

    def msk_clusters():
        c = client("kafka")
        if c is None:
            return
        try:
            resources, truncated = collect_pages(c, "list_clusters", "ClusterInfoList", time_check=time_check)
        except (KeyError, AttributeError):
            return
        counts["MSK_CLUSTER"] = len(resources)
        limited("MSK_CLUSTER", truncated)
        for cluster in resources:
            time_check()
            name = cluster["ClusterName"]
            queries = _queries("AWS/Kafka", "Cluster Name", name, [("BytesInPerSec", "Sum", "bytes_in"), ("BytesOutPerSec", "Sum", "bytes_out")])
            series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
            traffic = series.get("bytes_in", []) + series.get("bytes_out", [])
            add(evaluate_msk_cluster(cluster, traffic, cfg, start), cluster.get("ClusterArn", name))

    def kinesis_streams():
        c = client("kinesis")
        if c is None:
            return
        try:
            names = c.list_streams().get("StreamNames", [])
        except (KeyError, AttributeError):
            return
        counts["KINESIS_STREAM"] = len(names)
        for name in names[:RESOURCE_LIMIT]:
            time_check()
            queries = _queries("AWS/Kinesis", "StreamName", name, [("IncomingRecords", "Sum", "records")])
            series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
            stream_info = {"StreamName": name, "StreamStatus": "ACTIVE"}
            add(evaluate_kinesis_stream(stream_info, series.get("records", []), cfg, start), name)

    def cloudfront_distributions():
        c = client("cloudfront")
        if c is None:
            return
        try:
            items = c.list_distributions().get("DistributionList", {}).get("Items", [])
        except (KeyError, AttributeError):
            return
        counts["CLOUDFRONT_DISTRIBUTION"] = len(items)
        try:
            cw_global = session.client("cloudwatch", region_name="us-east-1", config=SDK_CONFIG)
        except Exception:
            cw_global = client("cloudwatch")
        for dist in items[:RESOURCE_LIMIT]:
            time_check()
            did = dist["Id"]
            queries = [{
                "Id": "requests",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/CloudFront",
                        "MetricName": "Requests",
                        "Dimensions": [
                            {"Name": "DistributionId", "Value": did},
                            {"Name": "Region", "Value": "Global"},
                        ],
                    },
                    "Period": 3600,
                    "Stat": "Sum",
                },
            }]
            series = metric_series(cw_global, queries, start, end, time_check=time_check)
            add(evaluate_cloudfront_distribution(dist, series.get("requests", []), cfg, start), did)
    def backup_vaults():
        c = client("backup")
        if c is None:
            return
        try:
            resources, truncated = collect_pages(c, "list_backup_vaults", "BackupVaultList", time_check=time_check)
        except (KeyError, AttributeError):
            return
        counts["BACKUP_VAULT"] = len(resources)
        limited("BACKUP_VAULT", truncated)
        for vault in resources:
            time_check()
            vname = vault["BackupVaultName"]
            expired_count = 0
            total_count = 0
            try:
                points = c.list_recovery_points_by_backup_vault(BackupVaultName=vname, MaxResults=100).get("RecoveryPoints", [])
                total_count = len(points)
                expired_count = sum(1 for p in points if p.get("Status") == "EXPIRED")
            except (KeyError, AttributeError, ClientError, BotoCoreError):
                pass
            add(evaluate_backup_vault(vault, expired_count, total_count, cfg), vault.get("BackupVaultArn", vname))

    def eks_clusters():
        c = client("eks")
        if c is None:
            return
        try:
            names = c.list_clusters().get("clusters", [])
        except (KeyError, AttributeError):
            return
        counts["EKS_CLUSTER"] = len(names)
        for name in names[:RESOURCE_LIMIT]:
            time_check()
            nodegroups = 0
            fargate = 0
            try:
                cluster = c.describe_cluster(name=name).get("cluster", {})
                nodegroups = len(c.list_nodegroups(clusterName=name).get("nodegroups", []))
                fargate = len(c.list_fargate_profiles(clusterName=name).get("fargateProfileNames", []))
            except (KeyError, AttributeError, ClientError, BotoCoreError):
                continue
            add(evaluate_eks_cluster(cluster, nodegroups, fargate, cfg), cluster.get("arn", name))

    def fsx_filesystems():
        c = client("fsx")
        if c is None:
            return
        try:
            resources, truncated = collect_pages(c, "describe_file_systems", "FileSystems", time_check=time_check)
        except (KeyError, AttributeError):
            return
        counts["FSX_FILE_SYSTEM"] = len(resources)
        limited("FSX_FILE_SYSTEM", truncated)
        for fs in resources:
            time_check()
            fid = fs["FileSystemId"]
            queries = _queries("AWS/FSx", "FileSystemId", fid, [("DataReadBytes", "Sum", "read"), ("DataWriteBytes", "Sum", "write")])
            series = metric_series(client("cloudwatch"), queries, start, end, time_check=time_check)
            traffic = series.get("read", []) + series.get("write", [])
            add(evaluate_fsx_filesystem(fs, traffic, cfg, start), fid)

    def memorydb_clusters():
        c = client("memorydb")
        if c is None:
            return
        try:
            resources, truncated = collect_pages(c, "describe_clusters", "Clusters", time_check=time_check)
        except (KeyError, AttributeError):
            return
        counts["MEMORYDB_CLUSTER"] = len(resources)
        limited("MEMORYDB_CLUSTER", truncated)
        for cluster in resources:
            time_check()
            add(evaluate_memorydb_cluster(cluster, [], cfg, start), cluster.get("ARN", cluster["Name"]))

    def docdb_neptune_clusters():
        c = client("rds")
        if c is None:
            return
        try:
            resources, truncated = collect_pages(c, "describe_db_clusters", "DBClusters", time_check=time_check)
        except (KeyError, AttributeError):
            return
        for cluster in resources:
            time_check()
            engine = cluster.get("Engine", "")
            if engine == "docdb":
                counts["DOCUMENTDB_CLUSTER"] = counts.get("DOCUMENTDB_CLUSTER", 0) + 1
                add(evaluate_documentdb_cluster(cluster, [], cfg, start), cluster["DBClusterIdentifier"])
            elif engine == "neptune":
                counts["NEPTUNE_CLUSTER"] = counts.get("NEPTUNE_CLUSTER", 0) + 1
                add(evaluate_neptune_cluster(cluster, [], cfg, start), cluster["DBClusterIdentifier"])


    operations = []
    if "compute" in service_groups:
        operations.append(("EC2", ec2_instances))
    if "containers" in service_groups:
        operations.extend((("AUTO_SCALING_GROUP", auto_scaling_groups), ("ECS", ecs_resources), ("EKS", eks_clusters)))
    if "serverless" in service_groups:
        operations.append(("LAMBDA_FUNCTION", lambda_functions))
    if "storage" in service_groups:
        operations.extend((("EBS", ebs_volumes), ("SNAPSHOT", snapshots), ("S3_MULTIPART", s3_multipart)))
    if "backup" in service_groups:
        operations.extend((("RDS_SNAPSHOT", rds_snapshots), ("EFS", efs_filesystems), ("ECR", ecr_repositories), ("FSX", fsx_filesystems), ("BACKUP", backup_vaults)))
    if "database" in service_groups:
        operations.append(("RDS", rds_instances))
    if "nosql" in service_groups or "cache" in service_groups:
        operations.extend((("DYNAMODB_TABLE", dynamodb_tables), ("ELASTICACHE", elasticache_clusters), ("MEMORYDB", memorydb_clusters), ("DOCDB_NEPTUNE", docdb_neptune_clusters)))
    if "network" in service_groups:
        operations.extend((("EIP", eip_addresses), ("NAT_GATEWAY", nat_gateways), ("ELB", load_balancers)))
    if "security" in service_groups:
        operations.extend((("SECURITY_GROUP", security_groups), ("VPC_ENDPOINT", vpc_endpoints), ("CLOUDFRONT", cloudfront_distributions)))
    if "monitoring" in service_groups:
        operations.append(("LOG_GROUP", log_groups))
    if "integration" in service_groups:
        operations.extend((
            ("SQS_QUEUE", sqs_queues),
            ("SNS_TOPIC", sns_topics),
            ("EVENTBRIDGE_RULE", eventbridge_rules),
            ("STEP_FUNCTION", step_functions),
            ("API_GATEWAY", api_gateways),
        ))
    if "analytics" in service_groups:
        operations.extend((
            ("SAGEMAKER", sagemaker_endpoints),
            ("OPENSEARCH", opensearch_domains),
            ("REDSHIFT", redshift_clusters),
            ("MSK", msk_clusters),
            ("KINESIS", kinesis_streams),
        ))
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
