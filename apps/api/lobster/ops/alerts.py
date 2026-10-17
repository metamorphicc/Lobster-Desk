"""Redacted local financial observations and durable opt-in webhook delivery."""
from contextlib import closing
from datetime import datetime
from hashlib import sha256
import hmac
import json
from pathlib import Path
import sqlite3
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..domain import utcnow
from ..execution.contracts import fingerprint
from .backup import read_only

SAFE_CODES = {"revenue_observation_unavailable", "database_unavailable", "worker_disabled", "market_worker_unavailable", "decision_worker_unavailable", "market_unavailable",
    "decision_error", "research_unavailable", "paper_paused", "paper_halted", "paper_funding_pending", "review_budget_exhausted",
    "testnet_reconciliation", "testnet_halted", "testnet_ledger_unavailable", "financial_runner_unavailable", "user_permission_uncertain",
    "user_consent_handoff", "exchange_command_uncertain", "exchange_exposure_review", "financial_journal_unavailable",
    "application_inventory_unavailable", "solana_transaction_uncertain", "charity_transaction_uncertain", "charity_pledge_uncertain",
    "treasury_journal_unavailable", "api_runtime_unavailable", "monitor_scope_mismatch"}
SAFE_SCOPES = {"service", "paper", "research", "testnet", "project", "user", "execution", "solana", "charity", "treasury"}


class AlertSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.ops", env_prefix="OPS_", extra="ignore", hide_input_in_errors=True)
    alerts_enabled: bool = False
    alert_webhook: SecretStr | None = None
    alert_webhook_secret: SecretStr | None = None
    alert_format: Literal["generic", "slack"] = "generic"
    state_path: Path = Path("data/operations.sqlite3")
    application_path: Path = Path("data/lobster.db")
    treasury_path: Path = Path("data/treasury.sqlite3")
    api_origin: Literal["http://127.0.0.1:8000"] = "http://127.0.0.1:8000"
    proxy_token: SecretStr | None = None

    @field_validator("alert_webhook", "alert_webhook_secret", "proxy_token", mode="before")
    @classmethod
    def blank(cls, value): return None if value == "" else value

    @model_validator(mode="after")
    def destination(self):
        if self.alert_webhook:
            target = urlsplit(self.alert_webhook.get_secret_value())
            if (target.scheme != "https" or not target.hostname or target.username or target.password or target.fragment
                    or target.port not in {None, 443} or target.hostname in {"localhost", "127.0.0.1", "::1"}
                    or target.hostname.endswith((".local", ".localhost"))):
                raise ValueError("An exact HTTPS notification endpoint without userinfo is required.")
            if self.alert_format == "slack" and (target.hostname != "hooks.slack.com" or not target.path.startswith("/services/")):
                raise ValueError("Slack format requires the official incoming webhook host/path.")
        return self

    def require_delivery(self):
        if not self.alerts_enabled or not self.alert_webhook: raise ValueError("Explicit alert delivery configuration required.")
        if self.alert_format == "generic" and (not self.alert_webhook_secret or len(self.alert_webhook_secret.get_secret_value()) < 32):
            raise ValueError("Generic notifications require a separate HMAC secret.")


