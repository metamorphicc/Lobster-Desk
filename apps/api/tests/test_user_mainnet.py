"""Mainnet boundary tests use public unfunded keys and memory/HTTP fixtures only."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
import pytest

from lobster.agents import DemoReviewer
from lobster.config import Settings
from lobster.domain import PitchInput, utcnow
from lobster.execution.simulation import SimulationGateway
from lobster.main import create_app
from lobster.pipeline import Pipeline
from lobster.store import Store
from lobster.users.auth import UserAuth, VerifyInput, AuthError
from lobster.users.capital import UserCapital
from lobster.users.contracts import UserMainnetSettings
from lobster.users.financial import UserFinancial, FinancialRequest
from lobster.users.intents import UserIntents, ProfileInput
from lobster.users.orders import UserPlans, illustrate
from lobster.users.runner import UserFinancialRunner
from test_user_orders import ADDRESS, KEY, OTHER_KEY, account
from test_user_intents import AGENT, BUILDER, sign

THIRD_KEY = "0x" + "0" * 63 + "3"  # Public unfunded vector. NEVER fund.


def login(auth):
    challenge = auth.challenge(ADDRESS, "offline")
    signature = Account.sign_message(encode_defunct(text=challenge["message"]), KEY).signature.hex()
    return challenge, VerifyInput(challenge_id=challenge["challenge_id"], signature="0x" + signature.removeprefix("0x"))


def test_network_auth_domains_and_sessions_are_disjoint_in_one_database(tmp_path):
    store = Store(f"sqlite:///{tmp_path/'auth.db'}")
    try:
        testnet, mainnet = UserAuth(store), UserAuth(store, network="mainnet")
        challenge, proof = login(mainnet)
        assert challenge["chain_id"] == 42161 and "mainnet workspace" in challenge["message"]
        with pytest.raises(AuthError): testnet.verify(proof, "offline")
        session = mainnet.verify(proof, "offline")
        token = "Bearer " + session["access_token"]
        assert session["scope"] == "mainnet:preview" and mainnet.require(token)["network"] == "mainnet"
        with pytest.raises(AuthError): testnet.require(token)
        with pytest.raises(AuthError): mainnet.verify(proof, "offline")
    finally: store.engine.dispose()


class MemoryMainnet(SimulationGateway):
    network = "mainnet"
    async def market(self):
        rules, snapshot = await super().market()
        return rules, snapshot.model_copy(update={"source": "hyperliquid"})
    async def account(self): return (await super().account()).model_copy(update={"network": "mainnet"})


@pytest.fixture
def rig(tmp_path):
    store = Store(f"sqlite:///{tmp_path/'mainnet.db'}")
    gateway = MemoryMainnet(); gateway.account_address = ADDRESS
    state = account() | {"network": "mainnet", "withdrawable": "900", "exchange_time_ms": int(utcnow().timestamp()*1000)}
    async def setup():
        episode = store.submit(PitchInput(author="Mainnet offline QA", direction="long", entry="60000", stop="59400", target="61800",
            thesis="Synthetic mainnet-domain fixture only; never an observed production trade."), "mainnet-review-01")
        pipeline = Pipeline(store, DemoReviewer())
        for _ in range(4): await pipeline.step((await gateway.market())[1])
        rules, market = await gateway.market()
        return store.get_episode(episode["id"]), rules, market
    episode, rules, market = asyncio.run(setup())
    intents, plans = UserIntents(store, network="mainnet"), UserPlans(store, network="mainnet")
    intents.configure(ProfileInput(address=ADDRESS, agent=AGENT, builder=BUILDER, fee_tenths_bps=20, network="mainnet"))
    capital = UserCapital(store, network="mainnet", namespaced=True)
    capital.observe(ADDRESS, state, state["exchange_time_ms"], [], complete=True)
    plan = plans.save(ADDRESS, "mainnet-preview-01", illustrate(episode, ADDRESS, state, market, rules, store.policy, capital.get(ADDRESS), network="mainnet"))
    financial = UserFinancial(store, intents, plans)
    class Service:
        network = "mainnet"
        settings = UserMainnetSettings(_env_file=None, builder_address=BUILDER, builder_fee_tenths_bps=20)
        async def inspect(self, owner): return state | {"observed_at": utcnow().isoformat(), "exchange_time_ms": int(utcnow().timestamp()*1000)}
        async def capital_history(self, owner, start, end): return []
    async def info(kind, **fields):
        if kind == "userAbstraction": return "disabled"
        if kind == "clearinghouseState": return {"time": int(utcnow().timestamp()*1000), "marginSummary": {"accountValue": "100"}}
        raise ValueError("Unexpected fixture query")
    gateway.info = info
    try: yield SimpleNamespace(store=store, gateway=gateway, financial=financial, plan=plan, capital=capital, service=Service(), state=state)
    finally: store.engine.dispose()


def test_same_owner_profiles_plans_capital_and_permissions_do_not_cross_networks(rig):
    other = UserIntents(rig.store)
    other.configure(ProfileInput(address=ADDRESS, agent=Account.from_key(THIRD_KEY).address.lower(), builder=BUILDER, fee_tenths_bps=20))
    assert other.profile(ADDRESS)["network"] == "testnet"
    assert rig.financial.intents.profile(ADDRESS)["network"] == "mainnet"
    assert UserCapital(rig.store).get(ADDRESS) is None and UserPlans(rig.store).get(ADDRESS, rig.plan["id"]) is None
    with pytest.raises(ValueError): rig.financial.intents.prepare(ADDRESS, rig.plan)
    with pytest.raises(ValueError): UserPlans(rig.store).save(ADDRESS, "cross-network-01", rig.plan)
    body = FinancialRequest(kind="agent")
    main = rig.financial.prepare(ADDRESS, body, "same-request-01")
    test = UserFinancial(rig.store, other, UserPlans(rig.store)).prepare(ADDRESS, body, "same-request-01")
    assert main["id"] != test["id"] and main["action"]["hyperliquidChain"] == "Mainnet"
    assert rig.financial.get(ADDRESS, test["id"]) is None
    assert rig.financial.jobs(ADDRESS) == [main]
    wrong = deepcopy(main["typed_data"]); wrong["domain"]["chainId"] = 421614
    with pytest.raises(ValueError): rig.financial.verify(ADDRESS, main["id"], sign(wrong))


def test_mainnet_trade_actual_partial_fill_and_restart_do_not_reuse_expired_review(rig, tmp_path, monkeypatch):
    financial = rig.financial
    job = financial.prepare(ADDRESS, FinancialRequest(kind="trade", plan_id=rig.plan["id"]), "mainnet-trade-01")
    assert job["typed_data"]["domain"]["chainId"] == 42161 and job["typed_data"]["primaryType"] == "MainnetTradeIntent"
    financial.verify(ADDRESS, job["id"], sign(job["typed_data"]))
    def runner(): return UserFinancialRunner(store=rig.store, financial=financial, capital=rig.capital, service=rig.service,
        root=tmp_path/"mainnet-execution", enabled=True, armed=True)
    async def run():
        trade = await runner().tick(ADDRESS, SecretStr(OTHER_KEY), rig.gateway)
        assert trade["status"] == "protected"
        monkeypatch.setattr(rig.store, "get_episode", lambda *args: (_ for _ in ()).throw(ValueError("Review unavailable")))
        assert (await runner().tick(ADDRESS, SecretStr(OTHER_KEY), rig.gateway))["status"] == "protected"
        assert sum(kind == "entry" for kind, _ in rig.gateway.writes) == 1
        assert financial.context(ADDRESS, tmp_path/"mainnet-execution", True)["execution"]["network"] == "mainnet"
        rig.gateway.network = "testnet"
        with pytest.raises(ValueError, match="network"): await runner().tick(ADDRESS, SecretStr(OTHER_KEY), rig.gateway)
    asyncio.run(run())


def test_mainnet_permission_transport_is_fixed_and_unknown_is_never_replayed(rig):
    job = rig.financial.prepare(ADDRESS, FinancialRequest(kind="builder"), "mainnet-permission-01")
    rig.financial.verify(ADDRESS, job["id"], sign(job["typed_data"]))
    writes = []
    def respond(request):
        assert str(request.url) == "https://api.hyperliquid.xyz/exchange"
        writes.append(request.content)
        raise httpx.ReadTimeout("Synthetic uncertain mainnet permission")
    async def info(*args, **kwargs): return 20
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            gateway = SimpleNamespace(network="mainnet", account_address=ADDRESS, client=client, info=info)
            assert (await rig.financial.submit_permission(ADDRESS, job["id"], gateway, armed=True))["status"] == "unknown"
            assert (await rig.financial.submit_permission(ADDRESS, job["id"], gateway, armed=True))["status"] == "unknown"
            assert len(writes) == 1
            gateway.network = "testnet"
            with pytest.raises(ValueError): await rig.financial.submit_permission(ADDRESS, job["id"], gateway, armed=True)
            with pytest.raises(ValueError): await rig.financial.reconcile_permission(ADDRESS, job["id"], gateway)
    asyncio.run(run())


@pytest.mark.parametrize("enabled", [False, True])
def test_mainnet_http_requires_separate_session_and_cannot_dispatch(tmp_path, enabled):
    root = tmp_path/"mainnet-execution"
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path/'app.db'}", worker_enabled=False),
        mainnet_user_settings=UserMainnetSettings(_env_file=None, builder_address=BUILDER, builder_fee_tenths_bps=20, financial_enabled=enabled, execution_root=str(root)))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        app.state.mainnet_intents.configure(ProfileInput(address=ADDRESS, agent=AGENT, builder=BUILDER, fee_tenths_bps=20, network="mainnet"))
        assert client.get("/api/v1/users/mainnet/config").json()["network"] == "mainnet"
        assert client.get("/api/v1/users/mainnet/financial").status_code == 401
        _, proof = login(app.state.mainnet_auth)
        signed = client.post("/api/v1/users/mainnet/auth/verify", json=proof.model_dump()).json()
        headers = {"Authorization": "Bearer " + signed["access_token"], "Idempotency-Key": "mainnet-http-01"}
        assert client.get("/api/v1/users/testnet/auth/session", headers=headers).status_code == 401
        result = client.post("/api/v1/users/mainnet/financial/jobs", headers=headers, json={"kind": "agent"})
        assert result.status_code == (201 if enabled else 503)
        if enabled:
            job = result.json()
            proof = client.post(f"/api/v1/users/mainnet/financial/jobs/{job['id']}/proof", headers=headers, json={"signature": sign(job["typed_data"])})
            assert proof.status_code == 200 and proof.json()["status"] == "signed"
            assert proof.json()["proof"] is None and proof.json()["submission_from_api"] is False
        assert not root.exists()
