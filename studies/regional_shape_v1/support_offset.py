"""Freeze scan-only plane shifts, then score the original development tubers."""
import argparse
import csv
import json
from contextlib import ExitStack
from itertools import permutations
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import numpy as np
from PIL import Image
from scipy.spatial import QhullError

from potato3d import calibration
from potato3d.geometry import camera_to_belt_mm, transform_points
from potato3d.io import load_points, safe_path, sha256, write_json
from studies.real_lobes_v1.intake import audit_raster
from .reflection_weight import common_sectors
from .study import BELT_DEPTH, HERE, INTRINSICS, LOBE_STUDY, METADATA, fit_body, run_study
from .vertical_offset import TOLERANCE_MM, offset_mae

SELECTION = LOBE_STUDY / "fresh_selection.json"
MEMBERS = LOBE_STUDY / "fresh_download_members.tsv"
PROTOCOL = HERE / "support_offset_protocol.md"
PREDICTION_FILE = "support_offset_predictions.json"


def shift_at_center(coefficients, belt_center_xy_mm):
    """Evaluate camera depth at the xy location of the original fitted footprint."""
    belt_center = [*belt_center_xy_mm, 0.]
    to_camera = np.linalg.inv(camera_to_belt_mm(BELT_DEPTH))
    camera_xy = transform_points([belt_center], to_camera)[0, :2]
    depth = np.dot(coefficients, [*camera_xy, 1.])
    return camera_xy, depth, BELT_DEPTH-depth


def stage_scans(source, root, selection):
    """Stage the released PLY and its exact RGB/depth frame, with identity metadata."""
    expected = selection["metadata_sha256"]
    intrinsic_path = safe_path(source, INTRINSICS)
    matrix_archive = safe_path(source, METADATA["tmatrix.zip"])
    for name, path in ((Path(INTRINSICS).name, intrinsic_path), ("tmatrix.zip", matrix_archive)):
        if sha256(path) != expected[name]:
            raise ValueError(f"Source metadata differs from the development selection: {name}")
    with MEMBERS.open(newline="") as handle:
        members = {(r["tuber_id"], r["member_basename"]): r for r in csv.DictReader(handle, delimiter="\t")}
    with ExitStack() as stack:
        matrices = stack.enter_context(ZipFile(matrix_archive))
        archives = {}
        rows = []
        for pair in selection["pairs"]:
            obj, frame = pair["object_id"], pair["frame"]
            registration_member = pair["registration_member"]
            reg_bytes = matrices.read(registration_member)
            released_partial = json.loads(reg_bytes)["rgbd_pcd_file"]
            if (registration_member != f"tmatrix/{obj}.json"
                    or released_partial != pair["partial"]
                    or Path(released_partial).name != f"{obj}_pcd_{frame}.ply"
                    or any(pair[role] != f"{obj}_{role}_{frame}.png" for role in ("rgb", "depth"))):
                raise ValueError(f"Frame identity differs from the released registration for {obj}")
            reg_path = root / "3_pair" / registration_member
            reg_path.parent.mkdir(parents=True, exist_ok=True)
            reg_path.write_bytes(reg_bytes)
            files = {"registration": str(reg_path.relative_to(root)), "partial": released_partial}
            for role in ("rgb", "depth"):
                files[role] = f"1_rgbd/1_image/{obj}/{pair[role]}"
            for role in ("partial", "rgb", "depth"):
                relative = files[role]
                entry = members[obj, Path(relative).name]
                archive = entry["archive"]
                if archive not in archives:
                    archives[archive] = stack.enter_context(ZipFile(safe_path(source, archive)))
                zip_file = archives[archive]
                info = zip_file.getinfo(entry["member_path"])
                if info.file_size != int(entry["uncompressed_bytes"]):
                    raise ValueError(f"Unexpected release member size: {entry['member_path']}")
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zip_file.read(info))
            rows.append({
                "object_id": obj, "frame_id": frame, "cultivar": pair["cultivar"],
                "acquisition_group": pair["acquisition_group"], "partial": released_partial, "unit": "m",
                "files": {role: {"path": name, "sha256": sha256(root/name)} for role, name in files.items()},
            })
    return json.loads(intrinsic_path.read_text()), rows


