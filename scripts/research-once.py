"""Run one isolated paper research cohort. Default: synthetic data, no model API."""
import argparse
import asyncio
import json
from pathlib import Path

import httpx

from lobster.config import Settings
from lobster.research.data import HistoryFeed
from lobster.research.providers import AnthropicResearcher, DemoResearcher
from lobster.research.service import Research
from lobster.store import Store


async def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    settings = Settings(database_url="sqlite:///" + str((args.output / "paper.sqlite3").resolve()),
        market_source=args.source, agent_provider=args.provider, research_enabled=True)
    store = Store(settings.database_url)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            dataset = await HistoryFeed(client, args.source, settings.research_history_bars).fetch()
            provider = DemoResearcher() if args.provider == "demo" else AnthropicResearcher(client, settings)
            research = Research(store, settings)
            identifier = await research.run(dataset, provider)
            report = research.get(identifier)
            with (args.output / "report.json").open("x", encoding="utf-8") as output:
                json.dump(report, output, indent=2)
            print(f"Research recorded: {report['status']}. Paper only; no exchange orders, payouts or token operations.")
            if report["status"] == "failed": raise ValueError("Research failed")
    finally:
        store.engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", choices=["demo", "hyperliquid", "hyperliquid-testnet"], default="demo")
    parser.add_argument("--provider", choices=["demo", "anthropic"], default="demo")
    args = parser.parse_args()
    try: asyncio.run(run(args))
    except Exception:
        parser.exit(1, "Research unavailable. Check a new output directory, complete history and configured provider access. No exchange write was attempted.\n")
