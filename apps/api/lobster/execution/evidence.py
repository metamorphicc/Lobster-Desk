"""Read-only exchange observations for owner acceptance review, never a certificate."""

from ..domain import utcnow
from .contracts import TESTNET_URL, fingerprint


async def collect_evidence(workbench) -> dict:
    inspection = await workbench.inspect()
    ledger = inspection["ledger"]
    trades = (ledger or {}).get("trades", [])
    commands = [command for trade in trades for command in workbench.ledger.commands(trade["id"])] if ledger else []
    queried = [command for command in commands if command["kind"] in {"entry", "stop", "target", "close"}][-100:]
    orders, fills, errors = [], [], []
    for command in queried:
        try:
            response = await workbench.gateway.order_status(command["request"]["cloid"])
            observed = response.get("order", {})
            item = observed.get("order", {})
            matched = (response.get("status") == "order" and item.get("coin") == "BTC"
                and item.get("cloid") == command["request"]["cloid"]
                and item.get("side") == ("B" if command["request"]["side"] == "buy" else "A"))
            orders.append({"command_id": command["id"], "kind": command["kind"], "observed_at": utcnow().isoformat(), "identity_matches": matched,
                "exchange_status": observed.get("status") if matched else "unresolved",
                "order": {k: item[k] for k in ("oid", "cloid", "coin", "side", "origSz", "sz", "reduceOnly", "triggerPx", "isTrigger") if k in item} if matched else None})
        except Exception:
            errors.append({"query": "orderStatus", "command_id": command["id"], "error": "Exchange observation unavailable."})
    if inspection["account_address"]:
        try:
            owned = {int(order["order"]["oid"]) for order in orders if order["identity_matches"] and "oid" in order["order"]}
            seen = set()
            for fill in await workbench.gateway.fills():
                if fill.get("coin") != "BTC" or int(fill["oid"]) not in owned:
                    continue
                key = (int(fill["oid"]), int(fill["tid"]))
                if key in seen:
                    continue
                seen.add(key)
                fills.append({k: fill[k] for k in ("oid", "tid", "coin", "side", "px", "sz", "fee", "feeToken", "closedPnl", "time")})
        except Exception:
            errors.append({"query": "userFills", "error": "Exchange fill observation incomplete."})
    report = {"schema": "lobster-testnet-evidence-v1", "captured_at": utcnow().isoformat(), "endpoint": TESTNET_URL,
        "network": "testnet", "exchange_writes_attempted": False, "funded_acceptance_verified": False,
        "scope": "Current read-only observations plus local command references. This is not an acceptance certificate.",
        "account_address": inspection["account_address"], "api_wallet_address": inspection["api_wallet_address"],
        "inspection": {k: inspection[k] for k in ("checks", "error", "market", "rules", "account")},
        "local_intents": [{k: trade[k] for k in ("id", "status", "filled_quantity", "protected_quantity", "created_at")} for trade in trades],
        "command_count": len(commands), "order_queries_truncated": len(queried) < sum(c["kind"] in {"entry", "stop", "target", "close"} for c in commands),
        "orders": orders, "fills": fills, "errors": errors,
        "required_owner_cases": [{"case": case, "status": "pending_owner_review"} for case in (
            "API wallet approval and expiry", "Actual entry and partial fill", "Native stop execution",
            "Restart and timeout without duplicate entry", "Owned order cleanup", "Fee and funding reconciliation")],
        "limits": ["Latest 2000 fills only; absence is not proof of non-execution.",
                   "Current observations cannot prove historical stop coverage or restart behavior.",
                   "Report hash detects accidental changes; it is not an exchange signature."]}
    return report | {"report_hash": fingerprint(report)}
