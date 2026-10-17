import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
import hmac
import json
import sqlite3

import httpx
from pydantic import SecretStr
import pytest

from lobster.domain import utcnow
from lobster.ops.alerts import AlertSettings, AlertOutbox, financial_observations
from lobster.ops.heartbeat import ping
from test_project_runner import project

ALERT = {"code": "exchange_command_uncertain", "severity": "critical", "scope": "project", "count": 1}


def settings(path):
    return AlertSettings(_env_file=None, alerts_enabled=True, alert_webhook=SecretStr("https://ops.example.test/receiver"),
        alert_webhook_secret=SecretStr("public-fixture-hmac-"+"1"*32), state_path=path)


def test_unchanged_observations_deduplicate_across_restart_and_concurrent_monitors(tmp_path):
    path = tmp_path/"ops.db"
    outbox = AlertOutbox(path)
    assert outbox.observe([]) is None and not outbox.rows()
    with ThreadPoolExecutor(4) as pool:
        events = list(pool.map(lambda _: AlertOutbox(path).observe([ALERT]), range(12)))
    assert sum(row is not None for row in events) == 1 and len(outbox.rows()) == 1
    assert AlertOutbox(path).observe([ALERT]) is None


def test_delivery_is_explicit_hmac_authenticated_and_excludes_private_fields(tmp_path):
    path = tmp_path/"ops.db"; outbox = AlertOutbox(path); config = settings(path)
    event = outbox.observe([ALERT | {"private_key": "never-send-this", "account": "0x"+"a"*40, "message": "private thesis"}])
    requests = []
    def respond(request):
        assert str(request.url) == "https://ops.example.test/receiver"
        stamp = request.headers["X-Lobster-Timestamp"]
        expected = hmac.new(config.alert_webhook_secret.get_secret_value().encode(), stamp.encode()+b"."+request.content, sha256).hexdigest()
        assert request.headers["X-Lobster-Signature"] == expected and request.headers["Idempotency-Key"] == event["id"]
        assert b"never-send-this" not in request.content and b"private thesis" not in request.content and b"0xaaaa" not in request.content
        requests.append(request); return httpx.Response(200, json={"ok": True})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(ValueError): await outbox.deliver(config, client)
            assert not requests
            assert (await outbox.deliver(config, client, armed=True))["status"] == "delivered"
            assert await outbox.deliver(config, client, armed=True) is None
    asyncio.run(run())
    assert len(requests) == 1 and outbox.rows()[0]["status"] == "delivered"


def test_timeout_retry_keeps_event_identity_backoff_and_bounded_attempts(tmp_path, monkeypatch):
    import lobster.ops.alerts as module
    path = tmp_path/"ops.db"; outbox = AlertOutbox(path); config = settings(path)
    event = outbox.observe([ALERT]); clock = [utcnow()]
    monkeypatch.setattr(module,"utcnow",lambda:clock[0])
    sent = []
    def respond(request):
        sent.append(request.headers["Idempotency-Key"]); raise httpx.ReadTimeout("public fixture")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            for attempt in range(5):
                result = await AlertOutbox(path).deliver(config, client, armed=True)
                assert result["event_id"] == event["id"] and result["attempts"] == attempt+1
                assert await outbox.deliver(config, client, armed=True) is None
                clock[0] += timedelta(minutes=16)
            assert outbox.rows()[0]["status"] == "failed"
    asyncio.run(run()); assert sent == [event["id"]]*5


def test_recovery_event_and_superseded_unattempted_history_are_distinct(tmp_path):
    outbox = AlertOutbox(tmp_path/"ops.db")
    incident = outbox.observe([ALERT])
    recovery = outbox.observe([])
    assert incident["id"] != recovery["id"] and recovery["kind"] == "recovery"
    assert outbox.rows()[0]["status"] == "superseded"
    assert outbox.observe([]) is None
    with pytest.raises(ValueError): outbox.observe([ALERT | {"code": "private_api_key_leak"}])


def test_financial_observations_find_uncertainty_and_stale_runner_without_leaking_paths(project, tmp_path, monkeypatch):
    import lobster.ops.alerts as module
    runner, gateway, setup, _ = project
    gateway.failures["entry"] = "before"
    asyncio.run(runner.tick())
    path = runner.ledger.engine.url.database
    assert ping(path,"project",state="needs_reconciliation")
    report = financial_observations(runner.store.engine.url.database, tmp_path/"absent-treasury")
    assert any(a["code"] == "exchange_command_uncertain" for a in report)
    assert not any(a["code"] == "financial_runner_unavailable" for a in report)
    monkeypatch.setattr(module,"utcnow",lambda:utcnow()+timedelta(seconds=31))
    report = financial_observations(runner.store.engine.url.database, tmp_path/"absent-treasury")
    assert any(a["code"] == "financial_runner_unavailable" for a in report)
    assert str(path) not in json.dumps(report) and runner.settings.account not in json.dumps(report)


@pytest.mark.parametrize("url", ["http://ops.example.test", "https://user:password@ops.example.test", "https://localhost/receiver", "https://ops.example.test:444/receiver"])
def test_bad_notification_destination_is_refused(url):
    with pytest.raises(ValueError): AlertSettings(_env_file=None, alert_webhook=SecretStr(url))


def test_monitor_rejects_wrong_instance_or_stale_api_and_redacts_all_freeform_text(tmp_path):
    import runpy
    from lobster.store import Store
    from lobster.execution.contracts import fingerprint
    observe = runpy.run_path("scripts/ops-runner.py")["observe"]
    path = tmp_path/"app.db"
    store = Store("sqlite:///"+path.as_posix()); store.engine.dispose()
    config = AlertSettings(_env_file=None, application_path=path, treasury_path=tmp_path/"absent.db")
    payload = {"schema": "lobster-local-readiness-v1", "observed_at": utcnow().isoformat(),
        "instance_fingerprint": fingerprint({"database":str(path.resolve())}), "alerts": [
            {"code":"market_unavailable","scope":"paper","severity":"warning","message":"private thesis must not leave this process"}]}
    async def run():
        def respond(request):
            assert str(request.url)=="http://127.0.0.1:8000/api/ready"
            return httpx.Response(200,json=payload)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result=await observe(config,client)
            assert result==[{"code":"market_unavailable","scope":"paper","severity":"warning","count":1}]
            assert "private thesis" not in json.dumps(result)
            payload["instance_fingerprint"]="wrong"
            assert (await observe(config,client))[0]["code"]=="monitor_scope_mismatch"
            payload["observed_at"]=(utcnow()-timedelta(minutes=4)).isoformat()
            assert (await observe(config,client))[0]["code"]=="api_runtime_unavailable"
    asyncio.run(run())


def test_heartbeat_failure_cannot_create_a_phantom_financial_database(tmp_path):
    path=tmp_path/"missing.db"
    assert not ping(path,"project") and not path.exists()
