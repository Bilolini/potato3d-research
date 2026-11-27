"""Strict dataset discovery: use the released named registration pair only."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import trimesh

from .geometry import (camera_to_belt_mm, check_scale_mm, mesh_quality,
                       rigid_matrix, transform_points)


def sha256(path: Path) -> str:
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def write_json(path: Path, value) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    def convert(x):
        if isinstance(x, np.ndarray):
            return x.tolist()
        if isinstance(x, np.generic):
            return x.item()
        if isinstance(x, Path):
            return str(x)
        raise TypeError(f"Cannot serialize {type(x)}")
    Path(path).write_text(json.dumps(value, indent=2, default=convert, allow_nan=False) + "\n")


def safe_path(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"Dataset path escapes root: {relative}")
    if not target.is_file():
        raise FileNotFoundError(target)
    return target


def load_mesh(path: Path, unit: str) -> trimesh.Trimesh:
    scale = {"m": 1000., "mm": 1.}.get(unit)
    if scale is None:
        raise ValueError("Declare geometry units as 'm' or 'mm'; no automatic guessing")
    mesh = trimesh.load(path, force="mesh", process=False, skip_materials=True)
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces):
        raise ValueError(f"Not a triangle mesh: {path}")
    mesh.vertices *= scale
    check_scale_mm(mesh.vertices)
    return mesh


def load_points(path: Path, unit: str) -> np.ndarray:
    if unit not in ("m", "mm"):
        raise ValueError("Declare point units as 'm' or 'mm'")
    cloud = trimesh.load(path, process=False)
    if isinstance(cloud, trimesh.Scene):
        raise ValueError("Expected a single point cloud, not a scene")
    points = np.asarray(cloud.vertices, dtype=float) * (1000 if unit == "m" else 1)
    check_scale_mm(points)
    return points


def discover_demo(root: Path) -> list[dict]:
    root = Path(root).resolve()
    matrix_dir = root / "3_pair" / "tmatrix"
    if not matrix_dir.is_dir():
        raise FileNotFoundError(f"Expected demo registration folder: {matrix_dir}")
    with safe_path(root, "ground_truth.csv").open(newline="") as f:
        metadata = {row["label"]: row for row in csv.DictReader(f)}
    records = []
    for path in sorted(matrix_dir.glob("*.json")):
        registration = json.loads(path.read_text())
        rigid_matrix(registration["T"])
        pid = path.stem
        if pid not in metadata:
            raise ValueError(f"Missing ground_truth.csv entry for {pid}")
        source = safe_path(root, registration["rgbd_pcd_file"])
        reference = safe_path(root, registration["sfm_mesh_file"])
        if source.parent.name != pid or reference.parent.name != pid:
            raise ValueError(f"Object identity mismatch in registration {path}")
        frames = sorted(source.parent.glob(f"{pid}_pcd_*.ply"))
        row = metadata[pid]
        records.append({"object_id": pid, "frame_id": source.stem.rsplit("_", 1)[1],
                        "split": "demo_smoke_only", "unit": "m", "partial": str(source.relative_to(root)),
                        "reference": str(reference.relative_to(root)),
                        "registration": str(path.relative_to(root)),
                        "rgbd_to_sfm_m": registration["T"],
                        "partial_sha256": sha256(source), "reference_sha256": sha256(reference),
                        "registration_sha256": sha256(path), "ground_truth_sha256": sha256(root / "ground_truth.csv"),
                        "available_frames": len(frames), "evaluatable_registered_frames": 1,
                        "rgb_images": len(list((root/"1_rgbd/1_image"/pid).glob("*_rgb_*.png"))),
                        "depth_images": len(list((root/"1_rgbd/1_image"/pid).glob("*_depth_*.png"))),
                        "cultivar": row.get("cultivar"),
                        "physical_volume_ml": float(row["volume_ml"]) if row.get("volume_ml") else None,
                        "reported_sfm_volume_ml": float(row["volume_metashape"]) if row.get("volume_metashape") else None,
                        "measured_dimensions_mm": [float(row[k]) for k in ("x1_length_mm", "x2_width_mm", "x3_depth_mm")],
                        "published_registration_rmse_mm": registration.get("open3d_inlier_rmse", 0) * 1000})
    if not records:
        raise ValueError("No registered demo pairs found")
    return records


def load_demo_pair(root: Path, record: dict, belt_depth_mm: float):
    root = Path(root)
    # Camera-to-belt depends only on external calibration, never the reference mesh.
    canonical = camera_to_belt_mm(belt_depth_mm)
    points = transform_points(load_points(safe_path(root, record["partial"]), record["unit"]), canonical)
    reference = load_mesh(safe_path(root, record["reference"]), record["unit"])
    sfm_to_camera = np.linalg.inv(rigid_matrix(record["rgbd_to_sfm_m"]))
    sfm_to_camera[:3, 3] *= 1000
    reference.apply_transform(canonical @ sfm_to_camera)
    # Do not ICP-align, fill holes, recenter or rescale using test/reference geometry.
    if points[:, 2].min() < 0:
        raise ValueError("Scan extends below supplied belt depth; verify calibration")
    return points, reference, {**record, "belt_depth_mm": belt_depth_mm,
                              "belt_calibration_status": "approximate paper value, not per-scan calibration",
                              "camera_mm_to_belt_mm": canonical.tolist(),
                              "sfm_mm_to_belt_mm": (canonical @ sfm_to_camera).tolist(),
                              "partial_geometry": check_scale_mm(points),
                              "reference_geometry": check_scale_mm(reference.vertices),
                              "reference_quality": mesh_quality(reference)}