def financial_observations(application_path, treasury_path):
    alerts = []
    def alert(code, severity, scope, count=1):
        if count: alerts.append({"code": code, "severity": severity, "scope": scope, "count": count})
    def rows(db, table):
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        return [json.loads(row[0]) for row in db.execute("SELECT payload FROM " + table)] if exists else []
    def stale_heartbeat(db, service, active):
        if not active: return
        states = {row["service"]: row for row in rows(db, "ops_heartbeats")}
        state = states.get(service)
        try:
            age = (utcnow() - datetime.fromisoformat(state["last_success_at"])).total_seconds() if state and state.get("last_success_at") else None
            healthy = state and state["ok"] and age is not None and -2 <= age <= (180 if service == "charity" else 30)
        except Exception: healthy = False
        if not healthy: alert("financial_runner_unavailable", "critical", service)
    try:
        with closing(read_only(Path(application_path))) as db:
            catalog = rows(db, "execution_catalog")
            jobs = rows(db, "user_financial_jobs")
        alert("user_permission_uncertain", "critical", "user", sum(job["kind"] != "trade" and job["status"] in {"sending", "unknown"} for job in jobs))
        linked_jobs = set()
        for item in catalog:
            try:
                with closing(read_only(Path(item["path"]))) as db:
                    control = json.loads(db.execute("SELECT payload FROM testnet_control WHERE id=1").fetchone()[0])
                    if any(control[k] != item[k] for k in ("network", "account", "signer")): raise ValueError("Journal identity differs")
                    trades, commands = rows(db, "testnet_trades"), rows(db, "testnet_commands")
                    linked_jobs.update((trade.get("audit_binding") or {}).get("user_intent_id") for trade in trades)
                    uncertain = sum(cmd["status"] in {"sending", "unknown"} for cmd in commands)
                    alert("exchange_command_uncertain", "critical", item["role"], uncertain)
                    active = any(t["status"] not in {"staged", "closed", "rejected", "expired", "cancelled"} for t in trades)
                    alert("exchange_exposure_review", "critical", item["role"], sum(t["status"] in {"needs_review", "emergency", "needs_protection", "closing_cleanup", "needs_reconciliation"} for t in trades))
                    stale_heartbeat(db, item["role"], active or uncertain)
            except Exception: alert("financial_journal_unavailable", "critical", "execution")
        alert("user_consent_handoff", "warning", "user", sum(job["kind"] == "trade" and job["status"] == "claimed" and job["id"] not in linked_jobs for job in jobs))
    except Exception: alert("application_inventory_unavailable", "critical", "service")
    if Path(treasury_path).exists():
        try:
            with closing(read_only(Path(treasury_path))) as db:
                solana, charity = rows(db, "solana_operations"), rows(db, "charity_payments")
                alert("solana_transaction_uncertain", "critical", "solana", sum(r["status"] in {"sending", "unknown"} for r in solana))
                alert("charity_transaction_uncertain", "critical", "charity", sum(r["status"] in {"sending", "unknown"} for r in charity))
                alert("charity_pledge_uncertain", "warning", "charity", sum(r["status"] in {"creating_pledge", "pledge_unknown"} for r in charity))
                stale_heartbeat(db, "solana", any(r["status"] in {"sending", "submitted", "unknown"} for r in solana))
                stale_heartbeat(db, "charity", any(r["status"] in {"sending", "submitted", "unknown"} for r in charity))
                for state in rows(db, "revenue_watches"):
                    if not state["active"]: continue
                    try:
                        age = (utcnow() - datetime.fromisoformat(state["last_success_at"])).total_seconds() if state.get("last_success_at") else None
                        healthy = not state["failed"] and age is not None and -2 <= age <= max(90, state["poll_seconds"]*3)
                    except Exception: healthy = False
                    if not healthy: alert("revenue_observation_unavailable", "warning", "treasury")
        except Exception: alert("treasury_journal_unavailable", "critical", "treasury")
    # Merge repeated static observations; no account, path, thesis, signature or
    # raw exception is eligible to leave this process in an alert payload.
    merged = {}
    for row in alerts:
        identity = (row["code"], row["severity"], row["scope"])
        merged[identity] = merged.get(identity, 0) + row["count"]
    return [{"code": key[0], "severity": key[1], "scope": key[2], "count": count} for key, count in sorted(merged.items())]


