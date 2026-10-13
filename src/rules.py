"""Pure detection rules. Findings are review candidates, never deletion decisions."""
import math

DEFAULTS = {"cpu_percent": 5, "network_mib_hour": 1, "window_hours": 24,
            "orphan_hours": 24, "snapshot_days": 30, "interval_hours": 6}

def config(value):
    limits = {"cpu_percent": (1, 50), "network_mib_hour": (0.1, 100),
              "window_hours": (24, 72), "orphan_hours": (1, 168),
              "snapshot_days": (7, 365), "interval_hours": (1, 24)}
    result = dict(DEFAULTS)
    if not isinstance(value, dict) or set(value) - set(limits):
        raise ValueError("Unknown configuration field")
    for key, val in value.items():
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
            raise ValueError("Configuration must contain finite numbers")
        lo, hi = limits[key]
        if not lo <= val <= hi or (key not in ("cpu_percent", "network_mib_hour") and val != int(val)):
            raise ValueError("Configuration outside supported bounds: " + key)
        result[key] = val
    return result

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
