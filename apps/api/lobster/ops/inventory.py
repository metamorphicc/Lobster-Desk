"""Read-only discovery of every registered financial journal for recovery."""
from contextlib import closing
import json
from pathlib import Path

from ..execution.contracts import fingerprint
from .backup import read_only, sqlite_path, inspect_database


def discover_sources(config, testnet, project, user_config, *, operations_path=None):
    paper = sqlite_path(config.database_url)
    if not paper.is_file(): raise ValueError("Application database is missing.")
    sources = {"paper": paper}
    with closing(read_only(paper)) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        catalog = [json.loads(r[0]) for r in db.execute("SELECT payload FROM execution_catalog")] if "execution_catalog" in tables else []
        profiles = [json.loads(r[0]) for r in db.execute("SELECT payload FROM user_execution_profiles")] if "user_execution_profiles" in tables else []
        jobs = [json.loads(r[0]) for r in db.execute("SELECT payload FROM user_financial_jobs")] if "user_financial_jobs" in tables else []
    def execution(path, *, required=False):
        path = path.resolve()
        if not path.is_file():
            if required: raise ValueError("A configured/registered financial journal is missing; incomplete recovery refused.")
            return
        if path in sources.values(): return
        role = "execution-" + fingerprint({"path": str(path)})[:24]
        inspect_database(path, role)
        sources[role] = path
    for item in catalog:
        if fingerprint({k: item[k] for k in ("network", "account", "signer", "path", "role")}) != item["id"]:
            raise ValueError("Financial catalog binding integrity failed.")
        path = Path(item["path"]).resolve()
        if not path.is_file(): raise ValueError("A registered financial journal is missing; incomplete recovery refused.")
        with closing(read_only(path)) as db:
            control = json.loads(db.execute("SELECT payload FROM testnet_control WHERE id=1").fetchone()[0])
        if any(control[k] != item[k] for k in ("network", "account", "signer")): raise ValueError("Catalog/journal financial identity mismatch.")
        execution(path, required=True)
    execution(sqlite_path(testnet.database_url), required=bool(testnet.account_address and testnet.api_wallet_address))
    execution(sqlite_path(project.database_url), required=bool(project.enabled and project.account and project.agent))
    root = Path(user_config.execution_root).resolve()
    for profile in profiles:
        owner, agent = profile["address"], profile["agent"]
        if any(item["account"] == owner and item["signer"] == agent and item["network"] == profile["network"] for item in catalog):
            continue  # Preserve the registered canonical path even after a config-root edit.
        path = (root / owner / (agent + ".sqlite3")).resolve()
        if not path.is_relative_to(root): raise ValueError("User journal escapes configured recovery root.")
        claimed = any(job["owner"] == owner and job["network"] == profile["network"] and job["kind"] == "trade" and job["status"] == "claimed" for job in jobs)
        execution(path, required=claimed)
    treasury = Path(config.treasury_path).resolve()
    if treasury.exists():
        if treasury in sources.values(): raise ValueError("Treasury/application journals must remain separate.")
        inspect_database(treasury, "treasury"); sources["treasury"] = treasury
    operations = Path(operations_path or getattr(config, "operations_path", "data/operations.sqlite3")).resolve()
    if operations.exists():
        if operations in sources.values(): raise ValueError("Operations state must remain separate.")
        inspect_database(operations, "operations"); sources["operations"] = operations
    return sources
