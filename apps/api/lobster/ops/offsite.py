"""Authenticated-encrypted recovery bundles and explicit immutable AWS S3 transport."""
import base64
from hashlib import sha256
import io
import json
import secrets
import zipfile
from pathlib import Path

from Crypto.Cipher import AES
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .backup import verify, required_tables, MAX_DATABASES

MAGIC = b"LDBAK2"
MAX_BYTES = 256 * 1024 * 1024


class OffsiteSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.ops", env_prefix="OPS_", extra="ignore", hide_input_in_errors=True)
    offsite_enabled: bool = False
    encryption_key: SecretStr | None = None
    s3_bucket: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
    s3_region: str = Field(default="us-east-1", pattern=r"^[a-z]{2}-[a-z]+-[1-9]$")
    s3_prefix: str = Field(default="lobster-backups", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_session_token: SecretStr | None = None
    use_instance_role: bool = False

    @field_validator("encryption_key", "s3_bucket", "aws_access_key_id", "aws_secret_access_key", "aws_session_token", mode="before")
    @classmethod
    def blank(cls, value): return None if value == "" else value

    def key(self):
        if not self.encryption_key: raise ValueError("Independent 256-bit backup encryption key required.")
        value = bytes.fromhex(self.encryption_key.get_secret_value())
        if len(value) != 32: raise ValueError("Exact 256-bit encryption key required.")
        return value

    def require_offsite(self):
        self.key()
        if not self.offsite_enabled or not self.s3_bucket or not (self.use_instance_role or self.aws_access_key_id and self.aws_secret_access_key):
            raise ValueError("Explicit offsite enablement and bucket/credentials or instance-role choice required.")


def encrypt_bytes(plaintext, key):
    if len(key) != 32 or len(plaintext) > MAX_BYTES: raise ValueError("Backup plaintext/key exceeds bounds.")
    nonce = secrets.token_bytes(12)
    header = MAGIC + sha256(key).digest()[:8] + nonce
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    cipher.update(header)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    return header + tag + ciphertext


def decrypt_bytes(payload, key):
    if len(key) != 32 or not 42 < len(payload) <= MAX_BYTES + 42 or payload[:6] != MAGIC or payload[6:14] != sha256(key).digest()[:8]:
        raise ValueError("Unknown backup envelope/key or size.")
    cipher = AES.new(key, AES.MODE_GCM, nonce=payload[14:26]); cipher.update(payload[:26])
    return cipher.decrypt_and_verify(payload[42:], payload[26:42])


def seal_snapshot(manifest_path, key, destination):
    manifest_path, destination = Path(manifest_path), Path(destination)
    manifest = verify(manifest_path)
    if sum(item["bytes"] for item in manifest["files"]) + manifest_path.stat().st_size > MAX_BYTES - 1024*1024:
        raise ValueError("Recovery bundle exceeds its 256 MiB bound.")
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", manifest_path.read_bytes())
        for item in manifest["files"]:
            raw = (manifest_path.parent / item["filename"]).read_bytes()
            if len(raw) != item["bytes"] or sha256(raw).hexdigest() != item["sha256"]: raise ValueError("Snapshot changed during encryption.")
            archive.writestr(item["filename"], raw)
    payload = encrypt_bytes(memory.getvalue(), key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as file: file.write(payload)
    return {"file": str(destination.resolve()), "bytes": len(payload), "sha256": sha256(payload).hexdigest(),
        "database_count": len(manifest["files"]), "encryption": "AES-256-GCM", "uploaded": False}


def open_snapshot(payload, key, destination):
    # Authentication/structural checks precede creating any destination path.
    plaintext = decrypt_bytes(payload, key)
    with zipfile.ZipFile(io.BytesIO(plaintext)) as archive:
        entries = archive.infolist()
        names = [item.filename for item in entries]
        if len(names) != len(set(names)) or not 2 <= len(names) <= MAX_DATABASES + 1 or "manifest.json" not in names:
            raise ValueError("Unknown/duplicate recovery archive entries.")
        if sum(item.file_size for item in entries) > MAX_BYTES or any(item.compress_type != zipfile.ZIP_STORED for item in entries):
            raise ValueError("Unsupported compressed/oversized recovery archive.")
        manifest_info = archive.getinfo("manifest.json")
        if manifest_info.file_size > 1024*1024: raise ValueError("Oversized recovery manifest.")
        raw_manifest = archive.read("manifest.json")
        manifest = json.loads(raw_manifest)
        expected = {"manifest.json"}
        files = {"manifest.json": raw_manifest}
        for item in manifest["files"]:
            required_tables(item["role"])
            if item["filename"] != item["role"] + ".sqlite3" or item["filename"] in expected: raise ValueError("Unsafe recovery filename/role.")
            expected.add(item["filename"])
            raw = archive.read(item["filename"])
            if len(raw) != item["bytes"] or sha256(raw).hexdigest() != item["sha256"]: raise ValueError("Encrypted snapshot file integrity failed.")
            files[item["filename"]] = raw
        if expected != set(names): raise ValueError("Unexpected recovery archive content.")
    destination = Path(destination).resolve(); destination.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        with (destination / name).open("xb") as file: file.write(raw)
    verify(destination / "manifest.json")
    return destination / "manifest.json"


def s3_client(settings):
    settings.require_offsite()
    import boto3
    from botocore.config import Config
    values = {}
    if not settings.use_instance_role:
        values = {"aws_access_key_id": settings.aws_access_key_id.get_secret_value(),
            "aws_secret_access_key": settings.aws_secret_access_key.get_secret_value()}
        if settings.aws_session_token: values["aws_session_token"] = settings.aws_session_token.get_secret_value()
    # Official AWS endpoint resolution, TLS verification and signing; no arbitrary
    # storage URL, browser upload, public ACL or cross-host credential redirect.
    return boto3.client("s3", region_name=settings.s3_region, config=Config(retries={"total_max_attempts": 1},
        connect_timeout=5, read_timeout=30), **values)


def object_key(settings, payload): return settings.s3_prefix + "/" + sha256(payload).hexdigest() + ".ldb"


def upload(settings, client, payload):
    settings.require_offsite()
    if not 42 < len(payload) <= MAX_BYTES+42 or payload[:6] != MAGIC: raise ValueError("Only bounded encrypted recovery envelopes may be uploaded.")
    # Validate the encryption key/tag before transmitting a local file.
    decrypt_bytes(payload, settings.key())
    key, digest = object_key(settings, payload), sha256(payload).hexdigest()
    try:
        client.put_object(Bucket=settings.s3_bucket, Key=key, Body=payload, ContentType="application/octet-stream",
            ServerSideEncryption="AES256", IfNoneMatch="*", ChecksumSHA256=base64.b64encode(sha256(payload).digest()).decode(),
            Metadata={"lobster-sha256": digest})
        existing = False
    except Exception as error:
        from botocore.exceptions import ClientError
        if not isinstance(error, ClientError) or error.response.get("Error", {}).get("Code") not in {"PreconditionFailed", "412"}: raise
        if download(settings, client, key) != payload: raise ValueError("Existing immutable backup content differs.")
        existing = True
    return {"object_key": key, "sha256": digest, "bytes": len(payload), "uploaded": True, "already_present": existing}


def download(settings, client, key):
    import re
    settings.require_offsite()
    if not re.fullmatch(re.escape(settings.s3_prefix) + r"/[a-f0-9]{64}\.ldb", key): raise ValueError("Unsafe/unrecognized remote backup key.")
    result = client.get_object(Bucket=settings.s3_bucket, Key=key)
    body = result["Body"]
    try:
        if not 42 < result["ContentLength"] <= MAX_BYTES+42: raise ValueError("Remote encrypted bundle exceeds bounds.")
        payload = body.read(MAX_BYTES+43)
    finally: body.close()
    if len(payload) != result["ContentLength"] or object_key(settings, payload) != key: raise ValueError("Remote backup bytes/hash differ.")
    decrypt_bytes(payload, settings.key())
    return payload
