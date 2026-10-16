"""One unsigned loopback readiness check. Does not schedule or deliver alerts."""

import argparse
import json

import httpx

from lobster.ops.probe import probe_exit_code, monitor_envelope, unavailable_envelope


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", action="store_true", help="Probe through Next's loopback proxy on port 3000 instead of API port 8000")
    parser.add_argument("--json", action="store_true", help="Write one bounded monitor envelope to stdout; no notification delivery")
    args = parser.parse_args()
    endpoint = "http://127.0.0.1:3000/api/ready" if args.web else "http://127.0.0.1:8000/api/ready"
    try:
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            response = client.get(endpoint)
        report = response.json()
        code = probe_exit_code(response.status_code, report)
        if args.json:
            print(json.dumps(monitor_envelope(response.status_code, report)))
            raise SystemExit(code)
        print("Local paper runtime: " + ("ready" if report["service_ready"] else "not ready"))
        for check in report["checks"]:
            print(f"  {check['status']}: {check['label']}")
        for alert in report["alerts"]:
            print(f"  {alert['severity']}: {alert['message']}")
        print("Production/exchange verification: not established by this probe. No execution state was changed.")
    except Exception:
        if args.json:
            print(json.dumps(unavailable_envelope()))
        parser.exit(2, "Readiness probe unavailable, malformed or inconsistent. Check the local API. No execution state was changed.\n")
    raise SystemExit(code)
