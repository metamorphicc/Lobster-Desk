from concurrent.futures import ThreadPoolExecutor

import pytest

from lobster.economics.book import TreasuryBook
from lobster.economics.buybacks import BuybackBook, BurnObservation, Purchase
from test_economics import entry


@pytest.fixture
def book(tmp_path):
    treasury = TreasuryBook(tmp_path / "treasury.db")
    treasury.append(entry(1, "builder_receipt", "100"))
    treasury.append(entry(2, "buyback_spend", "20"))
    return BuybackBook(treasury)


def purchase(**changes):
    return Purchase(**({"id": "purchase-001", "spending_entry_id": "receipt-0002", "network": "offline-chain",
        "asset": "offline-token", "settlement_ref": "offline-swap:tx:log:1", "evidence_sha256": "b"*64,
        "cost_usdc": "20", "quantity_atomic": "100000000000000000000", "token_decimals": 18} | changes))


def disposal(**changes):
    return BurnObservation(**({"id": "disposal-001", "purchase_id": "purchase-001", "network": "offline-chain", "asset": "offline-token",
        "event_ref": "offline-burn:tx:log:1", "evidence_sha256": "c"*64, "mechanism": "supply_reduction",
        "quantity_atomic": "10000000000000000000", "supply_before_atomic": "1000000000000000000000",
        "supply_after_atomic": "990000000000000000000"} | changes))


def test_purchase_is_not_a_burn_and_sink_transfer_never_reduces_claimed_supply(book):
    assert book.report()["unlinked_spending_receipts"] == ["receipt-0002"]
    book.purchase(purchase())
    report = book.report()
    assert report["lots"][0]["claimed_supply_reduction_atomic"] == "0"
    book.disposal(disposal(mechanism="sink_transfer", supply_before_atomic=None, supply_after_atomic=None))
    report = book.report()
    assert report["lots"][0]["claimed_supply_reduction_atomic"] == "0"
    assert report["lots"][0]["sink_transfer_atomic"] == "10000000000000000000"
    assert not report["burns_verified"] and not report["transfers_authorized"]


def test_receipts_are_atomic_idempotent_and_spend_cannot_be_used_twice(book):
    value = purchase()
    with ThreadPoolExecutor(5) as pool: results = list(pool.map(lambda _: book.purchase(value), range(10)))
    assert len({row["record_hash"] for row in results}) == 1
    with pytest.raises(ValueError, match="already used"): book.purchase(purchase(id="purchase-002"))
    burn = disposal()
    with ThreadPoolExecutor(5) as pool: results = list(pool.map(lambda _: book.disposal(burn), range(10)))
    assert len({row["record_hash"] for row in results}) == 1
    with pytest.raises(ValueError, match="already used"): book.disposal(disposal(id="disposal-002"))
    restored = BuybackBook(TreasuryBook(book.treasury.path))
    assert restored.report()["lots"][0]["claimed_supply_reduction_atomic"] == burn.quantity_atomic


@pytest.mark.parametrize("changes", [{"cost_usdc": "21"}, {"spending_entry_id": "receipt-0001"}])
def test_purchase_requires_matching_actual_recorded_spend(book, changes):
    with pytest.raises(ValueError): book.purchase(purchase(**changes))


@pytest.mark.parametrize("changes", [{"asset": "another-token"}, {"network": "another-network"},
    {"quantity_atomic": "101000000000000000000", "supply_after_atomic": "899000000000000000000"}])
def test_wrong_asset_network_and_excess_disposal_fail_closed(book, changes):
    book.purchase(purchase())
    with pytest.raises(ValueError): book.disposal(disposal(**changes))
    assert not book.report()["lots"][0]["disposals"]


@pytest.mark.parametrize("changes", [{"supply_after_atomic": "1"}, {"supply_before_atomic": None}, {"quantity_atomic": 1.1},
    {"quantity_atomic": "0"}, {"quantity_atomic": str(2**256)}])
def test_invalid_or_ambiguous_supply_math_is_not_called_a_burn(changes):
    with pytest.raises(ValueError): disposal(**changes)


def test_isolated_treasury_restore_preserves_receipt_links_and_duplicate_protection(book, tmp_path):
    from lobster.ops.backup import snapshot, restore_drill
    book.purchase(purchase())
    book.disposal(disposal())
    before = book.report()
    manifest = snapshot({"treasury": book.treasury.path}, tmp_path / "backup")
    restore_drill(manifest, tmp_path / "restore")
    restored = BuybackBook(TreasuryBook(tmp_path / "restore/treasury.sqlite3"))
    assert restored.report()["lots"] == before["lots"]
    restored.purchase(purchase())
    restored.disposal(disposal())
    assert len(restored.report()["lots"]) == 1
    assert len(restored.report()["lots"][0]["disposals"]) == 1
