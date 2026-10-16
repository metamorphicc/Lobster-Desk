import asyncio
from copy import deepcopy
from decimal import Decimal as D

import pytest
from pydantic import SecretStr

from lobster.execution.signer import TestnetSigner
from lobster.execution.contracts import OrderSpec


def test_entry_guard_runs_before_staging_and_after_leverage_but_never_blocks_recovery(execution_rig):
    broker, exchange, setup, _ = execution_rig
    observations = []
    async def guard(account):
        observations.append(account)
        if len(observations) == 3:
            raise ValueError("Builder approval revoked before entry")
    broker.entry_guard = guard
    trade = asyncio.run(broker.stage(setup))
    with pytest.raises(ValueError, match="revoked"):
        asyncio.run(broker.dispatch(trade["id"]))
    assert len(observations) == 3
    assert [kind for kind, _ in exchange.writes] == ["leverage"]
    # Another offline rig continuation: a filled position remains protectable
    # even when the external entry-only accounting/consent guard is unavailable.
    broker.entry_guard = None
    trade = asyncio.run(broker.dispatch(trade["id"]))
    async def unavailable(account): raise ValueError("Accounting outage")
    broker.entry_guard = unavailable
    recovered = asyncio.run(broker.reconcile(trade["id"]))
    assert recovered["status"] == "protected"


def test_configured_builder_fee_is_signed_on_all_order_legs_only(execution_rig):
    broker, exchange, setup, _ = execution_rig
    signer = TestnetSigner(SecretStr("0x" + "0"*63 + "1"), exchange.account_address, exchange.rules,
        builder="0x" + "4"*40, builder_fee_tenths_bps=20)
    broker.signer = signer
    trade = asyncio.run(broker.stage(setup))
    asyncio.run(broker.dispatch(trade["id"]))
    for kind, action in exchange.writes:
        if kind == "leverage": assert "builder" not in action
        else: assert action["builder"] == {"b": "0x" + "4"*40, "f": 20}
    with pytest.raises(ValueError):
        TestnetSigner(SecretStr("0x"+"0"*63+"1"), exchange.account_address, exchange.rules, builder=exchange.account_address)


def test_builder_fee_receipt_component_is_never_double_counted_or_fabricated(execution_rig):
    broker, exchange, setup, _ = execution_rig
    trade = asyncio.run(broker.stage(setup))
    asyncio.run(broker.dispatch(trade["id"]))
    old = exchange.observed_fills[0]
    # Existing fill had no component observation: don't infer one from a rate.
    assert broker.ledger.snapshot()["builder_fee_coverage_complete"] is False
    fill = deepcopy(old) | {"tid": 9876, "builderFee": "0.002"}
    broker.ledger.record_fills(trade["id"], [fill, fill], {old["oid"]})
    report = broker.ledger.snapshot()
    assert D(report["observed_builder_fee_component"]) == D("0.002")
    assert D(report["observed_fill_fees"]) == D("0.02")
    with pytest.raises(ValueError, match="Conflicting"):
        broker.ledger.record_fills(trade["id"], [fill | {"fee": "0.02"}], {old["oid"]})
    with pytest.raises(ValueError):
        broker.ledger.record_fills(trade["id"], [fill | {"tid": 9877, "fee": 0.01}], {old["oid"]})
