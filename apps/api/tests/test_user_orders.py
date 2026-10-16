import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
import pytest

from lobster.config import Settings
from lobster.domain import PitchInput, utcnow
from lobster.agents import DemoReviewer
from lobster.pipeline import Pipeline
from lobster.execution.contracts import fingerprint
from lobster.execution.settings import TestnetSettings
from lobster.main import create_app
from lobster.store import Episode, Store
from lobster.users.orders import UserPlans, illustrate
from lobster.users import orders

KEY = "0x" + "0" * 63 + "1"  # Public, unfunded test vector. NEVER fund.
OTHER_KEY = "0x" + "0" * 63 + "2"
ADDRESS = Account.from_key(KEY).address.lower()


def account(address=ADDRESS):
    return {"address": address, "network": "testnet", "stale": False, "observed_at": utcnow().isoformat(),
        "equity": "1000", "withdrawable": "1000", "reported_taker_rate": "0.00045", "positions": [], "open_orders": [],
        "builder_address": "0x" + "4" * 40, "builder_fee_tenths_bps": 20, "builder_approval_status": "approved"}


@pytest.fixture
def inputs(execution_rig, tmp_path):
    broker, exchange, setup, _ = execution_rig
    store = Store(f"sqlite:///{tmp_path / 'review.db'}")
    rules, market = asyncio.run(exchange.market())
    return store.get_episode(setup.episode_id), account(), market, rules, store.policy


def make(inputs):
    ep, state, market, rules, policy = inputs
    return illustrate(ep, state["address"], state, market, rules, policy)


def test_exact_user_sizing_fees_and_bound_review_never_produce_execution_authority(inputs):
    plan = make(inputs)
    assert plan["address"] == ADDRESS and plan["approval_hash"] == inputs[0]["approval_hash"]
    assert plan["per_trade"]["checks_passed"]
    assert D(plan["per_trade"]["notional"]) <= D("50")
    assert D(plan["per_trade"]["planned_loss_including_estimated_costs"]) <= D(plan["per_trade"]["risk_budget"])
    assert D(plan["fees"]["entry_builder_hypothetical"]) == D(plan["per_trade"]["notional"]) * D("0.0002")
    assert plan["fees"]["collected"] == "0"
    assert plan["protection_templates"]["quantity_binding"] == "actual_confirmed_fill"
    assert all(plan[key] is False for key in ("signed", "submitted", "executable", "nonce_reserved", "order_submission_enabled", "fee_collection_enabled"))
    assert any("baselines" in reason for reason in plan["execution_blockers"])
    assert fingerprint({key: value for key, value in plan.items() if key != "plan_hash"}) == plan["plan_hash"]


@pytest.mark.parametrize("change", ["stale_account", "wrong_account", "mainnet", "stale_market", "expired_review", "tampered_review",
    "occupied", "open_order", "zero_capital", "float_capital", "no_trigger", "gap", "tiny_capital"])
def test_missing_or_invalid_authority_fails_closed(inputs, change):
    ep, state, market, rules, policy = deepcopy(inputs)
    if change == "stale_account": state["observed_at"] = (utcnow() - timedelta(seconds=16)).isoformat()
    if change == "wrong_account": state["address"] = "0x" + "9" * 40
    if change == "mainnet": market = market.model_copy(update={"source": "hyperliquid"})
    if change == "stale_market": market = market.model_copy(update={"timestamp": utcnow() - timedelta(seconds=16)})
    if change == "expired_review": ep["expires_at"] = (utcnow() - timedelta(seconds=1)).isoformat()
    if change == "tampered_review": ep["pitch"]["target"] = "70000"
    if change == "occupied": state["positions"] = [{"symbol": "ETH"}]
    if change == "open_order": state["open_orders"] = [{"symbol": "BTC"}]
    if change == "zero_capital": state["equity"] = "0"
    if change == "float_capital": state["equity"] = 1000.0
    if change == "no_trigger": market = market.model_copy(update={"price": D("59999")})
    if change == "gap": market = market.model_copy(update={"price": D("61000")})
    if change == "tiny_capital": state["equity"] = "0.01"
    with pytest.raises(ValueError):
        illustrate(ep, ADDRESS, state, market, rules, policy)


def test_user_balance_changes_sizing_without_using_project_cash(inputs):
    ep, state, market, rules, policy = inputs
    large = make(inputs)
    small = illustrate(ep, ADDRESS, state | {"equity": "80", "withdrawable": "80"}, market, rules, policy)
    assert D(small["per_trade"]["notional"]) < D(large["per_trade"]["notional"])
    assert small["per_trade"]["user_equity"] == "80"


