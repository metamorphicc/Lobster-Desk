from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from lobster.domain import utcnow
from lobster.funding import PaperFunding
from lobster.research.data import demo_history
from lobster.store import Position, Store
from test_store import ready, market


def opened(tmp_path, direction="long"):
    store = Store(f"sqlite:///{tmp_path / 'funding.db'}")
    store.bind_market_source("demo")
    funding = PaperFunding(store)
    funding.enable()
    identifier = ready(store)
    store.approve(identifier, market())
    position = store.try_fill(identifier, market())
    hour = int(utcnow().timestamp()) // 3600 * 3600
    with store.transaction() as session:
        row = session.get(Position, position["id"])
        row.payload = row.payload | {"opened_at": datetime.fromtimestamp(hour - 7201, timezone.utc).isoformat(),
            "funding_cursor": hour - 10800, "direction": direction}
    return store, funding, position, hour


@pytest.mark.parametrize("direction,sign", [("long", -1), ("short", 1)])
def test_signed_hourly_settlements_are_exact_and_restart_idempotent(tmp_path, direction, sign):
    store, funding, position, hour = opened(tmp_path, direction)
    dataset = demo_history(240)
    before = D(store.state(market())["account"]["cash"])
    delta = funding.apply(dataset)
    assert delta * sign > 0
    assert D(store.state(market())["account"]["cash"]) == before + delta
    restored = Store(str(store.engine.url))
    try:
        assert PaperFunding(restored).apply(dataset) == 0
        assert D(restored.state(market())["account"]["funding_net"]) == delta
    finally: restored.engine.dispose(); store.engine.dispose()


def test_closed_position_funding_recovers_and_updates_net_pnl_once(tmp_path):
    store, funding, _, _ = opened(tmp_path)
    store.mark(market("61200"))
    first = store.state(market())["positions"][0]
    assert first["status"] == "closed" and funding.pending()
    delta = funding.apply(demo_history(240))
    second = store.state(market())["positions"][0]
    assert D(second["net_pnl"]) == D(first["net_pnl"]) + delta
    assert not funding.pending()
    assert D(store.state(market())["account"]["cash"]) == 1000 + D(second["net_pnl"])
    store.engine.dispose()


def test_uncovered_history_rolls_back_every_settlement_and_blocks_new_entries(tmp_path):
    store, funding, position, hour = opened(tmp_path)
    with store.transaction() as session:
        row = session.get(Position, position["id"])
        row.payload = row.payload | {"funding_cursor": hour - 300 * 3600}
    before = store.state(market())["account"]["cash"]
    with pytest.raises(ValueError, match="cover"): funding.apply(demo_history(240))
    funding.fail()
    assert store.state(market())["account"]["cash"] == before
    with store.transaction() as session: assert store.capital(session, market()).paused
    # Risk protection remains callable even when funding service is unavailable.
    store.mark(market("59400"))
    assert store.state(market())["positions"][0]["status"] == "closed"
    store.engine.dispose()


def test_concurrent_settlement_readers_cannot_charge_twice(tmp_path):
    store, funding, position, hour = opened(tmp_path)
    data = demo_history(240)
    with ThreadPoolExecutor(4) as pool:
        deltas = list(pool.map(lambda _: funding.apply(data), range(4)))
    assert sum(value != 0 for value in deltas) == 1
    assert D(store.state(market())["account"]["funding_net"]) == sum(deltas)
    store.engine.dispose()


def test_legacy_positions_are_not_silently_relabelled_as_funding_complete(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'legacy.db'}")
    identifier = ready(store)
    store.approve(identifier, market())
    store.try_fill(identifier, market())
    funding = PaperFunding(store)
    funding.enable()
    assert store.state(market())["account"]["funding_legacy"]
    assert not funding.pending()
    store.engine.dispose()
