from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from lobster.config import Settings
from lobster.domain import PitchInput
from lobster.main import create_app
from lobster.ops.backup import restore_drill, snapshot
from lobster.store import PitchAdmission, Store


NOW = datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)


def pitch():
    return PitchInput(author="Admission QA", direction="long", entry="60000", stop="59400", target="61800",
        thesis="A bounded paper setup with a defined stop and target.")


def test_sliding_limit_survives_restart_and_releases_only_expired_requests(tmp_path):
    url = f"sqlite:///{tmp_path / 'paper.db'}"
    store = Store(url)
    assert store.consume_pitch_request("peer", NOW) == 0
    for _ in range(9):
        assert store.consume_pitch_request("peer", NOW + timedelta(seconds=20)) == 0
    store.engine.dispose()
    restarted = Store(url)
    assert restarted.consume_pitch_request("peer", NOW + timedelta(seconds=59)) == 1
    assert restarted.consume_pitch_request("peer", NOW + timedelta(seconds=60)) == 0
    assert restarted.consume_pitch_request("peer", NOW + timedelta(seconds=60)) == 20


def test_clock_rollback_does_not_reset_or_shorten_the_window(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'paper.db'}")
    for _ in range(10):
        assert store.consume_pitch_request("peer", NOW) == 0
    assert store.consume_pitch_request("peer", NOW - timedelta(seconds=100)) == 160
    assert store.consume_pitch_request("peer", NOW + timedelta(seconds=60)) == 0
    # New admissions after a clock jump retain the persisted time floor.
    for _ in range(9):
        assert store.consume_pitch_request("peer", NOW - timedelta(seconds=100)) == 0
    assert store.consume_pitch_request("peer", NOW) == 120


def test_independent_stores_cannot_exceed_one_peer_budget(tmp_path):
    url = f"sqlite:///{tmp_path / 'paper.db'}"
    stores = [Store(url) for _ in range(4)]
    with ThreadPoolExecutor(8) as executor:
        results = list(executor.map(lambda i: stores[i % 4].consume_pitch_request("peer", NOW), range(32)))
    assert results.count(0) == 10
    assert results.count(60) == 22
    assert not stores[0].state(None)["episodes"]


def test_peer_state_is_bounded_and_expired_peers_are_pruned(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'paper.db'}")
    for index in range(128):
        assert store.consume_pitch_request(f"peer-{index}", NOW) == 0
    assert store.consume_pitch_request("unknown-peer", NOW) == 60
    with Session(store.engine) as session:
        data = session.get(PitchAdmission, 1).payload
        assert len(data["peers"]) == 128
        assert "peer-" not in json.dumps(data)
    assert store.consume_pitch_request("unknown-peer", NOW + timedelta(seconds=60)) == 0
    with Session(store.engine) as session:
        assert len(session.get(PitchAdmission, 1).payload["peers"]) == 1


def test_queue_bound_is_shared_and_idempotency_works_when_full(tmp_path):
    url = f"sqlite:///{tmp_path / 'paper.db'}"
    stores = [Store(url) for _ in range(4)]
    def submit(index):
        try:
            return stores[index % 4].submit(pitch(), f"pitch-{index}")
        except ValueError as error:
            assert "queue is full" in str(error)
            return None
    with ThreadPoolExecutor(8) as executor:
        results = list(executor.map(submit, range(32)))
    assert sum(result is not None for result in results) == 20
    first = next(result for result in results if result)
    request = f"pitch-{results.index(first)}"
    assert stores[0].submit(pitch(), request) == first
    with pytest.raises(ValueError, match="different pitch"):
        stores[0].submit(pitch().model_copy(update={"author": "Other"}), request)
    assert len([event for event in stores[0].events() if event["kind"] == "pitch_submitted"]) == 20


def test_snapshot_restores_active_rate_window(tmp_path):
    source = tmp_path / "paper.db"
    store = Store(f"sqlite:///{source}")
    for _ in range(10):
        store.consume_pitch_request("peer", NOW)
    manifest = snapshot({"paper": source}, tmp_path / "backup")
    restore_drill(manifest, tmp_path / "restore")
    recovered = Store(f"sqlite:///{tmp_path / 'restore/paper.sqlite3'}")
    assert recovered.consume_pitch_request("peer", NOW) == 60


def test_review_budget_remains_atomic_between_independent_stores(tmp_path):
    url = f"sqlite:///{tmp_path / 'paper.db'}"
    stores = [Store(url) for _ in range(4)]
    ids = []
    for index in range(4):
        episode = stores[0].submit(pitch(), f"review-{index}")
        stores[0].advance(episode["id"], "queued", "analyzing", "system", "Ready for review.")
        ids.append(episode["id"])
    with ThreadPoolExecutor(4) as executor:
        results = list(executor.map(lambda i: stores[i].reserve_review(ids[i], "analyzing", "analyst", 1), range(4)))
    assert sum(results) == 1
    assert stores[0].operational_snapshot()["review_calls_today"] == 1
    assert len([event for event in stores[0].events() if event["kind"] == "review_started"]) == 1
    assert sum(stores[0].get_episode(id)["status"] == "rejected" for id in ids) == 3


def test_http_limit_survives_restart_and_ignores_forwarded_peer_headers(tmp_path):
    config = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}", worker_enabled=False)
    with TestClient(create_app(config), base_url="http://127.0.0.1") as client:
        for _ in range(10):
            assert client.post("/api/v1/pitches", json=pitch().model_dump(mode="json"),
                headers={"Idempotency-Key": "retry-pitch"}).status_code == 201
    with TestClient(create_app(config), base_url="http://127.0.0.1") as client:
        response = client.post("/api/v1/pitches", json=pitch().model_dump(mode="json"),
            headers={"Idempotency-Key": "new-pitch", "X-Forwarded-For": "192.0.2.99", "Forwarded": "for=192.0.2.99"})
        assert response.status_code == 429
        assert 1 <= int(response.headers["Retry-After"]) <= 60
        assert len(client.get("/api/v1/state").json()["episodes"]) == 1


def test_admission_database_failure_is_static_503_and_creates_no_pitch(tmp_path, monkeypatch):
    config = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}", worker_enabled=False)
    app = create_app(config)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        def fail(*args):
            raise RuntimeError("synthetic-private-database-location")
        monkeypatch.setattr(app.state.runtime.store, "consume_pitch_request", fail)
        response = client.post("/api/v1/pitches", json=pitch().model_dump(mode="json"), headers={"Idempotency-Key": "new-pitch"})
        assert response.status_code == 503
        assert "synthetic-private" not in response.text
        assert not app.state.runtime.store.state(None)["episodes"]


@pytest.mark.parametrize("bad", [{"last_seen_us": True, "peers": {}}, {"last_seen_us": 0, "peers": {"bad": []}},
    {"last_seen_us": 0, "peers": {"a" * 64: [1]}}])
def test_corrupted_admission_state_fails_closed(tmp_path, bad):
    store = Store(f"sqlite:///{tmp_path / 'paper.db'}")
    with store.transaction() as session:
        session.add(PitchAdmission(id=1, payload=bad))
    with pytest.raises(ValueError, match="admission"):
        store.consume_pitch_request("peer", NOW)
