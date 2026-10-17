"""Read-only operations watch; notifications need separate opt-in and arming."""
import argparse
import asyncio
import json

import httpx

from lobster.domain import utcnow
from lobster.execution.lease import RunnerLease
from lobster.ops.alerts import AlertSettings, AlertOutbox, financial_observations, SAFE_CODES, SAFE_SCOPES
from lobster.execution.contracts import fingerprint


async def observe(settings, client):
    alerts = financial_observations(settings.application_path, settings.treasury_path)
    headers = {}
    if settings.proxy_token:
        headers = {"X-Lobster-Proxy-Token": settings.proxy_token.get_secret_value(), "X-Lobster-Client-IP": "127.0.0.1"}
    try:
        response = await client.get(settings.api_origin + "/api/ready", headers=headers, timeout=10, follow_redirects=False)
        if response.status_code not in {200, 503}: raise ValueError("Unknown readiness response")
        data = response.json()
        from datetime import datetime
        age = (utcnow() - datetime.fromisoformat(data["observed_at"])).total_seconds()
        if data["schema"] != "lobster-local-readiness-v1" or not -2 <= age <= 180 or not isinstance(data["alerts"], list):
            raise ValueError("Stale/unknown readiness schema")
        if data.get("instance_fingerprint") != fingerprint({"database": str(settings.application_path.resolve())}):
            alerts.append({"code": "monitor_scope_mismatch", "scope": "service", "severity": "critical", "count": 1})
            return alerts
        for row in data["alerts"]:
            if row["code"] not in SAFE_CODES or row["scope"] not in SAFE_SCOPES or row["severity"] not in {"warning", "critical"}:
                raise ValueError("Unknown readiness alert schema")
            alerts.append({"code": row["code"], "scope": row["scope"], "severity": row["severity"], "count": 1})
    except Exception: alerts.append({"code": "api_runtime_unavailable", "scope": "service", "severity": "critical", "count": 1})
    return alerts


async def main(args):
    settings = AlertSettings()
    if args.notify:
        if not args.arm: raise ValueError("Explicit --arm required for notification delivery.")
        settings.require_delivery()
    outbox = AlertOutbox(settings.state_path)
    with RunnerLease(settings.state_path.with_suffix(".runner.lock"), "operations monitor"):
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            while True:
                alerts = await observe(settings, client)
                event = outbox.observe(alerts)
                result = {"observed_at": utcnow().isoformat(), "alerts": alerts,
                    "event_created": event["id"] if event else None, "notification_attempted": False}
                if args.notify:
                    delivery = await outbox.deliver(settings, client, armed=True)
                    result.update(notification_attempted=delivery is not None, delivery=delivery)
                print(json.dumps(result))
                if not args.watch: break
                await asyncio.sleep(15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--arm", action="store_true")
    try: asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt: print("Operations monitor stopped. Financial runners are separate processes.")
    except Exception: parser.exit(1, "Operations watch failed. Check local database/monitor settings. No financial command was attempted; credentials were not printed.\n")
