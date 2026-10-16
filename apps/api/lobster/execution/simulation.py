"""Deterministic in-memory exchange for offline rehearsals/tests only.

No HTTP client, wallet provider, network destination or live transport is created.
Every price, balance, order and fill produced here is a labelled synthetic fixture.
"""
from decimal import Decimal as D

import httpx

from ..domain import Snapshot, utcnow
from .contracts import BtcRules, ExchangeAccount

class SimulationGateway:
    def __init__(self):
        self.account_address = "0x" + "2" * 40
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


