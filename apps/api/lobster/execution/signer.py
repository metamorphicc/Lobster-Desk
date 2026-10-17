"""Narrow SDK-backed signer: no generic action, withdrawal or mainnet entrypoint."""

from decimal import Decimal

from eth_account import Account
from hyperliquid.utils.signing import sign_l1_action
from pydantic import SecretStr

from .contracts import BtcRules, OrderSpec


class TestnetSigner:
    __test__ = False
    network = "testnet"
    def __init__(self, key: SecretStr, account_address: str, rules: BtcRules,
                 max_entry_notional: Decimal = Decimal("50"), *, builder: str | None = None, builder_fee_tenths_bps: int = 0):
        import re
        if (type(builder_fee_tenths_bps) is not int or not 0 <= builder_fee_tenths_bps <= 100
                or (builder is None and builder_fee_tenths_bps != 0)):
            raise ValueError("Builder fee must be a configured integer from 0 to 100 tenths of a basis point.")
        if builder is not None and (not re.fullmatch(r"0x[0-9a-fA-F]{40}", builder) or int(builder, 16) == 0
                                    or builder.lower() == account_address.lower()):
            raise ValueError("A separate nonzero builder address is required.")
        try:
            self.__wallet = Account.from_key(key.get_secret_value())
        except Exception:
            raise ValueError("The testnet API wallet key is invalid.") from None
        if self.__wallet.address.lower() == account_address.lower():
            raise ValueError("Use a dedicated API wallet, not the account's main private key.")
        if not max_entry_notional.is_finite() or not Decimal("10") <= max_entry_notional <= Decimal("100"):
            raise ValueError("The initial testnet entry cap must be between $10 and $100.")
        self.address = self.__wallet.address
        self.rules = rules
        self.max_entry_notional = max_entry_notional
        self.builder = builder.lower() if builder else None
        self.builder_fee_tenths_bps = builder_fee_tenths_bps

    def __repr__(self):
        return f"{type(self).__name__}(address={self.address!r}, network={self.network!r})"

    def _envelope(self, action: dict, nonce: int, now_ms: int, deadline_ms: int | None = None) -> dict:
        if not now_ms - 1000 <= nonce <= now_ms + 1000:
            raise ValueError("Nonce is outside the permitted signing window.")
        expires = min(now_ms + 5000, deadline_ms) if deadline_ms is not None else now_ms + 5000
        if expires <= now_ms:
            raise ValueError("Approval expired before signing.")
        signature = sign_l1_action(self.__wallet, action, None, nonce, expires, self.network == "mainnet")
        return {"action": action, "nonce": nonce, "signature": signature, "vaultAddress": None, "expiresAfter": expires}

    def order(self, order: OrderSpec, nonce: int, now_ms: int, deadline_ms: int | None = None, *, include_builder: bool = True) -> dict:
        if order.asset_id != self.rules.asset_id or order.quantity % self.rules.quantity_step:
            raise ValueError("Order does not match BTC market precision.")
        if self.rules.price(order.price) != order.price:
            raise ValueError("Order price has invalid exchange precision.")
        if order.trigger_price is not None and self.rules.price(order.trigger_price) != order.trigger_price:
            raise ValueError("Trigger price has invalid exchange precision.")
        if order.kind == "entry" and not Decimal("10") <= order.price * order.quantity <= self.max_entry_notional:
            raise ValueError("Entry notional falls outside the signer cap.")
        action = {"type": "order", "orders": [order.to_wire()], "grouping": "na"}
        if self.builder is not None and include_builder:
            action["builder"] = {"b": self.builder, "f": self.builder_fee_tenths_bps}
        return self._envelope(action, nonce, now_ms, deadline_ms)

    def leverage(self, value: int, nonce: int, now_ms: int) -> dict:
        if not 1 <= value <= min(2, self.rules.max_leverage):
            raise ValueError("Only isolated leverage up to 2x is permitted.")
        return self._envelope({"type": "updateLeverage", "asset": self.rules.asset_id,
                               "isCross": False, "leverage": value}, nonce, now_ms)

    def cancel(self, order_cloid: str, nonce: int, now_ms: int) -> dict:
        import re
        if not re.fullmatch(r"0x[0-9a-f]{32}", order_cloid):
            raise ValueError("Invalid client order ID.")
        return self._envelope({"type": "cancelByCloid", "cancels": [
            {"asset": self.rules.asset_id, "cloid": order_cloid}]}, nonce, now_ms)


class MainnetSigner(TestnetSigner):
    """Same restricted BTC action grammar, explicit mainnet signing domain."""
    network = "mainnet"

