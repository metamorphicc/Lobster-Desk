"""Bounded continuous observation of received builder rewards. No signing authority."""
from datetime import timedelta
import json
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..domain import utcnow
from ..users.contracts import Address
from .ingestion import RevenueImporter

DAY = 86400000


class RevenueSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.revenue", env_prefix="REVENUE_", extra="ignore", hide_input_in_errors=True)
    enabled: bool = False
    builder: Address | None = None
    baseline_ms: int | None = Field(default=None, ge=0)
    book: Path = Path("data/treasury.sqlite3")
    poll_seconds: int = Field(default=30, ge=15, le=300)
    observation_delay_seconds: int = Field(default=60, ge=15, le=300)

    @field_validator("baseline_ms", mode="before")
    @classmethod
    def exact_timestamp(cls, value):
        if value is None: return None
        if type(value) is int: return value
        if isinstance(value, str) and value.isascii() and value.isdigit(): return int(value)
        raise ValueError("An exact integer baseline timestamp is required.")


class RevenueWatcher:
    def __init__(self, book, settings, client):
        if not settings.enabled or not settings.builder or settings.baseline_ms is None:
            raise ValueError("Explicit received-revenue observer configuration is required.")
        if book.path != settings.book.resolve(): raise ValueError("Revenue observer book differs from configuration.")
        self.book, self.settings = book, settings
        self.importer = RevenueImporter(book, client, settings.builder)
        self.binding = {"builder": settings.builder, "baseline_ms": settings.baseline_ms, "network": "mainnet"}
        with book.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS revenue_watches (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            row = db.execute("SELECT payload FROM revenue_watches WHERE id='builder'").fetchone()
            old = json.loads(row[0]) if row else None
            if old and old["binding"] != self.binding: raise ValueError("Revenue source/baseline is immutable; reconcile before migration.")
            if not old:
                db.execute("INSERT INTO revenue_watches VALUES ('builder',?)", (json.dumps({"binding": self.binding,
                    "active": False, "last_success_at": None, "last_attempt_at": None, "failed": False,
                    "poll_seconds": settings.poll_seconds}),))

    def state(self):
        with self.book.transaction() as db:
            return json.loads(db.execute("SELECT payload FROM revenue_watches WHERE id='builder'").fetchone()[0])

    def record(self, *, active, attempt=False, success=False, failed=False):
        with self.book.transaction() as db:
            row = json.loads(db.execute("SELECT payload FROM revenue_watches WHERE id='builder'").fetchone()[0])
            if row["binding"] != self.binding: raise ValueError("Revenue observer binding changed.")
            now = utcnow().isoformat()
            value = row | {"active": active, "failed": failed, "poll_seconds": self.settings.poll_seconds}
            if attempt: value["last_attempt_at"] = now
            if success: value["last_success_at"] = now
            db.execute("UPDATE revenue_watches SET payload=? WHERE id='builder'", (json.dumps(value),))

    async def tick(self):
        self.record(active=True, attempt=True)
        try:
            end = int((utcnow() - timedelta(seconds=self.settings.observation_delay_seconds)).timestamp()*1000)
            with self.book.transaction() as db:
                row = db.execute("SELECT payload FROM revenue_sources WHERE id=?", ("builder:" + self.settings.builder,)).fetchone()
                previous = json.loads(row[0]) if row else None
            cursor = previous["cursor_ms"] if previous else self.settings.baseline_ms
            if cursor < self.settings.baseline_ms: raise ValueError("Existing receipt cursor precedes the configured baseline; skipping history is forbidden.")
            if end < cursor: raise ValueError("Revenue observation clock regressed or baseline is in the future.")
            if previous and end == cursor:
                result = {"imported_receipts": [], "cursor_ms": cursor, "transfers_attempted": False}
            else:
                start = max(self.settings.baseline_ms, cursor - 5000) if previous else cursor
                result = await self.importer.sync_builder(start, min(end, start + 7*DAY))
            self.record(active=True, success=True)
            return result | {"caught_up": result["cursor_ms"] == end, "observation_lag_seconds": self.settings.observation_delay_seconds,
                "automatic_claims_enabled": False}
        except Exception:
            self.record(active=True, failed=True)
            raise

    def close(self): self.record(active=False)


def public_revenue_report(book):
    with book.transaction() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='revenue_watches'").fetchone()
        row = db.execute("SELECT payload FROM revenue_watches WHERE id='builder'").fetchone() if exists else None
        state = json.loads(row[0]) if row else None
        status, cursor = "not_configured", None
        if state:
            status = "stopped"
            if state["active"]:
                from datetime import datetime
                age = (utcnow() - datetime.fromisoformat(state["last_success_at"])).total_seconds() if state.get("last_success_at") else None
                status = "running" if not state["failed"] and age is not None and -2 <= age <= max(90, state["poll_seconds"]*3) else "unavailable"
            source = db.execute("SELECT payload FROM revenue_sources WHERE id=?", ("builder:" + state["binding"]["builder"],)).fetchone()
            cursor = json.loads(source[0])["cursor_ms"] if source else None
        return {"network": "mainnet", "status": status, "cursor_ms": cursor,
            "last_success_at": state.get("last_success_at") if state else None, "signing_enabled": False, "automatic_claims_enabled": False}
