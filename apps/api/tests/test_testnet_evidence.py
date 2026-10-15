import asyncio
import json

from lobster.execution.contracts import fingerprint
from lobster.execution.evidence import collect_evidence
from lobster.execution.settings import TestnetSettings
from lobster.execution.workbench import TestnetWorkbench
import httpx


def test_evidence_uses_only_info_and_never_certifies_acceptance():
    calls = []
    def respond(request):
        calls.append(json.loads(request.content)["type"])
        assert request.url.path == "/info"
        return httpx.Response(200, json=[{"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}]},
            [{"midPx": "60000", "funding": "0", "openInterest": "1"}]])
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            workbench = TestnetWorkbench(TestnetSettings(_env_file=None), client, "sqlite:///:memory:")
            report = await collect_evidence(workbench)
            assert not report["funded_acceptance_verified"] and not report["exchange_writes_attempted"]
            assert not report["fills"] and report["required_owner_cases"]
            digest = report.pop("report_hash")
            assert fingerprint(report) == digest
    asyncio.run(run())
    assert calls == ["metaAndAssetCtxs"]


def test_observed_order_identity_and_fills_are_rechecked(execution_rig):
    broker, exchange, setup, _ = execution_rig
    async def run():
        await broker.stage(setup)
        await broker.dispatch(setup.episode_id)
        async with httpx.AsyncClient() as client:
            workbench = TestnetWorkbench(TestnetSettings(_env_file=None), client, "sqlite:///:memory:")
            workbench.ledger = broker.ledger
            workbench.settings = TestnetSettings(_env_file=None, account_address=exchange.account_address, api_wallet_address=broker.signer.address)
            workbench.gateway = exchange
            before = len(exchange.writes)
            report = await collect_evidence(workbench)
            assert len(exchange.writes) == before
            assert len(report["orders"]) == 3 and report["fills"]
            assert all(order["identity_matches"] for order in report["orders"])
            assert not report["funded_acceptance_verified"]
            assert '"signature":' not in json.dumps(report)
            assert "thesis" not in json.dumps(report)
            entry = next(record for record in exchange.orders.values() if not record["order"]["reduceOnly"])
            entry["order"]["coin"] = "ETH"
            report = await collect_evidence(workbench)
            assert not report["fills"]
            assert any(not order["identity_matches"] for order in report["orders"])
    asyncio.run(run())
