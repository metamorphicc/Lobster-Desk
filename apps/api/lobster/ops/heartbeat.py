"""Best-effort local runner observations. A telemetry failure never grants authority."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from ..domain import utcnow


def ping(path, service, *, ok=True, state="idle"):
    path = Path(path)
    if service not in {"project", "user", "testnet", "solana"} or not path.is_file(): return False
    try:
        with closing(sqlite3.connect(path, timeout=1)) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS ops_heartbeats (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            old = db.execute("SELECT payload FROM ops_heartbeats WHERE id=?", (service,)).fetchone()
            old = json.loads(old[0]) if old else {}
            value = {"service": service, "attempt_at": utcnow().isoformat(), "ok": bool(ok), "state": state,
                "last_success_at": utcnow().isoformat() if ok else old.get("last_success_at")}
            db.execute("INSERT OR REPLACE INTO ops_heartbeats VALUES (?,?)", (service, json.dumps(value)))
            db.commit()
        return True
    except Exception: return False
