"""Report a locked pilot rehearsal; never activates trading or reads credentials."""
import argparse
import json
from pathlib import Path

from lobster.ops.pilot import PilotPlan, PilotObservation, assess

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("release/pilot-plan.json"))
    parser.add_argument("--observation", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        for path in [args.plan, args.observation]:
            if path and path.stat().st_size > 100_000: raise ValueError()
        plan = PilotPlan.model_validate_json(args.plan.read_text(encoding="utf-8"))
        observation = PilotObservation.model_validate_json(args.observation.read_text(encoding="utf-8")) if args.observation else None
        report = assess(plan, observation)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output: json.dump(report, output, indent=2)
        print("Pilot rehearsal saved. Mainnet implementation/activation: disabled.")
    except Exception:
        parser.exit(1, "Pilot report refused. Check exact decimal inputs and a new output path.\n")
