"""Fresh-process validation on a separate fixture with frozen selected parameters."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import trimesh

from potato3d.completion import METHODS
from potato3d.development import DevelopmentShape
from potato3d.io import sha256, write_json
from potato3d.metrics import evaluate
from potato3d.spatial_study import validate_selection


def worker(output, parameters_path):
    output.mkdir()
    parameters = json.loads(parameters_path.read_text())
    shape = DevelopmentShape(axes=(35., 26., 19.), waist=.23, yaw=-.37, underside_warp=.9)
    points = shape.partial(1500, 7201, outlier_fraction=.02)
    reference = shape.mesh()
    trimesh.points.PointCloud(points).export(output/"partial.ply")
    reference.export(output/"reference.ply")
    config = {"seed": 7202, "surface_samples": 2000, "thresholds_mm": [2., 5., 10.]}
    scores = []
    for method in ["symmetry", "symmetry_robust95", "symmetry_spatial_height", "symmetry_spatial_surface", "symmetry_spatial"]:
        options = parameters if method.startswith("symmetry_spatial") else {}
        mesh, fitted = METHODS[method](points, **options)
        mesh.export(output/f"{method}.ply")
        scores.append({"method": method, "parameters": fitted,
                       "metrics": evaluate(mesh, reference, points, config,
                                           visible_partition=shape.visible, analytic_volume_ml=shape.volume_ml)})
    write_json(output/"scores.json", scores)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--parameters", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.parameters)
        return
    if args.selection is None or args.out is None or args.out.exists():
        parser.error("Require --selection and a new --out")
    selection = validate_selection(args.selection)
    with tempfile.TemporaryDirectory(prefix="potato-spatial-repeat-") as temporary:
        root = Path(temporary)
        write_json(root/"parameters.json", selection["selected_parameters"])
        for name in ["a", "b"]:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(root/name),
                            "--parameters", str(root/"parameters.json")], check=True)
        files = sorted((root/"a").glob("*.ply"))
        geometry_equal = all(sha256(p) == sha256(root/"b"/p.name) for p in files)
        scores_equal = (root/"a/scores.json").read_bytes() == (root/"b/scores.json").read_bytes()
        report = {"scope": "separate fixed validation fixture, not reserved development/confirmation cases",
                  "selection_sha256": sha256(args.selection), "script_sha256": sha256(Path(__file__)),
                  "fresh_processes": 2, "geometry_files": len(files), "geometry_bytes_equal": geometry_equal,
                  "parameters_and_metrics_equal": scores_equal}
        write_json(args.out, report)
        print(json.dumps(report, indent=2))
        if not geometry_equal or not scores_equal:
            raise SystemExit("Fresh-process spatial reproducibility check failed")


if __name__ == "__main__":
    main()
