from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest

from lobster.config import Settings
from lobster.domain import Snapshot, utcnow
from lobster.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}", worker_enabled=False,
                              operator_token="test-only-operator-token-12345"))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        app.state.runtime.market = Snapshot(source="demo", price="60000", timestamp=utcnow())
        yield client


def body():
    return {"author": "Trader", "direction": "long", "entry": "60000", "stop": "59400", "target": "61200",
            "thesis": "A breakout setup with defined invalidation and a target."}


def test_state_is_honest_about_modes_and_revenue(client):
    result = client.get("/api/v1/state").json()
    assert result["service"]["execution_mode"] == "paper"
    assert result["service"]["agent_provider"] == "demo"
    assert result["account"]["builder_revenue"] == "0"
    assert result["account"]["funding_included"] is False
    assert result["service"]["fee_collection_enabled"] is False


def test_submit_retry_has_one_episode_and_public_journal(client):
    headers = {"Idempotency-Key": "request-123"}
    first = client.post("/api/v1/pitches", json=body(), headers=headers)
    second = client.post("/api/v1/pitches", json=body(), headers=headers)
    assert first.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert client.get(f"/api/v1/episodes/{first.json()['id']}").status_code == 200
    assert len(client.get("/api/v1/state").json()["episodes"]) == 1
    events = client.get("/api/v1/journal").json()["events"]
    assert events[-1]["kind"] == "pitch_submitted"
    assert client.get(f"/api/v1/journal?after={events[-1]['id']}").json()["events"] == []


def test_missing_or_bad_idempotency_key(client):
    assert client.post("/api/v1/pitches", json=body()).status_code == 422
    assert client.post("/api/v1/pitches", json=body(), headers={"Idempotency-Key": "bad"}).status_code == 422


def test_operator_is_protected(client):
    assert client.post("/api/v1/operator", json={"action": "pause"}).status_code == 401
    response = client.post("/api/v1/operator", json={"action": "pause"},
        headers={"Authorization": "Bearer test-only-operator-token-12345"})
    assert response.status_code == 200
    assert client.get("/api/v1/state").json()["account"]["paused"]


def test_validation_and_local_rate_limit(client):
    invalid = body() | {"symbol": "ETH"}
    assert client.post("/api/v1/pitches", json=invalid, headers={"Idempotency-Key": "invalid-123"}).status_code == 422
    for i in range(10):
        assert client.post("/api/v1/pitches", json=body(), headers={"Idempotency-Key": f"request-{i}"}).status_code == 201
    assert client.post("/api/v1/pitches", json=body(), headers={"Idempotency-Key": "request-11"}).status_code == 429


def test_no_real_trading_route(client):
    assert client.post("/api/v1/orders", json={}).status_code == 404

