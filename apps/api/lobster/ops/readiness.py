"""Local observations and alerts. Never mutates a ledger or calls an exchange."""

from collections import Counter

from ..domain import utcnow


def readiness(runtime, testnet=None) -> dict:
    now = utcnow()
    checks, alerts, blockers = [], [], []
    def check(key, label, ok):
        checks.append({"key": key, "label": label, "status": "ok" if ok else "blocked"})
    def alert(code, severity, scope, message):
        alerts.append({"code": code, "severity": severity, "scope": scope, "message": message})
    counters = None
    try:
        counters = runtime.store.operational_snapshot()
        check("database", "Paper database readable", True)
    except Exception:
        check("database", "Paper database readable", False)
        alert("database_unavailable", "critical", "service", "Paper account observations are unavailable. Check the local database.")
        blockers.append("Paper account state unavailable")
    check("worker_enabled", "Local worker enabled", runtime.settings.worker_enabled)
    if not runtime.settings.worker_enabled:
        alert("worker_disabled", "warning", "service", "The local worker is disabled. Reviews and paper protection do not advance.")
        blockers.append("Worker disabled")
    workers = {}
    for name, tick in (("market", runtime.last_market_tick), ("decision", runtime.last_decision_tick)):
        task = runtime.tasks.get(name)
        running = task is not None and not task.done()
        age = (now - tick).total_seconds() if tick else None
        limit = max(30, runtime.settings.market_poll_seconds * 3) if name == "market" else max(90, runtime.settings.review_interval_seconds + 45)
        fresh_tick = age is not None and -2 <= age <= limit
        workers[name] = {"running": running, "last_tick_at": tick.isoformat() if tick else None,
            "age_seconds": round(age, 3) if age is not None else None, "deadline_seconds": limit}
        check(name + "_worker", name.capitalize() + " worker responding", running and fresh_tick)
        if runtime.settings.worker_enabled and not (running and fresh_tick):
            alert(name + "_worker_unavailable", "critical", "service", name.capitalize() + " worker has not completed a recent tick.")
            if name == "market":
                blockers.append("Market/protection worker unavailable")
    market = runtime.market
    age = (now - market.timestamp).total_seconds() if market else None
    fresh = age is not None and -2 <= age <= runtime.store.policy.max_data_age_seconds
    feed_ok = runtime.market_error is None
    decision_ok = runtime.worker_error is None
    source_ok = market is not None and market.source == runtime.settings.market_source
    check("market_source", "Market source matches configuration", source_ok)
    check("market_data", "Fresh market observation", fresh and feed_ok)
    check("decision_health", "Decision loop reports no worker error", decision_ok)
    if not fresh or not feed_ok or not source_ok:
        blockers.append("Fresh market data unavailable")
        alert("market_unavailable", "critical" if counters and counters["open_positions"] else "warning", "paper",
            "An open paper position lacks a fresh protection observation." if counters and counters["open_positions"] else "New paper entries wait for a fresh market observation.")
    if not decision_ok:
        alert("decision_error", "critical", "service", "The decision loop reports a worker error. Check local service logs.")
    budget = None
    if counters:
        if counters["paper_paused"]:
            blockers.append("Operator pause")
            alert("paper_paused", "warning", "paper", "The operator paused new paper entries; existing protection is independent.")
        if counters["paper_halt_reason"]:
            blockers.append("Latched paper risk halt")
            alert("paper_halted", "warning", "paper", "A latched risk halt blocks new paper entries. Investigate the recorded account reason.")
        if counters["open_positions"] or counters["reserved_entries"]:
            blockers.append("Paper execution slot occupied")
        budget = {"day": counters["review_budget_day"], "used": counters["review_calls_today"],
            "limit": runtime.settings.max_review_calls_per_day,
            "remaining": max(0, runtime.settings.max_review_calls_per_day - counters["review_calls_today"])}
        if budget["remaining"] == 0:
            alert("review_budget_exhausted", "warning", "paper", "The UTC review-call budget is exhausted. Existing protection is independent.")
    testnet_status = {"configured": False, "readable": None, "trade_statuses": {}, "halted": None}
    if testnet and testnet.ledger:
        testnet_status["configured"] = True
        try:
            local = testnet.ledger.snapshot()
            counts = dict(Counter(trade["status"] for trade in local["trades"]))
            testnet_status.update(readable=True, trade_statuses=counts, halted=bool(local["control"]["halt_reason"]))
            if any(counts.get(status) for status in ("submitting", "needs_reconciliation", "needs_review", "emergency", "needs_protection", "closing_cleanup")):
                alert("testnet_reconciliation", "critical", "testnet", "A local testnet intent needs owner-run reconciliation. This report does not query or modify exchange exposure.")
            if testnet_status["halted"]:
                alert("testnet_halted", "warning", "testnet", "The separate testnet execution ledger has a latched halt.")
        except Exception:
            testnet_status["readable"] = False
            alert("testnet_ledger_unavailable", "critical", "testnet", "The local testnet execution journal could not be read.")
    ready = all(item["status"] == "ok" for item in checks)
    return {"schema": "lobster-local-readiness-v1", "observed_at": now.isoformat(), "scope": "local-paper-runtime",
        "status": "ready" if ready else "not_ready", "service_ready": ready, "execution_mode": "paper",
        "production_verified": False, "exchange_execution_verified": False,
        "market_source": runtime.settings.market_source, "market_age_seconds": round(age, 3) if age is not None else None,
        "checks": checks, "workers": workers, "paper": counters, "review_budget": budget,
        "entry_blockers": blockers, "testnet": testnet_status, "alerts": alerts,
        "diagnostic_only": True, "note": "Observations do not authorize, pause or resume execution. Actual entries recheck all coded controls. Testnet state here is local journal state only."}
