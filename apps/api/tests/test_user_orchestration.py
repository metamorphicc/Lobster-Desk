import asyncio
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from lobster.domain import utcnow
from lobster.users.capital import UserCapital
from lobster.users.contracts import UserTestnetSettings
from lobster.users.execution import UserExecution
from lobster.users.intents import ProfileInput, UserIntents
from lobster.users.orders import UserPlans, illustrate
from lobster.store import Store, Episode
from test_user_orders import account, ADDRESS, OTHER_KEY
from test_user_intents import AGENT, BUILDER, sign


@pytest.fixture
def context(execution_rig, tmp_path):
    _, gateway, setup, _ = execution_rig
    store = Store(f"sqlite:///{tmp_path / 'users.db'}")
    original = Store(f"sqlite:///{tmp_path / 'review.db'}")
    episode = original.get_episode(setup.episode_id)
    with store.transaction() as session: session.add(Episode(id=episode["id"], request_id="user-12345", payload=episode))
    gateway.account_address = ADDRESS
    state = account() | {"withdrawable": "900", "exchange_time_ms": int(utcnow().timestamp()*1000)}
    rules, market = asyncio.run(gateway.market())
    plans = UserPlans(store)
    plan = plans.save(ADDRESS, "private-12345", illustrate(episode, ADDRESS, state, market, rules, store.policy))
    intents = UserIntents(store)
    intents.configure(ProfileInput(address=ADDRESS, agent=AGENT, builder=BUILDER))
    intent = intents.prepare(ADDRESS, plan)
    intents.verify_local(ADDRESS, intent["id"], sign(intent["typed_data"]))
    capital = UserCapital(store)
    capital.observe(ADDRESS, state, state["exchange_time_ms"], [], complete=True)
    class Service:
        settings = UserTestnetSettings(_env_file=None, builder_address=BUILDER)
        async def inspect(self, owner):
            return state | {"observed_at": utcnow().isoformat(), "exchange_time_ms": int(utcnow().timestamp()*1000)}
        async def capital_history(self, owner, start, end): return []
    service = Service()
    modes = {ADDRESS: "disabled", BUILDER: "disabled"}
    async def info(kind, **fields):
        if kind == "userAbstraction": return modes[fields["user"]]
        if kind == "clearinghouseState": return {"time": int(utcnow().timestamp()*1000), "marginSummary": {"accountValue": "100"}}
        raise ValueError("Unexpected query")
    gateway.info = info
    kwargs = dict(store=store, intents=intents, plans=plans, capital=capital, service=service, owner=ADDRESS,
        intent_id=intent["id"], gateway=gateway, key=SecretStr(OTHER_KEY), root=tmp_path / "isolated", rules=rules)
    execution = UserExecution(**kwargs)
    return execution, gateway, modes, state, kwargs


def test_private_plan_reaches_isolated_journal_but_even_arming_cannot_reach_network(context):
    execution, gateway, _, _, _ = context
    trade = asyncio.run(execution.stage_offline())
    assert D(trade["entry"]["quantity"]) <= D(execution.plan["entry"]["quantity"])
    assert execution.ledger.snapshot()["control"]["account"] == ADDRESS
    assert not execution.status()["exchange_submission_enabled"]
    with pytest.raises(ValueError): asyncio.run(execution.stage_offline())
    execution.broker.armed = True  # Deliberate accidental local configuration.
    asyncio.run(execution.broker.dispatch(trade["id"]))
    assert not gateway.writes  # Writer wrapper remains closed independently.
    assert execution.ledger.commands(trade["id"])[0]["status"] == "unknown"


