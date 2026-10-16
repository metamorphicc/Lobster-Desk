import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D
import json

from fastapi.testclient import TestClient
import httpx
import pytest

from lobster.config import Settings
from lobster.domain import Review, Snapshot, utcnow
from lobster.agents import DemoReviewer, output_schema
from lobster.execution.contracts import fingerprint
from lobster.main import create_app
from lobster.pipeline import Pipeline
from lobster.research.contracts import Dataset, HOUR, Hypotheses
from lobster.research.providers import AnthropicResearcher, development_context
from lobster.research.service import Campaign, Research, Signal
from lobster.store import Episode, Position, Store
from test_research_engine import history, strategy


@pytest.fixture
def lab(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'research.db'}")
    settings = Settings(_env_file=None, research_enabled=True)
    raw = history().model_dump(mode="json")
    delta = int(utcnow().timestamp()) // HOUR * HOUR - raw["as_of"]
    raw["as_of"] += delta
    for bar in raw["bars"]: bar["time"] += delta
    for rate in raw["funding"]: rate["time"] += delta
    dataset = Dataset.model_validate(raw)
    market = Snapshot(source="demo", price=dataset.bars[-1].close, timestamp=utcnow())
    research = Research(store, settings)
    class Provider:
        calls = 0
        verdict = "approve"
        async def propose(self, data):
            self.calls += 1
            return Hypotheses(regime="Synthetic upward regime for an offline invariant test.", candidates=[strategy()]), {"provider": "demo"}
        async def challenge(self, evidence):
            self.calls += 1
            return Review(verdict=self.verdict, summary="Offline independent fixture verdict; never a production observation.", evidence=["Synthetic complete history only."]), {"provider": "demo"}
    try: yield research, dataset, market, Provider()
    finally: store.engine.dispose()


def test_autonomous_cohort_emits_once_atomically_and_passes_existing_risk_pipeline(lab):
    research, dataset, market, provider = lab
    async def run():
        identifier = await research.run(dataset, provider)
        assert research.get(identifier)["status"] == "paper"
        assert provider.calls == 2
        assert await research.run(dataset, provider) is None
        with ThreadPoolExecutor(4) as pool:
            outputs = list(pool.map(lambda _: research.emit(dataset, market), range(4)))
        episode = next(item for item in outputs if item)
        assert sum(item is not None for item in outputs) == 1
        assert episode["research"]["campaign_id"] == identifier
        assert episode["status"] == "queued"
        pipeline = Pipeline(research.store, DemoReviewer())
        for _ in range(4): await pipeline.step(market)
        assert research.store.get_episode(episode["id"])["status"] == "approved"
        position = research.store.try_fill(episode["id"], market)
        assert position and position["execution_mode"] == "paper"
        # Strategy time exit belongs to the independent protection path.
        with research.store.transaction() as session:
            row = session.get(Position, position["id"])
            row.payload = row.payload | {"opened_at": (utcnow() - timedelta(hours=13)).isoformat()}
        research.store.mark(market)
        closed = research.store.state(market)["positions"][0]
        assert closed["close_reason"] == "strategy_time_limit"
        assert research.emit(dataset, market) is None
    asyncio.run(run())


def test_restart_does_not_replay_unknown_paid_request_and_daily_budget_is_durable(lab):
    research, dataset, _, provider = lab
    item = research.begin(dataset)
    research.reserve_call(item["id"], "researcher")
    restored = Research(research.store, research.settings)
    restored.recover()
    assert restored.get(item["id"])["status"] == "interrupted"
    assert asyncio.run(restored.run(dataset, provider)) is None and provider.calls == 0
    assert restored.summary()["calls_today"] == 1
    with pytest.raises(ValueError): restored.reserve_call(item["id"], "researcher")


def test_provider_failure_is_sanitized_and_no_retry_is_scheduled(lab):
    research, dataset, _, provider = lab
    async def broken(data): raise RuntimeError("secret-api-key-must-not-leak")
    provider.propose = broken
    identifier = asyncio.run(research.run(dataset, provider))
    assert research.get(identifier)["status"] == "failed"
    assert "secret-api-key" not in json.dumps(research.summary())
    assert asyncio.run(research.run(dataset, provider)) is None


