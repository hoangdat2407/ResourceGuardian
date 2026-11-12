"""HTML/text email report for Cloud Resource Guardian scan notifications.

Pure rendering helpers only: no AWS calls and no state changes. ``app.notify``
keeps ownership of deduplication, cooldown and SES delivery.
"""
from datetime import datetime, timedelta, timezone
from html import escape as _escape
import re
from urllib.parse import urlsplit, urlunsplit

VN_TIMEZONE = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")

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


def _resource_key(finding):
    return finding.get("type") or "", finding.get("resource_id") or finding.get("resource_name") or ""


def _unique_count(level, findings):
    return len({_resource_key(finding) for finding in findings if finding.get("level") == level})


def _short_resource(finding, limit=56):
    value = str(finding.get("resource_name") or finding.get("resource_id") or "Không xác định")
    if value.startswith("arn:"):
        value = value.rsplit("/", 1)[-1] if "/" in value else value.rsplit(":", 1)[-1]
    if len(value) <= limit:
        return value
    return value[:32] + "…" + value[-16:]


def _top_resources(findings, limit=5):
    priority = {"REVIEW": 0, "OBSERVING": 1, "INSUFFICIENT_DATA": 2}
    ordered = sorted(
        enumerate(findings),
        key=lambda item: (priority.get(item[1].get("level"), 3), item[0]),
    )
    rows = []
    seen = set()
    for _, finding in ordered:
        key = _resource_key(finding)
        if key in seen:
            continue
        seen.add(key)
        level = finding.get("level") or ""
        rows.append({
            "service": service_name(finding.get("type")),
            "resource": _short_resource(finding),
            "reason": human_reason(finding),
            "status": LEVEL_LABELS.get(level, "Cần xem chi tiết"),
        })
        if len(rows) == limit:
            break
    return rows


def _dashboard_url(web_url):
    try:
        parsed = urlsplit(web_url)
    except (TypeError, ValueError):
        return ""
    if parsed.scheme != "https" or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))


def _scan_warning(status):
    if status == "PARTIAL":
        return "Lượt quét chưa đầy đủ. Một số dịch vụ không thể kiểm tra; số liệu bên dưới chỉ phản ánh phần đã quét."
    if status in ("FAILED", "TIMED_OUT"):
        return "Lượt quét không thành công. Không dùng email này để kết luận tài khoản AWS không có vấn đề."
    return ""


