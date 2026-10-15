import asyncio
from datetime import timedelta
from decimal import Decimal as D

from eth_account import Account
from hyperliquid.utils.signing import recover_agent_or_user_from_l1_action
from pydantic import SecretStr, ValidationError
import pytest

from lobster.agents import DemoReviewer
from lobster.domain import Capital, PitchInput, RiskPolicy, Snapshot, utcnow
from lobster.execution.contracts import BtcRules, ExchangeAccount, OrderSpec, ReviewedSetup, cloid, size_entry, wire
from lobster.execution.signer import TestnetSigner
from lobster.pipeline import Pipeline
from lobster.store import Store

# Public deterministic test fixture, intercepted/offline only. Never fund this key.
KEY = SecretStr("0x" + "0" * 63 + "1")
ADDRESS = "0x" + "2" * 40


@pytest.fixture
def rules():
    return BtcRules(asset_id=0, size_decimals=5, max_leverage=40)


@pytest.fixture
def setup(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'review.db'}")
    id = store.submit(PitchInput(author="QA trader", direction="long", entry="60000", stop="59400", target="61800",
                     thesis="A defined BTC breakout for offline execution tests."), "request-123")["id"]
    market = Snapshot(source="hyperliquid-testnet", price="60000", timestamp=utcnow())
    for _ in range(4):
        asyncio.run(Pipeline(store, DemoReviewer()).step(market))
    return ReviewedSetup.from_episode(store.get_episode(id), store.policy)


def context(setup, rules):
    return dict(setup=setup, market=Snapshot(source="hyperliquid-testnet", price="60000", timestamp=utcnow()),
        account=ExchangeAccount(address=ADDRESS, equity="1000", withdrawable="1000", open_order_count=0, observed_at=utcnow()),
        capital=Capital(equity="1000", available_cash="1000", day_start_equity="1000", high_water_equity="1000"),
        rules=rules, policy=RiskPolicy(), now=utcnow(), max_notional=D("50"))


def test_entry_size_uses_worst_permitted_price_and_signer_cap(setup, rules):
    order = size_entry(**context(setup, rules))
    assert order.price == D("60120")
    assert D("10") <= order.quantity * order.price <= D("50")
    assert order.quantity <= setup.approved_quantity
    assert order.quantity % rules.quantity_step == 0
    assert order.to_wire()["t"] == {"limit": {"tif": "Ioc"}}
    assert order.to_wire()["r"] is False


@pytest.mark.parametrize("change", [{"other_positions": True}, {"btc_size": D("0.001")},
                                    {"open_order_count": 1}, {"observed_at": utcnow() - timedelta(minutes=1)}])
def test_dirty_or_stale_account_cannot_enter(setup, rules, change):
    ctx = context(setup, rules)
    ctx["account"] = ctx["account"].model_copy(update=change)
    with pytest.raises(ValueError):
        size_entry(**ctx)


@pytest.mark.parametrize("source", ["demo", "hyperliquid"])
def test_other_market_networks_cannot_enter(setup, rules, source):
    ctx = context(setup, rules)
    ctx["market"] = ctx["market"].model_copy(update={"source": source})
    with pytest.raises(ValueError, match="Testnet"):
        size_entry(**ctx)


def test_missed_entry_is_not_chased(setup, rules):
    ctx = context(setup, rules)
    ctx["market"] = ctx["market"].model_copy(update={"price": D("60500")})
    with pytest.raises(ValueError, match="deviation"):
        size_entry(**ctx)


def test_expired_review_cannot_enter(setup, rules):
    ctx = context(setup, rules)
    ctx["setup"] = setup.model_copy(update={"expires_at": utcnow() - timedelta(seconds=1)})
    with pytest.raises(ValueError, match="expired"):
        size_entry(**ctx)


def test_review_veto_cannot_be_constructed(setup):
    with pytest.raises(ValidationError):
        ReviewedSetup.model_validate(setup.model_dump() | {"risk": {"verdict": "reject", "summary": "This setup is unsupported.", "evidence": ["No confirmation."]}})


