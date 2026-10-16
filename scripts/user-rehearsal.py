"""Run all user lifecycle scenarios offline. Requires no funds, keys, wallet or network."""
import argparse
import asyncio
from pathlib import Path

from lobster.users.rehearsal import run_rehearsal

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="A new private output directory; never overwrites previous evidence")
    args = parser.parse_args()
    try:
        report = asyncio.run(run_rehearsal(args.output))
        print(f"Offline user rehearsal: {len(report['scenarios'])} scenarios passed. Report: {args.output.resolve() / 'report.json'}")
        print("Synthetic fixtures only. Production writer remains locked; funded acceptance is unverified.")
    except Exception:
        parser.exit(1, "Offline rehearsal failed. Choose a new output directory and inspect the local test suite; no exchange write was attempted.\n")
