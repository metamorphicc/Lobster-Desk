"""Non-executing pilot budget rehearsal. Never imports an exchange transport."""
from decimal import Decimal as D
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from ..domain import Contract, utcnow
from ..execution.contracts import fingerprint


def exact(value):
    if not isinstance(value, str): raise ValueError("Money/rates must be exact decimal strings.")
    return value


Money = Annotated[D, BeforeValidator(exact), Field(ge=0, allow_inf_nan=False)]


class PilotPlan(Contract):
    schema_version: Literal["lobster-pilot-plan-v1"] = "lobster-pilot-plan-v1"
    market: Literal["BTC"] = "BTC"
    max_leverage: int = Field(default=2, ge=1, le=2, strict=True)
    max_entry_notional: Money = D("50")
    owner_capital_budget: Money | None = None
    absolute_loss_budget: Money | None = None
    reserve_floor: Money | None = None
    execution_enabled: Literal[False] = False

    @model_validator(mode="after")
    def limits(self):
        if not D("10") <= self.max_entry_notional <= D("50"):
            raise ValueError("Initial rehearsal entries must stay between $10 and $50.")
        budget, loss, reserve = self.owner_capital_budget, self.absolute_loss_budget, self.reserve_floor
        if budget is not None and (budget <= 0 or (loss is not None and (loss <= 0 or loss > budget * D("0.05")))
                                  or (reserve is not None and reserve > budget)):
            raise ValueError("Capital/loss/reserve limits are inconsistent or exceed 5% initial drawdown.")
        return self


class PilotObservation(Contract):
    provenance: Literal["offline_fixture", "owner_supplied_unverified"]
    equity: Money
    initial_equity: Money
    net_external_cashflow: Annotated[D, BeforeValidator(exact), Field(allow_inf_nan=False)]
    day_performance_reference: Money
    high_water_performance: Money
    complete_history: bool = Field(strict=True)
    fresh: bool = Field(strict=True)
    unidentified_exposure: bool = Field(strict=True)
    unresolved_commands: int = Field(ge=0, strict=True)
    protection_confirmed: bool = Field(strict=True)
    has_exposure: bool = Field(strict=True)
    latched_halt: bool = Field(strict=True)


def assess(plan: PilotPlan, observation: PilotObservation | None):
    reasons = []
    configured = all(getattr(plan, key) is not None for key in ("owner_capital_budget", "absolute_loss_budget", "reserve_floor"))
    if not configured: reasons.append("Owner capital, absolute loss budget and reserve floor are unspecified.")
    measures = None
    if observation is None:
        reasons.append("No independently reviewed pilot observations are supplied.")
    else:
        value = observation
        performance = value.equity - value.net_external_cashflow
        initial = value.initial_equity
        basis = min(initial, value.equity)
        total_loss = max(D("0"), initial - performance)
        daily_loss = max(D("0"), value.day_performance_reference - performance)
        drawdown = max(D("0"), value.high_water_performance - performance)
        if initial <= 0 or value.day_performance_reference <= 0 or value.high_water_performance < performance:
            reasons.append("Invalid/non-positive performance references.")
        if not value.complete_history or not value.fresh: reasons.append("Fresh complete accounting history is required.")
        if value.unidentified_exposure or value.unresolved_commands: reasons.append("Unidentified exposure or unresolved commands require reconciliation.")
        if value.has_exposure and not value.protection_confirmed: reasons.append("Actual exposed size lacks confirmed native protection.")
        if value.latched_halt: reasons.append("Latched halt requires owner review; a new observation cannot clear it.")
        if basis <= 0 or daily_loss >= basis * D("0.01") or drawdown >= basis * D("0.05"):
            reasons.append("Daily loss or drawdown limit reached.")
        if configured:
            if initial > plan.owner_capital_budget: reasons.append("Initial equity exceeds the owner's pilot capital budget.")
            if total_loss >= plan.absolute_loss_budget: reasons.append("Absolute loss budget reached.")
            if value.equity < plan.reserve_floor: reasons.append("Reserve floor breached.")
        measures = {"cashflow_neutral_performance_balance": str(performance), "total_loss": str(total_loss),
            "daily_loss": str(daily_loss), "drawdown": str(drawdown), "loss_basis": str(basis),
            "is_realized_pnl": False, "provenance": value.provenance}
    report = {"schema": "lobster-pilot-rehearsal-v1", "created_at": utcnow().isoformat(),
        "plan": plan.model_dump(mode="json"), "plan_hash": fingerprint(plan.model_dump(mode="json")),
        "observation": observation.model_dump(mode="json") if observation else None,
        "rehearsal_checks_passed": not reasons, "blockers": reasons, "measures": measures,
        "execution_authorized": False, "mainnet_implemented": False, "production_verified": False,
        "note": "A local calculation over supplied observations. Passing checks cannot activate trading or certify exchange receipts, organic volume, retention or profitability."}
    return report | {"report_hash": fingerprint(report)}
