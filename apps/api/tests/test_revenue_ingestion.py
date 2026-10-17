import asyncio
import json
from decimal import Decimal as D
from types import SimpleNamespace

import httpx
import pytest

from lobster.economics.book import EconomicPolicy, TreasuryBook
from lobster.economics.ingestion import RevenueImporter, sync_project_settlement

BUILDER = "0x" + "1" * 40


def claim(index=1, amount="1.500000", time=1000):
    return {"time": time, "hash": "0x" + f"{index:064x}", "delta": {"type": "rewardsClaim", "amount": amount}}


class Upstream:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [claim()]
        self.referral = {"builderRewards": "0.01", "claimedRewards": "1000", "referrerState": {"data": {"referralStates": []}}}
        self.calls = []

    def request(self, request):
        assert str(request.url) == "https://api.hyperliquid.xyz/info"
        body = json.loads(request.content)
        self.calls.append(body)
        assert body["user"] == BUILDER
        if body["type"] == "referral": return httpx.Response(200, json=self.referral)
        assert body["type"] == "userNonFundingLedgerUpdates"
        return httpx.Response(200, json=[row for row in self.rows if body["startTime"] <= row["time"] <= body["endTime"]])


def sync(book, upstream, start=0, end=2000):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream.request)) as client:
            return await RevenueImporter(book, client, BUILDER).sync_builder(start, end)
    return asyncio.run(run())


def test_observed_claim_only_exact_cash_and_restart_deduplication(tmp_path):
    path = tmp_path / "book.db"
    book, upstream = TreasuryBook(path), Upstream()
    upstream.rows += [{"time": 1100, "hash": "0x" + "f"*64, "delta": {"type": "deposit", "usdc": "999"}}]
    first = sync(book, upstream)
    assert len(first["imported_receipts"]) == 1
    assert not first["cryptographic_finality_verified"] and not first["transfers_attempted"]
    assert sync(TreasuryBook(path), upstream)["imported_receipts"] == []
    report = book.report(EconomicPolicy())
    assert report["record_count"] == 1 and D(report["recorded_cash"]) == D("1.5")
    assert report["provenance"] == "owner_supplied_unverified" and not report["receipts_authenticated"]


@pytest.mark.parametrize("change", ["referrals", "aggregate", "float", "negative", "nan", "precision", "currency", "hash"])
def test_ambiguous_or_invalid_claim_rolls_back_every_receipt(tmp_path, change):
    book, upstream = TreasuryBook(tmp_path / "book.db"), Upstream([claim(), claim(2, time=1200)])
    if change == "referrals": upstream.referral["referrerState"]["data"]["referralStates"] = [{}]
    if change == "aggregate": upstream.referral["claimedRewards"] = "2"
    if change == "float": upstream.rows[1]["delta"]["amount"] = 1.1
    if change == "negative": upstream.rows[1]["delta"]["amount"] = "-1"
    if change == "nan": upstream.rows[1]["delta"]["amount"] = "NaN"
    if change == "precision": upstream.rows[1]["delta"]["amount"] = "0.0000001"
    if change == "currency": upstream.rows[1]["delta"]["token"] = "HYPE"
    if change == "hash": upstream.rows[1]["hash"] = "x"
    with pytest.raises(ValueError): sync(book, upstream)
    assert book.report(EconomicPolicy())["record_count"] == 0


def test_changed_late_receipt_gap_and_cursor_regression_refuse(tmp_path):
    book, upstream = TreasuryBook(tmp_path / "book.db"), Upstream()
    sync(book, upstream)
    for start, end in [(2001, 3000), (0, 1999)]:
        with pytest.raises(ValueError, match="cursor"): sync(book, upstream, start, end)
    upstream.rows.append(claim(2, time=1500))
    with pytest.raises(ValueError, match="Late"): sync(book, upstream, 0, 3000)
    upstream.rows = [claim(amount="1.6")]
    with pytest.raises(ValueError, match="changed"): sync(book, upstream, 0, 3000)
    assert book.report(EconomicPolicy())["record_count"] == 1


def test_conflicting_duplicate_and_full_same_timestamp_page_refuse(tmp_path):
    book, upstream = TreasuryBook(tmp_path / "book.db"), Upstream([claim(), claim(amount="2")])
    with pytest.raises(ValueError, match="Conflicting"): sync(book, upstream)
    upstream.rows = [claim(i) for i in range(500)]
    with pytest.raises(ValueError, match="truncated"): sync(book, upstream)
    assert book.report(EconomicPolicy())["record_count"] == 0


def test_overlapping_incremental_window_never_duplicates(tmp_path):
    book, upstream = TreasuryBook(tmp_path / "book.db"), Upstream()
    sync(book, upstream)
    upstream.rows.append(claim(2, amount="0.1", time=2500))
    assert len(sync(book, upstream, 0, 3000)["imported_receipts"]) == 1
    assert D(book.report(EconomicPolicy())["recorded_cash"]) == D("1.6")


def project():
    state = {"positions": [], "open_orders": []}
    reference = {"baseline_ms": 100, "cursor_ms": 2000, "funding_observed": "-0.1",
        "net_equity_change_excluding_cashflows": "1.700000"}
    snapshot = {"trades": [{"status": "closed"}], "fills": [{"time": 1000, "closedPnl": "2", "fee": "0.2", "builderFee": "0.01"}]}
    async def observe(): return state, reference
    return SimpleNamespace(settings=SimpleNamespace(network="mainnet", account=BUILDER),
        ledger=SimpleNamespace(network="mainnet", snapshot=lambda: snapshot), observe=observe), state, reference, snapshot


def test_flat_net_settlement_includes_funding_fees_once_and_survives_restart(tmp_path):
    path = tmp_path / "book.db"
    runner, state, ref, snapshot = project()
    result = asyncio.run(sync_project_settlement(TreasuryBook(path), runner))
    assert D(result["new_settlement"]) == D("1.7")
    assert D(asyncio.run(sync_project_settlement(TreasuryBook(path), runner))["new_settlement"]) == 0
    ref.update(cursor_ms=3000, net_equity_change_excluding_cashflows="1.200000")
    snapshot["fills"].append({"time": 2500, "closedPnl": "-0.4", "fee": "0.1"})
    result = asyncio.run(sync_project_settlement(TreasuryBook(path), runner))
    assert D(result["new_settlement"]) == D("-0.5")
    report = TreasuryBook(path).report(EconomicPolicy())
    assert report["record_count"] == 2 and D(report["recorded_cash"]) == D("1.2")


@pytest.mark.parametrize("change", ["testnet", "unrealized", "pending", "mismatch", "prehistory", "precision"])
def test_incomplete_or_paper_project_settlement_cannot_credit_treasury(tmp_path, change):
    runner, state, ref, snapshot = project()
    if change == "testnet": runner.settings.network = "testnet"
    if change == "unrealized": state["positions"] = [{}]
    if change == "pending": snapshot["trades"][0]["status"] = "unknown"
    if change == "mismatch": ref["net_equity_change_excluding_cashflows"] = "12"
    if change == "prehistory": snapshot["fills"][0]["time"] = 50
    if change == "precision": ref["net_equity_change_excluding_cashflows"] = "1.7000001"
    book = TreasuryBook(tmp_path / "book.db")
    with pytest.raises(ValueError): asyncio.run(sync_project_settlement(book, runner))
    assert book.report(EconomicPolicy())["record_count"] == 0
