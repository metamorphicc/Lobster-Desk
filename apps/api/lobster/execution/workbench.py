"""Read-only exchange inspection and local intent staging. No signer imports."""

import httpx

from ..domain import Capital, RiskPolicy, utcnow
from .contracts import ReviewedSetup, TESTNET_URL, size_entry
from .gateway import HyperliquidTestnet
from .ledger import ExecutionLedger
from .settings import TestnetSettings, require_separate_database


class TestnetWorkbench:
    __test__ = False

    def __init__(self, settings: TestnetSettings, client: httpx.AsyncClient, paper_database_url: str):
        self.settings = settings
        require_separate_database(paper_database_url, settings.database_url)
        if settings.account_address and settings.account_address == settings.api_wallet_address:
            raise ValueError("The owner and API wallet must be different addresses.")
        self.gateway = HyperliquidTestnet(client, settings.account_address)
        self.ledger = (ExecutionLedger(settings.database_url, settings.account_address, settings.api_wallet_address)
                       if settings.account_address and settings.api_wallet_address else None)
        self.policy = RiskPolicy()

    def status(self) -> dict:
        return {"network": "testnet", "endpoint": TESTNET_URL,
            "account_address": self.settings.account_address, "api_wallet_address": self.settings.api_wallet_address,
            "max_entry_notional": str(self.settings.max_entry_notional), "execution_enabled": False,
            "private_key_loaded": False, "operator_staging_available": self.ledger is not None,
            "funded_acceptance_verified": False,
            "ledger": self.ledger.snapshot() if self.ledger else None}

    async def inspect(self) -> dict:
        checks = [
            {"key": "network", "label": "Hyperliquid testnet", "status": "unknown"},
            {"key": "account", "label": "Dedicated account", "status": "missing"},
            {"key": "funding", "label": "Testnet trading balance", "status": "unknown"},
            {"key": "flat", "label": "No positions or open orders", "status": "unknown"},
            {"key": "agent", "label": "API wallet approval", "status": "missing"},
            {"key": "halt", "label": "Execution ledger allows new entries", "status":
                "blocked" if self.ledger and self.ledger.snapshot()["control"]["halt_reason"] else "ok"},
        ]
        market = rules = account = None
        error = None
        try:
            rules, market = await self.gateway.market()
            checks[0]["status"] = "ok" if (utcnow() - market.timestamp).total_seconds() <= 15 else "blocked"
            if self.settings.account_address:
                checks[1]["status"] = "ok"
                account = await self.gateway.account()
                checks[2]["status"] = "ok" if account.equity > 0 and account.withdrawable > 0 else "blocked"
                checks[3]["status"] = "ok" if not account.btc_size and not account.other_positions and not account.open_order_count else "blocked"
                if self.settings.api_wallet_address:
                    checks[4]["status"] = "ok" if await self.gateway.agent_approved(self.settings.api_wallet_address) else "blocked"
        except Exception:
            error = "Testnet inspection could not complete. No exchange write was attempted. Check the network and configured public addresses."
        # The last account request may have aged the initial market observation.
        if market and not -2 <= (utcnow() - market.timestamp).total_seconds() <= 15:
            checks[0]["status"] = "blocked"
        if account and not -2 <= (utcnow() - account.observed_at).total_seconds() <= 15:
            checks[2]["status"] = "blocked"
        return self.status() | {"checks": checks, "error": error,
            "market": market.model_dump(mode="json") if market else None,
            "rules": rules.model_dump(mode="json") if rules else None,
            "account": account.model_dump(mode="json") if account else None,
            "ready_to_stage": error is None and all(c["status"] == "ok" for c in checks)}

    def _capital(self, account) -> Capital:
        control = self.ledger.snapshot()["control"] if self.ledger else {}
        return Capital(equity=account.equity, available_cash=account.withdrawable,
            day_start_equity=control.get("day_start_equity") or account.equity,
            high_water_equity=control.get("high_water_equity") or account.equity,
            paused=bool(control.get("halt_reason")))

    async def preflight(self, episode: dict) -> tuple[dict, ReviewedSetup | None]:
        result = await self.inspect()
        result = result | {"episode_id": episode["id"], "eligible": False, "order": None, "reason": None}
        if not result["ready_to_stage"]:
            result["reason"] = "Complete the readiness checks before staging a testnet intent."
            return result, None
        try:
            from ..domain import Snapshot
            from .contracts import BtcRules, ExchangeAccount
            setup = ReviewedSetup.from_episode(episode, self.policy)
            account = ExchangeAccount.model_validate(result["account"])
            existing = next((t for t in self.ledger.snapshot()["trades"] if t["id"] == setup.episode_id), None) if self.ledger else None
            if existing and existing["status"] != "staged":
                raise ValueError("This episode already has a submitted or terminal intent. Pitch a new setup for a new entry.")
            if self.ledger and any(t["status"] not in {"closed", "rejected", "expired", "cancelled"}
                and t["id"] != setup.episode_id for t in self.ledger.snapshot()["trades"]):
                raise ValueError("Another unresolved testnet intent owns the execution slot.")
            order = size_entry(setup, Snapshot.model_validate(result["market"]), account,
                self._capital(account), BtcRules.model_validate(result["rules"]), self.policy,
                utcnow(), self.settings.max_entry_notional)
            result.update(eligible=True, order=order.model_dump(mode="json"),
                          reason="Risk, approval and account checks passed. This preview sends no order.")
            return result, setup
        except ValueError as error:
            result["reason"] = str(error)
            return result, None

    async def stage(self, episode: dict) -> dict:
        if not self.ledger:
            raise ValueError("Configure both public testnet addresses before staging.")
        report, setup = await self.preflight(episode)
        if not report["eligible"] or setup is None:
            raise ValueError(report["reason"])
        from .contracts import ExchangeAccount
        self.ledger.observe_capital(ExchangeAccount.model_validate(report["account"]), self.policy)
        return self.ledger.stage(setup, report["order"], report["rules"])
