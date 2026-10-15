import asyncio
from datetime import timedelta
import json

import httpx
import pytest

from lobster.agents import AnthropicReviewer, DemoReviewer
from lobster.config import Settings
from lobster.domain import PitchInput, Snapshot, utcnow
from lobster.pipeline import Pipeline
from lobster.store import Store


def pitch():
    return PitchInput(author="Trader", direction="long", entry="60000", stop="59400", target="61200",
                      thesis="BTC breakout with volume confirmation and a defined stop.")


def test_durable_pipeline_can_resume_between_each_review(tmp_path):
    path = f"sqlite:///{tmp_path / 'pipeline.db'}"
    store = Store(path)
    id = store.submit(pitch(), "request")["id"]
    for expected in ("analyzing", "risk_check", "capital_check", "approved"):
        store = Store(path)
        market = Snapshot(source="demo", price="60000", timestamp=utcnow())
        asyncio.run(Pipeline(store, DemoReviewer()).step(market))
        assert store.get_episode(id)["status"] == expected
    assert store.try_fill(id, market)


def test_pipeline_does_not_review_stale_data(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'pipeline.db'}")
    id = store.submit(pitch(), "request")["id"]
    market = Snapshot(source="demo", price="60000", timestamp=utcnow() - timedelta(minutes=2))
    asyncio.run(Pipeline(store, DemoReviewer()).step(market))
    assert store.get_episode(id)["status"] == "queued"


def test_provider_errors_fail_closed(tmp_path):
    class BrokenReviewer:
        async def review(self, *args):
            raise ValueError("secret must not leak")
    store = Store(f"sqlite:///{tmp_path / 'pipeline.db'}")
    id = store.submit(pitch(), "request")["id"]
    pipeline = Pipeline(store, BrokenReviewer())
    market = Snapshot(source="demo", price="60000", timestamp=utcnow())
    asyncio.run(pipeline.step(market))
    asyncio.run(pipeline.step(market))
    assert store.get_episode(id)["status"] == "rejected"
    assert "secret" not in json.dumps(store.events())


def test_real_adapter_uses_schema_no_tools_and_records_usage():
    def respond(request):
        body = json.loads(request.content)
        assert body["max_tokens"] == 600
        assert "tools" not in body
        assert body["output_config"]["format"]["schema"]["additionalProperties"] is False
        return httpx.Response(200, json={"stop_reason": "end_turn", "model": "test-model", "content": [
            {"type": "text", "text": json.dumps({"verdict": "reject", "summary": "The supplied data does not support this breakout.",
                                                    "evidence": ["No volume confirmation."]})}],
            "usage": {"input_tokens": 123, "output_tokens": 45}})
    async def run():
        settings = Settings(_env_file=None, agent_provider="anthropic", anthropic_api_key="test-only", anthropic_model="test-model")
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            review, metadata = await AnthropicReviewer(client, settings).review("analyst", pitch(),
                Snapshot(source="demo", price="60000", timestamp=utcnow()), [])
            assert review.verdict == "reject"
            assert metadata["input_tokens"] == 123
    asyncio.run(run())


def test_live_provider_requires_explicit_credentials_and_model():
    with pytest.raises(ValueError):
        Settings(_env_file=None, agent_provider="anthropic", anthropic_api_key=None, anthropic_model=None)

