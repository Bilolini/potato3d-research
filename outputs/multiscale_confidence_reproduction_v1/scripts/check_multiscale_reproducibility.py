"""Two fresh processes on separate patch/feature fixtures, never scored families."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import trimesh

from potato3d.completion import METHODS
from potato3d.io import sha256, write_json
from potato3d.metrics import evaluate
from potato3d.multiscale_study import validate_selection
from potato3d.protrusions import ProtrusionShape


def worker(path, parameters):
    path.mkdir()
    options = json.loads(parameters.read_text())
    config = {"seed": 8202, "surface_samples": 2000, "thresholds_mm": [2., 5., 10.]}
    scores = []
    for condition in ["patch", "genuine_feature"]:
        shape = ProtrusionShape(axes=(37., 27., 20.), waist=.24, yaw=.57, underside_warp=.9,
                                bump_amplitude_mm=8. if condition == "genuine_feature" else 0., bump_radius_unit=.13)
        points = shape.partial(1500, 8201)
        if condition == "patch":
            center = np.array([.25*37, .20*27, 0.])@shape.rotation.T
            ids = np.argsort(np.linalg.norm(points[:, :2]-center[:2], axis=1), kind="stable")[:30]
            points[ids, 2] += 15
        reference = shape.mesh(5)
        trimesh.points.PointCloud(points).export(path/f"{condition}_partial.ply")
        reference.export(path/f"{condition}_reference.ply")
        for method in ["symmetry_spatial", "symmetry_annular", "symmetry_multiscale"]:
            mesh, fitted = METHODS[method](points, **(options if method != "symmetry_spatial" else {}))
            mesh.export(path/f"{condition}_{method}.ply")
            scores.append({"condition": condition, "method": method, "parameters": fitted,
                           "metrics": evaluate(mesh, reference, points, config,
                                               visible_partition=shape.visible, analytic_volume_ml=shape.volume_ml)})
    write_json(path/"scores.json", scores)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--parameters", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.parameters)
    else:
        if args.selection is None or args.out is None or args.out.exists():
            parser.error("Require --selection and a new --out")
        selection = validate_selection(args.selection)
        with tempfile.TemporaryDirectory(prefix="potato-multiscale-repeat-") as temporary:
            root = Path(temporary)
            write_json(root/"parameters.json", selection["selected_parameters"])
            for name in ["a", "b"]:
                subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(root/name),
                                "--parameters", str(root/"parameters.json")], check=True)
            files = sorted((root/"a").glob("*.ply"))
            geometry_equal = all(sha256(p) == sha256(root/"b"/p.name) for p in files)
            metrics_equal = (root/"a/scores.json").read_bytes() == (root/"b/scores.json").read_bytes()
            report = {"role": "separate patch and genuine-feature validation fixtures", "fresh_processes": 2,
                      "geometry_files": len(files), "geometry_bytes_equal": geometry_equal,
                      "parameters_and_metrics_equal": metrics_equal, "selection_sha256": sha256(args.selection),
                      "script_sha256": sha256(Path(__file__))}
            write_json(args.out, report)
            print(json.dumps(report, indent=2))
            if not geometry_equal or not metrics_equal:
                raise SystemExit("Reproducibility mismatch")
