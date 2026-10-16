"""Closed-bar signals and Decimal next-bar simulation. No generated code/eval."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from ..domain import Capital, PitchInput, RiskPolicy, Snapshot
from ..risk import assess
from .contracts import Bar, Dataset, Strategy, HOUR


def signal(strategy: Strategy, bars: list[Bar]) -> str | None:
    if len(bars) <= strategy.lookback: return None
    history, latest = bars[-strategy.lookback-1:-1], bars[-1]
    mean = sum((bar.close for bar in history), D(0)) / len(history)
    fast = sum((bar.close for bar in bars[-strategy.fast:]), D(0)) / strategy.fast
    threshold = D(strategy.threshold_bps) / 10000
    if strategy.family == "trend":
        if fast > mean * (1 + threshold): return "long"
        if fast < mean * (1 - threshold): return "short"
    elif strategy.family == "breakout":
        if latest.close > max(b.high for b in history) * (1 + threshold): return "long"
        if latest.close < min(b.low for b in history) * (1 - threshold): return "short"
    else:
        if latest.close < mean * (1 - threshold): return "long"
        if latest.close > mean * (1 + threshold): return "short"
    return None


def pitch_for(strategy: Strategy, direction: str, price: D) -> PitchInput:
    sign = D(1) if direction == "long" else D(-1)
    entry = price.quantize(D("0.01"))
    return PitchInput(author="Tank Research", direction=direction, entry=entry,
        stop=(entry * (1 - sign * strategy.stop_fraction)).quantize(D("0.01")),
        target=(entry * (1 + sign * strategy.stop_fraction * strategy.reward_risk)).quantize(D("0.01")),
        leverage=1, thesis=f"Research {strategy.digest[:12]} / {strategy.family}: {strategy.hypothesis}"[:1200])


def backtest(dataset: Dataset, strategy: Strategy, start: int, end: int, *, stress: bool = False) -> dict:
    dataset = Dataset.model_validate(dataset.model_dump(mode="json"))
    strategy = Strategy.model_validate(strategy.model_dump(mode="json"))
    if not strategy.lookback + 1 <= start < end <= len(dataset.bars): raise ValueError("Invalid chronological test window.")
    policy = RiskPolicy()
    if stress:
        policy = policy.model_copy(update={"fee_rate": policy.fee_rate * 2, "slippage_rate": policy.slippage_rate * 2})
    cash, high, day_start = D(1000), D(1000), D(1000)
    day, halted, position = None, False, None
    trades, fees, funding, curve = [], D(0), D(0), []
    max_drawdown = D(0)
    rates = {rate.time // HOUR * HOUR: rate.rate for rate in dataset.funding}

    def close(reference, time, reason):
        nonlocal position, cash, fees
        p = position
        fill = reference * (1 - p["sign"] * policy.slippage_rate)
        exit_fee = fill * p["quantity"] * policy.fee_rate
        pnl = (fill - p["entry"]) * p["quantity"] * p["sign"] - p["entry_fee"] - exit_fee + p["funding"]
        cash += (fill - p["entry"]) * p["quantity"] * p["sign"] - exit_fee
        fees += exit_fee
        trades.append({"entry_time": p["time"], "exit_time": time, "direction": p["direction"],
            "entry": str(p["entry"]), "exit": str(fill), "quantity": str(p["quantity"]),
            "net_pnl": str(pnl), "funding": str(p["funding"]), "reason": reason})
        position = None

    for index in range(start, end):
        bar = dataset.bars[index]
        now = datetime.fromtimestamp(bar.time, timezone.utc)
        if position is None and not halted:
            direction = signal(strategy, dataset.bars[:index])  # Never sees this bar.
            if direction and abs(bar.open - dataset.bars[index-1].close) / dataset.bars[index-1].close <= policy.max_entry_slip:
                pitch = pitch_for(strategy, direction, bar.open)
                snapshot = Snapshot(source=dataset.source, price=bar.open, timestamp=now)
                capital = Capital(equity=cash, available_cash=cash, day_start_equity=day_start, high_water_equity=high)
                result = assess(pitch, snapshot, capital, policy, now, now + timedelta(seconds=900))
                if result.approved:
                    sign = D(1) if direction == "long" else D(-1)
                    fill = bar.open * (1 + sign * policy.slippage_rate)
                    actual = pitch.model_copy(update={"entry": fill})
                    final = assess(actual, snapshot, capital, policy, now, now + timedelta(seconds=900))
                    if final.approved:
                        quantity = min(result.quantity, final.quantity)
                        fee = quantity * fill * policy.fee_rate
                        if quantity * fill >= policy.min_notional:
                            cash -= fee
                            fees += fee
                            position = {"time": bar.time, "index": index, "direction": direction, "sign": sign,
                                "entry": fill, "quantity": quantity, "entry_fee": fee, "stop": pitch.stop, "target": pitch.target, "funding": D(0)}
        if position:
            p = position
            stop_hit = bar.low <= p["stop"] if p["sign"] == 1 else bar.high >= p["stop"]
            target_hit = bar.high >= p["target"] if p["sign"] == 1 else bar.low <= p["target"]
            # A funding boundary at the open is not charged to a new entry.
            # For an existing intrabar exit, conservatively charge adverse funding
            # and never credit uncertain favorable funding within that exit bar.
            raw_funding = -p["sign"] * p["quantity"] * bar.close * rates[bar.time + HOUR]
            charge = min(D(0), raw_funding) if stop_hit or target_hit else raw_funding
            cash += charge
            funding += charge
            p["funding"] += charge
            if stop_hit:
                reference = min(bar.open, p["stop"]) if p["sign"] == 1 else max(bar.open, p["stop"])
                close(reference, bar.time + HOUR, "stop")  # Stop wins ambiguous OHLC bars.
            elif target_hit: close(p["target"], bar.time + HOUR, "target")
            elif index - p["index"] + 1 >= strategy.max_holding_bars: close(bar.close, bar.time + HOUR, "time_limit")
        equity = cash + ((bar.close - position["entry"]) * position["quantity"] * position["sign"] if position else 0)
        high = max(high, equity)
        max_drawdown = max(max_drawdown, (high - equity) / high)
        # Like the paper core, thresholds are latched; crossing a UTC boundary
        # never clears the previous day's loss. Intrabar path remains an OHLC approximation.
        if equity <= day_start * (1 - policy.daily_loss_fraction) or equity <= high * (1 - policy.drawdown_fraction):
            halted = True
            if position: close(bar.close, bar.time + HOUR, "risk_halt")
        if now.date() != day:
            day, day_start = now.date(), cash + ((bar.close - position["entry"]) * position["quantity"] * position["sign"] if position else 0)
        curve.append(str(equity))
    if position: close(dataset.bars[end-1].close, dataset.bars[end-1].time + HOUR, "window_end")
    high = max(high, cash)
    max_drawdown = max(max_drawdown, (high - cash) / high)
    gains = sum((max(D(0), D(t["net_pnl"])) for t in trades), D(0))
    losses = -sum((min(D(0), D(t["net_pnl"])) for t in trades), D(0))
    return {"start": start, "end": end, "initial_equity": "1000", "final_equity": str(cash),
        "net_pnl": str(cash - 1000), "return_fraction": str(cash / 1000 - 1), "max_drawdown_fraction": str(max_drawdown),
        "trade_count": len(trades), "win_count": sum(D(t["net_pnl"]) > 0 for t in trades),
        "profit_factor": str(gains / losses) if losses else None, "fees": str(fees), "funding": str(funding),
        "halted": halted, "stress": stress, "trades": trades,
        "limitations": "Hourly OHLC path approximation; stop-first ambiguous bars, adverse gap fills, approximate funding notional, no order-book liquidity model. No live profitability claim."}


def passes(result: dict) -> bool:
    return result["trade_count"] >= 8 and D(result["net_pnl"]) > 0 and D(result["max_drawdown_fraction"]) <= D("0.03") and not result["halted"]


def evaluate(dataset: Dataset, candidates: list[Strategy]) -> dict:
    if not 1 <= len(candidates) <= 3 or len({s.digest for s in candidates}) != len(candidates):
        raise ValueError("A bounded unique cohort is required.")
    n = len(dataset.bars)
    development_end, validation_end = n * 6 // 10, n * 8 // 10
    rows = []
    for strategy in candidates:
        development = backtest(dataset, strategy, strategy.lookback + 1, development_end)
        validation = backtest(dataset, strategy, development_end, validation_end)
        stress = backtest(dataset, strategy, development_end, validation_end, stress=True)
        eligible = passes(development) and passes(validation) and passes(stress)
        rows.append({"strategy": strategy.model_dump(mode="json"), "strategy_hash": strategy.digest,
            "development": development, "validation": validation, "stress": stress,
            "selection_eligible": eligible, "holdout": None, "paper_candidate": False})
    # The final 20% is opened ONCE for the validation winner. A failed winner
    # cannot be replaced with a runner-up after inspecting this cohort's holdout.
    eligible = [row for row in rows if row["selection_eligible"]]
    winner = max(eligible, key=lambda r: D(r["validation"]["net_pnl"])) if eligible else None
    if winner:
        winner["holdout"] = backtest(dataset, Strategy.model_validate(winner["strategy"]), validation_end, n)
        winner["paper_candidate"] = passes(winner["holdout"])
    return {"schema": "lobster-research-evaluation-v1", "dataset_hash": dataset.digest,
        "split": {"development_end": development_end, "validation_end": validation_end, "end": n},
        "candidates": rows, "selected_hash": winner["strategy_hash"] if winner and winner["paper_candidate"] else None,
        "execution_mode": "paper", "production_verified": False}
