"""Separate testnet journal. Commands are claimed durably before any HTTP write."""

from contextlib import contextmanager
from datetime import timezone
from decimal import Decimal as D
from pathlib import Path
from threading import RLock

from sqlalchemy import JSON, Integer, String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from ..domain import Capital, RiskPolicy, utcnow
from .contracts import ExchangeAccount, ReviewedSetup, fingerprint


class Base(DeclarativeBase):
    pass


class Control(Base):
    __tablename__ = "testnet_control"
    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Trade(Base):
    __tablename__ = "testnet_trades"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Command(Base):
    __tablename__ = "testnet_commands"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Fill(Base):
    __tablename__ = "testnet_fills"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Journal(Base):
    __tablename__ = "testnet_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ExecutionLedger:
    def __init__(self, url: str, account_address: str, signer_address: str):
        if url.startswith("sqlite:///") and ":memory:" not in url:
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        options = {"connect_args": {"check_same_thread": False, "timeout": 20}} if url.startswith("sqlite") else {}
        if ":memory:" in url:
            options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        self.lock = RLock()
        Base.metadata.create_all(self.engine)
        with self.transaction() as session:
            control = session.get(Control, 1)
            identity = {"network": "testnet", "account": account_address.lower(), "signer": signer_address.lower()}
            if control:
                if any(control.payload.get(key) != value for key, value in identity.items()):
                    raise ValueError("The testnet ledger belongs to a different account or API wallet. Use a new ledger for a new identity.")
            else:
                session.add(Control(id=1, payload=identity | {"last_nonce": 0, "halt_reason": None,
                    "day": None, "day_start_equity": None, "high_water_equity": None}))

    @contextmanager
    def transaction(self):
        with self.lock, Session(self.engine) as session:
            try:
                if self.engine.dialect.name == "sqlite":
                    session.execute(text("BEGIN IMMEDIATE"))
                else:
                    session.execute(select(Control).where(Control.id == 1).with_for_update())
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    @staticmethod
    def event(session, kind, message, trade_id=None, data=None):
        session.add(Journal(payload={"timestamp": utcnow().isoformat(), "network": "testnet",
            "kind": kind, "message": message, "trade_id": trade_id, "data": data or {}}))

    def observe_capital(self, account: ExchangeAccount, policy: RiskPolicy) -> Capital:
        if not -2 <= (utcnow() - account.observed_at).total_seconds() <= policy.max_data_age_seconds:
            raise ValueError("Account observation is stale.")
        with self.transaction() as session:
            control = session.get(Control, 1)
            data = control.payload
            if account.address.lower() != data["account"]:
                raise ValueError("Account identity mismatch.")
            if account.equity == 0 and data["day_start_equity"] is None:
                return Capital(equity="0", available_cash="0", day_start_equity="0", high_water_equity="0")
            day = account.observed_at.astimezone(timezone.utc).date().isoformat()
            baseline = D(data["day_start_equity"]) if data["day_start_equity"] is not None else account.equity
            high = max(D(data["high_water_equity"] or "0"), account.equity)
            reason = data["halt_reason"]
            if account.equity <= baseline * (1 - policy.daily_loss_fraction):
                reason = reason or "Testnet daily loss threshold reached."
            if account.equity <= high * (1 - policy.drawdown_fraction):
                reason = reason or "Testnet drawdown threshold reached."
            if data["day"] is not None and data["day"] != day:
                baseline = account.equity
            control.payload = data | {"day": day, "day_start_equity": str(baseline),
                "high_water_equity": str(high), "halt_reason": reason}
            return Capital(equity=account.equity, available_cash=account.withdrawable,
                day_start_equity=baseline, high_water_equity=high, paused=reason is not None,
                occupied=bool(account.btc_size or account.other_positions or account.open_order_count))

    def stage(self, setup: ReviewedSetup, order: dict, rules: dict, *, audit_binding: dict | None = None) -> dict:
        binding = fingerprint(setup.model_dump(mode="json"))
        with self.transaction() as session:
            existing = session.get(Trade, setup.episode_id)
            if existing:
                if existing.payload.get("audit_binding") != audit_binding:
                    raise ValueError("The existing execution belongs to another user consent binding.")
                if existing.payload["setup_hash"] != binding:
                    raise ValueError("This episode already has a different testnet execution intent.")
                if existing.payload["status"] != "staged":
                    raise ValueError("This episode already has a submitted or terminal intent. Pitch a new setup for a new entry.")
                return existing.payload
            if session.get(Control, 1).payload["halt_reason"]:
                raise ValueError("The testnet execution ledger is halted.")
            if any(t.payload["status"] not in {"closed", "rejected", "expired", "cancelled"} for t in session.scalars(select(Trade))):
                raise ValueError("Another testnet trade or unresolved command already owns the execution slot.")
            data = {"id": setup.episode_id, "network": "testnet", "setup": setup.model_dump(mode="json"),
                "setup_hash": binding, "entry": order, "rules": rules, "status": "staged",
                "reason": "Intent staged locally. No exchange action has been sent.",
                "filled_quantity": "0", "protected_quantity": "0", "created_at": utcnow().isoformat()}
            if audit_binding is not None:
                data["audit_binding"] = audit_binding
            session.add(Trade(id=setup.episode_id, payload=data))
            self.event(session, "staged", data["reason"], setup.episode_id)
            return data

    def cancel_staged(self, trade_id: str) -> dict:
        with self.transaction() as session:
            row = session.get(Trade, trade_id)
            if not row:
                raise ValueError("Testnet execution intent not found.")
            if row.payload["status"] == "cancelled":
                return row.payload
            commands = session.scalar(select(Command).where(Command.trade_id == trade_id).limit(1))
            if row.payload["status"] != "staged" or commands is not None:
                raise ValueError("Only an unsent local intent can be cancelled here. Reconcile submitted commands with the owner runner.")
            row.payload = row.payload | {"status": "cancelled", "reason": "Unsent intent cancelled locally. No exchange action was sent."}
            self.event(session, "cancelled", row.payload["reason"], trade_id)
            return row.payload

    def trade(self, trade_id: str) -> dict:
        with Session(self.engine) as session:
            row = session.get(Trade, trade_id)
            if not row:
                raise ValueError("Testnet execution intent not found.")
            return row.payload

    def update_trade(self, trade_id: str, status: str, reason: str, **fields):
        with self.transaction() as session:
            row = session.get(Trade, trade_id)
            if row.payload["status"] == status and all(row.payload.get(k) == v for k, v in fields.items()):
                return
            row.payload = row.payload | fields | {"status": status, "reason": reason}
            self.event(session, status, reason, trade_id, fields)

    def halt(self, reason: str):
        with self.transaction() as session:
            control = session.get(Control, 1)
            if not control.payload["halt_reason"]:
                control.payload = control.payload | {"halt_reason": reason}
                self.event(session, "halt", reason)

    def prepare_command(self, trade_id: str, key: str, kind: str, payload: dict) -> dict:
        with self.transaction() as session:
            row = session.get(Command, key)
            if row:
                if row.trade_id != trade_id or row.payload["request"] != payload:
                    raise ValueError("Command ID collision or changed request.")
                return row.payload
            trade = session.get(Trade, trade_id)
            if not trade:
                raise ValueError("Stage an execution intent before preparing commands.")
            if kind in {"entry", "leverage"} and trade.payload["status"] in {"closed", "rejected", "expired", "cancelled"}:
                raise ValueError("A terminal intent cannot authorize an entry command.")
            data = {"id": key, "kind": kind, "request": payload, "status": "prepared", "nonce": None,
                    "result": None, "created_at": utcnow().isoformat()}
            session.add(Command(id=key, trade_id=trade_id, payload=data))
            return data

    def claim(self, key: str, now_ms: int) -> dict | None:
        with self.transaction() as session:
            row = session.get(Command, key)
            if not row or row.payload["status"] != "prepared":
                return None
            control = session.get(Control, 1)
            nonce = max(now_ms, control.payload["last_nonce"] + 1)
            if nonce > now_ms + 1000:
                raise ValueError("Signer clock is behind the durable nonce. Wait before signing.")
            control.payload = control.payload | {"last_nonce": nonce}
            row.payload = row.payload | {"status": "sending", "nonce": nonce}
            self.event(session, "command_claimed", "Command claimed; it will not be automatically submitted twice.",
                       row.trade_id, {"command_id": key, "nonce": nonce})
            return row.payload

    def finish(self, key: str, status: str, result: dict):
        if status not in {"acknowledged", "unknown", "rejected", "reconciled"}:
            raise ValueError("Invalid command state.")
        with self.transaction() as session:
            row = session.get(Command, key)
            row.payload = row.payload | {"status": status, "result": result}
            self.event(session, "command_" + status, "Exchange command state recorded.", row.trade_id,
                       {"command_id": key, "result": result})

    def commands(self, trade_id: str) -> list[dict]:
        with Session(self.engine) as session:
            return [row.payload for row in session.scalars(select(Command).where(Command.trade_id == trade_id))]

    def record_fills(self, trade_id: str, fills: list[dict], owned_oids: set[int]):
        with self.transaction() as session:
            for fill in fills:
                if fill.get("coin") != "BTC" or int(fill["oid"]) not in owned_oids:
                    continue
                key = f"{fill['oid']}:{fill['tid']}"
                # Decimal parsing also rejects malformed/non-finite observations.
                for field in ("sz", "px", "fee", "closedPnl"):
                    if isinstance(fill[field], (float, bool)) or not D(str(fill[field])).is_finite():
                        raise ValueError("Non-finite exchange fill.")
                if D(fill["sz"]) <= 0 or D(fill["px"]) <= 0 or fill.get("feeToken") != "USDC":
                    raise ValueError("Unsupported fill denomination or size.")
                data = {key: fill[key] for key in ("coin", "oid", "tid", "px", "sz", "fee", "feeToken", "closedPnl", "time", "side")}
                # Hyperliquid documents builderFee as INCLUDED in fee. Never add it twice.
                builder_fee = fill.get("builderFee")
                if builder_fee is not None:
                    if isinstance(builder_fee, (float, bool)) or not D(str(builder_fee)).is_finite() or not D("0") <= D(str(builder_fee)) <= D(str(fill["fee"])):
                        raise ValueError("Invalid builder fee observation.")
                    data["builderFee"] = str(builder_fee)
                existing = session.get(Fill, key)
                if existing:
                    if existing.trade_id != trade_id or existing.payload != data:
                        raise ValueError("Conflicting receipt for an already observed fill.")
                    continue
                session.add(Fill(id=key, trade_id=trade_id, payload=data))
                session.flush()  # Deduplicate repeated fills within this same response as well.
                self.event(session, "fill", "An actual testnet fill was observed.", trade_id, data)

    def snapshot(self) -> dict:
        with self.lock, Session(self.engine) as session:
            control = session.get(Control, 1).payload
            events = list(session.scalars(select(Journal).order_by(Journal.id.desc()).limit(100)))
            fills = [row.payload for row in session.scalars(select(Fill))]
            return {"network": "testnet", "control": control,
                "trades": [row.payload for row in session.scalars(select(Trade))], "fills": fills,
                "observed_fill_fees": str(sum((D(f["fee"]) for f in fills), D("0"))),
                "observed_builder_fee_component": str(sum((D(f.get("builderFee", "0")) for f in fills), D("0"))),
                "builder_fee_coverage_complete": all("builderFee" in f for f in fills) and bool(fills),
                "observed_closed_pnl": str(sum((D(f["closedPnl"]) for f in fills), D("0"))),
                "events": [row.payload | {"id": row.id} for row in reversed(events)]}

