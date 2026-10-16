"""Local source packaging. No deployment, credentials or activation switch."""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import subprocess
from typing import Literal

from ..domain import Contract, utcnow
from ..execution.contracts import fingerprint


class ReleaseConfig(Contract):
    schema_version: Literal["lobster-local-release-v1"] = "lobster-local-release-v1"
    mode: Literal["local-paper"] = "local-paper"
    api_host: Literal["127.0.0.1"] = "127.0.0.1"
    api_port: Literal[8000] = 8000
    web_origin: Literal["http://127.0.0.1:3000"] = "http://127.0.0.1:3000"
    worker_instances: Literal[1] = 1
    deployment_enabled: Literal[False] = False
    exchange_submission_enabled: Literal[False] = False
    token_operations_enabled: Literal[False] = False
    jurisdiction: None = None
    public_domain: None = None
    hosting: None = None
    token_role: None = None


def safe_source(name):
    path = PurePosixPath(name)
    return (not path.is_absolute() and ".." not in path.parts and "\\" not in name
        and not any(part in {"data", "artifacts", ".venv", "node_modules", ".next", ".git"} for part in path.parts)
        and (not path.name.startswith(".env") or path.name in {".env.example", ".env.testnet-signer.example"})
        and path.suffix.lower() not in {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12"})


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return result.stdout


def bundle(root: Path, destination: Path, config: ReleaseConfig):
    root = root.resolve()
    if git(root, "status", "--porcelain", "--untracked-files=normal").strip():
        raise ValueError("Commit the completed substage before packaging; the worktree must be clean.")
    branch = git(root, "branch", "--show-current").decode().strip()
    if not branch.startswith("codex/"): raise ValueError("Package a local codex/ branch.")
    revision = git(root, "rev-parse", "HEAD").decode().strip()
    names = git(root, "ls-tree", "-rz", "--name-only", revision).decode().strip("\0").split("\0")
    if not names or not all(safe_source(name) for name in names):
        raise ValueError("Tracked source includes a forbidden runtime/secret-material path.")
    archive = git(root, "archive", "--format=zip", revision)
    if len(archive) > 100_000_000: raise ValueError("Source archive exceeds the local packaging limit.")
    locks = {name: sha256(git(root, "show", revision + ":" + name)).hexdigest()
        for name in ("package-lock.json", "apps/api/requirements.lock")}
    report = {"schema": "lobster-source-bundle-v1", "created_at": utcnow().isoformat(), "revision": revision,
        "branch": branch, "files": len(names), "archive": "source.zip", "archive_sha256": sha256(archive).hexdigest(),
        "lock_sha256": locks, "config": config.model_dump(), "production_verified": False,
        "limits": "Committed source only. No installed runtime, build artifact, database, key, off-machine backup, independent review or deployment is included. SHA256 does not authenticate provenance."}
    report["manifest_hash"] = fingerprint(report)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "source.zip").write_bytes(archive)
    (destination / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
