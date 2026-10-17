from decimal import Decimal as D
import json

import pytest

from lobster.economics.book import TreasuryBook, TreasuryEntry
from lobster.economics.distribution import distribution
from lobster.economics.sharing import author_balances
from test_economics import entry
from test_distribution import ready

OWNER = "0x" + "1"*40


def allocation(index=1, net="100", owner=OWNER):
    return {"execution_id": f"{index:064x}", "strategy_id": "a"*32, "owner": owner, "net_profit": net, "evidence_hash": "b"*64}


def receipt(index, kind, amount, **extra):
    return TreasuryEntry.model_validate(entry(index, "capital_in", "1").model_dump(mode="json") | {"kind": kind, "amount": amount} | extra)


def settle(book, index=1, net="100", owner=OWNER):
    value = D(net)
    return book.append(receipt(index, "trading_profit" if value > 0 else "trading_loss" if value < 0 else "strategy_checkpoint", str(abs(value)), strategy_allocations=[allocation(index, net, owner)]))


def test_user_profit_is_split_once_and_never_funds_a_buyback(tmp_path):
    book = TreasuryBook(tmp_path/"shares.db")
    first = settle(book)
    report = distribution(book, ready())
    assert report["user_strategy_profit"] == {"net_realized": "100", "author_entitlement": "50.000000", "author_paid": "0", "author_outstanding": "50.000000", "bot_retained": "50.000000"}
    assert D(report["reserve_bounded_buyback_budget"]) == 0
    assert D(report["outstanding_earmarks"]["strategy_authors"]) == 50
    assert D(report["recorded_cash"]) == 100
    TreasuryBook(book.path).append(TreasuryEntry.model_validate(first["entry"]))
    assert distribution(book)["record_count"] == 1


def test_author_payout_cannot_exceed_earned_balance_and_losses_are_carried_forward(tmp_path):
    book = TreasuryBook(tmp_path/"payouts.db")
    settle(book)
    payout = receipt(2, "author_payout", "50", beneficiary=OWNER)
    book.append(payout)
    with pytest.raises(ValueError, match="exceeds earned"): book.append(receipt(3, "author_payout", "1", beneficiary=OWNER))
    settle(book, 4, "-20")
    report = distribution(book, ready())
    assert report["user_strategy_profit"]["author_outstanding"] == "0"
    assert report["blockers"]
    settle(book, 5, "40")
    with book.transaction() as db: balance = author_balances(book.read(db))[OWNER]
    assert D(balance["entitlement"]) == 60 and D(balance["outstanding"]) == 10
    assert D(distribution(book)["recorded_cash"]) == 70


def test_allocations_can_record_zero_account_delta_without_minting_cash_and_cannot_duplicate_execution(tmp_path):
    book = TreasuryBook(tmp_path/"zero.db")
    book.append(receipt(1, "strategy_checkpoint", "0", strategy_allocations=[allocation()]))
    assert D(distribution(book)["recorded_cash"]) == 0
    assert D(distribution(book)["user_strategy_profit"]["author_outstanding"]) == 50
    with pytest.raises(ValueError, match="only once"):
        book.append(receipt(2, "strategy_checkpoint", "0", strategy_allocations=[allocation()]))
    with pytest.raises(ValueError): book.append(receipt(3, "author_payout", "1", beneficiary=OWNER))


def test_fee_split_and_retired_donation_writer(tmp_path):
    book = TreasuryBook(tmp_path/"fees.db")
    book.append(entry(1, "builder_receipt", "500"))
    assert distribution(book)["fee_allocation"] == {"agents": "300.000000", "team": "200.000000"}
    with pytest.raises(ValueError, match="retired"): book.append(entry(2, "charity_payout", "1"))


def test_own_strategy_buybacks_cannot_consume_author_liabilities(tmp_path):
    book = TreasuryBook(tmp_path/"mixed.db")
    settle(book)
    book.append(entry(2, "trading_profit", "100"))
    report = distribution(book, ready())
    assert D(report["lifetime_buyback_entitlement"]) == 50
    book.append(entry(3, "capital_out", "140"))
    assert D(distribution(book, ready())["reserve_bounded_buyback_budget"]) == 10


def test_old_payment_receipts_remain_readable_without_a_new_donation_path(tmp_path):
    from lobster.execution.contracts import fingerprint
    book = TreasuryBook(tmp_path/"historical.db")
    book.append(entry(1, "capital_in", "100"))
    book.append(entry(2, "capital_out", "10"))
    with book.transaction() as db:
        row = json.loads(db.execute("SELECT payload FROM treasury_receipts WHERE id='receipt-0002'").fetchone()[0])
        row["entry"]["kind"] = "charity_payout"
        # Old rows lack the new optional metadata; their hashes are never rewritten by a reader.
        row["entry"].pop("strategy_allocations"); row["entry"].pop("beneficiary")
        row["record_hash"] = fingerprint({k: v for k, v in row.items() if k != "record_hash"})
        db.execute("UPDATE treasury_receipts SET payload=? WHERE id='receipt-0002'", (json.dumps(row),))
    assert D(distribution(book)["recorded_cash"]) == 90
    assert "charity" not in distribution(book)["fee_allocation"]


@pytest.mark.parametrize("invalid", [1.5, True, "NaN", "0.0000001"])
def test_strategy_profits_refuse_float_nonfinite_and_sub_usdc_precision(invalid):
    from lobster.economics.book import StrategyAllocation
    with pytest.raises(ValueError): StrategyAllocation.model_validate(allocation(net=invalid))
