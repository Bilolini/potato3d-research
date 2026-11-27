"""Geometry validation, explicit transforms and deterministic area sampling."""
from __future__ import annotations

import numpy as np
import trimesh


def validate_points(points: np.ndarray, minimum: int = 4) -> np.ndarray:
    p = np.asarray(points, dtype=np.float64)
    if p.ndim != 2 or p.shape[1] != 3 or len(p) < minimum:
        raise ValueError(f"Expected at least {minimum} XYZ points, got {p.shape}")
    if not np.isfinite(p).all():
        raise ValueError("Non-finite coordinates; exclude explicitly rather than silently dropping")
    if np.linalg.matrix_rank(p - p.mean(axis=0)) < 3:
        raise ValueError("Point cloud is degenerate (not three-dimensional)")
    return p


def check_scale_mm(points: np.ndarray) -> dict:
    p = validate_points(points)
    extent = np.ptp(p, axis=0)
    if extent.max() < 1 or extent.max() > 1000:
        raise ValueError(f"Implausible potato extent in mm: {extent}; check declared units")
    return {"bounds_mm": [p.min(axis=0).tolist(), p.max(axis=0).tolist()],
            "extents_mm": extent.tolist(), "point_count": len(p)}


def rigid_matrix(matrix: np.ndarray) -> np.ndarray:
    t = np.asarray(matrix, dtype=float)
    if t.shape != (4, 4) or not np.isfinite(t).all():
        raise ValueError("Expected finite 4x4 transform")
    if not np.allclose(t[3], [0, 0, 0, 1], atol=1e-8):
        raise ValueError("Invalid homogeneous transform")
    if not np.allclose(t[:3, :3].T @ t[:3, :3], np.eye(3), atol=1e-5):
        raise ValueError("Transform contains scaling/shear")
    if not np.isclose(np.linalg.det(t[:3, :3]), 1, atol=1e-5):
        raise ValueError("Transform changes handedness")
    return t


def transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    t = rigid_matrix(matrix)
    return np.asarray(points) @ t[:3, :3].T + t[:3, 3]


def camera_to_belt_mm(belt_depth_mm: float) -> np.ndarray:
    """Input already in mm: x right, y down, z away -> x right, y up, z height."""
    if not np.isfinite(belt_depth_mm) or belt_depth_mm <= 0:
        raise ValueError("A positive externally specified camera-to-belt depth is required")
    t = np.diag([1., -1., -1., 1.])
    t[2, 3] = belt_depth_mm
    return t


def sample_surface(mesh: trimesh.Trimesh, count: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Uniform triangle-area sampling, local RNG only; returns points and face IDs."""
    if count < 1:
        raise ValueError("Surface sample count must be positive")
    areas = np.asarray(mesh.area_faces)
    if len(areas) == 0 or not np.isfinite(areas).all() or areas.sum() <= 0:
        raise ValueError("Cannot sample an empty or invalid mesh")
    rng = np.random.default_rng(seed)
    faces = rng.choice(len(areas), size=count, p=areas / areas.sum())
    triangles = mesh.triangles[faces]
    uv = rng.random((count, 2))
    outside = uv.sum(axis=1) > 1
    uv[outside] = 1 - uv[outside]
    points = triangles[:, 0] + uv[:, :1] * (triangles[:, 1] - triangles[:, 0])
    points += uv[:, 1:] * (triangles[:, 2] - triangles[:, 0])
    return points, faces


def mesh_quality(mesh: trimesh.Trimesh) -> dict:
    if len(mesh.faces) == 0:
        raise ValueError("Expected triangular mesh")
    _, counts = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
    finite = bool(np.isfinite(mesh.vertices).all())
    winding = bool(mesh.is_winding_consistent)
    watertight = bool(mesh.is_watertight)
    volume_valid = finite and watertight and winding and mesh.volume > 0
    return {"vertices": len(mesh.vertices), "faces": len(mesh.faces),
            "watertight": watertight, "winding_consistent": winding,
            "boundary_edges": int(np.sum(counts == 1)),
            "nonmanifold_edges": int(np.sum(counts > 2)),
            "degenerate_faces": int(np.sum(mesh.area_faces < 1e-10)),
            "finite": finite, "positive_orientation": bool(mesh.volume > 0),
            "volume_ml": float(mesh.volume / 1000) if volume_valid else None,
            "volume_valid": volume_valid}


def subset(points: np.ndarray, maximum: int, seed: int) -> np.ndarray:
    if maximum < 4:
        raise ValueError("Need at least four fit points")
    if len(points) <= maximum:
        return points.copy()
    indices = np.sort(np.random.default_rng(seed).choice(len(points), maximum, replace=False))
    return points[indices]
