"""Create or inventory a private owner acceptance record. Never signs or trades."""
import argparse
import json
from pathlib import Path

from lobster.ops.acceptance import AcceptanceRecord, inventory, template

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["template", "inventory"])
    parser.add_argument("--record", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == "template": result = template()
        else:
            if not args.record or args.record.stat().st_size > 100_000: raise ValueError()
            result = inventory(AcceptanceRecord.model_validate_json(args.record.read_text(encoding="utf-8")), args.record.parent)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output: json.dump(result, output, indent=2)
        print("Private evidence record written. Acceptance and execution remain unverified/disabled.")
    except Exception:
        parser.exit(1, "Evidence preparation failed. Check the record, contained evidence files and a new output path.\n")
