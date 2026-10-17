"""Read actual mainnet claim history into the receipt book. Never claims/transfers rewards."""
import argparse
import asyncio
import json
from pathlib import Path

import httpx
from pydantic import TypeAdapter

from lobster.economics.book import TreasuryBook
from lobster.economics.ingestion import RevenueImporter
from lobster.users.contracts import Address


async def main(args):
    builder = TypeAdapter(Address).validate_python(args.builder)
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        result = await RevenueImporter(TreasuryBook(args.book), client, builder).sync_builder(args.start_ms, args.end_ms)
        print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--builder", required=True)
    parser.add_argument("--start-ms", type=int, required=True)
    parser.add_argument("--end-ms", type=int, required=True)
    parser.add_argument("--book", type=Path, default=Path("data/treasury.sqlite3"))
    try: asyncio.run(main(parser.parse_args()))
    except Exception: parser.exit(1, "Builder revenue ingestion failed. Check dedicated-builder attribution, exact receipts and complete time coverage. No financial write was attempted.\n")