class AlertOutbox:
    def __init__(self, path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=3)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS ops_alert_state (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS ops_alert_outbox (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.commit()

    def observe(self, alerts):
        # Strictly rebuild the outbound schema. Provider/API free-form text and
        # all incidental private fields are excluded even if supplied by a caller.
        clean = []
        for item in alerts:
            if (item["code"] not in SAFE_CODES or item["severity"] not in {"warning", "critical"}
                    or item["scope"] not in SAFE_SCOPES or type(item["count"]) is not int or not 0 < item["count"] <= 100000):
                raise ValueError("Unbounded alert schema.")
            clean.append({k: item[k] for k in ("code", "severity", "scope", "count")})
        clean.sort(key=lambda r: (r["code"], r["severity"], r["scope"]))
        digest = fingerprint({"alerts": clean})
        with closing(sqlite3.connect(self.path, timeout=3)) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT payload FROM ops_alert_state WHERE id=1").fetchone()
            previous = json.loads(old[0]) if old else None
            if previous and previous["digest"] == digest:
                db.execute("UPDATE ops_alert_state SET payload=? WHERE id=1", (json.dumps({"digest": digest, "observed_at": utcnow().isoformat()}),))
                db.commit(); return None
            db.execute("INSERT OR REPLACE INTO ops_alert_state VALUES (1,?)", (json.dumps({"digest": digest, "observed_at": utcnow().isoformat()}),))
            if not previous and not clean: db.commit(); return None
            for prior in db.execute("SELECT id,payload FROM ops_alert_outbox").fetchall():
                item = json.loads(prior[1])
                if item["status"] == "pending" and item["attempts"] == 0:
                    item["status"] = "superseded"
                    db.execute("UPDATE ops_alert_outbox SET payload=? WHERE id=?", (json.dumps(item), prior[0]))
            row = {"id": uuid4().hex, "kind": "incident" if clean else "recovery", "alerts": clean,
                "created_at": utcnow().isoformat(), "status": "pending", "attempts": 0, "next_attempt_ms": 0}
            db.execute("INSERT INTO ops_alert_outbox VALUES (?,?)", (row["id"], json.dumps(row)))
            db.commit(); return row

    def rows(self):
        with closing(sqlite3.connect(self.path, timeout=3)) as db: return [json.loads(row[0]) for row in db.execute("SELECT payload FROM ops_alert_outbox ORDER BY rowid")]

    async def deliver(self, settings, client, *, armed=False):
        if not armed: raise ValueError("Explicit notification arming required.")
        settings.require_delivery()
        with closing(sqlite3.connect(self.path, timeout=3)) as db:
            db.execute("BEGIN IMMEDIATE")
            now = int(utcnow().timestamp()*1000)
            # Recover a process that died after the claim. The event ID remains
            # stable so a generic receiver can deduplicate a possible repeat.
            rows = [json.loads(r[0]) for r in db.execute("SELECT payload FROM ops_alert_outbox ORDER BY rowid")]
            for old in rows:
                if old["status"] == "sending" and old["attempts"] >= 5 and old["next_attempt_ms"] <= now:
                    old["status"] = "failed"
                    db.execute("UPDATE ops_alert_outbox SET payload=? WHERE id=?", (json.dumps(old), old["id"]))
            row = next((r for r in rows if r["status"] in {"pending", "sending"} and r["next_attempt_ms"] <= now and r["attempts"] < 5), None)
            if row is None: db.commit(); return None
            row.update(status="sending", attempts=row["attempts"]+1, next_attempt_ms=now+60000*min(15, 2**row["attempts"]))
            db.execute("UPDATE ops_alert_outbox SET payload=? WHERE id=?", (json.dumps(row), row["id"])); db.commit()
        event = {k: row[k] for k in ("id", "kind", "alerts", "created_at")}
        body = event if settings.alert_format == "generic" else {"text": "Lobster Desk " + row["kind"] + " · " + row["id"] + "\n" +
            ("\n".join(f"{a['severity']}: {a['code']} ({a['scope']}, {a['count']})" for a in row["alerts"]) or "Previously observed alerts cleared.")}
        payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json", "Idempotency-Key": row["id"], "X-Lobster-Event-ID": row["id"]}
        if settings.alert_webhook_secret:
            stamp = str(int(utcnow().timestamp()))
            headers["X-Lobster-Timestamp"] = stamp
            headers["X-Lobster-Signature"] = hmac.new(settings.alert_webhook_secret.get_secret_value().encode(), stamp.encode()+b"."+payload, sha256).hexdigest()
        try:
            response = await client.post(settings.alert_webhook.get_secret_value(), content=payload, headers=headers, follow_redirects=False, timeout=10)
            if not 200 <= response.status_code < 300: raise ValueError("Notification refused")
            status = "delivered"
        except Exception: status = "failed" if row["attempts"] >= 5 else "pending"
        with closing(sqlite3.connect(self.path, timeout=3)) as db:
            latest = json.loads(db.execute("SELECT payload FROM ops_alert_outbox WHERE id=?", (row["id"],)).fetchone()[0])
            if latest["status"] == "sending":
                latest["status"] = status
                db.execute("UPDATE ops_alert_outbox SET payload=? WHERE id=?", (json.dumps(latest), row["id"])); db.commit()
        return {"event_id": row["id"], "status": status, "attempts": row["attempts"]}
