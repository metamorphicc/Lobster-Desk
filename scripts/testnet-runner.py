"""Owner-operated testnet signer; never started by npm run dev or FastAPI."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from sqlalchemy.engine import make_url

from lobster.config import Settings
from lobster.execution.broker import TestnetBroker
from lobster.execution.gateway import HyperliquidTestnet
from lobster.execution.lease import RunnerLease
from lobster.execution.ledger import ExecutionLedger
from lobster.execution.settings import SignerSettings, TestnetSettings, require_separate_database
from lobster.execution.signer import TestnetSigner
from lobster.execution.workbench import TestnetWorkbench
from lobster.ops.catalog import register_journal
from lobster.store import Store


async def main(args):
    public = TestnetSettings()
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        if not args.dispatch and not args.reconcile:
            report = await TestnetWorkbench(public, client, Settings().database_url).inspect()
            print(json.dumps(report, indent=2))
            return
        if not args.trade:
            raise ValueError("Supply --trade with an intent staged through the operator workbench.")
        private = SignerSettings()
        if not private.private_key or not private.enabled:
            raise ValueError("The owner must configure and explicitly enable the separate testnet signer locally.")
        if not public.account_address or not public.api_wallet_address:
            raise ValueError("Configure public testnet account and API wallet addresses first.")
        require_separate_database(Settings().database_url, public.database_url)
        gateway = HyperliquidTestnet(client, public.account_address)
        rules, _ = await gateway.market()
        signer = TestnetSigner(private.private_key, public.account_address, rules, public.max_entry_notional)
        if signer.address.lower() != public.api_wallet_address.lower():
            raise ValueError("The private API wallet key does not match the configured public API wallet address.")
        url = make_url(public.database_url)
        lease = Path(url.database + ".runner.lock") if url.drivername.startswith("sqlite") and url.database else Path("data/testnet.runner.lock")
        with RunnerLease(lease):
            ledger = ExecutionLedger(public.database_url, public.account_address, signer.address)
            application = Store(Settings().database_url)
            try:
                register_journal(application, ledger, "testnet")
                broker = TestnetBroker(ledger, gateway, signer, armed=True)
                result = await (broker.dispatch(args.trade) if args.dispatch else broker.reconcile(args.trade))
                print(json.dumps(result, indent=2))
                while args.watch and result["status"] not in {"closed", "rejected", "expired", "cancelled"}:
                    await asyncio.sleep(5)
                    try:
                        result = await broker.reconcile(args.trade)
                        print(json.dumps({"trade": result["id"], "status": result["status"], "reason": result["reason"]}))
                    except Exception:
                        print("Reconciliation observation failed; no entry replayed. Retrying observations in five seconds.")
            finally:
                ledger.engine.dispose()
                application.engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lobster Desk testnet-only inspection and owner signer")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--dispatch", action="store_true", help="Submit one locally staged testnet intent; requires separate local signer enablement")
    actions.add_argument("--reconcile", action="store_true", help="Reconcile an intent, install protection or reduce owned risk; never open a new position")
    parser.add_argument("--trade", help="Staged testnet intent ID")
    parser.add_argument("--watch", action="store_true", help="Continue reconciliation every five seconds until the intent is terminal")
    parsed = parser.parse_args()
    try:
        asyncio.run(main(parsed))
    except KeyboardInterrupt:
        print("Testnet monitor stopped. Check the exchange for open positions and protective orders.")
    except Exception:
        # SDK/configuration exceptions may contain input material. Never echo them.
        parser.exit(1, "Testnet runner stopped. Check local settings, API-wallet approval and connectivity. "
                    "No automatic entry retry was made. Inspect the exchange before taking further action.\n")