def predict_scan(root, row, matrix, image_size):
    _, check = audit_raster(root, row, matrix, image_size)
    result = {k: row[k] for k in ("object_id", "frame_id", "cultivar", "acquisition_group", "files")}
    result.update(raster_check=check, belt_center_xy_mm=None, camera_center_xy_mm=None, plane_fit=None,
                  local_plane_depth_mm=None, predicted_shift_mm=0., failure=None)
    points = load_points(safe_path(root, row["partial"]), row["unit"])
    try:
        body = fit_body(transform_points(points, camera_to_belt_mm(BELT_DEPTH)))
    except (ValueError, QhullError, np.linalg.LinAlgError) as error:
        result["failure"] = {"stage": "footprint_fit", "message": str(error)}
        return result
    center = body["center_xy_mm"]
    result["belt_center_xy_mm"] = center
    with Image.open(root / row["files"]["rgb"]["path"]) as image:
        alpha = np.array(image)[..., 3]
    with Image.open(root / row["files"]["depth"]["path"]) as image:
        depth = np.array(image)
    try:
        audit, _, _ = calibration.audit_background(depth, alpha, matrix)
    except (ValueError, np.linalg.LinAlgError) as error:
        result["failure"] = {"stage": "background_plane_fit", "message": str(error)}
        return result
    camera_xy, local_depth, shift = shift_at_center(audit["plane_z_ax_by_d"], center)
    result.update(camera_center_xy_mm=camera_xy, plane_fit=audit, local_plane_depth_mm=local_depth,
                  predicted_shift_mm=shift)
    return result


def freeze_predictions(source, path):
    selection = json.loads(SELECTION.read_text())
    with TemporaryDirectory(prefix="potato-support-scan-") as folder:
        root = Path(folder)
        camera, records = stage_scans(source, root, selection)
        if len(records) != 12 or len({r["object_id"] for r in records}) != 12:
            raise ValueError("Scan inputs differ from the 12-tuber development cohort")
        matrix = calibration.intrinsics_from_json(camera)
        size = (camera["width"], camera["height"])
        rows = [predict_scan(root, row, matrix, size) for row in records]
    write_json(path, {
        "stage": "frozen_scan_only_shifts", "protocol_sha256": sha256(PROTOCOL),
        "selection_sha256": sha256(SELECTION), "archive_members_sha256": sha256(MEMBERS),
        "intrinsics_sha256": selection["metadata_sha256"][Path(INTRINSICS).name],
        "registration_archive_sha256": selection["metadata_sha256"]["tmatrix.zip"],
        "estimator_source_sha256": sha256(Path(calibration.__file__)),
        "nominal_belt_depth_mm": BELT_DEPTH, "prediction_rule": "350 mm minus local plane depth",
        "fallback_count": sum(row["failure"] is not None for row in rows), "pairs": rows,
    })


def shuffled_control(costs):
    count = len(costs)
    indices = np.arange(count)
    matched = np.diag(costs).mean()
    means = np.array([np.mean(costs[indices, permutation]) for permutation in permutations(range(count))])
    strictly_better = np.count_nonzero(means < matched-TOLERANCE_MM)
    tied = np.count_nonzero(np.abs(means-matched) <= TOLERANCE_MM)
    equal_or_better_pct = 100 * (strictly_better+tied) / len(means)
    return {
        "assignments_including_identity": len(means),
        "correct_assignment_mae_mm": matched, "mean_assignment_mae_mm": means.mean(),
        "matched_minus_mean_shuffled_mm": matched-means.mean(),
        "assignment_mae_min_median_max_mm": np.percentile(means, [0, 50, 100]),
        "assignments_strictly_better": strictly_better, "assignments_tied": tied,
        "assignments_worse": len(means)-strictly_better-tied,
        "correct_assignment_rank_from_lowest": [strictly_better+1, strictly_better+tied],
        "percent_at_or_below_correct_assignment": equal_or_better_pct,
        "comparison_tolerance_mm": TOLERANCE_MM,
    }


def verify_scan_inputs(frozen, baseline):
    intake = {p["object_id"]: p for p in baseline["intake"]["pairs"]}
    scan_rows = {p["object_id"]: p for p in frozen["pairs"]}
    if (len(frozen["pairs"]) != 12 or set(scan_rows) != set(intake)
            or frozen["selection_sha256"] != baseline["selection_sha256"]
            or frozen["intrinsics_sha256"] != baseline["intake"]["metadata"]["intrinsics"]["sha256"]):
        raise ValueError("Frozen predictions differ from replayed development inputs")
    for obj, row in scan_rows.items():
        old = intake[obj]
        if row["frame_id"] != old["frame_id"] or any(v != old["files"][k] for k, v in row["files"].items()):
            raise ValueError(f"Scan inputs differ from the archived frame for {obj}")
    return scan_rows


