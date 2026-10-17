"""Exact realized strategy-author liabilities. Allocations never create cash."""
from collections import defaultdict
from decimal import Decimal as D, ROUND_DOWN


def author_balances(rows):
    pools, paid = defaultdict(lambda: D(0)), defaultdict(lambda: D(0))
    for row in rows:
        entry = row["entry"]
        for value in entry.get("strategy_allocations", []):
            pools[(value["owner"], value["strategy_id"])] += D(value["net_profit"])
        if entry["kind"] == "author_payout": paid[entry["beneficiary"]] += D(entry["amount"])
    balances = {}
    for owner in set(owner for owner, _ in pools) | set(paid):
        values = [net for (author, _), net in pools.items() if author == owner]
        entitlement = sum(((max(D(0), net)/2).quantize(D("0.000001"), rounding=ROUND_DOWN) for net in values), D(0))
        balances[owner] = {"strategy_count": len(values), "net_realized_profit": str(sum(values, D(0))),
            "entitlement": str(entitlement), "paid": str(paid[owner]), "outstanding": str(max(D(0), entitlement-paid[owner])),
            "overpaid_after_losses": str(max(D(0), paid[owner]-entitlement))}
    return balances
