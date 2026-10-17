"""Separate user testnet execution. Default is configuration inspection only."""
import argparse
import asyncio
from contextlib import ExitStack
import json
from pathlib import Path

import httpx

from lobster.config import Settings
from lobster.execution.gateway import HyperliquidTestnet, HyperliquidMainnet
from lobster.execution.lease import RunnerLease
from lobster.store import Store
from lobster.users.capital import UserCapital
from lobster.users.contracts import UserTestnetSettings, UserMainnetSettings
from lobster.users.financial import UserFinancial
from lobster.users.intents import UserIntents
from lobster.users.orders import UserPlans
from lobster.users.runner import UserRunnerSettings, UserFinancialRunner
from lobster.users.service import UserTestnetService
from lobster.ops.heartbeat import ping


async def main(args):
    settings = UserRunnerSettings(_env_file=args.config)
    if not args.run:
        print(json.dumps({"network": settings.network, "enabled": settings.enabled, "keys_configured": bool(settings.keys()),
            "dispatch_attempted": False, "note": "--run --arm required. Dedicated API keys are loaded only by this separate process."})); return
    if not args.arm or not settings.enabled: raise ValueError("Explicit user runner enablement/arming required.")
    network = settings.network
    config, user_config = Settings(), (UserTestnetSettings() if network == "testnet" else UserMainnetSettings())
    gateway_type = HyperliquidTestnet if network == "testnet" else HyperliquidMainnet
    keys = settings.keys()
    if not keys or not user_config.builder_address: raise ValueError("Registered user API keys and builder required.")
    enabled = user_config.financial_enabled and config.market_source == ("hyperliquid-testnet" if network == "testnet" else "hyperliquid")
    store = Store(config.database_url, config.initial_capital)
    try:
        financial = UserFinancial(store, UserIntents(store, network=network), UserPlans(store, network=network))
        with ExitStack() as leases:
            for owner in keys:
                profile = financial.intents.profile(owner)
                if not profile: raise ValueError("Register every public user profile before starting this key map.")
                leases.enter_context(RunnerLease(Path(user_config.execution_root).resolve() / owner / (profile["agent"] + ".runner.lock"), "user financial execution"))
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                service = UserTestnetService(user_config, client, network=network)
                runner = UserFinancialRunner(store=store, financial=financial, capital=UserCapital(store, network=network, namespaced=network == "mainnet"), service=service,
                    root=user_config.execution_root, enabled=enabled, armed=True)
                while True:
                    for owner, key in keys.items():
                        try:
                            result = await runner.tick(owner, key, gateway_type(client, owner))
                            profile = financial.intents.profile(owner)
                            ping(runner.root / owner / (profile["agent"] + ".sqlite3"), "user", state=result["status"] if result else "idle")
                            print(json.dumps({"owner": owner, "trade_id": result["id"] if result else None, "status": result["status"] if result else "idle"}))
                        except Exception:
                            print(json.dumps({"owner": owner, "status": "requires_reconciliation", "note": "No uncertain command is replayed. Other user journals continue independently."}))
                    if args.once: break
                    await asyncio.sleep(2)
    finally: store.engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--arm", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--config", default=".env.users", help="Separate ignored runner settings file; mainnet uses .env.users-mainnet.")
    try: asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt: print("User runner stopped. Verify exchange exposure and native protection.")
    except Exception: parser.exit(1, "User runner refused startup. Check registered profiles, separate journals, key map and explicit arming. Keys were not printed.\n")