def score(baseline, measurements, frozen, archived_offsets):
    scan_rows = verify_scan_inputs(frozen, baseline)
    best = {p["object_id"]: p for p in archived_offsets["pairs"]}
    eligible = [p for p in baseline["pairs"] if p["scored_bands"]]
    ids = [p["object_id"] for p in eligible]
    shifts = [scan_rows[obj]["predicted_shift_mm"] for obj in ids]
    costs, body_scores = [], []
    for pair in eligible:
        cells = measurements[pair["object_id"]]
        reference_ok = np.isfinite(cells.nominal_lower)
        bands = [common_sectors(cells, b["band"], reference_ok, b["coverage"]["common"])
                 for b in pair["bands"] if "errors_mm" in b]
        residual = cells.nominal_lower - cells.body_lower
        body = offset_mae(residual, bands, 0.)
        np.testing.assert_allclose(body, pair["errors_mm"]["body"], rtol=0, atol=TOLERANCE_MM)
        body_scores.append(body)
        costs.append([offset_mae(residual, bands, shift) for shift in shifts])
    costs = np.asarray(costs)
    body_mean = np.mean(body_scores)
    coverage = {k: baseline["summary"][k] for k in
                ("selected_tubers", "scored_tubers", "scored_bands", "scored_cells")}
    if (len(ids), coverage["scored_bands"], coverage["scored_cells"]) != (7, 10, 12202):
        raise ValueError("Archived scoring denominators did not reproduce")
    np.testing.assert_allclose(body_mean, baseline["summary"]["errors_mm"]["body"], rtol=0, atol=TOLERANCE_MM)

    matched = np.diag(costs)
    deltas = matched - body_scores
    omitted = [np.mean(np.delete(deltas, i)) for i in range(len(ids))]
    details = {}
    for i, obj in enumerate(ids):
        archive = best[obj]
        pair = eligible[i]
        if any(archive[k] != pair[k] for k in ("frame_id", "scored_bands", "scored_cells")):
            raise ValueError(f"Archived offset support differs for {obj}")
        np.testing.assert_allclose(archive["scores_mm"]["body_mae_mm"], body_scores[i], rtol=0, atol=TOLERANCE_MM)
        best_shift = archive["scores_mm"]["vertical_shift_mm"]
        details[obj] = {
            "archived_best_shift_mm": best_shift, "prediction_minus_best_shift_mm": shifts[i]-best_shift,
            "body_mae_mm": body_scores[i], "shifted_mae_mm": matched[i], "change_mm": deltas[i],
            "mean_change_if_omitted_mm": omitted[i],
        }

    control = shuffled_control(costs)
    criteria = {
        "better_than_body": bool(deltas.mean() < -TOLERANCE_MM),
        "better_than_mean_shuffled_assignment": bool(control["matched_minus_mean_shuffled_mm"] < -TOLERANCE_MM),
        "gain_survives_each_tuber_omission": bool(max(omitted) < -TOLERANCE_MM),
    }
    pairs = []
    for row in baseline["pairs"]:
        obj = row["object_id"]
        scan = scan_rows[obj]
        pairs.append({"object_id": obj, "frame_id": row["frame_id"], "cultivar": row["cultivar"],
                      "predicted_shift_mm": scan["predicted_shift_mm"], "plane_prediction_failure": scan["failure"],
                      "coverage_failure": row["failure"], "scored_bands": row["scored_bands"],
                      "scored_cells": row["scored_cells"], "comparison": details.get(obj)})
    return {
        "coverage": coverage, "fallback_count_on_scored_tubers": sum(scan_rows[obj]["failure"] is not None for obj in ids),
        "equal_tuber_body_mae_mm": body_mean, "equal_tuber_shifted_mae_mm": matched.mean(),
        "equal_tuber_change_mm": deltas.mean(),
        "omit_one_mean_change_range_mm": [min(omitted), max(omitted)],
        "shuffled_control": {**control, "tuber_and_shift_source_order": ids, "tuber_by_assigned_shift_mae_mm": costs},
        "decision_criteria": criteria, "meets_advancement_criterion": all(criteria.values()),
        "pairs": pairs,
    }


def score_frozen(source, path, output):
    digest = sha256(path)
    frozen = json.loads(path.read_text())
    if frozen["stage"] != "frozen_scan_only_shifts" or frozen["protocol_sha256"] != sha256(PROTOCOL):
        raise ValueError("The saved shifts belong to a different protocol")
    cells = {}
    baseline, _ = run_study(source, cells)
    archived = HERE / "results.json"
    with TemporaryDirectory(prefix="potato-support-score-") as tmp:
        replay = Path(tmp) / "results.json"
        write_json(replay, baseline)
        if replay.read_bytes() != archived.read_bytes():
            raise ValueError("Development replay differs from archived results")
    archived_offsets_path = HERE / "vertical_offset_results.json"
    archived_offsets = json.loads(archived_offsets_path.read_text())
    if archived_offsets["archived_development_sha256"] != sha256(archived):
        raise ValueError("Archived best shifts use a different baseline")
    results = score(baseline, cells, frozen, archived_offsets)
    if sha256(path) != digest:
        raise ValueError("Frozen shifts changed during scoring")
    write_json(output, {"stage": "scan_support_offset_development", "frozen_predictions_sha256": digest,
                        "archived_development_sha256": sha256(archived),
                        "archived_best_shifts_sha256": sha256(archived_offsets_path), **results})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("predict", "score"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=HERE)
    args = parser.parse_args()
    path = args.out_dir / PREDICTION_FILE
    if args.phase == "predict":
        freeze_predictions(args.source, path)
        print(f"Scan-only shifts saved at SHA-256 {sha256(path)}", flush=True)
    else:
        score_frozen(args.source, path, args.out_dir / "support_offset_results.json")


if __name__ == "__main__":
    main()
