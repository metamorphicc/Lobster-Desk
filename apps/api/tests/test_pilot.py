from decimal import Decimal as D

import pytest

from lobster.ops.pilot import PilotPlan, PilotObservation, assess


def plan():
    return PilotPlan(owner_capital_budget="1000", absolute_loss_budget="20", reserve_floor="900")


def observation(**changes):
    return PilotObservation(provenance="offline_fixture", **({"equity": "1000", "initial_equity": "1000", "net_external_cashflow": "0",
        "day_performance_reference": "1000", "high_water_performance": "1000", "complete_history": True,
        "fresh": True, "unidentified_exposure": False, "unresolved_commands": 0, "protection_confirmed": False,
        "has_exposure": False, "latched_halt": False} | changes))


def test_unspecified_plan_has_no_fabricated_production_metrics_or_activation():
    report = assess(PilotPlan(), None)
    assert report["measures"] is None and not report["rehearsal_checks_passed"]
    assert not assess(plan(), observation())["execution_authorized"]


@pytest.mark.parametrize("equity,cashflow", [("989", "0"), ("1989", "1000"), ("489", "-500")])
def test_deposit_cannot_hide_daily_loss_or_fund_recovery(equity, cashflow):
    report = assess(plan(), observation(equity=equity, net_external_cashflow=cashflow))
    assert not report["rehearsal_checks_passed"]
    assert D(report["measures"]["daily_loss"]) == D("11")


@pytest.mark.parametrize("changes", [{"complete_history": False}, {"fresh": False}, {"unidentified_exposure": True},
    {"unresolved_commands": 1}, {"latched_halt": True}, {"has_exposure": True}, {"high_water_performance": "999"}])
def test_recovery_and_accounting_gates_fail_closed(changes):
    assert not assess(plan(), observation(**changes))["rehearsal_checks_passed"]


@pytest.mark.parametrize("changes", [{"absolute_loss_budget": "51"}, {"max_leverage": 3}, {"execution_enabled": True},
    {"owner_capital_budget": 1000.0}, {"max_entry_notional": "51"}])
def test_pilot_cannot_relax_fixed_limits_or_accept_float_money(changes):
    with pytest.raises(ValueError): PilotPlan(**({"owner_capital_budget": "1000"} | changes))
