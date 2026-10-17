"""Separate owner-run charity process. No HTTP or payment in default config mode."""
import argparse
import asyncio
from decimal import Decimal as D
import json
from pathlib import Path

import httpx

from lobster.economics.book import TreasuryBook
from lobster.economics.charity import CharitySettings, GivingBlock, EthereumUsdc, CharityPayments, RECIPIENTS, public_charity_report
from lobster.execution.lease import RunnerLease
from lobster.ops.heartbeat import ping


def public(row):
    return {k: row.get(k) for k in ("id", "status", "amount", "pledge_id", "signature", "provider_status")}


async def main(args):
    settings = CharitySettings()
    if not any((args.directory, args.prepare, args.dispatch, args.reconcile, args.cancel, args.run, args.status)):
        print(json.dumps({"provider": "The Giving Block", "network": "ethereum", "currency": "USDC (ERC-20)",
            "enabled": settings.enabled, "configured": bool(settings.owner and settings.tgb_login and settings.tgb_password),
            "recipients": RECIPIENTS, "payment_attempted": False})); return
    if args.dispatch or args.run:
        if not args.arm: raise ValueError("Explicit charity arming required.")
        settings.require_armed()
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        provider = GivingBlock(client, settings.tgb_login, settings.tgb_password)
        if args.directory:
            print(json.dumps({key: await provider.recipient(key) for key in RECIPIENTS})); return
        with RunnerLease(Path(str(settings.book.resolve()) + ".charity.lock"), "charity payments"):
            book = TreasuryBook(settings.book)
            payments = CharityPayments(book, settings, provider, EthereumUsdc(client), armed=args.arm)
            if args.status: print(json.dumps(public_charity_report(book))); return
            if args.prepare:
                print(json.dumps(public(await payments.prepare(args.recipient, D(args.prepare))))); return
            if args.dispatch: print(json.dumps(public(await payments.dispatch(args.dispatch)))); return
            if args.reconcile: print(json.dumps(public(await payments.reconcile(args.reconcile)))); return
            if args.cancel: print(json.dumps(public(payments.cancel_unsent(args.cancel)))); return
            while True:
                try:
                    rows = payments.list()
                    active = next((r for r in rows if r["status"] not in {"finalized", "failed", "cancelled"}), None)
                    if active:
                        if active["status"] == "prepared": print(json.dumps(public(await payments.dispatch(active["id"]))))
                        else: print(json.dumps(public(await payments.reconcile(active["id"]))))
                    else:
                        # Equal cumulative target for the two selected causes.
                        totals = {key: sum((D(r["amount"]) for r in rows if r["recipient"]["key"] == key and r["status"] == "finalized"), D(0)) for key in RECIPIENTS}
                        recipient = min(totals, key=totals.get)
                        print(json.dumps(public(await payments.prepare(recipient, settings.batch_usdc))))
                    for row in rows:
                        if row["status"] == "finalized" and row.get("provider_status") != "record_observed": await payments.reconcile(row["id"])
                    ping(settings.book, "charity", state="active")
                except Exception:
                    ping(settings.book, "charity", ok=False, state="unavailable")
                    print("Charity cycle awaits earmarks, provider/network support, wallet funding or reconciliation. No uncertain payment is repeated.")
                if args.once: break
                await asyncio.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--directory", action="store_true")
    actions.add_argument("--prepare", help="Create a provider pledge for an exact USDC amount; no transfer")
    actions.add_argument("--dispatch")
    actions.add_argument("--reconcile")
    actions.add_argument("--cancel")
    actions.add_argument("--status", action="store_true")
    actions.add_argument("--run", action="store_true")
    parser.add_argument("--recipient", choices=list(RECIPIENTS), default="children")
    parser.add_argument("--arm", action="store_true")
    parser.add_argument("--once", action="store_true")
    try: asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt: print("Charity process stopped. Reconcile any existing transaction before restarting payments.")
    except Exception: parser.exit(1, "Charity operation refused. Check provider credentials/directory, earmarks/reserves, dedicated Ethereum wallet and payment state. Credentials were not printed.\n")
