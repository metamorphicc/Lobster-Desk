"""Fully offline user lifecycle exercises, using public unfunded key vectors only."""
from decimal import Decimal as D
import json
from pathlib import Path

from eth_account import Account
from eth_account.messages import encode_typed_data
from pydantic import SecretStr

from ..agents import DemoReviewer
from ..domain import PitchInput, utcnow
from ..execution.contracts import fingerprint
from ..execution.simulation import SimulationGateway
from ..pipeline import Pipeline
from ..store import Store
from .capital import UserCapital
from .contracts import UserTestnetSettings
from .execution import UserExecution, LockedUserGateway
from .intents import ProfileInput, UserIntents
from .orders import UserPlans, illustrate

# Public Ethereum test vectors, NOT project/user credentials. NEVER FUND.
OWNER_KEY = "0x" + "0"*63 + "1"
AGENT_KEY = "0x" + "0"*63 + "2"
OWNER = Account.from_key(OWNER_KEY).address.lower()
AGENT = Account.from_key(AGENT_KEY).address.lower()
BUILDER = "0x" + "4"*40
SCENARIOS = ("partial-fill-stop-restart", "timeout-after-fill", "timeout-before-send", "stop-rejected", "revoked-after-leverage")


class SimulationService:
    def __init__(self, gateway):
        self.gateway = gateway
        self.settings = UserTestnetSettings(_env_file=None, builder_address=BUILDER, builder_fee_tenths_bps=20)
        self.approved = True

    async def inspect(self, address):
        account = await self.gateway.account()
        return {"network": "testnet", "address": address, "observed_at": utcnow().isoformat(), "stale": False,
            "exchange_time_ms": int(utcnow().timestamp()*1000), "equity": str(account.equity), "withdrawable": str(account.withdrawable),
            "reported_taker_rate": "0.00045", "positions": [] if not account.btc_size else [{"symbol": "BTC"}],
            "open_orders": await self.gateway.open_orders(), "builder_address": BUILDER, "builder_fee_tenths_bps": 20,
            "builder_approval_status": "approved" if self.approved else "not_approved"}

    async def capital_history(self, owner, start, end): return []


class UserSimulationGateway(SimulationGateway):
    async def info(self, kind, **fields):
        if kind == "userAbstraction" and fields.get("user") in {OWNER, BUILDER}: return "disabled"
        if kind == "clearinghouseState" and fields.get("user") == BUILDER:
            return {"time": int(utcnow().timestamp()*1000), "marginSummary": {"accountValue": "100"}}
        raise ValueError("The offline fixture does not support this observation.")


