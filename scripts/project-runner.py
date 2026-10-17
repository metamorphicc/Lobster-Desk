"""Separate owner-run project trader. Default is configuration inspection only."""
import argparse
import asyncio
import json
from pathlib import Path

import httpx
from sqlalchemy.engine import make_url

from lobster.config import Settings
from lobster.execution.lease import RunnerLease
from lobster.execution.project import ProjectSettings, create_runner
from lobster.economics.book import TreasuryBook
from lobster.economics.ingestion import sync_project_settlement
from lobster.store import Store


async def main(args):
    config = ProjectSettings()
    if not args.run:
        print(json.dumps({"network": config.network, "configured": bool(config.account and config.agent),
            "enabled": config.enabled, "dispatch_attempted": False, "note": "--run --arm is required for actual exchange execution."}))
        return
    if not args.arm: raise ValueError("Explicit arming required")
    config.require_armed()
    source = Settings()
    expected = "hyperliquid" if config.network == "mainnet" else "hyperliquid-testnet"
    if source.market_source != expected: raise ValueError("Application data and execution network must agree")
    path = make_url(config.database_url)
    if not path.drivername.startswith("sqlite") or not path.database or path.database == ":memory:": raise ValueError("File-backed single-host journal required")
    with RunnerLease(Path(path.database + ".runner.lock"), "project execution"):
        store = Store(source.database_url, source.initial_capital)
        runner = None
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                runner = await create_runner(store, config, client, armed=True)
                while True:
                    try:
                        result = await runner.tick()
                        print(json.dumps({"network": config.network, "trade_id": result["id"] if result else None,
                            "status": result["status"] if result else "idle"}))
                        if config.network == "mainnet" and config.treasury_path:
                            try:
                                settlement = await sync_project_settlement(TreasuryBook(config.treasury_path), runner)
                                print(json.dumps({"settlement": settlement}))
                            except Exception:
                                print("Treasury settlement awaits flat-account reconciliation. No treasury transfer attempted.")
                    except Exception:
                        print("Project tick requires reconciliation or a fresh eligible signal. No uncertain entry is replayed.")
                    if args.once: break
                    await asyncio.sleep(5)
        finally:
            if runner: runner.ledger.engine.dispose()
            store.engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--arm", action="store_true")
    parser.add_argument("--once", action="store_true")
    try: asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt: print("Project runner stopped. Check any exchange exposure and native protection.")
    except Exception: parser.exit(1, "Project runner refused startup. Check network, separate keys/journal, explicit enablement and capital limits. No credentials were printed.\n")
