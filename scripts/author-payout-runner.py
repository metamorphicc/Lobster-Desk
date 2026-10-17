"""Separate bounded author-payment process; default inspects config without HTTP."""
import argparse
import asyncio
import json
from pathlib import Path

import httpx

from lobster.config import Settings
from lobster.economics.author_payouts import AuthorPayoutSettings, AuthorPayouts, TERMINAL
from lobster.economics.book import TreasuryBook
from lobster.execution.lease import RunnerLease
from lobster.ops.heartbeat import ping
from lobster.store import Store


async def main(args):
    settings = AuthorPayoutSettings()
    if not args.run:
        print(json.dumps({"network": "mainnet", "enabled": settings.enabled,
            "account_configured": bool(settings.account), "key_configured": bool(settings.private_key),
            "financial_write_attempted": False, "note": "--run --arm, explicit reserves and a registered dedicated project source are required."})); return
    if not args.arm: raise ValueError("Explicit author payout arming is required.")
    settings.require_armed()
    config = Settings()
    if settings.book.resolve() != Path(config.treasury_path).resolve(): raise ValueError("Author payout and API books must match.")
    with RunnerLease(Path(str(settings.book.resolve())+".author-payouts.lock"), "author payouts"):
        store = Store(config.database_url, config.initial_capital)
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                payments = AuthorPayouts(store, TreasuryBook(settings.book), settings, client, armed=True)
                while True:
                    try:
                        active = next((job for job in payments.jobs() if job["status"] not in TERMINAL), None)
                        job = await payments.dispatch(active["id"]) if active else await payments.prepare()
                        state = job["status"] if job else "idle"
                        ping(settings.book, "author_payouts", state=state, ok=state not in {"sending", "unknown"})
                        print(json.dumps({"id": job["id"] if job else None, "status": state, "network": "mainnet"}))
                    except Exception:
                        ping(settings.book, "author_payouts", ok=False, state="requires_reconciliation")
                        print("Author payout awaits verified earnings, flat source, reserves or reconciliation. No uncertain payment is repeated.")
                        if args.once: raise
                    if args.once: break
                    await asyncio.sleep(5)
        finally: store.engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--arm", action="store_true")
    parser.add_argument("--once", action="store_true")
    try: asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt: print("Author payouts stopped; reconcile unresolved commands before resuming.")
    except Exception: parser.exit(1, "Author payout process refused the operation. Check the dedicated source/key, shared book, exact earnings and reserves. Credentials were not printed.\n")
