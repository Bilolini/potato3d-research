"""Run reserved development or gated confirmation; never overwrite a run."""
import argparse
from pathlib import Path

from potato3d.io import write_json
from potato3d.pipeline import run
from potato3d.spatial_study import load_spatial_protocol, spatial_samples, study_config, validate_selection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["development", "confirmation"], required=True)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    protocol = load_spatial_protocol()
    selection = None
    if args.split == "confirmation":
        if args.selection is None:
            parser.error("Confirmation requires --selection from completed development")
        selection = validate_selection(args.selection)
    config = study_config(protocol, args.split, selection)
    rows = run(spatial_samples(protocol, config, confirmation_authorized=selection is not None), config, args.out, visualization=False)
    write_json(args.out/"protocol.json", protocol)
    failures = sum(r["status"] != "ok" for r in rows)
    print(f"{len(rows)} {args.split} predictions; {failures} failures")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
