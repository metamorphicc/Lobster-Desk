"""Execution fixtures use an in-memory exchange and a public, unfunded test key."""

import asyncio
from decimal import Decimal as D

import httpx
from pydantic import SecretStr
import pytest

from lobster.agents import DemoReviewer
from lobster.domain import PitchInput, Snapshot, utcnow
from lobster.execution.broker import TestnetBroker
from lobster.execution.contracts import BtcRules, ExchangeAccount, ReviewedSetup
from lobster.execution.ledger import ExecutionLedger
from lobster.execution.signer import TestnetSigner
from lobster.pipeline import Pipeline
from lobster.store import Store

FIXTURE_KEY = SecretStr("0x" + "0" * 63 + "1")  # Public test vector. NEVER fund.
FIXTURE_ADDRESS = "0x" + "2" * 40


class FakeTestnet:
    def __init__(self):
        self.account_address = FIXTURE_ADDRESS
        self.rules = BtcRules(asset_id=3, size_decimals=5, max_leverage=40)
        self.price = D("60000")
        self.position = D("0")
        self.partial = D("0.00030")
        self.approved = True
        self.orders = {}
        self.writes = []
        self.observed_fills = []
        self.leverage = 1
        self.failures = {}
        self.oid = 100
        self.stale = False

    async def market(self):
        return self.rules, Snapshot(source="hyperliquid-testnet", price=self.price, timestamp=utcnow())

    async def account(self):
        from datetime import timedelta
        return ExchangeAccount(address=self.account_address, equity="1000", withdrawable="900",
            observed_at=utcnow() - timedelta(seconds=60 if self.stale else 0), btc_size=self.position,
            btc_leverage=self.leverage, btc_is_cross=False, open_order_count=len(await self.open_orders()))

    async def agent_approved(self, address):
        return self.approved

    async def open_orders(self):
        return [record["order"] for record in self.orders.values() if record["status"] == "open"]

    async def order_status(self, key):
        return {"status": "order", "order": self.orders[key]} if key in self.orders else {"status": "unknownOid"}

    async def fills(self):
        return self.observed_fills

    def fill(self, item, quantity, price):
        side = item["side"]
        self.position += quantity if side == "B" else -quantity
        pnl = (price - D("60000")) * quantity if side == "A" else D("0")
        self.observed_fills.append({"coin": "BTC", "oid": item["oid"], "tid": len(self.observed_fills) + 1,
            "px": str(price), "sz": str(quantity), "fee": "0.01", "feeToken": "USDC", "closedPnl": str(pnl),
            "time": int(utcnow().timestamp() * 1000), "side": side})

    async def send(self, envelope):
        action = envelope["action"]
        kind = "leverage" if action["type"] == "updateLeverage" else "cancel" if action["type"] == "cancelByCloid" else (
            "entry" if not action["orders"][0]["r"] else
            "stop" if action["orders"][0]["t"].get("trigger", {}).get("tpsl") == "sl" else
            "target" if "trigger" in action["orders"][0]["t"] else "close")
        self.writes.append((kind, action))
        failure = self.failures.get(kind)
        if failure == "before":
            raise httpx.ReadTimeout("Network timeout; body must not be logged")
        if failure == "reject":
            return {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"error": "Rejected"}]}}}
        if kind == "leverage":
            self.leverage = action["leverage"]
            response = {"status": "ok", "response": {"type": "default"}}
        elif kind == "cancel":
            key = action["cancels"][0]["cloid"]
            if key in self.orders:
                self.orders[key]["status"] = "canceled"
            response = {"status": "ok", "response": {"type": "cancel", "data": {"statuses": ["success"]}}}
        else:
            order = action["orders"][0]
            self.oid += 1
            item = {"coin": "BTC", "cloid": order["c"], "oid": self.oid, "side": "B" if order["b"] else "A",
                    "sz": order["s"], "origSz": order["s"], "reduceOnly": order["r"], "isTrigger": "trigger" in order["t"],
                    "triggerPx": order["t"].get("trigger", {}).get("triggerPx", "0")}
            if kind in {"entry", "close"}:
                quantity = min(D(order["s"]), self.partial) if kind == "entry" else min(abs(self.position), D(order["s"]))
                self.fill(item, quantity, self.price)
                self.orders[order["c"]] = {"order": item, "status": "filled"}
                status = {"filled": {"oid": self.oid, "totalSz": str(quantity), "avgPx": str(self.price)}}
            else:
                self.orders[order["c"]] = {"order": item, "status": "open"}
                status = {"resting": {"oid": self.oid}}
            response = {"status": "ok", "response": {"type": "order", "data": {"statuses": [status]}}}
        if failure == "after":
            raise httpx.ReadTimeout("Timeout after execution; never replay")
        return response


@pytest.fixture
def execution_rig(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'review.db'}")
    episode = store.submit(PitchInput(author="QA trader", direction="long", entry="60000", stop="59400", target="61800",
                         thesis="A defined BTC breakout for offline lifecycle tests."), "request-123")
    exchange = FakeTestnet()
    for _ in range(4):
        asyncio.run(Pipeline(store, DemoReviewer()).step(asyncio.run(exchange.market())[1]))
    setup = ReviewedSetup.from_episode(store.get_episode(episode["id"]), store.policy)
    signer = TestnetSigner(FIXTURE_KEY, FIXTURE_ADDRESS, exchange.rules)
    url = f"sqlite:///{tmp_path / 'execution.db'}"
    ledger = ExecutionLedger(url, FIXTURE_ADDRESS, signer.address)
    broker = TestnetBroker(ledger, exchange, signer, armed=True)
    return broker, exchange, setup, url

