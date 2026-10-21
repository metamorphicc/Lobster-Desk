"""Public unfunded key vectors, temporary books and HTTP fixtures. No live payments."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal as D
import json

from eth_account import Account
from eth_account.messages import encode_typed_data
from hyperliquid.utils.signing import USD_SEND_SIGN_TYPES, user_signed_payload
import httpx
from pydantic import SecretStr
import pytest

from lobster.domain import utcnow
from lobster.economics.author_payouts import AuthorPayouts, AuthorPayoutSettings
from lobster.economics.book import TreasuryBook
from lobster.economics.distribution import distribution
from lobster.execution.ledger import ExecutionLedger
from lobster.ops.catalog import register_journal
from lobster.store import Store
from lobster.users.strategy_http import record_payout, PayoutReceipt
from test_strategy_sharing import receipt, allocation, OWNER


@pytest.fixture
def context(tmp_path, monkeypatch):
    import lobster.economics.author_payouts as module
    clock = [int(utcnow().timestamp()*1000)-3000]
    monkeypatch.setattr(module, "utcnow", lambda: datetime.fromtimestamp(clock[0]/1000, timezone.utc))
    key = SecretStr("0x"+"0"*63+"4")
    source = Account.from_key(key.get_secret_value()).address.lower()
    store = Store(f"sqlite:///{tmp_path/'app.db'}")
    ledger = ExecutionLedger(f"sqlite:///{tmp_path/'project.db'}", source, "0x"+"8"*40, network="mainnet")
    register_journal(store, ledger, "project")
    book = TreasuryBook(tmp_path/"book.db")
    book.append(receipt(1, "trading_profit", "100", strategy_allocations=[allocation()],
        occurred_at=datetime.fromtimestamp((clock[0]-1000)/1000, timezone.utc), provenance="owner_supplied_unverified"))
    settings = AuthorPayoutSettings(_env_file=None, enabled=True, account=source, private_key=key, book=book.path,
        operating_reserve="0", liability_reserve="0", tax_reserve="0")
    state = {"mode": "ok", "occupied": False, "rows": [], "writes": []}
    def response(request):
        body = json.loads(request.content)
        clock[0] += 10
        if str(request.url) == "https://api.hyperliquid.xyz/exchange":
            assert body["action"]["type"] == "usdSend" and body["action"]["hyperliquidChain"] == "Mainnet"
            typed = user_signed_payload("HyperliquidTransaction:UsdSend", USD_SEND_SIGN_TYPES, body["action"])
            vrs = (body["signature"]["v"], int(body["signature"]["r"],16), int(body["signature"]["s"],16))
            assert Account.recover_message(encode_typed_data(full_message=typed), vrs=vrs).lower() == source
            state["writes"].append(body)
            if state["mode"] == "reject": return httpx.Response(200, json={"status": "err"})
            state["rows"].append({"time": clock[0]-1, "hash": "0x"+"a"*64, "delta": {"type": "internalTransfer", "user": source,
                "destination": body["action"]["destination"], "usdc": body["action"]["amount"], "fee": "0"}})
            if state["mode"] == "timeout": raise httpx.ReadTimeout("Synthetic uncertain transfer after acceptance")
            return httpx.Response(200, json={"status": "ok", "response": {"type": "default"}})
        assert str(request.url) == "https://api.hyperliquid.xyz/info"
        kind = body["type"]
        if kind == "userAbstraction": value = "disabled"
        elif kind == "clearinghouseState": value = {"time": clock[0], "assetPositions": [{"position": {"coin":"BTC","szi":"1","entryPx":"60000","unrealizedPnl":"0"}}] if state["occupied"] else [],
            "marginSummary": {"accountValue": "1000"}, "withdrawable": "1000"}
        elif kind == "frontendOpenOrders": value = []
        elif kind == "userFees": value = {"userCrossRate": "0.00045"}
        elif kind == "userFunding": value = []
        elif kind == "userNonFundingLedgerUpdates": value = [r for r in state["rows"] if body["startTime"] <= r["time"] <= body["endTime"]]
        else: raise ValueError("Unexpected fixture request")
        return httpx.Response(200, json=value)
    try: yield store, book, settings, clock, state, response
    finally: ledger.engine.dispose(); store.engine.dispose()


def test_automatic_payout_is_bounded_signed_exactly_once_and_records_both_observed_sides(context):
    store, book, settings, _, state, response = context
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            payments = AuthorPayouts(store, book, settings, client, armed=True)
            job = await payments.prepare()
            assert job["plan"]["action"]["destination"] == OWNER and D(job["plan"]["action"]["amount"]) == 25
            result = await payments.dispatch(job["id"])
            assert result["status"] == "recorded"
            recovered = AuthorPayouts(store, TreasuryBook(book.path), settings, client, armed=True)
            assert (await recovered.dispatch(job["id"]))["status"] == "recorded" and len(state["writes"]) == 1
            assert D(distribution(book)["user_strategy_profit"]["author_paid"]) == 25
            assert D(distribution(book)["user_strategy_profit"]["author_outstanding"]) == 25
            assert settings.private_key.get_secret_value() not in json.dumps(payments.jobs())
    asyncio.run(run())


def test_author_payout_cannot_consume_donation_earmarks(context):
    store, book, settings, _, _, response = context
    book.append(receipt(2, "trading_profit", "100", provenance="owner_supplied_unverified"))
    book.append(receipt(3, "capital_out", "140", provenance="owner_supplied_unverified"))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            payments = AuthorPayouts(store, book, settings, client, armed=True)
            with book.transaction() as db:
                assert payments.limits(book.read(db), OWNER) == D("10")
            assert D(distribution(book)["donations"]["outstanding"]) == 50
    asyncio.run(run())


def test_unknown_transfer_remains_reserved_even_when_matching_history_exists(context):
    store, book, settings, _, state, response = context
    state["mode"] = "timeout"
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            payments = AuthorPayouts(store, book, settings, client, armed=True)
            job = await payments.prepare()
            assert (await payments.dispatch(job["id"]))["status"] == "unknown"
            recovered = AuthorPayouts(store, book, settings, client, armed=True)
            assert (await recovered.dispatch(job["id"]))["status"] == "unknown" and len(state["writes"]) == 1
            with pytest.raises(ValueError): await recovered.prepare()
            r = state["rows"][0]
            with pytest.raises(ValueError, match="unresolved"):
                await record_payout(store, book, payments.service, PayoutReceipt(journal_id=payments.journal["id"], owner=OWNER,
                    transfer_hash=r["hash"], timestamp_ms=r["time"], amount="25"))
            assert D(distribution(book)["user_strategy_profit"]["author_paid"]) == 0
    asyncio.run(run())


@pytest.mark.parametrize("change", ["expired", "occupied", "reduced_profit", "reserves"])
def test_changed_permission_capital_or_expiry_cannot_send(context, change):
    store, book, settings, clock, state, response = context
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            payments = AuthorPayouts(store, book, settings, client, armed=True)
            job = await payments.prepare()
            if change == "expired": clock[0] += 31000
            if change == "occupied": state["occupied"] = True
            if change == "reduced_profit": book.append(receipt(2, "trading_loss", "90", strategy_allocations=[allocation(2,"-90")], provenance="owner_supplied_unverified"))
            if change == "reserves": settings.operating_reserve = D("1000")
            if change == "expired": assert (await payments.dispatch(job["id"]))["status"] == "cancelled"
            else:
                with pytest.raises(ValueError): await payments.dispatch(job["id"])
            assert not state["writes"]
    asyncio.run(run())


def test_unarmed_or_wrong_source_key_is_refused_without_network(context):
    store, book, settings, _, _, response = context
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            with pytest.raises(ValueError, match="armed"): AuthorPayouts(store, book, settings, client)
            settings.private_key = SecretStr("0x"+"0"*63+"5")
            with pytest.raises(ValueError, match="key"): AuthorPayouts(store, book, settings, client, armed=True)
    asyncio.run(run())