async def scenario(name: str, directory: Path):
    if name not in SCENARIOS: raise ValueError("Unknown offline rehearsal scenario.")
    directory.mkdir(parents=True, exist_ok=False)
    store = Store("sqlite:///" + (directory / "application.sqlite3").resolve().as_posix())
    opened = []
    try:
        gateway = UserSimulationGateway()
        gateway.account_address = OWNER
        service = SimulationService(gateway)
        episode = store.submit(PitchInput(author="Offline rehearsal", direction="long", entry="60000", stop="59400", target="61800",
            thesis="Synthetic fixture: exact consent, partial execution and recovery."), "offline-setup")
        pipeline = Pipeline(store, DemoReviewer())
        for _ in range(4): await pipeline.step((await gateway.market())[1])
        reviewed = store.get_episode(episode["id"])
        rules, market = await gateway.market()
        account = await service.inspect(OWNER)
        capital, plans, intents = UserCapital(store), UserPlans(store), UserIntents(store)
        capital.observe(OWNER, account, account["exchange_time_ms"], [], complete=True)
        plan = plans.save(OWNER, "offline-plan", illustrate(reviewed, OWNER, account, market, rules, store.policy))
        intents.configure(ProfileInput(address=OWNER, agent=AGENT, builder=BUILDER))
        intent = intents.prepare(OWNER, plan)
        signature = "0x" + Account.sign_message(encode_typed_data(full_message=intent["typed_data"]), OWNER_KEY).signature.hex()
        intents.verify_local(OWNER, intent["id"], signature)
        kwargs = dict(store=store, intents=intents, plans=plans, capital=capital, service=service, owner=OWNER,
            intent_id=intent["id"], gateway=gateway, key=SecretStr(AGENT_KEY), root=directory / "users", rules=rules)
        execution = UserExecution(**kwargs)
        opened.append(execution.ledger.engine)
        trade = await execution.stage_offline()
        if not isinstance(execution.broker.gateway, LockedUserGateway): raise ValueError("The production user writer is not locked.")
        # ONLY this standalone rehearsal replaces the locked writer. The object
        # is constructed here and has no client, endpoint or network capability.
        execution.broker.gateway = gateway
        execution.broker.armed = True
        if name.startswith("timeout-"): gateway.failures["entry"] = "after" if name == "timeout-after-fill" else "before"
        if name == "stop-rejected": gateway.failures["stop"] = "reject"
        if name == "revoked-after-leverage":
            original_send = gateway.send
            async def revoke(envelope):
                result = await original_send(envelope)
                if envelope["action"]["type"] == "updateLeverage": service.approved = False
                return result
            gateway.send = revoke
        blocked = False
        try: trade = await execution.broker.dispatch(trade["id"])
        except ValueError:
            if name != "revoked-after-leverage": raise
            blocked = True
        # Reopen a new ledger/broker context from the exact same persisted files.
        execution.ledger.engine.dispose()
        restarted = UserExecution(**kwargs)
        opened.append(restarted.ledger.engine)
        restarted.broker.gateway = gateway
        restarted.broker.armed = True
        trade = await restarted.broker.reconcile(trade["id"])
        protected = trade["status"] == "protected" and D(trade["protected_quantity"]) == abs(gateway.position)
        if name == "partial-fill-stop-restart":
            if not protected: raise ValueError("Synthetic partial fill was not protected.")
            stop = restarted.broker._protective(trade, abs(gateway.position), "stop")
            record = gateway.orders[stop.cloid]
            gateway.fill(record["order"], abs(gateway.position), stop.trigger_price)
            record["status"] = "filled"
            trade = await restarted.broker.reconcile(trade["id"])
        commands = restarted.ledger.commands(trade["id"])
        entry_attempts = sum(kind == "entry" for kind, _ in gateway.writes)
        state = restarted.ledger.snapshot()
        checks = {
            "audit_binding_preserved": trade["audit_binding"]["user_plan_hash"] == plan["plan_hash"],
            "no_duplicate_entry": entry_attempts <= 1,
            "expected_recovery": (trade["status"] == "closed" and not gateway.position and not await gateway.open_orders()) if name == "partial-fill-stop-restart" else
                protected if name == "timeout-after-fill" else
                (trade["status"] == "needs_reconciliation" and not gateway.position) if name == "timeout-before-send" else
                (bool(state["control"]["halt_reason"]) and not gateway.position) if name == "stop-rejected" else
                (blocked and entry_attempts == 0 and not gateway.position),
        }
        if not all(checks.values()): raise ValueError("Offline rehearsal invariants failed.")
        return {"scenario": name, "offline_fixture": True, "checks": checks, "final_status": trade["status"],
            "synthetic_entry_attempts": entry_attempts, "synthetic_position": str(gateway.position),
            "synthetic_fill_count": len(state["fills"]), "plan_hash": plan["plan_hash"], "intent_id": intent["id"],
            "trade_id": trade["id"], "audit_binding": trade["audit_binding"],
            "commands": [{"id": item["id"], "kind": item["kind"], "status": item["status"]} for item in commands],
            "production_user_writer_locked": True}
    finally:
        for engine in opened: engine.dispose()
        store.engine.dispose()


async def run_rehearsal(destination: Path):
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    results = [await scenario(name, destination / name) for name in SCENARIOS]
    report = {"schema": "lobster-offline-user-rehearsal-v1", "created_at": utcnow().isoformat(), "offline_fixture": True,
        "scenarios": results, "checks_passed": all(all(result["checks"].values()) for result in results),
        "exchange_writes_attempted": False, "wallet_provider_used": False, "funded_acceptance_verified": False,
        "execution_authorized": False, "note": "Synthetic balances, market, signatures, orders and fills using public unfunded vectors. No credentials, funding, wallet extension or HTTP exchange is involved. Not a trading-performance or acceptance report."}
    report["report_hash"] = fingerprint(report)
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
