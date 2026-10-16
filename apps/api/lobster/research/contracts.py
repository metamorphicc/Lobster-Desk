from decimal import Decimal as D
from typing import Literal

from pydantic import Field, model_validator

from ..domain import Contract
from ..ops.pilot import Money
from ..execution.contracts import fingerprint

HOUR = 3600


class Bar(Contract):
    time: int = Field(strict=True, ge=0)
    open: Money
    high: Money
    low: Money
    close: Money
    volume: Money

    @model_validator(mode="after")
    def valid(self):
        if self.time % HOUR or self.low <= 0 or not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("Closed hourly OHLC bars must be aligned, positive and coherent.")
        return self


class Funding(Contract):
    time: int = Field(strict=True, ge=0)
    rate: D = Field(ge=D("-0.01"), le=D("0.01"), allow_inf_nan=False)


class Dataset(Contract):
    source: Literal["demo", "hyperliquid", "hyperliquid-testnet"]
    symbol: Literal["BTC"] = "BTC"
    interval: Literal["1h"] = "1h"
    as_of: int = Field(strict=True)
    bars: list[Bar] = Field(min_length=240, max_length=4000)
    funding: list[Funding] = Field(min_length=240, max_length=4000)

    @model_validator(mode="after")
    def complete(self):
        expected = list(range(self.bars[0].time, self.bars[0].time + len(self.bars) * HOUR, HOUR))
        if [b.time for b in self.bars] != expected or self.bars[-1].time + HOUR > self.as_of:
            raise ValueError("History has missing, unordered, duplicate or unclosed candles.")
        # Exactly one real rate per hourly settlement bucket. Missing historical
        # funding never becomes a fabricated zero; no extrapolation of today's rate.
        buckets = [f.time // HOUR * HOUR for f in self.funding]
        if buckets != [time + HOUR for time in expected] or any(f.time > self.as_of for f in self.funding):
            raise ValueError("Historical hourly funding coverage is incomplete or conflicting.")
        return self

    @property
    def digest(self):
        return fingerprint(self.model_dump(mode="json", exclude={"as_of"}))


class Strategy(Contract):
    name: str = Field(min_length=3, max_length=64)
    hypothesis: str = Field(min_length=20, max_length=600)
    family: Literal["trend", "breakout", "mean_reversion"]
    lookback: int = Field(default=24, ge=8, le=96, strict=True)
    fast: int = Field(default=6, ge=2, le=48, strict=True)
    threshold_bps: int = Field(default=20, ge=0, le=200, strict=True)
    stop_fraction: D = Field(default=D("0.005"), ge=D("0.003"), le=D("0.02"), allow_inf_nan=False)
    reward_risk: D = Field(default=D("2"), ge=D("1.8"), le=D("4"), allow_inf_nan=False)
    max_holding_bars: int = Field(default=12, ge=1, le=48, strict=True)

    @model_validator(mode="after")
    def bounded(self):
        if self.fast >= self.lookback: raise ValueError("Fast window must be shorter than the lookback.")
        return self

    @property
    def digest(self):
        # Names/prose do not create a new executable strategy.
        return fingerprint(self.model_dump(mode="json", exclude={"name", "hypothesis"}))


class Hypotheses(Contract):
    regime: str = Field(min_length=10, max_length=500)
    candidates: list[Strategy] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique(self):
        if len({s.digest for s in self.candidates}) != len(self.candidates):
            raise ValueError("Duplicate rules do not count as independent candidates.")
        return self
