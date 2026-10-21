from decimal import Decimal as D
from types import SimpleNamespace
import json

import pytest

from lobster.domain import utcnow
from lobster.economics.book import TreasuryBook, TreasuryEntry
from lobster.economics.distribution import DistributionPolicy, distribution
from lobster.economics.public_donations import public_donations
from lobster.execution.contracts import fingerprint
from lobster.execution.ledger import ExecutionLedger
from lobster.ops.catalog import register_journal
from lobster.store import Store
from test_economics import entry
from test_strategy_sharing import settle


def test_donations_exclude_principal_fees_authors_and_recover_losses_once(tmp_path):
    book = TreasuryBook(tmp_path/'book.db')
    book.append(entry(1, 'capital_in', '1000'))
    book.append(entry(2, 'builder_receipt', '500'))
    settle(book, 3, '100')
    assert D(distribution(book)['donations']['allocated']) == 0
    book.append(entry(4, 'trading_profit', '100'))
    book.append(entry(5, 'expense', '10'))
    assert D(distribution(book)['donations']['allocated']) == 45
    book.append(entry(6, 'trading_loss', '40'))
    assert D(distribution(TreasuryBook(book.path))['donations']['allocated']) == 25
    assert distribution(book)['donations']['sent'] == '0'
    assert D(distribution(book)['outstanding_earmarks']['donations']) == 25
    assert D(distribution(book)['lifetime_buyback_entitlement']) == 0
    with pytest.raises(ValueError): DistributionPolicy(profit_buyback_share='0.5')


def test_historical_buybacks_consume_old_half_not_new_charity_money(tmp_path):
    book = TreasuryBook(tmp_path/'book.db')
    book.append(entry(0, 'capital_in', '100'))
    book.append(entry(1, 'trading_profit', '100'))
    book.append(entry(2, 'buyback_spend', '30'))
    for _ in range(2): assert D(distribution(TreasuryBook(book.path))['donations']['allocated']) == 20
    book.append(entry(3, 'trading_loss', '80'))
    assert D(distribution(book)['donations']['allocated']) == 0
    assert distribution(book)['blockers']


def test_public_counter_requires_bound_reconciled_mainnet_settlement_and_redacts_sources(tmp_path):
    store = Store(f"sqlite:///{tmp_path/'app.db'}")
    account, signer = '0x'+'1'*40, '0x'+'2'*40
    ledger = ExecutionLedger(f"sqlite:///{tmp_path/'project.db'}", account, signer, network='mainnet')
    book = TreasuryBook(tmp_path/'treasury.db')
    runtime = SimpleNamespace(store=store, settings=SimpleNamespace(treasury_path=book.path))
    try:
        assert public_donations(runtime)['allocated'] is None
        register_journal(store, ledger, 'project')
        now = int(utcnow().timestamp()*1000)-1000
        from datetime import datetime, timezone
        identity = fingerprint({'source':'project:'+account,'baseline':now-1000,'cursor':now})
        book.append(TreasuryEntry(id=identity,receipt_ref='hl-mainnet-settlement:'+identity,evidence_sha256='a'*64,
            kind='trading_profit',amount='100',occurred_at=datetime.fromtimestamp(now/1000,timezone.utc),provenance='owner_supplied_unverified'))
        assert public_donations(runtime)['allocated'] is None
        with book.transaction() as db:
            db.execute('CREATE TABLE revenue_sources (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('INSERT INTO revenue_sources VALUES (?,?)',('project:'+account,json.dumps({'baseline_ms':now-1000,'cursor_ms':now,'net_settled':'100'})))
        report = public_donations(runtime)
        assert D(report['allocated']) == 50 and report['sent'] == '0'
        assert account not in json.dumps(report) and signer not in json.dumps(report) and str(book.path) not in json.dumps(report)
        # Manual/unmatched profit can never inflate a published counter.
        book.append(entry(2, 'trading_profit', '100').model_copy(update={'provenance':'owner_supplied_unverified'}))
        assert public_donations(runtime)['allocated'] is None
    finally:
        ledger.engine.dispose(); store.engine.dispose()
