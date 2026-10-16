"""Receipt links and claimed supply-change arithmetic; no token/chain implementation."""
import json
from decimal import Decimal as D
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ..domain import Contract, utcnow
from ..execution.contracts import fingerprint
from ..ops.pilot import Money
from .book import TreasuryBook

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")]
Atomic = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,77})$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def atomic(value):
    number = int(value)
    if number >= 2**256: raise ValueError("Atomic quantity exceeds the local receipt format.")
    return number


class Purchase(Contract):
    id: Identifier
    spending_entry_id: Identifier
    network: str = Field(min_length=2, max_length=64)
    asset: str = Field(min_length=2, max_length=128)
    settlement_ref: str = Field(min_length=8, max_length=200)
    evidence_sha256: Digest
    cost_usdc: Money
    quantity_atomic: Atomic
    token_decimals: int = Field(ge=0, le=30, strict=True)

    @model_validator(mode="after")
    def positive(self):
        if atomic(self.quantity_atomic) <= 0 or self.cost_usdc <= 0: raise ValueError("Purchase values must be positive.")
        return self


class BurnObservation(Contract):
    id: Identifier
    purchase_id: Identifier
    network: str = Field(min_length=2, max_length=64)
    asset: str = Field(min_length=2, max_length=128)
    event_ref: str = Field(min_length=8, max_length=200)
    evidence_sha256: Digest
    mechanism: Literal["supply_reduction", "sink_transfer"]
    quantity_atomic: Atomic
    supply_before_atomic: Atomic | None = None
    supply_after_atomic: Atomic | None = None

    @model_validator(mode="after")
    def arithmetic(self):
        quantity = atomic(self.quantity_atomic)
        if quantity <= 0: raise ValueError("A disposal observation requires a positive quantity.")
        if self.mechanism == "supply_reduction":
            if self.supply_before_atomic is None or self.supply_after_atomic is None:
                raise ValueError("A claimed supply reduction requires exact before/after observations.")
            if atomic(self.supply_before_atomic) - atomic(self.supply_after_atomic) != quantity:
                raise ValueError("Claimed supply reduction does not match the stated quantity.")
        elif self.supply_before_atomic is not None or self.supply_after_atomic is not None:
            raise ValueError("A sink transfer is not a supply reduction.")
        return self


