"""Public unfunded keys only; all signatures and handoffs stay offline."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta

from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi.testclient import TestClient
import pytest

from lobster.config import Settings
from lobster.domain import utcnow
from lobster.main import create_app
from lobster.store import Store
from lobster.users.contracts import UserTestnetSettings
from lobster.users.intents import ProfileInput, UserIntents
from lobster.users.orders import illustrate
from test_user_orders import inputs, KEY, OTHER_KEY, ADDRESS, signin

BUILDER = "0x" + "4" * 40
AGENT = Account.from_key(OTHER_KEY).address.lower()


@pytest.fixture
def journal(inputs, tmp_path):
    ep, state, market, rules, policy = inputs
    intents = UserIntents(Store(f"sqlite:///{tmp_path / 'intents.db'}"))
    intents.configure(ProfileInput(address=ADDRESS, agent=AGENT, builder=BUILDER))
    return intents, illustrate(ep, ADDRESS, state, market, rules, policy)


def sign(typed, key=KEY):
    return "0x" + Account.sign_message(encode_typed_data(full_message=typed), key).signature.hex()


def test_exact_local_consent_is_single_use_across_restart_and_concurrent_claims(journal):
    intents, plan = journal
    item = intents.prepare(ADDRESS, plan)
    signature = sign(item["typed_data"])
    verified = intents.verify_local(ADDRESS, item["id"], signature)
    assert verified["status"] == "verified_local"
    with pytest.raises(ValueError): intents.verify_local(ADDRESS, item["id"], signature)
    restored = UserIntents(Store(str(intents.store.engine.url)))
    def claim(_):
        try: return restored.claim_offline(ADDRESS, item["id"], plan)
        except ValueError: return None
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(claim, range(8)))
    assert sum(result is not None for result in results) == 1
    assert restored.get(ADDRESS, item["id"])["status"] == "claimed_offline"
    assert restored.get(AGENT, item["id"]) is None
    assert not verified["exchange_submission_enabled"]


@pytest.mark.parametrize("change", ["owner", "fee", "agent", "plan", "expiry", "signature"])
def test_changed_bindings_and_invalid_proofs_fail_closed(journal, monkeypatch, change):
    import lobster.users.intents as module
    intents, plan = journal
    item = intents.prepare(ADDRESS, plan)
    typed = deepcopy(item["typed_data"])
    if change in {"owner", "agent"}: typed["message"][change] = BUILDER
    if change == "fee": typed["message"]["builderFeeTenthsBps"] += 1
    if change == "expiry": monkeypatch.setattr(module, "utcnow", lambda: utcnow() + timedelta(seconds=31))
    if change == "signature": signature = sign(typed, OTHER_KEY)
    else: signature = sign(typed)
    if change == "plan":
        intents.verify_local(ADDRESS, item["id"], signature)
        plan["entry"]["quantity"] = "1"
        with pytest.raises(ValueError): intents.claim_offline(ADDRESS, item["id"], plan)
    else:
        with pytest.raises(ValueError): intents.verify_local(ADDRESS, item["id"], signature)
    assert not intents.get(ADDRESS, item["id"])["exchange_submission_enabled"]


def test_profile_is_immutable_and_each_user_requires_a_unique_api_wallet(journal):
    intents, _ = journal
    with pytest.raises(ValueError, match="immutable"):
        intents.configure(ProfileInput(address=ADDRESS, agent=AGENT, builder=BUILDER, fee_tenths_bps=30))
    with pytest.raises(ValueError, match="different"):
        intents.configure(ProfileInput(address="0x" + "5" * 40, agent=AGENT, builder=BUILDER))
    allowed = intents.configure(ProfileInput(address="0x" + "5" * 40, agent="0x" + "6" * 40, builder=BUILDER))
    assert allowed["builder"] == BUILDER


@pytest.mark.parametrize("changes", [{"agent": ADDRESS}, {"agent": BUILDER}, {"address": AGENT}, {"address": BUILDER}, {"builder": ADDRESS}, {"builder": AGENT}])
def test_api_wallets_cannot_reuse_another_registered_main_or_builder_key(journal, changes):
    intents, _ = journal
    profile = {"address": "0x" + "5"*40, "agent": "0x" + "6"*40, "builder": BUILDER} | changes
    with pytest.raises(ValueError): intents.configure(ProfileInput(**profile))


def test_permission_nonces_are_serialized_and_sdk_signatures_bind_testnet(journal):
    intents, _ = journal
    from hyperliquid.utils.signing import sign_agent, sign_approve_builder_fee
    plans = intents.approval_plans(ADDRESS)
    again = intents.approval_plans(ADDRESS)
    assert plans["builder"]["action"]["nonce"] < again["agent"]["action"]["nonce"]
    assert plans["builder"]["action"]["maxFeeRate"] == "0.02%"
    for label, sdk in [("agent", sign_agent), ("builder", sign_approve_builder_fee)]:
        typed = plans[label]["typed_data"]
        action = deepcopy(plans[label]["action"])
        signature = sdk(Account.from_key(KEY), action, False)
        expected = Account.sign_message(encode_typed_data(full_message=typed), KEY)
        assert signature == {"r": hex(expected.r), "s": hex(expected.s), "v": expected.v}
    assert not plans["submitted"] and not plans["wallet_signing_enabled"]


def test_http_profiles_require_operator_and_intents_cannot_sign_or_submit(journal, tmp_path):
    _, plan = journal
    app = create_app(Settings(_env_file=None, worker_enabled=False, operator_token="local-test-operator-123456",
        database_url=f"sqlite:///{tmp_path / 'http.db'}"), user_settings=UserTestnetSettings(_env_file=None, builder_address=BUILDER))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        body = {"address": ADDRESS, "agent": AGENT, "builder": BUILDER}
        url = "/api/v1/operator/user-testnet-profile"
        assert client.post(url, json=body).status_code == 401
        headers = signin(client, KEY)
        assert client.post(url, json=body, headers=headers).status_code == 401
        assert client.post(url, json=body, headers={"Authorization": "Bearer local-test-operator-123456"}).status_code == 200
        app.state.user_plans.save(ADDRESS, "intent-test-123", plan)
        response = client.post("/api/v1/users/testnet/intents", json={"plan_id": plan["id"]}, headers=headers)
        assert response.status_code == 201, response.text
        path = "/api/v1/users/testnet/intents/" + response.json()["id"]
        assert client.get(path, headers=signin(client, OTHER_KEY)).status_code == 404
        assert client.post(path + "/sign", json={"signature": sign(response.json()["typed_data"])}, headers=headers).status_code == 404
        assert client.post(path + "/submit", headers=headers).status_code == 404
        assert not app.state.runtime.store.state(None)["positions"]
