import asyncio
from datetime import timedelta

import httpx
import pytest

from lobster.domain import utcnow
from lobster.market import DemoFeed, HyperliquidFeed


def test_demo_is_labelled_and_has_ohlc_history():
    snapshot = asyncio.run(DemoFeed().fetch())
    assert snapshot.source == "demo"
    assert len(snapshot.candles) == 90
    assert all(c.low <= min(c.open, c.close) <= max(c.open, c.close) <= c.high for c in snapshot.candles)
    assert snapshot.timestamp > utcnow() - timedelta(seconds=2)


def test_live_feed_parses_btc_without_assuming_asset_index():
    requests = []
    def respond(request):
        import json
        kind = json.loads(request.content)["type"]
        requests.append(kind)
        if kind == "metaAndAssetCtxs":
            return httpx.Response(200, json=[{"universe": [{"name": "ETH"}, {"name": "BTC"}]},
                [{}, {"midPx": "70000", "markPx": "69999", "prevDayPx": "69000", "funding": "0.0001", "openInterest": "20000"}]])
        return httpx.Response(200, json=[{"t": 1700000000000, "o": "69900", "h": "70100", "l": "69800", "c": "70000"}])
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            feed = HyperliquidFeed(client)
            first = await feed.fetch()
            second = await feed.fetch()
            assert first.price == 70000 and second.source == "hyperliquid"
            assert len(second.candles) == 1
    asyncio.run(run())
    assert requests.count("candleSnapshot") == 1


def test_live_failure_never_falls_back_to_demo():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await HyperliquidFeed(client).fetch()
    asyncio.run(run())

