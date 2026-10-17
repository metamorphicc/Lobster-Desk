"""Opt-in user testnet writer. The legacy UserExecution remains locked."""
from decimal import Decimal as D
from pathlib import Path
from typing import Literal

from eth_account import Account
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..domain import utcnow, Capital
from ..execution.broker import TestnetBroker
from ..execution.signer import TestnetSigner
from .execution import UserExecution, UserLedger
from .financial import FinancialIntentAdapter

TERMINAL = {"closed", "rejected", "expired", "cancelled"}


class UserRunnerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.users", env_prefix="USER_EXECUTION_", extra="ignore", hide_input_in_errors=True)
    enabled: bool = False
    network: Literal["testnet", "mainnet"] = "testnet"
    keys_json: SecretStr | None = None

    def keys(self):
        import json
        from pydantic import TypeAdapter
        from .contracts import Address
        data = json.loads(self.keys_json.get_secret_value()) if self.keys_json else {}
        if not isinstance(data, dict) or len(data) > 100: raise ValueError("Bounded owner/API-key mapping required.")
        result = {}
        for owner, key in data.items():
            owner = TypeAdapter(Address).validate_python(owner)
            if not isinstance(key, str): raise ValueError("Dedicated API-wallet key required.")
            Account.from_key(key)
            if owner in result: raise ValueError("Duplicate normalized user wallet.")
            result[owner] = SecretStr(key)
        return result


class FinancialUserExecution(UserExecution):
    def __init__(self, *, financial, armed=False, **kwargs):
        if not armed: raise ValueError("The financial user writer must be explicitly armed.")
        original = kwargs["gateway"]
        self.financial = financial
        self.network = financial.network
        super().__init__(intents=FinancialIntentAdapter(financial), **kwargs)
        # This is a separate explicit executable class. The original rehearsal
        # gateway cannot be unlocked by changing its armed flag.
        self.broker.gateway, self.broker.armed = original, True

    async def entry_guard(self, account):
        if any(job["kind"] != "trade" and job["status"] in {"sending", "unknown"} for job in self.financial.jobs(self.owner)):
            raise ValueError("An uncertain owner permission command blocks entry until reviewed.")
        await super().entry_guard(account)

    def status(self):
        return {"intent_id": self.intent["id"], "plan_id": self.plan["id"], "address": self.owner,
            "ledger": self.ledger.snapshot(), "exchange_submission_enabled": True, "network": self.network}


class RecoverySigner(TestnetSigner):
    def __init__(self, *args, network="testnet", **kwargs):
        if network not in {"testnet", "mainnet"}: raise ValueError("Unsupported recovery network.")
        self.network = network
        super().__init__(*args, **kwargs)
    def order(self, order, *args, **kwargs):
        if order.kind == "entry": raise ValueError("Recovery cannot create an entry.")
        return super().order(order, *args, **kwargs, include_builder=False)
    def leverage(self, *args, **kwargs): raise ValueError("Recovery cannot change leverage.")


class RecoveryLedger(UserLedger):
    def observe_capital(self, account, policy):
        try: return super().observe_capital(account, policy)
        except Exception:
            # Missing application references cannot disable reduction of already
            # attributed owned exposure. This ledger is never used for entries.
            return Capital(equity=account.equity, available_cash=account.withdrawable,
                day_start_equity=account.equity, high_water_equity=account.equity, occupied=True, paused=True)


