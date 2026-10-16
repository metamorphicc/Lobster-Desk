"""Fixed-host public history, never credentials/orders. Missing data fails closed."""
from decimal import Decimal as D

import httpx

from ..domain import utcnow
from ..market import DemoFeed
from .contracts import Bar, Dataset, Funding, HOUR


def demo_history(count: int = 1440, now: int | None = None) -> Dataset:
    end = (now or int(utcnow().timestamp())) // HOUR * HOUR
    bars = []
    for time in range(end - count * HOUR, end, HOUR):
        prices = [DemoFeed.price_at(time + minute * 60) for minute in range(60)]
        bars.append(Bar(time=time, open=str(prices[0]), close=str(prices[-1]),
            high=str(max(prices) + 12), low=str(min(prices) - 12), volume="100"))
    return Dataset(source="demo", as_of=end, bars=bars,
        funding=[Funding(time=b.time + HOUR, rate="0.0000125") for b in bars])


class HistoryFeed:
    def __init__(self, client: httpx.AsyncClient, source: str, count: int = 1440):
        self.client, self.source, self.count = client, source, count
        self.endpoint = "https://api.hyperliquid-testnet.xyz/info" if source == "hyperliquid-testnet" else "https://api.hyperliquid.xyz/info"

    async def fetch(self) -> Dataset:
        if self.source == "demo": return demo_history(self.count)
        observed = int(utcnow().timestamp())
        end = observed // HOUR * HOUR
        start = end - self.count * HOUR
        response = await self.client.post(self.endpoint, json={"type": "candleSnapshot", "req": {
            "coin": "BTC", "interval": "1h", "startTime": start * 1000, "endTime": end * 1000}})
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, list) or len(raw) > 4001: raise ValueError("Invalid candle response.")
        bars = []
        for row in raw:
            if row["s"] != "BTC" or row["i"] != "1h" or type(row["t"]) is not int or type(row["T"]) is not int:
                raise ValueError("Wrong history market, interval or time.")
            if row["t"] % (HOUR * 1000) or row["T"] != row["t"] + HOUR * 1000 - 1: raise ValueError("Invalid candle duration/alignment.")
            if row["t"] >= end * 1000: continue  # Ignore only the current unclosed bar.
            if row["t"] < start * 1000: raise ValueError("Unexpected candle outside requested history.")
            bars.append(Bar(time=row["t"] // 1000, open=row["o"], high=row["h"], low=row["l"], close=row["c"], volume=row["v"]))
        rates = {}
        cursor = (start + HOUR) * 1000
        for _ in range(12):
            response = await self.client.post(self.endpoint, json={"type": "fundingHistory", "coin": "BTC", "startTime": cursor, "endTime": observed * 1000})
            response.raise_for_status()
            page = response.json()
            if not isinstance(page, list) or len(page) > 500: raise ValueError("Invalid funding page.")
            if not page: break
            times = [r["time"] for r in page]
            if any(type(t) is not int or t < cursor or t > observed * 1000 for t in times) or times != sorted(times):
                raise ValueError("Invalid funding chronology.")
            for row in page:
                if row["coin"] != "BTC": raise ValueError("Invalid funding identity.")
                item = Funding(time=row["time"] // 1000, rate=row["fundingRate"])
                if item.time in rates and rates[item.time] != item: raise ValueError("Conflicting funding receipt.")
                rates[item.time] = item
            last = times[-1]
            if last >= end * 1000 or len(page) < 500: break
            if last <= cursor: raise ValueError("Funding pagination did not advance.")
            cursor = last  # Inclusive overlap is deduplicated, never last+1.
        if len(bars) != self.count: raise ValueError("Requested candle history is truncated.")
        return Dataset(source=self.source, as_of=observed, bars=bars, funding=sorted(rates.values(), key=lambda f: f.time))
