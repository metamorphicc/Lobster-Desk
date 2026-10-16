"""Link supplied buyback/disposal observations locally. Never signs, swaps or burns."""
import argparse
import json
from pathlib import Path

from lobster.economics.book import TreasuryBook
from lobster.economics.buybacks import BuybackBook, Purchase, BurnObservation

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", type=Path, default=Path("data/treasury.sqlite3"))
    parser.add_argument("--purchase", type=Path)
    parser.add_argument("--disposal", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists(): raise ValueError()
        for path in [args.purchase, args.disposal]:
            if path and path.stat().st_size > 100_000: raise ValueError()
        purchase = Purchase.model_validate_json(args.purchase.read_text(encoding="utf-8")) if args.purchase else None
        disposal = BurnObservation.model_validate_json(args.disposal.read_text(encoding="utf-8")) if args.disposal else None
        book = BuybackBook(TreasuryBook(args.book))
        if purchase: book.purchase(purchase)
        if disposal: book.disposal(disposal)
        report = book.report()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output: json.dump(report, output, indent=2)
        print("Private buyback observations exported. Actual chain verification/operations: disabled.")
    except Exception:
        parser.exit(1, "Buyback report refused. Reconcile receipt links, quantities, asset/network and a new output path.\n")
