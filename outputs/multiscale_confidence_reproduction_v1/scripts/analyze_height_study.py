"""Analyze the sealed height study without selecting thresholds or cases."""
import argparse
from pathlib import Path

from potato3d.study_analysis import save_analysis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = save_analysis(args.run, args.out)
    print("Predefined synthetic development hypothesis supported:", report["predefined_development_hypothesis_supported"])
    for result in report["primary"]:
        print(result["metric"], result["mean"], result["ci95"], "families:", result["independent_families"])


if __name__ == "__main__":
    main()
