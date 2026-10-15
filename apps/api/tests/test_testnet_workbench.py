import asyncio
from copy import deepcopy
from datetime import timedelta

from fastapi.testclient import TestClient
import httpx
import pytest

from lobster.config import Settings
from lobster.domain import utcnow
from lobster.execution.lease import RunnerLease
from lobster.execution.settings import TestnetSettings
from lobster.execution.settings import require_separate_database
from lobster.execution.workbench import TestnetWorkbench
from lobster.main import create_app
from lobster.store import Store, digest


@pytest.fixture
def workbench(execution_rig, tmp_path):
    broker, exchange, setup, url = execution_rig
    paper_url = f"sqlite:///{tmp_path / 'review.db'}"
    store = Store(paper_url)
    episode = store.get_episode(setup.episode_id)
    settings = TestnetSettings(_env_file=None, database_url=url,
        account_address=exchange.account_address, api_wallet_address=broker.signer.address)
    client = httpx.AsyncClient()
    workbench = TestnetWorkbench(settings, client, paper_url)
    workbench.gateway = exchange
    yield workbench, exchange, episode, settings, paper_url
    workbench.ledger.engine.dispose()
    store.engine.dispose()
    asyncio.run(client.aclose())


def test_inspection_and_staging_never_send_or_create_commands(workbench):
    workbench, exchange, episode, *_ = workbench
    report = asyncio.run(workbench.inspect())
    assert report["ready_to_stage"]
    assert not report["private_key_loaded"] and not report["execution_enabled"]
    assert not report["funded_acceptance_verified"]
    preview, _ = asyncio.run(workbench.preflight(episode))
    assert preview["eligible"]
    assert float(preview["order"]["quantity"]) * float(preview["order"]["price"]) <= 50
    assert not workbench.ledger.snapshot()["trades"]
    first = asyncio.run(workbench.stage(episode))
    second = asyncio.run(workbench.stage(episode))
    assert first == second
    assert first["status"] == "staged"
    assert not workbench.ledger.commands(first["id"])
    assert len(workbench.ledger.snapshot()["trades"]) == 1
    assert not exchange.writes


@pytest.mark.parametrize("source", ["demo", "hyperliquid"])
def test_other_market_sources_cannot_authorize_testnet(workbench, source):
    workbench, exchange, episode, *_ = workbench
    episode = deepcopy(episode)
    episode["snapshot"]["source"] = source
    episode["approval_hash"] = digest(episode)
    result, setup = asyncio.run(workbench.preflight(episode))
    assert not result["eligible"] and setup is None
    assert "testnet data" in result["reason"]
    assert not exchange.writes


@pytest.mark.parametrize("change", ["tamper", "expired", "closed", "rejected"])
def test_no_staging_without_current_bound_review(workbench, change):
    workbench, exchange, episode, *_ = workbench
    episode = deepcopy(episode)
    if change == "tamper":
        episode["pitch"]["stop"] = "59999"
    elif change == "expired":
        episode["expires_at"] = (utcnow() - timedelta(seconds=1)).isoformat()
        episode["approval_hash"] = digest(episode)
    else:
        episode["status"] = change
    with pytest.raises(ValueError):
        asyncio.run(workbench.stage(episode))
    assert not workbench.ledger.snapshot()["trades"] and not exchange.writes


def test_paper_fill_does_not_consume_independent_testnet_review(workbench):
    workbench, exchange, episode, *_ = workbench
    episode = deepcopy(episode)
    episode["status"] = "filled"
    # Paper status is not execution authority. The bound review and fresh testnet checks are.
    assert asyncio.run(workbench.preflight(episode))[0]["eligible"]
    exchange.position = exchange.partial
    assert not asyncio.run(workbench.preflight(episode))[0]["eligible"]


def test_halt_and_unapproved_wallet_block_readiness(workbench):
    workbench, exchange, episode, *_ = workbench
    exchange.approved = False
    assert not asyncio.run(workbench.inspect())["ready_to_stage"]
    exchange.approved = True
    workbench.ledger.halt("Stop confirmation failed.")
    assert not asyncio.run(workbench.inspect())["ready_to_stage"]
    with pytest.raises(ValueError):
        asyncio.run(workbench.stage(episode))


