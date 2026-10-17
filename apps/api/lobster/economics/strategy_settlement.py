"""Attribute closed owned fills/funding to the pre-review verified author."""
from collections import defaultdict
from decimal import Decimal as D

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..execution.contracts import ReviewedSetup, fingerprint
from ..execution.ledger import Fill
from ..users.capital import Receipt
from ..users.strategies import UserStrategies


def allocations(runner, snapshot, reference):
    if not any(t.get("setup", {}).get("strategy_attribution") for t in snapshot["trades"]): return []
    groups, intervals, funding = defaultdict(list), {}, defaultdict(lambda: D(0))
    with Session(runner.ledger.engine) as db:
        for row in db.scalars(select(Fill)): groups[row.trade_id].append(row.payload)
        receipts = [row.payload for row in db.scalars(select(Receipt)) if row.payload["address"] == runner.settings.account
            and row.payload["stream"] == "funding" and reference["baseline_ms"] < row.payload["time"] <= reference["cursor_ms"]]
    for trade in snapshot["trades"]:
        fills = groups[trade["id"]]
        if fills:
            if trade["status"] != "closed": raise ValueError("Filled strategy attribution requires a closed trade.")
            intervals[trade["id"]] = (min(f["time"] for f in fills), max(f["time"] for f in fills))
    if sum((D(r["funding"]) for r in receipts), D(0)) != D(reference["funding_observed"]):
        raise ValueError("Per-trade funding receipts do not reconcile to the account reference.")
    for receipt in receipts:
        matches = [key for key, (start, end) in intervals.items() if start <= receipt["time"] <= end]
        if len(matches) != 1 and D(receipt["funding"]): raise ValueError("Funding cannot be assigned unambiguously to one owned trade.")
        if matches: funding[matches[0]] += D(receipt["funding"])
    result = []
    for trade in snapshot["trades"]:
        if not trade.get("setup", {}).get("strategy_attribution") or not groups[trade["id"]]: continue
        setup = ReviewedSetup.model_validate(trade["setup"])
        if fingerprint(setup.model_dump(mode="json")) != trade["setup_hash"]: raise ValueError("Stored strategy execution binding changed.")
        attribution = setup.strategy_attribution.model_dump()
        owner = UserStrategies(runner.store, "mainnet").resolve(attribution, trade["id"])
        binding = trade.get("audit_binding", {})
        if binding.get("strategy_owner") != owner or any(binding.get(k) != v for k, v in attribution.items()):
            raise ValueError("Execution does not match its verified strategy author.")
        fills = groups[trade["id"]]
        if any(f["feeToken"] != "USDC" for f in fills): raise ValueError("Unsupported strategy fee currency.")
        net = sum((D(f["closedPnl"])-D(f["fee"]) for f in fills), D(0)) + funding[trade["id"]]
        if net != net.quantize(D("0.000001")): raise ValueError("Strategy profit is not exact USDC.")
        result.append({"execution_id": fingerprint({"account": runner.settings.account, "trade": trade["id"]}),
            "strategy_id": attribution["strategy_id"], "owner": owner, "net_profit": str(net),
            "evidence_hash": fingerprint({"fills": fills, "funding": str(funding[trade["id"]]), "binding": binding})})
    return result
