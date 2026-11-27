"""Analyze the reserved multiscale run with all feature-preservation criteria."""
import argparse
from pathlib import Path

from potato3d.multiscale_analysis import save_analysis


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = save_analysis(args.run, args.out)
    print(report["split"], report["predictions"], "predictions; failures", report["failed_predictions"])
    print("Predefined confirmation supported:", report["predefined_confirmation_supported"])
    for c in report["confirmation_criteria"]:
        print(c["condition"], c["metric"], "vs", c["baseline"], c["mean"], c["ci95"], "passed:", c["passed"])