class BuybackBook:
    def __init__(self, treasury: TreasuryBook):
        self.treasury = treasury
        with treasury.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS buyback_purchases (id TEXT PRIMARY KEY, spending_id TEXT UNIQUE NOT NULL, settlement_ref TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS buyback_disposals (id TEXT PRIMARY KEY, purchase_id TEXT NOT NULL, event_ref TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)")

    @staticmethod
    def rows(db, table):
        if table not in {"buyback_purchases", "buyback_disposals"}: raise ValueError()
        rows = [json.loads(row[0]) for row in db.execute("SELECT payload FROM " + table + " ORDER BY id")]
        for row in rows:
            if fingerprint({key: value for key, value in row.items() if key != "record_hash"}) != row["record_hash"]:
                raise ValueError("Buyback observation integrity failed.")
        return rows

    def purchase(self, purchase: Purchase):
        purchase = Purchase.model_validate(purchase.model_dump(mode="json"))
        value = purchase.model_dump(mode="json")
        with self.treasury.transaction() as db:
            spending = next((row for row in self.treasury.read(db) if row["entry"]["id"] == purchase.spending_entry_id), None)
            if not spending or spending["entry"]["kind"] != "buyback_spend" or purchase.cost_usdc != D(spending["entry"]["amount"]):
                raise ValueError("An exact existing USDC buyback-spend receipt is required.")
            for row in self.rows(db, "buyback_purchases"):
                item = row["observation"]
                if item["id"] == purchase.id or item["spending_entry_id"] == purchase.spending_entry_id or item["settlement_ref"] == purchase.settlement_ref:
                    if item != value: raise ValueError("Purchase identity or spending receipt was already used.")
                    return row
            row = {"observation": value, "spending_record_hash": spending["record_hash"], "recorded_at": utcnow().isoformat()}
            row["record_hash"] = fingerprint(row)
            db.execute("INSERT INTO buyback_purchases VALUES (?,?,?,?)", (purchase.id, purchase.spending_entry_id, purchase.settlement_ref, json.dumps(row)))
            return row

    def disposal(self, burn: BurnObservation):
        burn = BurnObservation.model_validate(burn.model_dump(mode="json"))
        value = burn.model_dump(mode="json")
        with self.treasury.transaction() as db:
            purchase = next((row for row in self.rows(db, "buyback_purchases") if row["observation"]["id"] == burn.purchase_id), None)
            if not purchase or any(purchase["observation"][key] != value[key] for key in ("network", "asset")):
                raise ValueError("Disposal network/asset must match an existing purchase.")
            consumed = 0
            for row in self.rows(db, "buyback_disposals"):
                item = row["observation"]
                if item["id"] == burn.id or item["event_ref"] == burn.event_ref:
                    if item != value: raise ValueError("Disposal identity or event was already used.")
                    return row
                if item["purchase_id"] == burn.purchase_id: consumed += atomic(item["quantity_atomic"])
            if consumed + atomic(burn.quantity_atomic) > atomic(purchase["observation"]["quantity_atomic"]):
                raise ValueError("Claimed disposals exceed the purchased token lot.")
            row = {"observation": value, "purchase_hash": purchase["record_hash"], "recorded_at": utcnow().isoformat()}
            row["record_hash"] = fingerprint(row)
            db.execute("INSERT INTO buyback_disposals VALUES (?,?,?,?)", (burn.id, burn.purchase_id, burn.event_ref, json.dumps(row)))
            return row

    def report(self):
        with self.treasury.transaction() as db:
            receipts = self.treasury.read(db)
            purchases, disposals = self.rows(db, "buyback_purchases"), self.rows(db, "buyback_disposals")
        lots = []
        for row in purchases:
            item = row["observation"]
            Purchase.model_validate(item)
            spending = next((value for value in receipts if value["record_hash"] == row["spending_record_hash"]), None)
            if not spending or spending["entry"]["id"] != item["spending_entry_id"] or spending["entry"]["kind"] != "buyback_spend" or D(spending["entry"]["amount"]) != D(item["cost_usdc"]):
                raise ValueError("Linked treasury receipt integrity failed.")
            linked = [value for value in disposals if value["observation"]["purchase_id"] == item["id"]]
            for value in linked:
                burn = BurnObservation.model_validate(value["observation"])
                if value["purchase_hash"] != row["record_hash"] or burn.network != item["network"] or burn.asset != item["asset"]:
                    raise ValueError("Linked disposal integrity failed.")
            reduced = sum(atomic(value["observation"]["quantity_atomic"]) for value in linked if value["observation"]["mechanism"] == "supply_reduction")
            sink = sum(atomic(value["observation"]["quantity_atomic"]) for value in linked if value["observation"]["mechanism"] == "sink_transfer")
            remaining = atomic(item["quantity_atomic"]) - reduced - sink
            if remaining < 0: raise ValueError("Disposal quantities exceed the purchased lot.")
            lots.append({"purchase": item, "purchase_record_hash": row["record_hash"],
                "claimed_supply_reduction_atomic": str(reduced), "sink_transfer_atomic": str(sink), "unallocated_atomic": str(remaining),
                "disposals": [value["observation"] for value in linked]})
        if any(not any(row["observation"]["id"] == value["observation"]["purchase_id"] for row in purchases) for value in disposals):
            raise ValueError("A disposal has no corresponding purchase.")
        linked_ids = {row["observation"]["spending_entry_id"] for row in purchases}
        report = {"schema": "lobster-buyback-report-v1", "created_at": utcnow().isoformat(), "lots": lots,
            "unlinked_spending_receipts": [row["entry"]["id"] for row in receipts if row["entry"]["kind"] == "buyback_spend" and row["entry"]["id"] not in linked_ids],
            "provenance": receipts[0]["entry"]["provenance"] if receipts else None,
            "receipts_authenticated": False, "burns_verified": False, "transfers_authorized": False,
            "token_contract_selected": False, "holder_entitlement": None,
            "note": "Owner-supplied links and quantity arithmetic only. A purchase is not a burn; a sink transfer is not total-supply reduction. No chain authenticity, finality, token semantics or circulating-supply change is certified. Review privately before publication."}
        return report | {"report_hash": fingerprint(report)}


