"""Run the regional underside development study on the selected fresh pairs."""
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image
from scipy.spatial import ConvexHull, QhullError
from trimesh.transformations import rotation_matrix

from potato3d.completion.robust import robust95
from potato3d.io import discover_demo, load_demo_pair, safe_path, sha256, write_json
from studies.body_detail_v1.model import body_surfaces, fit_body

# These standalone scripts import their neighbors by name.
HERE = Path(__file__).resolve().parent
LOBE_STUDY = HERE.parent / "real_lobes_v1"
sys.path.append(str(LOBE_STUDY))
from audit import reference_heights
from fresh_pilot import METADATA, OVERLAP_RULE, pin_ellipses, registration_overlap, stage
from intake import INTRINSICS, build_manifest
from pilot import sample_scan_heights
from screen import RULES, grid_screen_flags, screen_raster

BANDS = ((.25, .50), (.50, .75))
SECTOR_COUNT = 8
MIN_CELLS = 20
MIN_FRACTION = .5
BELT_DEPTH = 350.
METHODS = ("body", "aligned", "shifted")
SHIFTS = tuple(range(1, SECTOR_COUNT))


@dataclass(frozen=True)
class RegionalCells:
    sectors: np.ndarray
    sector_masks: list[list[np.ndarray]]
    scan_ok: np.ndarray
    body_lower: np.ndarray
    mirror_lower: np.ndarray
    nominal_lower: np.ndarray
    probe_lower: dict[str, np.ndarray]


def region_cells(body):
    center = np.asarray(body["center_xy_mm"])
    radii = np.asarray(body["radii_xy_mm"])[::-1]
    major = np.asarray(body["rotation_basis"])[:, 1]
    if major[0] < 0 or (major[0] == 0 and major[1] < 0):
        major = -major
    basis = np.column_stack([major, [-major[1], major[0]]])
    extent = np.linalg.norm(basis * radii, axis=1) * BANDS[-1][1]
    x, y = [np.arange(np.ceil(lo), np.floor(hi)+1)
            for lo, hi in zip(center-extent, center+extent)]
    xy = np.stack(np.meshgrid(x, y), axis=-1).reshape(-1, 2)
    uv = ((xy-center) @ basis) / radii
    radius = np.linalg.norm(uv, axis=1)
    angle = np.mod(np.arctan2(uv[:, 1], uv[:, 0]), 2*np.pi)
    sector = np.floor(angle * SECTOR_COUNT/(2*np.pi)).astype(int) % SECTOR_COUNT
    selected = (radius >= BANDS[0][0]) & (radius <= BANDS[-1][1])
    band = (radius[selected] >= BANDS[1][0]).astype(int)
    return xy[selected], band, sector[selected], major


def sector_masks(bands, sectors):
    return [[(bands == b) & (sectors == s) for s in range(SECTOR_COUNT)]
            for b in range(len(BANDS))]


def centered_medians(residual, support, masks):
    medians = np.array([np.median(residual[m & support]) for m in masks])
    return medians - medians.mean()


def predict(bottom, correction, sectors):
    aligned = bottom - correction[sectors]
    shifted = np.vstack([bottom - np.roll(correction, k)[sectors] for k in SHIFTS])
    return aligned, shifted


def sector_mae(predicted, measured, masks):
    return np.mean([np.mean(np.abs(predicted[..., m] - measured[m]), axis=-1)
                    for m in masks], axis=0)


def error_summary(body, aligned, shifted, measured, masks):
    shifts = sector_mae(shifted, measured, masks)
    return {"body": sector_mae(body, measured, masks),
            "aligned": sector_mae(aligned, measured, masks),
            "shifted": shifts.mean(), "each_shift": shifts}


def average_scores(scores, methods=METHODS):
    if not scores:
        return None
    result = {key: np.mean([s[key] for s in scores], axis=0) for key in methods}
    if "shifted" in result:
        result["aligned_minus_body"] = result["aligned"] - result["body"]
        result["aligned_minus_shifted"] = result["aligned"] - result["shifted"]
    return result


