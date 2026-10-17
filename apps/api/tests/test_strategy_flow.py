"""Verified author -> project fills -> realized allocation -> observed payment. Offline only."""
import asyncio
from copy import deepcopy
from decimal import Decimal as D
from types import SimpleNamespace

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from lobster.agents import DemoReviewer
from lobster.config import Settings
from lobster.domain import PitchInput, utcnow
from lobster.economics.book import TreasuryBook
from lobster.economics.distribution import distribution
from lobster.economics.ingestion import sync_project_settlement
from lobster.execution.project import ProjectRunner, ProjectSettings, ProjectLedger
from lobster.execution.signer import MainnetSigner
from lobster.main import create_app
from lobster.pipeline import Pipeline
from lobster.store import Store
from lobster.users.strategies import UserStrategies
from lobster.users.strategy_http import PayoutReceipt, record_payout
from test_user_mainnet import MemoryMainnet
from test_user_orders import ADDRESS, KEY


def pitch():
    return PitchInput(author="Strategy QA", direction="long", entry="60000", stop="59400", target="61800",
        thesis="A synthetic author-attributed setup for financial invariant tests.")


def signin(client, network="mainnet"):
    challenge = client.post(f"/api/v1/users/{network}/auth/challenge", json={"address": ADDRESS}).json()
    signature = "0x"+Account.sign_message(encode_defunct(text=challenge["message"]), KEY).signature.hex().removeprefix("0x")
    result = client.post(f"/api/v1/users/{network}/auth/verify", json={"challenge_id": challenge["challenge_id"], "signature": signature}).json()
    return {"Authorization": "Bearer "+result["access_token"], "Idempotency-Key": "strategy-http-01"}


def test_strategy_http_never_trusts_display_name_or_claims_anonymous_history(tmp_path):
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path/'app.db'}", treasury_path=str(tmp_path/'book.db'), worker_enabled=False))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        path = "/api/v1/users/mainnet/strategy-pitches"
        assert client.post(path, json=pitch().model_dump(mode="json"), headers={"Idempotency-Key": "anonymous-01"}).status_code == 401
        headers = signin(client)
        result = client.post(path, json=pitch().model_dump(mode="json"), headers=headers)
        assert result.status_code == 201
        ep = result.json()
        assert ADDRESS not in str(ep) and "strategy_attribution" in ep
        assert client.post(path, json=pitch().model_dump(mode="json"), headers=headers).json()["id"] == ep["id"]
        assert client.post(path, json=pitch().model_dump(mode="json") | {"owner": "0x"+"9"*40}, headers=headers).status_code == 422
        assert client.post(path, json=pitch().model_dump(mode="json") | {"target": "62000"}, headers=headers).status_code == 409
        private = client.get("/api/v1/users/mainnet/strategy-earnings", headers=headers).json()
        assert len(private["strategies"]) == 1 and private["balance"] is None and not private["payout_submission_enabled"]
        assert client.get("/api/v1/users/testnet/strategy-earnings", headers=headers).status_code == 401
        assert "charity" not in client.get("/api/v1/economics").json()


