"""Same-machine ownership for the local SQLite paper worker."""

from contextlib import nullcontext
from pathlib import Path

from sqlalchemy.engine import make_url

from ..execution.lease import RunnerLease


def worker_lease(database_url: str):
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or url.query:
        raise ValueError("Local worker ownership requires a plain SQLite URL. Other databases require a separate leadership implementation.")
    if not url.database or url.database == ":memory:":
        # Each in-memory Store has its own database; no cross-process resource exists.
        return nullcontext()
    database = Path(url.database).resolve()
    return RunnerLease(database.with_name(database.name + ".paper-worker.lock"), purpose="paper worker")
