from datetime import timedelta
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from lobster.domain import Capital, PitchInput, RiskPolicy, Snapshot, utcnow
from lobster.risk import assess


@pytest.fixture
def context():
    now = utcnow()
    return dict(
        pitch=PitchInput(author="Trader", direction="long", entry="60000", stop="59400",
                         target="61200", thesis="Breakout with a defined invalidation level."),
        market=Snapshot(source="demo", price="60000", timestamp=now),
        capital=Capital(equity="1000", available_cash="1000", day_start_equity="1000",
                        high_water_equity="1000"),
        policy=RiskPolicy(), now=now, expires_at=now + timedelta(minutes=15))


def test_size_respects_loss_notional_and_cash(context):
    result = assess(**context)
    assert result.approved
    assert result.planned_loss <= D("2.50")
    assert result.notional <= D("250")
    assert result.margin + result.notional * context["policy"].fee_rate <= D("1000")
    assert result.quantity % D("0.00001") == 0


@pytest.mark.parametrize("change", [
    {"paused": True}, {"occupied": True}, {"equity": D("990")},
    {"high_water_equity": D("1100")}, {"available_cash": D("0")},
    {"equity": D("0")}, {"day_start_equity": D("0")},
])
def test_capital_failures_veto(context, change):
    context["capital"] = context["capital"].model_copy(update=change)
    assert not assess(**context).approved


@pytest.mark.parametrize("change", [
    {"leverage": 3}, {"stop": D("60500")}, {"target": D("60300")},
    {"stop": D("60000")}, {"stop": D("59999")}, {"stop": D("55000")},
])
def test_invalid_setups_veto(context, change):
    context["pitch"] = context["pitch"].model_copy(update=change)
    assert not assess(**context).approved


@pytest.mark.parametrize("seconds", [-30, 30])
def test_stale_and_future_data_veto(context, seconds):
    context["market"] = context["market"].model_copy(
        update={"timestamp": context["now"] + timedelta(seconds=seconds)})
    assert not assess(**context).approved


def test_expiry_veto(context):
    context["expires_at"] = context["now"]
    assert not assess(**context).approved


def test_below_minimum_is_skipped(context):
    context["capital"] = Capital(equity="10", available_cash="10", day_start_equity="10", high_water_equity="10")
    assert not assess(**context).approved


def test_short_position(context):
    context["pitch"] = context["pitch"].model_copy(update={"direction": "short", "stop": D("60600"), "target": D("58800")})
    assert assess(**context).approved


@pytest.mark.parametrize("change", [{"entry": "NaN"}, {"entry": "Infinity"}, {"symbol": "ETH"},
                                    {"entry": "0"}, {"entry": "60000.001"}, {"tools": ["withdraw"]}])
def test_input_contract_rejects_unsafe_values(context, change):
    with pytest.raises(ValidationError):
        PitchInput.model_validate(context["pitch"].model_dump() | change)

