import asyncio
from copy import deepcopy
from decimal import Decimal as D

import pytest

from lobster.domain import utcnow
from lobster.execution.project import ProjectSettings, ProjectLedger, ProjectRunner
from lobster.execution.signer import TestnetSigner
from lobster.store import Episode, Store, digest
from conftest import FIXTURE_KEY


@pytest.fixture
def project(execution_rig, tmp_path):
    _, gateway, setup, _ = execution_rig
    store = Store(f"sqlite:///{tmp_path / 'review.db'}")
    with store.transaction() as session:
        row = session.get(Episode, setup.episode_id)
        item = deepcopy(row.payload)
        item["research"] = {"campaign_id": "a"*64, "strategy_hash": "b"*64, "signal_bar": 1, "max_holding_seconds": 3600}
        item["approval_hash"] = digest(item)
        row.payload = item
    signer = TestnetSigner(FIXTURE_KEY, gateway.account_address, gateway.rules)
    settings = ProjectSettings(_env_file=None, enabled=True, account=gateway.account_address, agent=signer.address,
        private_key=FIXTURE_KEY, capital_budget="1000", absolute_loss_budget="20", reserve_floor="100")
    ledger = ProjectLedger(f"sqlite:///{tmp_path / 'project.db'}", settings.account, settings.agent)
    class Service:
        broken = False
        taker = "0.00045"
        async def inspect(self, owner):
            if self.broken: raise ValueError("Offline accounting outage")
            return {"address": owner, "network": "testnet", "stale": False, "observed_at": utcnow().isoformat(),
                "exchange_time_ms": int(utcnow().timestamp()*1000), "equity": "1000", "withdrawable": "900",
                "positions": [{"quantity": str(gateway.position)}] if gateway.position else [],
                "open_orders": await gateway.open_orders(), "reported_taker_rate": self.taker}
        async def capital_history(self, *args): return []
    service = Service()
    async def info(kind, **fields):
        assert kind == "userAbstraction" and fields["user"] == settings.account
        return "disabled"
    gateway.info = info
    runner = ProjectRunner(store, settings, ledger, gateway, signer, service, armed=True)
    try: yield runner, gateway, setup, service
    finally:
        ledger.engine.dispose()
        store.engine.dispose()


def test_project_signal_dispatches_once_and_restarts_with_owned_partial_protection(project):
    runner, gateway, setup, _ = project
    async def run():
        first = await runner.tick()
        assert first["status"] == "protected"
        assert first["audit_binding"]["max_holding_seconds"] == 3600
        assert D(first["protected_quantity"]) == gateway.partial
        restored = ProjectRunner(runner.store, runner.settings, runner.ledger, gateway, runner.broker.signer, runner.service, armed=True)
        assert (await restored.tick())["status"] == "protected"
        assert sum(kind == "entry" for kind, _ in gateway.writes) == 1
    asyncio.run(run())


def test_capital_or_fee_budget_failure_prevents_any_financial_command(project):
    runner, gateway, _, service = project
    runner.settings.capital_budget = D("999")
    with pytest.raises(ValueError, match="budget"): asyncio.run(runner.tick())
    assert gateway.writes == []
    runner.settings.capital_budget = D("1000")
    service.taker = "0.00046"
    with pytest.raises(ValueError, match="fees"): asyncio.run(runner.tick())
    assert gateway.writes == []


def test_recovery_accounting_outage_does_not_disable_owned_risk_reduction(project):
    runner, gateway, _, service = project
    async def run():
        assert (await runner.tick())["status"] == "protected"
        service.broken = True
        result = await runner.tick()
        assert result["status"] == "emergency"
        assert gateway.position == 0 and runner.ledger.snapshot()["control"]["halt_reason"]
        assert (await runner.tick())["status"] == "closed"
        assert sum(kind == "entry" for kind, _ in gateway.writes) == 1
    asyncio.run(run())


def test_project_holding_limit_closes_owned_exposure_without_latching_loss_halt(project, monkeypatch):
    runner, gateway, _, _ = project
    async def run():
        first = await runner.tick()
        import lobster.execution.broker as module
        actual_now = module.now_ms
        monkeypatch.setattr(module, "now_ms", lambda: actual_now() + 3601000)
        result = await runner.tick()
        assert result["status"] == "closing" and gateway.position == 0
        assert not runner.ledger.snapshot()["control"]["halt_reason"]
    asyncio.run(run())


def test_default_and_unarmed_execution_never_dispatch(project):
    assert not ProjectSettings(_env_file=None).enabled
    with pytest.raises(ValueError): ProjectSettings(_env_file=None).require_armed()
    runner, gateway, _, _ = project
    runner.armed = runner.broker.armed = False
    assert asyncio.run(runner.tick()) is None and gateway.writes == []
