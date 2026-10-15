import asyncio
import json

from fastapi.testclient import TestClient
import httpx
from pydantic import TypeAdapter, ValidationError
import pytest

from lobster.config import Settings
from lobster.main import create_app
from lobster.users.contracts import Address, UserTestnetSettings, fee_percent
from lobster.users.service import UserTestnetService

OWNER = "0x" + "a" * 40
OTHER = "0x" + "b" * 40
BUILDER = "0x" + "c" * 40


def transport(calls, approval=20, bad_rate=False):
    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.host == "api.hyperliquid-testnet.xyz" and request.url.path == "/info"
        assert body["user"] in {OWNER, OTHER}
        kind = body["type"]
        if kind == "clearinghouseState":
            return httpx.Response(200, json={"marginSummary": {"accountValue": "123.456789" if body["user"] == OWNER else "456"},
                "withdrawable": "100", "assetPositions": [{"position": {"coin": "BTC", "szi": "0.0003",
                "entryPx": "60000", "unrealizedPnl": "0.123456789"}}]})
        if kind == "frontendOpenOrders":
            return httpx.Response(200, json=[{"coin": "BTC", "oid": 123, "side": "A", "sz": "0.0003",
                "limitPx": "59000", "reduceOnly": True, "isTrigger": True}])
        if kind == "userFees":
            return httpx.Response(200, json={"userCrossRate": "NaN" if bad_rate else "0.00045"})
        assert kind == "maxBuilderFee" and body["builder"] == BUILDER
        return httpx.Response(200, content=json.dumps(approval), headers={"Content-Type": "application/json"})
    return httpx.MockTransport(respond)


@pytest.mark.parametrize("approval,status", [(0, "not_approved"), (10, "below_requested"), (20, "approved"), (100, "approved")])
def test_user_account_is_public_read_only_and_fees_keep_units(approval, status):
    calls = []
    async def run():
        async with httpx.AsyncClient(transport=transport(calls, approval)) as client:
            service = UserTestnetService(UserTestnetSettings(_env_file=None, builder_address=BUILDER), client)
            report = await service.inspect(OWNER)
            assert report["equity"] == "123.456789"
            assert report["positions"][0]["unrealized_pnl"] == "0.123456789"
            assert report["builder_fee_percent"] == "0.02%"
            assert report["approved_builder_fee_tenths_bps"] == approval
            assert report["builder_approval_status"] == status
            assert report["open_orders"][0]["reduce_only"]
            assert not report["authenticated"] and not report["order_submission_enabled"] and not report["fee_collection_enabled"]
    asyncio.run(run())
    assert len(calls) == 4


def test_different_users_have_no_shared_balance_or_owner_authority():
    async def run():
        async with httpx.AsyncClient(transport=transport([])) as client:
            service = UserTestnetService(UserTestnetSettings(_env_file=None), client)
            first, second = await asyncio.gather(service.inspect(OWNER), service.inspect(OTHER))
            assert first["address"] == OWNER and second["address"] == OTHER
            assert first["equity"] != second["equity"]
            assert first["builder_approval_status"] == "not_configured"
    asyncio.run(run())


@pytest.mark.parametrize("bad", [True, -1, "20", 20.5, None])
def test_malformed_approval_never_becomes_permission(bad):
    async def run():
        async with httpx.AsyncClient(transport=transport([], bad)) as client:
            service = UserTestnetService(UserTestnetSettings(_env_file=None, builder_address=BUILDER), client)
            with pytest.raises(ValueError, match="approval"):
                await service.inspect(OWNER)
    asyncio.run(run())


def test_address_validation_and_builder_bounds(monkeypatch):
    assert TypeAdapter(Address).validate_python("0x" + "A" * 40) == OWNER
    for value in ["http://localhost", "0x" + "0" * 40, "0x123"]:
        with pytest.raises(ValidationError):
            TypeAdapter(Address).validate_python(value)
    with pytest.raises(ValidationError):
        UserTestnetSettings(_env_file=None, builder_fee_tenths_bps=101)
    monkeypatch.setenv("USER_TESTNET_BUILDER_FEE_TENTHS_BPS", "20")
    assert UserTestnetSettings(_env_file=None).builder_fee_tenths_bps == 20
    assert [fee_percent(i) for i in (0, 1, 10, 20, 100)] == ["0%", "0.001%", "0.01%", "0.02%", "0.1%"]


def test_account_api_validates_addresses_and_does_not_enable_execution(tmp_path):
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}", worker_enabled=False),
                     user_settings=UserTestnetSettings(_env_file=None, builder_address=BUILDER))
    async def run():
        async with httpx.AsyncClient(transport=transport([])) as exchange_client:
            with TestClient(app) as client:
                app.state.users.client = exchange_client
                base = "/api/v1/users/testnet"
                assert not client.get(base + "/config").json()["fee_collection_enabled"]
                assert client.get(base + "/accounts/0x123").status_code == 422
                assert client.get(base + "/accounts/" + OWNER).json()["address"] == OWNER
                assert client.post(base + "/orders", json={"address": OWNER}).status_code == 404
                assert app.state.runtime.store.state(None)["account"]["cash"] == "1000"
    asyncio.run(run())


def test_upstream_error_is_static_and_not_zero_balance(tmp_path):
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}", worker_enabled=False))
    async def run():
        async with httpx.AsyncClient(transport=transport([], bad_rate=True)) as exchange_client:
            with TestClient(app) as client:
                app.state.users.client = exchange_client
                response = client.get("/api/v1/users/testnet/accounts/" + OWNER)
                assert response.status_code == 502
                assert "equity" not in response.json()
    asyncio.run(run())
