"""Scan-only lobe detection and registered-reference measurement on demo tubers."""
import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull, cKDTree

from potato3d.io import discover_demo, load_demo_pair, write_json

from audit import reference_heights


@dataclass(frozen=True)
class Patch:
    center: int
    relief: float
    coherence: float
    slope: float
    support: float
    core: np.ndarray
    ring: np.ndarray
    design: np.ndarray


def observed_grid(points):
    xy = points[:, :2]
    hull = ConvexHull(xy)
    axes = [np.arange(np.ceil(lo), hi) for lo, hi in zip(xy.min(0), xy.max(0))]
    grid = np.stack(np.meshgrid(*axes), axis=-1).reshape(-1, 2)
    depth = -(grid @ hull.equations[:, :2].T + hull.equations[:, 2]).max(axis=1)
    grid, depth = grid[depth >= 0], depth[depth >= 0]
    return grid, depth, sample_scan_heights(points, grid)


def sample_scan_heights(points, grid):
    xy = points[:, :2]
    distance, index = cKDTree(xy).query(grid, k=5)
    height = np.median(points[index, 2], axis=1)
    height[distance[:, -1] > 1.5] = np.nan
    return height


def relief(height, core, ring, design):
    """Fit a robust quadratic on the ring and measure signed median core relief."""
    valid = np.isfinite(height)
    ring_design, core_design = design[:len(ring)], design[len(ring):]
    annulus, interior = valid[ring], valid[core]
    core_fraction, ring_fraction = interior.mean(), annulus.mean()
    if core_fraction < .8 or ring_fraction < .8:
        return None, core_fraction, ring_fraction

    x, y = ring_design[annulus], height[ring[annulus]]
    if np.linalg.cond(x) > 30:
        return None, core_fraction, ring_fraction
    weights = np.ones(len(y))
    for _ in range(3):
        fit = np.linalg.lstsq(x*weights[:, None], y*weights, rcond=None)[0]
        residual = y-x@fit
        scale = max(.25, 1.4826*np.median(np.abs(residual-np.median(residual))))
        weights = np.sqrt(np.minimum(1, 1.5*scale/np.maximum(np.abs(residual), 1e-8)))
    delta = height[core[interior]]-core_design[interior]@fit
    slope = np.linalg.norm(fit[1:3])/9
    stats = (np.median(delta), np.mean(delta >= .75), slope)
    return stats, core_fraction, ring_fraction


def scan_patches(grid, depth, height):
    patches = []
    tree = cKDTree(grid)
    centers = np.flatnonzero((depth >= 9) & np.isfinite(height))
    for center, neighbors in zip(centers, tree.query_ball_point(grid[centers], 9)):
        neighbors = np.array(sorted(neighbors))
        offset = grid[neighbors]-grid[center]
        distance = np.linalg.norm(offset, axis=1)
        core, ring = neighbors[distance <= 3], neighbors[distance >= 6]
        x, y = (np.vstack([grid[ring], grid[core]])-grid[center]).T/9
        design = np.stack([np.ones_like(x), x, y, x*x, x*y, y*y], axis=1)
        stats, core_fraction, ring_fraction = relief(height, core, ring, design)
        if stats is not None:
            patches.append(Patch(center, *stats, min(core_fraction, ring_fraction), core, ring, design))
    return patches


def detect_and_match(grid, depth, height, threshold_mm=1.5):
    patches = scan_patches(grid, depth, height)
    return match_patches(grid, depth, patches, threshold_mm), len(patches)


def match_patches(grid, depth, patches, threshold_mm=1.5):
    candidates = []
    for patch in sorted(patches, key=lambda p: (-p.relief, p.center)):
        if patch.relief < threshold_mm:
            break
        if patch.coherence >= .8 and all(
            np.linalg.norm(grid[patch.center]-grid[other.center]) >= 9 for other in candidates
        ):
            candidates.append(patch)

    controls = [patch for patch in patches if abs(patch.relief) <= .5]
    matches = []
    used = []
    for candidate in candidates:
        choices = []
        for patch in controls:
            xy = grid[patch.center]
            if any(np.linalg.norm(xy-grid[other.center]) < 9 for other in candidates+used):
                continue
            features = np.abs([depth[patch.center]-depth[candidate.center],
                               patch.slope-candidate.slope, patch.support-candidate.support])
            scaled = features/[3., .20, .10]
            if scaled.max() <= 1+1e-9:
                choices.append((np.linalg.norm(scaled), patch.center, patch))
        control = min(choices)[2] if choices else None
        if control is not None:
            used.append(control)
        matches.append((candidate, control))
    return matches


def measure_patch(bounds, patch):
    if patch is None:
        return None
    # Outward relief is positive on both sides.
    result = {}
    for side, height in [("top", bounds[:, 1]), ("underside", -bounds[:, 0])]:
        stats, core_fraction, ring_fraction = relief(height, patch.core, patch.ring, patch.design)
        result[side] = {"relief_mm": None if stats is None else stats[0],
                        "core_coverage": core_fraction, "annulus_coverage": ring_fraction}
    return result


def run_pair(root, record):
    points, reference, _ = load_demo_pair(root, record, belt_depth_mm=350)
    grid, depth, height = observed_grid(points)
    matches, count = detect_and_match(grid, depth, height)
    return measure_matches(record, grid, depth, reference, matches, count)


def measure_matches(record, grid, depth, reference, matches, count):
    result = {"object_id": record["object_id"], "frame_id": record["frame_id"],
              "eligible_centers": count, "detections": []}
    if not matches:
        return result
    rmse = record["published_registration_rmse_mm"]
    probes = {"nominal": [0., 0.], "x_plus": [rmse, 0.], "x_minus": [-rmse, 0.],
              "y_plus": [0., rmse], "y_minus": [0., -rmse]}
    bounds = {label: reference_heights(reference, grid+offset)[0] for label, offset in probes.items()}
    for candidate, control in matches:
        item = {}
        for role, patch in [("candidate", candidate), ("control", control)]:
            item[role] = None if patch is None else {
                "xy_mm": grid[patch.center], "scan_relief_mm": patch.relief,
                "scan_core_coherence": patch.coherence, "scan_support": patch.support,
                "silhouette_distance_mm": depth[patch.center], "scan_background_slope": patch.slope,
                "reference": {label: measure_patch(hits, patch) for label, hits in bounds.items()},
            }
        result["detections"].append(item)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/raw/3DPotatoTwinDemo"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    write_json(args.out, {"stage": "demo_development", "threshold_mm": 1.5,
                          "pairs": [run_pair(args.root, p) for p in discover_demo(args.root)]})


if __name__ == "__main__":
    main()
