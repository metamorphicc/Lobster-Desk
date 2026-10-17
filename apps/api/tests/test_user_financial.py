import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from pydantic import SecretStr
import pytest

from lobster.config import Settings
from lobster.domain import utcnow
from lobster.main import create_app
from lobster.store import Store
from lobster.users.contracts import UserTestnetSettings
from lobster.users.financial import UserFinancial, FinancialRequest
from lobster.users.intents import UserIntents, ProfileInput
from lobster.users.orders import UserPlans
from lobster.users.runner import UserFinancialRunner
from fastapi.testclient import TestClient
from test_user_orchestration import context
from test_user_intents import AGENT, BUILDER, sign
from test_user_orders import ADDRESS, KEY, OTHER_KEY, signin


def financial(context):
    old, gateway, _, _, _ = context
    return UserFinancial(old.store, old.intents, old.intents.plans if hasattr(old.intents, "plans") else UserPlans(old.store))


def test_financial_trade_domain_rejects_rehearsal_proof_and_is_idempotent(context):
    old, _, _, _, _ = context
    service = financial(context)
    body = FinancialRequest(kind="trade", plan_id=old.plan["id"])
    job = service.prepare(ADDRESS, body, "financial-trade-01")
    assert service.prepare(ADDRESS, body, "financial-trade-01")["id"] == job["id"]
    assert job["typed_data"]["domain"]["name"] == "Lobster Desk Execution Consent"
    wrong = deepcopy(job["typed_data"]); wrong["domain"]["name"] = "Lobster Desk Local Intent"
    with pytest.raises(ValueError, match="owner"): service.verify(ADDRESS, job["id"], sign(wrong))
    signature = sign(job["typed_data"])
    assert service.verify(ADDRESS, job["id"], signature)["status"] == "signed"
    assert service.verify(ADDRESS, job["id"], signature)["status"] == "signed"
    assert service.get(AGENT, job["id"]) is None and service.view(service.get(ADDRESS, job["id"]))["proof"] is None
    assert service.claim_trade(ADDRESS, job["id"], old.plan)["status"] == "claimed"
    with pytest.raises(ValueError): service.claim_trade(ADDRESS, job["id"], old.plan)
    with pytest.raises(ValueError): service.prepare(ADDRESS, FinancialRequest(kind="builder"), "financial-trade-01")


def test_actual_user_runner_partial_fill_protection_and_restart_after_review_expiry(context, tmp_path, monkeypatch):
    old, gateway, _, _, _ = context
    service = financial(context)
    job = service.prepare(ADDRESS, FinancialRequest(kind="trade", plan_id=old.plan["id"]), "financial-trade-02")
    service.verify(ADDRESS, job["id"], sign(job["typed_data"]))
    root = tmp_path / "financial-execution"
    def runner():
        return UserFinancialRunner(store=old.store, financial=service, capital=old.capital, service=old.service,
            root=root, enabled=True, armed=True)
    async def run():
        result = await runner().tick(ADDRESS, SecretStr(OTHER_KEY), gateway)
        assert result["status"] == "protected" and result["audit_binding"]["user_intent_id"] == job["id"]
        assert sum(kind == "entry" for kind, _ in gateway.writes) == 1
        # Recovery must not reconstruct the current expired/changed model review.
        original = old.store.get_episode
        def unavailable(*args): raise ValueError("Review unavailable after the entry")
        monkeypatch.setattr(old.store, "get_episode", unavailable)
        assert (await runner().tick(ADDRESS, SecretStr(OTHER_KEY), gateway))["status"] == "protected"
        assert sum(kind == "entry" for kind, _ in gateway.writes) == 1
        private = service.context(ADDRESS, root, True)
        assert private["execution"]["trades"][0]["id"] == result["id"]
        assert all(row["proof"] is None for row in private["jobs"])
    asyncio.run(run())


