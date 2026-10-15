from datetime import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from hashlib import sha256
import json
from typing import Literal

from pydantic import Field, model_validator

from ..domain import Capital, Contract, PitchInput, Review, RiskPolicy, Snapshot
from ..risk import assess
from ..store import digest

TESTNET_URL = "https://api.hyperliquid-testnet.xyz"


def fingerprint(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def wire(value: Decimal) -> str:
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")


class BtcRules(Contract):
    symbol: Literal["BTC"] = "BTC"
    asset_id: int = Field(ge=0, lt=10000)
    size_decimals: int = Field(ge=0, le=6)
    max_leverage: int = Field(ge=1)

    @property
    def quantity_step(self) -> Decimal:
        return Decimal(1).scaleb(-self.size_decimals)

    def price(self, value: Decimal, upward: bool = False) -> Decimal:
        if not value.is_finite() or value <= 0:
            raise ValueError("Price must be finite and positive.")
        # Perps permit 5 significant figures and at most 6-szDecimals decimals.
        exponent = max(value.adjusted() - 4, -(6 - self.size_decimals))
        return value.quantize(Decimal(1).scaleb(exponent), rounding=ROUND_UP if upward else ROUND_DOWN)


class ExchangeAccount(Contract):
    address: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    network: Literal["testnet"] = "testnet"
    observed_at: datetime
    equity: Decimal = Field(ge=0, allow_inf_nan=False)
    withdrawable: Decimal = Field(ge=0, allow_inf_nan=False)
    btc_size: Decimal = Field(default=Decimal("0"), allow_inf_nan=False)
    other_positions: bool = False
    open_order_count: int = Field(ge=0)
    btc_leverage: int | None = None
    btc_is_cross: bool | None = None


class ReviewedSetup(Contract):
    episode_id: str = Field(min_length=1, max_length=64)
    pitch: PitchInput
    analyst: Review
    risk: Review
    expires_at: datetime
    approved_quantity: Decimal = Field(gt=0, allow_inf_nan=False)
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str
    network: Literal["testnet"] = "testnet"

    @model_validator(mode="after")
    def eligible(self):
        if self.analyst.verdict != "approve" or self.risk.verdict != "approve":
            raise ValueError("Both reviewers must approve the setup.")
        if self.expires_at.tzinfo is None:
            raise ValueError("Approval expiry requires a timezone.")
        return self

    @classmethod
    def from_episode(cls, episode: dict, policy: RiskPolicy):
        if episode.get("status") != "approved" or episode.get("approval_hash") != digest(episode):
            raise ValueError("The episode has no current, bound capital approval.")
        if episode.get("snapshot", {}).get("source") != "hyperliquid-testnet":
            raise ValueError("Only an episode reviewed against testnet data can authorize testnet execution.")
        if episode.get("policy") != policy.model_dump(mode="json") or not episode.get("risk", {}).get("approved"):
            raise ValueError("Risk approval does not match the current policy.")
        # Metadata is audit information, not part of the model's authority.
        reviews = {role: {key: value for key, value in episode["reviews"][role].items() if key != "metadata"}
                   for role in ("analyst", "risk")}
        return cls(episode_id=episode["id"], pitch=episode["pitch"], analyst=reviews["analyst"], risk=reviews["risk"],
            expires_at=episode["expires_at"], approved_quantity=episode["risk"]["quantity"],
            approval_hash=episode["approval_hash"], policy_version=policy.version)


class OrderSpec(Contract):
    symbol: Literal["BTC"] = "BTC"
    asset_id: int = Field(ge=0, lt=10000)
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0, allow_inf_nan=False)
    price: Decimal = Field(gt=0, allow_inf_nan=False)
    cloid: str = Field(pattern=r"^0x[0-9a-f]{32}$")
    kind: Literal["entry", "stop", "target", "close"]
    trigger_price: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def trigger_shape(self):
        if (self.kind in {"stop", "target"}) != (self.trigger_price is not None):
            raise ValueError("Only protective orders have a trigger price.")
        return self

    def to_wire(self) -> dict:
        order_type = ({"trigger": {"isMarket": True, "triggerPx": wire(self.trigger_price),
                                   "tpsl": "sl" if self.kind == "stop" else "tp"}}
                      if self.trigger_price is not None else {"limit": {"tif": "Ioc"}})
        return {"a": self.asset_id, "b": self.side == "buy", "p": wire(self.price),
                "s": wire(self.quantity), "r": self.kind != "entry", "t": order_type, "c": self.cloid}


def cloid(trade_id: str, kind: str, revision: int = 0) -> str:
    return "0x" + sha256(f"lobster:testnet:{trade_id}:{kind}:{revision}".encode()).hexdigest()[:32]


def size_entry(setup: ReviewedSetup, market: Snapshot, account: ExchangeAccount,
               capital: Capital, rules: BtcRules, policy: RiskPolicy, now: datetime,
               max_notional: Decimal) -> OrderSpec:
    if market.source != "hyperliquid-testnet" or account.network != "testnet":
        raise ValueError("Testnet market and account observations are required.")
    if not -2 <= (now - account.observed_at).total_seconds() <= policy.max_data_age_seconds:
        raise ValueError("Account observation is stale.")
    if setup.policy_version != policy.version:
        raise ValueError("The risk policy changed after review.")
    if account.btc_size or account.other_positions or account.open_order_count:
        raise ValueError("Use a dedicated account with no existing positions or orders.")
    pitch = setup.pitch
    triggered = market.price >= pitch.entry if pitch.direction == "long" else market.price <= pitch.entry
    if not triggered:
        raise ValueError("The entry trigger has not been reached.")
    if abs(market.price - pitch.entry) / pitch.entry > policy.max_entry_slip:
        raise ValueError("The price moved beyond the approved entry deviation.")
    if pitch.leverage > rules.max_leverage:
        raise ValueError("The exchange market does not permit this leverage.")
    buy = pitch.direction == "long"
    # Size against the worst permitted fill, rather than an optimistic midpoint.
    price = rules.price(market.price * (1 + policy.max_entry_slip if buy else 1 - policy.max_entry_slip), upward=not buy)
    result = assess(pitch.model_copy(update={"entry": price}), market, capital,
                    policy.model_copy(update={"quantity_step": rules.quantity_step}), now, setup.expires_at)
    if not result.approved:
        raise ValueError(" ".join(result.reasons))
    quantity = min(result.quantity, setup.approved_quantity, max_notional / price)
    quantity = (quantity / rules.quantity_step).to_integral_value(rounding=ROUND_DOWN) * rules.quantity_step
    if quantity * price < policy.min_notional:
        raise ValueError("Final testnet order is below the minimum notional.")
    return OrderSpec(asset_id=rules.asset_id, side="buy" if buy else "sell", quantity=quantity,
                     price=price, cloid=cloid(setup.episode_id, "entry"), kind="entry")

