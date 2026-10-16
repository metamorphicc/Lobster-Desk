from contextlib import closing, contextmanager
from datetime import datetime
from decimal import Decimal as D, ROUND_DOWN
import json
from pathlib import Path
import sqlite3
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ..domain import Contract, utcnow
from ..execution.contracts import fingerprint
from ..ops.pilot import Money

KINDS = ("capital_in", "capital_out", "builder_receipt", "trading_profit", "trading_loss", "expense", "buyback_spend", "refund")
CREDITS = {"capital_in", "builder_receipt", "trading_profit"}


class EconomicPolicy(Contract):
    schema_version: Literal["lobster-economic-policy-v1"] = "lobster-economic-policy-v1"
    currency: Literal["USDC"] = "USDC"
    operating_reserve_target: Money | None = None
    liability_reserve: Money | None = None
    tax_reserve_fraction: Money | None = None
    buyback_fraction: Money | None = None
    jurisdiction: None = None
    token_role: None = None
    token_contract: None = None
    transfers_enabled: Literal[False] = False
    token_issuance_enabled: Literal[False] = False
    holder_payouts_enabled: Literal[False] = False

    @model_validator(mode="after")
    def fractions(self):
        if any(value is not None and value > 1 for value in (self.tax_reserve_fraction, self.buyback_fraction)):
            raise ValueError("Planning fractions cannot exceed one.")
        return self


class TreasuryEntry(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")
    receipt_ref: str = Field(min_length=8, max_length=200)
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: Literal["capital_in", "capital_out", "builder_receipt", "trading_profit", "trading_loss", "expense", "buyback_spend", "refund"]
    amount: Money
    currency: Literal["USDC"] = "USDC"
    occurred_at: datetime
    provenance: Literal["offline_fixture", "owner_supplied_unverified"]

    @model_validator(mode="after")
    def valid(self):
        if self.amount <= 0 or self.amount > D("1000000000000") or self.amount != self.amount.quantize(D("0.000001")):
            raise ValueError("Amounts must be positive exact USDC values with at most six decimal places.")
        if self.occurred_at.tzinfo is None or self.occurred_at > utcnow():
            raise ValueError("A non-future timestamp with timezone is required.")
        return self


class TreasuryBook:
    """Independent SQLite receipt book, append-only API and atomic duplicate checks.

    A hash chain detects accidental alteration; a DB administrator can rewrite it.
    Owner-supplied references are not cryptographic proof of settlement.
    """
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS treasury_receipts (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, receipt_ref TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)")

    @contextmanager
    def transaction(self):
        with closing(sqlite3.connect(self.path, timeout=20)) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def read(db):
        rows = [json.loads(row[0]) for row in db.execute("SELECT payload FROM treasury_receipts ORDER BY seq")]
        previous = "0" * 64
        for row in rows:
            digest = row["record_hash"]
            if row["previous_hash"] != previous or fingerprint({key: value for key, value in row.items() if key != "record_hash"}) != digest:
                raise ValueError("Treasury receipt chain integrity failed.")
            TreasuryEntry.model_validate(row["entry"])
            previous = digest
        if len({row["entry"]["provenance"] for row in rows}) > 1:
            raise ValueError("Fixture and owner-supplied books must remain separate.")
        return rows

    def append(self, entry: TreasuryEntry):
        entry = TreasuryEntry.model_validate(entry.model_dump(mode="json"))
        payload = entry.model_dump(mode="json")
        with self.transaction() as db:
            rows = self.read(db)
            for row in rows:
                if row["entry"]["id"] == entry.id or row["entry"]["receipt_ref"] == entry.receipt_ref:
                    if row["entry"] != payload: raise ValueError("Receipt identity conflicts with an existing entry.")
                    return row
            if rows and rows[0]["entry"]["provenance"] != entry.provenance:
                raise ValueError("Use a separate book for offline fixtures.")
            cash = sum((D(row["entry"]["amount"]) * (1 if row["entry"]["kind"] in CREDITS else -1) for row in rows), D("0"))
            if entry.kind not in CREDITS and entry.amount > cash:
                raise ValueError("The receipt would make recorded treasury cash negative. Reconcile missing funding first.")
            row = {"entry": payload, "recorded_at": utcnow().isoformat(), "previous_hash": rows[-1]["record_hash"] if rows else "0" * 64}
            row["record_hash"] = fingerprint(row)
            db.execute("INSERT INTO treasury_receipts (id,receipt_ref,payload) VALUES (?,?,?)", (entry.id, entry.receipt_ref, json.dumps(row)))
            return row

    def report(self, policy: EconomicPolicy):
        with self.transaction() as db: rows = self.read(db)
        totals = {kind: sum((D(row["entry"]["amount"]) for row in rows if row["entry"]["kind"] == kind), D("0")) for kind in KINDS}
        cash = sum((value * (1 if key in CREDITS else -1) for key, value in totals.items()), D("0"))
        net_earned = totals["builder_receipt"] + totals["trading_profit"] - totals["trading_loss"] - totals["expense"] - totals["refund"]
        unrecovered = max(D("0"), -net_earned)
        unspent_earned = max(D("0"), net_earned - totals["buyback_spend"])
        required = (policy.operating_reserve_target, policy.liability_reserve, policy.tax_reserve_fraction, policy.buyback_fraction)
        configured = all(value is not None for value in required)
        allocation = None
        if configured:
            tax = max(D("0"), net_earned) * policy.tax_reserve_fraction
            available = max(D("0"), cash - policy.operating_reserve_target - policy.liability_reserve - tax)
            allocation = (min(unspent_earned, available) * policy.buyback_fraction).quantize(D("0.000001"), rounding=ROUND_DOWN)
        report = {"schema": "lobster-treasury-report-v1", "created_at": utcnow().isoformat(), "currency": "USDC",
            "record_count": len(rows), "provenance": rows[0]["entry"]["provenance"] if rows else None,
            "receipts_authenticated": False, "chain_head": rows[-1]["record_hash"] if rows else None,
            "totals": {key: str(value) for key, value in totals.items()}, "recorded_cash": str(cash),
            "net_recorded_earnings": str(net_earned), "unrecovered_loss": str(unrecovered),
            "unspent_earnings": str(unspent_earned), "provisional_buyback_allocation": str(allocation) if allocation is not None else None,
            "policy": policy.model_dump(mode="json"), "policy_hash": fingerprint(policy.model_dump(mode="json")),
            "transfers_authorized": False, "holder_payouts_enabled": False, "production_metrics_verified": False,
            "blockers": ["Token role, jurisdiction and rights are undecided.", "Owner-supplied receipts require independent reconciliation."] + ([] if configured else ["Reserve, liability, tax and allocation parameters are unspecified."]),
            "note": "Accounting over this local book only. Capital injections and hypothetical/unclaimed builder fees are not earnings. Trading settlements must be net of fees/funding once. No chain/exchange receipt or token burn is certified."}
        return report | {"report_hash": fingerprint(report)}
