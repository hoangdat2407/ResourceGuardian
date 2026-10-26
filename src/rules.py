"""Pure detection rules. Findings are review candidates, never deletion decisions."""
import hashlib
import json
import math
from datetime import datetime

DEFAULTS = {
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

LIMITS = {
    "cpu_percent": (1, 50, False),
    "network_mib_hour": (0.1, 100, False),
    "window_hours": (24, 168, True),
    "orphan_hours": (1, 168, True),
    "snapshot_days": (7, 365, True),
    "interval_hours": (1, 24, True),
    "rds_cpu_percent": (1, 50, False),
    "rds_connections": (1, 1000, True),
    "nat_mib_hour": (0.1, 10000, False),
    "alb_requests_hour": (1, 1000000, True),
    "nlb_new_flows_hour": (1, 1000000, True),
}


def _merge_config(result, value):
    if not isinstance(value, dict) or set(value) - set(LIMITS):
        raise ValueError("Unknown configuration field")
    for key, val in value.items():
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError("Configuration must contain finite numbers")
        lo, hi, integer = LIMITS[key]
        # Check bounds before converting integers to floating point (or int).
        # This also rejects NaN/infinity without overflowing on huge JSON integers.
        if not lo <= val <= hi or (integer and val != int(val)):
            raise ValueError("Configuration outside supported bounds: " + key)
        result[key] = int(val) if integer else val


def config(value, base=None):
    """Normalize a partial settings update over defaults and an optional base."""
    result = dict(DEFAULTS)
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
