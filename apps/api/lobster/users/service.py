"""Public account observations, always from the fixed testnet /info endpoint."""

from decimal import Decimal as D

import httpx

from ..domain import utcnow
from ..execution.gateway import HyperliquidTestnet
from .contracts import UserTestnetSettings, fee_percent


def amount(value) -> str:
    # Upstream monetary values must remain decimal strings, never binary floats.
    if isinstance(value, (float, bool)):
        raise ValueError("Malformed exchange amount.")
    result = D(value)
    if not result.is_finite():
        raise ValueError("Non-finite exchange amount.")
    return str(result)


class UserTestnetService:
    def __init__(self, settings: UserTestnetSettings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    def config(self) -> dict:
        return {"network": "testnet", "account_access": "public_read_only", "authenticated": False,
            "order_submission_enabled": False, "fee_collection_enabled": False,
            "builder_address": self.settings.builder_address,
            "builder_fee_tenths_bps": self.settings.builder_fee_tenths_bps,
            "builder_fee_percent": fee_percent(self.settings.builder_fee_tenths_bps)}

    async def inspect(self, address: str) -> dict:
        observed = utcnow()
        gateway = HyperliquidTestnet(self.client, address)
        state = await gateway.info("clearinghouseState", user=address)
        orders = await gateway.open_orders()
        fees = await gateway.info("userFees", user=address)
        approval = None
        if self.settings.builder_address:
            approval = await gateway.info("maxBuilderFee", user=address, builder=self.settings.builder_address)
            if not isinstance(approval, int) or isinstance(approval, bool) or approval < 0:
                raise ValueError("Malformed builder approval.")
        positions = []
        for item in state["assetPositions"]:
            position = item["position"]
            if D(amount(position["szi"])):
                positions.append({"symbol": str(position["coin"]), "quantity": amount(position["szi"]),
                    "entry_price": amount(position["entryPx"]) if position.get("entryPx") is not None else None,
                    "unrealized_pnl": amount(position["unrealizedPnl"])})
        taker = amount(fees["userCrossRate"])
        if not D("0") <= D(taker) <= D("0.01"):
            raise ValueError("Unsupported account fee rate.")
        return self.config() | {"address": address, "observed_at": observed.isoformat(),
            "exchange_time_ms": state.get("time"),
            "stale": (utcnow() - observed).total_seconds() > 15,
            "equity": amount(state["marginSummary"]["accountValue"]), "withdrawable": amount(state["withdrawable"]),
            "positions": positions, "reported_taker_rate": taker,
            "open_orders": [{"symbol": str(order["coin"]), "oid": str(order["oid"]), "side": str(order["side"]),
                "quantity": amount(order["sz"]), "limit_price": amount(order["limitPx"]),
                "reduce_only": order.get("reduceOnly") is True, "is_trigger": order.get("isTrigger") is True}
                for order in orders],
            "approved_builder_fee_tenths_bps": approval,
            "builder_approval_status": ("not_configured" if approval is None else "not_approved" if approval == 0 else
                "below_requested" if approval < self.settings.builder_fee_tenths_bps else "approved"),
            "limits": "Public data does not authenticate wallet ownership. Reported account fees may differ from final exchange fees. No orders or fee collection are enabled."}

    async def capital_history(self, address: str, start: int, end: int) -> list[dict]:
        from .capital import normalize_receipt
        if not 0 <= start <= end or end - start > 7 * 86400000:
            raise ValueError("The accounting window exceeds its seven-day recovery bound.")
        gateway = HyperliquidTestnet(self.client, address)
        normalized = []
        for stream, kind in (("ledger", "userNonFundingLedgerUpdates"), ("funding", "userFunding")):
            cursor, seen = start, set()
            for _ in range(10):
                page = await gateway.info(kind, user=address, startTime=cursor, endTime=end)
                if not isinstance(page, list) or len(page) > 5000:
                    raise ValueError("Malformed or oversized capital history page.")
                next_cursor = cursor
                added = 0
                for item in page:
                    receipt = normalize_receipt(address, stream, item, cursor, end)
                    next_cursor = max(next_cursor, receipt["time"])
                    pair = (receipt["id"], receipt["details_hash"])
                    if pair not in seen:
                        normalized.append(receipt); seen.add(pair); added += 1
                if len(page) < 500:
                    break
                if next_cursor <= cursor or not added:
                    raise ValueError("Capital pagination cannot establish complete timestamp coverage.")
                cursor = next_cursor  # Inclusive overlap; never skip same-timestamp entries.
            else:
                raise ValueError("Capital pagination budget exhausted; history remains incomplete.")
        return sorted(normalized, key=lambda item: (item["time"], item["id"]))
