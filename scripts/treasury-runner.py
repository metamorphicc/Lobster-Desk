"""Owner-run Solana treasury. Default inspects configuration without networking."""
import argparse
import asyncio
from decimal import Decimal as D
import json
from pathlib import Path

import httpx

from lobster.economics.book import TreasuryBook
from lobster.economics.distribution import distribution
from lobster.economics.solana_treasury import SolanaSettings, create_treasury
from lobster.execution.lease import RunnerLease
from lobster.domain import utcnow
from lobster.ops.heartbeat import ping


def public(row):
    return {key: row.get(key) for key in ("id", "status", "signature", "finalized_slot", "evidence_hash")}


async def main(args):
    settings = SolanaSettings()
    if not any((args.buyback, args.burn, args.dispatch, args.reconcile, args.run, args.status)):
        print(json.dumps({"network": "solana-mainnet", "enabled": settings.enabled,
            "configured": bool(settings.owner and settings.mint), "financial_write_attempted": False,
            "note": "Mint, dedicated funded wallet, reserves and explicit --arm are required for dispatch."}))
        return
    if args.dispatch or args.run:
        if not args.arm: raise ValueError("Explicit treasury arming required.")
        settings.require_armed()
    with RunnerLease(Path(str(settings.book.resolve()) + ".solana.lock"), "Solana treasury"):
        book = TreasuryBook(settings.book)
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            treasury = create_treasury(book, settings, client, armed=args.arm)
            if args.status:
                print(json.dumps({"operations": [public(row) for row in treasury.operations.list()], "lots": treasury.operations.lots()})); return
            if args.buyback:
                print(json.dumps(public(await treasury.prepare_buyback(D(args.buyback))))); return
            if args.burn:
                print(json.dumps(public(await treasury.prepare_burn(args.burn)))); return
            if args.dispatch:
                print(json.dumps(public(await treasury.dispatch(args.dispatch)))); return
            if args.reconcile:
                print(json.dumps(public(await treasury.reconcile(args.reconcile)))); return
            while True:
                try:
                    active = next((row for row in treasury.operations.list() if row["status"] not in {"finalized", "failed", "cancelled"}), None)
                    if active:
                        if active["status"] == "prepared" and active["plan"]["expires_ms"] <= int(utcnow().timestamp()*1000):
                            treasury.operations.cancel(active["id"])
                        else: print(json.dumps(public(await treasury.dispatch(active["id"]))))
                    else:
                        lot = next((lot for lot in treasury.operations.lots() if int(lot["quantity"]) > int(lot["burned"])), None)
                        if lot:
                            print(json.dumps(public(await treasury.prepare_burn(lot["id"]))))
                        else:
                            report = distribution(book, settings.policy())
                            budget = report["reserve_bounded_buyback_budget"]
                            if budget is not None and D(budget) >= 5:
                                print(json.dumps(public(await treasury.prepare_buyback(min(D(budget), settings.max_buyback_usdc)))))
                    ping(settings.book, "solana", state="active")
                except Exception:
                    ping(settings.book, "solana", ok=False, state="unavailable")
                    print("Treasury cycle awaits configuration, liquidity, funding or reconciliation. No uncertain transaction is rebuilt.")
                if args.once: break
                await asyncio.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--buyback", help="Prepare an exact USDC purchase; no financial submission")
    actions.add_argument("--burn", help="Prepare a burn of a finalized purchase ID; no submission")
    actions.add_argument("--dispatch", help="Submit one prepared operation, or reconcile its existing signature")
    actions.add_argument("--reconcile", help="Read finalized evidence for an existing operation")
    actions.add_argument("--status", action="store_true")
    actions.add_argument("--run", action="store_true", help="Opt-in bounded buyback then burn loop")
    parser.add_argument("--arm", action="store_true")
    parser.add_argument("--once", action="store_true")
    try: asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt: print("Treasury stopped; unresolved signatures remain reserved for reconciliation.")
    except Exception: parser.exit(1, "Treasury refused the operation. Check mint/wallet, exact budgets, Solana funding and durable operation status. Credentials were not printed.\n")
