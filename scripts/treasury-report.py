"""Append a local receipt or export accounting. No chain RPC, keys or transfers."""
import argparse
import json
from pathlib import Path

from lobster.economics.book import EconomicPolicy, TreasuryBook, TreasuryEntry

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", type=Path, default=Path("data/treasury.sqlite3"))
    parser.add_argument("--policy", type=Path, default=Path("release/economic-policy.json"))
    parser.add_argument("--append", type=Path, help="Private owner-supplied receipt JSON; never authenticated automatically")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists(): raise ValueError()
        for path in [args.policy, args.append]:
            if path and path.stat().st_size > 100_000: raise ValueError()
        policy = EconomicPolicy.model_validate_json(args.policy.read_text(encoding="utf-8"))
        entry = TreasuryEntry.model_validate_json(args.append.read_text(encoding="utf-8")) if args.append else None
        book = TreasuryBook(args.book)
        if entry: book.append(entry)
        report = book.report(policy)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output: json.dump(report, output, indent=2)
        print("Local accounting exported. Receipts remain unverified; transfers/token operations: disabled.")
    except Exception:
        parser.exit(1, "Treasury reporting failed. Reconcile receipt identity, exact amounts, policy and a new output path.\n")
