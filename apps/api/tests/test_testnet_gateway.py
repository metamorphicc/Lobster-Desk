import asyncio
from datetime import timedelta
import json

import httpx
import pytest

from lobster.domain import utcnow
from lobster.execution.gateway import HyperliquidTestnet

ACCOUNT = "0x" + "2" * 40
AGENT = "0x" + "3" * 40


def test_gateway_uses_only_fixed_testnet_host_and_owner_queries():
    seen = []
    def respond(request):
        assert request.url.host == "api.hyperliquid-testnet.xyz"
        body = json.loads(request.content)
        seen.append(body)
        kind = body["type"]
        if kind == "metaAndAssetCtxs":
            return httpx.Response(200, json=[{"universe": [{"name": "ETH"}, {"name": "BTC", "szDecimals": 5, "maxLeverage": 40}]},
                [{}, {"midPx": "60000", "markPx": "60001", "funding": "0.0001", "openInterest": "20000"}]])
        assert body.get("user") == ACCOUNT
        if kind == "clearinghouseState":
            return httpx.Response(200, json={"marginSummary": {"accountValue": "1000"}, "withdrawable": "900", "assetPositions": []})
        if kind == "extraAgents":
            return httpx.Response(200, json=[{"name": "lobster-testnet", "address": AGENT,
                                            "validUntil": int((utcnow() + timedelta(hours=1)).timestamp() * 1000)}])
        if kind == "orderStatus":
            return httpx.Response(200, json={"status": "unknownOid"})
        return httpx.Response(200, json=[])
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            gateway = HyperliquidTestnet(client, ACCOUNT)
            rules, market = await gateway.market()
            assert rules.asset_id == 1
            assert market.source == "hyperliquid-testnet"
            assert (await gateway.account()).equity == 1000
            assert await gateway.agent_approved(AGENT)
            assert not await gateway.agent_approved(ACCOUNT)
            assert await gateway.order_status("0x" + "1" * 32) == {"status": "unknownOid"}
            assert await gateway.fills() == []
    asyncio.run(run())
    assert all(item.get("user") != AGENT for item in seen)


def test_gateway_does_not_follow_redirects():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://api.hyperliquid.xyz/info"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await HyperliquidTestnet(client, ACCOUNT).market()
    asyncio.run(run())
    assert len(requests) == 1


@pytest.mark.parametrize("action", ["withdraw3", "usdSend", "approveAgent", "spotSend"])
def test_gateway_has_no_money_transfer_action(action):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail("No HTTP request allowed"))) as client:
            with pytest.raises(ValueError, match="Unsupported"):
                await HyperliquidTestnet(client, ACCOUNT).send({"action": {"type": action}, "vaultAddress": None})
    asyncio.run(run())


def test_expired_signature_is_not_sent():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail("No HTTP request allowed"))) as client:
            with pytest.raises(ValueError, match="expired"):
                await HyperliquidTestnet(client, ACCOUNT).send({"action": {"type": "order"}, "expiresAfter": 1})
    asyncio.run(run())