@pytest.mark.parametrize("failure", ["mode", "revoked", "costs", "account", "history"])
def test_user_permissions_and_accounting_are_refreshed_and_fail_closed(context, failure):
    execution, gateway, modes, state, _ = context
    if failure == "mode": modes[ADDRESS] = "unifiedAccount"
    if failure == "revoked": state["builder_approval_status"] = "not_approved"
    if failure == "costs": state["reported_taker_rate"] = "0.00046"
    if failure == "account": state["equity"] = "999"
    if failure == "history":
        async def incomplete(*args): raise ValueError("Truncated history")
        execution.service.capital_history = incomplete
    with pytest.raises(ValueError): asyncio.run(execution.stage_offline())
    assert not gateway.writes
    if failure == "history": assert execution.capital.get(ADDRESS)["halt_reason"]
    assert execution.intents.get(ADDRESS, execution.intent["id"])["status"] == "claimed_offline"


def test_offline_user_flow_reuses_actual_fill_protection_and_recovers_without_entry_guard(context):
    execution, gateway, _, _, _ = context
    trade = asyncio.run(execution.stage_offline())
    # Test-only in-memory exchange injection. No real gateway/network writes.
    execution.broker.gateway = gateway
    execution.broker.armed = True
    trade = asyncio.run(execution.broker.dispatch(trade["id"]))
    assert trade["status"] == "protected"
    assert D(trade["protected_quantity"]) == gateway.partial
    for kind, action in gateway.writes:
        if kind == "entry": assert action["builder"]["f"] == 20
        else: assert "builder" not in action
    assert trade["audit_binding"]["user_plan_hash"] == execution.plan["plan_hash"]
    async def unavailable(*args): raise ValueError("Accounting outage")
    execution.broker.entry_guard = unavailable
    assert asyncio.run(execution.broker.reconcile(trade["id"]))["status"] == "protected"
    assert sum(kind == "entry" for kind, _ in gateway.writes) == 1


def test_exact_plan_limits_expiry_and_user_key_binding_are_enforced(context):
    execution, gateway, _, _, kwargs = context
    trade = asyncio.run(execution.stage_offline())
    from lobster.execution.contracts import OrderSpec
    order = OrderSpec.model_validate(trade["entry"])
    now = int(utcnow().timestamp()*1000)
    for changed in [order.model_copy(update={"quantity": order.quantity*2}), order.model_copy(update={"price": order.price + 100})]:
        with pytest.raises(ValueError): execution.broker.signer.order(changed, now, now)
    with pytest.raises(ValueError): execution.broker.signer.order(order, execution.intent["expires_ms"], execution.intent["expires_ms"])
    wrong = dict(kwargs, key=SecretStr("0x"+"0"*63+"3"))
    with pytest.raises(ValueError, match="profile"): UserExecution(**wrong)


def test_actual_user_guard_rechecks_revocation_after_leverage_before_entry(context):
    execution, gateway, _, state, _ = context
    trade = asyncio.run(execution.stage_offline())
    send = gateway.send
    async def revoke_after_leverage(envelope):
        result = await send(envelope)
        if envelope["action"]["type"] == "updateLeverage": state["builder_approval_status"] = "not_approved"
        return result
    gateway.send = revoke_after_leverage
    execution.broker.gateway = gateway  # Explicit in-memory fixture only.
    execution.broker.armed = True
    with pytest.raises(ValueError, match="approval"):
        asyncio.run(execution.broker.dispatch(trade["id"]))
    assert [kind for kind, _ in gateway.writes] == ["leverage"]
    assert not gateway.position


def test_unclaimed_or_different_consent_cannot_reuse_a_staged_entry(context):
    execution, gateway, _, _, kwargs = context
    with pytest.raises(ValueError, match="claimed"):
        asyncio.run(execution.broker.stage(execution.setup))
    asyncio.run(execution.stage_offline())
    fresh = execution.intents.prepare(ADDRESS, execution.plan)
    execution.intents.verify_local(ADDRESS, fresh["id"], sign(fresh["typed_data"]))
    other = UserExecution(**dict(kwargs, intent_id=fresh["id"]))
    other.intents.claim_offline(ADDRESS, fresh["id"], other.plan)
    with pytest.raises(ValueError, match="different"):
        asyncio.run(other.broker.stage(other.setup))
    assert not gateway.writes
