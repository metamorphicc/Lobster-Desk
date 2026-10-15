import asyncio
from contextlib import suppress
from datetime import timedelta
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from lobster.agents import DemoReviewer
from lobster.config import Settings
from lobster.domain import PitchInput, Snapshot, utcnow
from lobster.execution.settings import TestnetSettings
from lobster.main import Runtime, create_app
from lobster.market import DemoFeed
from lobster.ops.readiness import readiness
from lobster.pipeline import Pipeline
from lobster.store import Account, Store


class AliveTask:
    def done(self):
        return False


@pytest.fixture
def runtime(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'diagnostics.db'}")
    runtime = Runtime(Settings(_env_file=None, worker_enabled=True), store)
    runtime.market = Snapshot(source="demo", price="60000", timestamp=utcnow())
    runtime.last_market_tick = runtime.last_decision_tick = utcnow()
    runtime.tasks = {"market": AliveTask(), "decision": AliveTask()}
    yield runtime
    store.engine.dispose()


def reviewed(runtime):
    episode = runtime.store.submit(PitchInput(author="Diagnostics QA", direction="long", entry="60000",
        stop="59400", target="61800", thesis="A bounded setup for read-only diagnostic counters."), "diagnostic-123")
    for _ in range(4):
        asyncio.run(Pipeline(runtime.store, DemoReviewer()).step(runtime.market))
    return runtime.store.get_episode(episode["id"])


def test_healthy_local_runtime_is_not_a_production_or_exchange_certificate(runtime):
    before = runtime.store.state(None)
    report = readiness(runtime)
    assert report["service_ready"] and report["status"] == "ready"
    assert report["review_budget"]["remaining"] == 100
    assert not report["production_verified"] and not report["exchange_execution_verified"]
    assert report["diagnostic_only"] and not report["alerts"]
    assert runtime.store.state(None) == before


def test_pause_and_halt_are_visible_without_claiming_the_service_is_down(runtime):
    runtime.store.operate("pause", runtime.market)
    with runtime.store.transaction() as session:
        account = session.get(Account, 1)
        account.payload = account.payload | {"halt_reason": "Daily risk threshold reached."}
    report = readiness(runtime)
    assert report["service_ready"]
    assert {"Operator pause", "Latched paper risk halt"}.issubset(report["entry_blockers"])
    assert {a["code"] for a in report["alerts"]} == {"paper_paused", "paper_halted"}


def test_stale_data_with_open_exposure_is_a_critical_paper_alert(runtime):
    episode = reviewed(runtime)
    runtime.store.try_fill(episode["id"], runtime.market)
    runtime.market = runtime.market.model_copy(update={"timestamp": utcnow() - timedelta(seconds=60)})
    before = runtime.store.state(None)
    report = readiness(runtime)
    assert not report["service_ready"] and report["paper"]["open_positions"] == 1
    assert any(a["code"] == "market_unavailable" and a["severity"] == "critical" for a in report["alerts"])
    assert runtime.store.state(None) == before


@pytest.mark.parametrize("field", ["market", "decision"])
def test_missing_or_stale_worker_is_not_ready(runtime, field):
    runtime.tasks.pop(field)
    assert not readiness(runtime)["service_ready"]
    runtime.tasks[field] = AliveTask()
    setattr(runtime, f"last_{field}_tick", utcnow() - timedelta(seconds=150))
    report = readiness(runtime)
    assert not report["service_ready"]
    assert any(a["code"] == field + "_worker_unavailable" for a in report["alerts"])


@pytest.mark.parametrize("change", ["future", "source", "feed_error", "worker_error"])
def test_invalid_market_or_worker_health_never_reports_ready(runtime, change):
    if change == "future":
        runtime.market = runtime.market.model_copy(update={"timestamp": utcnow() + timedelta(seconds=60)})
    elif change == "source":
        runtime.market = runtime.market.model_copy(update={"source": "hyperliquid"})
    elif change == "feed_error":
        runtime.market_error = "Observation failed."
    else:
        runtime.worker_error = "Decision worker failed."
    assert not readiness(runtime)["service_ready"]


def test_review_budget_and_reserved_slot_are_independent_diagnostics(runtime):
    episode = reviewed(runtime)
    runtime.settings.max_review_calls_per_day = 2
    report = readiness(runtime)
    assert episode["status"] == "approved"
    assert report["paper"]["reserved_entries"] == 1
    assert report["review_budget"]["used"] == 2 and report["review_budget"]["remaining"] == 0
    assert report["service_ready"]
    assert "Paper execution slot occupied" in report["entry_blockers"]
    assert any(a["code"] == "review_budget_exhausted" for a in report["alerts"])


def test_database_failure_is_unknown_not_zero_and_never_echoes_exception(runtime, monkeypatch):
    def fail():
        raise ValueError("SYNTHETIC_PRIVATE_DATABASE_MARKER")
    monkeypatch.setattr(runtime.store, "operational_snapshot", fail)
    report = readiness(runtime)
    assert not report["service_ready"] and report["paper"] is None and report["review_budget"] is None
    assert "SYNTHETIC_PRIVATE_DATABASE_MARKER" not in json.dumps(report)


def test_testnet_uncertainty_is_reported_from_local_state_without_network_writes(runtime, execution_rig):
    broker, exchange, setup, _ = execution_rig
    asyncio.run(broker.stage(setup))
    exchange.failures["entry"] = "before"
    asyncio.run(broker.dispatch(setup.episode_id))
    writes = len(exchange.writes)
    before = broker.ledger.snapshot()
    report = readiness(runtime, SimpleNamespace(ledger=broker.ledger))
    assert report["service_ready"]  # This flag describes the independent paper runtime.
    assert any(a["code"] == "testnet_reconciliation" and a["severity"] == "critical" for a in report["alerts"])
    assert len(exchange.writes) == writes and broker.ledger.snapshot() == before
    assert "thesis" not in json.dumps(report)


def test_actual_local_workers_publish_ticks_and_stop_being_ready_after_cancellation(runtime):
    async def run():
        runtime.tasks = {"market": asyncio.create_task(runtime.market_loop(DemoFeed())),
                         "decision": asyncio.create_task(runtime.decision_loop(DemoReviewer()))}
        try:
            await asyncio.sleep(0)
            assert runtime.last_market_tick and runtime.last_decision_tick
            assert readiness(runtime)["service_ready"]
        finally:
            for task in runtime.tasks.values():
                task.cancel()
            for task in runtime.tasks.values():
                with suppress(asyncio.CancelledError):
                    await task
        assert not readiness(runtime)["service_ready"]
    asyncio.run(run())


def test_liveness_and_readiness_have_distinct_http_statuses(tmp_path):
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}", worker_enabled=False),
                     TestnetSettings(_env_file=None))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        before = app.state.runtime.store.state(None)
        assert client.get("/api/health").json()["probe"] == "liveness"
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/ready").status_code == 503
        report = client.get("/api/v1/ops/status")
        assert report.status_code == 200 and not report.json()["service_ready"]
        assert not report.json()["production_verified"]
        assert app.state.runtime.store.state(None) == before
