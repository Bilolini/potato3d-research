"""Reaggregate stored per-frame metrics, with equal weight per object."""
import argparse
import json
from pathlib import Path

from potato3d.io import write_json
from potato3d.pipeline import summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists")
    rows = json.loads(args.results.read_text())
    config = json.loads(args.results.with_name("config.json").read_text())
    write_json(args.out, summarize(rows, config["bootstrap_replicates"], config["seed"]))


if __name__ == "__main__":
    main()
