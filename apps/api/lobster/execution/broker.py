"""Testnet execution state machine; writes require an explicitly armed owner process.

This is intentionally not registered as a public trading API. Network writes are
never retried automatically. Reconciliation is read-only except for reducing risk
(installing protection, cancelling owned leftovers, or emergency reduce-only exit).
"""

import asyncio
from datetime import datetime
from decimal import Decimal as D

from ..domain import RiskPolicy, utcnow
from .contracts import BtcRules, OrderSpec, ReviewedSetup, cloid, fingerprint, size_entry
from .gateway import HyperliquidTestnet
from .ledger import ExecutionLedger
from .signer import TestnetSigner


def now_ms() -> int:
    return int(utcnow().timestamp() * 1000)


def decode_ack(body: dict, kind: str) -> dict:
    if body.get("status") != "ok":
        return {"outcome": "rejected"}
    response = body.get("response", {})
    if kind == "leverage":
        if response.get("type") != "default":
            raise ValueError("Unexpected leverage response.")
        return {"outcome": "accepted"}
    statuses = response.get("data", {}).get("statuses", [])
    if len(statuses) != 1:
        raise ValueError("Expected exactly one command status.")
    item = statuses[0]
    if kind == "cancel" and item == "success":
        return {"outcome": "cancelled"}
    if isinstance(item, dict) and "error" in item:
        return {"outcome": "rejected"}
    if isinstance(item, dict) and "resting" in item:
        return {"outcome": "resting", "oid": int(item["resting"]["oid"])}
    if isinstance(item, dict) and "filled" in item:
        filled = item["filled"]
        quantity, price = D(filled["totalSz"]), D(filled["avgPx"])
        if not quantity.is_finite() or not price.is_finite() or min(quantity, price) <= 0:
            raise ValueError("Invalid fill acknowledgement.")
        return {"outcome": "filled", "oid": int(filled["oid"]), "quantity": str(quantity), "price": str(price)}
    raise ValueError("Unknown exchange acknowledgement.")


