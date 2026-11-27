"""Run reserved development or gated confirmation with genuine-feature controls."""
import argparse
from pathlib import Path

from potato3d.io import write_json
from potato3d.multiscale_study import load_protocol, make_config, samples, validate_selection
from potato3d.pipeline import run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["development", "confirmation"], required=True)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    protocol = load_protocol()
    selection = None
    if args.split == "confirmation":
        if args.selection is None:
            parser.error("Require a frozen --selection for confirmation")
        selection = validate_selection(args.selection)
    config = make_config(protocol, args.split, selection)
    rows = run(samples(protocol, config, confirmation_authorized=selection is not None), config, args.out, visualization=False)
    write_json(args.out/"protocol.json", protocol)
    failures = sum(r["status"] != "ok" for r in rows)
    print(f"{len(rows)} {args.split} predictions; {failures} failures")
    if failures:
        raise SystemExit(1)
