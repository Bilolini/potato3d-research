"""Apply the sealed two-option development selection and freeze its evidence."""
import argparse
import json
from pathlib import Path

from potato3d.multiscale_study import select_candidate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("development", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    selection = select_candidate(args.development, args.out)
    print(json.dumps({"selected": selection["selected_option"], "scores": selection["selection_scores"]}, indent=2))
