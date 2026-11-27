"""Validate local 3DPotatoTwin pairs and record their provenance before scoring."""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from potato3d.io import discover_demo, load_points, safe_path, sha256, write_json


DEMO_MANIFEST = Path(__file__).resolve().parents[2] / "data/demo_manifest.json"
INTRINSICS = "1_rgbd/0_camera_intrinsics/realsense_d405_camera_intrinsic.json"


def audit_raster(root, pair, matrix, size):
    key, frame = pair["object_id"], pair["frame_id"]
    folder = f"1_rgbd/1_image/{key}"
    paths = {role: f"{folder}/{key}_{role}_{frame}.png" for role in ("rgb", "depth")}
    images = {}
    for role, relative in paths.items():
        with Image.open(safe_path(root, relative)) as image:
            if image.size != size:
                raise ValueError(f"{key} {role} dimensions disagree with camera intrinsics")
            images[role] = np.array(image)
    rgb, depth = images["rgb"], images["depth"]
    if rgb.ndim != 3 or rgb.shape[-1] != 4 or depth.ndim != 2:
        raise ValueError(f"{key} requires an RGBA mask and single-channel depth")
    xyz = load_points(safe_path(root, pair["partial"]), pair["unit"])
    if np.any(xyz[:, 2] <= 0):
        raise ValueError(f"{key} has nonpositive camera depth")
    uvw = xyz @ matrix.T
    x, y = np.rint(uvw[:, :2] / uvw[:, 2:]).astype(int).T
    inside = (x >= 0) & (x < size[0]) & (y >= 0) & (y < size[1])
    if not inside.all():
        raise ValueError(f"{key} projects outside the released raster")
    error = np.abs(depth[y, x].astype(float)-xyz[:, 2])
    in_mask = np.mean(rgb[y, x, 3] > 0)
    if error.max() > .01 or in_mask < .99:
        raise ValueError(f"{key} failed the released PLY-to-RGB-D round trip")
    return paths, {"point_count": len(xyz), "mask_fraction": in_mask, "max_depth_error_mm": error.max()}


def build_manifest(root, allow_demo):
    demo = json.loads(DEMO_MANIFEST.read_text())["objects"]
    demo_ids = {row["object_id"] for row in demo}
    demo_inputs = {row["partial_sha256"] for row in demo}
    demo_references = {row["reference_sha256"] for row in demo}
    rows = discover_demo(root)
    if not allow_demo:
        for pair in rows:
            if (pair["object_id"] in demo_ids or pair["partial_sha256"] in demo_inputs
                    or pair["reference_sha256"] in demo_references):
                raise ValueError(f"{pair['object_id']} matches a previous demo object or asset")
    camera_path = safe_path(root, INTRINSICS)
    camera = json.loads(camera_path.read_text())
    matrix = np.asarray(camera["intrinsic_matrix"], dtype=float).reshape(3, 3, order="F")
    if not np.isfinite(matrix).all() or not np.array_equal(matrix[2], [0, 0, 1]) or min(matrix[0, 0], matrix[1, 1]) <= 0:
        raise ValueError("Invalid camera intrinsics")
    size = camera["width"], camera["height"]
    warnings = "3_pair/non-perfect.txt"
    if not (root / warnings).is_file() and (root / "non-perfect.txt").is_file():
        warnings = "non-perfect.txt"
    metadata = {"ground_truth": "ground_truth.csv", "intrinsics": INTRINSICS}
    if not allow_demo or (root / warnings).is_file():
        metadata["registration_warnings"] = warnings
    meta = {role: {"path": path, "sha256": sha256(safe_path(root, path))}
            for role, path in metadata.items()}

    records = []
    for pair in rows:
        key = pair["object_id"]
        raster, checks = audit_raster(root, pair, matrix, size)
        assets = {role: {"path": pair[role], "sha256": pair[f"{role}_sha256"]}
                  for role in ("partial", "reference", "registration")}
        assets.update({role: {"path": path, "sha256": sha256(safe_path(root, path))}
                       for role, path in raster.items()})
        records.append({"object_id": key, "frame_id": pair["frame_id"],
                        "cultivar": pair["cultivar"], "unit": pair["unit"],
                        "published_registration_rmse_mm": pair["published_registration_rmse_mm"],
                        "rgbd_to_sfm_m": pair["rgbd_to_sfm_m"], "files": assets, "raster_check": checks})
    return {"stage": "intake_demo_check" if allow_demo else "fresh_development_intake",
            "registration_warning_review": "pending manual review",
            "metadata": meta, "pairs": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--demo-check", action="store_true",
                        help="Allow the known demo pairs for an intake smoke check.")
    args = parser.parse_args()
    write_json(args.out, build_manifest(args.root, args.demo_check))


if __name__ == "__main__":
    main()
