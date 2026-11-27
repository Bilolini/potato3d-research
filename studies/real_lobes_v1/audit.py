"""Audit vertical reference coverage using existing registered development pairs."""
import argparse
from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull, cKDTree

from potato3d.io import discover_demo, load_demo_pair, write_json


def reference_heights(mesh, xy, merge_mm=1e-4):
    """Return lower/upper heights where exactly one outward-oriented pair exists."""
    triangles = mesh.triangles
    origin = triangles[:, 0, :2]
    u, v = (triangles[:, 1:, :2] - origin[:, None]).transpose(1, 0, 2)
    det = u[:, 0]*v[:, 1] - u[:, 1]*v[:, 0]
    hits = [[] for _ in xy]
    tree = cKDTree(xy)

    # Each projected triangle fits inside this circle. Barycentric tests below
    # perform the exact intersection on every candidate inside the circle.
    for batch in np.array_split(np.flatnonzero(np.abs(det) > 1e-10),
                                max(1, (len(det)+4095)//4096)):
        projected = triangles[batch, :, :2]
        centers = projected.mean(axis=1)
        radii = np.linalg.norm(projected-centers[:, None], axis=2).max(axis=1)
        candidates = tree.query_ball_point(centers, radii+1e-8)
        lengths = [len(indices) for indices in candidates]
        if not sum(lengths):
            continue
        face = np.repeat(batch, lengths)
        ray = np.concatenate(candidates).astype(np.intp)
        dx, dy = (xy[ray]-origin[face]).T
        a = (dx*v[face, 1]-dy*v[face, 0])/det[face]
        b = (u[face, 0]*dy-u[face, 1]*dx)/det[face]
        inside = (a >= -1e-9) & (b >= -1e-9) & (a+b <= 1+1e-9)
        face, ray, a, b = face[inside], ray[inside], a[inside], b[inside]
        z = triangles[face, :, 2]
        height = z[:, 0] + a*(z[:, 1]-z[:, 0]) + b*(z[:, 2]-z[:, 0])
        for i, depth, sign in zip(ray, height, np.sign(det[face])):
            hits[i].append((depth, sign))

    bounds = np.full((len(xy), 2), np.nan)
    counts = np.zeros(len(xy), dtype=int)
    for i, crossings in enumerate(hits):
        groups = []
        for height, sign in sorted(crossings):
            if not groups or height-groups[-1][0] > merge_mm:
                groups.append((height, {sign}))
            else:
                groups[-1][1].add(sign)
        counts[i] = len(groups)
        if len(groups) == 2 and groups[0][1] == {-1} and groups[1][1] == {1}:
            bounds[i] = [g[0] for g in groups]
    return bounds, counts


def audit_pair(root, record):
    points, reference, _ = load_demo_pair(root, record, belt_depth_mm=350)
    xy = points[:, :2]
    hull = ConvexHull(xy)
    spacing_mm = 1.
    axes = [np.arange(np.ceil(lo), hi, spacing_mm) for lo, hi in zip(xy.min(0), xy.max(0))]
    grid = np.stack(np.meshgrid(*axes), axis=-1).reshape(-1, 2)
    inside = np.all(grid @ hull.equations[:, :2].T + hull.equations[:, 2] <= -2., axis=1)
    grid = grid[inside]
    if not len(grid):
        raise ValueError("Empty interior evaluation grid")

    bounds, count = reference_heights(reference, grid)
    paired = np.isfinite(bounds[:, 0])
    rmse = record["published_registration_rmse_mm"]
    shifts = []
    for offset in rmse*np.array([[1., 0.], [-1., 0.], [0., 1.], [0., -1.]]):
        shifted, _ = reference_heights(reference, grid+offset)
        common = paired & np.isfinite(shifted[:, 0])
        shifts.append({"probe_xy_mm": offset, "common_pair_fraction": common.mean(),
                       "lower_abs_shift_p95_mm": (
                           np.percentile(np.abs(shifted[common, 0]-bounds[common, 0]), 95)
                           if common.any() else None)})
    return {
        "object_id": record["object_id"], "frame_id": record["frame_id"],
        "reference_watertight": reference.is_watertight,
        "grid_rays": len(grid), "paired_rays": paired.sum(),
        "zero_crossing_rays": (count == 0).sum(),
        "one_crossing_rays": (count == 1).sum(),
        "extra_crossing_rays": (count > 2).sum(),
        "two_crossings_rejected": ((count == 2) & ~paired).sum(),
        "published_registration_rmse_mm": rmse, "alignment_probes": shifts,
        "input_sha256": {key: record[key] for key in (
            "partial_sha256", "reference_sha256", "registration_sha256")},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/raw/3DPotatoTwinDemo"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = [audit_pair(args.root, record) for record in discover_demo(args.root)]
    write_json(args.out, {"stage": "development_geometry_only", "pairs": rows})


if __name__ == "__main__":
    main()
