"""Private immutable user order illustrations. No exchange action or nonce reservation."""

from datetime import datetime, timedelta
from decimal import Decimal as D, ROUND_DOWN
from uuid import uuid4

from pydantic import Field
from sqlalchemy import JSON, String, UniqueConstraint, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..domain import Contract, RiskPolicy, Snapshot, utcnow
from ..execution.contracts import BtcRules, ReviewedSetup, fingerprint
from .fees import require_fresh
from .service import amount


class PreviewInput(Contract):
    episode_id: str = Field(min_length=1, max_length=64)


class Base(DeclarativeBase):
    pass


class UserPlan(Base):
    __tablename__ = "user_order_plans"
    __table_args__ = (UniqueConstraint("address", "request_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    address: Mapped[str] = mapped_column(String(42), index=True)
    request_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)


def illustrate(episode: dict, address: str, account: dict, market: Snapshot, rules: BtcRules, policy: RiskPolicy,
               capital_reference: dict | None = None) -> dict:
    now = utcnow()
    setup = ReviewedSetup.from_episode(episode, policy)
    require_fresh(account, address)
    if capital_reference and (capital_reference["address"] != address or capital_reference["halt_reason"]):
        raise ValueError("User capital observations have a latched halt or identity mismatch. Owner review is required.")
    if market.source != "hyperliquid-testnet" or not -2 <= (now - market.timestamp).total_seconds() <= 15:
        raise ValueError("A fresh testnet market observation is required.")
    if setup.expires_at <= now:
        raise ValueError("The reviewed setup expired. Ask the tank to review a new pitch.")
    if account["positions"] or account["open_orders"]:
        raise ValueError("A dedicated user account with no existing positions or orders is required for this preview.")
    pitch = setup.pitch
    if pitch.leverage > min(policy.max_leverage, rules.max_leverage):
        raise ValueError("Requested leverage exceeds local or exchange limits.")
    buy = pitch.direction == "long"
    if not (market.price >= pitch.entry if buy else market.price <= pitch.entry):
        raise ValueError("The reviewed entry trigger has not been reached.")
    if abs(market.price - pitch.entry) / pitch.entry > policy.max_entry_slip:
        raise ValueError("The current price is outside the reviewed entry deviation.")
    entry = rules.price(market.price * (1 + policy.max_entry_slip if buy else 1 - policy.max_entry_slip), upward=not buy)
    stop = rules.price(pitch.stop, upward=buy)
    target = rules.price(pitch.target, upward=not buy)
    if not (stop < entry < target if buy else target < entry < stop):
        raise ValueError("Rounded protective levels do not bracket the entry.")
    distance = abs(entry - stop)
    if not policy.min_stop_fraction <= distance / entry <= policy.max_stop_fraction:
        raise ValueError("Rounded stop distance exceeds the per-trade policy.")
    rr = abs(target - entry) / distance
    if rr < policy.min_reward_risk:
        raise ValueError("Rounded reward-to-risk is below the per-trade policy.")
    equity, available, taker = (D(amount(account[key])) for key in ("equity", "withdrawable", "reported_taker_rate"))
    if not all(value.is_finite() for value in (equity, available, taker)) or min(equity, available) <= 0 or not 0 <= taker <= D("0.01"):
        raise ValueError("Valid positive user equity/withdrawable funds and an account fee observation are required.")
    units = account["builder_fee_tenths_bps"]
    if type(units) is not int or not 0 <= units <= 100:
        raise ValueError("Unsupported builder fee observation.")
    builder_rate = D(units) / 100000
    fees = taker + builder_rate
    unit_loss = distance + (entry + stop) * (fees + policy.slippage_rate)
    cap = D("50")
    quantity = min(equity * policy.risk_fraction / unit_loss, equity * policy.max_notional_fraction / entry,
        available / (entry / pitch.leverage + entry * fees), cap / entry, setup.approved_quantity)
    quantity = (quantity / rules.quantity_step).to_integral_value(rounding=ROUND_DOWN) * rules.quantity_step
    notional = quantity * entry
    if quantity <= 0 or notional < policy.min_notional:
        raise ValueError("The risk-sized user order falls below the $10 minimum notional.")
    expires = min(now + timedelta(seconds=30), setup.expires_at)
    plan = {"schema": "lobster-user-order-preview-v1", "id": uuid4().hex, "network": "testnet", "address": address,
        "episode_id": setup.episode_id, "approval_hash": setup.approval_hash, "policy_version": policy.version,
        "created_at": now.isoformat(), "expires_at": expires.isoformat(), "account_observed_at": account["observed_at"],
        "market_observed_at": market.timestamp.isoformat(), "market_price": str(market.price),
        "entry": {"symbol": "BTC", "asset_id": rules.asset_id, "side": "buy" if buy else "sell", "quantity": str(quantity),
            "limit_price": str(entry), "time_in_force": "Ioc", "leverage": pitch.leverage, "margin_mode": "isolated"},
        "protection_templates": {"stop_trigger": str(stop), "target_trigger": str(target), "reduce_only": True,
            "quantity_binding": "actual_confirmed_fill", "activation": "Only after actual entry reconciliation; no protection is installed by this preview."},
        "per_trade": {"checks_passed": True, "notional": str(notional), "margin": str(notional / pitch.leverage),
            "planned_loss_including_estimated_costs": str(quantity * unit_loss), "risk_budget": str(equity * policy.risk_fraction),
            "user_equity": str(equity), "user_withdrawable": str(available), "notional_cap": str(cap), "reward_risk": str(rr)},
        "fees": {"reported_taker_rate": str(taker), "builder_address": account["builder_address"],
            "builder_fee_tenths_bps": units, "builder_fee_rate": str(builder_rate),
            "entry_exchange_estimate": str(notional * taker), "entry_builder_hypothetical": str(notional * builder_rate),
            "stop_roundtrip_estimate": str(quantity * (entry + stop) * fees), "collected": "0"},
        "signed": False, "submitted": False, "nonce_reserved": False, "executable": False,
        "order_submission_enabled": False, "fee_collection_enabled": False,
        "execution_blockers": ["User daily-loss/drawdown baselines and external cash flows are not established.",
            "User exchange signing, native protection and funded acceptance remain unverified.",
            "Builder eligibility and actual fee receipts remain unverified.",
            "A preview reserves no capital, order slot or exchange nonce."],
        "assumptions": "Per-trade illustration only. Both legs include the configured hypothetical builder rate and observed taker rate. Slippage is estimated; funding, gap losses and final exchange costs can differ."}
    if account["builder_address"] is None or account["builder_approval_status"] != "approved" or account["builder_address"] == address:
        plan["execution_blockers"].append("A separate eligible builder and sufficient actual fee approval are not established.")
    if capital_reference:
        plan["capital_reference"] = capital_reference
        plan["execution_blockers"][0] = "Observed loss references exist; unknown prehistory and current receipt coverage still require execution acceptance."
    return plan | {"plan_hash": fingerprint(plan)}


class UserPlans:
    def __init__(self, store):
        self.store = store
        Base.metadata.create_all(store.engine)

    @staticmethod
    def view(plan: dict) -> dict:
        return plan | {"expired": utcnow() >= datetime.fromisoformat(plan["expires_at"]),
            "observation": "Stored immutable preview; not a live order, account lock or exchange receipt."}

    def by_request(self, address: str, key: str, episode_id: str) -> dict | None:
        with self.store.transaction() as session:
            row = session.scalar(select(UserPlan).where(UserPlan.address == address, UserPlan.request_id == key))
            if row and row.payload["episode_id"] != episode_id:
                raise ValueError("This request ID belongs to another user preview input.")
            return self.view(row.payload) if row else None

    def save(self, address: str, key: str, plan: dict) -> dict:
        with self.store.transaction() as session:
            row = session.scalar(select(UserPlan).where(UserPlan.address == address, UserPlan.request_id == key))
            if row:
                if row.payload["episode_id"] != plan["episode_id"]:
                    raise ValueError("This request ID belongs to another user preview input.")
                return self.view(row.payload)
            if (plan["address"] != address or plan["executable"] or plan["submitted"] or plan["signed"]
                    or plan["nonce_reserved"] or plan["order_submission_enabled"] or plan["fee_collection_enabled"]
                    or plan["plan_hash"] != fingerprint({key: value for key, value in plan.items() if key != "plan_hash"})):
                raise ValueError("Only unsigned user-bound illustrations can be stored.")
            session.add(UserPlan(id=plan["id"], address=address, request_id=key, payload=plan))
            return self.view(plan)

    def get(self, address: str, plan_id: str) -> dict | None:
        with self.store.transaction() as session:
            row = session.get(UserPlan, plan_id)
            return self.view(row.payload) if row and row.address == address else None
