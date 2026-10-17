import asyncio
from datetime import datetime, timezone
import json

import httpx
import pytest

from lobster.economics.book import TreasuryBook, EconomicPolicy
from lobster.economics.revenue_watcher import RevenueSettings, RevenueWatcher, DAY
from lobster.economics.revenue_watcher import public_revenue_report
from lobster.ops.alerts import financial_observations
from lobster.store import Store
from test_revenue_ingestion import BUILDER, Upstream, claim


def setup(tmp_path, monkeypatch, *, baseline=0, now_ms=62000, upstream=None):
    import lobster.economics.revenue_watcher as module
    clock = [now_ms]
    monkeypatch.setattr(module, "utcnow", lambda: datetime.fromtimestamp(clock[0]/1000, timezone.utc))
    book = TreasuryBook(tmp_path/"book.db")
    settings = RevenueSettings(_env_file=None, enabled=True, builder=BUILDER, baseline_ms=baseline, book=book.path)
    upstream = upstream or Upstream()
    return book, settings, upstream, clock


def test_continuous_observer_restart_overlap_and_exact_cumulative_fee_allocation(tmp_path, monkeypatch):
    from lobster.economics.distribution import distribution
    book, settings, upstream, clock = setup(tmp_path, monkeypatch)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream.request)) as client:
            watcher = RevenueWatcher(book, settings, client)
            assert len((await watcher.tick())["imported_receipts"]) == 1
            watcher.close()
            assert watcher.state()["active"] is False
            clock[0] += 2000
            upstream.rows.append(claim(2, amount="1.000000", time=3000))
            recovered = RevenueWatcher(TreasuryBook(book.path), settings, client)
            result = await recovered.tick()
            assert len(result["imported_receipts"]) == 1 and result["caught_up"] and not result["automatic_claims_enabled"]
            assert not result["transfers_attempted"]
            assert public_revenue_report(book)["status"] == "running"
            assert BUILDER not in json.dumps(public_revenue_report(book))
            assert (await recovered.tick())["imported_receipts"] == []
            assert len(upstream.calls) == 4  # Two exact fixed-host read pairs; no same-clock replay.
    asyncio.run(run())
    report = distribution(book)
    assert report["recorded_cash"] == "2.500000"
    assert book.report(EconomicPolicy())["record_count"] == 2


def test_manual_history_cursor_cannot_be_skipped_by_a_new_observer(tmp_path, monkeypatch):
    from lobster.economics.ingestion import RevenueImporter
    book, settings, upstream, _ = setup(tmp_path, monkeypatch, baseline=3000, now_ms=100000)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream.request)) as client:
            assert public_revenue_report(book)["status"] == "not_configured"
            await RevenueImporter(book, client, BUILDER).sync_builder(0, 2000)
            watcher = RevenueWatcher(book, settings, client)
            with pytest.raises(ValueError, match="precedes"): await watcher.tick()
            assert len(upstream.calls) == 2
    asyncio.run(run())


def test_observation_failure_preserves_receipt_cursor_and_raises_redacted_monitor_warning(tmp_path, monkeypatch):
    book, settings, upstream, clock = setup(tmp_path, monkeypatch)
    app = Store(f"sqlite:///{tmp_path/'app.db'}")
    try:
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(upstream.request)) as client:
                watcher = RevenueWatcher(book, settings, client)
                await watcher.tick()
                upstream.referral["referrerState"]["data"]["referralStates"] = [{"private": "never publish"}]
                clock[0] += 2000
                with pytest.raises(ValueError): await watcher.tick()
                with book.transaction() as db:
                    source = json.loads(db.execute("SELECT payload FROM revenue_sources").fetchone()[0])
                    assert source["cursor_ms"] == 2000
                alerts = financial_observations(tmp_path/"app.db", book.path)
                assert {"code": "revenue_observation_unavailable", "severity": "warning", "scope": "treasury", "count": 1} in alerts
                assert "private" not in json.dumps(alerts)
                watcher.close()
                assert not any(a["code"] == "revenue_observation_unavailable" for a in financial_observations(tmp_path/"app.db", book.path))
        asyncio.run(run())
    finally: app.engine.dispose()


def test_long_catchup_is_seven_day_bounded_and_source_baseline_cannot_be_changed(tmp_path, monkeypatch):
    book, settings, upstream, clock = setup(tmp_path, monkeypatch, now_ms=20*DAY+60000, upstream=Upstream([]))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream.request)) as client:
            watcher = RevenueWatcher(book, settings, client)
            result = await watcher.tick()
            assert result["cursor_ms"] == 7*DAY and not result["caught_up"]
            assert (await watcher.tick())["cursor_ms"] == 14*DAY-5000
            with pytest.raises(ValueError, match="immutable"):
                RevenueWatcher(book, settings.model_copy(update={"baseline_ms": 1}), client)
            clock[0] = 62000
            with pytest.raises(ValueError, match="regressed"): await watcher.tick()
    asyncio.run(run())


def test_existing_manual_cursor_cannot_be_skipped_and_late_history_does_not_allocate_twice(tmp_path, monkeypatch):
    book, settings, upstream, clock = setup(tmp_path, monkeypatch, upstream=Upstream([]))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream.request)) as client:
            watcher = RevenueWatcher(book, settings, client)
            await watcher.tick()
            upstream.rows.append(claim(time=1000))
            clock[0] += 1000
            with pytest.raises(ValueError, match="Late receipt"): await watcher.tick()
            assert book.report(EconomicPolicy())["record_count"] == 0
    asyncio.run(run())


@pytest.mark.parametrize("invalid", [True, 1000.0, "1.5", "1e3", "-1", ""])
def test_baseline_refuses_ambiguous_money_style_coercions(invalid):
    with pytest.raises(ValueError): RevenueSettings(_env_file=None, baseline_ms=invalid)


def test_integer_environment_baseline_is_accepted_without_key_material(monkeypatch):
    monkeypatch.setenv("REVENUE_BASELINE_MS", "1000")
    assert RevenueSettings(_env_file=None).baseline_ms == 1000