def test_short_plan_and_capital_fee_invariants(inputs, tmp_path):
    _, state, market, rules, policy = inputs
    store = Store(f"sqlite:///{tmp_path / 'short-review.db'}")
    ep = store.submit(PitchInput(author="Short QA", direction="short", entry="60000", stop="60600", target="58200",
        thesis="A short setup with a defined stop and target for invariant tests."), "short-123")
    pipeline = Pipeline(store, DemoReviewer())
    for _ in range(4): asyncio.run(pipeline.step(market))
    reviewed = store.get_episode(ep["id"])
    for equity in ["80", "200", "1000"]:
        for available in ["12", "40", "1000"]:
            for units in [0, 20, 100]:
                observation = state | {"equity": equity, "withdrawable": available, "builder_fee_tenths_bps": units}
                plan = illustrate(reviewed, ADDRESS, observation, market, rules, policy)
                entry, budget = plan["entry"], plan["per_trade"]
                assert entry["side"] == "sell"
                assert D(budget["notional"]) <= min(D("50"), D(equity) * D("0.25"))
                assert D(budget["planned_loss_including_estimated_costs"]) <= D(equity) * D("0.0025")
                assert D(budget["margin"]) + D(plan["fees"]["entry_exchange_estimate"]) + D(plan["fees"]["entry_builder_hypothetical"]) <= D(available)


def test_private_plan_idempotency_is_atomic_and_never_leaks_other_users(inputs, tmp_path, monkeypatch):
    stores = [Store(f"sqlite:///{tmp_path / 'private.db'}") for _ in range(3)]
    ledgers = [UserPlans(store) for store in stores]
    plan = make(inputs)
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda index: ledgers[index % 3].save(ADDRESS, "request-123", make(inputs)), range(12)))
    assert len({result["id"] for result in results}) == 1
    saved = results[0]
    assert ledgers[0].get("0x" + "9" * 40, saved["id"]) is None
    with pytest.raises(ValueError, match="another"):
        ledgers[0].by_request(ADDRESS, "request-123", "other-episode")
    assert "user_order_plans" not in str(stores[0].state(None))
    monkeypatch.setattr(orders, "utcnow", lambda: utcnow() + timedelta(seconds=31))
    restored = UserPlans(Store(str(stores[0].engine.url)))
    assert restored.get(ADDRESS, saved["id"])["expired"]
    assert restored.get(ADDRESS, saved["id"])["plan_hash"] == saved["plan_hash"]
    assert plan["fees"]["collected"] == "0"


def signin(client, key):
    address = Account.from_key(key).address.lower()
    challenge = client.post("/api/v1/users/testnet/auth/challenge", json={"address": address}).json()
    signature = "0x" + Account.sign_message(encode_defunct(text=challenge["message"]), key).signature.hex()
    result = client.post("/api/v1/users/testnet/auth/verify", json={"challenge_id": challenge["challenge_id"], "signature": signature}).json()
    return {"Authorization": "Bearer " + result["access_token"]}


def test_http_preview_is_private_replayable_and_never_sends_exchange_writes(inputs, tmp_path, monkeypatch):
    import lobster.main as main
    ep, state, market, rules, _ = inputs
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}", worker_enabled=False), TestnetSettings(_env_file=None))
    calls = []
    with TestClient(app, base_url="http://127.0.0.1") as client:
        with app.state.runtime.store.transaction() as session:
            session.add(Episode(id=ep["id"], request_id="fixture-review", payload=ep))
        async def inspect(address):
            calls.append(address); return account(address)
        async def observe(self):
            return rules, market
        monkeypatch.setattr(app.state.users, "inspect", inspect)
        monkeypatch.setattr(main.HyperliquidTestnet, "market", observe)
        url = "/api/v1/users/testnet/order-preview"
        body = {"episode_id": ep["id"]}
        assert client.post(url, json=body, headers={"Idempotency-Key": "preview-123"}).status_code == 401
        assert calls == []
        headers = signin(client, KEY) | {"Idempotency-Key": "preview-123"}
        first = client.post(url, json=body, headers=headers)
        assert first.status_code == 201, first.text
        assert first.json()["address"] == ADDRESS
        assert client.post(url, json=body, headers=headers).json()["id"] == first.json()["id"]
        assert calls == [ADDRESS]  # Cached replay performs no external read.
        path = "/api/v1/users/testnet/order-previews/" + first.json()["id"]
        assert client.get(path, headers=headers).status_code == 200
        other = signin(client, OTHER_KEY)
        assert client.get(path, headers=other).status_code == 404
        assert client.post(url, json=body | {"address": ADDRESS}, headers=other | {"Idempotency-Key": "preview-456"}).status_code == 422
        assert client.post("/api/v1/users/testnet/orders", json=first.json(), headers=headers).status_code == 404
        assert not app.state.runtime.store.state(None)["positions"]


def test_revoked_session_during_account_lookup_cannot_save_a_preview(inputs, tmp_path, monkeypatch):
    import lobster.main as main
    ep, _, market, rules, _ = inputs
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}", worker_enabled=False), TestnetSettings(_env_file=None))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        with app.state.runtime.store.transaction() as session:
            session.add(Episode(id=ep["id"], request_id="fixture-review", payload=ep))
        headers = signin(client, KEY)
        async def inspect(address):
            app.state.user_auth.logout(headers["Authorization"])
            return account(address)
        async def observe(self): return rules, market
        monkeypatch.setattr(app.state.users, "inspect", inspect)
        monkeypatch.setattr(main.HyperliquidTestnet, "market", observe)
        response = client.post("/api/v1/users/testnet/order-preview", json={"episode_id": ep["id"]}, headers=headers | {"Idempotency-Key": "revoked-123"})
        assert response.status_code == 401
        assert app.state.user_plans.by_request(ADDRESS, "revoked-123", ep["id"]) is None
