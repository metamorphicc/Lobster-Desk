from copy import deepcopy
from decimal import Decimal as D
import asyncio
import json

import httpx
import pytest

from lobster.research.contracts import Dataset, Hypotheses, Strategy, HOUR
from lobster.research.data import HistoryFeed, demo_history
from lobster.research.engine import backtest, evaluate, signal


def strategy(**changes):
    return Strategy(name="Test trend", hypothesis="An explicit synthetic trend hypothesis for offline tests.", family="trend", **changes)


def history():
    dataset = demo_history(480, 1700000000).model_dump(mode="json")
    for i, bar in enumerate(dataset["bars"]):
        price = D(60000) + i * 20
        bar.update(open=str(price), high=str(price + 30), low=str(price - 10), close=str(price + 20))
    for rate in dataset["funding"]: rate["rate"] = "0"
    return Dataset.model_validate(dataset)


@pytest.mark.parametrize("change", ["gap", "duplicate", "future", "ohlc", "funding", "wrong_funding", "nan"])
def test_history_is_complete_closed_and_exact(change):
    raw = history().model_dump(mode="json")
    if change == "gap": raw["bars"].pop(5)
    if change == "duplicate": raw["bars"][5] = raw["bars"][4]
    if change == "future": raw["as_of"] -= HOUR
    if change == "ohlc": raw["bars"][5]["low"] = "100000000"
    if change == "funding": raw["funding"].pop(5)
    if change == "wrong_funding": raw["funding"][5]["time"] += HOUR
    if change == "nan": raw["bars"][5]["close"] = "NaN"
    with pytest.raises(ValueError): Dataset.model_validate(raw)


def test_rules_cannot_contain_tools_code_or_duplicate_executable_parameters():
    with pytest.raises(ValueError): strategy(code="import os")
    with pytest.raises(ValueError): strategy(lookback=8, fast=9)
    with pytest.raises(ValueError): strategy(stop_fraction="0.5")
    item = strategy()
    with pytest.raises(ValueError): Hypotheses(regime="Some synthetic regime", candidates=[item, item.model_copy(update={"name": "Renamed"})])


def test_next_bar_execution_prefix_invariance_and_exact_net_pnl():
    dataset, rules = history(), strategy()
    first = backtest(dataset, rules, 100, 250)
    changed = dataset.model_dump(mode="json")
    for bar in changed["bars"][250:]: bar.update(open="10000", high="10100", low="9900", close="10000")
    second = backtest(Dataset.model_validate(changed), rules, 100, 250)
    assert first == second
    assert first["trades"] and first["trades"][0]["entry_time"] == dataset.bars[100].time
    assert sum((D(t["net_pnl"]) for t in first["trades"]), D(0)) == D(first["net_pnl"])
    assert D(first["fees"]) > 0
    assert signal(rules, dataset.bars[:24]) is None


def test_ambiguous_candle_stops_first_and_gap_fills_at_worse_open():
    raw = history().model_dump(mode="json")
    raw["bars"][100].update(high="70000", low="50000")
    result = backtest(Dataset.model_validate(raw), strategy(), 100, 102)
    assert result["trades"][0]["reason"] == "stop" and D(result["trades"][0]["net_pnl"]) < 0
    raw = history().model_dump(mode="json")
    raw["bars"][101].update(open="55000", high="55100", low="54900", close="55000")
    result = backtest(Dataset.model_validate(raw), strategy(), 100, 102)
    assert D(result["trades"][0]["exit"]) < D("55000")


def test_funding_is_a_signed_cost_and_historical_loss_halts_stay_latched():
    raw = history().model_dump(mode="json")
    for rate in raw["funding"]: rate["rate"] = "0.01"
    result = backtest(Dataset.model_validate(raw), strategy(), 100, 400)
    assert D(result["funding"]) < 0 and result["halted"]
    assert sum((D(t["net_pnl"]) for t in result["trades"]), D(0)) == D(result["net_pnl"])


def test_holdout_only_runs_for_validation_winner_and_failure_has_no_fallback(monkeypatch):
    import lobster.research.engine as engine
    dataset, calls = history(), []
    def fake(dataset, item, start, end, **kwargs):
        calls.append((item.family, start, end))
        # winner fails untouched history; runner-up must not get a second chance
        return {"trade_count": 20, "net_pnl": "-1" if start == 384 else "20" if item.family == "trend" else "10",
            "max_drawdown_fraction": "0.001", "halted": False}
    monkeypatch.setattr(engine, "backtest", fake)
    other = strategy().model_copy(update={"family": "breakout"})
    report = evaluate(dataset, [strategy(), other])
    assert report["selected_hash"] is None
    assert [item for item in calls if item[1] == 384] == [("trend", 384, 480)]


def test_history_transport_is_read_only_and_missing_page_cannot_be_zero_filled():
    dataset = history()
    calls = []
    def respond(request):
        assert request.url.host == "api.hyperliquid.xyz" and request.url.path == "/info"
        body = json.loads(request.content)
        calls.append(body)
        if body["type"] == "candleSnapshot":
            return httpx.Response(200, json=[{"s": "BTC", "i": "1h", "t": b.time * 1000,
                "T": (b.time + HOUR) * 1000 - 1, "o": str(b.open), "h": str(b.high), "l": str(b.low), "c": str(b.close), "v": str(b.volume)} for b in dataset.bars])
        assert body["type"] == "fundingHistory"
        return httpx.Response(200, json=[])
    async def run():
        from unittest.mock import patch
        from datetime import datetime, timezone
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch("lobster.research.data.utcnow", return_value=datetime.fromtimestamp(dataset.as_of, timezone.utc)):
                with pytest.raises(ValueError): await HistoryFeed(client, "hyperliquid", 480).fetch()
    asyncio.run(run())
    assert len(calls) == 2


def test_inclusive_funding_pages_deduplicate_millisecond_settlements():
    from unittest.mock import patch
    from datetime import datetime, timezone
    dataset = demo_history(600, 1700000000)
    # Real funding timestamps can be milliseconds after the hour.
    now = datetime.fromtimestamp(dataset.as_of + 60, timezone.utc)
    records = [{"coin": "BTC", "time": r.time * 1000 + 123, "fundingRate": str(r.rate)} for r in dataset.funding]
    starts = []
    def respond(request):
        body = json.loads(request.content)
        if body["type"] == "candleSnapshot":
            return httpx.Response(200, json=[{"s": "BTC", "i": "1h", "t": b.time * 1000,
                "T": (b.time + HOUR) * 1000 - 1, "o": str(b.open), "h": str(b.high), "l": str(b.low), "c": str(b.close), "v": str(b.volume)} for b in dataset.bars])
        starts.append(body["startTime"])
        return httpx.Response(200, json=[r for r in records if r["time"] >= body["startTime"]][:500])
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch("lobster.research.data.utcnow", return_value=now):
                result = await HistoryFeed(client, "hyperliquid", 600).fetch()
                assert len(result.funding) == 600
    asyncio.run(run())
    assert starts[1] == records[499]["time"]
