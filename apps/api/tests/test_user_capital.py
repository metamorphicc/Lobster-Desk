from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import func, select

from lobster.store import Store
from lobster.users.capital import Observation, Receipt, UserCapital, normalize_receipt
from lobster.users.contracts import UserTestnetSettings
from lobster.users.service import UserTestnetService
from lobster.users import capital

ADDRESS = "0x" + "a" * 40
BASE = datetime(2026, 10, 16, 23, 59, 50, tzinfo=timezone.utc)


@pytest.fixture
def clock(monkeypatch):
    value = [BASE]
    monkeypatch.setattr(capital, "utcnow", lambda: value[0])
    # Freshness helpers use their own clock; preserve the same deterministic window.
    monkeypatch.setattr("lobster.users.fees.utcnow", lambda: value[0])
    return value


def account(clock, equity="1000", address=ADDRESS):
    return {"address": address, "network": "testnet", "stale": False, "observed_at": clock[0].isoformat(),
        "exchange_time_ms": int(clock[0].timestamp() * 1000), "equity": equity, "positions": [], "open_orders": []}


@pytest.fixture
def ledger(tmp_path, clock):
    return UserCapital(Store(f"sqlite:///{tmp_path / 'capital.db'}"))


def seed(ledger, clock):
    a = account(clock)
    return ledger.observe(ADDRESS, a, a["exchange_time_ms"], [], complete=True)


def receipt(timestamp, value="100", kind="deposit", stream="ledger", **extra):
    return normalize_receipt(ADDRESS, stream, {"time": timestamp, "hash": "0x" + "1" * 64,
        "delta": {"type": kind, "usdc": value, **extra}}, timestamp, timestamp)


def test_deposits_are_not_profit_and_cannot_hide_loss_or_unlatch_halt(ledger, clock):
    first = seed(ledger, clock)
    clock[0] += timedelta(seconds=1)
    event = receipt(int(clock[0].timestamp() * 1000), "1000")
    result = ledger.observe(ADDRESS, account(clock, "1980"), first["cursor_ms"], [event], complete=True)
    assert result["cashflows"] == "1000"
    assert result["net_equity_change_excluding_cashflows"] == "-20"
    assert result["halt_reason"] and not result["entry_permission"]
    clock[0] += timedelta(seconds=1)
    recovered = ledger.observe(ADDRESS, account(clock, "2100"), result["cursor_ms"], [], complete=True)
    assert recovered["halt_reason"] == result["halt_reason"]


def test_funding_is_reported_once_without_adding_it_to_equity_twice(ledger, clock):
    initial = seed(ledger, clock)
    clock[0] += timedelta(seconds=1)
    event = receipt(int(clock[0].timestamp() * 1000), "-2", "funding", "funding", coin="BTC")
    result = ledger.observe(ADDRESS, account(clock, "998"), initial["cursor_ms"], [event, event], complete=True)
    assert result["funding_observed"] == "-2"
    assert result["performance_balance"] == "998" and result["receipt_count"] == 1
    assert result["net_equity_change_excluding_cashflows"] == "-2"
    with ledger.store.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 2
        assert session.scalar(select(func.count()).select_from(Receipt)) == 1
    restarted = UserCapital(Store(str(ledger.store.engine.url)))
    assert restarted.observe(ADDRESS, account(clock, "998"), initial["cursor_ms"], [event], complete=True)["receipt_count"] == 1


def test_withdrawals_and_day_rollover_preserve_old_loss_check(ledger, clock):
    initial = seed(ledger, clock)
    clock[0] += timedelta(seconds=11)
    event = receipt(int(clock[0].timestamp() * 1000), "500", "withdraw", fee="0")
    result = ledger.observe(ADDRESS, account(clock, "480"), initial["cursor_ms"], [event], complete=True)
    assert result["day"] == "2026-10-17"
    assert result["cashflows"] == "-500" and result["performance_balance"] == "980"
    assert result["halt_reason"]


def test_drawdown_and_account_isolation_are_durable(ledger, clock):
    initial = seed(ledger, clock)
    clock[0] += timedelta(seconds=1)
    high = ledger.observe(ADDRESS, account(clock, "1200"), initial["cursor_ms"], [], complete=True)
    clock[0] += timedelta(seconds=1)
    loss = ledger.observe(ADDRESS, account(clock, "1139"), high["cursor_ms"], [], complete=True)
    assert "drawdown" in loss["halt_reason"]
    other = "0x" + "b" * 40
    other_state = account(clock, address=other)
    clean = ledger.observe(other, other_state, other_state["exchange_time_ms"], [], complete=True)
    assert clean["halt_reason"] is None
    assert UserCapital(Store(str(ledger.store.engine.url))).get(ADDRESS)["halt_reason"]


