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
    "window_hours": (24, 72, True),
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
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
            raise ValueError("Configuration must contain finite numbers")
        lo, hi, integer = LIMITS[key]
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
    if min(len(cpu), len(net_in), len(net_out)) < required:
        return "INSUFFICIENT_DATA", None
    ordered = sorted(cpu)
    p95 = ordered[max(0, math.ceil(.95 * len(ordered)) - 1)]
    mib_hour = (sum(net_in) + sum(net_out)) / hours / 1048576
    evidence = {"cpu_p95": round(p95, 3), "network_mib_hour": round(mib_hour, 3),
                "coverage": round(min(len(cpu), len(net_in), len(net_out)) / hours, 3)}
    return ("REVIEW" if p95 < cfg["cpu_percent"] and mib_hour < cfg["network_mib_hour"] else "OK"), evidence


def _coverage(series, hours):
    required = math.ceil(hours * 0.8)
    return len(series) >= required, round(len(series) / hours, 3)


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
    average = sum(values) / len(values) / divisor
    evidence = {evidence_key: round(average, 3), "coverage": coverage}
    return ("REVIEW" if average < threshold else "OK"), evidence


def nat_idle(source_bytes, destination_bytes, hours, cfg):
    source_ok, source_coverage = _coverage(source_bytes, hours)
    destination_ok, destination_coverage = _coverage(destination_bytes, hours)
    if not source_ok or not destination_ok:
        return "INSUFFICIENT_DATA", None
    average = (sum(source_bytes) + sum(destination_bytes)) / min(
        len(source_bytes), len(destination_bytes)
    ) / 1048576
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
