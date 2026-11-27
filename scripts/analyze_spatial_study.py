"""Apply the fixed analysis to one completed spatial study split."""
import argparse
from pathlib import Path

from potato3d.spatial_analysis import save_spatial_analysis


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = save_spatial_analysis(args.run, args.out)
    print(report["split"], report["predictions"], "predictions; failures", report["failed_predictions"])
    print("Predefined confirmation supported:", report["predefined_confirmation_supported"])
    for result in report["confirmation_criteria"]:
        print(result["condition"], result["metric"], "vs", result["baseline"], result["mean"], result["ci95"], "passed:", result["passed"])