def coverage(masks, scan, reference):
    common = scan & reference
    nominal, scan_count, ref_count, shared = [
        np.array([np.count_nonzero(m & valid) for m in masks])
        for valid in (True, scan, reference, common)
    ]
    required = np.maximum(MIN_CELLS, np.ceil(MIN_FRACTION * nominal)).astype(int)
    return {"nominal": nominal, "scan": scan_count, "reference": ref_count, "common": shared,
            "required": required, "failed_sectors": np.flatnonzero(shared < required)}


def belt_penetration(predicted):
    return {"cells_below_belt": np.count_nonzero(predicted < 0, axis=-1),
            "minimum_height_mm": np.min(predicted, axis=-1)}


def band_results(masks, sectors, scan, scan_residual, sfm, top, bottom, mirror, reasons):
    scan_ok = np.isfinite(scan)
    ref_ok = np.isfinite(sfm[:, 0])
    common = scan_ok & ref_ok
    results, example = [], None
    for band, cells in enumerate(masks):
        cov = coverage(cells, scan_ok, ref_ok)
        row = {"band": band, "coverage": cov,
               "scan_exclusion_flags": {
                   key: np.array([np.count_nonzero(m & flag) for m in cells])
                   for key, flag in reasons.items()}}
        results.append(row)
        if len(cov["failed_sectors"]):
            continue
        shared = [m & common for m in cells]
        scored = np.any(shared, axis=0)
        correction = centered_medians(scan_residual, scan_ok, cells)
        # Summarize SfM upper heights independently. For the reliability comparison
        # also recompute the RGB-D medians using these exact same cells.
        sfm_top = centered_medians(sfm[:, 1] - top, common, cells)
        paired_scan = centered_medians(scan_residual, common, cells)
        sfm_outward = -centered_medians(sfm[:, 0] - bottom, common, cells)
        aligned, shifted = predict(bottom, correction, sectors)
        row.update({
            "errors_mm": error_summary(bottom, aligned, shifted, sfm[:, 0], shared),
            "scan_correction_mm": correction,
            "paired_scan_top_relief_mm": paired_scan,
            "sfm_top_relief_mm": sfm_top,
            "sfm_outward_lower_relief_mm": sfm_outward,
            "top_relief_mae_mm": np.mean(np.abs(paired_scan - sfm_top)),
            "top_relief_correlation": (
                np.corrcoef(paired_scan, sfm_top)[0, 1]
                if np.std(paired_scan) > 0 and np.std(sfm_top) > 0 else None),
            "belt_penetration": {key: belt_penetration(pred[..., scored])
                                 for key, pred in (("body", bottom), ("aligned", aligned),
                                                   ("each_shift", shifted))},
            "sfm_belt_relative_height_check": belt_penetration(sfm[scored, 0]),
        })
        mirror_shared = scored & np.isfinite(mirror)
        row["mirror_common_cells"] = [np.count_nonzero(m & mirror_shared) for m in cells]
        if all(row["mirror_common_cells"]):
            row["mirror_comparison_mm"] = {
                key: np.mean([np.mean(np.abs(pred[m & mirror_shared] - sfm[m & mirror_shared, 0]))
                              for m in cells])
                for key, pred in (("body", bottom), ("clipped_q95", mirror))
            }
        if example is None:
            example = {"scored": scored, "band_cells": np.any(cells, axis=0),
                       "radial_band": "–".join(f"{limit:.2f}" for limit in BANDS[band]),
                       "scan_correction": correction[sectors], "sfm_top": sfm_top[sectors],
                       "lower_body": bottom, "lower_aligned": aligned, "lower_sfm": sfm[:, 0]}
    return results, example


