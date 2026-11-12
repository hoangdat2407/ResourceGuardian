"""Pure detection rules. Findings are review candidates, never deletion decisions."""
import hashlib
import json
import math
from datetime import datetime

THRESHOLD_METADATA = {
    # Nhóm 1: Tính toán & Container (compute)
    "cpu_percent": {"group": "compute", "resource": "EC2", "rule": "EC2_LOW_UTILIZATION", "label": "Ngưỡng CPU EC2 (%)", "min": 1, "max": 50, "integer": False, "default": 5, "unit": "%"},
    "network_mib_hour": {"group": "compute", "resource": "EC2", "rule": "EC2_LOW_UTILIZATION", "label": "Ngưỡng network EC2 (MiB/giờ)", "min": 0.1, "max": 100, "integer": False, "default": 1, "unit": "MiB/giờ"},
    "window_hours": {"group": "compute", "resource": "ALL", "rule": "METRIC_WINDOW", "label": "Cửa sổ metrics (giờ)", "min": 24, "max": 168, "integer": True, "default": 24, "unit": "giờ"},
    "interval_hours": {"group": "compute", "resource": "ALL", "rule": "SCAN_INTERVAL", "label": "Khoảng cách giữa các lần quét (giờ)", "min": 1, "max": 24, "integer": True, "default": 6, "unit": "giờ"},
    "lambda_unused_days": {"group": "compute", "resource": "LAMBDA_FUNCTION", "rule": "LAMBDA_UNUSED", "label": "Thời gian Lambda không hoạt động (ngày)", "min": 7, "max": 90, "integer": True, "default": 30, "unit": "ngày"},
    "lambda_max_invocations": {"group": "compute", "resource": "LAMBDA_FUNCTION", "rule": "LAMBDA_UNUSED", "label": "Lượt gọi Lambda tối đa", "min": 0, "max": 10000, "integer": True, "default": 0, "unit": "lượt"},
    "asg_zero_days": {"group": "compute", "resource": "AUTO_SCALING_GROUP", "rule": "ASG_ZERO_CAPACITY_OLD", "label": "Thời gian ASG dung lượng 0 (ngày)", "min": 1, "max": 90, "integer": True, "default": 7, "unit": "ngày"},
    "ecs_empty_days": {"group": "compute", "resource": "ECS_CLUSTER", "rule": "ECS_CLUSTER_EMPTY", "label": "Thời gian ECS Cluster rỗng (ngày)", "min": 1, "max": 90, "integer": True, "default": 7, "unit": "ngày"},
    "eks_idle_days": {"group": "compute", "resource": "EKS_CLUSTER", "rule": "EKS_IDLE_CANDIDATE", "label": "Thời gian EKS không có Node (ngày)", "min": 1, "max": 90, "integer": True, "default": 14, "unit": "ngày"},
    # Nhóm 2: Lưu trữ & Sao lưu (storage)
    "orphan_hours": {"group": "storage", "resource": "EBS", "rule": "EBS_UNATTACHED", "label": "Thời gian theo dõi EBS / EIP (giờ)", "min": 1, "max": 168, "integer": True, "default": 24, "unit": "giờ"},
    "snapshot_days": {"group": "storage", "resource": "SNAPSHOT", "rule": "SNAPSHOT_OLD_UNREFERENCED", "label": "Tuổi EBS Snapshot (ngày)", "min": 7, "max": 365, "integer": True, "default": 30, "unit": "ngày"},
    "rds_snapshot_days": {"group": "storage", "resource": "RDS_SNAPSHOT", "rule": "RDS_SNAPSHOT_OLD", "label": "Tuổi RDS Snapshot thủ công (ngày)", "min": 7, "max": 365, "integer": True, "default": 90, "unit": "ngày"},
    "efs_no_mount_days": {"group": "storage", "resource": "EFS_FILE_SYSTEM", "rule": "EFS_NO_MOUNT_TARGET", "label": "Thời gian EFS không có Mount Target (ngày)", "min": 1, "max": 90, "integer": True, "default": 7, "unit": "ngày"},
    "ecr_image_days": {"group": "storage", "resource": "ECR_REPOSITORY", "rule": "ECR_NO_LIFECYCLE", "label": "Tuổi Image ECR khuyến nghị (ngày)", "min": 7, "max": 365, "integer": True, "default": 90, "unit": "ngày"},
    "fsx_idle_days": {"group": "storage", "resource": "FSX_FILE_SYSTEM", "rule": "FSX_LOW_ACTIVITY", "label": "Thời gian FSx không có I/O (ngày)", "min": 1, "max": 90, "integer": True, "default": 14, "unit": "ngày"},
    "backup_point_days": {"group": "storage", "resource": "BACKUP_VAULT", "rule": "BACKUP_OLD_RECOVERY_POINT", "label": "Tuổi Recovery Point AWS Backup (ngày)", "min": 30, "max": 365, "integer": True, "default": 180, "unit": "ngày"},
    # Nhóm 3: Cơ sở dữ liệu & Cache (database)
    "rds_cpu_percent": {"group": "database", "resource": "RDS", "rule": "RDS_LOW_UTILIZATION", "label": "Ngưỡng CPU RDS (%)", "min": 1, "max": 50, "integer": False, "default": 5, "unit": "%"},
    "rds_connections": {"group": "database", "resource": "RDS", "rule": "RDS_LOW_UTILIZATION", "label": "Ngưỡng kết nối RDS", "min": 1, "max": 1000, "integer": True, "default": 1, "unit": "kết nối"},
    "dynamodb_idle_days": {"group": "database", "resource": "DYNAMODB_TABLE", "rule": "DYNAMODB_IDLE", "label": "Thời gian DynamoDB rảnh (ngày)", "min": 1, "max": 90, "integer": True, "default": 14, "unit": "ngày"},
    "elasticache_idle_days": {"group": "database", "resource": "ELASTICACHE_CLUSTER", "rule": "ELASTICACHE_IDLE", "label": "Thời gian ElastiCache rảnh (ngày)", "min": 1, "max": 90, "integer": True, "default": 7, "unit": "ngày"},
    "memorydb_idle_days": {"group": "database", "resource": "MEMORYDB_CLUSTER", "rule": "MEMORYDB_IDLE", "label": "Thời gian MemoryDB rảnh (ngày)", "min": 1, "max": 90, "integer": True, "default": 7, "unit": "ngày"},
    "documentdb_idle_days": {"group": "database", "resource": "DOCUMENTDB_CLUSTER", "rule": "DOCUMENTDB_IDLE", "label": "Thời gian DocumentDB rảnh (ngày)", "min": 1, "max": 90, "integer": True, "default": 7, "unit": "ngày"},
    "neptune_idle_days": {"group": "database", "resource": "NEPTUNE_CLUSTER", "rule": "NEPTUNE_IDLE", "label": "Thời gian Neptune rảnh (ngày)", "min": 1, "max": 90, "integer": True, "default": 14, "unit": "ngày"},
    # Nhóm 4: Mạng & Phân phối nội dung (network)
    "nat_mib_hour": {"group": "network", "resource": "NAT_GATEWAY", "rule": "NAT_LOW_UTILIZATION", "label": "Ngưỡng lưu lượng NAT (MiB/giờ)", "min": 0.1, "max": 10000, "integer": False, "default": 1, "unit": "MiB/giờ"},
    "alb_requests_hour": {"group": "network", "resource": "ALB", "rule": "ALB_LOW_UTILIZATION", "label": "Ngưỡng request ALB (request/giờ)", "min": 1, "max": 1000000, "integer": True, "default": 1, "unit": "request/giờ"},
    "nlb_new_flows_hour": {"group": "network", "resource": "NLB", "rule": "NLB_LOW_UTILIZATION", "label": "Ngưỡng flow mới NLB (flow/giờ)", "min": 1, "max": 1000000, "integer": True, "default": 1, "unit": "flow/giờ"},
    "sg_unused_days": {"group": "network", "resource": "SECURITY_GROUP", "rule": "SECURITY_GROUP_UNUSED", "label": "Thời gian Security Group không gắn (ngày)", "min": 1, "max": 90, "integer": True, "default": 7, "unit": "ngày"},
    "vpc_endpoint_unused_days": {"group": "network", "resource": "VPC_ENDPOINT", "rule": "VPC_ENDPOINT_UNUSED", "label": "Thời gian VPC Endpoint không dùng (ngày)", "min": 1, "max": 90, "integer": True, "default": 14, "unit": "ngày"},
    "cloudfront_requests_day": {"group": "network", "resource": "CLOUDFRONT_DISTRIBUTION", "rule": "CLOUDFRONT_LOW_TRAFFIC", "label": "Ngưỡng request CloudFront (req/ngày)", "min": 1, "max": 1000000, "integer": True, "default": 100, "unit": "req/ngày"},

    # Nhóm 5: Phân tích dữ liệu & AI (analytics)
    "sagemaker_idle_days": {"group": "analytics", "resource": "SAGEMAKER_ENDPOINT", "rule": "SAGEMAKER_ENDPOINT_IDLE", "label": "Thời gian SageMaker không gọi (ngày)", "min": 1, "max": 90, "integer": True, "default": 7, "unit": "ngày"},
    "opensearch_idle_days": {"group": "analytics", "resource": "OPENSEARCH_DOMAIN", "rule": "OPENSEARCH_IDLE", "label": "Thời gian OpenSearch không có query (ngày)", "min": 1, "max": 90, "integer": True, "default": 7, "unit": "ngày"},
    "redshift_idle_days": {"group": "analytics", "resource": "REDSHIFT_CLUSTER", "rule": "REDSHIFT_IDLE", "label": "Thời gian Redshift không có kết nối (ngày)", "min": 1, "max": 90, "integer": True, "default": 7, "unit": "ngày"},
    "msk_idle_days": {"group": "analytics", "resource": "MSK_CLUSTER", "rule": "MSK_IDLE", "label": "Thời gian MSK không có lưu lượng (ngày)", "min": 1, "max": 90, "integer": True, "default": 7, "unit": "ngày"},
    "kinesis_idle_days": {"group": "analytics", "resource": "KINESIS_STREAM", "rule": "KINESIS_IDLE", "label": "Thời gian Kinesis không có record (ngày)", "min": 1, "max": 90, "integer": True, "default": 7, "unit": "ngày"},
    # Nhóm 6: Giám sát & Tích hợp (integration)
    "log_group_retention_days": {"group": "integration", "resource": "LOG_GROUP", "rule": "LOG_GROUP_NO_RETENTION", "label": "Thời gian lưu Log Group đề xuất (ngày)", "min": 7, "max": 365, "integer": True, "default": 30, "unit": "ngày"},
    "sqs_idle_days": {"group": "integration", "resource": "SQS_QUEUE", "rule": "SQS_QUEUE_IDLE", "label": "Thời gian SQS không có traffic (ngày)", "min": 1, "max": 90, "integer": True, "default": 14, "unit": "ngày"},
    "sns_unused_days": {"group": "integration", "resource": "SNS_TOPIC", "rule": "SNS_TOPIC_UNUSED", "label": "Thời gian SNS không hoạt động (ngày)", "min": 1, "max": 90, "integer": True, "default": 30, "unit": "ngày"},
    "eventbridge_unused_days": {"group": "integration", "resource": "EVENTBRIDGE_RULE", "rule": "EVENTBRIDGE_RULE_UNUSED", "label": "Thời gian EventBridge rule không dùng (ngày)", "min": 1, "max": 90, "integer": True, "default": 30, "unit": "ngày"},
    "stepfunctions_unused_days": {"group": "integration", "resource": "STEP_FUNCTION", "rule": "STEP_FUNCTION_UNUSED", "label": "Thời gian Step Functions không chạy (ngày)", "min": 1, "max": 90, "integer": True, "default": 30, "unit": "ngày"},
    "apigateway_unused_days": {"group": "integration", "resource": "API_GATEWAY", "rule": "API_GATEWAY_UNUSED", "label": "Thời gian API Gateway không có request (ngày)", "min": 1, "max": 90, "integer": True, "default": 14, "unit": "ngày"},
}

