"""Serializable contracts. Money is Decimal; model prose never carries authority."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Candle(Contract):
    time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class Snapshot(Contract):
    source: Literal["demo", "hyperliquid", "hyperliquid-testnet"]
    symbol: Literal["BTC"] = "BTC"
    price: Decimal = Field(gt=0, allow_inf_nan=False)
    timestamp: datetime
    funding: Decimal = Decimal("0")
    open_interest: Decimal = Decimal("0")
    change_24h: Decimal = Decimal("0")
    candles: list[Candle] = Field(default_factory=list)

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Market timestamps must include a timezone")
        return value


class PitchInput(Contract):
    author: str = Field(min_length=2, max_length=32, pattern=r"^[\w .-]+$")
    symbol: Literal["BTC"] = "BTC"
    direction: Literal["long", "short"]
    entry: Decimal = Field(gt=0, le=10000000, max_digits=14, decimal_places=2, allow_inf_nan=False)
    stop: Decimal = Field(gt=0, le=10000000, max_digits=14, decimal_places=2, allow_inf_nan=False)
    target: Decimal = Field(gt=0, le=10000000, max_digits=14, decimal_places=2, allow_inf_nan=False)
    leverage: int = Field(default=1, ge=1, le=20)
    thesis: str = Field(min_length=20, max_length=1200)

    @field_validator("author", "thesis", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class Review(Contract):
    verdict: Literal["approve", "reject"]
    summary: str = Field(min_length=8, max_length=700)
    evidence: list[str] = Field(min_length=1, max_length=5)


class RiskPolicy(Contract):
    version: str = "btc-breakout-v1"
    risk_fraction: Decimal = Decimal("0.0025")
    daily_loss_fraction: Decimal = Decimal("0.01")
    drawdown_fraction: Decimal = Decimal("0.05")
    max_notional_fraction: Decimal = Decimal("0.25")
    min_notional: Decimal = Decimal("10")
    max_leverage: int = 2
    min_reward_risk: Decimal = Decimal("1.5")
    min_stop_fraction: Decimal = Decimal("0.001")
    max_stop_fraction: Decimal = Decimal("0.03")
    max_entry_distance: Decimal = Decimal("0.03")
    max_entry_slip: Decimal = Decimal("0.002")
    fee_rate: Decimal = Decimal("0.00045")
    slippage_rate: Decimal = Decimal("0.0002")
    quantity_step: Decimal = Decimal("0.00001")
    max_data_age_seconds: int = 15
    proposal_ttl_seconds: int = 900


class Capital(Contract):
    equity: Decimal
    available_cash: Decimal
    day_start_equity: Decimal
    high_water_equity: Decimal
    occupied: bool = False
    paused: bool = False


class RiskResult(Contract):
    approved: bool
    reasons: list[str]
    quantity: Decimal = Decimal("0")
    notional: Decimal = Decimal("0")
    margin: Decimal = Decimal("0")
    planned_loss: Decimal = Decimal("0")
    reward_risk: Decimal = Decimal("0")
    policy_version: str


class OperatorAction(Contract):
    action: Literal["pause", "resume", "close"]

