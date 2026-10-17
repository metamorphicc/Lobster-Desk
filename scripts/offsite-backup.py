"""Owner-operated encrypted recovery. No network in default inspection mode."""
import argparse
import json
from pathlib import Path
from uuid import uuid4

from lobster.config import Settings
from lobster.domain import utcnow
from lobster.execution.project import ProjectSettings
from lobster.execution.settings import TestnetSettings
from lobster.users.contracts import UserTestnetSettings
from lobster.ops.backup import snapshot
from lobster.ops.inventory import discover_sources
from lobster.ops.offsite import OffsiteSettings, seal_snapshot, open_snapshot, upload, download, s3_client


def main(args):
    settings = OffsiteSettings()
    if not any((args.seal, args.open, args.upload, args.fetch, args.snapshot)):
        print(json.dumps({"offsite_enabled": settings.offsite_enabled, "encryption_configured": bool(settings.encryption_key),
            "storage_configured": bool(settings.s3_bucket), "network_attempted": False})); return
    if args.seal or args.open or args.snapshot:
        key = settings.key()
        if args.open:
            if not args.destination: raise ValueError("A new isolated destination directory is required.")
            manifest = open_snapshot(args.open.read_bytes(), key, args.destination)
            print(json.dumps({"verified_manifest": str(manifest), "live_database_replaced": False, "exchange_reconciled": False})); return
        manifest = args.seal
        if args.snapshot:
            sources = discover_sources(Settings(), TestnetSettings(), ProjectSettings(), UserTestnetSettings())
            folder = Path("artifacts/backups") / (utcnow().strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8])
            manifest = snapshot(sources, folder)
        if not args.output: raise ValueError("An unused encrypted output filename is required.")
        print(json.dumps(seal_snapshot(manifest, key, args.output))); return
    if args.upload:
        if not args.arm: raise ValueError("Explicit --arm is required for offsite upload.")
        payload = args.upload.read_bytes()
        print(json.dumps(upload(settings, s3_client(settings), payload))); return
    if args.fetch:
        if not args.output: raise ValueError("An unused encrypted output filename is required.")
        payload = download(settings, s3_client(settings), args.fetch)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as file: file.write(payload)
        print(json.dumps({"downloaded": True, "bytes": len(payload), "live_database_replaced": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--seal", type=Path, metavar="MANIFEST")
    actions.add_argument("--open", type=Path, metavar="ENCRYPTED_FILE")
    actions.add_argument("--snapshot", action="store_true")
    actions.add_argument("--upload", type=Path, metavar="ENCRYPTED_FILE")
    actions.add_argument("--fetch", metavar="OBJECT_KEY")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--arm", action="store_true")
    try: main(parser.parse_args())
    except Exception: parser.exit(1, "Encrypted recovery operation failed. Check exact inventory, unused destinations, encryption key and explicit storage configuration. No live database was replaced; credentials were not printed.\n")
