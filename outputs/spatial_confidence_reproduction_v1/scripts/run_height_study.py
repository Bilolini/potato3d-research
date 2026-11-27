"""Run the sealed fresh synthetic development protocol once, serially on CPU."""
import argparse
from pathlib import Path

from potato3d.development import development_samples, load_protocol
from potato3d.io import write_json
from potato3d.pipeline import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=Path("configs/height_development_v1.yaml"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    protocol, config = load_protocol(args.protocol)
    rows = run(development_samples(protocol, config), config, args.out, visualization=False)
    write_json(args.out/"protocol.json", protocol)
    failures = sum(r["status"] != "ok" for r in rows)
    print(f"{len(rows)} predictions, {failures} failures; analyze all rows before drawing conclusions")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
