"""Transactional paper account and append-only application journal."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from sqlalchemy import JSON, Integer, String, create_engine, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from .domain import Capital, PitchInput, RiskPolicy, Snapshot, utcnow
from .risk import assess
from .admission import consume


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Episode(Base):
    __tablename__ = "episodes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Position(Base):
    __tablename__ = "positions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    episode_id: Mapped[str] = mapped_column(String(36), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payload: Mapped[dict] = mapped_column(JSON)


class PitchAdmission(Base):
    __tablename__ = "pitch_admission"
    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


def digest(episode: dict) -> str:
    binding = {key: episode.get(key) for key in ("pitch", "snapshot", "risk", "policy", "expires_at", "reviews")}
    if episode.get("research") is not None:
        binding["research"] = episode["research"]
    return sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def stamp() -> str:
    return utcnow().isoformat()


class Store:
    def __init__(self, url: str, initial_capital: D = D("1000"), policy: RiskPolicy | None = None):
        if url.startswith("sqlite:///") and ":memory:" not in url:
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        options = {"connect_args": {"check_same_thread": False, "timeout": 20}} if url.startswith("sqlite") else {}
        if ":memory:" in url:
            options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        self.lock = RLock()
        self.policy = policy or RiskPolicy()
        Base.metadata.create_all(self.engine)
        with self.transaction() as session:
            if not session.get(Account, 1):
                session.add(Account(id=1, payload={"initial_capital": str(initial_capital),
                    "cash": str(initial_capital), "realized_gross": "0", "fees_paid": "0",
                    "day_start_equity": str(initial_capital), "high_water_equity": str(initial_capital),
                    "day": utcnow().date().isoformat(), "paused": False,
                    "halt_reason": None, "created_at": stamp()}))
                self.event(session, "system", "account_created", "Paper account initialized. This is simulated capital.",
                           data={"amount": str(initial_capital)})

    @contextmanager
    def transaction(self):
        with self.lock, Session(self.engine) as session:
            try:
                if self.engine.dialect.name == "sqlite":
                    session.execute(text("BEGIN IMMEDIATE"))
                else:
                    session.execute(select(Account).where(Account.id == 1).with_for_update())
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def event(self, session: Session, actor: str, kind: str, message: str,
              episode_id: str | None = None, data: dict | None = None):
        session.add(Event(payload={"timestamp": stamp(), "actor": actor, "kind": kind,
            "message": message, "episode_id": episode_id, "data": data or {}}))

    def capital(self, session: Session, market: Snapshot, exclude_episode: str | None = None) -> Capital:
        account = session.get(Account, 1).payload
        unrealized = D("0")
        occupied = False
        reserved = D("0")
        for pos in session.scalars(select(Position)):
            p = pos.payload
            if p["status"] == "open":
                occupied = True
                sign = D("1") if p["direction"] == "long" else D("-1")
                unrealized += (market.price - D(p["entry_price"])) * D(p["quantity"]) * sign
                reserved += D(p["margin"])
        for row in session.scalars(select(Episode)):
            e = row.payload
            if e["status"] == "approved" and row.id != exclude_episode:
                occupied = True
                reserved += D(e["risk"]["margin"])
        return Capital(equity=D(account["cash"]) + unrealized,
            available_cash=D(account["cash"]) - reserved,
            day_start_equity=D(account["day_start_equity"]),
            high_water_equity=D(account["high_water_equity"]), occupied=occupied,
            paused=account["paused"] or account["halt_reason"] is not None)

    def bind_market_source(self, source: str):
        with self.transaction() as session:
            account = session.get(Account, 1)
            previous = account.payload.get("market_source")
            open_sources = {p.payload["market_source"] for p in session.scalars(select(Position)) if p.payload["status"] == "open"}
            open_sources.update(e.payload["snapshot"]["source"] for e in session.scalars(select(Episode))
                if e.payload["status"] in {"analyzing", "risk_check", "capital_check", "approved"} and e.payload.get("snapshot"))
            if any(value != source for value in open_sources):
                raise ValueError("Close open positions and finish pending reviews before changing MARKET_SOURCE. Use a separate DATABASE_URL for a different feed.")
            if previous != source:
                account.payload = account.payload | {"market_source": source}
                self.event(session, "system", "market_source", f"Market source bound to {source}; execution remains paper.")

    def working_episodes(self) -> list[dict]:
        # Execution must never depend on a paginated presentation of the history.
        with self.lock, Session(self.engine) as session:
            return [e.payload for e in session.scalars(select(Episode))
                    if e.payload["status"] in {"queued", "analyzing", "risk_check", "capital_check", "approved"}]

    def reserve_review(self, episode_id: str, status: str, role: str, daily_limit: int) -> bool:
        with self.transaction() as session:
            row = session.get(Episode, episode_id)
            if not row or row.payload["status"] != status:
                return False
            ep = row.payload
            attempts = ep.get("review_attempts", {})
            day = utcnow().date().isoformat()
            count = session.scalar(select(func.count()).select_from(Event).where(
                Event.payload["kind"].as_string() == "review_started",
                Event.payload["timestamp"].as_string().startswith(day)))
            reason = ("A previous reviewer call was interrupted. No automatic retry was made." if attempts.get(role)
                      else "The daily review-call budget is exhausted. Submit a new pitch after the UTC day resets." if count >= daily_limit else None)
            if reason:
                row.payload = ep | {"status": "rejected", "reason": reason}
                self.event(session, "system", "rejected", reason, episode_id)
                return False
            row.payload = ep | {"review_attempts": attempts | {role: 1}}
            self.event(session, role, "review_started", f"Starting the {role} review.", episode_id)
            return True

    def consume_pitch_request(self, peer: str, now: datetime | None = None) -> int:
        """Persist a validated HTTP attempt before submission; retries also count."""
        with self.transaction() as session:
            row = session.get(PitchAdmission, 1)
            state, retry = consume(row.payload if row else {"last_seen_us": 0, "peers": {}}, peer, now or utcnow())
            if row:
                row.payload = state
            else:
                session.add(PitchAdmission(id=1, payload=state))
        return retry

    def submit(self, pitch: PitchInput, request_id: str) -> dict:
        with self.transaction() as session:
            return self.submit_in_transaction(session, pitch, request_id)

    def submit_in_transaction(self, session: Session, pitch: PitchInput, request_id: str, research: dict | None = None) -> dict:
        existing = session.scalar(select(Episode).where(Episode.request_id == request_id))
        if existing:
            if existing.payload["pitch"] != pitch.model_dump(mode="json"):
                raise ValueError("This request ID belongs to a different pitch.")
            return existing.payload
        pending = session.scalar(select(func.count()).select_from(Episode).where(
            Episode.payload["status"].as_string().in_(("queued", "analyzing", "risk_check", "capital_check"))))
        if pending >= 20:
            raise ValueError("The pitch queue is full. Wait for the current reviews to finish.")
        now = utcnow()
        ep = {"id": str(uuid4()), "pitch": pitch.model_dump(mode="json"), "status": "queued",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=self.policy.proposal_ttl_seconds)).isoformat(),
            "snapshot": None, "reviews": {}, "risk": None, "policy": self.policy.model_dump(mode="json"),
            "approval_hash": None, "position_id": None, "reason": "Waiting for the analyst."}
        if research is not None: ep["research"] = research
        session.add(Episode(id=ep["id"], request_id=request_id, payload=ep))
        self.event(session, "user", "pitch_submitted", f"{pitch.author} pitched a BTC {pitch.direction} setup.", ep["id"])
        return ep

    def get_episode(self, episode_id: str) -> dict | None:
        with Session(self.engine) as session:
            row = session.get(Episode, episode_id)
            return row.payload if row else None

    def advance(self, episode_id: str, expected: str, status: str, actor: str, message: str,
                updates: dict | None = None) -> bool:
        with self.transaction() as session:
            row = session.get(Episode, episode_id)
            if not row or row.payload["status"] != expected:
                return False
            row.payload = row.payload | (updates or {}) | {"status": status, "reason": message}
            self.event(session, actor, status, message, episode_id)
            return True

    def approve(self, episode_id: str, market: Snapshot) -> dict | None:
        with self.transaction() as session:
            row = session.get(Episode, episode_id)
            if not row or row.payload["status"] != "capital_check":
                return None
            ep = row.payload
            if any(ep["reviews"].get(role, {}).get("verdict") != "approve" for role in ("analyst", "risk")):
                raise ValueError("Both analyst and risk reviews must approve the proposal.")
            result = assess(PitchInput.model_validate(ep["pitch"]), market,
                self.capital(session, market), self.policy, utcnow(), datetime.fromisoformat(ep["expires_at"]))
            ep = ep | {"risk": result.model_dump(mode="json"), "status": "approved" if result.approved else "rejected",
                "reason": ("Capital reserved. Waiting for the entry trigger." if result.approved else " ".join(result.reasons))}
            if result.approved:
                ep["approval_hash"] = digest(ep)
            row.payload = ep
            self.event(session, "banker", ep["status"], ep["reason"], episode_id,
                       {"risk": result.model_dump(mode="json"), "approval_hash": ep["approval_hash"]})
            return ep

    def try_fill(self, episode_id: str, market: Snapshot) -> dict | None:
        with self.transaction() as session:
            previous = session.scalar(select(Position).where(Position.episode_id == episode_id))
            if previous:
                return previous.payload
            row = session.get(Episode, episode_id)
            if not row or row.payload["status"] != "approved":
                return None
            ep = row.payload
            if utcnow() >= datetime.fromisoformat(ep["expires_at"]):
                row.payload = ep | {"status": "expired", "reason": "The proposal has expired."}
                self.event(session, "executor", "expired", row.payload["reason"], episode_id)
                return None
            if ep["approval_hash"] != digest(ep) or ep["policy"] != self.policy.model_dump(mode="json") or ep["snapshot"]["source"] != market.source:
                row.payload = ep | {"status": "rejected", "reason": "Approval binding or risk policy changed."}
                self.event(session, "executor", "rejected", row.payload["reason"], episode_id)
                return None
            pitch = PitchInput.model_validate(ep["pitch"])
            result = assess(pitch, market, self.capital(session, market, exclude_episode=episode_id),
                self.policy, utcnow(), datetime.fromisoformat(ep["expires_at"]))
            if not result.approved:
                row.payload = ep | {"status": "expired" if utcnow() >= datetime.fromisoformat(ep["expires_at"]) else "rejected",
                                    "reason": " ".join(result.reasons)}
                self.event(session, "executor", row.payload["status"], row.payload["reason"], episode_id)
                return None
            triggered = market.price >= pitch.entry if pitch.direction == "long" else market.price <= pitch.entry
            if not triggered:
                return None
            if abs(market.price - pitch.entry) / pitch.entry > self.policy.max_entry_slip:
                row.payload = ep | {"status": "expired", "reason": "Price moved beyond the permitted entry deviation."}
                self.event(session, "executor", "expired", row.payload["reason"], episode_id)
                return None
            sign = D("1") if pitch.direction == "long" else D("-1")
            fill_price = market.price * (1 + sign * self.policy.slippage_rate)
            actual = pitch.model_copy(update={"entry": fill_price})
            final = assess(actual, market, self.capital(session, market, exclude_episode=episode_id),
                self.policy, utcnow(), datetime.fromisoformat(ep["expires_at"]))
            if not final.approved:
                row.payload = ep | {"status": "rejected", "reason": " ".join(final.reasons)}
                self.event(session, "executor", "rejected", row.payload["reason"], episode_id)
                return None
            quantity = min(D(ep["risk"]["quantity"]), final.quantity)
            notional = quantity * fill_price
            if notional < self.policy.min_notional:
                row.payload = ep | {"status": "rejected", "reason": "Final rounded notional is below the $10 minimum."}
                self.event(session, "executor", "rejected", row.payload["reason"], episode_id)
                return None
            fee = notional * self.policy.fee_rate
            account = session.get(Account, 1)
            account.payload = account.payload | {"cash": str(D(account.payload["cash"]) - fee),
                "fees_paid": str(D(account.payload["fees_paid"]) + fee)}
            pos = {"id": str(uuid4()), "episode_id": episode_id, "symbol": "BTC", "direction": pitch.direction,
                "status": "open", "quantity": str(quantity), "entry_price": str(fill_price),
                "stop": str(pitch.stop), "target": str(pitch.target), "leverage": pitch.leverage,
                "margin": str(notional / pitch.leverage), "entry_fee": str(fee), "exit_fee": "0",
                "exit_price": None, "net_pnl": None, "opened_at": stamp(), "closed_at": None,
                "close_reason": None, "execution_mode": "paper", "market_source": market.source,
                "entry_fill_id": str(uuid4()), "exit_fill_id": None}
            session.add(Position(id=pos["id"], episode_id=episode_id, payload=pos))
            row.payload = ep | {"status": "filled", "position_id": pos["id"], "reason": "Paper order filled; stop and target monitoring active."}
            self.event(session, "executor", "filled", row.payload["reason"], episode_id, pos)
            return pos

    def close_in_transaction(self, session: Session, row: Position, market: Snapshot, reason: str) -> dict:
        pos = row.payload
        if pos["status"] == "closed":
            return pos
        sign = D("1") if pos["direction"] == "long" else D("-1")
        exit_price = market.price * (1 - sign * self.policy.slippage_rate)
        quantity = D(pos["quantity"])
        gross = (exit_price - D(pos["entry_price"])) * quantity * sign
        exit_fee = exit_price * quantity * self.policy.fee_rate
        account = session.get(Account, 1)
        account.payload = account.payload | {"cash": str(D(account.payload["cash"]) + gross - exit_fee),
            "realized_gross": str(D(account.payload["realized_gross"]) + gross),
            "fees_paid": str(D(account.payload["fees_paid"]) + exit_fee)}
        closed = pos | {"status": "closed", "exit_price": str(exit_price), "exit_fee": str(exit_fee),
            "net_pnl": str(gross - D(pos["entry_fee"]) - exit_fee), "closed_at": stamp(),
            "close_reason": reason, "exit_fill_id": str(uuid4())}
        row.payload = closed
        ep = session.get(Episode, pos["episode_id"])
        ep.payload = ep.payload | {"status": "closed", "reason": f"Paper position closed: {reason}."}
        self.event(session, "executor", "closed", ep.payload["reason"], pos["episode_id"], closed)
        return closed

    def mark(self, market: Snapshot):
        age = (utcnow() - market.timestamp).total_seconds()
        if not -2 <= age <= self.policy.max_data_age_seconds:
            return
        with self.transaction() as session:
            account = session.get(Account, 1)
            capital = self.capital(session, market)
            high = max(D(account.payload["high_water_equity"]), capital.equity)
            account.payload = account.payload | {"high_water_equity": str(high)}
            # Check the previous day's threshold BEFORE resetting the UTC day baseline.
            reason = None
            if capital.equity <= capital.day_start_equity * (1 - self.policy.daily_loss_fraction):
                reason = "Daily loss threshold reached."
            if capital.equity <= high * (1 - self.policy.drawdown_fraction):
                reason = "Maximum drawdown threshold reached."
            if reason and not account.payload["halt_reason"]:
                account.payload = account.payload | {"halt_reason": reason}
                self.event(session, "risk", "risk_halt", reason)
            for row in session.scalars(select(Position)):
                pos = row.payload
                if pos["status"] != "open":
                    continue
                long = pos["direction"] == "long"
                stop_hit = market.price <= D(pos["stop"]) if long else market.price >= D(pos["stop"])
                target_hit = market.price >= D(pos["target"]) if long else market.price <= D(pos["target"])
                if stop_hit or target_hit or reason:
                    self.close_in_transaction(session, row, market, "stop" if stop_hit else "target" if target_hit else "risk_halt")
                elif (origin := session.get(Episode, pos["episode_id"]).payload.get("research")) and (
                    market.timestamp - datetime.fromisoformat(pos["opened_at"])).total_seconds() >= origin["max_holding_seconds"]:
                    self.close_in_transaction(session, row, market, "strategy_time_limit")
            if account.payload["day"] != market.timestamp.date().isoformat():
                updated = self.capital(session, market)
                account.payload = account.payload | {"day": market.timestamp.date().isoformat(), "day_start_equity": str(updated.equity)}
                self.event(session, "system", "day_rollover", "UTC day baseline recorded; risk halts remain latched.")

    def operate(self, action: str, market: Snapshot | None) -> None:
        with self.transaction() as session:
            account = session.get(Account, 1)
            if action == "resume" and account.payload["halt_reason"]:
                raise ValueError("A risk halt is latched. Review the account before changing its policy; resume cannot override it.")
            if action == "close":
                if not market or not -2 <= (utcnow() - market.timestamp).total_seconds() <= self.policy.max_data_age_seconds:
                    raise ValueError("A fresh market price is required to close the paper position.")
                for row in session.scalars(select(Position)):
                    if row.payload["status"] == "open":
                        self.close_in_transaction(session, row, market, "operator")
            else:
                account.payload = account.payload | {"paused": action == "pause"}
            self.event(session, "operator", action, f"Operator action: {action}.")

    def events(self, after: int = 0, limit: int = 100) -> list[dict]:
        with Session(self.engine) as session:
            return [row.payload | {"id": row.id} for row in session.scalars(
                select(Event).where(Event.id > after).order_by(Event.id).limit(limit))]

    def state(self, market: Snapshot | None) -> dict:
        with self.lock, Session(self.engine) as session:
            account = session.get(Account, 1).payload
            episodes = [row.payload for row in session.scalars(select(Episode))]
            positions = [row.payload for row in session.scalars(select(Position))]
            capital = self.capital(session, market) if market else None
            latest = list(session.scalars(select(Event).order_by(Event.id.desc()).limit(80)))
            return {"account": account | {"equity": str(capital.equity) if capital else None,
                "available_cash": str(capital.available_cash) if capital else None,
                "net_realized_pnl": str(D(account["realized_gross"]) - D(account["fees_paid"])),
                "builder_revenue": "0", "funding_included": False},
                "episodes": sorted(episodes, key=lambda e: e["created_at"], reverse=True)[:100],
                "positions": sorted(positions, key=lambda p: p["opened_at"], reverse=True)[:100],
                "events": [row.payload | {"id": row.id} for row in reversed(latest)],
                "last_event_id": latest[0].id if latest else 0}

    def operational_snapshot(self) -> dict:
        """Read-only counters; these observations never authorize an entry."""
        with self.lock, Session(self.engine) as session:
            account = session.get(Account, 1).payload
            statuses = dict(session.execute(select(Episode.payload["status"].as_string(), func.count())
                                           .group_by(Episode.payload["status"].as_string())).all())
            open_positions = session.scalar(select(func.count()).select_from(Position)
                .where(Position.payload["status"].as_string() == "open"))
            day = utcnow().date().isoformat()
            calls = session.scalar(select(func.count()).select_from(Event).where(
                Event.payload["kind"].as_string() == "review_started",
                Event.payload["timestamp"].as_string().startswith(day)))
            return {"paper_paused": bool(account["paused"]), "paper_halt_reason": account["halt_reason"],
                "open_positions": open_positions, "reserved_entries": statuses.get("approved", 0),
                "pending_reviews": sum(statuses.get(status, 0) for status in ("queued", "analyzing", "risk_check", "capital_check")),
                "episodes_total": sum(statuses.values()), "review_calls_today": calls, "review_budget_day": day}

