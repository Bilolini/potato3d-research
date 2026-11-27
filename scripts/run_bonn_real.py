"""Run sealed lab-fruit priors, development selection, holdout and analysis."""
import argparse
from pathlib import Path
from potato3d.fruit_study import analyze, run, select, train


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["train", "development", "select", "holdout", "analyze"])
    parser.add_argument("--data", type=Path, default=Path("data/raw/bonn_real_v1"))
    parser.add_argument("--prior", type=Path, default=Path("outputs/bonn_prior_v1"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "train":
        train(args.data, args.out)
    elif args.stage in {"development", "holdout"}:
        run(args.data, args.prior, args.stage, args.out, args.selection)
    elif args.stage == "select":
        print(select(args.input, args.out))
    else:
        analyze(args.input, args.out)