def test_tampered_and_paper_episodes_are_rejected(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'test.db'}")
    ep = store.submit(PitchInput(author="Trader", direction="long", entry="60000", stop="59400", target="61800",
                     thesis="A defined breakout with a clear stop and target."), "request-123")
    with pytest.raises(ValueError, match="bound"):
        ReviewedSetup.from_episode(ep, store.policy)


@pytest.mark.parametrize("price,expected", [("60000.123", "60000"), ("0.0123456", "0.0"), ("61234", "61234")])
def test_price_precision(rules, price, expected):
    # Small values illustrate the BTC decimal cap; BTC trading rejects zero prices.
    assert rules.price(D(price)) == D(expected)


def test_wire_decimal_never_uses_scientific_notation():
    assert wire(D("0.00001000")) == "0.00001"
    assert wire(D("60000.000")) == "60000"
    assert wire(D("1E+5")) == "100000"


def test_signature_recovers_only_in_testnet_domain(setup, rules):
    signer = TestnetSigner(KEY, ADDRESS, rules)
    order = size_entry(**context(setup, rules))
    envelope = signer.order(order, 1700000000000, 1700000000000)
    args = (envelope["action"], envelope["signature"], None, envelope["nonce"], envelope["expiresAfter"])
    assert recover_agent_or_user_from_l1_action(*args, False) == signer.address
    assert recover_agent_or_user_from_l1_action(*args, True) != signer.address
    assert envelope["expiresAfter"] - envelope["nonce"] == 5000
    assert "builder" not in envelope["action"]
    assert KEY.get_secret_value() not in repr(signer)


def test_main_wallet_key_is_refused(rules):
    with pytest.raises(ValueError, match="main private key"):
        TestnetSigner(KEY, Account.from_key(KEY.get_secret_value()).address, rules)


def test_protection_is_reduce_only(rules):
    signer = TestnetSigner(KEY, ADDRESS, rules)
    order = OrderSpec(asset_id=0, side="sell", quantity="0.0005", price="59000", trigger_price="59400",
                      cloid=cloid("test", "stop"), kind="stop")
    envelope = signer.order(order, 1700000000000, 1700000000000)
    assert envelope["action"]["orders"][0]["r"] is True
    assert envelope["action"]["orders"][0]["t"]["trigger"]["tpsl"] == "sl"


@pytest.mark.parametrize("leverage", [0, 3, 20])
def test_signer_refuses_unsafe_leverage(rules, leverage):
    with pytest.raises(ValueError):
        TestnetSigner(KEY, ADDRESS, rules).leverage(leverage, 1700000000000, 1700000000000)


def test_signer_isolated_leverage(rules):
    action = TestnetSigner(KEY, ADDRESS, rules).leverage(2, 1700000000000, 1700000000000)["action"]
    assert action == {"type": "updateLeverage", "asset": 0, "isCross": False, "leverage": 2}


def test_signer_refuses_oversized_entry(rules):
    order = OrderSpec(asset_id=0, side="buy", quantity="0.01", price="60000", cloid=cloid("test", "entry"), kind="entry")
    with pytest.raises(ValueError, match="cap"):
        TestnetSigner(KEY, ADDRESS, rules).order(order, 1700000000000, 1700000000000)


def test_signer_refuses_wrong_asset_and_precision(rules):
    signer = TestnetSigner(KEY, ADDRESS, rules)
    order = OrderSpec(asset_id=1, side="buy", quantity="0.0005001", price="60000", cloid=cloid("test", "entry"), kind="entry")
    with pytest.raises(ValueError, match="precision"):
        signer.order(order, 1700000000000, 1700000000000)


@pytest.mark.parametrize("nonce", [1699999999999, 1700000001001])
def test_signer_refuses_old_or_far_future_nonce(rules, nonce):
    with pytest.raises(ValueError, match="Nonce"):
        TestnetSigner(KEY, ADDRESS, rules).leverage(1, nonce, 1700000000000)

