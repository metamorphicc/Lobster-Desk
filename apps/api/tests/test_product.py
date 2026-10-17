import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from lobster.domain import utcnow
from lobster.execution.ledger import ExecutionLedger
from lobster.execution.contracts import fingerprint
from lobster.market import DemoFeed
from lobster.ops.catalog import register_journal
from lobster.product import product_state
from lobster.store import Store
from lobster.users.capital import UserCapital, Reference


@pytest.fixture
def public_runtime(tmp_path):
    store = Store(f"sqlite:///{tmp_path/'app.db'}")
    runtime = SimpleNamespace(store=store, product_market=None)
    yield runtime
    store.engine.dispose()


def test_product_never_relabels_paper_capital_or_synthetic_market(public_runtime):
    public_runtime.product_market = asyncio.run(DemoFeed().fetch())
    result = product_state(public_runtime)
    assert result["market"] is None
    assert result["account"]["equity"] is None
    assert result["account"]["performance_pnl"] is None
    assert result["episodes"] == result["positions"] == result["events"] == []
    assert "1000" not in json.dumps(result["account"])


def test_public_market_must_be_fresh_mainnet(public_runtime):
    snapshot = asyncio.run(DemoFeed().fetch()).model_copy(update={"source": "hyperliquid"})
    public_runtime.product_market = snapshot
    assert product_state(public_runtime)["market"]["source"] == "hyperliquid"
    public_runtime.product_market = snapshot.model_copy(update={"timestamp": utcnow() - timedelta(seconds=16)})
    assert product_state(public_runtime)["market"] is None
    public_runtime.product_market = snapshot.model_copy(update={"source": "hyperliquid-testnet"})
    assert product_state(public_runtime)["market"] is None


@pytest.mark.parametrize("network,age,halt,visible", [("mainnet", 0, None, True), ("testnet", 0, None, False),
    ("mainnet", 31, None, False), ("mainnet", 0, "Accounting review", False)])
def test_public_capital_requires_registered_mainnet_and_current_reference(public_runtime, tmp_path, network, age, halt, visible):
    account, signer = "0x" + "1" * 40, "0x" + "2" * 40
    ledger = ExecutionLedger(f"sqlite:///{tmp_path/'project.db'}", account, signer, network=network)
    try:
        register_journal(public_runtime.store, ledger, "project")
        UserCapital(SimpleNamespace(engine=ledger.engine, transaction=ledger.transaction, policy=public_runtime.store.policy), network=network)
        with ledger.transaction() as db:
            db.add(Reference(address=account, payload={"network": network, "address": account,
                "policy_hash": fingerprint(public_runtime.store.policy.model_dump(mode="json")),
                "equity": "123.456789", "net_equity_change_excluding_cashflows": "-2.3", "halt_reason": halt,
                "observed_at": (utcnow() - timedelta(seconds=age)).isoformat()}))
        result = product_state(public_runtime)
        assert result["account"]["equity"] == ("123.456789" if visible else None)
        assert result["account"]["performance_pnl"] == ("-2.3" if visible else None)
        assert account not in json.dumps(result) and signer not in json.dumps(result)
    finally: ledger.engine.dispose()
