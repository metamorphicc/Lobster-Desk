"""SQLite snapshots and restore drills. Restores never replace an existing path."""

from contextlib import closing
from hashlib import file_digest
import json
from pathlib import Path
import shutil
import sqlite3
import time
import re

from sqlalchemy.engine import make_url

from ..domain import utcnow

SCHEMA = "lobster-sqlite-backup-v1"
REQUIRED = {"paper": {"accounts", "episodes", "positions", "events"},
    "testnet": {"testnet_control", "testnet_trades", "testnet_commands", "testnet_fills", "testnet_events"},
    "treasury": {"treasury_receipts"}}
MAX_DATABASES = 128


def required_tables(role):
    if role in REQUIRED: return REQUIRED[role]
    if re.fullmatch(r"execution-[a-f0-9]{24}", role): return REQUIRED["testnet"]
    raise ValueError("Unknown recovery database role.")


def sqlite_path(url: str) -> Path:
    parsed = make_url(url)
    if not parsed.drivername.startswith("sqlite") or not parsed.database or parsed.database == ":memory:" or parsed.query:
        raise ValueError("This tool supports local file-backed SQLite only. Use a database-native backup tool for other configurations.")
    return Path(parsed.database).resolve()


def checksum(path: Path) -> str:
    with path.open("rb") as file:
        return file_digest(file, "sha256").hexdigest()


def read_only(path: Path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)


def inspect_database(path: Path, role: str) -> dict:
    with closing(read_only(path)) as connection:
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed.")
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if not required_tables(role).issubset(tables):
            raise ValueError("The snapshot does not contain the required application tables.")
        counts = {table: connection.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0] for table in tables}
        return {"tables": counts, "user_version": connection.execute("PRAGMA user_version").fetchone()[0]}


def snapshot(sources: dict[str, Path], destination: Path) -> Path:
    if not sources or len(sources) > MAX_DATABASES:
        raise ValueError("Supply known paper, testnet and/or treasury database roles.")
    for role in sources: required_tables(role)
    paths = {role: path.resolve() for role, path in sources.items()}
    if len(set(paths.values())) != len(paths):
        raise ValueError("Database source files must be separate.")
    for role, path in paths.items():
        if not path.is_file():
            raise ValueError("A requested source database is missing; no empty database will be created.")
        inspect_database(path, role)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    files = []
    for role, source in paths.items():
        target = destination / f"{role}.sqlite3"
        with target.open("xb"):
            pass
        deadline = time.monotonic() + 30
        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise TimeoutError("SQLite snapshot exceeded its time budget.")
        with closing(read_only(source)) as origin, closing(sqlite3.connect(target)) as copy:
            origin.backup(copy, pages=256, progress=progress, sleep=0.1)
        facts = inspect_database(target, role)
        files.append({"role": role, "filename": target.name, "sha256": checksum(target),
            "bytes": target.stat().st_size, "captured_at": utcnow().isoformat(), **facts})
    manifest = {"schema": SCHEMA, "created_at": utcnow().isoformat(), "files": files,
        "limits": "Per-database snapshots, not an atomic cross-database snapshot. Hashes are integrity checks, not authenticated receipts. No secrets/configuration files are included."}
    manifest_path = destination / "manifest.json"
    with manifest_path.open("x", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)
        file.write("\n")
    verify(manifest_path)
    return manifest_path


def verify(manifest_path: Path) -> dict:
    if manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError("Backup manifest exceeds its size limit.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA or not 1 <= len(manifest.get("files", [])) <= MAX_DATABASES:
        raise ValueError("Unsupported or incomplete backup manifest.")
    seen = set()
    for item in manifest["files"]:
        role = item["role"]
        required_tables(role)
        if role in seen or item["filename"] != f"{role}.sqlite3":
            raise ValueError("Invalid or duplicate database role/filename in manifest.")
        seen.add(role)
        path = (manifest_path.parent / item["filename"]).resolve()
        if path.parent != manifest_path.parent.resolve() or not path.is_file():
            raise ValueError("Backup file must exist inside the manifest directory.")
        if checksum(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise ValueError("Backup checksum or size does not match the manifest.")
        facts = inspect_database(path, role)
        if facts["tables"] != item["tables"] or facts["user_version"] != item["user_version"]:
            raise ValueError("Backup schema or row counts do not match the manifest.")
    return manifest


def restore_drill(manifest_path: Path, destination: Path) -> dict:
    manifest = verify(manifest_path)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    for item in manifest["files"]:
        source = (manifest_path.parent / item["filename"]).resolve()
        target = destination / item["filename"]
        with source.open("rb") as origin, target.open("xb") as copy:
            shutil.copyfileobj(origin, copy)
        if checksum(target) != item["sha256"]:
            raise ValueError("Restored bytes do not match the verified snapshot.")
        if inspect_database(target, item["role"])["tables"] != item["tables"]:
            raise ValueError("Restored row counts do not match the snapshot.")
    report = {"schema": "lobster-restore-drill-v1", "completed_at": utcnow().isoformat(),
        "roles": [item["role"] for item in manifest["files"]], "integrity_verified": True,
        "live_database_replaced": False, "exchange_reconciled": False,
        "note": "Isolated file restore verified. Do not use an old signer nonce ledger for new submissions; reconcile exchange state before recovery activation."}
    with (destination / "restore-report.json").open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
        file.write("\n")
    return report
