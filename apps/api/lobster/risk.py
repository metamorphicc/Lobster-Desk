"""Fail-closed deterministic controls, independent of the agent provider."""

from datetime import datetime
from decimal import Decimal, ROUND_DOWN

from .domain import Capital, PitchInput, RiskPolicy, RiskResult, Snapshot


def assess(pitch: PitchInput, market: Snapshot, capital: Capital,
           policy: RiskPolicy, now: datetime, expires_at: datetime) -> RiskResult:
    reasons: list[str] = []
    age = (now - market.timestamp).total_seconds()
    if age < -2 or age > policy.max_data_age_seconds:
        reasons.append("Market data is stale or timestamped in the future.")
    if now >= expires_at:
        reasons.append("The proposal has expired.")
    if capital.paused:
        reasons.append("New entries are paused by the operator.")
    if capital.occupied:
        reasons.append("The tank already has an open position or capital reservation.")
    if capital.equity <= 0 or capital.available_cash <= 0:
        reasons.append("No trading capital is available.")
    if capital.day_start_equity <= 0 or capital.high_water_equity <= 0:
        reasons.append("Capital reference values are invalid.")
    if capital.equity <= capital.day_start_equity * (1 - policy.daily_loss_fraction):
        reasons.append("The daily loss threshold has been reached.")
    if capital.equity <= capital.high_water_equity * (1 - policy.drawdown_fraction):
        reasons.append("The maximum drawdown threshold has been reached.")
    if pitch.leverage > policy.max_leverage:
        reasons.append(f"Leverage exceeds the {policy.max_leverage}x policy limit.")
    valid_levels = (pitch.stop < pitch.entry < pitch.target if pitch.direction == "long"
                    else pitch.target < pitch.entry < pitch.stop)
    if not valid_levels:
        reasons.append("Stop and target must sit on opposite sides of entry in the trade direction.")
    distance = abs(pitch.entry - pitch.stop)
    stop_fraction = distance / pitch.entry
    if not policy.min_stop_fraction <= stop_fraction <= policy.max_stop_fraction:
        reasons.append("Stop distance must be between 0.1% and 3% of entry.")
    if abs(pitch.entry - market.price) / market.price > policy.max_entry_distance:
        reasons.append("Entry is more than 3% away from the current market.")
    reward_risk = abs(pitch.target - pitch.entry) / distance if distance else Decimal("0")
    if reward_risk < policy.min_reward_risk:
        reasons.append("The gross reward-to-risk ratio is below 1.5.")
    if reasons:
        return RiskResult(approved=False, reasons=reasons, reward_risk=reward_risk,
                          policy_version=policy.version)

    # Both entry and stop execution costs reduce the risk budget.
    unit_loss = distance + (pitch.entry + pitch.stop) * (policy.fee_rate + policy.slippage_rate)
    by_risk = capital.equity * policy.risk_fraction / unit_loss
    by_notional = capital.equity * policy.max_notional_fraction / pitch.entry
    by_cash = capital.available_cash / (pitch.entry / pitch.leverage + pitch.entry * policy.fee_rate)
    quantity = (min(by_risk, by_notional, by_cash) / policy.quantity_step).to_integral_value(
        rounding=ROUND_DOWN) * policy.quantity_step
    notional = quantity * pitch.entry
    if quantity <= 0 or notional < policy.min_notional:
        return RiskResult(approved=False, reasons=["Risk-sized order falls below the $10 minimum notional."],
                          reward_risk=reward_risk, policy_version=policy.version)
    return RiskResult(approved=True,
        reasons=["Stop, loss budget, exposure, leverage and capital checks passed."],
        quantity=quantity, notional=notional, margin=notional / pitch.leverage,
        planned_loss=quantity * unit_loss, reward_risk=reward_risk, policy_version=policy.version)

