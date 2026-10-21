"""Redacted accruals from reconciled project settlements; no payment authority."""
from contextlib import closing
from datetime import datetime
from decimal import Decimal as D
import json
from pathlib import Path
import sqlite3

from ..execution.contracts import fingerprint
from ..ops.backup import read_only
from .book import TreasuryBook
from .distribution import DistributionPolicy, distribution_rows


def public_donations(runtime):
    unavailable = {"allocated": None, "sent": None, "outstanding": None,
        "scope": "own_agent_strategies_only", "payments_enabled": False}
    path = getattr(getattr(runtime, "settings", None), "treasury_path", None)
    if not path or not Path(path).is_file(): return unavailable
    try:
        with closing(read_only(Path(runtime.store.engine.url.database).resolve())) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_catalog'").fetchone(): return unavailable
            catalog = [json.loads(r[0]) for r in db.execute("SELECT payload FROM execution_catalog WHERE json_extract(payload,'$.role')='project' AND json_extract(payload,'$.network')='mainnet' LIMIT 2")]
        if len(catalog) != 1: return unavailable
        binding = catalog[0]
        if fingerprint({k: binding[k] for k in ("network", "account", "signer", "path", "role")}) != binding["id"]: return unavailable
        source_id = "project:" + binding["account"]
        with closing(read_only(Path(path).resolve())) as db:
            db.execute("BEGIN")
            if db.execute("SELECT count(*) FROM treasury_receipts").fetchone()[0] > 10000: return unavailable
            rows = TreasuryBook.read(db)
            source = db.execute("SELECT payload FROM revenue_sources WHERE id=?", (source_id,)).fetchone()
            if not source or not rows or rows[0]["entry"]["provenance"] != "owner_supplied_unverified": return unavailable
            source = json.loads(source[0])
            net = D(0)
            for row in rows:
                entry = row["entry"]
                if entry["kind"] not in {"trading_profit", "trading_loss", "strategy_checkpoint"}: continue
                cursor = round(datetime.fromisoformat(entry["occurred_at"]).timestamp()*1000)
                identity = fingerprint({"source": source_id, "baseline": source["baseline_ms"], "cursor": cursor})
                if (entry["id"] != identity or entry["receipt_ref"] != "hl-mainnet-settlement:" + identity
                        or not source["baseline_ms"] <= cursor <= source["cursor_ms"]): return unavailable
                net += D(entry["amount"]) * (-1 if entry["kind"] == "trading_loss" else 1)
            if not net.is_finite() or net != D(source["net_settled"]): return unavailable
            report = distribution_rows(rows, DistributionPolicy())
            return {k: report["donations"][k] for k in unavailable}
    except (ValueError, KeyError, TypeError, ArithmeticError, sqlite3.Error, OSError):
        return unavailable
