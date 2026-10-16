"""Report the agreed fee/profit/burn policy. Never signs or transfers funds."""
import argparse
import json
from pathlib import Path

from lobster.economics.book import TreasuryBook
from lobster.economics.distribution import DistributionPolicy, distribution

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", type=Path, default=Path("data/treasury.sqlite3"))
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists(): raise ValueError()
        if args.policy and args.policy.stat().st_size > 100_000: raise ValueError()
        policy = DistributionPolicy.model_validate_json(args.policy.read_text(encoding="utf-8")) if args.policy else DistributionPolicy()
        report = distribution(TreasuryBook(args.book), policy)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output: json.dump(report, output, indent=2)
        print("Distribution accounting exported. No transfers or burns were executed.")
    except Exception:
        parser.exit(1, "Distribution report failed. Check receipts, exact policy and a new output path.\n")
