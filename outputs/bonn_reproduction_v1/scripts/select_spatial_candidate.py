"""Freeze the predefined development selection before confirmation access."""
import argparse
import json
from pathlib import Path

from potato3d.spatial_study import select_candidate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("development", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    seal = select_candidate(args.development, args.out)
    print(json.dumps({"selected": seal["selected_option"], "scores": seal["selection_scores"]}, indent=2))