def test_critic_veto_and_budget_exhaustion_cannot_activate(lab):
    research, dataset, market, provider = lab
    provider.verdict = "reject"
    identifier = asyncio.run(research.run(dataset, provider))
    assert research.get(identifier)["status"] == "vetoed" and research.emit(dataset, market) is None


def test_one_call_budget_cannot_skip_independent_critic(lab):
    research, dataset, market, provider = lab
    research.settings.max_research_calls_per_day = 1
    identifier = asyncio.run(research.run(dataset, provider))
    assert research.get(identifier)["status"] == "failed"
    assert research.active() is None and provider.calls == 1


def test_stale_market_changed_source_and_changed_history_never_emit(lab):
    research, dataset, market, provider = lab
    identifier = asyncio.run(research.run(dataset, provider))
    assert research.emit(dataset, market.model_copy(update={"timestamp": utcnow() - timedelta(minutes=1)})) is None
    assert research.emit(dataset, market.model_copy(update={"source": "hyperliquid"})) is None
    # Corrupting a stored evaluation is not silently accepted.
    with research.store.transaction() as session:
        row = session.get(Campaign, identifier)
        changed = deepcopy(row.payload)
        changed["evaluation"]["selected_hash"] = "f" * 64
        row.payload = changed
    with pytest.raises(ValueError, match="integrity"): research.emit(dataset, market)


def test_signal_and_pitch_roll_back_together(lab, monkeypatch):
    research, dataset, market, provider = lab
    asyncio.run(research.run(dataset, provider))
    original = research.store.submit_in_transaction
    def broken(*args):
        original(*args)
        raise RuntimeError("Interrupted transaction")
    monkeypatch.setattr(research.store, "submit_in_transaction", broken)
    with pytest.raises(RuntimeError): research.emit(dataset, market)
    assert research.store.state(market)["episodes"] == []
    assert research.summary()["signals"] == []
    monkeypatch.setattr(research.store, "submit_in_transaction", original)
    assert research.emit(dataset, market)["status"] == "queued"


def test_generation_context_never_contains_validation_holdout_or_current_price(lab):
    _, dataset, _, _ = lab
    context = development_context(dataset)
    cutoff = len(dataset.bars) * 6 // 10
    assert context["last_time"] == dataset.bars[cutoff-1].time
    assert max(b["time"] for b in context["recent_closed_bars"]) < dataset.bars[cutoff].time
    schema = output_schema(Hypotheses)
    assert '"minimum"' not in json.dumps(schema) and schema["additionalProperties"] is False
    assert "Local validation constraints" in json.dumps(schema)


def test_research_http_reads_have_no_activation_routes_or_keys(lab, tmp_path):
    research, dataset, _, provider = lab
    identifier = asyncio.run(research.run(dataset, provider))
    app = create_app(research.settings.model_copy(update={"database_url": str(research.store.engine.url),
        "worker_enabled": False, "treasury_path": str(tmp_path / "treasury.db")}))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        summary = client.get("/api/v1/research").json()
        assert summary["campaigns"][0]["id"] == identifier
        assert "dataset" not in summary["campaigns"][0]
        assert not summary["exchange_submission_enabled"]
        assert client.get("/api/v1/research/" + identifier).json()["dataset_hash"] == dataset.digest
        assert client.post("/api/v1/research", json={}).status_code == 405
        report = client.get("/api/v1/economics").json()
        assert report["policy"]["builder_fee_tenths_bps"] == 50
        assert report["policy"]["token_disposition"] == "burn" and not report["transfers_authorized"]


def test_paid_adapter_uses_fixed_host_bounded_schema_no_tools_and_local_validation(lab):
    _, dataset, _, _ = lab
    def respond(request):
        assert request.url.host == "api.anthropic.com" and request.url.path == "/v1/messages"
        body = json.loads(request.content)
        assert "tools" not in body and body["max_tokens"] == 2200
        assert body["output_config"]["format"]["schema"]["additionalProperties"] is False
        return httpx.Response(200, json={"stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 20},
            "content": [{"type": "text", "text": Hypotheses(regime="Synthetic test development regime", candidates=[strategy()]).model_dump_json()}]})
    async def run():
        settings = Settings(_env_file=None, agent_provider="anthropic", anthropic_api_key="offline-test-only", anthropic_model="test-model")
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result, metadata = await AnthropicResearcher(client, settings).propose(dataset)
            assert len(result.candidates) == 1 and metadata["input_tokens"] == 10
    asyncio.run(run())
