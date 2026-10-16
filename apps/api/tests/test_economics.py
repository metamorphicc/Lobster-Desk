from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
import json
import sqlite3

import pytest

from lobster.domain import utcnow
from lobster.economics.book import EconomicPolicy, TreasuryBook, TreasuryEntry


def entry(index, kind, amount):
    return TreasuryEntry(id=f"receipt-{index:04}", receipt_ref=f"offline-receipt:{index}", evidence_sha256="a"*64,
        kind=kind, amount=amount, occurred_at=utcnow(), provenance="offline_fixture")


def policy():
    return EconomicPolicy(operating_reserve_target="100", liability_reserve="10", tax_reserve_fraction="0.1", buyback_fraction="0.5")


def test_capital_never_counts_as_earnings_and_unset_policy_never_allocates(tmp_path):
    book = TreasuryBook(tmp_path / "treasury.db")
    assert book.report(EconomicPolicy())["provenance"] is None
    book.append(entry(1, "capital_in", "1000"))
    report = book.report(policy())
    assert report["recorded_cash"] == "1000"
    assert report["net_recorded_earnings"] == "0" and D(report["provisional_buyback_allocation"]) == 0
    assert book.report(EconomicPolicy())["provisional_buyback_allocation"] is None


def test_losses_expenses_reserves_tax_and_past_buybacks_are_applied_once(tmp_path):
    book = TreasuryBook(tmp_path / "treasury.db")
    for i, (kind, amount) in enumerate([("capital_in", "1000"), ("builder_receipt", "100"), ("trading_loss", "150"),
        ("expense", "10"), ("builder_receipt", "100"), ("buyback_spend", "10")]):
        book.append(entry(i, kind, amount))
        report = book.report(policy())
        if i == 3:
            assert report["unrecovered_loss"] == "60"
            assert D(report["provisional_buyback_allocation"]) == 0
    assert report["net_recorded_earnings"] == "40"
    assert report["unspent_earnings"] == "30"
    assert D(report["provisional_buyback_allocation"]) == D("15")
    assert not report["transfers_authorized"]
    assert not report["receipts_authenticated"]
    assert report["totals"]["buyback_spend"] == "10"


def test_reserve_shortfall_and_fraction_rounding_never_overallocate(tmp_path):
    book = TreasuryBook(tmp_path / "treasury.db")
    book.append(entry(1, "builder_receipt", "100.000001"))
    assert D(book.report(policy())["provisional_buyback_allocation"]) == 0
    zero = EconomicPolicy(operating_reserve_target="0", liability_reserve="0", tax_reserve_fraction="0", buyback_fraction="0.333333")
    value = D(book.report(zero)["provisional_buyback_allocation"])
    assert value <= D("100.000001") * D("0.333333")
    assert value.as_tuple().exponent == -6


def test_atomic_idempotency_conflicts_restart_and_negative_cash_rollback(tmp_path):
    path = tmp_path / "treasury.db"
    books = [TreasuryBook(path) for _ in range(3)]
    receipt = entry(1, "builder_receipt", "100")
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda i: books[i % 3].append(receipt), range(12)))
    assert len({row["record_hash"] for row in results}) == 1
    with pytest.raises(ValueError, match="conflicts"):
        books[0].append(receipt.model_copy(update={"id": "different-request"}))
    with pytest.raises(ValueError, match="negative"):
        books[0].append(entry(2, "expense", "101"))
    assert TreasuryBook(path).report(policy())["record_count"] == 1


def test_rewritten_chain_and_fixture_provenance_cannot_be_silently_accepted(tmp_path):
    path = tmp_path / "treasury.db"
    book = TreasuryBook(path)
    book.append(entry(1, "capital_in", "100"))
    with pytest.raises(ValueError, match="separate"):
        book.append(entry(2, "builder_receipt", "1").model_copy(update={"provenance": "owner_supplied_unverified"}))
    with sqlite3.connect(path) as db:
        payload = json.loads(db.execute("SELECT payload FROM treasury_receipts").fetchone()[0])
        payload["entry"]["amount"] = "1000"
        db.execute("UPDATE treasury_receipts SET payload=?", (json.dumps(payload),))
    with pytest.raises(ValueError, match="integrity"): book.report(policy())


@pytest.mark.parametrize("amount", [1.1, True, "NaN", "Infinity", "-1", "0", "0.0000001"])
def test_receipts_require_positive_exact_usdc(amount):
    with pytest.raises(ValueError): entry(1, "builder_receipt", amount)


def test_no_token_or_payout_rights_can_be_enabled_by_configuration():
    for change in [{"holder_payouts_enabled": True}, {"transfers_enabled": True}, {"token_role": "dividend"}, {"buyback_fraction": "1.1"}]:
        with pytest.raises(ValueError): EconomicPolicy(**change)
