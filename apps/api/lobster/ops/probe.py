"""Strict interpretation of the local readiness report for the owner CLI."""


def probe_exit_code(status_code: int, report: dict) -> int:
    if (report.get("schema") != "lobster-local-readiness-v1" or report.get("scope") != "local-paper-runtime"
            or report.get("diagnostic_only") is not True or report.get("execution_mode") != "paper"
            or report.get("production_verified") is not False or report.get("exchange_execution_verified") is not False):
        raise ValueError("Unsupported readiness report.")
    ready = report.get("service_ready")
    checks, alerts = report.get("checks"), report.get("alerts")
    if not isinstance(ready, bool) or not isinstance(checks, list) or not checks or not isinstance(alerts, list):
        raise ValueError("Incomplete readiness report.")
    if any(not isinstance(check, dict) or check.get("status") not in {"ok", "blocked"}
           or not isinstance(check.get("label"), str) for check in checks):
        raise ValueError("Malformed readiness check.")
    if ready != all(check["status"] == "ok" for check in checks) or status_code != (200 if ready else 503):
        raise ValueError("Readiness flags and HTTP status disagree.")
    if any(not isinstance(alert, dict) or alert.get("severity") not in {"warning", "critical"}
           or not isinstance(alert.get("message"), str) for alert in alerts):
        raise ValueError("Malformed local alert.")
    return 0 if ready and not any(alert["severity"] == "critical" for alert in alerts) else 1


def monitor_envelope(status_code: int, report: dict) -> dict:
    """An external owner-run collector can ingest stdout; this sends nothing."""
    code = probe_exit_code(status_code, report)
    return {"schema": "lobster-monitor-observation-v1", "scope": "local-paper-runtime", "exit_code": code,
        "service_ready": report["service_ready"], "production_verified": False, "diagnostic_only": True,
        "alerts": [{"severity": item["severity"], "message": item["message"]} for item in report["alerts"]],
        "delivery_attempted": False}
