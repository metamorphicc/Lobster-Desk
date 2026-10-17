import asyncio
import json

import pytest

from lobster.execution.public import project_activity
from lobster.ops.catalog import register_journal
from lobster.store import Store


def test_public_project_report_is_read_only_empty_without_execution(tmp_path):
    store = Store(f"sqlite:///{tmp_path/'app.db'}")
    try:
        result = project_activity(store)
        assert result["journals"] == [] and result["submission_enabled"] is False
        assert result["scope"] == "registered-project-journals-only"
    finally: store.engine.dispose()


def test_project_report_contains_review_fill_protection_but_no_commands_or_private_identity(execution_rig, tmp_path):
    broker, gateway, setup, _ = execution_rig
    store = Store(f"sqlite:///{tmp_path/'app.db'}")
    try:
        register_journal(store, broker.ledger, "project")
        async def run():
            await broker.stage(setup)
            return await broker.dispatch(setup.episode_id)
        trade = asyncio.run(run())
        from lobster.ops.heartbeat import ping
        assert ping(broker.ledger.engine.url.database, "project")
        result = project_activity(store)
        assert result["journals"][0]["heartbeat"]["ok"] is True
        public = result["journals"][0]["trades"][0]
        assert public["status"] == "protected" and public["protected_quantity"] == trade["filled_quantity"]
        assert public["reviews"]["analyst"]["verdict"] == "approve" and len(public["recent_fills"]) == 1
        encoded = json.dumps(result)
        for private in [gateway.account_address, broker.signer.address.lower(), str(tmp_path), '"signature"', '"nonce"', '"commands"']:
            assert private not in encoded
        before = broker.ledger.snapshot()
        assert project_activity(store)["journals"] == result["journals"]
        assert broker.ledger.snapshot() == before
    finally: store.engine.dispose()


def test_user_journals_are_never_part_of_public_project_report(execution_rig, tmp_path):
    broker, _, _, _ = execution_rig
    store = Store(f"sqlite:///{tmp_path/'app.db'}")
    try:
        register_journal(store, broker.ledger, "user")
        assert project_activity(store)["journals"] == []
    finally: store.engine.dispose()


def test_changed_or_missing_registered_project_journal_fails_closed(execution_rig, tmp_path):
    from sqlalchemy import text
    broker, _, _, _ = execution_rig
    store = Store(f"sqlite:///{tmp_path/'app.db'}")
    try:
        register_journal(store, broker.ledger, "project")
        with broker.ledger.transaction() as db:
            db.execute(text("UPDATE testnet_control SET payload=json_set(payload,'$.network','mainnet') WHERE id=1"))
        with pytest.raises(ValueError, match="identity"): project_activity(store)
    finally: store.engine.dispose()
