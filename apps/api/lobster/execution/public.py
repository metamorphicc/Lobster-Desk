"""Bounded public project observations. User journals and signed commands stay private."""
from contextlib import closing
import json
from pathlib import Path

from ..domain import utcnow
from ..ops.backup import read_only
from .contracts import fingerprint


def project_activity(store):
    path = Path(store.engine.url.database).resolve()
    with closing(read_only(path)) as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_catalog'").fetchone()
        rows = db.execute("SELECT payload FROM execution_catalog WHERE json_extract(payload,'$.role')='project' LIMIT 5").fetchall() if exists else []
    if len(rows) > 4: raise ValueError("Project publication inventory exceeds its bound.")
    journals = []
    for row in rows:
        item = json.loads(row[0])
        if fingerprint({k: item[k] for k in ("network", "account", "signer", "path", "role")}) != item["id"]:
            raise ValueError("Project catalog binding changed.")
        with closing(read_only(Path(item["path"]).resolve())) as db:
            db.execute("BEGIN")
            control = json.loads(db.execute("SELECT payload FROM testnet_control WHERE id=1").fetchone()[0])
            if any(control[k] != item[k] for k in ("network", "account", "signer")):
                raise ValueError("Project journal identity differs.")
            trades = []
            for record in db.execute("SELECT payload FROM testnet_trades ORDER BY rowid DESC LIMIT 20"):
                trade = json.loads(record[0])
                if trade["network"] != item["network"]: raise ValueError("Project trade network differs.")
                setup, entry = trade["setup"], trade["entry"]
                fills = []
                for fill_row in db.execute("SELECT payload FROM testnet_fills WHERE trade_id=? ORDER BY rowid DESC LIMIT 40", (trade["id"],)):
                    fill = json.loads(fill_row[0])
                    fills.append({key: fill[key] for key in ("time", "px", "sz", "fee", "feeToken", "closedPnl", "side")})
                trades.append({"id": trade["id"], "network": trade["network"], "status": trade["status"],
                    "created_at": trade["created_at"], "direction": setup["pitch"]["direction"],
                    "entry": {k: entry[k] for k in ("side", "quantity", "price")},
                    "stop": setup["pitch"]["stop"], "target": setup["pitch"]["target"],
                    "filled_quantity": trade["filled_quantity"], "protected_quantity": trade["protected_quantity"],
                    "approval_hash": setup["approval_hash"],
                    "reviews": {role: {key: setup[role][key] for key in ("verdict", "summary", "evidence")} for role in ("analyst", "risk")},
                    "research": {k: v for k, v in (trade.get("audit_binding") or {}).items() if k in {"campaign_id", "strategy_hash", "max_holding_seconds"}},
                    "recent_fills": fills})
            # Never publish raw errors, signed payloads, owner/agent addresses,
            # command results or user consent audit bindings.
            heartbeat = None
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ops_heartbeats'").fetchone():
                record = db.execute("SELECT payload FROM ops_heartbeats WHERE id='project'").fetchone()
                if record:
                    beat = json.loads(record[0]); heartbeat = {k: beat.get(k) for k in ("attempt_at", "last_success_at", "ok")}
            journals.append({"id": item["id"], "network": item["network"], "halted": bool(control["halt_reason"]),
                "heartbeat": heartbeat, "trades": trades})
    return {"schema": "lobster-public-project-activity-v1", "observed_at": utcnow().isoformat(), "journals": journals,
        "scope": "registered-project-journals-only", "submission_enabled": False,
        "limits": "Latest 20 trades per journal and 40 fills per trade. Local runner observations are not independently verified exchange acceptance. Paper performance and private user journals are excluded."}