def probe_results(nominal, perturbed, scan_residual, sectors, masks, top, bottom, nominal_rows):
    scan_ok = np.isfinite(scan_residual)
    shared_ref = np.isfinite(nominal[:, 0]) & np.isfinite(perturbed[:, 0])
    results = []
    for row, cells in zip(nominal_rows, masks):
        cov = coverage(cells, scan_ok, shared_ref)
        loss = row["coverage"]["common"] - cov["common"]
        entry = {"band": row["band"], "common_cells": cov["common"], "lost_cells": loss,
                 "failed_sectors": cov["failed_sectors"]}
        results.append(entry)
        if "errors_mm" not in row or len(cov["failed_sectors"]):
            continue
        common = scan_ok & shared_ref
        shared = [m & common for m in cells]
        paired_scan = centered_medians(scan_residual, common, cells)
        aligned, shifted = predict(bottom, row["scan_correction_mm"], sectors)
        for key, ref in (("nominal", nominal), ("perturbed", perturbed)):
            entry[key] = error_summary(bottom, aligned, shifted, ref[:, 0], shared)
            sfm_top = centered_medians(ref[:, 1]-top, common, cells)
            entry[key]["top_relief_mae_mm"] = np.mean(np.abs(sfm_top - paired_scan))
    eligible = [r for r in results if "nominal" in r]
    scored = np.zeros_like(scan_ok)
    for row in eligible:
        scored |= np.any(masks[row["band"]], axis=0)
    scored &= scan_ok & shared_ref
    return {
        "bands": results, "scored_bands": len(eligible), "scored_cells": np.count_nonzero(scored),
        "nominal_same_support_mm": average_scores([r["nominal"] for r in eligible], (*METHODS, "top_relief_mae_mm")),
        "perturbed_mm": average_scores([r["perturbed"] for r in eligible], (*METHODS, "top_relief_mae_mm")),
        "lower_abs_displacement_p95_mm": (
            np.percentile(np.abs(perturbed[scored, 0] - nominal[scored, 0]), 95) if scored.any() else None),
    }


def ray_counts(bounds, counts):
    return {"paired": np.count_nonzero(np.isfinite(bounds[:, 0])),
            "no_crossings": np.count_nonzero(counts == 0),
            "one_crossing": np.count_nonzero(counts == 1),
            "wrong_orientation": np.count_nonzero((counts == 2) & ~np.isfinite(bounds[:, 0])),
            "extra_crossings": np.count_nonzero(counts > 2)}


def registration_probes(mesh, xy, rmse, centroid):
    for index, axis in enumerate(("x", "y")):
        for sign, direction in ((1, "plus"), (-1, "minus")):
            offset = np.zeros(2)
            offset[index] = sign * rmse
            yield f"{axis}_{direction}", mesh, xy+offset, {"ray_offset_xy_mm": offset}
    for index, axis in enumerate(("x", "y")):
        for sign, direction in ((1, "plus"), (-1, "minus")):
            rotated = mesh.copy()
            rotated.apply_transform(rotation_matrix(np.deg2rad(sign), np.eye(3)[index], point=centroid))
            yield f"rot_{axis}_{direction}", rotated, xy, {
                "rotation_axis": axis, "degrees": sign, "pivot_xyz_mm": centroid}


