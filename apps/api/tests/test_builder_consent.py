from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal as D

from eth_account import Account
from eth_account.messages import encode_typed_data
from hyperliquid.utils.signing import sign_approve_builder_fee
from pydantic import ValidationError
import pytest

from lobster.domain import utcnow
from lobster.execution.contracts import fingerprint
from lobster.users.contracts import UserTestnetSettings
from lobster.users.fees import ConsentInput, FeeQuoteInput, consent_plan, fee_quote

# Public offline test vector. Never fund this key or use it as a real wallet.
KEY = "0x" + "0" * 63 + "1"
OWNER = Account.from_key(KEY).address.lower()
BUILDER = "0x" + "c" * 40


def observation():
    return {"network": "testnet", "address": OWNER, "stale": False, "observed_at": utcnow().isoformat(),
        "reported_taker_rate": "0.00045", "builder_address": BUILDER, "builder_fee_tenths_bps": 20,
        "builder_fee_percent": "0.02%", "approved_builder_fee_tenths_bps": 10, "builder_approval_status": "below_requested"}


@pytest.mark.parametrize("notional,exchange,builder,total", [("50", "0.02250", "0.01", "0.03250"),
    ("0.01", "0.0000045", "0.000002", "0.0000065"), ("1000000", "450", "200", "650")])
def test_exact_cost_illustration_without_authority(notional, exchange, builder, total):
    quote = fee_quote(FeeQuoteInput(address=OWNER, notional=notional), observation())
    assert D(quote["estimated_exchange_fee"]) == D(exchange)
    assert D(quote["hypothetical_builder_fee"]) == D(builder)
    assert D(quote["estimated_total_if_applied"]) == D(total)
    assert quote["builder_approval_status"] == "below_requested"
    assert not quote["fee_collection_enabled"] and not quote["order_submission_enabled"]


@pytest.mark.parametrize("notional", [True, 50.0, "NaN", "Infinity", "0", "-10", "1000001", "1.000000001"])
def test_bad_cost_input_is_refused(notional):
    with pytest.raises(ValidationError):
        FeeQuoteInput(address=OWNER, notional=notional)


@pytest.mark.parametrize("intent,rate", [("approve", "0.02%"), ("revoke", "0%")])
def test_unsigned_consent_matches_official_sdk_offline(intent, rate):
    plan = consent_plan(ConsentInput(address=OWNER, intent=intent), UserTestnetSettings(_env_file=None, builder_address=BUILDER), observation())
    assert not plan["signed"] and not plan["submitted"]
    assert plan["action"]["maxFeeRate"] == rate and plan["action"]["hyperliquidChain"] == "Testnet"
    assert plan["typed_data"]["domain"]["chainId"] == int("66eee", 16)
    wallet = Account.from_key(KEY)
    sdk_signature = sign_approve_builder_fee(wallet, deepcopy(plan["action"]), False)
    message = encode_typed_data(full_message=plan["typed_data"])
    local = Account.sign_message(message, KEY)
    assert sdk_signature == {"r": hex(local.r), "s": hex(local.s), "v": local.v}
    assert Account.recover_message(message, signature=local.signature).lower() == OWNER
    assert (datetime.fromisoformat(plan["preview_valid_until"]) - datetime.fromisoformat(plan["created_at"])).total_seconds() == 30
    digest = plan.pop("plan_hash")
    assert fingerprint(plan) == digest
    for field, changed in [("hyperliquidChain", "Mainnet"), ("builder", "0x" + "b" * 40), ("maxFeeRate", "0.1%"), ("nonce", plan["action"]["nonce"] + 1)]:
        modified = deepcopy(plan["typed_data"])
        modified["message"][field] = changed
        assert Account.recover_message(encode_typed_data(full_message=modified), signature=local.signature).lower() != OWNER


def test_missing_builder_self_fee_stale_and_wrong_account_cannot_create_plan():
    body = ConsentInput(address=OWNER, intent="approve")
    for settings, account in [
        (UserTestnetSettings(_env_file=None), observation()),
        (UserTestnetSettings(_env_file=None, builder_address=OWNER), observation()),
        (UserTestnetSettings(_env_file=None, builder_address=BUILDER), observation() | {"stale": True}),
        (UserTestnetSettings(_env_file=None, builder_address=BUILDER), observation() | {"address": BUILDER}),
        (UserTestnetSettings(_env_file=None, builder_address=BUILDER), observation() | {"network": "mainnet"})]:
        with pytest.raises(ValueError):
            consent_plan(body, settings, account)
    with pytest.raises(ValidationError):
        ConsentInput(address=OWNER, intent="approve", builder=OWNER, hyperliquidChain="Mainnet")


@pytest.mark.parametrize("seconds", [-60, 60])
def test_timestamp_is_rechecked_even_if_stale_flag_was_false(seconds):
    account = observation() | {"observed_at": (utcnow() + timedelta(seconds=seconds)).isoformat()}
    with pytest.raises(ValueError, match="fresh"):
        fee_quote(FeeQuoteInput(address=OWNER, notional="50"), account)
    with pytest.raises(ValueError, match="fresh"):
        consent_plan(ConsentInput(address=OWNER, intent="approve"), UserTestnetSettings(_env_file=None, builder_address=BUILDER), account)