MVP_DEFAULTS = {
    "cpu_percent": 5,
    "network_mib_hour": 1,
    "window_hours": 24,
    "orphan_hours": 24,
    "snapshot_days": 30,
    "interval_hours": 6,
    "rds_cpu_percent": 5,
    "rds_connections": 1,
    "nat_mib_hour": 1,
    "alb_requests_hour": 1,
    "nlb_new_flows_hour": 1,
}
DEFAULTS = {k: v["default"] for k, v in THRESHOLD_METADATA.items()}
LIMITS = {k: (v["min"], v["max"], v["integer"]) for k, v in THRESHOLD_METADATA.items()}

def _merge_config(result, value):
    if not isinstance(value, dict) or set(value) - set(LIMITS):
        raise ValueError("Unknown configuration field")
    for key, val in value.items():
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError("Configuration must contain finite numbers")
        lo, hi, integer = LIMITS[key]
        if not lo <= val <= hi or (integer and val != int(val)):
            raise ValueError("Configuration outside supported bounds: " + key)
        result[key] = int(val) if integer else val


def config(value, base=None, include_extended=False):
    """Normalize a partial settings update over defaults and an optional base."""
    if not isinstance(value, dict) or (base is not None and not isinstance(base, dict)):
        raise ValueError("Expected a dict")
    has_extended = include_extended or bool((set(value) - set(MVP_DEFAULTS)) or (base and set(base) - set(MVP_DEFAULTS)))
    result = dict(DEFAULTS if has_extended else MVP_DEFAULTS)
    if base is not None:
        _merge_config(result, base)
    _merge_config(result, value)
    return result