def run_pair(root, record, camera, ellipses, cell_measurements=None, *, measure_probes=True):
    obj, frame = record["object_id"], record["frame_id"]
    overlap = registration_overlap(root, record)
    result = {"object_id": obj, "frame_id": frame, "cultivar": record["cultivar"],
              "registration_overlap": overlap, "pin_ellipses": ellipses, "failure": None}
    if not overlap["passes"]:
        result["failure"] = {"stage": "registration_overlap", "message": "Released pair failed existing overlap rule"}
        return result, None
    points, mesh, _ = load_demo_pair(root, record, BELT_DEPTH)
    try:
        body = fit_body(points)
        xy, bands, sectors, major = region_cells(body)
        if not len(xy):
            raise ValueError("Footprint has no regional grid cells")
        top, bottom, _ = body_surfaces(xy, body)
    except (QhullError, ValueError, FloatingPointError, np.linalg.LinAlgError) as error:
        result["failure"] = {"stage": "body_fit", "message": str(error)}
        return result, None
    result.update(body_fit=body, oriented_major_axis_xy=major)

    folder = root / "1_rgbd/1_image" / obj
    with Image.open(folder / f"{obj}_rgb_{frame}.png") as im:
        foreground = np.asarray(im)[..., 3] > 0
    with Image.open(folder / f"{obj}_depth_{frame}.png") as im:
        depth = np.array(im)
    hull = ConvexHull(points[:, :2])
    inside = np.all(xy @ hull.equations[:, :2].T + hull.equations[:, 2] <= 1e-9, axis=1)
    scan = sample_scan_heights(points, xy)
    flags = grid_screen_flags(points, xy, camera, screen_raster(foreground, depth, ellipses))
    reasons = {"outside_scan_hull": ~inside, "missing_five_neighbors": ~np.isfinite(scan), **flags}
    scan[np.logical_or.reduce(list(reasons.values()))] = np.nan
    masks = sector_masks(bands, sectors)
    nominal, counts = reference_heights(mesh, xy)
    result["reference_rays"] = ray_counts(nominal, counts)

    mirror = np.full(len(xy), np.nan)
    try:
        mirror_mesh, result["mirror_parameters"] = robust95(points)
        mirror = reference_heights(mirror_mesh, xy)[0][:, 0]
    except (ValueError, QhullError, FloatingPointError, np.linalg.LinAlgError) as error:
        result["mirror_failure"] = str(error)
    result["bands"], example = band_results(
        masks, sectors, scan, scan-top, nominal, top, bottom, mirror, reasons)
    eligible = [r for r in result["bands"] if "errors_mm" in r]
    result["scored_bands"] = len(eligible)
    result["scored_cells"] = sum(np.sum(r["coverage"]["common"]) for r in eligible)
    result["errors_mm"] = average_scores([r["errors_mm"] for r in eligible], (*METHODS, "each_shift"))
    mirror_rows = [r for r in eligible if "mirror_comparison_mm" in r]
    result["mirror_scored_bands"] = len(mirror_rows)
    result["mirror_comparison_mm"] = average_scores(
        [r["mirror_comparison_mm"] for r in mirror_rows], ("body", "clipped_q95"))
    result["top_relief_mae_mm"] = np.mean([r["top_relief_mae_mm"] for r in eligible]) if eligible else None
    if not eligible:
        result["failure"] = {"stage": "coverage", "message": "No band met all eight common-cell requirements"}

    probe_lower = {}
    result["probes"] = {}
    probes = registration_probes(
        mesh, xy, record["published_registration_rmse_mm"], points.mean(axis=0)) if measure_probes else ()
    for key, ref, rays, transform in probes:
        bounds, counts = reference_heights(ref, rays)
        result["probes"][key] = {
            "transform": transform, "reference_rays": ray_counts(bounds, counts),
            **probe_results(nominal, bounds, scan-top, sectors, masks, top, bottom, result["bands"]),
        }
        if cell_measurements is not None:
            probe_lower[key] = bounds[:, 0]
    if cell_measurements is not None:
        cell_measurements[obj] = RegionalCells(
            sectors, masks, np.isfinite(scan), bottom, mirror, nominal[:, 0], probe_lower)
    if example is not None:
        example.update(object_id=obj, frame_id=frame, xy=xy)
    return result, example


