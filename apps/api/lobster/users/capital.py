"""Private observation-based user loss references. Never grants entry permission."""

from datetime import datetime, timezone
from decimal import Decimal as D
from uuid import uuid4

from sqlalchemy import JSON, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..domain import utcnow
from ..execution.contracts import fingerprint
from .fees import require_fresh
from .service import amount


class Base(DeclarativeBase):
    pass


class Reference(Base):
    __tablename__ = "user_capital_references"
    address: Mapped[str] = mapped_column(String(42), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Receipt(Base):
    __tablename__ = "user_capital_receipts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    address: Mapped[str] = mapped_column(String(42), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Observation(Base):
    __tablename__ = "user_capital_observations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    address: Mapped[str] = mapped_column(String(42), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


def normalize_receipt(address: str, stream: str, row: dict, start: int, end: int) -> dict:
    timestamp, tx, delta = row["time"], row["hash"], row["delta"]
    if type(timestamp) is not int or not start <= timestamp <= end or not isinstance(tx, str) or len(tx) != 66 or not tx.startswith("0x"):
        raise ValueError("Unbounded or malformed ledger receipt.")
    int(tx[2:], 16)
    kind = delta["type"]
    value = D(amount(delta["usdc"]))
    flow = funding = D("0")
    if stream == "funding" and kind == "funding" and delta.get("coin") == "BTC":
        funding = value
    elif stream == "ledger" and value >= 0:
        if kind == "deposit": flow = value
        elif kind == "accountClassTransfer" and type(delta.get("toPerp")) is bool:
            flow = value if delta["toPerp"] else -value
        elif kind == "withdraw" and D(amount(delta["fee"])) == 0:
            flow = -value
        elif kind in {"internalTransfer", "subAccountTransfer"} and D(amount(delta.get("fee", "0"))) == 0:
            source, destination = delta["user"].lower(), delta["destination"].lower()
            if address not in {source, destination}:
                raise ValueError("A transfer receipt belongs to another account.")
            flow = value * ((1 if destination == address else 0) - (1 if source == address else 0))
        else:
            raise ValueError("Unsupported or fee-ambiguous cash-flow receipt. Owner review is required.")
    else:
        raise ValueError("Unsupported funding or ledger receipt.")
    identity = {"address": address, "stream": stream, "time": timestamp, "hash": tx.lower(), "kind": kind, "coin": delta.get("coin")}
    # Conflicting updates with the same source identity halt; never sum both.
    return identity | {"id": fingerprint(identity), "cashflow": str(flow), "funding": str(funding),
        "details_hash": fingerprint({key: str(value) if isinstance(value, D) else value for key, value in delta.items()})}


class UserCapital:
    def __init__(self, store):
        self.store = store
        Base.metadata.create_all(store.engine)

    def get(self, address: str) -> dict | None:
        with self.store.transaction() as session:
            row = session.get(Reference, address)
            return self.view(row.payload) if row else None

    @staticmethod
    def view(state: dict) -> dict:
        age = (utcnow() - datetime.fromisoformat(state["observed_at"])).total_seconds()
        return state | {"stale": not -2 <= age <= 15, "entry_permission": False,
            "history_before_baseline": "unknown", "scope": "first-perps-dex-testnet-observations",
            "limits": "References start at the first observed flat positive account, not reconstructed midnight/all-time history. Funding is already included in equity. Unsupported/late/ambiguous history latches review. No entry permission is granted."}

    def halt(self, address: str, reason: str):
        with self.store.transaction() as session:
            row = session.get(Reference, address)
            if row and not row.payload["halt_reason"]:
                row.payload = row.payload | {"halt_reason": reason}
                session.add(Observation(id=uuid4().hex, address=address, payload={"kind": "halt", "at": utcnow().isoformat(), "reason": reason}))

    def observe(self, address: str, account: dict, start: int, receipts: list[dict], *, complete: bool) -> dict:
        require_fresh(account, address)
        end = account.get("exchange_time_ms")
        if type(end) is not int or not -2000 <= int(utcnow().timestamp() * 1000) - end <= 15000 or type(start) is not int:
            raise ValueError("An exact fresh exchange timestamp is required for capital accounting.")
        if complete is not True or start > end:
            raise ValueError("The cash-flow/funding window is incomplete.")
        equity = D(amount(account["equity"]))
        if equity < 0:
            raise ValueError("Invalid user equity observation.")
        with self.store.transaction() as session:
            row = session.get(Reference, address)
            if not row:
                if equity <= 0 or account["positions"] or account["open_orders"] or receipts or start != end:
                    raise ValueError("Start references with a flat positive account and a point observation.")
                day = datetime.fromtimestamp(end / 1000, timezone.utc).date().isoformat()
                state = {"address": address, "network": "testnet", "initial_equity": str(equity), "equity": str(equity),
                    "policy_hash": fingerprint(self.store.policy.model_dump(mode="json")),
                    "baseline_ms": end, "cursor_ms": end, "observed_at": account["observed_at"], "day": day,
                    "day_reference_ms": end, "day_reference": str(equity), "high_water": str(equity),
                    "cashflows": "0", "funding_observed": "0", "performance_balance": str(equity),
                    "net_equity_change_excluding_cashflows": "0", "halt_reason": None, "receipt_count": 0}
                session.add(Reference(address=address, payload=state))
                session.add(Observation(id=uuid4().hex, address=address, payload={"kind": "baseline", **state}))
                return self.view(state)
            state = row.payload
            if state["policy_hash"] != fingerprint(self.store.policy.model_dump(mode="json")):
                raise ValueError("User capital policy changed; owner review is required.")
            if end < state["cursor_ms"]:
                return self.view(state)  # A concurrent newer observation already won.
            if start > state["cursor_ms"] + 1 or start < state["baseline_ms"]:
                raise ValueError("Capital history has a gap or precedes its baseline.")
            if end == state["cursor_ms"] and equity != D(state["equity"]):
                raise ValueError("Conflicting equity at one exchange timestamp.")
            flow, funding, added = D("0"), D("0"), []
            for receipt in receipts:
                if receipt["address"] != address or not start <= receipt["time"] <= end:
                    raise ValueError("Capital receipt is outside its account/window.")
                existing = session.get(Receipt, receipt["id"])
                if existing:
                    if existing.payload != receipt:
                        raise ValueError("Conflicting capital receipt identity.")
                    continue
                if receipt["time"] <= state["baseline_ms"]:
                    continue  # The baseline equity already included it.
                if receipt["time"] <= state["cursor_ms"]:
                    raise ValueError("Late receipt changed an already observed capital interval.")
                flow += D(receipt["cashflow"]); funding += D(receipt["funding"])
                session.add(Receipt(id=receipt["id"], address=address, payload=receipt)); session.flush()
                added.append(receipt["id"])
            if end == state["cursor_ms"] and not added:
                return self.view(state)
            cumulative = D(state["cashflows"]) + flow
            performance = equity - cumulative
            reference, high = D(state["day_reference"]), D(state["high_water"])
            # Cash inflows never enlarge the loss allowance or erase an earlier loss.
            basis = min(D(state["initial_equity"]), equity)
            policy = self.store.policy
            reason = state["halt_reason"]
            if performance <= reference - basis * policy.daily_loss_fraction:
                reason = reason or "User daily observed loss threshold reached."
            if performance <= high - basis * policy.drawdown_fraction:
                reason = reason or "User observed drawdown threshold reached."
            day = datetime.fromtimestamp(end / 1000, timezone.utc).date().isoformat()
            # Evaluate the old window before rolling its daily observation reference.
            update = {"day": day, "day_reference": str(performance), "day_reference_ms": end} if day != state["day"] else {}
            state = state | update | {"equity": str(equity), "cursor_ms": end, "observed_at": account["observed_at"],
                "cashflows": str(cumulative), "funding_observed": str(D(state["funding_observed"]) + funding),
                "performance_balance": str(performance), "net_equity_change_excluding_cashflows": str(performance - D(state["initial_equity"])),
                "high_water": str(max(high, performance)), "halt_reason": reason, "receipt_count": state["receipt_count"] + len(added)}
            row.payload = state
            session.add(Observation(id=uuid4().hex, address=address, payload={"kind": "observation", "new_receipts": added, **state}))
            return self.view(state)