def finding_id(resource_type, region, stable_identity):
    payload = json.dumps(
        [resource_type, region, stable_identity],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def keep(tags):
    return any(t.get("Key") == "guardian:keep" and t.get("Value", "").lower() == "true" for t in tags)


def _metric_data(series, hours, thresholds, units):
    """Validate every sample and retain diagnostics without copying raw invalid data."""
    required = math.ceil(hours * 0.8)
    values, invalid = {}, []
    received, invalid_counts = {}, {}
    for name, samples in series.items():
        values[name] = []
        received[name] = len(samples) if isinstance(samples, (list, tuple)) else 0
        invalid_counts[name] = 0
        if not isinstance(samples, (list, tuple)):
            invalid.append(name)
            invalid_counts[name] = 1
            continue
        for sample in samples:
            try:
                valid = not isinstance(sample, bool) and isinstance(sample, (int, float)) and math.isfinite(sample) and sample >= 0
            except OverflowError:
                valid = False
            if not valid:
                if name not in invalid: invalid.append(name)
                invalid_counts[name] += 1
            else:
                values[name].append(sample)
    counts = {name: len(samples) for name, samples in values.items()}
    missing = [name for name, count in counts.items() if count < required]
    evidence = {"window_hours": hours,
                "thresholds": dict(thresholds), "metric_units": dict(units),
                "sample_counts": counts, "required_samples": required,
                "received_sample_counts": received, "invalid_sample_counts": invalid_counts,
                "missing_metrics": missing, "invalid_metrics": invalid,
                "coverage": round(min(counts.values()) / hours, 3),
                "calculation_errors": [], "data_issues": []}
    return values, evidence


def _unusable(evidence):
    return bool(evidence["missing_metrics"] or evidence["invalid_metrics"])


def _overflow(evidence, metrics):
    evidence["invalid_metrics"] = list(metrics)
    evidence["calculation_errors"] = ["AGGREGATE_OVERFLOW"]
    return "INSUFFICIENT_DATA", evidence


def idle(cpu, net_in, net_out, hours, cfg):
    """Require >=80% of hourly samples for all three metrics, including real zeros."""
    values, evidence = _metric_data(
        {"cpu": cpu, "netin": net_in, "netout": net_out}, hours,
        {"cpu_percent": cfg["cpu_percent"], "network_mib_hour": cfg["network_mib_hour"]},
        {"cpu": "Percent", "netin": "Bytes", "netout": "Bytes"},
    )
    if _unusable(evidence):
        return "INSUFFICIENT_DATA", evidence
    ordered = sorted(values["cpu"])
    p95 = ordered[max(0, math.ceil(.95 * len(ordered)) - 1)]
    try:
        # Each hourly Sum is averaged only over hours actually measured in that
        # direction; missing hours must not dilute traffic as if they were zero.
        incoming_hour = math.fsum(values["netin"]) / len(values["netin"])
        outgoing_hour = math.fsum(values["netout"]) / len(values["netout"])
        mib_hour = (incoming_hour + outgoing_hour) / 1048576
    except OverflowError:
        return _overflow(evidence, ("netin", "netout"))
    if not math.isfinite(mib_hour):
        return _overflow(evidence, ("netin", "netout"))
    evidence.update({"cpu_p95": round(p95, 3), "network_mib_hour": round(mib_hour, 3)})
    return ("REVIEW" if p95 < cfg["cpu_percent"] and mib_hour < cfg["network_mib_hour"] else "OK"), evidence


RULE_METADATA = {
    "EC2": ("EC2_LOW_UTILIZATION", "Xác minh mục đích và tải dự kiến của instance; bổ sung metrics nếu thiếu trước khi cân nhắc giảm cấu hình hoặc dừng."),
    "EBS": ("EBS_UNATTACHED", "Xác minh chủ sở hữu, nhu cầu gắn lại và chính sách lưu giữ dữ liệu trước khi cân nhắc xóa volume."),
    "EIP": ("EIP_UNASSOCIATED", "Xác minh địa chỉ có được dự trữ cho dịch vụ hoặc DNS trước khi cân nhắc giải phóng Elastic IP."),
    "SNAPSHOT": ("SNAPSHOT_OLD_UNREFERENCED", "Đối chiếu kế hoạch sao lưu, phục hồi và lưu giữ; xác nhận với chủ sở hữu trước khi cân nhắc xóa snapshot."),
    "RDS": ("RDS_LOW_UTILIZATION", "Xác minh mục đích và tải dự kiến của cơ sở dữ liệu trước khi cân nhắc giảm cấu hình hoặc dừng."),
    "NAT_GATEWAY": ("NAT_LOW_UTILIZATION", "Xác minh lưu lượng mạng qua NAT Gateway trước khi cân nhắc xóa để tối ưu chi phí."),
    "ALB": ("ALB_LOW_UTILIZATION", "Xác minh lưu lượng request của Application Load Balancer trước khi cân nhắc xóa."),
    "NLB": ("NLB_LOW_UTILIZATION", "Xác minh số flow mới của Network Load Balancer trước khi cân nhắc xóa."),
     "S3_MULTIPART": ("S3_STALE_MULTIPART", "Xác nhận các multipart upload dang dở không còn cần thiết trước khi hủy để tránh tốn dung lượng."),
    "LAMBDA_FUNCTION": ("LAMBDA_UNUSED", "Xác minh mục đích sử dụng, lịch trigger định kỳ hoặc event source mapping trước khi lưu trữ hoặc xóa Lambda function."),
    "LAMBDA": ("LAMBDA_UNUSED", "Xác minh mục đích sử dụng, lịch trigger định kỳ hoặc event source mapping trước khi lưu trữ hoặc xóa Lambda function."),
    "LOG_GROUP": ("LOG_GROUP_NO_RETENTION", "Cấu hình thời gian lưu giữ (Retention Policy) phù hợp như 14, 30 hoặc 90 ngày để tránh chi phí lưu trữ log vô hạn."),
    "SECURITY_GROUP": ("SECURITY_GROUP_UNUSED", "Xác minh các kết nối và quy tắc firewall trước khi cân nhắc xóa Security Group không sử dụng."),
    "RDS_SNAPSHOT": ("RDS_SNAPSHOT_OLD", "Đối chiếu chính sách lưu trữ backup; xác nhận với chủ sở hữu trước khi cân nhắc xóa RDS Snapshot."),
    "DYNAMODB_TABLE": ("DYNAMODB_IDLE", "Xác minh ứng dụng kết nối hoặc chuyển billing mode sang On-Demand để tối ưu chi phí bảng DynamoDB."),
    "ECR_REPOSITORY": ("ECR_NO_LIFECYCLE", "Thiết lập Lifecycle Policy cho repository ECR để tự động dọn dẹp các image cũ không còn sử dụng."),
    "SQS_QUEUE": ("SQS_QUEUE_IDLE", "Kiểm tra hệ thống sản xuất/tiêu thụ message hoặc chuyển đổi hàng đợi SQS nếu không còn nhu cầu."),
    "ELASTICACHE_CLUSTER": ("ELASTICACHE_IDLE", "Xác minh ứng dụng kết nối hoặc hạ cấu hình/dừng cụm ElastiCache không có kết nối."),
    "EFS_FILE_SYSTEM": ("EFS_NO_MOUNT_TARGET", "Tạo Mount Target hoặc sao lưu dữ liệu trước khi xóa hệ thống tệp EFS không được gắn kết."),
    "ECS_CLUSTER": ("ECS_CLUSTER_EMPTY", "Xóa cluster ECS rỗng không có container instance hoặc task nào đang chạy."),
    "ECS_SERVICE": ("ECS_SERVICE_IDLE", "Xác minh cấu hình dịch vụ ECS có desired count bằng 0 trong thời gian dài."),
    "AUTO_SCALING_GROUP": ("ASG_ZERO_CAPACITY_OLD", "Xác minh nhu cầu sử dụng trước khi xóa Auto Scaling Group có desired và min capacity bằng 0."),
    "API_GATEWAY": ("API_GATEWAY_UNUSED", "Xác minh traffic API Gateway trước khi lưu trữ hoặc xóa API không có request."),
    "SNS_TOPIC": ("SNS_TOPIC_UNUSED", "Xác minh các subscriber và hệ thống gửi tin trước khi xóa SNS Topic không hoạt động."),
    "EVENTBRIDGE_RULE": ("EVENTBRIDGE_RULE_UNUSED", "Kích hoạt hoặc xóa EventBridge Rule đang bị vô hiệu hóa hoặc không có target."),
    "STEP_FUNCTION": ("STEP_FUNCTION_UNUSED", "Xác minh quy trình nghiệp vụ trước khi xóa State Machine không có lượt thực thi nào."),
    "VPC_ENDPOINT": ("VPC_ENDPOINT_UNUSED", "Xác minh lưu lượng mạng qua VPC Endpoint trước khi cân nhắc xóa để tiết kiệm chi phí cố định theo giờ."),
    "SAGEMAKER_ENDPOINT": ("SAGEMAKER_ENDPOINT_IDLE", "Hạ cấu hình hoặc xóa SageMaker Endpoint không nhận request để tránh chi phí instance ML chạy ngầm."),
    "OPENSEARCH_DOMAIN": ("OPENSEARCH_IDLE", "Xác minh các ứng dụng tìm kiếm hoặc lưu trữ log trước khi cân nhắc xóa hoặc tắt OpenSearch domain."),
    "REDSHIFT_CLUSTER": ("REDSHIFT_IDLE", "Tạm dừng (Pause) hoặc tạo snapshot rồi xóa Redshift cluster không có kết nối client."),
    "MSK_CLUSTER": ("MSK_IDLE", "Xác minh các producer/consumer Kafka trước khi cân nhắc thu hẹp hoặc xóa MSK cluster."),
    "KINESIS_STREAM": ("KINESIS_IDLE", "Xác minh luồng dữ liệu ingest trước khi xóa Kinesis Data Stream không có record."),
    "CLOUDFRONT_DISTRIBUTION": ("CLOUDFRONT_LOW_TRAFFIC", "Vô hiệu hóa (Disable) CloudFront distribution có lưu lượng request thấp trước khi xóa."),
    "BACKUP_VAULT": ("BACKUP_OLD_RECOVERY_POINT", "Dọn dẹp các recovery point đã quá hạn hoặc không còn nhu cầu phục hồi trong AWS Backup vault."),
    "EKS_CLUSTER": ("EKS_IDLE_CANDIDATE", "Xác minh nhu cầu triển khai workload trước khi xóa EKS control plane không có worker nodes."),
    "FSX_FILE_SYSTEM": ("FSX_LOW_ACTIVITY", "Sao lưu và xóa hệ thống tệp FSx không có hoạt động đọc/ghi dữ liệu để tối ưu chi phí lưu trữ."),
    "MEMORYDB_CLUSTER": ("MEMORYDB_IDLE", "Xác minh kết nối ứng dụng trước khi cân nhắc xóa MemoryDB cluster không sử dụng."),
    "DOCUMENTDB_CLUSTER": ("DOCUMENTDB_IDLE", "Tạm dừng hoặc tạo snapshot rồi xóa DocumentDB cluster không có kết nối."),
    "NEPTUNE_CLUSTER": ("NEPTUNE_IDLE", "Tạo snapshot và xóa Neptune graph database cluster không có kết nối."),
}


def _finding(kind, resource_id, level, reason, evidence):
    rule_id, recommendation = RULE_METADATA[kind]
    return {"type": kind, "resource_id": resource_id, "level": level, "reason": reason,
            "evidence": evidence, "rule_id": rule_id, "recommendation": recommendation}


def evaluate_ec2(instance, metric_values, cfg, window_start):
    """Evaluate hourly, deduplicated CPU/NetworkIn/NetworkOut samples from a collector."""
    if keep(instance.get("Tags", [])) or instance.get("State", {}).get("Name") != "running": return None
    level, evidence = idle(*metric_values, cfg["window_hours"], cfg)
    launch = instance.get("LaunchTime")
    evidence.update({"observation_start": window_start.isoformat(), "launch_time": _iso(launch)})
    issue = _creation_issue(launch, window_start)
    if issue:
        evidence["data_issues"].append(issue)
        reason = "Instance younger than observation window" if issue == "RESOURCE_TOO_YOUNG" else "Resource creation time unavailable; not classified as idle"
        return _finding("EC2", instance["InstanceId"], "INSUFFICIENT_DATA", reason, evidence)
    if level == "OK": return None
    reason = "Low CPU and network; confirm intended workload" if level == "REVIEW" else "Missing CloudWatch metrics; not classified as idle"
    return _finding("EC2", instance["InstanceId"], level, reason, evidence)


def evaluate_ebs(volume, observed_hours, cfg):
    """Observation duration comes from persisted real usage, even while findings are hidden."""
    if keep(volume.get("Tags", [])) or volume["State"] != "available" or volume["Attachments"]: return None
    level = "REVIEW" if observed_hours >= cfg["orphan_hours"] else "OBSERVING"
    return _finding("EBS", volume["VolumeId"], level, "Unattached volume; validate data retention",
                    {"size_gib": volume["Size"], "observed_hours": round(observed_hours, 1), "threshold_hours": cfg["orphan_hours"],
                     "thresholds": {"orphan_hours": cfg["orphan_hours"]}})


def evaluate_eip(address, observed_hours, cfg):
    if not address.get("AllocationId") or keep(address.get("Tags", [])) or address.get("AssociationId"): return None
    level = "REVIEW" if observed_hours >= cfg["orphan_hours"] else "OBSERVING"
    return _finding("EIP", address["AllocationId"], level, "Unassociated public IPv4; may be intentionally reserved",
                    {"observed_hours": round(observed_hours, 1), "threshold_hours": cfg["orphan_hours"],
                     "thresholds": {"orphan_hours": cfg["orphan_hours"]}})


def evaluate_snapshot(snapshot, referenced_snapshot_ids, relationships_complete, cfg, now):
    """Only a complete AMI listing can support an unreferenced-snapshot candidate."""
    rid, tags = snapshot["SnapshotId"], snapshot.get("Tags", [])
    if not relationships_complete or keep(tags) or rid in referenced_snapshot_ids: return None
    if "aws:backup" in snapshot.get("Description", "").lower() or any(tag.get("Key", "").startswith("aws:backup") for tag in tags): return None
    age_days = (now - snapshot["StartTime"]).total_seconds() / 86400
    if age_days < cfg["snapshot_days"] or snapshot["State"] != "completed": return None
    return _finding("SNAPSHOT", rid, "REVIEW", "Old snapshot not referenced by listed AMIs; backup purpose requires review",
                    {"age_days": int(age_days), "snapshot_days": cfg["snapshot_days"],
                     "volume_id": snapshot.get("VolumeId"), "logical_volume_gib": snapshot["VolumeSize"],
                     "relationships_complete": True, "thresholds": {"snapshot_days": cfg["snapshot_days"]},
                     "snapshot_started_at": snapshot["StartTime"].isoformat(),
                     "relationship_scope": "owned AMIs including disabled AMIs; backup/retention requires review"})


def rds_idle(cpu, connections, hours, cfg):
    values, evidence = _metric_data(
        {"cpu": cpu, "connections": connections}, hours,
        {"rds_cpu_percent": cfg["rds_cpu_percent"], "rds_connections": cfg["rds_connections"]},
        {"cpu": "Percent", "connections": "Count"},
    )
    if _unusable(evidence):
        return "INSUFFICIENT_DATA", evidence
    cpu_ordered = sorted(values["cpu"])
    connection_ordered = sorted(values["connections"])
    cpu_p95 = cpu_ordered[max(0, math.ceil(0.95 * len(cpu_ordered)) - 1)]
    connection_p95 = connection_ordered[max(0, math.ceil(0.95 * len(connection_ordered)) - 1)]
    evidence.update({
        "cpu_p95": round(cpu_p95, 3),
        "connections_p95": round(connection_p95, 3),
    })
    status = (
        "REVIEW"
        if cpu_p95 < cfg["rds_cpu_percent"] and connection_p95 < cfg["rds_connections"]
        else "OK"
    )
    return status, evidence


def _average_rule(samples, hours, threshold, evidence_key, metric_name, threshold_key):
    values, evidence = _metric_data({metric_name: samples}, hours, {threshold_key: threshold}, {metric_name: "Count"})
    if _unusable(evidence):
        return "INSUFFICIENT_DATA", evidence
    try:
        average = math.fsum(values[metric_name]) / len(values[metric_name])
    except OverflowError:
        return _overflow(evidence, (metric_name,))
    if not math.isfinite(average):
        return _overflow(evidence, (metric_name,))
    evidence[evidence_key] = round(average, 3)
    return ("REVIEW" if average < threshold else "OK"), evidence


def nat_idle(source_bytes, destination_bytes, hours, cfg):
    values, evidence = _metric_data(
        {"source": source_bytes, "destination": destination_bytes}, hours,
        {"nat_mib_hour": cfg["nat_mib_hour"]}, {"source": "Bytes", "destination": "Bytes"},
    )
    if _unusable(evidence):
        return "INSUFFICIENT_DATA", evidence
    try:
        source_hour = math.fsum(values["source"]) / len(values["source"])
        destination_hour = math.fsum(values["destination"]) / len(values["destination"])
        average = (source_hour + destination_hour) / 1048576
    except OverflowError:
        return _overflow(evidence, ("source", "destination"))
    if not math.isfinite(average):
        return _overflow(evidence, ("source", "destination"))
    evidence["nat_mib_hour"] = round(average, 3)
    return ("REVIEW" if average < cfg["nat_mib_hour"] else "OK"), evidence


def alb_idle(requests, hours, cfg):
    return _average_rule(requests, hours, cfg["alb_requests_hour"], "requests_hour", "requests", "alb_requests_hour")


def nlb_idle(flows, hours, cfg):
    return _average_rule(flows, hours, cfg["nlb_new_flows_hour"], "new_flows_hour", "flows", "nlb_new_flows_hour")


def stale_multipart(initiated, now):
    return ("REVIEW" if (now - initiated).total_seconds() > 7 * 86400 else "OK"), {
        "age_days": round((now - initiated).total_seconds() / 86400, 3),
        "threshold_days": 7, "thresholds": {"multipart_days": 7},
        "initiated_at": initiated.isoformat(),
    }


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) and value.utcoffset() is not None else None


