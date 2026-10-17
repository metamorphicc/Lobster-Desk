"""Opt-in project runner: actual broker dispatch, never imported by FastAPI."""
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select

from ..domain import Capital, utcnow
from ..store import Account, Episode
from ..users.capital import UserCapital
from ..users.contracts import Address, UserTestnetSettings
from ..users.fees import require_fresh
from ..users.service import UserTestnetService
from .broker import TestnetBroker
from .contracts import ReviewedSetup, fingerprint
from .gateway import HyperliquidMainnet, HyperliquidTestnet
from .ledger import ExecutionLedger
from .signer import MainnetSigner, TestnetSigner

TERMINAL = {"closed", "rejected", "expired", "cancelled"}


class ProjectSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.execution", env_prefix="PROJECT_", extra="ignore", hide_input_in_errors=True)
    network: Literal["testnet", "mainnet"] = "testnet"
    enabled: bool = False
    account: Address | None = None
    agent: Address | None = None
    private_key: SecretStr | None = None
    database_url: str = "sqlite:///data/project-testnet.sqlite3"
    capital_budget: D | None = Field(default=None, gt=0, le=100000, allow_inf_nan=False)
    absolute_loss_budget: D | None = Field(default=None, gt=0, allow_inf_nan=False)
    reserve_floor: D | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_entry_notional: D = Field(default=D("50"), ge=10, le=50, allow_inf_nan=False)
    treasury_path: Path | None = None

    @model_validator(mode="after")
    def budgets(self):
        if self.capital_budget is not None:
            if self.absolute_loss_budget is not None and self.absolute_loss_budget > self.capital_budget * D("0.05"):
                raise ValueError("Absolute loss cannot exceed 5% of the capital budget.")
            if self.reserve_floor is not None and self.reserve_floor > self.capital_budget:
                raise ValueError("Reserve exceeds capital budget.")
        if self.account is not None and self.account == self.agent: raise ValueError("Dedicated API wallet required.")
        return self

    def require_armed(self):
        if not self.enabled or any(getattr(self, key) is None for key in ("account", "agent", "private_key", "capital_budget", "absolute_loss_budget", "reserve_floor")):
            raise ValueError("Project execution requires explicit enablement, separate API wallet and all capital/loss/reserve limits.")


class ProjectLedger(ExecutionLedger):
    def observe_capital(self, account, policy):
        if account.network != self.network or account.address.lower() != self.owner: raise ValueError("Wrong project account/network.")
        reference = self.capital.get(self.owner)
        if not reference: raise ValueError("Project loss references required.")
        flows = D(reference["cashflows"])
        return Capital(equity=account.equity, available_cash=max(D(0), account.withdrawable - self.reserve_floor),
            day_start_equity=max(D(0), D(reference["day_reference"]) + flows),
            high_water_equity=max(D(0), D(reference["high_water"]) + flows),
            paused=bool(reference["stale"] or reference["halt_reason"] or self.snapshot()["control"]["halt_reason"]),
            occupied=bool(account.btc_size or account.other_positions or account.open_order_count))


