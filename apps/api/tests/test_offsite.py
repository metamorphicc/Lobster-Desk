import base64
from hashlib import sha256
import io
import json
from pathlib import Path
import zipfile

from botocore.stub import Stubber
from botocore.response import StreamingBody
from pydantic import SecretStr
import pytest

from lobster.config import Settings
from lobster.execution.ledger import ExecutionLedger
from lobster.execution.project import ProjectSettings
from lobster.execution.settings import TestnetSettings
from lobster.ops.backup import snapshot, verify, restore_drill
from lobster.ops.catalog import register_journal
from lobster.ops.inventory import discover_sources
from lobster.ops.offsite import (OffsiteSettings, seal_snapshot, open_snapshot, encrypt_bytes,
    s3_client, upload, download, object_key)
from lobster.store import Store
from lobster.users.contracts import UserTestnetSettings

KEY = bytes(range(32))  # PUBLIC encryption fixture, never encrypt real data with it.
OWNER, AGENT = "0x" + "a"*40, "0x" + "b"*40


@pytest.fixture
def inventory(tmp_path):
    store = Store(f"sqlite:///{tmp_path/'app.db'}")
    ledger = ExecutionLedger(f"sqlite:///{tmp_path/'user.db'}", OWNER, AGENT)
    register_journal(store, ledger, "user")
    config = Settings(_env_file=None, database_url=str(store.engine.url), treasury_path=str(tmp_path/'absent-treasury.db'))
    old = TestnetSettings(_env_file=None, database_url=f"sqlite:///{tmp_path/'absent-testnet.db'}")
    project = ProjectSettings(_env_file=None, database_url=f"sqlite:///{tmp_path/'absent-project.db'}")
    user = UserTestnetSettings(_env_file=None, execution_root=str(tmp_path/'empty-users'))
    try: yield store, ledger, lambda: discover_sources(config, old, project, user)
    finally: ledger.engine.dispose(); store.engine.dispose()


def test_every_canonical_financial_journal_is_included_and_duplicate_wallet_path_refused(inventory, tmp_path):
    store, ledger, discover = inventory
    sources = discover()
    assert len(sources) == 2 and Path(ledger.engine.url.database).resolve() in sources.values()
    assert len([role for role in sources if role.startswith("execution-")]) == 1
    assert register_journal(store, ledger, "user")["path"] == str(Path(ledger.engine.url.database).resolve())
    other = ExecutionLedger(f"sqlite:///{tmp_path/'different.db'}", OWNER, AGENT)
    try:
        with pytest.raises(ValueError, match="canonical"): register_journal(store, other, "project")
    finally: other.engine.dispose()


def test_encrypted_snapshot_authenticates_every_database_and_restores_into_new_directory(inventory, tmp_path):
    _, ledger, discover = inventory
    manifest = snapshot(discover(), tmp_path / "snapshot")
    target = tmp_path / "private.ldb"
    report = seal_snapshot(manifest, KEY, target)
    raw = target.read_bytes()
    assert b"SQLite format" not in raw and not report["uploaded"] and report["encryption"] == "AES-256-GCM"
    decoded = open_snapshot(raw, KEY, tmp_path/"decoded")
    assert len(verify(decoded)["files"]) == 2
    recovered = restore_drill(decoded, tmp_path/"isolated-restore")
    assert recovered["integrity_verified"] and not recovered["live_database_replaced"] and not recovered["exchange_reconciled"]
    assert not ledger.snapshot()["trades"]
    with pytest.raises(FileExistsError): seal_snapshot(manifest, KEY, target)
    with pytest.raises(FileExistsError): open_snapshot(raw, KEY, tmp_path/"decoded")


@pytest.mark.parametrize("corruption", ["key", "header", "tag", "payload", "truncated"])
def test_wrong_key_or_modified_ciphertext_creates_no_restore_directory(inventory, tmp_path, corruption):
    _, _, discover = inventory
    manifest = snapshot(discover(), tmp_path/"snapshot")
    target = tmp_path/"private.ldb"
    seal_snapshot(manifest, KEY, target)
    raw, key = bytearray(target.read_bytes()), KEY
    if corruption == "key": key = bytes(reversed(KEY))
    if corruption == "header": raw[0] ^= 1
    if corruption == "tag": raw[30] ^= 1
    if corruption == "payload": raw[-1] ^= 1
    if corruption == "truncated": raw = raw[:20]
    destination = tmp_path/"must-not-exist"
    with pytest.raises(ValueError): open_snapshot(bytes(raw), key, destination)
    assert not destination.exists()


