import asyncio
from decimal import Decimal as D

from fastapi.testclient import TestClient

from lobster.agents import DemoReviewer
from lobster.config import Settings
from lobster.domain import Snapshot, utcnow
from lobster.main import create_app
from lobster.pipeline import Pipeline


def test_api_pitch_to_fill_to_stop_and_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'end-to-end.db'}"
    config = Settings(_env_file=None, database_url=url, worker_enabled=False)
    app = create_app(config)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        runtime = app.state.runtime
        runtime.market = Snapshot(source="demo", price="60000", timestamp=utcnow())
        response = client.post("/api/v1/pitches", headers={"Idempotency-Key": "e2e-request"}, json={
            "author": "QA trader", "direction": "long", "entry": "60000", "stop": "59400", "target": "61200",
            "thesis": "An explicit breakout setup for an end-to-end paper test."})
        assert response.status_code == 201
        id = response.json()["id"]
        for _ in range(4):
            asyncio.run(Pipeline(runtime.store, DemoReviewer()).step(runtime.market))
        runtime.store.try_fill(id, runtime.market)
        assert client.get(f"/api/v1/episodes/{id}").json()["status"] == "filled"
        runtime.market = Snapshot(source="demo", price="59300", timestamp=utcnow())
        runtime.store.mark(runtime.market)
        state = client.get("/api/v1/state").json()
        assert state["positions"][0]["status"] == "closed"
        assert state["positions"][0]["close_reason"] == "stop"
        assert D(state["account"]["cash"]) == D("1000") + D(state["positions"][0]["net_pnl"])
        last_event = state["last_event_id"]
        final_cash = state["account"]["cash"]

    with TestClient(create_app(config), base_url="http://127.0.0.1") as restarted:
        state = restarted.get("/api/v1/state").json()
        assert state["account"]["cash"] == final_cash
        assert state["episodes"][0]["status"] == "closed"
        assert state["last_event_id"] == last_event
        assert state["account"]["builder_revenue"] == "0"


def test_independent_review_veto_never_reserves_capital(tmp_path):
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'veto.db'}", worker_enabled=False))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        runtime = app.state.runtime
        runtime.market = Snapshot(source="demo", price="60000", timestamp=utcnow())
        response = client.post("/api/v1/pitches", headers={"Idempotency-Key": "veto-request"}, json={
            "author": "QA trader", "direction": "long", "entry": "60000", "stop": "60600", "target": "61200",
            "thesis": "A deliberately invalid stop for an end-to-end veto test."})
        id = response.json()["id"]
        for _ in range(4):
            asyncio.run(Pipeline(runtime.store, DemoReviewer()).step(runtime.market))
        assert client.get(f"/api/v1/episodes/{id}").json()["status"] == "rejected"
        assert "reject" in client.get(f"/api/v1/episodes/{id}").json()["reason"]
        assert runtime.store.try_fill(id, runtime.market) is None
        assert client.get("/api/v1/state").json()["positions"] == []

