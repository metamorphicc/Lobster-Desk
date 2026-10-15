import asyncio
from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from lobster.agents import DemoReviewer
from lobster.domain import PitchInput, Snapshot, utcnow
from lobster.pipeline import Pipeline
from lobster.store import Episode, Store


def market(source="demo", price="60000"):
    return Snapshot(source=source, price=price, timestamp=utcnow())


def submit(store, key="request-123"):
    return store.submit(PitchInput(author="Trader", direction="long", entry="60000", stop="59400", target="61200",
                        thesis="A breakout setup with a clear stop and target."), key)


def approve(store):
    ep = submit(store)
    pipeline = Pipeline(store, DemoReviewer())
    for _ in range(4):
        asyncio.run(pipeline.step(market()))
    assert store.get_episode(ep["id"])["status"] == "approved"
    return ep["id"]


def test_switching_feed_with_reserved_capital_is_blocked(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'test.db'}")
    store.bind_market_source("demo")
    approve(store)
    with pytest.raises(ValueError, match="MARKET_SOURCE"):
        store.bind_market_source("hyperliquid")


def test_switching_feed_with_open_position_is_blocked(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'test.db'}")
    id = approve(store)
    store.try_fill(id, market())
    with pytest.raises(ValueError, match="MARKET_SOURCE"):
        store.bind_market_source("hyperliquid")


def test_approved_demo_proposal_cannot_execute_on_live_feed(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'test.db'}")
    id = approve(store)
    assert store.try_fill(id, market("hyperliquid")) is None
    assert store.get_episode(id)["status"] == "rejected"


def test_execution_queue_survives_history_pagination(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'test.db'}")
    id = approve(store)
    for index in range(101):
        ep = submit(store, f"rejected-{index}")
        store.advance(ep["id"], "queued", "rejected", "risk", "Test rejection.")
    assert id not in {e["id"] for e in store.state(market())["episodes"]}
    assert id in {e["id"] for e in store.working_episodes()}
    assert store.try_fill(id, market())


def test_review_budget_is_persistent_and_fails_closed(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    store = Store(url)
    id = submit(store)["id"]
    pipeline = Pipeline(store, DemoReviewer(), daily_limit=1)
    asyncio.run(pipeline.step(market()))
    asyncio.run(pipeline.step(market()))
    restarted = Store(url)
    asyncio.run(Pipeline(restarted, DemoReviewer(), daily_limit=1).step(market()))
    assert restarted.get_episode(id)["status"] == "rejected"
    assert "budget" in restarted.get_episode(id)["reason"]
    assert len([e for e in restarted.events() if e["kind"] == "review_started"]) == 1


def test_interrupted_model_call_is_not_automatically_repeated(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'test.db'}")
    ep = submit(store)
    asyncio.run(Pipeline(store, DemoReviewer()).step(market()))
    store.reserve_review(ep["id"], "analyzing", "analyst", 100)
    asyncio.run(Pipeline(store, DemoReviewer()).step(market()))
    assert store.get_episode(ep["id"])["status"] == "rejected"
    assert "interrupted" in store.get_episode(ep["id"])["reason"]


def test_persisted_expiry_releases_reservation_after_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    store = Store(url)
    id = approve(store)
    with store.transaction() as session:
        row = session.get(Episode, id)
        row.payload = row.payload | {"expires_at": (utcnow() - timedelta(seconds=1)).isoformat()}
    store.engine.dispose()
    restarted = Store(url)
    assert restarted.try_fill(id, market()) is None
    assert restarted.get_episode(id)["status"] == "expired"
    assert not restarted.working_episodes()

