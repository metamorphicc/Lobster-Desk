"""Durable bounded research and paper-only signal admission on the paper DB."""
import asyncio
from datetime import datetime
from decimal import Decimal as D

from sqlalchemy import JSON, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from ..domain import Snapshot, utcnow
from ..execution.contracts import fingerprint
from ..store import Base, Episode, Event, Position
from .contracts import Dataset, Hypotheses, Strategy, HOUR
from .engine import evaluate, pitch_for, signal


class Campaign(Base):
    __tablename__ = "research_campaigns"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Control(Base):
    __tablename__ = "research_control"
    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Signal(Base):
    __tablename__ = "research_signals"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


def compact(report):
    """Metrics for models/UI; full trades remain in the individual audit report."""
    return report | {"candidates": [row | {key: {k: v for k, v in row[key].items() if k != "trades"} if row[key] else None
        for key in ("development", "validation", "stress", "holdout")} for row in report["candidates"]]}


class Research:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        Base.metadata.create_all(store.engine)

    def recover(self):
        with self.store.transaction() as session:
            for row in session.scalars(select(Campaign)):
                if row.payload["status"] in {"generating", "testing", "challenging"}:
                    row.payload = row.payload | {"status": "interrupted", "reason": "Research interrupted. No model call was replayed; wait for the next scheduled cohort."}
                    self.store.event(session, "researcher", "research_interrupted", row.payload["reason"], data={"campaign_id": row.id})

    def begin(self, dataset):
        now = utcnow()
        if dataset.source != self.settings.market_source or dataset.as_of > now.timestamp() + 2 or not 0 <= now.timestamp() - dataset.bars[-1].time - HOUR < HOUR + 120:
            raise ValueError("Research requires fresh closed history from the configured source.")
        identifier = fingerprint({"dataset": dataset.digest, "engine": "research-v1", "policy": self.store.policy.model_dump(mode="json")})
        with self.store.transaction() as session:
            control = session.get(Control, 1)
            previous = control.payload if control else {}
            if session.get(Campaign, identifier): return None
            if previous.get("last_started_at") and (now - datetime.fromisoformat(previous["last_started_at"])).total_seconds() < self.settings.research_interval_seconds:
                return None
            item = {"id": identifier, "created_at": now.isoformat(), "source": dataset.source,
                "dataset_hash": dataset.digest, "dataset": dataset.model_dump(mode="json"), "calls": {},
                "status": "generating", "reason": "Preparing bounded strategy hypotheses.",
                "hypotheses": None, "evaluation": None, "critic": None, "selected_hash": None}
            session.add(Campaign(id=identifier, payload=item))
            payload = previous | {"last_started_at": now.isoformat()}
            if control: control.payload = payload
            else: session.add(Control(id=1, payload=payload))
            self.store.event(session, "researcher", "research_started", "A new BTC research cohort started; execution stays paper.", data={"campaign_id": identifier, "dataset_hash": dataset.digest})
            return item

    def reserve_call(self, identifier, role):
        with self.store.transaction() as session:
            row = session.get(Campaign, identifier)
            if not row or role in row.payload["calls"]: raise ValueError("A research role cannot be replayed.")
            day = utcnow().date().isoformat()
            count = session.scalar(select(func.count()).select_from(Event).where(
                Event.payload["kind"].as_string() == "research_call_started", Event.payload["timestamp"].as_string().startswith(day)))
            if count >= self.settings.max_research_calls_per_day: raise ValueError("Research call budget exhausted.")
            row.payload = row.payload | {"calls": row.payload["calls"] | {role: {"started_at": utcnow().isoformat()}}}
            self.store.event(session, role, "research_call_started", f"Starting one bounded {role} call.", data={"campaign_id": identifier})

    def update(self, identifier, status, reason, **changes):
        with self.store.transaction() as session:
            row = session.get(Campaign, identifier)
            row.payload = row.payload | changes | {"status": status, "reason": reason}
            self.store.event(session, "researcher", "research_" + status, reason, data={"campaign_id": identifier,
                "selected_hash": changes.get("selected_hash")})

    async def run(self, dataset, provider):
        item = await asyncio.to_thread(self.begin, dataset)
        if not item: return None
        identifier = item["id"]
        try:
            await asyncio.to_thread(self.reserve_call, identifier, "researcher")
            proposals, metadata = await provider.propose(dataset)
            proposals = Hypotheses.model_validate(proposals.model_dump(mode="json"))
            await asyncio.to_thread(self.update, identifier, "testing", proposals.regime,
                hypotheses=proposals.model_dump(mode="json"), generation_metadata=metadata)
            report = await asyncio.to_thread(evaluate, dataset, proposals.candidates)
            await asyncio.to_thread(self.update, identifier, "challenging" if report["selected_hash"] else "rejected",
                "One candidate passed coded history gates; awaiting an independent veto review." if report["selected_hash"] else "No candidate passed the coded historical gates. The cohort stays inactive.",
                evaluation=report, evaluation_hash=fingerprint(report))
            if not report["selected_hash"]: return identifier
            await asyncio.to_thread(self.reserve_call, identifier, "critic")
            review, metadata = await provider.challenge(compact(report))
            from ..domain import Review
            review = Review.model_validate(review.model_dump(mode="json"))
            await asyncio.to_thread(self.update, identifier, "paper" if review.verdict == "approve" else "vetoed", review.summary,
                critic=review.model_dump(mode="json"), critic_metadata=metadata,
                selected_hash=report["selected_hash"] if review.verdict == "approve" else None)
            if review.verdict == "approve":
                with self.store.transaction() as session:
                    control = session.get(Control, 1)
                    control.payload = control.payload | {"active_id": identifier}
            return identifier
        except asyncio.CancelledError:
            # Shutdown leaves the durable attempt for recover(), never a retry.
            raise
        except Exception:
            await asyncio.to_thread(self.update, identifier, "failed", "Research failed validation, provider access or its call budget. No strategy was authorized and no automatic call retry was made.")
            return identifier

    def get(self, identifier):
        with self.store.transaction() as session:
            row = session.get(Campaign, identifier)
            if not row: return None
            item = row.payload
            dataset = Dataset.model_validate(item["dataset"])
            if dataset.digest != item["dataset_hash"] or (item["evaluation"] and fingerprint(item["evaluation"]) != item["evaluation_hash"]):
                raise ValueError("Research audit integrity failed.")
            return item

    def active(self):
        with self.store.transaction() as session:
            control = session.get(Control, 1)
            identifier = control.payload.get("active_id") if control else None
        item = self.get(identifier) if identifier else None
        if not item or item["status"] != "paper": return None
        if (utcnow() - datetime.fromisoformat(item["created_at"])).total_seconds() < -2:
            raise ValueError("Research creation time is in the future; entry fails closed.")
        if (utcnow() - datetime.fromisoformat(item["created_at"])).total_seconds() > 7 * 86400:
            self.update(item["id"], "retired", "Candidate expired after seven days; fresh research is required.")
            return None
        evaluation = item["evaluation"]
        selected = next((row for row in evaluation["candidates"] if row["strategy_hash"] == item["selected_hash"]), None)
        if not selected or not selected["paper_candidate"] or not item["critic"] or item["critic"]["verdict"] != "approve":
            raise ValueError("The paper candidate lacks bound historical and critic approval.")
        strategy = Strategy.model_validate(selected["strategy"])
        if strategy.digest != item["selected_hash"] or evaluation["dataset_hash"] != item["dataset_hash"]:
            raise ValueError("Research strategy/dataset binding changed.")
        return item, strategy

    def emit(self, dataset, market):
        if not self.settings.research_enabled or market is None: return None
        now = utcnow()
        if (market.source != self.settings.market_source or dataset.source != market.source
            or not -2 <= (now - market.timestamp).total_seconds() <= self.store.policy.max_data_age_seconds
            or dataset.as_of > now.timestamp() + 2
            or dataset.bars[-1].time + HOUR != int(now.timestamp()) // HOUR * HOUR): return None
        selected = self.active()
        if not selected: return None
        campaign, strategy = selected
        if campaign["source"] != market.source: return None
        bar = dataset.bars[-1]
        direction = signal(strategy, dataset.bars)
        if direction is None: return None
        request_id = "research-" + fingerprint({"strategy": strategy.digest, "bar": bar.time, "source": dataset.source})[:48]
        pitch = pitch_for(strategy, direction, market.price)
        provenance = {"campaign_id": campaign["id"], "strategy_hash": strategy.digest,
            "signal_bar": bar.time, "max_holding_seconds": strategy.max_holding_bars * HOUR}
        with self.store.transaction() as session:
            if session.get(Signal, request_id): return None
            closed = [p.payload for p in session.scalars(select(Position)) if p.payload["status"] == "closed"
                and (session.get(Episode, p.episode_id).payload.get("research") or {}).get("strategy_hash") == strategy.digest]
            retired = len(closed) >= 8 and sum((D(p["net_pnl"]) for p in closed), D(0)) <= 0
            busy = self.store.capital(session, market)
            reason = ("Forward paper performance is nonpositive after at least eight closed trades." if retired else
                "The paper account is occupied, paused or halted." if busy.occupied or busy.paused else
                "Price moved beyond the closed signal's 0.2% entry allowance." if abs(market.price - bar.close) / bar.close > self.store.policy.max_entry_slip else None)
            if retired:
                row = session.get(Campaign, campaign["id"])
                row.payload = row.payload | {"status": "retired", "reason": reason}
            if reason:
                session.add(Signal(id=request_id, payload=provenance | {"status": "skipped", "reason": reason, "episode_id": None}))
                self.store.event(session, "researcher", "signal_skipped", reason, data=provenance)
                return None
            # Atomic signal, pitch and provenance. The existing analyst/risk/banker
            # pipeline still has to approve; this never submits an exchange order.
            episode = self.store.submit_in_transaction(session, pitch, request_id, provenance)
            session.add(Signal(id=request_id, payload=provenance | {"status": "pitched", "episode_id": episode["id"]}))
            self.store.event(session, "researcher", "research_signal", "A closed-hour strategy signal entered the normal paper review pipeline.", episode["id"], provenance)
            return episode

    def summary(self):
        with self.store.transaction() as session:
            rows = list(session.scalars(select(Campaign).order_by(Campaign.payload["created_at"].as_string().desc()).limit(12)))
            control = session.get(Control, 1)
            used = session.scalar(select(func.count()).select_from(Event).where(Event.payload["kind"].as_string() == "research_call_started",
                Event.payload["timestamp"].as_string().startswith(utcnow().date().isoformat())))
            campaigns = [{key: row.payload.get(key) for key in ("id", "created_at", "source", "dataset_hash", "status", "reason", "hypotheses", "critic", "selected_hash")}
                | {"evaluation": compact(row.payload["evaluation"]) if row.payload["evaluation"] else None} for row in rows]
            recent = list(session.scalars(select(Signal).order_by(Signal.payload["signal_bar"].as_integer().desc()).limit(20)))
            return {"enabled": self.settings.research_enabled, "provider": self.settings.agent_provider,
                "active_id": control.payload.get("active_id") if control else None,
                "interval_seconds": self.settings.research_interval_seconds, "history_bars": self.settings.research_history_bars,
                "calls_today": used, "daily_call_limit": self.settings.max_research_calls_per_day,
                "campaigns": campaigns, "signals": [row.payload for row in recent], "execution_mode": "paper",
                "exchange_submission_enabled": False}
