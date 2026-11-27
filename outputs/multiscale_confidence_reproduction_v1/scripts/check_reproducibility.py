"""Repeat the analytic CPU experiment and compare exported geometry and scores."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from potato3d.io import sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/baseline.yaml"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists")
    with tempfile.TemporaryDirectory(prefix="potato3d-repeat-") as temporary:
        root = Path(temporary)
        for name in ["a", "b"]:
            subprocess.run([sys.executable, "-m", "potato3d.cli", "synthetic", "--config", str(args.config),
                            "--out", str(root/name), "--no-visualization"], check=True)
        paths = sorted(p.relative_to(root/"a") for p in (root/"a").rglob("*.ply"))
        geometry_equal = all(sha256(root/"a"/p) == sha256(root/"b"/p) for p in paths)
        def scores(name):
            rows = json.loads((root/name/"results.json").read_text())
            return [{k: v for k, v in row.items() if not k.endswith("_seconds")} for row in rows]
        metrics_equal = scores("a") == scores("b")
        report = {"geometry_bytes_equal": geometry_equal, "geometry_files": len(paths),
                  "non_timing_metrics_equal": metrics_equal, "scope": "one analytic object, all three baselines, two fresh processes"}
        write_json(args.out, report)
        if not geometry_equal or not metrics_equal:
            raise SystemExit("Reproducibility mismatch; inspect dependency/platform effects")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
