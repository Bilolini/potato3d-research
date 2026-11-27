"""Fresh-process check on a separate validation fixture, not a scored study case."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from potato3d.completion import METHODS
from potato3d.development import DevelopmentShape
from potato3d.io import sha256, write_json
from potato3d.metrics import evaluate


def worker(path):
    path.mkdir()
    shape = DevelopmentShape(axes=(37., 26., 21.), waist=.27, yaw=-.45, underside_warp=1.2)
    observations = shape.partial(1500, 112358, outlier_fraction=.02)
    reference = shape.mesh()
    config = {"seed": 112359, "surface_samples": 2000, "thresholds_mm": [2., 5., 10.]}
    scores = []
    for method in ["symmetry", "symmetry_height95", "symmetry_robust95"]:
        mesh, parameters = METHODS[method](observations)
        mesh.export(path/f"{method}.ply")
        scores.append({"method": method, "parameters": parameters,
                       "metrics": evaluate(mesh, reference, observations, config,
                                           visible_partition=shape.visible, analytic_volume_ml=shape.volume_ml)})
    write_json(path/"scores.json", scores)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    if args.out is None or args.out.exists():
        parser.error("Specify a new --out path")
    with tempfile.TemporaryDirectory(prefix="potato-height-repeat-") as temporary:
        root = Path(temporary)
        for name in ["a", "b"]:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(root/name)], check=True)
        geometry_equal = all(sha256(p) == sha256(root/"b"/p.name) for p in sorted((root/"a").glob("*.ply")))
        metrics_equal = (root/"a/scores.json").read_bytes() == (root/"b/scores.json").read_bytes()
        report = {"fixture_role": "separate fixed validation fixture; not height_development_v1",
                  "fresh_processes": 2, "geometry_files": 3, "geometry_bytes_equal": geometry_equal,
                  "parameters_and_metrics_equal": metrics_equal, "script_sha256": sha256(Path(__file__))}
        write_json(args.out, report)
        print(json.dumps(report, indent=2))
        if not geometry_equal or not metrics_equal:
            raise SystemExit("Fresh-process reproducibility check failed")


if __name__ == "__main__":
    main()
