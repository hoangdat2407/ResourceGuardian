"""HTML/text email report for Cloud Resource Guardian scan notifications.

Pure rendering helpers only: no AWS calls and no state changes. ``app.notify``
keeps ownership of deduplication, cooldown and SES delivery.
"""
from datetime import datetime, timezone
from html import escape as _escape
import re

SERVICE_NAMES = {
    "EC2": "Amazon EC2",
    "EBS": "Amazon EBS",
    "EIP": "Elastic IP",
    "SNAPSHOT": "EBS Snapshot",
    "S3_MULTIPART": "S3 Multipart Upload",
    "RDS": "Amazon RDS",
    "RDS_SNAPSHOT": "RDS Snapshot",
    "NAT_GATEWAY": "NAT Gateway",
    "ALB": "Application Load Balancer",
    "NLB": "Network Load Balancer",
    "LAMBDA_FUNCTION": "AWS Lambda",
    "LOG_GROUP": "CloudWatch Log Group",
    "SECURITY_GROUP": "Security Group",
    "VPC_ENDPOINT": "VPC Endpoint",
    "DYNAMODB_TABLE": "Amazon DynamoDB",
    "ELASTICACHE_CLUSTER": "Amazon ElastiCache",
    "MEMORYDB_CLUSTER": "Amazon MemoryDB",
    "DOCUMENTDB_CLUSTER": "Amazon DocumentDB",
    "NEPTUNE_CLUSTER": "Amazon Neptune",
    "EFS_FILE_SYSTEM": "Amazon EFS",
    "ECR_REPOSITORY": "Amazon ECR",
    "FSX_FILE_SYSTEM": "Amazon FSx",
    "BACKUP_VAULT": "AWS Backup",
    "ECS_CLUSTER": "Amazon ECS Cluster",
    "ECS_SERVICE": "Amazon ECS Service",
    "AUTO_SCALING_GROUP": "Auto Scaling Group",
    "EKS_CLUSTER": "Amazon EKS",
    "SQS_QUEUE": "Amazon SQS",
    "SNS_TOPIC": "Amazon SNS",
    "EVENTBRIDGE_RULE": "Amazon EventBridge",
    "STEP_FUNCTION": "AWS Step Functions",
    "API_GATEWAY": "Amazon API Gateway",
    "SAGEMAKER_ENDPOINT": "Amazon SageMaker",
    "OPENSEARCH_DOMAIN": "Amazon OpenSearch",
    "REDSHIFT_CLUSTER": "Amazon Redshift",
    "MSK_CLUSTER": "Amazon MSK",
    "KINESIS_STREAM": "Amazon Kinesis",
    "CLOUDFRONT_DISTRIBUTION": "Amazon CloudFront",
}

STATUS_LABELS = {
    "SUCCEEDED": "Hoàn tất",
    "SUCCESS": "Hoàn tất",
    "PARTIAL": "Chưa đầy đủ",
    "FAILED": "Thất bại",
    "TIMED_OUT": "Quá hạn",
    "RUNNING": "Đang quét",
    "QUEUED": "Đang chờ",
}

LEVEL_LABELS = {
    "REVIEW": "Cần kiểm tra",
    "OBSERVING": "Đang quan sát",
    "INSUFFICIENT_DATA": "Thiếu dữ liệu",
}

ERROR_HINTS = {
    "AccessDenied": "thiếu quyền IAM đọc tài nguyên",
    "AccessDeniedException": "thiếu quyền IAM đọc tài nguyên",
    "UnauthorizedOperation": "thiếu quyền IAM đọc tài nguyên",
    "SubscriptionRequiredException": "chưa kích hoạt subscription cho dịch vụ",
    "RequestLimitExceeded": "vượt giới hạn gọi API",
    "TIME_BUDGET": "hết thời gian xử lý an toàn",
    "RESOURCE_LIMIT": "chạm giới hạn số tài nguyên hiển thị",
}

