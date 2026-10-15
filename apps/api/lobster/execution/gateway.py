"""Fixed-host transport. No redirects, user-controlled URL or mainnet mode."""

from decimal import Decimal as D
import re

import httpx

from ..domain import Snapshot, utcnow
from .contracts import BtcRules, ExchangeAccount, TESTNET_URL


class HyperliquidTestnet:
    __test__ = False

    def __init__(self, client: httpx.AsyncClient, account_address: str):
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", account_address) or int(account_address, 16) == 0:
            raise ValueError("A nonzero testnet account address is required.")
        self.client = client
        self.account_address = account_address.lower()

    async def info(self, kind: str, **fields):
        response = await self.client.post(TESTNET_URL + "/info", json={"type": kind, **fields},
                                          follow_redirects=False, timeout=10)
        response.raise_for_status()
        return response.json()

    async def market(self) -> tuple[BtcRules, Snapshot]:
        observed = utcnow()
        meta, contexts = await self.info("metaAndAssetCtxs")
        index, asset = next((i, a) for i, a in enumerate(meta["universe"]) if a["name"] == "BTC")
        if asset.get("isDelisted"):
            raise ValueError("BTC is unavailable on testnet.")
        ctx = contexts[index]
        rules = BtcRules(asset_id=index, size_decimals=asset["szDecimals"], max_leverage=asset["maxLeverage"])
        snapshot = Snapshot(source="hyperliquid-testnet", price=ctx["midPx"] or ctx["markPx"], timestamp=observed,
            funding=ctx["funding"], open_interest=ctx["openInterest"])
        return rules, snapshot

    async def account(self) -> ExchangeAccount:
        observed = utcnow()
        state = await self.info("clearinghouseState", user=self.account_address)
        orders = await self.open_orders()
        positions = [item["position"] for item in state["assetPositions"]]
        btc = next((p for p in positions if p["coin"] == "BTC"), {})
        leverage = btc.get("leverage", {})
        return ExchangeAccount(address=self.account_address, observed_at=observed,
            equity=state["marginSummary"]["accountValue"], withdrawable=state["withdrawable"],
            btc_size=btc.get("szi", "0"), open_order_count=len(orders),
            other_positions=any(p["coin"] != "BTC" and D(p["szi"]) != 0 for p in positions),
            btc_leverage=leverage.get("value"), btc_is_cross=leverage.get("type") == "cross" if leverage else None)

    async def open_orders(self) -> list[dict]:
        return await self.info("frontendOpenOrders", user=self.account_address)

    async def agent_approved(self, agent_address: str) -> bool:
        agents = await self.info("extraAgents", user=self.account_address)
        now = int(utcnow().timestamp() * 1000)
        return any(a["address"].lower() == agent_address.lower() and int(a["validUntil"]) > now + 60000 for a in agents)

    async def order_status(self, order_cloid: str) -> dict:
        return await self.info("orderStatus", user=self.account_address, oid=order_cloid)

    async def fills(self) -> list[dict]:
        return await self.info("userFills", user=self.account_address, aggregateByTime=False)

    async def send(self, envelope: dict) -> dict:
        if envelope.get("vaultAddress") is not None or envelope["action"]["type"] not in {"order", "updateLeverage", "cancelByCloid"}:
            raise ValueError("Unsupported testnet execution action.")
        if not envelope.get("expiresAfter") or envelope["expiresAfter"] <= int(utcnow().timestamp() * 1000):
            raise ValueError("Signed action expired before submission.")
        response = await self.client.post(TESTNET_URL + "/exchange", json=envelope, follow_redirects=False, timeout=10)
        response.raise_for_status()
        return response.json()

