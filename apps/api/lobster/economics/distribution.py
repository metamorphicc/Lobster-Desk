"""Owner-selected accounting policy. No wallet, transfers or burn authority."""

from decimal import Decimal as D, ROUND_DOWN
from typing import Literal

from ..domain import Contract, utcnow
from ..execution.contracts import fingerprint
from ..ops.pilot import Money
from .book import CREDITS, KINDS, TreasuryBook


def usdc(value: D) -> D:
    return value.quantize(D("0.000001"), rounding=ROUND_DOWN)


class DistributionPolicy(Contract):
    version: Literal["fees-bot60-team40-author50-v2"] = "fees-bot60-team40-author50-v2"
    builder_fee_tenths_bps: Literal[50] = 50
    fee_scope: Literal["entry_only"] = "entry_only"
    agent_share: Literal["0.6"] = "0.6"
    team_share: Literal["0.4"] = "0.4"
    strategy_author_share: Literal["0.5"] = "0.5"
    profit_buyback_share: Literal["0.5"] = "0.5"
    token_disposition: Literal["burn"] = "burn"
    # Unknown reserves suppress a spendable budget, not the chosen economics.
    operating_reserve: Money | None = None
    liability_reserve: Money | None = None
    tax_reserve: Money | None = None
    token_network: Literal["solana"] = "solana"
    token_contract: str | None = None
    transfers_enabled: Literal[False] = False
    holder_payouts_enabled: Literal[False] = False


def distribution(book: TreasuryBook, policy: DistributionPolicy | None = None) -> dict:
    policy = policy or DistributionPolicy()
    with book.transaction() as db:
        rows = book.read(db)
    return distribution_rows(rows, policy)


def distribution_rows(rows, policy):
    totals = {kind: sum((D(row["entry"]["amount"]) for row in rows if row["entry"]["kind"] == kind), D(0)) for kind in KINDS}
    cash = sum((amount if kind in CREDITS else -amount for kind, amount in totals.items()), D(0))
    # Refunds conservatively reduce builder proceeds; a refund exceeding receipts blocks.
    fees = max(D(0), totals["builder_receipt"] - totals["refund"])
    team = usdc(fees * D(policy.team_share))
    agents = fees - team  # Six-decimal rounding dust stays in trading capital.
    team_due = max(D(0), team - totals["team_payout"])
    from .sharing import author_balances
    balances = author_balances(rows)
    author_due = sum((D(b["outstanding"]) for b in balances.values()), D(0))
    author_entitlement = sum((D(b["entitlement"]) for b in balances.values()), D(0))
    user_net = sum((D(b["net_realized_profit"]) for b in balances.values()), D(0))
    net_profit = totals["trading_profit"] - totals["trading_loss"] - totals["expense"]
    # Cumulative entitlement minus ALL previous spending: rereading/restarting never
    # budgets 50% of the remaining half again. Deposits/builder fees are not profit.
    own_profit = net_profit - user_net
    eligible_buyback_profit = max(D(0), min(own_profit, net_profit-author_entitlement))
    entitlement = usdc(eligible_buyback_profit * D(policy.profit_buyback_share))
    pending = max(D(0), entitlement - totals["buyback_spend"])
    blockers = []
    if totals["refund"] > totals["builder_receipt"]: blockers.append("Refunds exceed recorded builder receipts.")
    if totals["team_payout"] > team:
        blockers.append("Recorded payouts exceed their earmarked fee allocation.")
    if any(D(b["overpaid_after_losses"]) for b in balances.values()): blockers.append("Prior author payouts exceed current strategy entitlement; recover strategy losses before further allocations.")
    if totals["buyback_spend"] > entitlement:
        blockers.append("Past buybacks exceed current net-profit entitlement; recover losses before allocating again.")
    reserves = (policy.operating_reserve, policy.liability_reserve, policy.tax_reserve)
    budget = None
    if any(value is None for value in reserves):
        blockers.append("Operating, liability and tax reserves are unspecified.")
    else:
        free = max(D(0), cash - team_due - author_due - sum(reserves, D(0)))
        budget = D(0) if blockers else usdc(min(pending, free))
    report = {"schema": "lobster-distribution-v1", "created_at": utcnow().isoformat(),
        "policy": policy.model_dump(mode="json"), "record_count": len(rows),
        "provenance": rows[0]["entry"]["provenance"] if rows else None,
        "receipt_chain_head": rows[-1]["record_hash"] if rows else None,
        "recorded_cash": str(cash), "received_builder_fees_net_refunds": str(fees),
        "fee_allocation": {"agents": str(agents), "team": str(team)},
        "outstanding_earmarks": {"team": str(team_due), "strategy_authors": str(author_due)},
        "user_strategy_profit": {"net_realized": str(user_net), "author_entitlement": str(author_entitlement),
            "author_paid": str(totals["author_payout"]), "author_outstanding": str(author_due),
            "bot_retained": str(user_net-author_entitlement)},
        "own_strategy_profit_after_expenses": str(own_profit),
        "net_realized_trading_profit_after_expenses": str(net_profit),
        "loss_carryforward": str(max(D(0), -net_profit)),
        "lifetime_buyback_entitlement": str(entitlement), "recorded_buyback_spend": str(totals["buyback_spend"]),
        "unspent_buyback_entitlement": str(pending),
        "reserve_bounded_buyback_budget": str(budget) if budget is not None else None,
        "recorded_team_paid": str(totals["team_payout"]),
        "blockers": blockers, "transfers_authorized": False, "receipts_authenticated": False,
        "burns_verified": False, "holder_payouts_enabled": False,
        "note": "Received fees: 60% bot / 40% team. Net realized user-strategy profit: 50% author / 50% bot, with strategy loss recovery. User-strategy profit cannot fund token buybacks. Historical retired-payment receipts remain cash debits. Allocations are liabilities, not completed transfers."}
    return report | {"report_hash": fingerprint(report)}