def build_email(profile, result, web_url=""):
    """Return concise HTML/text content for one scan notification; no I/O."""
    del profile  # Recipient/account details are intentionally not exposed in the email body.
    findings = [finding for finding in (result.get("findings") or []) if isinstance(finding, dict)]
    review_resources = _unique_count("REVIEW", findings)
    observing_resources = _unique_count("OBSERVING", findings)
    insufficient_resources = _unique_count("INSUFFICIENT_DATA", findings)
    top = _top_resources(findings)
    completed = result.get("completed_at")
    try:
        completed_text = datetime.fromtimestamp(completed, VN_TIMEZONE).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        completed_text = "Chưa có thời gian"
    status = result.get("status") or ""
    status_label = STATUS_LABELS.get(status, status or "Không xác định")
    warning = _scan_warning(status)
    link = _dashboard_url(web_url)
    if status in ("FAILED", "TIMED_OUT"):
        subject = "[Cloud Resource Guardian] Lượt quét không thành công"
    else:
        subject = "[Cloud Resource Guardian] " + str(review_resources) + " tài nguyên cần kiểm tra"
    is_empty = not findings

    text_lines = [
        "CLOUD RESOURCE GUARDIAN",
        "Kết quả quét tài nguyên AWS",
        "",
        "Thời gian: " + completed_text + " (giờ Việt Nam)",
        "Trạng thái: " + status_label,
    ]
    if warning:
        text_lines += ["", warning]
    if is_empty:
        text_lines += [
            "",
            "Không có tài nguyên cần kiểm tra, đang quan sát hoặc thiếu dữ liệu trong kết quả quét này.",
        ]
    else:
        text_lines += [
            "",
            "TỔNG QUAN",
            "- Cần kiểm tra: " + str(review_resources),
            "- Đang quan sát: " + str(observing_resources),
            "- Thiếu dữ liệu: " + str(insufficient_resources),
            "",
            "TÀI NGUYÊN NỔI BẬT",
        ]
        for index, row in enumerate(top, 1):
            text_lines += [
                str(index) + ". " + row["service"] + " — " + row["resource"],
                "   " + row["status"] + ": " + row["reason"],
            ]
        remaining = len({_resource_key(finding) for finding in findings}) - len(top)
        if remaining > 0:
            text_lines.append("Còn " + str(remaining) + " tài nguyên khác trên Dashboard.")
    if link:
        text_lines += ["", "Xem chi tiết trên Dashboard: " + link]
    text_lines += [
        "",
        "Cloud Resource Guardian chỉ đọc dữ liệu và không tự dừng hoặc xóa tài nguyên AWS.",
    ]
    text = "\n".join(text_lines)

    esc = _escape
    if status == "PARTIAL":
        badge_bg, badge_fg = "#fff4db", "#8a5200"
    elif status in ("FAILED", "TIMED_OUT"):
        badge_bg, badge_fg = "#fde8e7", "#a1221a"
    else:
        badge_bg, badge_fg = "#e8f5ec", "#1d6637"

    warning_html = ""
    if warning:
        warning_html = (
            '<div style="margin:16px 0 0;padding:12px 14px;border-left:4px solid '
            + ("#a1221a" if status in ("FAILED", "TIMED_OUT") else "#b36b00")
            + ';background:' + badge_bg + ';font-size:13px;line-height:1.5;color:' + badge_fg + ';">'
            + esc(warning) + "</div>"
        )

    button_html = ""
    if link:
        button_html = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="margin:22px 0 0;"><tr><td align="center">'
            '<a href="' + esc(link, quote=True) + '" style="display:inline-block;padding:12px 20px;'
            'border-radius:6px;background:#126b82;color:#ffffff;text-decoration:none;font-size:14px;'
            'font-weight:700;">Xem chi tiết trên Dashboard</a></td></tr></table>'
        )

    if is_empty:
        content_html = (
            '<p style="margin:20px 0 0;font-size:14px;line-height:1.6;color:#344955;">'
            "Không có tài nguyên cần kiểm tra, đang quan sát hoặc thiếu dữ liệu trong kết quả quét này."
            "</p>" + button_html
        )
    else:
        kpis = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="margin:20px 0 0;table-layout:fixed;"><tr>'
            '<td width="33%" valign="top" style="padding:0 4px 0 0;"><div style="padding:12px 6px;'
            'border:1px solid #dce4e8;border-radius:7px;text-align:center;">'
            '<div style="font-size:24px;font-weight:700;color:#9a5b00;">' + str(review_resources) + '</div>'
            '<div style="font-size:11px;color:#526570;">Cần kiểm tra</div></div></td>'
            '<td width="34%" valign="top" style="padding:0 2px;"><div style="padding:12px 6px;'
            'border:1px solid #dce4e8;border-radius:7px;text-align:center;">'
            '<div style="font-size:24px;font-weight:700;color:#344955;">' + str(observing_resources) + '</div>'
            '<div style="font-size:11px;color:#526570;">Đang quan sát</div></div></td>'
            '<td width="33%" valign="top" style="padding:0 0 0 4px;"><div style="padding:12px 6px;'
            'border:1px solid #dce4e8;border-radius:7px;text-align:center;">'
            '<div style="font-size:24px;font-weight:700;color:#344955;">' + str(insufficient_resources) + '</div>'
            '<div style="font-size:11px;color:#526570;">Thiếu dữ liệu</div></div></td>'
            "</tr></table>"
        )
        resources = ""
        for row in top:
            resources += (
                '<tr><td style="padding:12px 0;border-bottom:1px solid #edf1f3;">'
                '<div style="font-size:12px;color:#526570;">' + esc(row["service"]) + " · "
                + esc(row["status"]) + '</div>'
                '<div style="margin-top:3px;font-size:14px;font-weight:700;color:#172b36;'
                'word-break:break-word;">' + esc(row["resource"]) + '</div>'
                '<div style="margin-top:4px;font-size:13px;line-height:1.5;color:#344955;">'
                + esc(row["reason"]) + "</div></td></tr>"
            )
        unique_total = len({_resource_key(finding) for finding in findings})
        remaining = unique_total - len(top)
        more_html = (
            '<p style="margin:10px 0 0;font-size:12px;color:#526570;">Còn '
            + str(remaining) + " tài nguyên khác trên Dashboard.</p>"
            if remaining > 0 else ""
        )
        content_html = (
            kpis
            + '<h2 style="margin:24px 0 4px;font-size:15px;color:#172b36;">Tài nguyên nổi bật</h2>'
            + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            + resources + "</table>" + more_html + button_html
        )

    html = (
        '<!doctype html><html lang="vi"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>" + esc(subject) + "</title></head>"
        '<body style="margin:0;padding:0;background:#f2f5f6;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        '<tr><td align="center" style="padding:20px 10px;">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;max-width:600px;background:#ffffff;border:1px solid #dce4e8;border-radius:9px;">'
        '<tr><td style="padding:20px 22px;background:#172b36;border-radius:9px 9px 0 0;">'
        '<div style="font-size:18px;font-weight:700;color:#ffffff;">Cloud Resource Guardian</div>'
        '<div style="margin-top:3px;font-size:13px;color:#c8d4da;">Kết quả quét tài nguyên AWS</div>'
        '</td></tr><tr><td style="padding:20px 22px;">'
        '<div style="font-size:13px;line-height:1.65;color:#344955;">'
        '<div><strong>Thời gian:</strong> ' + esc(completed_text) + ' (giờ Việt Nam)</div>'
        '<div><strong>Trạng thái:</strong> <span style="display:inline-block;padding:2px 8px;'
        'border-radius:999px;background:' + badge_bg + ';color:' + badge_fg + ';font-weight:700;">'
        + esc(status_label) + "</span></div></div>"
        + warning_html + content_html
        + '<p style="margin:22px 0 0;padding-top:16px;border-top:1px solid #edf1f3;'
        'font-size:11px;line-height:1.6;color:#6a7b84;">Cloud Resource Guardian chỉ đọc dữ liệu và '
        'không tự dừng hoặc xóa tài nguyên AWS.</p>'
        '</td></tr></table></td></tr></table></body></html>'
    )
    return {"subject": subject, "text": text, "html": html}
