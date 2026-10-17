"""Exactly-once paper funding settlements from complete historical input."""
from datetime import datetime
from decimal import Decimal as D

from sqlalchemy import JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column

from .domain import utcnow
from .execution.contracts import fingerprint
from .research.contracts import Dataset, HOUR
from .store import Account, Base, Position


class PaperSettlement(Base):
    __tablename__ = "paper_funding_settlements"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class PaperFunding:
    def __init__(self, store):
        self.store = store
        Base.metadata.create_all(store.engine)

    def enable(self):
        with self.store.transaction() as session:
            account = session.get(Account, 1)
            if account.payload.get("funding_enabled"): return
            legacy = any(not row.payload.get("funding_included") for row in session.scalars(select(Position)))
            account.payload = account.payload | {"funding_enabled": True, "funding_net": "0", "funding_legacy": legacy,
                "funding_started_at": utcnow().isoformat(), "funding_error": None}
            self.store.event(session, "system", "paper_funding_enabled", "Hourly paper funding enabled for new positions. Historical unmodeled positions remain labelled separately.")

    def pending(self):
        now = int(utcnow().timestamp())
        with self.store.transaction() as session:
            rows = [row.payload for row in session.scalars(select(Position)) if row.payload.get("funding_included")]
            return [p for p in rows if p["funding_cursor"] < int(datetime.fromisoformat(p["closed_at"]).timestamp() if p["closed_at"] else now) // HOUR * HOUR]

    def fail(self):
        with self.store.transaction() as session:
            account = session.get(Account, 1)
            account.payload = account.payload | {"funding_error": "Paper funding settlement data unavailable; new entries wait for reconciliation."}

    def apply(self, dataset: Dataset):
        dataset = Dataset.model_validate(dataset.model_dump(mode="json"))
        if dataset.as_of > utcnow().timestamp() + 2: raise ValueError("Funding dataset is future-dated.")
        events = {f.time // HOUR * HOUR: f for f in dataset.funding}
        prices = {bar.time + HOUR: bar.close for bar in dataset.bars}
        with self.store.transaction() as session:
            account = session.get(Account, 1)
            if not account.payload.get("funding_enabled"): raise ValueError("Paper funding is not enabled.")
            if account.payload.get("market_source") not in {None, dataset.source}: raise ValueError("Funding source changed.")
            delta = D(0)
            for row in session.scalars(select(Position)):
                p = row.payload
                if not p.get("funding_included"): continue
                cutoff = min(int(utcnow().timestamp()), int(datetime.fromisoformat(p["closed_at"]).timestamp()) if p["closed_at"] else int(utcnow().timestamp()))
                target = cutoff // HOUR * HOUR
                if target <= p["funding_cursor"]: continue
                if p["market_source"] != dataset.source: raise ValueError("Position funding source differs.")
                amount = D(0)
                for hour in range(p["funding_cursor"] + HOUR, target + 1, HOUR):
                    if hour not in events or hour not in prices: raise ValueError("Funding history cannot cover every owed settlement.")
                    sign = D(1) if p["direction"] == "long" else D(-1)
                    paid = -sign * D(p["quantity"]) * prices[hour] * events[hour].rate
                    receipt = {"position_id": p["id"], "hour": hour, "source": dataset.source,
                        "rate": str(events[hour].rate), "notional_price_proxy": str(prices[hour]), "amount": str(paid)}
                    key = p["id"] + ":" + str(hour)
                    previous = session.get(PaperSettlement, key)
                    if previous:
                        if previous.payload != receipt: raise ValueError("Conflicting paper funding receipt.")
                        raise ValueError("Funding cursor conflicts with an already-applied receipt.")
                    session.add(PaperSettlement(id=key, payload=receipt))
                    self.store.event(session, "executor", "paper_funding", "A historical hourly funding settlement was applied to paper capital.", p["episode_id"], receipt)
                    amount += paid
                updated = p | {"funding_cursor": target, "funding_net": str(D(p.get("funding_net", "0")) + amount)}
                if p["status"] == "closed": updated["net_pnl"] = str(D(p["net_pnl"]) + amount)
                row.payload = updated
                delta += amount
            account.payload = account.payload | {"cash": str(D(account.payload["cash"]) + delta),
                "funding_net": str(D(account.payload.get("funding_net", "0")) + delta), "funding_error": None}
            return delta