class UserFinancialRunner:
    def __init__(self, *, store, financial, capital, service, root, enabled=False, armed=False):
        self.store, self.financial, self.capital, self.service = store, financial, capital, service
        self.root, self.enabled, self.armed = Path(root).resolve(), enabled, armed
        self.network = financial.network
        if capital.network != self.network or getattr(service, "network", "testnet") != self.network: raise ValueError("User runner network mismatch.")

    async def tick(self, owner, key, gateway):
        if not self.armed: raise ValueError("User runner is not armed.")
        if getattr(gateway, "network", "testnet") != self.network: raise ValueError("User gateway network mismatch.")
        profile = self.financial.intents.profile(owner)
        if not profile or Account.from_key(key.get_secret_value()).address.lower() != profile["agent"]:
            raise ValueError("Runner key differs from the user's immutable dedicated API-wallet profile.")
        rules, _ = await gateway.market()
        path = self.root / owner / (profile["agent"] + ".sqlite3")
        if path == Path(self.store.engine.url.database).resolve(): raise ValueError("User financial journal must be separate.")
        ledger = RecoveryLedger("sqlite:///" + path.as_posix(), owner, profile["agent"], network=self.network)
        ledger.bind(self.capital, owner)
        try:
            from ..ops.catalog import register_journal
            register_journal(self.store, ledger, "user")
            active = next((trade for trade in ledger.snapshot()["trades"] if trade["status"] not in TERMINAL), None)
            if active and ledger.commands(active["id"]):
                # Reconstruct from the execution journal, not an expired model
                # review/preview. This path has no entry or leverage signer.
                try: await self.refresh_capital(owner)
                except Exception:
                    try: self.capital.halt(owner, "Financial user accounting unavailable; entries blocked while owned risk is reconciled.")
                    except Exception: pass
                signer = RecoverySigner(key, owner, rules, D("50"), network=self.network)
                broker = TestnetBroker(ledger, gateway, signer, armed=True, policy=self.store.policy)
                result = await broker.reconcile(active["id"])
                await self.permissions(owner, gateway, revoke_only=True)
                return result
            if active:
                job_id = (active.get("audit_binding") or {}).get("user_intent_id")
                job = self.financial.get(owner, job_id)
                if not job or job["status"] != "claimed": raise ValueError("Unsent execution lacks its exact claimed financial consent.")
                if int(utcnow().timestamp()*1000) >= job["expires_ms"]:
                    ledger.update_trade(active["id"], "expired", "Unsent user financial consent expired.")
                    return ledger.trade(active["id"])
                if not self.enabled: return active
                execution = self.execution(owner, job_id, gateway, key, rules)
                try: return await execution.broker.dispatch(active["id"])
                finally: execution.ledger.engine.dispose()
            await self.permissions(owner, gateway)
            if not self.enabled: return None
            for job in self.financial.jobs(owner):
                if job["kind"] != "trade" or job["status"] != "signed" or int(utcnow().timestamp()*1000) >= job["expires_ms"]: continue
                execution = self.execution(owner, job["id"], gateway, key, rules)
                try:
                    trade = await execution.stage_offline()
                    return await execution.broker.dispatch(trade["id"])
                finally: execution.ledger.engine.dispose()
            return None
        finally: ledger.engine.dispose()

    async def refresh_capital(self, owner):
        from .fees import require_fresh
        state = await self.service.inspect(owner)
        require_fresh(state, owner, network=self.network)
        ref = self.capital.get(owner)
        end = state.get("exchange_time_ms")
        if not ref or type(end) is not int: raise ValueError("Existing capital history and exact timestamp required.")
        start = max(ref["baseline_ms"], ref["cursor_ms"] - 5000)
        receipts = await self.service.capital_history(owner, start, end)
        return self.capital.observe(owner, state, start, receipts, complete=True)

    def execution(self, owner, job_id, gateway, key, rules):
        return FinancialUserExecution(financial=self.financial, store=self.store, plans=self.financial.plans,
            capital=self.capital, service=self.service, owner=owner, intent_id=job_id, gateway=gateway,
            key=key, root=self.root, rules=rules, armed=self.armed)

    async def permissions(self, owner, gateway, revoke_only=False):
        jobs = self.financial.jobs(owner)
        uncertain = any(job["kind"] != "trade" and job["status"] in {"sending", "unknown"} for job in jobs)
        for job in jobs:
            if job["kind"] == "trade": continue
            if revoke_only and job["kind"] != "revoke_builder": continue
            if job["status"] == "signed" and int(utcnow().timestamp()*1000) < job["expires_ms"]:
                if not uncertain and (self.enabled or job["kind"] == "revoke_builder"):
                    await self.financial.submit_permission(owner, job["id"], gateway, armed=self.armed)
            elif job["status"] in {"sending", "unknown", "acknowledged"}:
                await self.financial.reconcile_permission(owner, job["id"], gateway)