EVIDENCE_FIELDS = {
    "observed_hours": ("Thời gian theo dõi", "giờ"),
    "age_days": ("Tuổi tài nguyên", "ngày"),
    "cpu_p95": ("CPU p95", "%"),
    "connections_p95": ("Kết nối p95", "kết nối"),
    "network_mib_hour": ("Lưu lượng mạng", "MiB/giờ"),
    "nat_mib_hour": ("Lưu lượng NAT", "MiB/giờ"),
    "requests_hour": ("Request trung bình", "request/giờ"),
    "new_flows_hour": ("Flow mới", "flow/giờ"),
    "invocations": ("Lượt gọi", "lượt"),
    "request_count": ("Request nhận được", "request"),
    "requests_count": ("Request trong ngày", "request"),
    "records_sum": ("Record nạp vào", "record"),
    "messages_sent": ("Tin nhắn gửi", "tin nhắn"),
    "messages_published": ("Tin nhắn publish", "tin nhắn"),
    "executions_count": ("Lượt thực thi", "lượt"),
    "size_gib": ("Dung lượng volume", "GiB"),
    "stored_mib": ("Dung lượng log", "MiB"),
    "mount_targets_count": ("Mount target", "điểm"),
    "running_tasks": ("Task đang chạy", "task"),
    "desired_count": ("Desired count", "task"),
    "instance_count": ("Instance đang chạy", "instance"),
    "expired_recovery_points": ("Recovery point hết hạn", "điểm"),
    "database_connections": ("Kết nối cơ sở dữ liệu", "kết nối"),
    "connections_sum": ("Kết nối client", "kết nối"),
    "traffic_sum": ("Lưu lượng", "byte"),
    "total_io_bytes": ("Lưu lượng I/O", "byte"),
    "retention_in_days": ("Thời gian lưu log", "ngày"),
}

EVIDENCE_ORDER = [
    "observed_hours", "age_days", "cpu_p95", "connections_p95", "network_mib_hour",
    "nat_mib_hour", "requests_hour", "new_flows_hour", "invocations", "request_count",
    "requests_count", "records_sum", "messages_sent", "messages_published",
    "executions_count", "expired_recovery_points", "running_tasks", "instance_count",
    "database_connections", "connections_sum", "traffic_sum", "total_io_bytes",
    "stored_mib", "mount_targets_count", "size_gib", "retention_in_days",
]

THRESHOLD_FIELDS = {
    "orphan_hours": ("ngưỡng theo dõi", "giờ"),
    "snapshot_days": ("ngưỡng tuổi snapshot", "ngày"),
    "multipart_days": ("ngưỡng tuổi multipart upload", "ngày"),
    "cpu_percent": ("ngưỡng CPU", "%"),
    "network_mib_hour": ("ngưỡng lưu lượng mạng", "MiB/giờ"),
    "rds_cpu_percent": ("ngưỡng CPU", "%"),
    "rds_connections": ("ngưỡng kết nối", "kết nối"),
    "nat_mib_hour": ("ngưỡng lưu lượng NAT", "MiB/giờ"),
    "alb_requests_hour": ("ngưỡng request", "request/giờ"),
    "nlb_new_flows_hour": ("ngưỡng flow mới", "flow/giờ"),
    "cloudfront_requests_day": ("ngưỡng request/ngày", "request/ngày"),
}

