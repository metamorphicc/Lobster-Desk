"""Persisted budgets for API endpoints that amplify requests to the exchange."""
import re

from fastapi import HTTPException, Request
from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .admission import consume
from .domain import utcnow


class Base(DeclarativeBase): pass


class ReadControl(Base):
    __tablename__ = "external_read_control"
    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ExternalReads:
    def __init__(self, store):
        self.store = store
        Base.metadata.create_all(store.engine)
        with store.transaction() as db:
            if not db.get(ReadControl, 1):
                empty = {"last_seen_us": 0, "peers": {}}
                db.add(ReadControl(id=1, payload={"clients": empty, "global": empty}))

    def admit(self, peer):
        with self.store.transaction() as db:
            row = db.get(ReadControl, 1)
            now = utcnow()
            clients, retry = consume(row.payload["clients"], peer, now)
            global_state = row.payload["global"]
            if not retry:
                global_state, retry = consume(global_state, "exchange-reads", now, limit=60)
            row.payload = {"clients": clients, "global": global_state}
        if retry:
            raise HTTPException(429, "Account lookup capacity reached. Please retry shortly.", headers={"Retry-After": str(retry)})


async def admit_external_read(request: Request):
    path = request.url.path
    expensive = bool(re.fullmatch(r"/api/v1/users/(?:mainnet|testnet)/(?:accounts/[^/]+|capital/refresh|order-preview|fee-quote|consent-preview)", path)
        or path == "/api/v1/testnet/inspect" or path.startswith("/api/v1/testnet/preflight/"))
    if request.method == "OPTIONS" or not expensive: return
    try:
        request.app.state.external_reads.admit(request.client.host if request.client else "local")
    except HTTPException: raise
    except Exception:
        raise HTTPException(503, "Account lookup admission is unavailable.") from None
