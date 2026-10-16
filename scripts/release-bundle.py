"""Package committed source locally. Never pushes, deploys or opens network access."""
import argparse
from pathlib import Path

from lobster.ops.release import ReleaseConfig, bundle

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("release/local-paper.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = ReleaseConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
        result = bundle(Path(__file__).resolve().parents[1], args.output, config)
        print("Committed source packaged locally at " + str(args.output.resolve()))
        print("Revision: " + result["revision"] + "; production/exchange/token activation: disabled.")
    except Exception:
        parser.exit(1, "Packaging refused. Check clean codex/ branch, tracked paths, local-only config and a new output directory.\n")