VI_REASONS = {
    "Low CPU and network; confirm intended workload": "CPU và lưu lượng mạng thấp; kiểm tra mục đích sử dụng.",
    "Missing CloudWatch metrics; not classified as idle": "Thiếu metrics CloudWatch; chưa thể kết luận ít hoạt động.",
    "Missing CloudWatch metrics for CloudFront; not classified as idle": "Thiếu metrics CloudWatch cho CloudFront; chưa thể kết luận ít hoạt động.",
    "Instance younger than observation window": "Instance mới hơn cửa sổ quan sát.",
    "Resource younger than observation window": "Tài nguyên mới hơn cửa sổ quan sát.",
    "Resource creation time unavailable; not classified as idle": "Không có thời điểm tạo tài nguyên; chưa thể kết luận ít hoạt động.",
    "Unattached volume; validate data retention": "Volume chưa gắn với EC2; kiểm tra nhu cầu giữ dữ liệu.",
    "Unassociated public IPv4; may be intentionally reserved": "Elastic IP chưa liên kết; có thể đang được giữ có chủ đích.",
    "Old snapshot not referenced by listed AMIs; backup purpose requires review": "Snapshot cũ không được AMI đã đọc tham chiếu; kiểm tra mục đích sao lưu.",
    "Only a complete AMI listing can support an unreferenced-snapshot candidate.": "Chỉ khi đọc đầy đủ danh sách AMI mới có thể kết luận snapshot không được tham chiếu.",
    "Multipart initiation time unavailable; not classified as stale": "Không có thời điểm bắt đầu multipart upload; chưa thể kết luận là tồn đọng.",
    "Multipart upload older than 7 days; confirm whether it is still needed": "Multipart upload đã tồn tại hơn 7 ngày; xác nhận xem còn cần thiết không.",
    "Lambda function has 0 invocations; has configured triggers or permissions that may be dormant": "Hàm Lambda không có lượt gọi; có trigger hoặc quyền nhưng không hoạt động.",
    "Unused Lambda function with 0 invocations and no event source mappings": "Hàm Lambda không có lượt gọi và không có event source mapping.",
    "Log group has no retention policy set (Never Expire); accumulating storage costs": "Nhóm log không đặt thời gian lưu giữ; dung lượng tăng dần.",
    "Security Group is not attached to any network interface or referenced by another group": "Security Group không gắn vào ENI nào và không được nhóm khác tham chiếu.",
    "Manual RDS snapshot older than retention threshold; verify backup necessity": "Bản chụp RDS thủ công cũ hơn ngưỡng; kiểm tra nhu cầu giữ backup.",
    "DynamoDB table has zero read/write activity in observation window": "Bảng DynamoDB không có hoạt động đọc/ghi trong cửa sổ quan sát.",
    "ECR repository has no lifecycle policy configured; images accumulate indefinitely": "Kho ảnh ECR chưa có Lifecycle Policy để dọn image cũ.",
    "SQS queue has zero message traffic in observation window": "Hàng đợi SQS không có lưu lượng tin nhắn trong cửa sổ quan sát.",
    "ElastiCache cluster has zero client connections in observation window": "Cụm ElastiCache không có kết nối client trong cửa sổ quan sát.",
    "EFS file system has no mount targets configured; not connected to any compute instance": "Hệ thống tệp EFS không có mount target; chưa kết nối tới compute.",
    "ECS cluster has zero running tasks, container instances, and active services": "Cụm ECS không có task, container instance hay service hoạt động.",
    "ECS service has desired count set to 0": "Service ECS đang đặt desired count bằng 0.",
    "Auto Scaling Group has 0 desired capacity, 0 min size, and 0 running instances": "Auto Scaling Group có desired và min capacity bằng 0.",
    "API Gateway received zero requests in observation window": "API Gateway không nhận request nào trong cửa sổ quan sát.",
    "SNS topic has zero confirmed subscriptions and zero published messages in observation window": "Topic SNS không có subscription xác nhận và không có tin nhắn publish.",
    "EventBridge rule is DISABLED": "Rule EventBridge đang ở trạng thái DISABLED.",
    "EventBridge rule has no targets configured": "Rule EventBridge không có target nào.",
    "Step Functions state machine had zero executions started in observation window": "State Machine không có lượt thực thi trong cửa sổ quan sát.",
    "VPC Endpoint has zero data transfer or connections in observation window": "VPC Endpoint không có lưu lượng hoặc kết nối trong cửa sổ quan sát.",
    "SageMaker endpoint has zero invocations in observation window": "SageMaker endpoint không có lượt gọi trong cửa sổ quan sát.",
    "OpenSearch domain has zero search or indexing requests in observation window": "OpenSearch domain không có request tìm kiếm hoặc indexing.",
    "Redshift cluster has zero database connections in observation window": "Redshift cluster không có kết nối cơ sở dữ liệu trong cửa sổ quan sát.",
    "MSK Kafka cluster has zero incoming or outgoing message traffic in observation window": "Cụm MSK không có lưu lượng tin nhắn vào/ra.",
    "Kinesis Data Stream has zero incoming records in observation window": "Kinesis Data Stream không có record nạp vào trong cửa sổ quan sát.",
    "AWS Backup vault contains expired recovery points that were not deleted": "AWS Backup vault còn recovery point đã hết hạn chưa xóa.",
    "EKS cluster has no active managed nodegroups or Fargate profiles": "EKS cluster không có node group hay Fargate profile hoạt động.",
    "FSx file system has zero data read/write throughput in observation window": "FSx không có thông lượng đọc/ghi trong cửa sổ quan sát.",
    "MemoryDB cluster has zero client connections in observation window": "Cụm MemoryDB không có kết nối client trong cửa sổ quan sát.",
    "DocumentDB cluster has zero client connections in observation window": "Cụm DocumentDB không có kết nối client trong cửa sổ quan sát.",
    "Neptune graph database cluster has zero client connections in observation window": "Cụm Neptune không có kết nối client trong cửa sổ quan sát.",
    "Low ALB request volume; confirm intended workload": "Lưu lượng request ALB thấp; kiểm tra mục đích sử dụng.",
    "Low NLB flow volume; confirm intended workload": "Lưu lượng flow NLB thấp; kiểm tra mục đích sử dụng.",
    "Low NAT traffic; confirm intended workload": "Lưu lượng qua NAT Gateway thấp; kiểm tra mục đích sử dụng.",
    "Low database activity; confirm intended workload": "Hoạt động cơ sở dữ liệu thấp; kiểm tra mục đích sử dụng.",
    "Low utilization activity; confirm intended workload": "Mức sử dụng thấp; kiểm tra mục đích sử dụng.",
}