def summarize(rows):
    eligible = [r for r in rows if r.get("errors_mm") is not None]
    mirror = [r for r in eligible if r["mirror_comparison_mm"] is not None]
    probes = {}
    for key in sorted({key for r in rows for key in r.get("probes", {})}):
        attempted = [r["probes"][key] for r in rows if key in r.get("probes", {})]
        valid = [p for p in attempted if p["scored_bands"]]
        probes[key] = {
            "scored_tubers": len(valid), "scored_bands": sum(p["scored_bands"] for p in valid),
            "scored_cells": sum(p["scored_cells"] for p in valid),
            "lost_cells_before_band_gate": sum(np.sum(b["lost_cells"]) for p in attempted for b in p["bands"]),
            "nominal_same_support_mm": average_scores(
                [p["nominal_same_support_mm"] for p in valid], (*METHODS, "top_relief_mae_mm")),
            "perturbed_mm": average_scores([p["perturbed_mm"] for p in valid], (*METHODS, "top_relief_mae_mm")),
            "max_tuber_lower_displacement_p95_mm": max((p["lower_abs_displacement_p95_mm"] for p in valid), default=None),
        }
    return {"selected_tubers": len(rows), "planned_bands": len(rows)*len(BANDS),
            "scored_tubers": len(eligible), "scored_bands": sum(r["scored_bands"] for r in eligible),
            "scored_cells": sum(r["scored_cells"] for r in eligible),
            "errors_mm": average_scores([r["errors_mm"] for r in eligible], (*METHODS, "each_shift")),
            "mirror_scored_tubers": len(mirror), "mirror_scored_bands": sum(r["mirror_scored_bands"] for r in mirror),
            "mirror_comparison_mm": average_scores(
                [r["mirror_comparison_mm"] for r in mirror], ("body", "clipped_q95")),
            "top_relief_mae_mm": np.mean([r["top_relief_mae_mm"] for r in eligible]) if eligible else None,
            "probes": probes}


def run_study(source, cell_measurements=None):
    path = LOBE_STUDY / "fresh_selection.json"
    selection = json.loads(path.read_text())
    with TemporaryDirectory(prefix="potato-regional-") as tmp:
        root = Path(tmp)
        stage(source, root, selection)
        intake = build_manifest(root, allow_demo=False)
        records = discover_demo(root)
        expected = {(p["object_id"], p["frame"]) for p in selection["pairs"]}
        observed = {(p["object_id"], p["frame_id"]) for p in records}
        if len(records) != 12 or observed != expected:
            raise ValueError("Staged pairs differ from the fixed 12-tuber cohort")
        camera = json.loads((root / INTRINSICS).read_text())
        intrinsics = np.asarray(camera["intrinsic_matrix"]).reshape(3, 3, order="F")
        coco = json.loads(safe_path(source, METADATA["pin_regions.json"]).read_text())
        rows, example = [], None
        for record in records:
            obj, frame = record["object_id"], record["frame_id"]
            ellipses = pin_ellipses(coco, f"{obj}/{obj}_rgb_{frame}.png")
            row, candidate = run_pair(root, record, intrinsics, ellipses, cell_measurements)
            rows.append(row)
            if example is None:
                example = candidate
            print(f"{obj}: {row.get('scored_bands', 0)} of 2 bands", flush=True)
    payload = {
        "stage": "regional_shape_development", "selection_sha256": sha256(path),
        "protocol_sha256": sha256(HERE / "protocol.md"), "intake": intake,
        "rules": {"radial_bands": BANDS, "sectors_per_band": SECTOR_COUNT, "grid_mm": 1,
                  "minimum_cells_per_sector": MIN_CELLS, "minimum_common_fraction": MIN_FRACTION,
                  "belt_depth_mm": BELT_DEPTH, "overlap": OVERLAP_RULE, "rgbd_screen": RULES,
                  "shift_offsets": SHIFTS},
        "example": None if example is None else {"object_id": example["object_id"], "frame_id": example["frame_id"]},
        "summary": summarize(rows), "pairs": rows,
    }
    return payload, example


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--example", type=Path)
    args = parser.parse_args()
    payload, example = run_study(args.source)
    write_json(args.out, payload)
    if args.example is not None and example is not None:
        from .plot_example import plot_example
        plot_example(example, args.example)


if __name__ == "__main__":
    main()
