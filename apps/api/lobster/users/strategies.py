"""Authenticated strategy authorship, bound before review; never trust display names."""
from sqlalchemy import JSON, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..execution.contracts import fingerprint


class Base(DeclarativeBase): pass


class StrategyOwner(Base):
    __tablename__ = "strategy_owners"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(42), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class UserStrategies:
    def __init__(self, store, network):
        if network not in {"testnet", "mainnet"}: raise ValueError("Unsupported strategy network.")
        self.store, self.network = store, network
        Base.metadata.create_all(store.engine)

    def submit(self, owner, pitch, key):
        identity = fingerprint({"owner": owner, "network": self.network, "request": key})[:32]
        strategy_hash = fingerprint(pitch.model_dump(mode="json"))
        attribution = {"strategy_id": identity, "strategy_hash": strategy_hash, "network": self.network,
            "owner_commitment": fingerprint({"strategy_id": identity, "owner": owner})}
        with self.store.transaction() as session:
            row = session.get(StrategyOwner, identity)
            if row and (row.owner != owner or row.payload["attribution"] != attribution): raise ValueError("Strategy request identity conflict.")
            episode = self.store.submit_in_transaction(session, pitch, "strategy-"+identity, attribution=attribution)
            if not row: session.add(StrategyOwner(id=identity, owner=owner, payload={"attribution": attribution, "episode_id": episode["id"]}))
            return episode

    def resolve(self, attribution, episode_id):
        with self.store.transaction() as session:
            row = session.get(StrategyOwner, attribution["strategy_id"])
            if (not row or row.payload["attribution"] != attribution or row.payload["episode_id"] != episode_id
                    or attribution["network"] != self.network
                    or fingerprint({"strategy_id": row.id, "owner": row.owner}) != attribution["owner_commitment"]):
                raise ValueError("Verified strategy author binding is missing or changed.")
            return row.owner

    def list(self, owner):
        with self.store.transaction() as session:
            return [row.payload for row in session.scalars(select(StrategyOwner).where(StrategyOwner.owner == owner))
                if row.payload["attribution"]["network"] == self.network]