GENERIC_REASON = "Cần kiểm tra tài nguyên theo quy tắc phát hiện."


def service_name(kind):
    return SERVICE_NAMES.get(kind or "", kind or "Dịch vụ AWS")


def number(value):
    if isinstance(value, bool):
        return "Có" if value else "Không"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return ("%.2f" % value).rstrip("0").rstrip(".").replace(".", ",")
    return str(value)


def human_reason(finding):
    reason = finding.get("reason") or ""
    if reason in VI_REASONS:
        return VI_REASONS[reason]
    patterns = [
        (r"^ECR repository contains images older than (\d+) days$", "Kho ảnh ECR có image cũ hơn {0} ngày."),
        (r"^Auto Scaling Group has 0 capacity for more than (\d+) days$", "Auto Scaling Group có dung lượng bằng 0 liên tục hơn {0} ngày."),
        (r"^CloudFront distribution has low request traffic \(< (\d+) requests/day\)$", "CloudFront nhận ít hơn {0} request mỗi ngày."),
        (r"^AWS Backup vault contains (\d+) expired recovery points that were not deleted$", "AWS Backup vault có {0} recovery point đã hết hạn chưa xóa."),
    ]
    for pattern, template in patterns:
        match = re.match(pattern, reason)
        if match:
            return template.format(match.group(1))
    if reason and not re.search(r"[A-Za-z]{4,}", reason):
        return reason
    return GENERIC_REASON


def _threshold_text(evidence):
    thresholds = evidence.get("thresholds")
    if isinstance(thresholds, dict):
        for key, (label, unit) in THRESHOLD_FIELDS.items():
            if thresholds.get(key) is not None:
                return label + " " + number(thresholds[key]) + (" " + unit if unit else "")
        for key, value in thresholds.items():
            if value is not None and isinstance(value, (int, float)):
                return "ngưỡng " + number(value)
    for key, label, unit in (
        ("threshold_hours", "ngưỡng theo dõi", "giờ"),
        ("snapshot_days", "ngưỡng tuổi snapshot", "ngày"),
        ("threshold_days", "ngưỡng", "ngày"),
    ):
        if evidence.get(key) is not None:
            return label + " " + number(evidence[key]) + (" " + unit if unit else "")
    return ""


