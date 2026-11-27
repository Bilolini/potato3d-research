"""Screen the demo pilot using the same RGB-D eligibility for candidates and controls."""
import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, distance_transform_edt
from scipy.spatial import cKDTree

from potato3d.geometry import camera_to_belt_mm, transform_points
from potato3d.io import discover_demo, load_demo_pair, sha256, write_json

from pilot import match_patches, measure_matches, observed_grid, scan_patches

# Development settings selected after the initial visual review.
RULES = {"foreground_margin_px": 3, "depth_step_mm": 4,
         "depth_edge_buffer_px": 1, "marker_buffer_px": 2,
         "footprint_radius_mm": 9}


def screen_raster(foreground, depth, ellipses):
    valid = foreground & (depth > 0)
    foreground_margin = distance_transform_edt(np.pad(valid, 1))[1:-1, 1:-1]
    depth = depth.astype(float)
    edge = np.zeros_like(valid)
    for axis in (0, 1):
        near = [slice(None)]*2
        far = near.copy()
        near[axis], far[axis] = slice(None, -1), slice(1, None)
        a, b = tuple(near), tuple(far)
        jump = valid[a] & valid[b] & (np.abs(depth[a]-depth[b]) >= RULES["depth_step_mm"])
        edge[a] |= jump
        edge[b] |= jump
    y, x = np.ogrid[:depth.shape[0], :depth.shape[1]]
    marker = np.zeros_like(valid)
    for cx, cy, rx, ry in ellipses:
        marker |= ((x-cx)/(rx+RULES["marker_buffer_px"]))**2 + (
            (y-cy)/(ry+RULES["marker_buffer_px"]))**2 <= 1
    return {
        "foreground_boundary_or_missing_depth": foreground_margin < RULES["foreground_margin_px"],
        "depth_discontinuity": binary_dilation(edge, iterations=RULES["depth_edge_buffer_px"]),
        "marker_overlap": marker,
    }


def grid_screen_flags(points, grid, intrinsics, raster):
    # Project each nominal grid cell with the nearest observed camera depth.
    # The cell's own XY is retained so missing regions are still sampled.
    distances, neighbors = cKDTree(points[:, :2]).query(grid, k=5)
    xyz = np.column_stack([grid, points[neighbors[:, 0], 2]])
    coordinates = np.vstack([xyz, points])
    camera = transform_points(coordinates, camera_to_belt_mm(350))
    homogeneous = camera @ intrinsics.T
    x, y = np.rint(homogeneous[:, :2]/homogeneous[:, 2:]).astype(int).T
    height, width = next(iter(raster.values())).shape
    in_frame = (0 <= x) & (x < width) & (0 <= y) & (y < height)
    masks = {}
    for reason, mask in raster.items():
        flags = np.full(len(coordinates), reason == "foreground_boundary_or_missing_depth")
        flags[in_frame] = mask[y[in_frame], x[in_frame]]
        # Check the raw pixels that contribute to each supported interpolated cell.
        cell_flags, point_flags = np.split(flags, [len(grid)])
        masks[reason] = cell_flags | ((distances[:, -1] <= 1.5) & point_flags[neighbors].any(axis=1))
    return masks


def patch_flags(points, grid, patches, intrinsics, raster):
    masks = grid_screen_flags(points, grid, intrinsics, raster)
    ids = [p.center for p in patches]
    footprints = cKDTree(grid).query_ball_point(grid[ids], RULES["footprint_radius_mm"])
    return {center: [reason for reason, flags in masks.items() if flags[footprint].any()]
            for center, footprint in zip(ids, footprints)}


def run_pair(root, record, intrinsics, ellipses):
    obj, frame = record["object_id"], record["frame_id"]
    folder = root / "1_rgbd/1_image" / obj
    rgb_path = folder / f"{obj}_rgb_{frame}.png"
    depth_path = folder / f"{obj}_depth_{frame}.png"
    rgba = np.asarray(Image.open(rgb_path))
    depth = np.asarray(Image.open(depth_path))
    points, reference, _ = load_demo_pair(root, record, belt_depth_mm=350)
    grid, hull_depth, height = observed_grid(points)
    patches = scan_patches(grid, hull_depth, height)
    old_matches = match_patches(grid, hull_depth, patches)
    flags = patch_flags(points, grid, patches, intrinsics,
                        screen_raster(rgba[..., 3] > 0, depth, ellipses))
    eligible = [p for p in patches if not flags[p.center]]
    matches = match_patches(grid, hull_depth, eligible)
    result = measure_matches(record, grid, hull_depth, reference, matches, len(eligible))
    result["original_eligible_centers"] = len(patches)
    result["excluded_centers_by_reason"] = dict(Counter(
        reason for reasons in flags.values() for reason in reasons))
    result["rgb_sha256"] = sha256(rgb_path)
    result["depth_sha256"] = sha256(depth_path)
    result["original_detections"] = [
        {role: None if patch is None else {
            "xy_mm": grid[patch.center], "screen_reasons": flags[patch.center],
        } for role, patch in [("candidate", candidate), ("control", control)]}
        for candidate, control in old_matches
    ]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/raw/3DPotatoTwinDemo"))
    parser.add_argument("--markers", type=Path, default=Path(__file__).with_name("demo_markers.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    annotations = json.loads(args.markers.read_text())["frames"]
    path = args.root / "1_rgbd/0_camera_intrinsics/realsense_d405_camera_intrinsic.json"
    intrinsics = np.array(json.loads(path.read_text())["intrinsic_matrix"]).reshape((3, 3), order="F")
    rows = [run_pair(args.root, record, intrinsics,
                     annotations[f"{record['object_id']}/{record['frame_id']}"])
            for record in discover_demo(args.root)]
    write_json(args.out, {"stage": "demo_development_screen", "rules": RULES,
                          "marker_sha256": sha256(args.markers), "pairs": rows})


if __name__ == "__main__":
    main()
