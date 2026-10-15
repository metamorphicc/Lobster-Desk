import asyncio
import json
import sqlite3

import pytest

from lobster.domain import PitchInput
from lobster.execution.broker import TestnetBroker
from lobster.execution.ledger import ExecutionLedger
from lobster.ops.backup import checksum, restore_drill, snapshot, sqlite_path, verify
from lobster.store import Store


def test_live_wal_snapshot_includes_committed_pitch_without_changing_source(tmp_path):
    source = tmp_path / "source.db"
    store = Store(f"sqlite:///{source}")
    writer = sqlite3.connect(source)
    writer.execute("PRAGMA journal_mode=WAL")
    pitch = store.submit(PitchInput(author="Backup QA", direction="long", entry="60000", stop="59400", target="61800",
        thesis="A defined breakout setup for the WAL snapshot restore drill."), "backup-123")
    assert source.with_name(source.name + "-wal").exists()
    original = store.state(None)
    manifest = snapshot({"paper": source}, tmp_path / "backup")
    restore = tmp_path / "restore"
    report = restore_drill(manifest, restore)
    assert report["integrity_verified"] and not report["live_database_replaced"]
    recovered = Store(f"sqlite:///{restore / 'paper.sqlite3'}")
    assert recovered.get_episode(pitch["id"]) == pitch
    assert recovered.state(None) == original == store.state(None)
    assert checksum(restore / "paper.sqlite3") == verify(manifest)["files"][0]["sha256"]
    recovered.engine.dispose(); writer.close(); store.engine.dispose()


def test_restored_uncertain_command_and_nonce_cannot_replay_entry(execution_rig, tmp_path):
    broker, exchange, setup, _ = execution_rig
    asyncio.run(broker.stage(setup))
    exchange.failures["entry"] = "before"
    asyncio.run(broker.dispatch(setup.episode_id))
    before = broker.ledger.snapshot()
    commands = broker.ledger.commands(setup.episode_id)
    writes = len(exchange.writes)
    manifest = snapshot({"paper": tmp_path / "review.db", "testnet": tmp_path / "execution.db"}, tmp_path / "backup")
    restore_drill(manifest, tmp_path / "restore")
    ledger = ExecutionLedger(f"sqlite:///{tmp_path / 'restore/testnet.sqlite3'}", exchange.account_address, broker.signer.address)
    assert ledger.snapshot() == before
    assert ledger.commands(setup.episode_id) == commands
    recovered = TestnetBroker(ledger, exchange, broker.signer, armed=True)
    asyncio.run(recovered.dispatch(setup.episode_id))
    assert len(exchange.writes) == writes
    assert ledger.snapshot()["control"]["last_nonce"] == before["control"]["last_nonce"]
    ledger.engine.dispose()


def sample(tmp_path):
    source = tmp_path / "source.db"
    store = Store(f"sqlite:///{source}")
    store.engine.dispose()
    return snapshot({"paper": source}, tmp_path / "backup")


def test_corrupted_backup_is_rejected_before_restore_destination_exists(tmp_path):
    manifest = sample(tmp_path)
    with (manifest.parent / "paper.sqlite3").open("ab") as file:
        file.write(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        restore_drill(manifest, tmp_path / "restore")
    assert not (tmp_path / "restore").exists()


@pytest.mark.parametrize("filename", ["../source.db", "C:/private.db", "testnet.sqlite3"])
def test_manifest_cannot_select_another_file(tmp_path, filename):
    manifest = sample(tmp_path)
    data = json.loads(manifest.read_text())
    data["files"][0]["filename"] = filename
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="filename"):
        restore_drill(manifest, tmp_path / "restore")
    assert not (tmp_path / "restore").exists()


def test_restore_refuses_existing_directory_and_preserves_files(tmp_path):
    manifest = sample(tmp_path)
    target = tmp_path / "restore"
    target.mkdir()
    protected = target / "paper.sqlite3"
    protected.write_bytes(b"must remain unchanged")
    with pytest.raises(FileExistsError):
        restore_drill(manifest, target)
    assert protected.read_bytes() == b"must remain unchanged"
    with pytest.raises(FileExistsError):
        snapshot({"paper": tmp_path / "source.db"}, manifest.parent)


def test_missing_database_is_not_created_and_unsupported_urls_are_refused(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(ValueError, match="missing"):
        snapshot({"paper": missing}, tmp_path / "backup")
    assert not missing.exists() and not (tmp_path / "backup").exists()
    for url in ["sqlite:///:memory:", "postgresql://user:secret@localhost/db", "sqlite:///data/test.db?mode=ro"]:
        with pytest.raises(ValueError, match="SQLite"):
            sqlite_path(url)
