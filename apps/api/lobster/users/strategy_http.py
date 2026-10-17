"""Verified strategy submissions, private accruals and observed payout receipts."""
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
import re
from typing import Literal

from fastapi import Header, HTTPException, Request
from pydantic import Field
from sqlalchemy.orm import Session

from ..domain import Contract, PitchInput, utcnow
from ..economics.book import TreasuryBook, TreasuryEntry
from ..economics.sharing import author_balances
from ..execution.contracts import fingerprint
from ..ops.catalog import JournalLocation
from ..ops.pilot import Money
from .auth import AuthError
from .contracts import Address
from .strategies import UserStrategies


class PayoutReceipt(Contract):
    journal_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    owner: Address
    transfer_hash: str = Field(pattern=r"^0x[a-f0-9]{64}$")
    timestamp_ms: int = Field(ge=0, strict=True)
    amount: Money = Field(gt=0, le=1000000, decimal_places=6)


async def record_payout(store, book, service, body):
    if service.network != "mainnet" or body.timestamp_ms > int(utcnow().timestamp()*1000) - 1:
        raise ValueError("A completed mainnet transfer observation is required.")
    with Session(store.engine) as db:
        row = db.get(JournalLocation, body.journal_id)
        item = row.payload if row else None
    if (not item or item["role"] != "project" or item["network"] != "mainnet"
            or fingerprint({k: item[k] for k in ("network", "account", "signer", "path", "role")}) != body.journal_id
            or item["account"] == body.owner):
        raise ValueError("Registered mainnet project source and separate strategy author required.")
    receipts = []
    for address, expected in [(item["account"], -body.amount), (body.owner, body.amount)]:
        history = await service.capital_history(address, max(0, body.timestamp_ms-1), body.timestamp_ms+1)
        matches = [r for r in history if r["hash"] == body.transfer_hash]
        if (len(matches) != 1 or matches[0]["time"] != body.timestamp_ms or matches[0]["kind"] != "internalTransfer"
                or matches[0]["stream"] != "ledger" or D(matches[0]["cashflow"]) != expected):
            raise ValueError("Exact matching source debit and author credit are not observed.")
        receipts += matches
    value = TreasuryEntry(id=fingerprint({"mainnet-author-transfer": body.transfer_hash}),
        receipt_ref="hl-author-payout:"+body.transfer_hash, evidence_sha256=fingerprint({"receipts": receipts}),
        kind="author_payout", amount=str(body.amount), beneficiary=body.owner,
        occurred_at=datetime.fromtimestamp(body.timestamp_ms/1000, timezone.utc), provenance="owner_supplied_unverified")
    return book.append(value)


def install(app, config, require_operator):
    def identity(request, network, authorization):
        auth = request.app.state.mainnet_auth if network == "mainnet" else request.app.state.user_auth
        try: return auth.require(authorization)["address"]
        except AuthError as error: raise HTTPException(error.status, error.message) from None

    @app.post("/api/v1/users/{network}/strategy-pitches", status_code=201)
    def strategy_pitch(network: Literal["testnet", "mainnet"], body: PitchInput, request: Request,
            authorization: str | None = Header(default=None), idempotency_key: str = Header(alias="Idempotency-Key")):
        owner = identity(request, network, authorization)
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", idempotency_key): raise HTTPException(422, "Bounded request identity required.")
        store = request.app.state.runtime.store
        peer = request.client.host if request.client else "local"
        if retry := store.consume_pitch_request(peer): raise HTTPException(429, "Pitch limit reached.", headers={"Retry-After": str(retry)})
        try: return UserStrategies(store, network).submit(owner, body, idempotency_key)
        except ValueError as error: raise HTTPException(409, str(error)) from None

    @app.get("/api/v1/users/{network}/strategy-earnings")
    def earnings(network: Literal["testnet", "mainnet"], request: Request, authorization: str | None = Header(default=None)):
        owner = identity(request, network, authorization)
        strategies = UserStrategies(request.app.state.runtime.store, network).list(owner)
        balance = None
        if network == "mainnet":
            book = TreasuryBook(Path(config.treasury_path))
            with book.transaction() as db: balance = author_balances(book.read(db)).get(owner)
        return {"network": network, "strategies": strategies, "balance": balance,
            "payout_submission_enabled": False, "note": "Only verified, realized project trades accrue author shares. Testnet/paper results are not payable. Accrued shares and observed payments are separate."}

    @app.post("/api/v1/operator/strategy-payout-receipt")
    async def payout_receipt(body: PayoutReceipt, request: Request, authorization: str | None = Header(default=None)):
        require_operator(authorization)
        try:
            row = await record_payout(request.app.state.runtime.store, TreasuryBook(Path(config.treasury_path)), request.app.state.mainnet_users, body)
            return {"receipt_id": row["entry"]["id"], "recorded": True, "transfer_submitted": False}
        except ValueError as error: raise HTTPException(409, str(error)) from None
        except Exception: raise HTTPException(502, "Payout transfer observations are unavailable. No payment was submitted.") from None
