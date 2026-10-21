from decimal import Decimal as D

from lobster.economics.book import TreasuryBook
from lobster.economics.distribution import DistributionPolicy, distribution
from lobster.users.contracts import UserTestnetSettings
from test_economics import entry


def ready():
    return DistributionPolicy(operating_reserve="0", liability_reserve="0", tax_reserve="0")


def test_exact_fee_waterfall_and_no_deposit_or_fee_profit(tmp_path):
    book = TreasuryBook(tmp_path / "fees.db")
    book.append(entry(1, "capital_in", "1000"))
    book.append(entry(2, "builder_receipt", "500"))
    report = distribution(book, ready())
    assert report["fee_allocation"] == {"agents": "300.000000", "team": "200.000000"}
    assert D(report["lifetime_buyback_entitlement"]) == 0
    assert UserTestnetSettings(_env_file=None).builder_fee_tenths_bps == 50


def test_loss_recovery_costs_and_spend_do_not_reallocate_previous_half(tmp_path):
    path = tmp_path / "profit.db"
    book = TreasuryBook(path)
    for i, (kind, amount) in enumerate([("capital_in", "1000"), ("trading_loss", "100"),
        ("trading_profit", "150"), ("expense", "10"), ("buyback_spend", "20")]):
        book.append(entry(i, kind, amount))
    report = distribution(TreasuryBook(path), ready())
    assert report["net_realized_trading_profit_after_expenses"] == "40"
    assert D(report["reserve_bounded_buyback_budget"]) == 0
    assert D(report["lifetime_buyback_entitlement"]) == 0
    assert D(report["donations"]["allocated"]) == 0  # Already spent under the old destination.
    book.append(entry(5, "trading_loss", "50"))
    assert D(distribution(book, ready())["reserve_bounded_buyback_budget"]) == 0
    assert distribution(book, ready())["loss_carryforward"] == "10"


def test_team_earmarks_and_reserves_cannot_fund_buybacks(tmp_path):
    book = TreasuryBook(tmp_path / "reserve.db")
    for i, (kind, amount) in enumerate([("builder_receipt", "500"), ("trading_profit", "100"),
        ("capital_out", "400")]): book.append(entry(i, kind, amount))
    assert D(distribution(book, ready())["reserve_bounded_buyback_budget"]) == 0
    assert distribution(book)["reserve_bounded_buyback_budget"] is None
    book.append(entry(4, "team_payout", "100"))
    report = distribution(book, ready())
    assert D(report["outstanding_earmarks"]["team"]) == 100
    assert D(report["reserve_bounded_buyback_budget"]) == 0


def test_micro_usdc_rounding_preserves_all_fees_and_flags_overpaid_earmarks(tmp_path):
    book = TreasuryBook(tmp_path / "dust.db")
    book.append(entry(1, "builder_receipt", "0.000001"))
    assert sum(map(D, distribution(book)["fee_allocation"].values())) == D("0.000001")
    book.append(entry(2, "team_payout", "0.000001"))
    report = distribution(book, ready())
    assert report["blockers"] and D(report["reserve_bounded_buyback_budget"]) == 0
    assert not report["transfers_authorized"] and not report["burns_verified"]
