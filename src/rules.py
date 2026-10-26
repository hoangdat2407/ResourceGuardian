"""Pure detection rules. Findings are review candidates, never deletion decisions."""
import hashlib
import json
import math

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


def idle(cpu, net_in, net_out, hours, cfg):
    """Require >=80% of hourly samples for all three metrics, including real zeros."""
    required = math.ceil(hours * .8)
    values, invalid = {}, []
    for name, samples in (("cpu", cpu), ("netin", net_in), ("netout", net_out)):
        values[name] = []
        for sample in samples:
            try:
                valid = not isinstance(sample, bool) and isinstance(sample, (int, float)) and math.isfinite(sample) and sample >= 0
            except OverflowError:
                valid = False
            if not valid:
                if name not in invalid: invalid.append(name)
            else:
                values[name].append(sample)
    counts = {name: len(samples) for name, samples in values.items()}
    missing = [name for name, count in counts.items() if count < required]
    evidence = {"window_hours": hours,
                "thresholds": {"cpu_percent": cfg["cpu_percent"], "network_mib_hour": cfg["network_mib_hour"]},
                "sample_counts": counts, "required_samples": required,
                "missing_metrics": missing, "invalid_metrics": invalid,
                "coverage": round(min(counts.values()) / hours, 3)}
    if missing or invalid:
        return "INSUFFICIENT_DATA", evidence
    ordered = sorted(values["cpu"])
    p95 = ordered[max(0, math.ceil(.95 * len(ordered)) - 1)]
    try:
        # Each hourly Sum is averaged only over hours actually measured in that
        # direction; missing hours must not dilute traffic as if they were zero.
        incoming_hour = math.fsum(values["netin"]) / counts["netin"]
        outgoing_hour = math.fsum(values["netout"]) / counts["netout"]
        mib_hour = (incoming_hour + outgoing_hour) / 1048576
    except OverflowError:
        mib_hour = float("inf")
    if not math.isfinite(mib_hour):
        evidence["invalid_metrics"] = ["netin", "netout"]
        return "INSUFFICIENT_DATA", evidence
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
    if keep(instance.get("Tags", [])) or instance["State"]["Name"] != "running": return None
    level, evidence = idle(*metric_values, cfg["window_hours"], cfg)
    evidence.update({"observation_start": window_start.isoformat(), "launch_time": instance["LaunchTime"].isoformat()})
    if instance["LaunchTime"] > window_start:
        return _finding("EC2", instance["InstanceId"], "INSUFFICIENT_DATA", "Instance younger than observation window", evidence)
    if level == "OK": return None
    reason = "Low CPU and network; confirm intended workload" if level == "REVIEW" else "Missing CloudWatch metrics; not classified as idle"
    return _finding("EC2", instance["InstanceId"], level, reason, evidence)


def evaluate_ebs(volume, observed_hours, cfg):
    """Observation duration comes from persisted real usage, even while findings are hidden."""
    if keep(volume.get("Tags", [])) or volume["State"] != "available" or volume["Attachments"]: return None
    level = "REVIEW" if observed_hours >= cfg["orphan_hours"] else "OBSERVING"
    return _finding("EBS", volume["VolumeId"], level, "Unattached volume; validate data retention",
                    {"size_gib": volume["Size"], "observed_hours": round(observed_hours, 1), "threshold_hours": cfg["orphan_hours"]})


def evaluate_eip(address, observed_hours, cfg):
    if not address.get("AllocationId") or keep(address.get("Tags", [])) or address.get("AssociationId"): return None
    level = "REVIEW" if observed_hours >= cfg["orphan_hours"] else "OBSERVING"
    return _finding("EIP", address["AllocationId"], level, "Unassociated public IPv4; may be intentionally reserved",
                    {"observed_hours": round(observed_hours, 1), "threshold_hours": cfg["orphan_hours"]})


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
                     "relationships_complete": True})


def _coverage(series, hours):
    """Require enough hourly samples and reject a series containing invalid data."""
    required = math.ceil(hours * 0.8)
    try:
        valid = all(
            not isinstance(sample, bool)
            and isinstance(sample, (int, float))
            and math.isfinite(sample)
            and sample >= 0
            for sample in series
        )
    except OverflowError:
        valid = False
    return valid and len(series) >= required, round(len(series) / hours, 3)


def rds_idle(cpu, connections, hours, cfg):
    cpu_ok, cpu_coverage = _coverage(cpu, hours)
    connection_ok, connection_coverage = _coverage(connections, hours)
    if not cpu_ok or not connection_ok:
        return "INSUFFICIENT_DATA", None
    cpu_ordered = sorted(cpu)
    connection_ordered = sorted(connections)
    cpu_p95 = cpu_ordered[max(0, math.ceil(0.95 * len(cpu_ordered)) - 1)]
    connection_p95 = connection_ordered[max(0, math.ceil(0.95 * len(connection_ordered)) - 1)]
    evidence = {
        "cpu_p95": round(cpu_p95, 3),
        "connections_p95": round(connection_p95, 3),
        "coverage": min(cpu_coverage, connection_coverage),
    }
    status = (
        "REVIEW"
        if cpu_p95 < cfg["rds_cpu_percent"] and connection_p95 < cfg["rds_connections"]
        else "OK"
    )
    return status, evidence


def _average_rule(values, hours, threshold, evidence_key, divisor=1):
    enough, coverage = _coverage(values, hours)
    if not enough:
        return "INSUFFICIENT_DATA", None
    try:
        average = math.fsum(values) / len(values) / divisor
    except OverflowError:
        return "INSUFFICIENT_DATA", None
    if not math.isfinite(average):
        return "INSUFFICIENT_DATA", None
    evidence = {evidence_key: round(average, 3), "coverage": coverage}
    return ("REVIEW" if average < threshold else "OK"), evidence


def nat_idle(source_bytes, destination_bytes, hours, cfg):
    source_ok, source_coverage = _coverage(source_bytes, hours)
    destination_ok, destination_coverage = _coverage(destination_bytes, hours)
    if not source_ok or not destination_ok:
        return "INSUFFICIENT_DATA", None
    try:
        source_hour = math.fsum(source_bytes) / len(source_bytes)
        destination_hour = math.fsum(destination_bytes) / len(destination_bytes)
        average = (source_hour + destination_hour) / 1048576
    except OverflowError:
        return "INSUFFICIENT_DATA", None
    if not math.isfinite(average):
        return "INSUFFICIENT_DATA", None
    evidence = {
        "nat_mib_hour": round(average, 3),
        "coverage": min(source_coverage, destination_coverage),
    }
    return ("REVIEW" if average < cfg["nat_mib_hour"] else "OK"), evidence


def alb_idle(requests, hours, cfg):
    return _average_rule(requests, hours, cfg["alb_requests_hour"], "requests_hour")


def nlb_idle(flows, hours, cfg):
    return _average_rule(flows, hours, cfg["nlb_new_flows_hour"], "new_flows_hour")


def stale_multipart(initiated, now):
    return ("REVIEW" if (now - initiated).total_seconds() > 7 * 86400 else "OK"), {
        "age_days": round((now - initiated).total_seconds() / 86400, 3)
    }
