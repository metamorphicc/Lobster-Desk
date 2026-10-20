import asyncio
from datetime import timedelta

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from lobster.config import Settings
from lobster.domain import utcnow
from lobster.external_reads import ExternalReads
from lobster.http_boundary import LocalBoundary
from lobster.main import create_app
from lobster.store import Store
from test_public_boundary import HEADERS, ORIGIN, PROXY


def test_slow_uploads_consume_slots_before_reading_body_and_release_them():
    async def run():
        gate, entered = asyncio.Event(), []
        async def app(scope, receive, send):
            await JSONResponse({"ok": True})(scope, receive, send)
        boundary = LocalBoundary(app, allowed_origins={ORIGIN}, proxy_token=PROXY)
        async def body(index):
            entered.append(index)
            await gate.wait()
            yield b"x"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=boundary), base_url=ORIGIN) as client:
            tasks = [asyncio.create_task(client.post("/", headers=HEADERS, content=body(i))) for i in range(8)]
            try:
                for _ in range(100):
                    if len(entered) == 8: break
                    await asyncio.sleep(0)
                assert len(entered) == 8
                response = await client.post("/", headers=HEADERS, content=body(9))
                assert response.status_code == 429 and 9 not in entered
            finally:
                gate.set()
                assert all(r.status_code == 200 for r in await asyncio.gather(*tasks))
            assert boundary.active == {}
            assert (await client.post("/", headers=HEADERS, content=b"ok")).status_code == 200
    asyncio.run(run())


def test_lookup_budget_survives_restart_and_has_global_bound(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path/'budget.db'}")
    try:
        budget = ExternalReads(store)
        for _ in range(10): budget.admit("peer")
        with pytest.raises(HTTPException) as failure: ExternalReads(store).admit("peer")
        assert failure.value.status_code == 429 and int(failure.value.headers["Retry-After"]) > 0
        for peer in range(50): budget.admit(str(peer))
        with pytest.raises(HTTPException) as failure: budget.admit("new-peer")
        assert failure.value.status_code == 429
        monkeypatch.setattr("lobster.external_reads.utcnow", lambda: utcnow() + timedelta(seconds=61))
        budget.admit("peer")
    finally: store.engine.dispose()


def test_public_lookup_limit_cannot_be_bypassed_by_network_or_address(tmp_path):
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path/'api.db'}", worker_enabled=False))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        calls = []
        async def inspect(address):
            calls.append(address)
            return {"address": address}
        app.state.users.inspect = app.state.mainnet_users.inspect = inspect
        for index in range(10):
            network = "testnet" if index % 2 else "mainnet"
            assert client.get(f"/api/v1/users/{network}/accounts/0x{index+1:040x}").status_code == 200
        response = client.get("/api/v1/users/mainnet/accounts/0x" + "f"*40)
        assert response.status_code == 429 and len(calls) == 10 and response.headers["Retry-After"]
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/v1/product/state").status_code == 200
