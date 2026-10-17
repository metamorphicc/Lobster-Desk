"""Owner-operated SQLite backup, verification and isolated restore drill."""

import argparse
from pathlib import Path
from uuid import uuid4

from lobster.config import Settings
from lobster.domain import utcnow
from lobster.execution.settings import TestnetSettings
from lobster.ops.backup import restore_drill, snapshot, sqlite_path, verify
from lobster.ops.inventory import discover_sources
from lobster.execution.project import ProjectSettings
from lobster.users.contracts import UserTestnetSettings
from lobster.ops.alerts import AlertSettings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--verify", type=Path, metavar="MANIFEST")
    actions.add_argument("--restore", type=Path, metavar="MANIFEST")
    parser.add_argument("--destination", type=Path, help="A new directory; an existing path is always refused")
    parser.add_argument("--treasury-book", type=Path, help="Override the configured treasury book path")
    args = parser.parse_args()
    try:
        if args.verify:
            result = verify(args.verify)
            print("Verified snapshot roles: " + ", ".join(item["role"] for item in result["files"]))
        elif args.restore:
            destination = args.destination or Path("artifacts/restore-drills") / (utcnow().strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8])
            restore_drill(args.restore, destination)
            print(f"Isolated restore verified: {destination.resolve()}")
            print("Live databases were not replaced. Exchange state and signer nonces still require recovery review.")
        else:
            config = Settings()
            if args.treasury_book is not None: config.treasury_path = str(args.treasury_book)
            sources = discover_sources(config, TestnetSettings(), ProjectSettings(), UserTestnetSettings(), operations_path=AlertSettings().state_path)
            destination = args.destination or Path("artifacts/backups") / (utcnow().strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8])
            manifest = snapshot(sources, destination)
            print(f"Verified SQLite snapshot: {manifest.resolve()}")
    except FileExistsError:
        parser.exit(1, "Destination already exists. Choose a new directory; no existing database is overwritten.\n")
    except Exception:
        # Never print a database URL or a configuration exception containing credentials.
        parser.exit(1, "Backup/restore could not complete. Check SQLite file paths, permissions and manifest integrity. No live database was replaced.\n")
