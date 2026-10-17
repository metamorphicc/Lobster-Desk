"""Mainnet domains/transport are exercised only with public keys and HTTP mocks."""
import asyncio
from decimal import Decimal as D
import json

from hyperliquid.utils.signing import recover_agent_or_user_from_l1_action
import httpx
import pytest

from lobster.domain import utcnow
from lobster.execution.broker import TestnetBroker
from lobster.execution.contracts import OrderSpec, cloid
from lobster.execution.gateway import HyperliquidMainnet, HyperliquidTestnet
from lobster.execution.ledger import ExecutionLedger
from lobster.execution.signer import MainnetSigner, TestnetSigner
from lobster.execution.simulation import SimulationGateway
from conftest import FIXTURE_KEY, FIXTURE_ADDRESS


def test_mainnet_signature_cannot_recover_as_testnet_and_ids_are_disjoint():
    gateway = SimulationGateway()
    signer = MainnetSigner(FIXTURE_KEY, FIXTURE_ADDRESS, gateway.rules)
    now = int(utcnow().timestamp() * 1000)
    order = OrderSpec(asset_id=3, side="buy", quantity="0.0003", price="60000", kind="entry", cloid=cloid("fixture", "entry", network="mainnet"))
    envelope = signer.order(order, now, now)
    args = (envelope["action"], envelope["signature"], None, envelope["nonce"], envelope["expiresAfter"])
    assert recover_agent_or_user_from_l1_action(*args, True) == signer.address
    assert recover_agent_or_user_from_l1_action(*args, False) != signer.address
    assert cloid("fixture", "entry") != order.cloid


def test_mainnet_transport_fixed_host_and_source_no_redirects():
    seen = []
    def respond(request):
        assert request.url.host == "api.hyperliquid.xyz" and request.url.path == "/info"
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=[{"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}]},
            [{"midPx": "60000", "markPx": "60001", "funding": "0.0001", "openInterest": "20000"}]])
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            _, market = await HyperliquidMainnet(client, FIXTURE_ADDRESS).market()
            assert market.source == "hyperliquid"
    asyncio.run(run())
    assert len(seen) == 1


def test_ledger_network_identity_survives_restart_and_cannot_be_changed(tmp_path):
    path = f"sqlite:///{tmp_path / 'execution.db'}"
    signer = MainnetSigner(FIXTURE_KEY, FIXTURE_ADDRESS, SimulationGateway().rules)
    ledger = ExecutionLedger(path, FIXTURE_ADDRESS, signer.address, network="mainnet")
    assert ledger.snapshot()["control"]["network"] == "mainnet"
    ledger.engine.dispose()
    with pytest.raises(ValueError, match="different"):
        ExecutionLedger(path, FIXTURE_ADDRESS, signer.address)
    restored = ExecutionLedger(path, FIXTURE_ADDRESS, signer.address, network="mainnet")
    restored.engine.dispose()


def test_network_mismatch_is_refused_before_any_command(execution_rig, tmp_path):
    broker, exchange, setup, _ = execution_rig
    signer = MainnetSigner(FIXTURE_KEY, exchange.account_address, exchange.rules)
    with pytest.raises(ValueError, match="networks"):
        TestnetBroker(broker.ledger, exchange, signer, armed=True)
    assert exchange.writes == []


def test_mainnet_reuses_partial_fill_protection_and_restart_recovery(execution_rig, tmp_path):
    _, fixture, test_setup, _ = execution_rig
    class MainnetFixture(SimulationGateway):
        network = "mainnet"
        async def market(self):
            rules, market = await super().market()
            return rules, market.model_copy(update={"source": "hyperliquid"})
        async def account(self): return (await super().account()).model_copy(update={"network": "mainnet"})
    gateway = MainnetFixture()
    signer = MainnetSigner(FIXTURE_KEY, gateway.account_address, gateway.rules)
    url = f"sqlite:///{tmp_path / 'mainnet-fixture.db'}"
    ledger = ExecutionLedger(url, gateway.account_address, signer.address, network="mainnet")
    setup = test_setup.model_copy(update={"network": "mainnet"})
    async def run():
        broker = TestnetBroker(ledger, gateway, signer, armed=True)
        await broker.stage(setup)
        result = await broker.dispatch(setup.episode_id)
        assert result["status"] == "protected" and result["network"] == "mainnet"
        assert D(result["protected_quantity"]) == gateway.partial
        restored = ExecutionLedger(url, gateway.account_address, signer.address, network="mainnet")
        try:
            restarted = TestnetBroker(restored, gateway, signer, armed=True)
            assert (await restarted.dispatch(setup.episode_id))["status"] == "protected"
            assert sum(kind == "entry" for kind, _ in gateway.writes) == 1
        finally: restored.engine.dispose()
    try: asyncio.run(run())
    finally: ledger.engine.dispose()