def permission_gateway(timeout=False):
    writes = []
    def respond(request):
        assert str(request.url) == "https://api.hyperliquid-testnet.xyz/exchange"
        body = json.loads(request.content)
        assert body["action"]["type"] in {"approveAgent", "approveBuilderFee"}
        assert body["action"]["hyperliquidChain"] == "Testnet"
        writes.append(body)
        if timeout: raise httpx.ReadTimeout("public fixture")
        return httpx.Response(200, json={"status": "ok", "response": {"type": "default"}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    async def approved(agent): return agent == AGENT
    async def info(kind, **fields):
        assert kind == "maxBuilderFee" and fields == {"user": ADDRESS, "builder": BUILDER}
        return 20
    return SimpleNamespace(network="testnet", account_address=ADDRESS, client=client, agent_approved=approved, info=info), writes


@pytest.mark.parametrize("kind", ["agent", "builder"])
def test_sdk_permission_proof_is_claimed_before_submission_and_observed_once(context, kind):
    service = financial(context)
    job = service.prepare(ADDRESS, FinancialRequest(kind=kind), "permission-test-01")
    service.verify(ADDRESS, job["id"], sign(job["typed_data"]))
    gateway, writes = permission_gateway()
    async def run():
        try:
            assert (await service.submit_permission(ADDRESS, job["id"], gateway, armed=True))["status"] == "observed"
            assert (await service.submit_permission(ADDRESS, job["id"], gateway, armed=True))["status"] == "observed"
            assert len(writes) == 1
        finally: await gateway.client.aclose()
    asyncio.run(run())


def test_unknown_permission_matching_current_state_is_not_resolved_or_resent(context):
    service = financial(context)
    job = service.prepare(ADDRESS, FinancialRequest(kind="agent"), "permission-test-02")
    service.verify(ADDRESS, job["id"], sign(job["typed_data"]))
    gateway, writes = permission_gateway(timeout=True)
    async def run():
        try:
            result = await service.submit_permission(ADDRESS, job["id"], gateway, armed=True)
            assert result["status"] == "unknown" and result["permission_currently_matches"]
            assert (await service.submit_permission(ADDRESS, job["id"], gateway, armed=True))["status"] == "unknown"
            assert len(writes) == 1
        finally: await gateway.client.aclose()
    asyncio.run(run())


def test_builder_revocation_exact_zero_and_expired_or_other_owner_proofs_refuse(context, monkeypatch):
    import lobster.users.financial as module
    service = financial(context)
    job = service.prepare(ADDRESS, FinancialRequest(kind="revoke_builder"), "permission-revoke-01")
    assert job["action"]["maxFeeRate"] == "0%"
    with pytest.raises(ValueError): service.verify(AGENT, job["id"], sign(job["typed_data"]))
    monkeypatch.setattr(module, "utcnow", lambda: utcnow()+timedelta(seconds=31))
    with pytest.raises(ValueError, match="expired"): service.verify(ADDRESS, job["id"], sign(job["typed_data"]))


@pytest.mark.parametrize("enabled", [False, True])
def test_financial_http_is_owner_authenticated_gated_and_never_dispatches(tmp_path, enabled):
    root = tmp_path / "financial"
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path/'app.db'}", worker_enabled=False),
        user_settings=UserTestnetSettings(_env_file=None, financial_enabled=enabled, builder_address=BUILDER, builder_fee_tenths_bps=20, execution_root=str(root)))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/api/v1/users/testnet/financial").status_code == 401
        headers = signin(client, KEY) | {"Idempotency-Key": "financial-http-01"}
        app.state.user_intents.configure(ProfileInput(address=ADDRESS, agent=AGENT, builder=BUILDER, fee_tenths_bps=20))
        response = client.post("/api/v1/users/testnet/financial/jobs", headers=headers, json={"kind": "builder"})
        if not enabled:
            assert response.status_code == 503
        else:
            assert response.status_code == 201
            job = response.json()
            response = client.post(f"/api/v1/users/testnet/financial/jobs/{job['id']}/proof", headers=headers,
                json={"signature": sign(job["typed_data"])})
            assert response.status_code == 200 and response.json()["status"] == "signed"
            assert response.json()["proof"] is None and response.json()["submission_from_api"] is False
        assert client.get("/api/v1/users/testnet/financial", headers=headers).json()["enabled"] is enabled
        assert not root.exists()