@pytest.mark.parametrize("funding", ["0", "-0.100000", "0.040000"])
def test_realized_project_strategy_profit_and_verified_payout_recover_without_duplicate_credit(tmp_path, funding):
    store = Store(f"sqlite:///{tmp_path/'app.db'}")
    gateway = MemoryMainnet()
    key = SecretStr("0x"+"0"*63+"4")  # Public unfunded fixture. NEVER fund.
    signer = MainnetSigner(key, gateway.account_address, gateway.rules)
    settings = ProjectSettings(_env_file=None, network="mainnet", enabled=True, account=gateway.account_address,
        agent=signer.address, private_key=key, capital_budget="1000", absolute_loss_budget="20", reserve_floor="100", treasury_path=tmp_path/"book.db")
    ledger = ProjectLedger(f"sqlite:///{tmp_path/'execution.db'}", settings.account, settings.agent, network="mainnet")
    strategies = UserStrategies(store, "mainnet")
    ep = strategies.submit(ADDRESS, pitch(), "strategy-test-01")
    with pytest.raises(ValueError): strategies.resolve(ep["strategy_attribution"] | {"owner_commitment": "a"*64}, ep["id"])
    class Service:
        network = "mainnet"
        equity = "1000"
        receipts = []
        async def inspect(self, owner):
            return {"address": owner, "network": "mainnet", "stale": False, "observed_at": utcnow().isoformat(), "exchange_time_ms": int(utcnow().timestamp()*1000),
                "equity": self.equity, "withdrawable": "900", "positions": [{"quantity": str(gateway.position)}] if gateway.position else [],
                "open_orders": await gateway.open_orders(), "reported_taker_rate": "0.00045"}
        async def capital_history(self, owner, start, end): return [r for r in self.receipts if start <= r["time"] <= end]
    service = Service()
    async def info(kind, **fields): return "disabled"
    gateway.info = info
    runner = ProjectRunner(store, settings, ledger, gateway, signer, service, armed=True)
    book = TreasuryBook(tmp_path/"book.db")
    async def run():
        pipeline = Pipeline(store, DemoReviewer())
        for _ in range(4): await pipeline.step((await gateway.market())[1])
        trade = await runner.tick()
        assert trade["status"] == "protected" and trade["audit_binding"]["strategy_owner"] == ADDRESS
        gateway.price = D("61800")
        await runner.broker.close_owned(trade["id"])
        await runner.broker.reconcile(trade["id"])
        assert ledger.trade(trade["id"])["status"] == "closed"
        expected = D("0.52") + D(funding)
        author_share = expected/2
        service.equity = str(1000 + expected)
        if D(funding):
            from lobster.users.capital import normalize_receipt
            stamp = ledger.snapshot()["fills"][0]["time"]
            service.receipts = [normalize_receipt(settings.account, "funding", {"time": stamp, "hash": "0x"+"b"*64,
                "delta": {"type": "funding", "coin": "BTC", "usdc": funding}}, 0, int(utcnow().timestamp()*1000))]
        first = await sync_project_settlement(book, runner)
        assert D(first["new_settlement"]) == expected
        report = distribution(book)
        assert D(report["user_strategy_profit"]["author_entitlement"]) == author_share
        assert D(report["user_strategy_profit"]["bot_retained"]) == author_share
        assert D(report["lifetime_buyback_entitlement"]) == 0
        observed_account = (await gateway.account()).model_copy(update={"equity": D(service.equity)})
        await runner.entry_guard(observed_account)
        protected_capital = ledger.observe_capital(observed_account, store.policy)
        assert protected_capital.available_cash == D("800")-author_share
        assert protected_capital.equity == D(service.equity)-author_share
        assert D((await sync_project_settlement(TreasuryBook(book.path), runner))["new_settlement"]) == 0
        assert distribution(book)["record_count"] == 1
        from lobster.ops.catalog import register_journal
        journal = register_journal(store, ledger, "project")
        body = PayoutReceipt(journal_id=journal["id"], owner=ADDRESS, transfer_hash="0x"+"a"*64, timestamp_ms=1000, amount=str(author_share))
        class Payments:
            network = "mainnet"
            async def capital_history(self, owner, start, end):
                return [{"address": owner, "stream": "ledger", "time": 1000, "hash": body.transfer_hash, "kind": "internalTransfer",
                    "cashflow": str(author_share if owner == ADDRESS else -author_share), "funding": "0", "details_hash": "b"*64}]
        observed = await record_payout(store, book, Payments(), body)
        assert (await record_payout(store, book, Payments(), body))["record_hash"] == observed["record_hash"]
        assert distribution(book)["user_strategy_profit"]["author_outstanding"] == "0"
        assert D(distribution(book)["recorded_cash"]) == author_share
        with pytest.raises(ValueError): await record_payout(store, book, Payments(), body.model_copy(update={"owner": "0x"+"9"*40}))
    try: asyncio.run(run())
    finally: ledger.engine.dispose(); store.engine.dispose()
