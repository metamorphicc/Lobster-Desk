"""Bounded local evidence inventories. File integrity never establishes acceptance."""
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field

from ..domain import Contract, utcnow
from ..execution.contracts import fingerprint

CASES = (
    "wallet-message-review", "wallet-rejection-and-account-change", "session-replay-and-expiry",
    "agent-approval-and-expiry", "builder-eligibility", "fee-approval-and-revocation",
    "private-plan-to-owned-entry", "actual-partial-fill-protection", "native-stop-execution",
    "restart-and-unknown-command", "user-and-nonce-isolation", "cashflow-and-funding-reconciliation",
    "builder-revenue-receipt", "post-revocation-reduction", "final-flat-and-owned-cleanup",
)


class Case(Contract):
    case: str
    status: Literal["not_run", "observed", "failed"] = "not_run"
    files: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=2000)


class AcceptanceRecord(Contract):
    schema_version: Literal["lobster-user-acceptance-v1"] = "lobster-user-acceptance-v1"
    network: Literal["testnet"] = "testnet"
    reviewer: str | None = Field(default=None, max_length=100)
    cases: list[Case] = Field(max_length=len(CASES))


def template():
    return AcceptanceRecord(cases=[Case(case=name) for name in CASES]).model_dump()


def inventory(record: AcceptanceRecord, root: Path):
    if {case.case for case in record.cases} != set(CASES) or len(record.cases) != len(CASES):
        raise ValueError("Every acceptance case is required exactly once.")
    root = root.resolve(strict=True)
    files, total = {}, 0
    for case in record.cases:
        if case.status == "observed" and (not case.files or not record.reviewer):
            raise ValueError("An observation requires evidence files and a named reviewer.")
        if case.status == "not_run" and case.files:
            raise ValueError("Unrun cases cannot claim evidence.")
        for name in case.files:
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
                raise ValueError("Evidence paths must be relative and contained in the evidence directory.")
            path = (root / name).resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in {".json", ".png", ".jpg", ".pdf", ".txt", ".md"} or path.name.startswith("."):
                raise ValueError("Unsupported evidence path. Never include keys, environment files or databases.")
            if name in files: continue
            size = path.stat().st_size
            total += size
            if size > 10_000_000 or total > 100_000_000:
                raise ValueError("Evidence inventory exceeds the size limit.")
            # Read a bounded amount even if a file changes concurrently.
            with path.open("rb") as source: content = source.read(10_000_001)
            if len(content) != size:
                raise ValueError("Evidence file changed while hashing.")
            files[name] = {"bytes": size, "sha256": sha256(content).hexdigest()}
    report = {"schema": "lobster-user-evidence-inventory-v1", "created_at": utcnow().isoformat(),
        "record": record.model_dump(), "files": files, "acceptance_verified": False,
        "execution_authorized": False, "exchange_writes_attempted": False,
        "limits": "Owner-supplied observations and file hashes only. No exchange authenticity, historical coverage, signature validity or case success is certified. Review privately before sharing."}
    return report | {"report_hash": fingerprint(report)}
