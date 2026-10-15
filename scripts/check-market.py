"""Optional read-only smoke check against public Hyperliquid data."""
import asyncio
import httpx

from lobster.market import HyperliquidFeed


async def main():
    async with httpx.AsyncClient(timeout=15) as client:
        snapshot = await HyperliquidFeed(client).fetch()
        print(snapshot.model_dump_json(exclude={"candles"}))
        print(f"Validated {len(snapshot.candles)} candles; no signing credentials or orders used.")


if __name__ == "__main__":
    asyncio.run(main())

