import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D

import pytest

from lobster.execution.broker import TestnetBroker
from lobster.execution.ledger import ExecutionLedger


def run(awaitable):
    return asyncio.run(awaitable)


def test_staging_is_read_only_and_unarmed_dispatch_fails(execution_rig):
    broker, exchange, setup, _ = execution_rig
    run(broker.stage(setup))
    assert exchange.writes == []
    broker.armed = False
    with pytest.raises(ValueError, match="armed"):
        run(broker.dispatch(setup.episode_id))
    assert exchange.writes == []


def test_partial_fill_is_protected_at_actual_size(execution_rig):
    broker, exchange, setup, _ = execution_rig
    run(broker.stage(setup))
    result = run(broker.dispatch(setup.episode_id))
    assert result["status"] == "protected"
    assert D(result["protected_quantity"]) == exchange.partial
    assert D(result["entry"]["quantity"]) > exchange.partial
    for kind, action in exchange.writes:
        if kind in {"stop", "target"}:
            assert D(action["orders"][0]["s"]) == exchange.partial
            assert action["orders"][0]["r"] is True
    assert [kind for kind, _ in exchange.writes] == ["leverage", "entry", "stop", "target"]


def test_timeout_after_entry_reconciles_without_duplicate(execution_rig):
    broker, exchange, setup, _ = execution_rig
    exchange.failures["entry"] = "after"
    run(broker.stage(setup))
    assert run(broker.dispatch(setup.episode_id))["status"] == "protected"
    run(broker.dispatch(setup.episode_id))
    assert sum(kind == "entry" for kind, _ in exchange.writes) == 1


def test_timeout_before_entry_stays_uncertain_and_is_never_replayed(execution_rig):
    broker, exchange, setup, _ = execution_rig
    exchange.failures["entry"] = "before"
    run(broker.stage(setup))
    assert run(broker.dispatch(setup.episode_id))["status"] == "needs_reconciliation"
    run(broker.dispatch(setup.episode_id))
    assert sum(kind == "entry" for kind, _ in exchange.writes) == 1
    with pytest.raises(ValueError, match="execution slot"):
        run(broker.stage(setup.model_copy(update={"episode_id": "another-episode"})))


def test_restart_preserves_ownership_and_does_not_repeat_orders(execution_rig):
    broker, exchange, setup, url = execution_rig
    run(broker.stage(setup))
    run(broker.dispatch(setup.episode_id))
    writes = len(exchange.writes)
    recovered = ExecutionLedger(url, exchange.account_address, broker.signer.address)
    restarted = TestnetBroker(recovered, exchange, broker.signer, armed=True)
    assert run(restarted.dispatch(setup.episode_id))["status"] == "protected"
    assert len(exchange.writes) == writes
    assert len(recovered.snapshot()["fills"]) == 1


def test_failed_stop_triggers_reduce_only_exit_and_latched_halt(execution_rig):
    broker, exchange, setup, _ = execution_rig
    exchange.failures["stop"] = "reject"
    run(broker.stage(setup))
    assert run(broker.dispatch(setup.episode_id))["status"] == "emergency"
    assert exchange.position == 0
    close = next(action for kind, action in exchange.writes if kind == "close")
    assert close["orders"][0]["r"] is True
    assert broker.ledger.snapshot()["control"]["halt_reason"]
    assert run(broker.reconcile(setup.episode_id))["status"] == "closed"


def test_timeout_on_accepted_stop_uses_exchange_confirmation(execution_rig):
    broker, exchange, setup, _ = execution_rig
    exchange.failures["stop"] = "after"
    run(broker.stage(setup))
    assert run(broker.dispatch(setup.episode_id))["status"] == "protected"
    assert not any(kind == "close" for kind, _ in exchange.writes)


def test_exit_fill_closes_trade_and_cleans_up_owned_protection(execution_rig):
    broker, exchange, setup, _ = execution_rig
    run(broker.stage(setup))
    run(broker.dispatch(setup.episode_id))
    stop = next(o for o in exchange.orders.values() if o["order"]["triggerPx"] == "59400")
    exchange.fill(stop["order"], abs(exchange.position), D("59400"))
    stop["status"] = "filled"
    assert run(broker.reconcile(setup.episode_id))["status"] == "closed"
    assert not run(exchange.open_orders())
    fees = broker.ledger.snapshot()["observed_fill_fees"]
    run(broker.reconcile(setup.episode_id))
    assert broker.ledger.snapshot()["observed_fill_fees"] == fees
    assert len(broker.ledger.snapshot()["fills"]) == 2


def test_reduced_position_gets_replacement_stop_before_old_cancel(execution_rig):
    broker, exchange, setup, _ = execution_rig
    run(broker.stage(setup))
    run(broker.dispatch(setup.episode_id))
    stop = next(o for o in exchange.orders.values() if o["order"]["triggerPx"] == "59400")
    exchange.fill(stop["order"], D("0.0001"), D("59400"))
    start = len(exchange.writes)
    result = run(broker.reconcile(setup.episode_id))
    assert result["status"] == "protected"
    assert D(result["protected_quantity"]) == D("0.0002")
    after = [kind for kind, action in exchange.writes[start:]]
    assert after.index("stop") < after.index("cancel")


def test_expired_agent_cannot_send(execution_rig):
    broker, exchange, setup, _ = execution_rig
    run(broker.stage(setup))
    exchange.approved = False
    with pytest.raises(ValueError, match="not approved"):
        run(broker.dispatch(setup.episode_id))
    assert exchange.writes == []


def test_uncertain_leverage_prevents_entry(execution_rig):
    broker, exchange, setup, _ = execution_rig
    exchange.failures["leverage"] = "after"
    run(broker.stage(setup))
    assert run(broker.dispatch(setup.episode_id))["status"] == "needs_reconciliation"
    run(broker.dispatch(setup.episode_id))
    assert [kind for kind, _ in exchange.writes] == ["leverage"]


def test_one_claim_across_multiple_ledger_instances(execution_rig):
    broker, exchange, setup, url = execution_rig
    trade = run(broker.stage(setup))
    key = trade["entry"]["cloid"]
    broker.ledger.prepare_command(setup.episode_id, key, "entry", trade["entry"])
    other = ExecutionLedger(url, exchange.account_address, broker.signer.address)
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(lambda ledger: ledger.claim(key, 1700000000000), [broker.ledger, other]))
    assert sum(result is not None for result in results) == 1
    assert other.claim(key, 1700000000001) is None


def test_ledger_identity_cannot_be_reassigned(execution_rig):
    broker, exchange, setup, url = execution_rig
    with pytest.raises(ValueError, match="different account"):
        ExecutionLedger(url, "0x" + "3" * 40, broker.signer.address)


def test_stale_reconciliation_never_writes(execution_rig):
    broker, exchange, setup, _ = execution_rig
    run(broker.stage(setup))
    run(broker.dispatch(setup.episode_id))
    exchange.stale = True
    count = len(exchange.writes)
    assert run(broker.reconcile(setup.episode_id))["status"] == "needs_reconciliation"
    assert len(exchange.writes) == count

