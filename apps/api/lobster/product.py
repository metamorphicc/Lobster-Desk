"""Public product projection: mainnet market and registered project activity only.

Paper balances, fills, fixture reviews and operational errors never become
product metrics. Missing/stale exchange capital remains null, never seeded cash.
"""
from .domain import utcnow
from .execution.public import project_activity


def product_state(runtime):
    market = runtime.product_market
    if market is not None and (market.source != "hyperliquid" or not -2 <= (utcnow() - market.timestamp).total_seconds() <= 15):
        market = None
    activity = project_activity(runtime.store, network="mainnet")
    journals = activity["journals"]
    # Multiple accounts need an explicit aggregation policy, not a guessed sum.
    capital = journals[0]["capital"] if len(journals) == 1 else None
    episodes = []
    for journal in journals:
        for trade in journal["trades"]:
            episodes.append({"id": trade["id"], "pitch": trade["pitch"], "status": trade["status"],
                "created_at": trade["created_at"], "expires_at": None,
                "reason": {"protected": "Position open. Stop protection confirmed.", "closed": "Trade closed.",
                    "staged": "Setup reviewed. Awaiting execution."}.get(trade["status"], "Execution status recorded in the journal."),
                "reviews": trade["reviews"], "risk": None, "approval_hash": trade["approval_hash"], "position_id": None})
    episodes.sort(key=lambda ep: ep["created_at"], reverse=True)
    return {"market": market.model_dump(mode="json") if market else None, "episodes": episodes,
        "positions": [], "events": [], "last_event_id": 0,
        "account": {"equity": capital["equity"] if capital else None,
            "performance_pnl": capital["net_equity_change_excluding_cashflows"] if capital else None,
            "observed_at": capital["observed_at"] if capital else None},
        "policy": runtime.store.policy.model_dump(mode="json"),
        "service": {"execution_mode": "project", "market_source": "hyperliquid", "data_stale": market is None},
        "activity": activity}