def test_authenticated_archive_cannot_write_arbitrary_files(tmp_path):
    memory = io.BytesIO()
    with zipfile.ZipFile(memory,"w",compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", json.dumps({"files": [{"role": "../escape", "filename": "../escape.sqlite3"}]}))
        archive.writestr("../escape.sqlite3", b"not a database")
    with pytest.raises(ValueError): open_snapshot(encrypt_bytes(memory.getvalue(), KEY), KEY, tmp_path/"destination")
    assert not (tmp_path/"destination").exists() and not (tmp_path/"escape.sqlite3").exists()


def storage_settings():
    return OffsiteSettings(_env_file=None, offsite_enabled=True, encryption_key=SecretStr(KEY.hex()),
        s3_bucket="public-fixture-backup", aws_access_key_id=SecretStr("public-fixture"), aws_secret_access_key=SecretStr("public-fixture"))


def test_offsite_upload_uses_official_sdk_conditional_encrypted_object_and_verified_read(inventory, tmp_path):
    _, _, discover = inventory
    manifest = snapshot(discover(), tmp_path/"snapshot")
    target = tmp_path/"private.ldb"; seal_snapshot(manifest, KEY, target)
    payload, settings = target.read_bytes(), storage_settings()
    client = s3_client(settings)
    assert client.meta.endpoint_url == "https://s3.amazonaws.com"
    key = object_key(settings, payload)
    with Stubber(client) as stub:
        stub.add_response("put_object", {"ETag": '"public-fixture"'}, {"Bucket": settings.s3_bucket, "Key": key, "Body": payload,
            "ContentType": "application/octet-stream", "ServerSideEncryption": "AES256", "IfNoneMatch": "*",
            "ChecksumSHA256": base64.b64encode(sha256(payload).digest()).decode(), "Metadata": {"lobster-sha256": sha256(payload).hexdigest()}})
        assert upload(settings, client, payload)["uploaded"]
        stub.add_response("get_object", {"Body": StreamingBody(io.BytesIO(payload), len(payload)), "ContentLength": len(payload)}, {"Bucket": settings.s3_bucket, "Key": key})
        assert download(settings, client, key) == payload
        stub.assert_no_pending_responses()
    client.close()


def test_disabled_or_unencrypted_remote_operations_fail_before_sdk_request():
    payload = encrypt_bytes(b"public fixture", KEY)
    with pytest.raises(ValueError): upload(OffsiteSettings(_env_file=None), None, payload)
    with pytest.raises(ValueError): upload(storage_settings(), None, b"SQLite format plaintext must never upload")
    with pytest.raises(ValueError): download(storage_settings(), None, "../../arbitrary")


def test_missing_registered_journal_is_never_silently_skipped(inventory):
    _, ledger, discover = inventory
    ledger.engine.dispose()
    Path(ledger.engine.url.database).unlink()
    with pytest.raises(ValueError, match="missing"): discover()


def test_existing_s3_object_is_compared_without_overwriting():
    settings, payload = storage_settings(), encrypt_bytes(b"public fixture", KEY)
    client = s3_client(settings)
    key = object_key(settings, payload)
    with Stubber(client) as stub:
        stub.add_client_error("put_object", service_error_code="PreconditionFailed", http_status_code=412)
        stub.add_response("get_object", {"Body": StreamingBody(io.BytesIO(payload), len(payload)), "ContentLength": len(payload)},
            {"Bucket": settings.s3_bucket, "Key": key})
        assert upload(settings, client, payload)["already_present"]
        stub.assert_no_pending_responses()
    client.close()


def test_encrypted_recovery_preserves_uncertain_entry_nonce_and_prevents_replay(execution_rig, tmp_path):
    import asyncio
    from lobster.execution.broker import TestnetBroker
    broker, exchange, setup, _ = execution_rig
    asyncio.run(broker.stage(setup))
    exchange.failures["entry"] = "before"
    asyncio.run(broker.dispatch(setup.episode_id))
    original, commands, sent = broker.ledger.snapshot(), broker.ledger.commands(setup.episode_id), len(exchange.writes)
    manifest = snapshot({"paper": tmp_path/"review.db", "testnet": tmp_path/"execution.db"}, tmp_path/"snapshot")
    encrypted = tmp_path/"recovery.ldb"; seal_snapshot(manifest, KEY, encrypted)
    decoded = open_snapshot(encrypted.read_bytes(), KEY, tmp_path/"decoded")
    restore_drill(decoded, tmp_path/"restore")
    restored = ExecutionLedger(f"sqlite:///{tmp_path/'restore/testnet.sqlite3'}", exchange.account_address, broker.signer.address)
    try:
        assert restored.commands(setup.episode_id) == commands
        restarted = TestnetBroker(restored, exchange, broker.signer, armed=True)
        asyncio.run(restarted.dispatch(setup.episode_id))
        assert len(exchange.writes) == sent and restored.snapshot()["control"]["last_nonce"] == original["control"]["last_nonce"]
    finally: restored.engine.dispose()