def evidence_summary(finding):
    evidence = finding.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        return ""
    parts = []
    for key in EVIDENCE_ORDER:
        value = evidence.get(key)
        if value is None or isinstance(value, dict) or isinstance(value, list):
            continue
        label, unit = EVIDENCE_FIELDS[key]
        parts.append(label + " " + number(value) + (" " + unit if unit else ""))
        break
    threshold = _threshold_text(evidence)
    if threshold:
        parts.append(threshold)
    return " · ".join(parts)


def _errors(result):
    rows = []
    for error in result.get("errors") or []:
        if not isinstance(error, dict):
            continue
        code = str(error.get("code") or "")
        hint = ERROR_HINTS.get(code, "chưa đọc được dữ liệu của dịch vụ")
        rows.append({"service": service_name(error.get("type")), "hint": hint, "code": code})
    return rows


def _unique(level, findings):
    return {(f.get("type"), f.get("resource_id")) for f in findings if f.get("level") == level}


def _service_stats(review):
    stats = {}
    for finding in review:
        kind = finding.get("type") or ""
        entry = stats.setdefault(kind, {"alerts": 0, "resources": set()})
        entry["alerts"] += 1
        entry["resources"].add(finding.get("resource_id"))
    rows = [
        {"name": service_name(kind), "alerts": value["alerts"], "resources": len(value["resources"])}
        for kind, value in stats.items()
    ]
    return sorted(rows, key=lambda row: (-row["alerts"], row["name"]))


def _top_resources(review, limit=5):
    grouped = {}
    order = []
    for finding in review:
        key = (finding.get("type") or "", finding.get("resource_id") or "")
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(finding)
    rows = []
    for key in order[:limit]:
        findings = grouped[key]
        rows.append({
            "service": service_name(key[0]),
            "resource": key[1] or "Không xác định",
            "findings": [
                {"reason": human_reason(item), "evidence": evidence_summary(item)}
                for item in findings[:3]
            ],
            "more": max(0, len(findings) - 3),
        })
    return rows