class ProjectRunner:
    def __init__(self, store, settings, ledger, gateway, signer, service, *, armed=False):
        from ..ops.catalog import register_journal
        register_journal(store, ledger, "project")
        self.store, self.settings, self.ledger, self.gateway, self.service = store, settings, ledger, gateway, service
        self.armed = armed
        ledger.owner, ledger.reserve_floor = settings.account, settings.reserve_floor
        adapter = SimpleNamespace(engine=ledger.engine, policy=store.policy, transaction=ledger.transaction)
        self.capital = ledger.capital = UserCapital(adapter, network=settings.network)
        self.broker = TestnetBroker(ledger, gateway, signer, armed=armed, policy=store.policy, entry_guard=self.entry_guard)

    async def observe(self):
        state = await self.service.inspect(self.settings.account)
        require_fresh(state, self.settings.account, network=self.settings.network)
        reference = self.capital.get(self.settings.account)
        end = state.get("exchange_time_ms")
        if type(end) is not int: raise ValueError("Exact exchange time required.")
        start = max(reference["baseline_ms"], reference["cursor_ms"] - 5000) if reference else end
        try:
            history = await self.service.capital_history(self.settings.account, start, end) if reference else []
            reference = self.capital.observe(self.settings.account, state, start, history, complete=True)
        except ValueError:
            self.capital.halt(self.settings.account, "Project accounting requires reconciliation; no new entry permitted.")
            raise
        return state, reference

    async def entry_guard(self, account):
        self.settings.require_armed()
        if not self.armed: raise ValueError("Project runner is not armed.")
        if await self.gateway.info("userAbstraction", user=self.settings.account) != "disabled":
            raise ValueError("Project execution supports explicitly observed standard accounts only.")
        state, reference = await self.observe()
        if D(state["reported_taker_rate"]) > self.store.policy.fee_rate:
            raise ValueError("Observed exchange fees exceed the coded risk cost assumption.")
        if (state["positions"] or state["open_orders"] or D(state["equity"]) != account.equity
                or D(state["withdrawable"]) != account.withdrawable): raise ValueError("Project observations disagree or account is occupied.")
        initial, performance = D(reference["initial_equity"]), D(reference["performance_balance"])
        if initial > self.settings.capital_budget or initial + D(reference["cashflows"]) > self.settings.capital_budget:
            raise ValueError("Project account exceeds the explicit capital budget; use a dedicated small account.")
        if initial - performance >= self.settings.absolute_loss_budget or account.equity <= self.settings.reserve_floor or reference["halt_reason"]:
            self.ledger.halt("Project absolute loss, reserve or observed risk limit reached.")
            raise ValueError("Project capital limit reached.")
        with self.store.transaction() as session:
            app = session.get(Account, 1).payload
            if app["paused"] or app["halt_reason"]: raise ValueError("Application entry pause/halt is active.")
            expected = "hyperliquid" if self.settings.network == "mainnet" else "hyperliquid-testnet"
            if app.get("market_source") not in {None, expected}: raise ValueError("Application source differs from project network.")

    async def tick(self):
        # Recovery always runs before admission and does not depend on an entry
        # permission service being available. Never send a second uncertain entry.
        for trade in self.ledger.snapshot()["trades"]:
            if trade["status"] not in TERMINAL:
                if trade["status"] == "staged" and not self.ledger.commands(trade["id"]):
                    if not self.armed: return trade
                    try: return await self.broker.dispatch(trade["id"])
                    except ValueError:
                        if utcnow() >= datetime.fromisoformat(trade["setup"]["expires_at"]):
                            self.ledger.update_trade(trade["id"], "expired", "Unsent project approval expired.")
                        raise
                try: await self.observe()
                except Exception:
                    # Accounting outages must not disable stop installation or
                    # risk reduction. Latch entry halt, then reconcile owned risk.
                    self.ledger.halt("Project accounting unavailable during recovery.")
                return await self.broker.reconcile(trade["id"])
        if not self.armed: return None
        state, reference = await self.observe()
        with self.store.transaction() as session:
            candidates = [row.payload for row in session.scalars(select(Episode).where(
                Episode.payload["status"].as_string().in_(("approved", "filled"))).order_by(Episode.payload["created_at"].as_string()))
                if row.payload.get("research")]
        seen = {trade["id"] for trade in self.ledger.snapshot()["trades"]}
        for episode in candidates:
            if episode["id"] in seen or utcnow() >= datetime.fromisoformat(episode["expires_at"]): continue
            setup = ReviewedSetup.from_episode(episode, self.store.policy, network=self.settings.network)
            origin = episode["research"]
            await self.broker.stage(setup, audit_binding={"origin": "autonomous-project",
                "campaign_id": origin["campaign_id"], "strategy_hash": origin["strategy_hash"],
                "max_holding_seconds": origin["max_holding_seconds"]})
            return await self.broker.dispatch(setup.episode_id)
        return None


async def create_runner(store, settings, client, *, armed=False):
    from .settings import require_separate_database
    require_separate_database(str(store.engine.url), settings.database_url)
    if armed: settings.require_armed()
    if not settings.account or not settings.agent or not settings.private_key: raise ValueError("Project account and API wallet are not configured.")
    gateway_type = HyperliquidMainnet if settings.network == "mainnet" else HyperliquidTestnet
    signer_type = MainnetSigner if settings.network == "mainnet" else TestnetSigner
    gateway = gateway_type(client, settings.account)
    rules, _ = await gateway.market()
    signer = signer_type(settings.private_key, settings.account, rules, settings.max_entry_notional)
    if signer.address.lower() != settings.agent: raise ValueError("Configured project API wallet differs from its key.")
    ledger = ProjectLedger(settings.database_url, settings.account, settings.agent, network=settings.network)
    service = UserTestnetService(UserTestnetSettings(_env_file=None), client, network=settings.network)
    try: return ProjectRunner(store, settings, ledger, gateway, signer, service, armed=armed)
    except Exception:
        ledger.engine.dispose()
        raise