def _creation_issue(created, window_start):
    if _iso(created) is None:
        return "MISSING_CREATION_TIME"
    return "RESOURCE_TOO_YOUNG" if created > window_start else None


def _metric_finding(kind, resource_id, created, level, evidence, window_start, reason):
    evidence.update(created_at=_iso(created), observation_start=window_start.isoformat())
    issue = _creation_issue(created, window_start)
    if issue:
        evidence["data_issues"].append(issue)
        level = "INSUFFICIENT_DATA"
        reason = "Resource younger than observation window" if issue == "RESOURCE_TOO_YOUNG" else "Resource creation time unavailable; not classified as idle"
    if level == "OK":
        return None
    if level == "INSUFFICIENT_DATA" and not issue:
        reason = "Missing CloudWatch metrics; not classified as idle"
    return _finding(kind, resource_id, level, reason, evidence)


def _missing_metric_finding(kind, resource_id, series, window_start, units):
    """Return INSUFFICIENT_DATA when any required CloudWatch series has no valid sample."""
    counts = {}
    missing = []
    for name, samples in series.items():
        valid = [
            value for value in samples
            if not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value >= 0
        ] if isinstance(samples, (list, tuple)) else []
        counts[name] = len(valid)
        if not valid:
            missing.append(name)
    if not missing:
        return None
    evidence = {
        "sample_counts": counts,
        "missing_metrics": missing,
        "metric_units": units,
        "data_issues": ["NO_CLOUDWATCH_METRICS"],
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding(kind, resource_id, "INSUFFICIENT_DATA",
                    "Missing CloudWatch metrics; not classified as idle", evidence)


def evaluate_rds(instance, metric_values, cfg, window_start):
    if instance.get("DBInstanceStatus") != "available" or keep(instance.get("TagList", [])):
        return None
    level, evidence = rds_idle(*metric_values, cfg["window_hours"], cfg)
    evidence.update(engine=instance.get("Engine"), instance_class=instance.get("DBInstanceClass"))
    return _metric_finding("RDS", instance["DBInstanceIdentifier"], instance.get("InstanceCreateTime"),
                           level, evidence, window_start, "Low database activity; confirm intended workload")


def evaluate_nat_gateway(gateway, metric_values, cfg, window_start):
    if gateway.get("State") != "available" or keep(gateway.get("Tags", [])):
        return None
    level, evidence = nat_idle(*metric_values, cfg["window_hours"], cfg)
    evidence.update(vpc_id=gateway.get("VpcId"), subnet_id=gateway.get("SubnetId"))
    return _metric_finding("NAT_GATEWAY", gateway["NatGatewayId"], gateway.get("CreateTime"),
                           level, evidence, window_start, "Low NAT traffic; confirm intended workload")


def evaluate_load_balancer(load_balancer, metric_values, cfg, window_start):
    kind = {"application": "ALB", "network": "NLB"}.get(load_balancer.get("Type"))
    if not kind or load_balancer.get("State", {}).get("Code") != "active" or keep(load_balancer.get("Tags", [])):
        return None
    evaluator = alb_idle if kind == "ALB" else nlb_idle
    level, evidence = evaluator(*metric_values, cfg["window_hours"], cfg)
    evidence["scheme"] = load_balancer.get("Scheme")
    reason = "Low ALB request volume; confirm intended workload" if kind == "ALB" else "Low NLB flow volume; confirm intended workload"
    return _metric_finding(kind, load_balancer["LoadBalancerName"], load_balancer.get("CreatedTime"),
                           level, evidence, window_start, reason)


def evaluate_s3_multipart(bucket, upload, now):
    initiated = upload.get("Initiated")
    evidence = {"bucket": bucket, "key": upload.get("Key"), "upload_id": upload.get("UploadId"),
                "threshold_days": 7, "thresholds": {"multipart_days": 7}, "initiated_at": _iso(initiated)}
    if _iso(initiated) is None or initiated > now:
        evidence["data_issues"] = ["INVALID_INITIATION_TIME"]
        return _finding("S3_MULTIPART", "s3://" + bucket + "/" + upload["Key"], "INSUFFICIENT_DATA",
                        "Multipart initiation time unavailable; not classified as stale", evidence)
    level, age_evidence = stale_multipart(initiated, now)
    if level == "OK":
        return None
    evidence.update(age_evidence)
    return _finding("S3_MULTIPART", "s3://" + bucket + "/" + upload["Key"], level,
                    "Multipart upload older than 7 days; confirm whether it is still needed", evidence)

def evaluate_lambda(function_info, metric_values, cfg, window_start, event_source_mappings_count=0, has_resource_policy=False):
    tags = function_info.get("Tags") or []
    if isinstance(tags, dict):
        tags = [{"Key": k, "Value": v} for k, v in tags.items()]
    if keep(tags):
        return None
    missing = _missing_metric_finding(
        "LAMBDA_FUNCTION", function_info["FunctionName"], {"invocations": metric_values or []},
        window_start, {"invocations": "Count"},
    )
    if missing:
        return missing
    invocations = [v for v in (metric_values or []) if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0]
    total_invocations = sum(invocations) if invocations else 0
    max_invocations = cfg.get("lambda_max_invocations", 0) if cfg else 0
    if total_invocations > max_invocations:
        return None
    code_size = function_info.get("CodeSize", 0)
    unused_days = cfg.get("lambda_unused_days", 30) if cfg else 30
    evidence = {
        "function_name": function_info["FunctionName"],
        "runtime": function_info.get("Runtime", "unknown"),
        "code_size_bytes": code_size,
        "code_size_mib": round(code_size / 1048576, 2),
        "last_modified": function_info.get("LastModified"),
        "invocations": total_invocations,
        "event_source_mappings": event_source_mappings_count,
        "has_resource_policy": has_resource_policy,
        "window_hours": cfg.get("window_hours", 24) if cfg else 24,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
        "thresholds": {"max_invocations": max_invocations, "unused_days": unused_days},
    }
    if event_source_mappings_count > 0 or has_resource_policy:
        reason = "Lambda function has 0 invocations; has configured triggers or permissions that may be dormant"
    else:
        reason = "Unused Lambda function with 0 invocations and no event source mappings"
    return _finding("LAMBDA_FUNCTION", function_info["FunctionName"], "REVIEW", reason, evidence)


def evaluate_log_group(log_group, cfg=None):
    tags = log_group.get("Tags") or log_group.get("tags") or []
    if isinstance(tags, dict):
        tags = [{"Key": k, "Value": v} for k, v in tags.items()]
    if keep(tags):
        return None
    retention = log_group.get("retentionInDays")
    if retention is not None and retention > 0:
        return None
    stored_bytes = log_group.get("storedBytes", 0)
    evidence = {
        "log_group_name": log_group["logGroupName"],
        "stored_bytes": stored_bytes,
        "stored_mib": round(stored_bytes / 1048576, 2),
        "retention_in_days": None,
        "recommended_retention_days": 30,
        "creation_time": log_group.get("creationTime"),
        "metric_units": {"stored_bytes": "Bytes"},
    }
    return _finding("LOG_GROUP", log_group["logGroupName"], "REVIEW",
                    "Log group has no retention policy set (Never Expire); accumulating storage costs", evidence)

def evaluate_security_group(sg, attached_sg_ids, referenced_sg_ids, observed_hours=0, cfg=None):
    if sg.get("GroupName") == "default" or keep(sg.get("Tags", [])):
        return None
    gid = sg["GroupId"]
    if gid in attached_sg_ids or gid in referenced_sg_ids:
        return None
    threshold_days = cfg.get("sg_unused_days", 7) if cfg else 7
    threshold_hours = threshold_days * 24
    level = "REVIEW" if observed_hours >= threshold_hours else "OBSERVING"
    evidence = {
        "group_id": gid,
        "group_name": sg.get("GroupName"),
        "vpc_id": sg.get("VpcId"),
        "description": sg.get("Description"),
        "observed_hours": round(observed_hours, 1),
        "threshold_hours": threshold_hours,
        "threshold_days": threshold_days,
    }
    return _finding("SECURITY_GROUP", gid, level,
                    "Security Group is not attached to any network interface or referenced by another group", evidence)

def evaluate_rds_snapshot(snapshot, cfg, now):
    if keep(snapshot.get("TagList", [])) or snapshot.get("SnapshotType") != "manual" or snapshot.get("Status") != "available":
        return None
    create_time = snapshot.get("SnapshotCreateTime")
    if not create_time or not isinstance(create_time, datetime):
        return None
    age_days = (now - create_time).total_seconds() / 86400
    threshold_days = cfg.get("rds_snapshot_days", 90)
    if age_days < threshold_days:
        return None
    evidence = {
        "snapshot_id": snapshot["DBSnapshotIdentifier"],
        "db_instance_id": snapshot.get("DBInstanceIdentifier"),
        "age_days": round(age_days, 1),
        "threshold_days": threshold_days,
        "engine": snapshot.get("Engine"),
        "allocated_storage_gib": snapshot.get("AllocatedStorage"),
        "snapshot_create_time": create_time.isoformat(),
    }
    return _finding("RDS_SNAPSHOT", snapshot["DBSnapshotIdentifier"], "REVIEW",
                    "Manual RDS snapshot older than retention threshold; verify backup necessity", evidence)


def evaluate_dynamodb_table(table_info, metric_values, cfg, window_start):
    if keep(table_info.get("Tags", [])) or table_info.get("TableStatus") != "ACTIVE":
        return None
    missing = _missing_metric_finding(
        "DYNAMODB_TABLE", table_info["TableName"],
        {"read": metric_values.get("read", []), "write": metric_values.get("write", [])},
        window_start, {"read": "Count", "write": "Count"},
    )
    if missing:
        return missing
    reads = [v for v in metric_values.get("read", []) if isinstance(v, (int, float)) and math.isfinite(v)]
    writes = [v for v in metric_values.get("write", []) if isinstance(v, (int, float)) and math.isfinite(v)]
    total_activity = sum(reads) + sum(writes)
    if total_activity > 0:
        return None
    billing_mode = table_info.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED")
    evidence = {
        "table_name": table_info["TableName"],
        "item_count": table_info.get("ItemCount", 0),
        "table_size_bytes": table_info.get("TableSizeBytes", 0),
        "billing_mode": billing_mode,
        "read_units": round(sum(reads), 2),
        "write_units": round(sum(writes), 2),
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("DYNAMODB_TABLE", table_info["TableName"], "REVIEW",
                    "DynamoDB table has zero read/write activity in observation window", evidence)


def evaluate_ecr_repository(repo, has_lifecycle_policy, oldest_image_age_days, cfg=None):
    if keep(repo.get("tags", [])):
        return None
    repo_name = repo["repositoryName"]
    image_threshold_days = cfg.get("ecr_image_days", 90) if cfg else 90
    if not has_lifecycle_policy:
        evidence = {
            "repository_name": repo_name,
            "registry_id": repo.get("registryId"),
            "has_lifecycle_policy": False,
        }
        return _finding("ECR_REPOSITORY", repo_name, "REVIEW",
                        "ECR repository has no lifecycle policy configured; images accumulate indefinitely", evidence)
    if oldest_image_age_days and oldest_image_age_days >= image_threshold_days:
        evidence = {
            "repository_name": repo_name,
            "registry_id": repo.get("registryId"),
            "has_lifecycle_policy": True,
            "oldest_image_age_days": round(oldest_image_age_days, 1),
            "threshold_days": image_threshold_days,
        }
        return {"type": "ECR_REPOSITORY", "resource_id": repo_name, "level": "REVIEW",
                "reason": f"ECR repository contains images older than {image_threshold_days} days",
                "evidence": evidence, "rule_id": "ECR_IMAGE_OLD",
                "recommendation": "Thiết lập hoặc điều chỉnh Lifecycle Policy để tự động dọn dẹp các image cũ."}
    return None


def evaluate_sqs_queue(queue_url, attributes, metric_values, cfg, window_start):
    name = queue_url.split("/")[-1]
    if "dlq" in name.lower() or "deadletter" in name.lower():
        return None  # Dead letter queues are intentionally quiet
    messages = int(attributes.get("ApproximateNumberOfMessages", 0))
    if messages > 0:
        return None
    missing = _missing_metric_finding(
        "SQS_QUEUE", name,
        {"sent": metric_values.get("sent", []), "received": metric_values.get("received", [])},
        window_start, {"sent": "Count", "received": "Count"},
    )
    if missing:
        return missing
    sent = sum(v for v in metric_values.get("sent", []) if isinstance(v, (int, float)) and math.isfinite(v))
    received = sum(v for v in metric_values.get("received", []) if isinstance(v, (int, float)) and math.isfinite(v))
    if sent > 0 or received > 0:
        return None
    evidence = {
        "queue_url": queue_url,
        "queue_name": name,
        "approximate_messages": messages,
        "messages_sent": round(sent, 2),
        "messages_received": round(received, 2),
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("SQS_QUEUE", name, "REVIEW",
                    "SQS queue has zero message traffic in observation window", evidence)


def evaluate_elasticache_cluster(cluster, metric_values, cfg, window_start):
    if keep(cluster.get("Tags", [])) or cluster.get("CacheClusterStatus") != "available":
        return None
    missing = _missing_metric_finding(
        "ELASTICACHE_CLUSTER", cluster["CacheClusterId"], {"connections": metric_values or []},
        window_start, {"connections": "Count"},
    )
    if missing:
        return missing
    connections = [v for v in (metric_values or []) if isinstance(v, (int, float)) and math.isfinite(v)]
    total_conns = sum(connections) if connections else 0
    if total_conns > 0:
        return None
    evidence = {
        "cluster_id": cluster["CacheClusterId"],
        "engine": cluster.get("Engine"),
        "cache_node_type": cluster.get("CacheNodeType"),
        "connections_sum": total_conns,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("ELASTICACHE_CLUSTER", cluster["CacheClusterId"], "REVIEW",
                    "ElastiCache cluster has zero client connections in observation window", evidence)


def evaluate_efs_file_system(fs, cfg=None):
    if keep(fs.get("Tags", [])) or fs.get("LifeCycleState") != "available":
        return None
    mount_targets = fs.get("NumberOfMountTargets", 0)
    if mount_targets > 0:
        return None
    evidence = {
        "file_system_id": fs["FileSystemId"],
        "size_in_bytes": fs.get("SizeInBytes", {}).get("Value", 0),
        "mount_targets_count": mount_targets,
        "creation_time": _iso(fs.get("CreationTime")),
    }
    return _finding("EFS_FILE_SYSTEM", fs["FileSystemId"], "REVIEW",
                    "EFS file system has no mount targets configured; not connected to any compute instance", evidence)


def evaluate_ecs_cluster(cluster, cfg=None):
    if keep(cluster.get("tags", [])) or cluster.get("status") != "ACTIVE":
        return None
    running = cluster.get("runningTasksCount", 0)
    pending = cluster.get("pendingTasksCount", 0)
    instances = cluster.get("registeredContainerInstancesCount", 0)
    services = cluster.get("activeServicesCount", 0)
    if running > 0 or pending > 0 or instances > 0 or services > 0:
        return None
    evidence = {
        "cluster_name": cluster["clusterName"],
        "cluster_arn": cluster.get("clusterArn"),
        "running_tasks": running,
        "active_services": services,
    }
    return _finding("ECS_CLUSTER", cluster["clusterName"], "REVIEW",
                    "ECS cluster has zero running tasks, container instances, and active services", evidence)


def evaluate_ecs_service(service, cfg=None):
    if keep(service.get("tags", [])) or service.get("status") != "ACTIVE":
        return None
    desired = service.get("desiredCount", 0)
    running = service.get("runningCount", 0)
    if desired > 0 or running > 0:
        return None
    evidence = {
        "service_name": service["serviceName"],
        "cluster_arn": service.get("clusterArn"),
        "desired_count": desired,
        "running_count": running,
    }
    return _finding("ECS_SERVICE", service["serviceName"], "REVIEW",
                    "ECS service has desired count set to 0", evidence)


def evaluate_auto_scaling_group(asg, cfg=None):
    if keep(asg.get("Tags", [])):
        return None
    desired = asg.get("DesiredCapacity", 0)
    min_size = asg.get("MinSize", 0)
    instances = len(asg.get("Instances", []))
    if desired > 0 or min_size > 0 or instances > 0:
        return None
    created = asg.get("CreatedTime")
    threshold_days = cfg.get("asg_zero_days", 7) if cfg else 7
    age_days = None
    if created and isinstance(created, datetime):
        age_days = (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds() / 86400
        if age_days < threshold_days:
            return None
    evidence = {
        "auto_scaling_group_name": asg["AutoScalingGroupName"],
        "desired_capacity": desired,
        "min_size": min_size,
        "instance_count": instances,
        "created_time": _iso(created),
        "threshold_days": threshold_days,
        "age_days": round(age_days, 1) if age_days is not None else None,
    }
    return _finding("AUTO_SCALING_GROUP", asg["AutoScalingGroupName"], "REVIEW",
                    f"Auto Scaling Group has 0 capacity for more than {threshold_days} days", evidence)

def evaluate_api_gateway(api_info, metric_values, cfg, window_start):
    if keep(api_info.get("tags", [])):
        return None
    missing = _missing_metric_finding(
        "API_GATEWAY", api_info.get("id") or api_info.get("ApiId", "unknown"),
        {"requests": metric_values or []}, window_start, {"requests": "Count"},
    )
    if missing:
        return missing
    requests = [v for v in (metric_values or []) if isinstance(v, (int, float)) and math.isfinite(v)]
    total_reqs = sum(requests) if requests else 0
    if total_reqs > 0:
        return None
    api_id = api_info.get("id") or api_info.get("ApiId", "unknown")
    name = api_info.get("name") or api_info.get("Name", api_id)
    evidence = {
        "api_id": api_id,
        "api_name": name,
        "request_count": total_reqs,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("API_GATEWAY", api_id, "REVIEW",
                    "API Gateway received zero requests in observation window", evidence)


def evaluate_sns_topic(topic_arn, attributes, metric_values, cfg, window_start):
    name = topic_arn.split(":")[-1]
    subs = int(attributes.get("SubscriptionsConfirmed", 0))
    if subs > 0:
        return None
    missing = _missing_metric_finding(
        "SNS_TOPIC", name, {"published": metric_values or []},
        window_start, {"published": "Count"},
    )
    if missing:
        return missing
    published = sum(v for v in (metric_values or []) if isinstance(v, (int, float)) and math.isfinite(v))
    if published > 0:
        return None
    evidence = {
        "topic_arn": topic_arn,
        "topic_name": name,
        "subscriptions_confirmed": subs,
        "messages_published": round(published, 2),
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("SNS_TOPIC", name, "REVIEW",
                    "SNS topic has zero confirmed subscriptions and zero published messages in observation window", evidence)


def evaluate_eventbridge_rule(rule_info, targets, cfg=None):
    if keep(rule_info.get("Tags", [])):
        return None
    name = rule_info["Name"]
    state = rule_info.get("State", "ENABLED")
    targets_count = len(targets)
    if state == "ENABLED" and targets_count > 0:
        return None
    reason = "EventBridge rule is DISABLED" if state == "DISABLED" else "EventBridge rule has no targets configured"
    evidence = {
        "rule_name": name,
        "rule_arn": rule_info.get("Arn"),
        "state": state,
        "targets_count": targets_count,
        "event_pattern": rule_info.get("EventPattern"),
        "schedule_expression": rule_info.get("ScheduleExpression"),
    }
    return _finding("EVENTBRIDGE_RULE", name, "REVIEW", reason, evidence)


def evaluate_step_function(sm_info, metric_values, cfg, window_start):
    name = sm_info["name"]
    missing = _missing_metric_finding(
        "STEP_FUNCTION", sm_info["name"], {"executions": metric_values or []},
        window_start, {"executions": "Count"},
    )
    if missing:
        return missing
    execs = [v for v in (metric_values or []) if isinstance(v, (int, float)) and math.isfinite(v)]
    total_execs = sum(execs) if execs else 0
    if total_execs > 0:
        return None
    evidence = {
        "state_machine_arn": sm_info["stateMachineArn"],
        "state_machine_name": name,
        "type": sm_info.get("type", "STANDARD"),
        "executions_count": total_execs,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("STEP_FUNCTION", name, "REVIEW",
                    "Step Functions state machine had zero executions started in observation window", evidence)


def evaluate_vpc_endpoint(vpce_info, metric_values, cfg, window_start):
    if keep(vpce_info.get("Tags", [])) or vpce_info.get("State") != "available":
        return None
    endpoint_type = vpce_info.get("VpcEndpointType", "Interface")
    if endpoint_type == "Gateway":
        return None
    eid = vpce_info["VpcEndpointId"]
    metric_series = metric_values if isinstance(metric_values, dict) else {"activity": metric_values or []}
    missing = _missing_metric_finding(
        "VPC_ENDPOINT", eid, metric_series, window_start,
        {name: "Bytes" if name == "bytes" else "Count" for name in metric_series},
    )
    if missing:
        return missing
    metric_values = [value for samples in metric_series.values() for value in samples]
    traffic = [v for v in (metric_values or []) if isinstance(v, (int, float)) and math.isfinite(v)]
    total_traffic = sum(traffic) if traffic else 0
    if total_traffic > 0:
        return None
    threshold_days = cfg.get("vpc_endpoint_unused_days", 14) if cfg else 14
    evidence = {
        "vpc_endpoint_id": eid,
        "vpc_id": vpce_info.get("VpcId"),
        "service_name": vpce_info.get("ServiceName"),
        "vpc_endpoint_type": endpoint_type,
        "bytes_processed": total_traffic,
        "threshold_days": threshold_days,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("VPC_ENDPOINT", eid, "REVIEW",
                    "VPC Endpoint has zero data transfer or connections in observation window", evidence)


def evaluate_sagemaker_endpoint(endpoint_info, metric_values, cfg, window_start):
    if keep(endpoint_info.get("Tags", [])) or endpoint_info.get("EndpointStatus") != "InService":
        return None
    missing = _missing_metric_finding(
        "SAGEMAKER_ENDPOINT", endpoint_info["EndpointName"], {"invocations": metric_values or []},
        window_start, {"invocations": "Count"},
    )
    if missing:
        return missing
    invocations = [v for v in (metric_values or []) if isinstance(v, (int, float)) and math.isfinite(v)]
    if sum(invocations) > 0:
        return None
    name = endpoint_info["EndpointName"]
    threshold_days = cfg.get("sagemaker_idle_days", 7) if cfg else 7
    evidence = {
        "endpoint_name": name,
        "endpoint_arn": endpoint_info.get("EndpointArn"),
        "endpoint_status": endpoint_info.get("EndpointStatus"),
        "invocations_sum": sum(invocations),
        "threshold_days": threshold_days,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("SAGEMAKER_ENDPOINT", name, "REVIEW",
                    "SageMaker endpoint has zero invocations in observation window", evidence)


def evaluate_opensearch_domain(domain_info, metric_values, cfg, window_start):
    if domain_info.get("Processing") is True or keep(domain_info.get("Tags", [])):
        return None
    metric_series = metric_values if isinstance(metric_values, dict) else {"requests": metric_values or []}
    missing = _missing_metric_finding(
        "OPENSEARCH_DOMAIN", domain_info["DomainName"], metric_series,
        window_start, {name: "Count" for name in metric_series},
    )
    if missing:
        return missing
    metric_values = [value for samples in metric_series.values() for value in samples]
    requests = [v for v in metric_values if isinstance(v, (int, float)) and math.isfinite(v)]
    if sum(requests) > 0:
        return None
    name = domain_info["DomainName"]
    threshold_days = cfg.get("opensearch_idle_days", 7) if cfg else 7
    evidence = {
        "domain_name": name,
        "domain_arn": domain_info.get("ARN"),
        "engine_version": domain_info.get("EngineVersion"),
        "requests_sum": sum(requests),
        "threshold_days": threshold_days,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("OPENSEARCH_DOMAIN", name, "REVIEW",
                    "OpenSearch domain has zero search or indexing requests in observation window", evidence)


def evaluate_redshift_cluster(cluster_info, metric_values, cfg, window_start):
    if keep(cluster_info.get("Tags", [])) or cluster_info.get("ClusterStatus") != "available":
        return None
    missing = _missing_metric_finding(
        "REDSHIFT_CLUSTER", cluster_info["ClusterIdentifier"], {"connections": metric_values or []},
        window_start, {"connections": "Count"},
    )
    if missing:
        return missing
    conns = [v for v in (metric_values or []) if isinstance(v, (int, float)) and math.isfinite(v)]
    if sum(conns) > 0:
        return None
    cid = cluster_info["ClusterIdentifier"]
    threshold_days = cfg.get("redshift_idle_days", 7) if cfg else 7
    evidence = {
        "cluster_identifier": cid,
        "node_type": cluster_info.get("NodeType"),
        "number_of_nodes": cluster_info.get("NumberOfNodes"),
        "database_connections": sum(conns),
        "threshold_days": threshold_days,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("REDSHIFT_CLUSTER", cid, "REVIEW",
                    "Redshift cluster has zero database connections in observation window", evidence)


def evaluate_msk_cluster(cluster_info, metric_values, cfg, window_start):
    if cluster_info.get("State") != "ACTIVE":
        return None
    metric_series = metric_values if isinstance(metric_values, dict) else {"traffic": metric_values or []}
    missing = _missing_metric_finding(
        "MSK_CLUSTER", cluster_info["ClusterName"], metric_series,
        window_start, {name: "Bytes" for name in metric_series},
    )
    if missing:
        return missing
    metric_values = [value for samples in metric_series.values() for value in samples]
    traffic = [v for v in metric_values if isinstance(v, (int, float)) and math.isfinite(v)]
    if sum(traffic) > 0:
        return None
    name = cluster_info["ClusterName"]
    threshold_days = cfg.get("msk_idle_days", 7) if cfg else 7
    evidence = {
        "cluster_name": name,
        "cluster_arn": cluster_info.get("ClusterArn"),
        "number_of_nodes": cluster_info.get("NumberOfBrokerNodes"),
        "traffic_sum": sum(traffic),
        "threshold_days": threshold_days,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("MSK_CLUSTER", name, "REVIEW",
                    "MSK Kafka cluster has zero incoming or outgoing message traffic in observation window", evidence)


def evaluate_kinesis_stream(stream_info, metric_values, cfg, window_start):
    if stream_info.get("StreamStatus") != "ACTIVE":
        return None
    missing = _missing_metric_finding(
        "KINESIS_STREAM", stream_info["StreamName"], {"records": metric_values or []},
        window_start, {"records": "Count"},
    )
    if missing:
        return missing
    records = [v for v in (metric_values or []) if isinstance(v, (int, float)) and math.isfinite(v)]
    if sum(records) > 0:
        return None
    name = stream_info["StreamName"]
    threshold_days = cfg.get("kinesis_idle_days", 7) if cfg else 7
    evidence = {
        "stream_name": name,
        "stream_arn": stream_info.get("StreamARN"),
        "records_sum": sum(records),
        "threshold_days": threshold_days,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("KINESIS_STREAM", name, "REVIEW",
                    "Kinesis Data Stream has zero incoming records in observation window", evidence)


def evaluate_cloudfront_distribution(dist_info, metric_values, cfg, window_start):
    if not dist_info.get("Enabled") or dist_info.get("Status") != "Deployed":
        return None
    did = dist_info["Id"]
    reqs = [v for v in (metric_values or []) if isinstance(v, (int, float)) and math.isfinite(v)]
    if not reqs:
        evidence = {
            "distribution_id": did,
            "domain_name": dist_info.get("DomainName"),
            "data_issues": ["NO_CLOUDWATCH_METRICS"],
            "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
        }
        return _finding("CLOUDFRONT_DISTRIBUTION", did, "INSUFFICIENT_DATA",
                        "Missing CloudWatch metrics for CloudFront; not classified as idle", evidence)
    total_reqs = sum(reqs)
    threshold = cfg.get("cloudfront_requests_day", 100) if cfg else 100
    if total_reqs >= threshold:
        return None
    evidence = {
        "distribution_id": did,
        "domain_name": dist_info.get("DomainName"),
        "requests_count": total_reqs,
        "threshold_requests_day": threshold,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("CLOUDFRONT_DISTRIBUTION", did, "REVIEW",
                    f"CloudFront distribution has low request traffic (< {threshold} requests/day)", evidence)

def evaluate_backup_vault(vault_info, expired_count, total_count, cfg=None):
    name = vault_info["BackupVaultName"]
    if expired_count == 0 and total_count == 0:
        return None
    if expired_count > 0:
        evidence = {
            "vault_name": name,
            "vault_arn": vault_info.get("BackupVaultArn"),
            "expired_recovery_points": expired_count,
            "total_recovery_points": total_count,
        }
        return _finding("BACKUP_VAULT", name, "REVIEW",
                        f"AWS Backup vault contains {expired_count} expired recovery points that were not deleted", evidence)
    return None


def evaluate_eks_cluster(cluster_info, nodegroups_count, fargate_count, cfg=None):
    if keep(cluster_info.get("tags", [])) or cluster_info.get("status") != "ACTIVE":
        return None
    if nodegroups_count > 0 or fargate_count > 0:
        return None
    name = cluster_info["name"]
    threshold_days = cfg.get("eks_idle_days", 14) if cfg else 14
    evidence = {
        "cluster_name": name,
        "cluster_arn": cluster_info.get("arn"),
        "version": cluster_info.get("version"),
        "nodegroups_count": nodegroups_count,
        "fargate_profiles_count": fargate_count,
        "threshold_days": threshold_days,
    }
    return _finding("EKS_CLUSTER", name, "REVIEW",
                    "EKS cluster has no active managed nodegroups or Fargate profiles", evidence)


def evaluate_fsx_filesystem(fs_info, metric_values, cfg, window_start):
    if keep(fs_info.get("Tags", [])) or fs_info.get("Lifecycle") != "AVAILABLE":
        return None
    metric_series = metric_values if isinstance(metric_values, dict) else {"io": metric_values or []}
    missing = _missing_metric_finding(
        "FSX_FILE_SYSTEM", fs_info["FileSystemId"], metric_series,
        window_start, {name: "Bytes" for name in metric_series},
    )
    if missing:
        return missing
    metric_values = [value for samples in metric_series.values() for value in samples]
    bytes_io = [v for v in metric_values if isinstance(v, (int, float)) and math.isfinite(v)]
    if sum(bytes_io) > 0:
        return None
    fid = fs_info["FileSystemId"]
    threshold_days = cfg.get("fsx_idle_days", 14) if cfg else 14
    evidence = {
        "file_system_id": fid,
        "file_system_type": fs_info.get("FileSystemType"),
        "storage_capacity": fs_info.get("StorageCapacity"),
        "total_io_bytes": sum(bytes_io),
        "threshold_days": threshold_days,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("FSX_FILE_SYSTEM", fid, "REVIEW",
                    "FSx file system has zero data read/write throughput in observation window", evidence)


def evaluate_memorydb_cluster(cluster_info, metric_values, cfg, window_start):
    if cluster_info.get("Status") != "available":
        return None
    missing = _missing_metric_finding(
        "MEMORYDB_CLUSTER", cluster_info["Name"], {"connections": metric_values or []},
        window_start, {"connections": "Count"},
    )
    if missing:
        return missing
    conns = [v for v in (metric_values or []) if isinstance(v, (int, float)) and math.isfinite(v)]
    if sum(conns) > 0:
        return None
    name = cluster_info["Name"]
    threshold_days = cfg.get("memorydb_idle_days", 7) if cfg else 7
    evidence = {
        "cluster_name": name,
        "cluster_arn": cluster_info.get("ARN"),
        "node_type": cluster_info.get("NodeType"),
        "connections_sum": sum(conns),
        "threshold_days": threshold_days,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("MEMORYDB_CLUSTER", name, "REVIEW",
                    "MemoryDB cluster has zero client connections in observation window", evidence)


def evaluate_documentdb_cluster(cluster_info, metric_values, cfg, window_start):
    if cluster_info.get("Status") != "available" or cluster_info.get("Engine") != "docdb":
        return None
    missing = _missing_metric_finding(
        "DOCUMENTDB_CLUSTER", cluster_info["DBClusterIdentifier"], {"connections": metric_values or []},
        window_start, {"connections": "Count"},
    )
    if missing:
        return missing
    conns = [v for v in (metric_values or []) if isinstance(v, (int, float)) and math.isfinite(v)]
    if sum(conns) > 0:
        return None
    cid = cluster_info["DBClusterIdentifier"]
    threshold_days = cfg.get("documentdb_idle_days", 7) if cfg else 7
    evidence = {
        "cluster_identifier": cid,
        "engine": "docdb",
        "cluster_members_count": len(cluster_info.get("DBClusterMembers", [])),
        "database_connections": sum(conns),
        "threshold_days": threshold_days,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("DOCUMENTDB_CLUSTER", cid, "REVIEW",
                    "DocumentDB cluster has zero client connections in observation window", evidence)


def evaluate_neptune_cluster(cluster_info, metric_values, cfg, window_start):
    if cluster_info.get("Status") != "available" or cluster_info.get("Engine") != "neptune":
        return None
    missing = _missing_metric_finding(
        "NEPTUNE_CLUSTER", cluster_info["DBClusterIdentifier"], {"connections": metric_values or []},
        window_start, {"connections": "Count"},
    )
    if missing:
        return missing
    conns = [v for v in (metric_values or []) if isinstance(v, (int, float)) and math.isfinite(v)]
    if sum(conns) > 0:
        return None
    cid = cluster_info["DBClusterIdentifier"]
    threshold_days = cfg.get("neptune_idle_days", 14) if cfg else 14
    evidence = {
        "cluster_identifier": cid,
        "engine": "neptune",
        "cluster_members_count": len(cluster_info.get("DBClusterMembers", [])),
        "database_connections": sum(conns),
        "threshold_days": threshold_days,
        "observation_start": window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start),
    }
    return _finding("NEPTUNE_CLUSTER", cid, "REVIEW",
                    "Neptune graph database cluster has zero client connections in observation window", evidence)


RESOURCE_REGISTRY = {
    "EC2": {"service_id": "ec2", "group": "compute", "display_name": "EC2 Instance", "rules": ["EC2_LOW_UTILIZATION"]},
    "EBS": {"service_id": "ebs", "group": "storage", "display_name": "EBS Volume", "rules": ["EBS_UNATTACHED"]},
    "EIP": {"service_id": "eip", "group": "network", "display_name": "Elastic IP", "rules": ["EIP_UNASSOCIATED"]},
    "SNAPSHOT": {"service_id": "snapshot", "group": "storage", "display_name": "EBS Snapshot", "rules": ["SNAPSHOT_OLD_UNREFERENCED"]},
    "S3_MULTIPART": {"service_id": "s3", "group": "storage", "display_name": "S3 Multipart Upload", "rules": ["S3_STALE_MULTIPART"]},
    "RDS": {"service_id": "rds", "group": "database", "display_name": "RDS Instance", "rules": ["RDS_LOW_UTILIZATION"]},
    "NAT_GATEWAY": {"service_id": "nat", "group": "network", "display_name": "NAT Gateway", "rules": ["NAT_LOW_UTILIZATION"]},
    "ALB": {"service_id": "alb", "group": "network", "display_name": "Application Load Balancer", "rules": ["ALB_LOW_UTILIZATION"]},
    "NLB": {"service_id": "nlb", "group": "network", "display_name": "Network Load Balancer", "rules": ["NLB_LOW_UTILIZATION"]},
    "LAMBDA_FUNCTION": {"service_id": "lambda", "group": "compute", "display_name": "Lambda Function", "rules": ["LAMBDA_UNUSED"]},
    "LOG_GROUP": {"service_id": "logs", "group": "integration", "display_name": "CloudWatch Log Group", "rules": ["LOG_GROUP_NO_RETENTION"]},
    "SECURITY_GROUP": {"service_id": "ec2", "group": "network", "display_name": "Security Group", "rules": ["SECURITY_GROUP_UNUSED"]},
    "RDS_SNAPSHOT": {"service_id": "rds", "group": "storage", "display_name": "RDS Snapshot", "rules": ["RDS_SNAPSHOT_OLD"]},
    "DYNAMODB_TABLE": {"service_id": "dynamodb", "group": "database", "display_name": "DynamoDB Table", "rules": ["DYNAMODB_IDLE"]},
    "ECR_REPOSITORY": {"service_id": "ecr", "group": "storage", "display_name": "ECR Repository", "rules": ["ECR_NO_LIFECYCLE", "ECR_IMAGE_OLD"]},
    "SQS_QUEUE": {"service_id": "sqs", "group": "integration", "display_name": "SQS Queue", "rules": ["SQS_QUEUE_IDLE"]},
    "ELASTICACHE_CLUSTER": {"service_id": "elasticache", "group": "database", "display_name": "ElastiCache Cluster", "rules": ["ELASTICACHE_IDLE"]},
    "EFS_FILE_SYSTEM": {"service_id": "efs", "group": "storage", "display_name": "EFS File System", "rules": ["EFS_NO_MOUNT_TARGET"]},
    "ECS_CLUSTER": {"service_id": "ecs", "group": "compute", "display_name": "ECS Cluster", "rules": ["ECS_CLUSTER_EMPTY"]},
    "ECS_SERVICE": {"service_id": "ecs", "group": "compute", "display_name": "ECS Service", "rules": ["ECS_SERVICE_IDLE"]},
    "AUTO_SCALING_GROUP": {"service_id": "autoscaling", "group": "compute", "display_name": "Auto Scaling Group", "rules": ["ASG_ZERO_CAPACITY_OLD"]},
    "API_GATEWAY": {"service_id": "apigateway", "group": "integration", "display_name": "API Gateway", "rules": ["API_GATEWAY_UNUSED"]},
    "SNS_TOPIC": {"service_id": "sns", "group": "integration", "display_name": "SNS Topic", "rules": ["SNS_TOPIC_UNUSED"]},
    "EVENTBRIDGE_RULE": {"service_id": "events", "group": "integration", "display_name": "EventBridge Rule", "rules": ["EVENTBRIDGE_RULE_UNUSED"]},
    "STEP_FUNCTION": {"service_id": "stepfunctions", "group": "integration", "display_name": "Step Function", "rules": ["STEP_FUNCTION_UNUSED"]},
    "VPC_ENDPOINT": {"service_id": "ec2", "group": "network", "display_name": "VPC Endpoint", "rules": ["VPC_ENDPOINT_UNUSED"]},
    "SAGEMAKER_ENDPOINT": {"service_id": "sagemaker", "group": "analytics", "display_name": "SageMaker Endpoint", "rules": ["SAGEMAKER_ENDPOINT_IDLE"]},
    "OPENSEARCH_DOMAIN": {"service_id": "opensearch", "group": "analytics", "display_name": "OpenSearch Domain", "rules": ["OPENSEARCH_IDLE"]},
    "REDSHIFT_CLUSTER": {"service_id": "redshift", "group": "analytics", "display_name": "Redshift Cluster", "rules": ["REDSHIFT_IDLE"]},
    "MSK_CLUSTER": {"service_id": "msk", "group": "analytics", "display_name": "MSK Kafka Cluster", "rules": ["MSK_IDLE"]},
    "KINESIS_STREAM": {"service_id": "kinesis", "group": "analytics", "display_name": "Kinesis Stream", "rules": ["KINESIS_IDLE"]},
    "CLOUDFRONT_DISTRIBUTION": {"service_id": "cloudfront", "group": "network", "display_name": "CloudFront Distribution", "rules": ["CLOUDFRONT_LOW_TRAFFIC"]},
    "BACKUP_VAULT": {"service_id": "backup", "group": "storage", "display_name": "AWS Backup Vault", "rules": ["BACKUP_OLD_RECOVERY_POINT"]},
    "EKS_CLUSTER": {"service_id": "eks", "group": "compute", "display_name": "EKS Cluster", "rules": ["EKS_IDLE_CANDIDATE"]},
    "FSX_FILE_SYSTEM": {"service_id": "fsx", "group": "storage", "display_name": "FSx File System", "rules": ["FSX_LOW_ACTIVITY"]},
    "MEMORYDB_CLUSTER": {"service_id": "memorydb", "group": "database", "display_name": "MemoryDB Cluster", "rules": ["MEMORYDB_IDLE"]},
    "DOCUMENTDB_CLUSTER": {"service_id": "documentdb", "group": "database", "display_name": "DocumentDB Cluster", "rules": ["DOCUMENTDB_IDLE"]},
    "NEPTUNE_CLUSTER": {"service_id": "neptune", "group": "database", "display_name": "Neptune Cluster", "rules": ["NEPTUNE_IDLE"]},
}
