from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from lobster.domain import PitchInput, Snapshot, utcnow
from lobster.store import Account, Episode, Store


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'test.db'}")


def market(price="60000"):
    return Snapshot(source="demo", price=price, timestamp=utcnow())


def pitch():
    return PitchInput(author="Trader", direction="long", entry="60000", stop="59400", target="61200",
                      thesis="Breakout with volume confirmation and a defined stop.")


def ready(store, request_id="test"):
    ep = store.submit(pitch(), request_id)
    store.advance(ep["id"], "queued", "capital_check", "analyst", "Reviewed.", {
        "snapshot": market().model_dump(mode="json"),
        "reviews": {"analyst": {"verdict": "approve"}, "risk": {"verdict": "approve"}}})
    return ep["id"]


def test_pitch_idempotency_and_conflict(store):
    first = store.submit(pitch(), "same")
    assert store.submit(pitch(), "same")["id"] == first["id"]
    with pytest.raises(ValueError, match="different pitch"):
        store.submit(pitch().model_copy(update={"author": "Other"}), "same")


def test_two_approvals_required(store):
    ep = store.submit(pitch(), "test")
    store.advance(ep["id"], "queued", "capital_check", "analyst", "Incomplete review.")
    with pytest.raises(ValueError, match="Both"):
        store.approve(ep["id"], market())


def test_single_reservation_under_concurrent_approval(store):
    ids = [ready(store, str(i)) for i in range(2)]
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(lambda id: store.approve(id, market()), ids))
    assert sum(r["status"] == "approved" for r in results) == 1


def test_fill_is_idempotent_even_after_restart(store):
    id = ready(store)
    store.approve(id, market())
    first = store.try_fill(id, market())
    restarted = Store(str(store.engine.url))
    assert restarted.try_fill(id, market())["id"] == first["id"]
    assert len(restarted.state(market())["positions"]) == 1


def test_fees_and_close_accounting(store):
    id = ready(store)
    store.approve(id, market())
    opened = store.try_fill(id, market())
    assert D(store.state(market())["account"]["cash"]) == D("1000") - D(opened["entry_fee"])
    store.mark(market("61200"))
    state = store.state(market("61200"))
    closed = state["positions"][0]
    assert closed["status"] == "closed"
    assert closed["close_reason"] == "target"
    assert D(state["account"]["cash"]) == D("1000") + D(closed["net_pnl"])
    assert D(state["account"]["net_realized_pnl"]) == D(closed["net_pnl"])
    cash = state["account"]["cash"]
    store.mark(market("61200"))
    assert store.state(market())["account"]["cash"] == cash


def test_stale_data_does_not_fill(store):
    id = ready(store)
    store.approve(id, market())
    stale = market().model_copy(update={"timestamp": utcnow() - timedelta(minutes=1)})
    assert store.try_fill(id, stale) is None


def test_waits_for_breakout(store):
    id = ready(store)
    store.approve(id, market("59900"))
    assert store.try_fill(id, market("59900")) is None
    assert store.get_episode(id)["status"] == "approved"


def test_entry_gap_is_not_chased(store):
    id = ready(store)
    store.approve(id, market())
    assert store.try_fill(id, market("60500")) is None
    assert store.get_episode(id)["status"] == "expired"


def test_modified_approval_is_rejected(store):
    id = ready(store)
    store.approve(id, market())
    with store.transaction() as session:
        row = session.get(Episode, id)
        row.payload = row.payload | {"pitch": row.payload["pitch"] | {"target": "62000"}}
    assert store.try_fill(id, market()) is None


def test_gap_stop_uses_market_price_and_latches_loss_halt(store):
    id = ready(store)
    store.approve(id, market())
    store.try_fill(id, market())
    store.mark(market("50000"))
    state = store.state(market("50000"))
    assert state["positions"][0]["close_reason"] == "stop"
    assert D(state["positions"][0]["exit_price"]) < D("50000")
    assert state["account"]["halt_reason"]
    with pytest.raises(ValueError, match="latched"):
        store.operate("resume", market())


def test_operator_pause_still_allows_stop_protection(store):
    id = ready(store)
    store.approve(id, market())
    store.try_fill(id, market())
    store.operate("pause", market())
    store.mark(market("59400"))
    assert store.state(market())["positions"][0]["status"] == "closed"


def test_failed_transaction_rolls_back_account_and_events(store):
    before = store.events()
    with pytest.raises(RuntimeError):
        with store.transaction() as session:
            row = session.get(Account, 1)
            row.payload = row.payload | {"cash": "0"}
            store.event(session, "system", "test", "Must roll back.")
            raise RuntimeError("Interrupted")
    assert store.events() == before
    assert store.state(market())["account"]["cash"] == "1000"

