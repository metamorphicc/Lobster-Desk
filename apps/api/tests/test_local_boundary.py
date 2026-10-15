import asyncio

from fastapi.testclient import TestClient
import httpx
from pydantic import ValidationError
import pytest
from starlette.responses import JSONResponse

from lobster.config import Settings
from lobster.main import create_app
from lobster.http_boundary import LocalBoundary


@pytest.fixture
def local_client(tmp_path):
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}", worker_enabled=False,
                             operator_token="test-only-operator-token-12345"))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


def test_foreign_host_is_rejected(local_client):
    assert local_client.get("/api/health", headers={"Host": "attacker.invalid"}).status_code == 400


def test_foreign_or_null_browser_origin_is_rejected(local_client):
    for origin in ["https://attacker.invalid", "null", "http://127.0.0.1:3000.attacker.invalid"]:
        assert local_client.get("/api/health", headers={"Origin": origin}).status_code == 403
    assert local_client.get("/api/health", headers={"Origin": "http://127.0.0.1:3000"}).status_code == 200


def test_oversized_body_is_refused_before_json_parsing(local_client):
    response = local_client.post("/api/v1/pitches", content=b"x" * 65537, headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert not local_client.get("/api/v1/state").json()["episodes"]


def test_api_data_has_no_store_and_nosniff(local_client):
    response = local_client.get("/api/v1/state")
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def test_settings_validation_does_not_echo_synthetic_credentials():
    marker = "synthetic-invalid-token"
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, operator_token=marker)
    assert marker not in str(error.value)
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, agent_provider="anthropic", anthropic_api_key=marker, anthropic_model=None)
    assert marker not in str(error.value)


def test_chunked_body_limit_is_checked_without_content_length():
    calls = []
    async def probe(scope, receive, send):
        message = await receive()
        calls.append(message["body"])
        await JSONResponse({"bytes": len(message["body"])})(scope, receive, send)
    async def chunks():
        yield b"12"
        yield b"345"
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=LocalBoundary(probe, max_body_bytes=4)), base_url="http://127.0.0.1") as client:
            assert (await client.post("/", content=chunks())).status_code == 413
            assert not calls
            response = await client.post("/", content=b"1234")
            assert response.status_code == 200 and response.json()["bytes"] == 4
            assert calls == [b"1234"]
    asyncio.run(run())


def test_slow_body_times_out_before_the_application():
    async def probe(scope, receive, send):
        pytest.fail("A partial slow body reached the application")
    async def chunks():
        yield b"12"
        await asyncio.sleep(1)
        yield b"34"
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=LocalBoundary(probe, body_timeout=0.01)), base_url="http://127.0.0.1") as client:
            assert (await client.post("/", content=chunks())).status_code == 408
    asyncio.run(run())


def test_normal_local_cors_post_and_preflight_still_work(local_client):
    origin = "http://127.0.0.1:3000"
    response = local_client.options("/api/v1/pitches", headers={"Origin": origin,
        "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type,Idempotency-Key"})
    assert response.status_code == 200 and response.headers["Access-Control-Allow-Origin"] == origin
    response = local_client.post("/api/v1/pitches", json={"author": "Boundary QA", "direction": "long",
        "entry": "60000", "stop": "59400", "target": "61800", "thesis": "A normal request still crosses the bounded local API."},
        headers={"Origin": origin, "Idempotency-Key": "boundary-request"})
    assert response.status_code == 201


def test_malformed_headers_and_unicode_bearer_fail_closed(local_client):
    assert local_client.post("/api/v1/pitches", headers={"Content-Length": "9" * 5000}, content=b"").status_code == 400
    assert local_client.post("/api/v1/pitches", headers=[("Content-Length", "1"), ("Content-Length", "1")], content=b"x").status_code == 400
    assert local_client.post("/api/v1/operator", json={"action": "pause"}, headers=[(b"authorization", b"Bearer \xff")]).status_code == 401
    assert local_client.get("/api/health", headers=[("Origin", "http://127.0.0.1:3000"), ("Origin", "https://attacker.invalid")]).status_code == 403
