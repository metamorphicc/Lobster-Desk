"""Capture unsigned testnet observations. Does not import or instantiate a signer."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from lobster.config import Settings
from lobster.domain import utcnow
from lobster.execution.evidence import collect_evidence
from lobster.execution.settings import TestnetSettings
from lobster.execution.workbench import TestnetWorkbench


async def capture(output: Path):
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        workbench = TestnetWorkbench(TestnetSettings(), client, Settings().database_url)
        try:
            report = await collect_evidence(workbench)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as file:
                json.dump(report, file, indent=2)
                file.write("\n")
            print(f"Read-only evidence saved: {output.resolve()}")
            print("Funded acceptance: UNVERIFIED. Review the pending cases; no exchange write was attempted.")
        finally:
            if workbench.ledger:
                workbench.ledger.engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts") / f"testnet-evidence-{utcnow().strftime('%Y%m%dT%H%M%S')}.json")
    args = parser.parse_args()
    try:
        asyncio.run(capture(args.output))
    except FileExistsError:
        parser.exit(1, "Evidence file already exists. Choose a new output path to preserve the previous capture.\n")
    except Exception:
        parser.exit(1, "Evidence capture could not complete. Check public settings, connectivity and output permissions.\n")
