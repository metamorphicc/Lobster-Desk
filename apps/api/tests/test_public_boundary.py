import asyncio

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
import httpx
import pytest
from starlette.responses import JSONResponse

from lobster.config import Settings
from lobster.http_boundary import LocalBoundary
from lobster.main import create_app
from test_user_orders import KEY, ADDRESS

ORIGIN = "https://desk.example.test"
PROXY = "public-fixture-proxy-" + "1"*32
OPERATOR = "public-fixture-operator-" + "2"*32
HEADERS = {"X-Lobster-Proxy-Token": PROXY, "X-Lobster-Client-IP": "203.0.113.20", "Origin": ORIGIN}


def config(tmp_path, **changes):
    values = {"deployment_mode": "public-single-host", "database_url": f"sqlite:///{tmp_path/'public.db'}", "web_origin": ORIGIN,
        "proxy_token": PROXY, "operator_token": OPERATOR}
    return Settings(_env_file=None, **(values | changes))


@pytest.mark.parametrize("change", [{"web_origin": "http://desk.example.test"}, {"proxy_token": None}, {"operator_token": None},
    {"operator_token": PROXY}, {"web_origin": "https://desk.example.test/"}, {"web_origin": "https://user:password@desk.example.test"},
    {"web_origin": "https://127.0.0.1"}, {"worker_enabled": False}, {"database_url": "sqlite:///:memory:"}])
def test_public_configuration_cannot_silently_weaken_boundary(tmp_path, change):
    with pytest.raises(ValueError): config(tmp_path, **change)


def test_public_proxy_origin_identity_and_exact_signin_message(tmp_path):
    app = create_app(config(tmp_path))
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/health").status_code == 403
        assert client.get("/api/health", headers=HEADERS | {"X-Lobster-Proxy-Token": "wrong"}).status_code == 403
        assert client.get("/api/health", headers=HEADERS | {"Origin": "https://attacker.invalid"}).status_code == 403
        assert client.get("/api/health", headers=HEADERS | {"Host": "attacker.invalid"}).status_code == 400
        assert client.get("/api/health", headers=HEADERS | {"X-Lobster-Client-IP": "attacker"}).status_code == 400
        assert client.get("/api/health", headers=HEADERS).status_code == 200
        response = client.post("/api/v1/users/testnet/auth/challenge", json={"address": ADDRESS}, headers=HEADERS)
        assert response.status_code == 200
        challenge = response.json()
        assert challenge["origin"] == ORIGIN and f"URI: {ORIGIN}" in challenge["message"]
        assert "http://127.0.0.1" not in challenge["message"]
        signature = "0x" + Account.sign_message(encode_defunct(text=challenge["message"]), KEY).signature.hex()
        result = client.post("/api/v1/users/testnet/auth/verify", headers=HEADERS,
            json={"challenge_id": challenge["challenge_id"], "signature": signature})
        assert result.status_code == 200 and not result.json()["order_submission_enabled"]
        assert PROXY not in result.text and OPERATOR not in result.text


def test_trusted_proxy_peer_wins_over_forged_forwarded_headers_and_limits_connections():
    peers = []
    release = asyncio.Event()
    async def app(scope, receive, send):
        peers.append(scope["client"][0]); await release.wait()
        await JSONResponse({"ok": True})(scope, receive, send)
    async def run():
        boundary = LocalBoundary(app, allowed_origins={ORIGIN}, proxy_token=PROXY)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=boundary), base_url=ORIGIN) as client:
            tasks = [asyncio.create_task(client.get("/", headers=HEADERS | {"X-Forwarded-For": "8.8.8.8"})) for _ in range(8)]
            for _ in range(100):
                if len(peers) == 8: break
                await asyncio.sleep(0)
            assert peers == ["203.0.113.20"]*8
            result = await client.get("/", headers=HEADERS)
            assert result.status_code == 429
            release.set(); assert all(r.status_code == 200 for r in await asyncio.gather(*tasks))
            assert boundary.active == {}
    asyncio.run(run())
