"""Public read-only data adapters. Neither adapter can submit an order."""

from datetime import datetime, timezone
from decimal import Decimal as D
import math
import time

import httpx

from .domain import Candle, Snapshot, utcnow


class DemoFeed:
    @staticmethod
    def price_at(timestamp: float) -> D:
        # Clock-derived and reproducible across restarts; visibly labelled synthetic.
        value = 68000 + 310 * math.sin(timestamp / 180) + 90 * math.sin(timestamp / 37)
        return D(str(round(value, 2)))

    async def fetch(self) -> Snapshot:
        now = utcnow()
        last_minute = int(now.timestamp()) // 60 * 60
        candles = []
        for index in range(90):
            ts = last_minute - (89 - index) * 60
            opening = self.price_at(ts)
            close = self.price_at(min(ts + 59, now.timestamp()))
            candles.append(Candle(time=ts, open=opening, high=max(opening, close) + D("12"),
                                  low=min(opening, close) - D("12"), close=close))
        return Snapshot(source="demo", price=self.price_at(now.timestamp()), timestamp=now,
                        funding="0.0000125", open_interest="24000", candles=candles,
                        change_24h=(self.price_at(now.timestamp()) / self.price_at(now.timestamp() - 86400) - 1) * 100)


class HyperliquidFeed:
    endpoint = "https://api.hyperliquid.xyz/info"

    def __init__(self, client: httpx.AsyncClient, *, testnet: bool = False):
        self.client = client
        self.endpoint = "https://api.hyperliquid-testnet.xyz/info" if testnet else self.endpoint
        self.source = "hyperliquid-testnet" if testnet else "hyperliquid"
        self.candles: list[Candle] = []
        self.candles_fetched_at = 0.0

    async def fetch(self) -> Snapshot:
        # Use request start time conservatively: network latency ages this observation.
        observed = utcnow()
        response = await self.client.post(self.endpoint, json={"type": "metaAndAssetCtxs"})
        response.raise_for_status()
        metadata, contexts = response.json()
        index = next(i for i, asset in enumerate(metadata["universe"]) if asset["name"] == "BTC")
        context = contexts[index]
        price = D(context["midPx"] or context["markPx"])
        previous = D(context["prevDayPx"])
        if time.monotonic() - self.candles_fetched_at >= 30 or not self.candles:
            end = int(observed.timestamp() * 1000)
            candles = await self.client.post(self.endpoint, json={"type": "candleSnapshot", "req": {
                "coin": "BTC", "interval": "1m", "startTime": end - 90 * 60000, "endTime": end}})
            candles.raise_for_status()
            self.candles = [Candle(time=int(c["t"]) // 1000, open=c["o"], high=c["h"], low=c["l"], close=c["c"])
                            for c in candles.json()][-90:]
            self.candles_fetched_at = time.monotonic()
        return Snapshot(source=self.source, price=price, timestamp=observed,
            funding=context["funding"], open_interest=context["openInterest"],
            change_24h=(price / previous - 1) * 100 if previous else D("0"), candles=self.candles)

