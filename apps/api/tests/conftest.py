"""Execution fixtures use an in-memory exchange and a public, unfunded test key."""

import asyncio

from pydantic import SecretStr
import pytest

from lobster.agents import DemoReviewer
from lobster.domain import PitchInput
from lobster.execution.broker import TestnetBroker
from lobster.execution.contracts import ReviewedSetup
from lobster.execution.ledger import ExecutionLedger
from lobster.execution.signer import TestnetSigner
from lobster.execution.simulation import SimulationGateway as FakeTestnet
from lobster.pipeline import Pipeline
from lobster.store import Store

FIXTURE_KEY = SecretStr("0x" + "0" * 63 + "1")  # Public test vector. NEVER fund.
FIXTURE_ADDRESS = "0x" + "2" * 40


@pytest.fixture
def execution_rig(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'review.db'}")
    episode = store.submit(PitchInput(author="QA trader", direction="long", entry="60000", stop="59400", target="61800",
                         thesis="A defined BTC breakout for offline lifecycle tests."), "request-123")
    exchange = FakeTestnet()
    async def review():
        pipeline = Pipeline(store, DemoReviewer())
        for _ in range(4):
            await pipeline.step((await exchange.market())[1])
    # Windows asyncio.run creates a TCP socketpair. One lifecycle per review
    # avoids exhausting ephemeral sockets during repeated full-suite runs.
    asyncio.run(review())
    setup = ReviewedSetup.from_episode(store.get_episode(episode["id"]), store.policy)
    signer = TestnetSigner(FIXTURE_KEY, FIXTURE_ADDRESS, exchange.rules)
    url = f"sqlite:///{tmp_path / 'execution.db'}"
    ledger = ExecutionLedger(url, FIXTURE_ADDRESS, signer.address)
    broker = TestnetBroker(ledger, exchange, signer, armed=True)
    try:
        yield broker, exchange, setup, url
    finally:
        ledger.engine.dispose()
        store.engine.dispose()