class TestnetBroker:
    __test__ = False

    def __init__(self, ledger: ExecutionLedger, gateway: HyperliquidTestnet, signer: TestnetSigner,
                 *, armed: bool = False, policy: RiskPolicy | None = None, entry_guard=None):
        self.ledger, self.gateway, self.signer = ledger, gateway, signer
        self.armed = armed
        self.policy = policy or RiskPolicy()
        self.entry_guard = entry_guard
        self.lock = asyncio.Lock()
        identity = ledger.snapshot()["control"]
        self.network = identity["network"]
        if self.network != getattr(gateway, "network", "testnet") or self.network != signer.network:
            raise ValueError("Signer, gateway and ledger networks do not match.")
        if identity["account"] != gateway.account_address.lower() or identity["signer"] != signer.address.lower():
            raise ValueError("Signer, gateway and ledger identities do not match.")

    async def _entry_capital(self, account):
        # Refresh user cash-flow references/permissions before EACH entry check.
        # Deliberately absent from reconciliation: outages must not disable exits.
        if self.entry_guard is not None:
            await self.entry_guard(account)
        return self.ledger.observe_capital(account, self.policy)

    async def stage(self, setup: ReviewedSetup) -> dict:
        rules, market = await self.gateway.market()
        account = await self.gateway.account()
        if rules != self.signer.rules:
            raise ValueError("BTC metadata changed; recreate the signer with current rules.")
        capital = await self._entry_capital(account)
        order = size_entry(setup, market, account, capital, rules, self.policy, utcnow(), self.signer.max_entry_notional)
        return self.ledger.stage(setup, order.model_dump(mode="json"), rules.model_dump(mode="json"))

    async def _send(self, trade_id: str, key: str, kind: str, request: dict) -> dict:
        if not self.armed:
            raise ValueError("Testnet submission is not armed.")
        command = self.ledger.prepare_command(trade_id, key, kind, request)
        claimed = self.ledger.claim(key, now_ms())
        if claimed is None:
            return command  # Any previous attempt must be reconciled, never replayed.
        try:
            now = now_ms()
            if kind == "leverage":
                envelope = self.signer.leverage(request["leverage"], claimed["nonce"], now)
            elif kind == "cancel":
                envelope = self.signer.cancel(request["cloid"], claimed["nonce"], now)
            else:
                deadline = (int(datetime.fromisoformat(self.ledger.trade(trade_id)["setup"]["expires_at"]).timestamp() * 1000)
                            if kind == "entry" else None)
                envelope = self.signer.order(OrderSpec.model_validate(request), claimed["nonce"], now, deadline)
            result = decode_ack(await self.gateway.send(envelope), kind)
            self.ledger.finish(key, "rejected" if result["outcome"] == "rejected" else "acknowledged", result)
        except Exception:
            # The exchange may have accepted the request. Do not persist exception
            # bodies, signed envelopes or key material, and do not send again.
            self.ledger.finish(key, "unknown", {"outcome": "unknown"})
        return next(c for c in self.ledger.commands(trade_id) if c["id"] == key)

    async def dispatch(self, trade_id: str) -> dict:
        async with self.lock:
            return await self._dispatch(trade_id)

    async def _dispatch(self, trade_id: str) -> dict:
        if not self.armed:
            raise ValueError("Testnet submission is not armed.")
        trade = self.ledger.trade(trade_id)
        if any(c["kind"] == "entry" for c in self.ledger.commands(trade_id)):
            return await self._reconcile(trade_id)
        if trade["status"] in {"closed", "rejected", "expired", "cancelled"}:
            return trade
        setup = ReviewedSetup.model_validate(trade["setup"])
        if trade["setup_hash"] != fingerprint(setup.model_dump(mode="json")):
            raise ValueError("Staged setup binding changed.")
        if not await self.gateway.agent_approved(self.signer.address):
            raise ValueError("The dedicated API wallet is not approved on testnet or is about to expire.")
        rules, market = await self.gateway.market()
        account = await self.gateway.account()
        if rules.model_dump(mode="json") != trade["rules"]:
            raise ValueError("BTC exchange metadata changed after staging.")
        capital = await self._entry_capital(account)
        order = size_entry(setup, market, account, capital, rules, self.policy, utcnow(), self.signer.max_entry_notional)
        # A refreshed quote may only reduce the originally approved quantity.
        order = order.model_copy(update={"quantity": min(order.quantity, D(trade["entry"]["quantity"]))})
        if order.quantity * order.price < self.policy.min_notional:
            raise ValueError("Refreshed entry notional is below the exchange minimum.")
        leverage_key = f"{trade_id}:leverage"
        leverage = await self._send(trade_id, leverage_key, "leverage", {"leverage": setup.pitch.leverage})
        if leverage["status"] == "rejected":
            self.ledger.update_trade(trade_id, "rejected", "Exchange rejected isolated leverage configuration.")
            return self.ledger.trade(trade_id)
        if leverage["status"] not in {"acknowledged", "reconciled"}:
            self.ledger.update_trade(trade_id, "needs_reconciliation", "Isolated leverage configuration is unconfirmed; no entry sent.")
            return self.ledger.trade(trade_id)
        if leverage["result"].get("outcome") == "rejected":
            self.ledger.update_trade(trade_id, "rejected", "Exchange rejected isolated leverage configuration.")
            return self.ledger.trade(trade_id)
        # Recheck both market and account AFTER the leverage roundtrip as well.
        rules, market = await self.gateway.market()
        account = await self.gateway.account()
        if not -2 <= (utcnow() - account.observed_at).total_seconds() <= self.policy.max_data_age_seconds:
            self.ledger.update_trade(trade_id, "needs_reconciliation", "Account observation is stale; no reconciliation writes authorized.")
            return self.ledger.trade(trade_id)
        capital = await self._entry_capital(account)
        final = size_entry(setup, market, account, capital, rules, self.policy, utcnow(), self.signer.max_entry_notional)
        final = final.model_copy(update={"quantity": min(final.quantity, order.quantity)})
        if final.quantity * final.price < self.policy.min_notional:
            raise ValueError("Final rounded entry is below the exchange minimum.")
        self.ledger.update_trade(trade_id, "submitting", "Entry authorized after fresh risk and capital checks.",
                                 entry=final.model_dump(mode="json"))
        result = await self._send(trade_id, final.cloid, "entry", final.model_dump(mode="json"))
        if result["status"] == "rejected":
            self.ledger.update_trade(trade_id, "rejected", "Exchange rejected entry; no automatic retry.")
            return self.ledger.trade(trade_id)
        return await self._reconcile(trade_id)

    async def reconcile(self, trade_id: str) -> dict:
        async with self.lock:
            return await self._reconcile(trade_id)

    async def _observe_commands(self, trade_id: str):
        for command in self.ledger.commands(trade_id):
            if command["kind"] not in {"entry", "stop", "target", "close"}:
                continue
            if command["status"] == "prepared" or command["status"] == "rejected":
                continue
            response = await self.gateway.order_status(command["request"]["cloid"])
            if response.get("status") == "unknownOid":
                continue  # Missing data is not evidence that a timed-out write failed.
            observed = response["order"]
            item = observed["order"]
            request = OrderSpec.model_validate(command["request"])
            if item["coin"] != "BTC" or item.get("cloid") != request.cloid or item["side"] != ("B" if request.side == "buy" else "A"):
                self.ledger.halt("An exchange order did not match its local identity.")
                raise ValueError("Exchange order identity mismatch.")
            if command["result"] and command["result"].get("oid") not in {None, int(item["oid"])}:
                self.ledger.halt("The exchange returned conflicting order IDs.")
                raise ValueError("Conflicting order IDs.")
            result = (command["result"] or {}) | {"oid": int(item["oid"]), "exchange_status": observed["status"]}
            self.ledger.finish(command["id"], "reconciled", result)

    def _protective(self, trade: dict, quantity: D, kind: str) -> OrderSpec:
        rules = self.signer.rules
        setup = ReviewedSetup.model_validate(trade["setup"])
        sell = setup.pitch.direction == "long"
        trigger = rules.price(setup.pitch.stop if kind == "stop" else setup.pitch.target,
                              upward=sell if kind == "stop" else not sell)
        # Exchange-native trigger with bounded aggressive execution price. Gaps can
        # still exceed this bound; reconciliation must not claim a guaranteed stop.
        price = rules.price(trigger * (D("0.99") if sell else D("1.01")), upward=not sell)
        key = cloid(trade["id"], f"{kind}:{quantity}", network=self.network)
        return OrderSpec(asset_id=rules.asset_id, side="sell" if sell else "buy", quantity=quantity,
                         price=price, trigger_price=trigger, kind=kind, cloid=key)

    @staticmethod
    def _confirmed(order: OrderSpec, observed: list[dict]) -> bool:
        return any(item.get("cloid") == order.cloid and item.get("coin") == "BTC" and item.get("reduceOnly") is True
            and item.get("isTrigger") is True and item.get("side") == ("B" if order.side == "buy" else "A")
            and D(item["sz"]) == order.quantity and D(item["triggerPx"]) == order.trigger_price for item in observed)

    async def _emergency_exit(self, trade: dict, quantity: D):
        self.ledger.halt("Position protection was not confirmed. New entries are blocked.")
        self.ledger.update_trade(trade["id"], "emergency", "Protection failed; attempting an owned reduce-only exit.")
        if not self.armed:
            return
        commands = [c for c in self.ledger.commands(trade["id"]) if c["kind"] == "close"]
        if any(c["status"] in {"sending", "unknown"} for c in commands) or len(commands) >= 3:
            self.ledger.update_trade(trade["id"], "needs_review", "Emergency exit is unresolved or its attempt budget is exhausted. Owner intervention required.")
            return
        _, market = await self.gateway.market()
        sell = trade["setup"]["pitch"]["direction"] == "long"
        price = self.signer.rules.price(market.price * (D("0.99") if sell else D("1.01")), upward=not sell)
        order = OrderSpec(asset_id=self.signer.rules.asset_id, side="sell" if sell else "buy", quantity=quantity,
            price=price, cloid=cloid(trade["id"], f"close:{quantity}", network=self.network), kind="close")
        await self._send(trade["id"], order.cloid, "close", order.model_dump(mode="json"))

    async def _reconcile(self, trade_id: str) -> dict:
        trade = self.ledger.trade(trade_id)
        await self._observe_commands(trade_id)
        commands = self.ledger.commands(trade_id)
        entry = next((c for c in commands if c["kind"] == "entry"), None)
        if not entry:
            return trade
        account = await self.gateway.account()
        if account.network != self.network or account.address.lower() != self.gateway.account_address.lower():
            raise ValueError("Reconciliation observation belongs to a different network/account.")
        if not -2 <= (utcnow() - account.observed_at).total_seconds() <= self.policy.max_data_age_seconds:
            self.ledger.update_trade(trade_id, "needs_reconciliation", "Account observation is stale; no reconciliation writes authorized.")
            return self.ledger.trade(trade_id)
        owned = {int(c["result"]["oid"]) for c in commands if c["result"] and c["result"].get("oid") is not None}
        self.ledger.record_fills(trade_id, await self.gateway.fills(), owned)
        fills = [f for f in self.ledger.snapshot()["fills"] if int(f["oid"]) in owned]
        entry_oid = (entry["result"] or {}).get("oid")
        entered = sum((D(f["sz"]) for f in fills if f["oid"] == entry_oid), D("0"))
        exited = sum((D(f["sz"]) for f in fills if f["oid"] != entry_oid), D("0"))
        if not account.btc_size:
            # Flat account alone cannot resolve an uncertain write or delayed fills.
            if entered > 0 and exited == entered:
                if self.armed:
                    for command in commands:
                        if command["kind"] in {"stop", "target"}:
                            key = command["request"]["cloid"]
                            await self._send(trade_id, f"{key}:cancel", "cancel", {"cloid": key})
                leftovers = await self.gateway.open_orders()
                owned_cloids = {c["request"].get("cloid") for c in commands if c["kind"] in {"stop", "target"}}
                clean = not any(o.get("cloid") in owned_cloids for o in leftovers)
                self.ledger.update_trade(trade_id, "closed" if clean else "closing_cleanup",
                    "Owned fills reconcile to flat; protective-order cleanup confirmed." if clean else
                    "Position is flat, but owned protective orders still need cleanup.", filled_quantity=str(entered), protected_quantity="0")
            elif entry["status"] == "rejected":
                self.ledger.update_trade(trade_id, "rejected", "Entry was explicitly rejected by the exchange.")
            else:
                self.ledger.update_trade(trade_id, "needs_reconciliation", "Waiting for authoritative order/fill observations. No entry will be resent.")
            return self.ledger.trade(trade_id)
        quantity = abs(account.btc_size)
        expected_sign = 1 if trade["setup"]["pitch"]["direction"] == "long" else -1
        acknowledged = D((entry["result"] or {}).get("quantity", "0"))
        if account.btc_size * expected_sign <= 0 or quantity > D(trade["entry"]["quantity"]) or quantity > max(entered, acknowledged) or entry_oid is None:
            self.ledger.halt("Observed BTC exposure cannot be attributed to the owned entry.")
            self.ledger.update_trade(trade_id, "needs_review", "Unexpected account exposure. No unidentified position will be modified.")
            return self.ledger.trade(trade_id)
        capital = self.ledger.observe_capital(account, self.policy)
        if capital.paused or account.btc_is_cross is not False or account.btc_leverage is None or account.btc_leverage > 2:
            await self._emergency_exit(trade, quantity)
            return self.ledger.trade(trade_id)
        stop = self._protective(trade, quantity, "stop")
        observed = await self.gateway.open_orders()
        if not self._confirmed(stop, observed):
            if not self.armed:
                self.ledger.update_trade(trade_id, "needs_protection", "Owned exposure observed; the signer is not armed to install protection.")
                return self.ledger.trade(trade_id)
            command = await self._send(trade_id, stop.cloid, "stop", stop.model_dump(mode="json"))
            observed = await self.gateway.open_orders()
            if not self._confirmed(stop, observed):
                # A successful HTTP response alone is not sufficient protection.
                await self._emergency_exit(trade, quantity)
                return self.ledger.trade(trade_id)
        target = self._protective(trade, quantity, "target")
        if self.armed and not self._confirmed(target, observed):
            await self._send(trade_id, target.cloid, "target", target.model_dump(mode="json"))
            observed = await self.gateway.open_orders()
        # Replacement stop is installed first. Only then cancel older owned sizes.
        if self.armed:
            for command in self.ledger.commands(trade_id):
                if command["kind"] in {"stop", "target"} and command["request"]["cloid"] not in {stop.cloid, target.cloid}:
                    key = command["request"]["cloid"]
                    await self._send(trade_id, f"{key}:cancel", "cancel", {"cloid": key})
        self.ledger.update_trade(trade_id, "protected", "Exchange-native stop confirmed against the actual filled size.",
            filled_quantity=str(entered or acknowledged), protected_quantity=str(quantity),
            target_confirmed=self._confirmed(target, observed))
        return self.ledger.trade(trade_id)

