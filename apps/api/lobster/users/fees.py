"""Exact cost illustrations and unsigned, testnet-only builder consent plans."""

from datetime import datetime, timedelta
from decimal import Decimal as D
from typing import Literal

from hyperliquid.utils.signing import user_signed_payload
from pydantic import Field, field_validator

from ..domain import Contract, utcnow
from ..execution.contracts import TESTNET_URL, fingerprint
from .contracts import Address, UserTestnetSettings, fee_percent


class FeeQuoteInput(Contract):
    address: Address
    notional: D = Field(ge=D("0.01"), le=D("1000000"), max_digits=18, decimal_places=8, allow_inf_nan=False)

    @field_validator("notional", mode="before")
    @classmethod
    def decimal_input(cls, value):
        if isinstance(value, (bool, float)):
            raise ValueError("Supply notional as a decimal string.")
        return value


class ConsentInput(Contract):
    address: Address
    intent: Literal["approve", "revoke"]


def require_fresh(account: dict, address: str):
    observed = datetime.fromisoformat(account["observed_at"])
    if (account["address"] != address or account["network"] != "testnet" or account["stale"] is not False or observed.tzinfo is None
            or not -2 <= (utcnow() - observed).total_seconds() <= 15):
        raise ValueError("A fresh observation of the requested testnet account is required.")


def fee_quote(body: FeeQuoteInput, account: dict) -> dict:
    require_fresh(account, body.address)
    exchange = body.notional * D(account["reported_taker_rate"])
    builder = body.notional * D(account["builder_fee_tenths_bps"]) / 100000
    return {"network": "testnet", "address": body.address, "observed_at": account["observed_at"],
        "notional": str(body.notional), "reported_taker_rate": account["reported_taker_rate"],
        "estimated_exchange_fee": str(exchange), "hypothetical_builder_fee": str(builder),
        "estimated_total_if_applied": str(exchange + builder),
        "builder_address": account["builder_address"], "builder_fee_percent": account["builder_fee_percent"],
        "builder_approval_status": account["builder_approval_status"],
        "order_submission_enabled": False, "fee_collection_enabled": False,
        "assumptions": "Illustration for one BTC perpetual taker fill. Excludes funding and slippage; final exchange fees may differ. No charge or permission change occurs."}


def consent_plan(body: ConsentInput, settings: UserTestnetSettings, account: dict) -> dict:
    if not settings.builder_address:
        raise ValueError("Configure a public testnet builder address before preparing a consent plan.")
    if settings.builder_address == body.address:
        raise ValueError("Self-paid builder fees do not fund the product. Choose a separate user account.")
    require_fresh(account, body.address)
    if account["builder_address"] != settings.builder_address:
        raise ValueError("The builder observation does not match current configuration.")
    now = utcnow()
    maximum = settings.builder_fee_tenths_bps if body.intent == "approve" else 0
    if body.intent == "approve" and maximum == 0:
        raise ValueError("The configured builder rate is zero. Use a revocation preview instead.")
    action = {"type": "approveBuilderFee", "hyperliquidChain": "Testnet", "signatureChainId": "0x66eee",
        "maxFeeRate": fee_percent(maximum), "builder": settings.builder_address, "nonce": int(now.timestamp() * 1000)}
    typed = user_signed_payload("HyperliquidTransaction:ApproveBuilderFee", [
        {"name": "hyperliquidChain", "type": "string"}, {"name": "maxFeeRate", "type": "string"},
        {"name": "builder", "type": "address"}, {"name": "nonce", "type": "uint64"}], action)
    plan = {"schema": "lobster-builder-consent-preview-v1", "network": "testnet", "intent": body.intent,
        "expected_signer": body.address, "signer_authority": "User main wallet only; an API wallet cannot grant this approval.",
        "builder_address": settings.builder_address, "maximum_fee_tenths_bps": maximum,
        "maximum_fee_percent": fee_percent(maximum),
        "current_approved_fee_tenths_bps": account["approved_builder_fee_tenths_bps"],
        "created_at": now.isoformat(), "preview_valid_until": (now + timedelta(seconds=30)).isoformat(),
        "submission_endpoint": TESTNET_URL + "/exchange", "action": action, "typed_data": typed,
        "signed": False, "submitted": False, "fee_collection_enabled": False,
        "limitations": ["This plan changes no permission. Approval and revocation require explicit user main-wallet signing and exchange confirmation.",
            "The 30-second preview deadline is local metadata, not a cryptographic expiry of this action.",
            "Expected signer is application metadata; future submission must recover and verify the actual signer.",
            "Builder eligibility, actual approval/revocation and user execution remain unverified. Never submit this downloaded preview as an order."]}
    return plan | {"plan_hash": fingerprint(plan)}
