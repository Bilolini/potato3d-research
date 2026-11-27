"""Commands are intentionally small; output directories must be new."""
import argparse
from pathlib import Path

from .io import discover_demo, load_demo_pair, write_json
from .pipeline import Sample, inspect_demo, load_config, run, synthetic_samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Audit real demo geometry and metadata")
    inspect.add_argument("--data", type=Path, required=True)
    inspect.add_argument("--belt-depth-mm", type=float, required=True)
    inspect.add_argument("--out", type=Path, required=True)
    for name in ["synthetic", "demo"]:
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, default=Path("configs/baseline.yaml"))
        command.add_argument("--out", type=Path, required=True)
        command.add_argument("--no-visualization", action="store_true")
        if name == "synthetic":
            command.add_argument("--study", action="store_true", help="Two analytic shapes x four matched corruption regimes")
        else:
            command.add_argument("--data", type=Path, required=True)
            command.add_argument("--belt-depth-mm", type=float, required=True,
                                 help="External calibration assumption; ~350 mm for this 2023 demo")
            command.add_argument("--object-id", action="append", help="Optional explicit subset of object IDs")
    args = parser.parse_args()
    if args.command == "inspect":
        if args.out.exists():
            parser.error("Inspection output exists; choose a new path")
        audit = inspect_demo(args.data, args.belt_depth_mm)
        write_json(args.out, audit)
        print(f"{audit['unique_objects']} objects; {audit['available_partial_frames']} partial frames; {audit['registered_frames']} registered pairs")
        return
    config = load_config(args.config)
    if args.command == "synthetic":
        samples = synthetic_samples(config, args.study)
    else:
        records = discover_demo(args.data)
        if args.object_id:
            missing = set(args.object_id)-{r["object_id"] for r in records}
            if missing:
                parser.error(f"Unknown object IDs: {missing}")
            records = [r for r in records if r["object_id"] in args.object_id]
        def real_samples():
            for record in records:
                points, reference, metadata = load_demo_pair(args.data, record, args.belt_depth_mm)
                yield Sample(record["object_id"], record["frame_id"], "registered_center", points, reference, metadata)
        samples = real_samples()
    rows = run(samples, config, args.out, not args.no_visualization)
    failures = sum(r["status"] != "ok" for r in rows)
    print(f"Saved {len(rows)} predictions ({failures} failures) to {args.out}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
