"""Durable inventory of canonical financial journals, never signing keys."""
from pathlib import Path

from sqlalchemy import JSON, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..execution.contracts import fingerprint
from ..domain import utcnow


class Base(DeclarativeBase): pass


class JournalLocation(Base):
    __tablename__ = "execution_catalog"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_key: Mapped[str] = mapped_column(String(64), unique=True)
    signer_key: Mapped[str] = mapped_column(String(64), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)


def register_journal(store, ledger, role):
    if role not in {"testnet", "project", "user"}: raise ValueError("Unknown execution role.")
    if ledger.engine.dialect.name != "sqlite" or not ledger.engine.url.database or ledger.engine.url.database == ":memory:":
        raise ValueError("Financial recovery catalog requires a file-backed SQLite journal.")
    path = Path(ledger.engine.url.database).resolve()
    if path == Path(store.engine.url.database).resolve(): raise ValueError("Financial/app databases must remain separate.")
    control = ledger.snapshot()["control"]
    binding = {"network": control["network"], "account": control["account"], "signer": control["signer"], "path": str(path), "role": role}
    identity = fingerprint(binding)
    Base.metadata.create_all(store.engine)
    with store.transaction() as session:
        existing = session.get(JournalLocation, identity)
        if existing:
            if any(existing.payload[k] != v for k, v in binding.items()): raise ValueError("Financial catalog integrity failed.")
            return existing.payload
        for row in session.scalars(select(JournalLocation)):
            other = row.payload
            if other["network"] != binding["network"]: continue
            if (binding["account"] in {other["account"], other["signer"]}
                    or binding["signer"] in {other["account"], other["signer"]}):
                raise ValueError("A wallet/network is already bound to another canonical financial journal. Reconcile and migrate explicitly.")
        data = binding | {"id": identity, "registered_at": utcnow().isoformat()}
        session.add(JournalLocation(id=identity, owner_key=binding["network"]+":"+binding["account"],
            signer_key=binding["network"]+":"+binding["signer"], payload=data))
        return data