def build_email(profile, result, web_url=""):
    """Return subject/text/html for one scan notification (pure, no I/O)."""
    findings = result.get("findings") or []
    review = [finding for finding in findings if finding.get("level") == "REVIEW"]
    total_findings = result.get("finding_count", len(findings))
    completed = result.get("completed_at")
    try:
        completed_text = datetime.fromtimestamp(completed, timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    except (TypeError, ValueError, OSError, OverflowError):
        completed_text = "Chưa có thời gian"
    status = result.get("status") or ""
    status_label = STATUS_LABELS.get(status, status or "Không xác định")
    account = profile.get("account_id") or "Không xác định"
    region = result.get("region") or "Không xác định"
    scan_id = result.get("scan_id") or "Không xác định"
    errors = _errors(result)
    error_services = {row["service"] for row in errors}
    review_resources = len(_unique("REVIEW", review))
    insufficient_resources = len(_unique("INSUFFICIENT_DATA", findings))
    observing_resources = len(_unique("OBSERVING", findings))
    stats = _service_stats(review)
    top = _top_resources(review)
    warning = ""
    if status == "PARTIAL":
        warning = "Lượt quét chưa đầy đủ. Các số liệu chỉ phản ánh phần đã quét thành công; không kết luận tài khoản AWS an toàn."
    elif status in ("FAILED", "TIMED_OUT"):
        warning = "Lượt quét không thành công. Không kết luận tài khoản AWS an toàn dựa trên email này."
    link = web_url if web_url.startswith(("https://", "http://")) else ""
    subject = "Cloud Resource Guardian: " + str(review_resources) + " tài nguyên cần kiểm tra"

    text_lines = [
        "CLOUD RESOURCE GUARDIAN — BÁO CÁO TÀI NGUYÊN AWS",
        "",
        "Lượt quét: " + completed_text,
        "AWS account: " + account,
        "Region: " + region,
        "Trạng thái: " + status_label,
        "Scan ID: " + scan_id,
        "",
    ]
    if warning:
        text_lines += ["CẢNH BÁO: " + warning, ""]
    if errors:
        text_lines.append("Dịch vụ chưa quét được:")
        for row in errors:
            text_lines.append("- " + row["service"] + ": " + row["hint"] + (" (" + row["code"] + ")" if row["code"] else ""))
        text_lines.append("")
    text_lines += [
        "TỔNG QUAN",
        "- Tài nguyên cần kiểm tra (REVIEW): " + str(review_resources),
        "- Tổng findings của lượt quét: " + str(total_findings),
        "- Dịch vụ gặp lỗi khi quét: " + str(len(error_services)),
    ]
    if insufficient_resources or observing_resources:
        text_lines.append(
            "- Đang quan sát: " + str(observing_resources)
            + " tài nguyên; thiếu dữ liệu: " + str(insufficient_resources) + " tài nguyên."
        )
    text_lines += ["", "CẢNH BÁO THEO DỊCH VỤ"]
    if stats:
        for row in stats:
            text_lines.append("- " + row["name"] + ": " + str(row["alerts"]) + " cảnh báo / " + str(row["resources"]) + " tài nguyên")
    else:
        text_lines.append("- Không có cảnh báo REVIEW trong lượt quét này.")
    text_lines += ["", "TÀI NGUYÊN ĐÁNG CHÚ Ý (tối đa 5)"]
    if top:
        for index, row in enumerate(top, 1):
            text_lines.append(str(index) + ". " + row["service"] + " — " + row["resource"])
            for item in row["findings"]:
                text_lines.append("   Lý do: " + item["reason"])
                if item["evidence"]:
                    text_lines.append("   Bằng chứng: " + item["evidence"])
            if row["more"]:
                text_lines.append("   Và " + str(row["more"]) + " cảnh báo khác trên cùng tài nguyên.")
    else:
        text_lines.append("Không có tài nguyên cần kiểm tra.")
    text_lines.append("")
    if link:
        text_lines += ["Xem chi tiết trên Dashboard: " + link, ""]
    text_lines += [
        "Thông tin bổ sung",
        "Account ID: " + account,
        "Scan ID: " + scan_id,
        "Hệ thống chỉ đọc dữ liệu và không tự dừng hoặc xóa tài nguyên AWS.",
        "Đây là danh sách ứng viên cần kiểm tra, không phải kết luận về mức độ nghiêm trọng hay chi phí tiết kiệm.",
    ]
    text = "\n".join(text_lines)

    esc = _escape
    stat_cell = 'class="stat-cell" valign="top" style="padding:0 6px 0 6px;"'
    if status == "PARTIAL":
        badge_bg, badge_fg = "#fdf5e6", "#a5600a"
    elif status in ("FAILED", "TIMED_OUT"):
        badge_bg, badge_fg = "#fdecea", "#b3261e"
    else:
        badge_bg, badge_fg = "#e9f5ee", "#1c6b3c"
    warning_html = ""
    if warning:
        colour = "#b3261e" if status in ("FAILED", "TIMED_OUT") else "#a5600a"
        background = "#fdecea" if status in ("FAILED", "TIMED_OUT") else "#fdf5e6"
        warning_html = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="margin:0 0 20px;"><tr><td style="background:' + background + ';border-left:4px solid ' + colour
            + ';border-radius:6px;padding:12px 14px;font-size:13px;line-height:1.5;color:' + colour + ';">'
            + esc(warning) + "</td></tr></table>"
        )
    errors_html = ""
    if errors:
        items = "".join(
            '<li style="margin:0 0 4px;">' + esc(row["service"]) + ": " + esc(row["hint"])
            + (' <span style="color:#5b6b77;">(' + esc(row["code"]) + ")</span>" if row["code"] else "") + "</li>"
            for row in errors
        )
        errors_html = (
            '<h2 style="margin:20px 0 8px;font-size:15px;color:#16232e;">Dịch vụ chưa quét được</h2>'
            '<ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.55;color:#3d4f5c;">' + items + "</ul>"
        )
    stats_html = ""
    for row in stats:
        stats_html += (
            '<tr><td style="padding:8px 0;border-bottom:1px solid #eef2f4;font-size:13px;color:#16232e;">'
            + esc(row["name"]) + '</td>'
            '<td style="padding:8px 0;border-bottom:1px solid #eef2f4;font-size:13px;text-align:right;color:#3d4f5c;white-space:nowrap;">'
            + str(row["alerts"]) + " cảnh báo · " + str(row["resources"]) + " tài nguyên</td></tr>"
        )
    if not stats_html:
        stats_html = '<tr><td colspan="2" style="padding:8px 0;font-size:13px;color:#5b6b77;">Không có cảnh báo REVIEW trong lượt quét này.</td></tr>'
    resources_html = ""
    for index, row in enumerate(top, 1):
        findings_html = ""
        for item in row["findings"]:
            evidence = ('<div style="margin:4px 0 0;font-size:12.5px;color:#5b6b77;">' + esc(item["evidence"]) + "</div>") if item["evidence"] else ""
            findings_html += (
                '<div style="margin:8px 0 0;"><div style="font-size:13px;line-height:1.5;color:#3d4f5c;">'
                + esc(item["reason"]) + "</div>" + evidence + "</div>"
            )
        more = ('<div style="margin:6px 0 0;font-size:12px;color:#5b6b77;">Và ' + str(row["more"]) + " cảnh báo khác trên cùng tài nguyên.</div>") if row["more"] else ""
        resources_html += (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 10px;">'
            '<tr><td style="border:1px solid #dde4e9;border-radius:8px;padding:12px 14px;background:#ffffff;">'
            '<div style="font-size:12px;color:#5b6b77;">' + str(index) + ". " + esc(row["service"]) + "</div>"
            '<div style="margin:3px 0 0;font-family:Consolas,Menlo,monospace;font-size:12.5px;color:#16232e;word-break:break-all;">'
            + esc(row["resource"]) + "</div>" + findings_html + more + "</td></tr></table>"
        )
    if not resources_html:
        resources_html = '<p style="margin:0;font-size:13px;color:#5b6b77;">Không có tài nguyên cần kiểm tra.</p>'
    button_html = ""
    if link:
        button_html = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:22px 0 4px;">'
            '<tr><td align="center"><a href="' + esc(link) + '" style="display:inline-block;background:#0f6f86;color:#ffffff;'
            'text-decoration:none;font-size:14px;font-weight:bold;padding:12px 22px;border-radius:7px;">'
            "Xem chi tiết trên Dashboard</a></td></tr></table>"
        )
    level_note = ""
    if insufficient_resources or observing_resources:
        level_note = (
            '<p style="margin:12px 0 0;font-size:12px;line-height:1.5;color:#5b6b77;">Đang quan sát: '
            + str(observing_resources) + " tài nguyên · Thiếu dữ liệu: " + str(insufficient_resources)
            + " tài nguyên. Tài nguyên thiếu dữ liệu không được coi là an toàn.</p>"
        )
    html = (
        '<!doctype html><html lang="vi"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>" + esc(subject) + "</title>"
        '<style>@media only screen and (max-width:480px){'
        ".stat-row > .stat-cell{display:block !important;width:100% !important;padding:0 0 8px 0 !important;}"
        "}</style></head>"
        '<body style="margin:0;padding:0;background:#f4f6f8;">'
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;">'
        + esc(str(review_resources) + " tài nguyên cần kiểm tra trong lượt quét " + completed_text + ".") + "</div>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f4f6f8;">'
        '<tr><td align="center" style="padding:24px 12px;">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;max-width:600px;background:#ffffff;border:1px solid #dde4e9;border-radius:10px;">'
        '<tr><td style="background:#12232e;border-radius:10px 10px 0 0;padding:20px 24px;">'
        '<div style="font-size:18px;font-weight:bold;color:#ffffff;">Cloud Resource Guardian</div>'
        '<div style="margin-top:4px;font-size:13px;color:#c3d3dc;">Báo cáo tài nguyên AWS</div></td></tr>'
        '<tr><td style="padding:20px 24px 8px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td style="font-size:13px;line-height:1.6;color:#3d4f5c;">'
        "<div><strong>Thời gian quét:</strong> " + esc(completed_text) + "</div>"
        "<div><strong>Region:</strong> " + esc(region) + "</div>"
        '<div><strong>Trạng thái:</strong> <span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        'background:' + badge_bg + ";color:" + badge_fg + ';font-size:12px;font-weight:bold;">' + esc(status_label) + "</span></div>"
        "</td></tr></table></td></tr>"
        '<tr><td style="padding:0 24px;">' + warning_html + errors_html + "</td></tr>"
        '<tr><td style="padding:4px 18px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr class="stat-row">'
        '<td ' + stat_cell + '><div style="border:1px solid #dde4e9;border-radius:8px;padding:12px;">'
        '<div style="font-size:12px;color:#5b6b77;">Cần kiểm tra</div>'
        '<div style="font-size:28px;font-weight:bold;color:#a5600a;line-height:1.2;">' + str(review_resources) + "</div>"
        '<div style="font-size:11px;color:#5b6b77;">tài nguyên</div></div></td>'
        '<td ' + stat_cell + '><div style="border:1px solid #dde4e9;border-radius:8px;padding:12px;">'
        '<div style="font-size:12px;color:#5b6b77;">Tổng findings</div>'
        '<div style="font-size:28px;font-weight:bold;color:#16232e;line-height:1.2;">' + str(total_findings) + "</div>"
        '<div style="font-size:11px;color:#5b6b77;">findings</div></div></td>'
        '<td ' + stat_cell + '><div style="border:1px solid #dde4e9;border-radius:8px;padding:12px;">'
        '<div style="font-size:12px;color:#5b6b77;">Dịch vụ quét lỗi</div>'
        '<div style="font-size:28px;font-weight:bold;color:#16232e;line-height:1.2;">' + str(len(error_services)) + "</div>"
        '<div style="font-size:11px;color:#5b6b77;">dịch vụ</div></div></td>'
        "</tr></table>"
        '<p style="margin:10px 6px 0;font-size:11.5px;line-height:1.5;color:#5b6b77;">'
        "Cần kiểm tra đếm theo tài nguyên duy nhất; tổng findings đếm theo số cảnh báo backend trả về.</p>"
        + level_note + "</td></tr>"
        '<tr><td style="padding:22px 24px 0;">'
        '<h2 style="margin:0 0 10px;font-size:15px;color:#16232e;">Cảnh báo theo dịch vụ</h2>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">' + stats_html + "</table>"
        "</td></tr>"
        '<tr><td style="padding:22px 24px 0;">'
        '<h2 style="margin:0 0 10px;font-size:15px;color:#16232e;">Tài nguyên đáng chú ý</h2>'
        '<p style="margin:0 0 10px;font-size:12px;color:#5b6b77;">Tối đa 5 tài nguyên đầu tiên theo kết quả quét; không xếp hạng mức độ nghiêm trọng.</p>'
        + resources_html + "</td></tr>"
        '<tr><td style="padding:8px 24px 0;">' + button_html + "</td></tr>"
        '<tr><td style="padding:22px 24px 24px;border-top:1px solid #eef2f4;">'
        '<div style="font-size:12px;line-height:1.6;color:#5b6b77;">'
        "<div>Account ID: " + esc(account) + "</div>"
        "<div>Scan ID: " + esc(scan_id) + "</div>"
        "<div>Hệ thống chỉ đọc dữ liệu và không tự dừng hoặc xóa tài nguyên AWS.</div>"
        "<div>Đây là danh sách ứng viên cần kiểm tra, không phải kết luận về mức độ nghiêm trọng hay chi phí tiết kiệm.</div>"
        "</div></td></tr>"
        "</table></td></tr></table></body></html>"
    )
    return {"subject": subject, "text": text, "html": html}