def test_anonymous_inspection_reads_only_market_metadata(tmp_path):
    calls = []
    def respond(request):
        calls.append(request)
        assert request.url.host == "api.hyperliquid-testnet.xyz"
        return httpx.Response(200, json=[{"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}]},
                                        [{"midPx": None, "markPx": "60000", "funding": "0", "openInterest": "100"}]])
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            workbench = TestnetWorkbench(TestnetSettings(_env_file=None), client, "sqlite:///:memory:")
            result = await workbench.inspect()
            assert not result["ready_to_stage"] and result["account"] is None
            assert result["market"]["source"] == "hyperliquid-testnet"
            assert workbench.ledger is None
    asyncio.run(check())
    assert len(calls) == 1 and calls[0].url.path == "/info"


def test_api_staging_requires_operator_and_exposes_no_dispatch(workbench, monkeypatch):
    workbench, exchange, episode, config, paper_url = workbench
    # A signer secret in the environment must not turn HTTP inspection into execution.
    monkeypatch.setenv("HL_SIGNER_PRIVATE_KEY", "never-load-this-value")
    monkeypatch.setenv("HL_SIGNER_ENABLED", "true")
    app = create_app(Settings(_env_file=None, database_url=paper_url, market_source="hyperliquid-testnet", worker_enabled=False,
                             operator_token="operator-token-for-test-12345"), config)
    with TestClient(app) as client:
        app.state.testnet.gateway = exchange
        report = client.get("/api/v1/testnet/status").json()
        assert not report["private_key_loaded"] and not report["execution_enabled"]
        body = {"episode_id": episode["id"]}
        assert client.post("/api/v1/testnet/stage", json=body).status_code == 401
        assert client.post("/api/v1/testnet/dispatch", json=body).status_code == 404
        assert client.get("/api/v1/testnet/preflight/missing").status_code == 404
        assert client.get(f"/api/v1/testnet/preflight/{episode['id']}").json()["eligible"]
        assert client.post("/api/v1/testnet/stage", json=body,
            headers={"Authorization": "Bearer operator-token-for-test-12345"}).status_code == 201
        assert client.post("/api/v1/testnet/cancel", json=body).status_code == 401
        cancelled = client.post("/api/v1/testnet/cancel", json=body,
            headers={"Authorization": "Bearer operator-token-for-test-12345"})
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        assert not exchange.writes


def test_runner_lease_has_one_owner_and_can_be_reacquired(tmp_path):
    path = tmp_path / "runner.lock"
    with RunnerLease(path):
        with pytest.raises(ValueError, match="runner"):
            with RunnerLease(path):
                pytest.fail("A second runner acquired the lease")
    with RunnerLease(path):
        pass


def test_database_path_alias_cannot_mix_paper_and_testnet(tmp_path):
    first = f"sqlite:///{tmp_path / 'ledger.db'}"
    alias = f"sqlite:///{tmp_path}/./ledger.db"
    with pytest.raises(ValueError, match="separate"):
        require_separate_database(first, alias)


def test_cancel_unsent_intent_is_local_and_cannot_restage_it(workbench):
    workbench, exchange, episode, *_ = workbench
    first = asyncio.run(workbench.stage(episode))
    cancelled = workbench.ledger.cancel_staged(first["id"])
    assert cancelled["status"] == "cancelled"
    assert workbench.ledger.cancel_staged(first["id"]) == cancelled
    with pytest.raises(ValueError, match="terminal"):
        workbench.ledger.prepare_command(first["id"], "late-leverage", "leverage", {"leverage": 1})
    assert not asyncio.run(workbench.preflight(episode))[0]["eligible"]
    assert not exchange.writes


def test_local_cancel_cannot_hide_prepared_or_unknown_command(workbench):
    workbench, exchange, episode, *_ = workbench
    trade = asyncio.run(workbench.stage(episode))
    workbench.ledger.prepare_command(trade["id"], "entry", "entry", trade["entry"])
    with pytest.raises(ValueError, match="unsent"):
        workbench.ledger.cancel_staged(trade["id"])