def test_unknown_window_late_receipt_and_conflicting_equity_fail_without_partial_updates(ledger, clock):
    initial = seed(ledger, clock)
    clock[0] += timedelta(seconds=2)
    current = account(clock)
    with pytest.raises(ValueError, match="incomplete"):
        ledger.observe(ADDRESS, current, initial["cursor_ms"], [], complete=False)
    result = ledger.observe(ADDRESS, current, initial["cursor_ms"], [], complete=True)
    late = receipt(initial["cursor_ms"] + 1000)
    with pytest.raises(ValueError, match="Late"):
        ledger.observe(ADDRESS, current, initial["cursor_ms"], [late], complete=True)
    with pytest.raises(ValueError, match="Conflicting equity"):
        ledger.observe(ADDRESS, current | {"equity": "999"}, initial["cursor_ms"], [], complete=True)
    assert ledger.get(ADDRESS)["cursor_ms"] == result["cursor_ms"]
    assert ledger.get(ADDRESS)["receipt_count"] == 0
    clock[0] += timedelta(seconds=1)
    valid = receipt(int(clock[0].timestamp() * 1000))
    with pytest.raises(ValueError, match="Late"):
        ledger.observe(ADDRESS, account(clock), initial["cursor_ms"], [valid, late], complete=True)
    with ledger.store.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Receipt)) == 0


@pytest.mark.parametrize("delta", [{"type": "withdraw", "usdc": "10", "fee": "1"}, {"type": "mystery", "usdc": "10"},
    {"type": "deposit", "usdc": 0.1}, {"type": "deposit", "usdc": "NaN"}, {"type": "deposit", "usdc": "-1"}])
def test_ambiguous_or_inexact_receipts_are_not_guessed(delta):
    with pytest.raises((ValueError, ArithmeticError)):
        normalize_receipt(ADDRESS, "ledger", {"time": 1, "hash": "0x" + "1" * 64, "delta": delta}, 0, 2)


def test_decimal_json_and_inclusive_history_pagination_fail_closed_at_same_timestamp():
    import asyncio
    calls = []
    def respond(request):
        import json
        body = json.loads(request.content)
        calls.append(body)
        if body["type"] == "userFunding": return httpx.Response(200, json=[])
        return httpx.Response(200, content='[{"time":2,"hash":"0x' + '1'*64 + '","delta":{"type":"deposit","usdc":0.1}}]')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            service = UserTestnetService(UserTestnetSettings(_env_file=None), client)
            data = await service.capital_history(ADDRESS, 0, 3)
            assert data[0]["cashflow"] == "0.1"
            assert {call["type"] for call in calls} == {"userFunding", "userNonFundingLedgerUpdates"}
        repeated = [{"time": 1, "hash": "0x" + "1"*64, "delta": {"type": "deposit", "usdc": "1"}}] * 500
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=repeated))) as client:
            with pytest.raises(ValueError, match="coverage"):
                await UserTestnetService(UserTestnetSettings(_env_file=None), client).capital_history(ADDRESS, 0, 3)
    asyncio.run(run())


def test_capital_http_is_owner_bound_and_halts_on_unknown_history(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from eth_account import Account
    from eth_account.messages import encode_defunct
    from lobster.main import create_app
    from lobster.config import Settings
    from lobster.execution.settings import TestnetSettings
    from lobster.domain import utcnow
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}", worker_enabled=False), TestnetSettings(_env_file=None))
    # Public unfunded vector; never a production signing key.
    key = "0x" + "0" * 63 + "1"
    address = Account.from_key(key).address.lower()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        ch = client.post("/api/v1/users/testnet/auth/challenge", json={"address": address}).json()
        signature = "0x" + Account.sign_message(encode_defunct(text=ch["message"]), key).signature.hex()
        proof = client.post("/api/v1/users/testnet/auth/verify", json={"challenge_id": ch["challenge_id"], "signature": signature}).json()
        headers = {"Authorization": "Bearer " + proof["access_token"]}
        assert client.post("/api/v1/users/testnet/capital/refresh").status_code == 401
        async def inspect(owner):
            assert owner == address
            now = utcnow()
            return {"address": owner, "network": "testnet", "stale": False, "observed_at": now.isoformat(),
                "exchange_time_ms": int(now.timestamp() * 1000), "equity": "1000", "positions": [], "open_orders": []}
        monkeypatch.setattr(app.state.users, "inspect", inspect)
        first = client.post("/api/v1/users/testnet/capital/refresh", headers=headers)
        assert first.status_code == 200, first.text
        assert not first.json()["entry_permission"]
        async def unknown(*args): raise ValueError("Synthetic unsupported receipt")
        monkeypatch.setattr(app.state.users, "capital_history", unknown)
        second = client.post("/api/v1/users/testnet/capital/refresh", headers=headers)
        assert second.status_code == 409
        observed = client.get("/api/v1/users/testnet/capital", headers=headers).json()
        assert observed["reference"]["halt_reason"]
        assert address not in str(client.get("/api/v1/journal").json())
