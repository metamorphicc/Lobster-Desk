"""Observe actual received mainnet builder claims. No key, signing or reward claiming."""
import argparse
import asyncio
import json
from pathlib import Path

import httpx

from lobster.economics.book import TreasuryBook
from lobster.economics.revenue_watcher import RevenueSettings, RevenueWatcher
from lobster.execution.lease import RunnerLease


async def main(args):
    settings = RevenueSettings()
    if not args.run:
        print(json.dumps({"network": "mainnet", "enabled": settings.enabled,
            "configured": bool(settings.builder and settings.baseline_ms is not None),
            "network_request_attempted": False, "financial_write_attempted": False,
            "note": "--run reads actual received claims into the local receipt book. It cannot claim rewards or transfer funds."})); return
    if not settings.enabled: raise ValueError("Revenue observation is disabled.")
    with RunnerLease(Path(str(settings.book.resolve()) + ".revenue.lock"), "received builder revenue observer"):
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            watcher = RevenueWatcher(TreasuryBook(settings.book), settings, client)
            try:
                while True:
                    try:
                        result = await watcher.tick()
                        print(json.dumps({"imported_count": len(result["imported_receipts"]), "cursor_ms": result["cursor_ms"],
                            "caught_up": result["caught_up"], "transfers_attempted": False}))
                    except Exception:
                        print(json.dumps({"status": "observation_unavailable", "transfers_attempted": False,
                            "note": "Receipt cursor did not advance on failure. Review source attribution and complete history."}))
                        if args.once: raise
                    if args.once: break
                    await asyncio.sleep(settings.poll_seconds)
            finally: watcher.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--once", action="store_true")
    try: asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt: print("Received-revenue observation stopped. No financial authority was held.")
    except Exception: parser.exit(1, "Revenue observer refused startup or could not reconcile the observation. Credentials were not printed.\n")
