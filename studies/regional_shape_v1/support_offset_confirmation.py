"""Freeze the scan-only confirmation predictions, then allow one fresh scoring pass."""
import argparse
import json
import os
import platform
import sys
from collections import Counter, defaultdict
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from scipy.spatial import QhullError

from potato3d.calibration import intrinsics_from_json
from potato3d.io import safe_path, sha256, write_json
from .reflection_weight import common_sectors
from .replication import BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED, CULTIVARS, bootstrap_intervals, coverage_summary, fingerprint
from .replication_intake import PROJECT
from .study import BELT_DEPTH, HERE, INTRINSICS, LOBE_STUDY, METADATA, build_manifest, discover_demo, pin_ellipses, run_pair
from .support_offset import PREDICTION_FILE, freeze_predictions, predict_scan, score_frozen
from .support_offset_confirmation_intake import (
    COHORT, COHORT_SHA256, DEMO_AUDIT, DEMO_PATH, PRIOR_COHORT, PRIOR_INTAKE, stage_references, stage_scans,
)
from .vertical_offset import TOLERANCE_MM, offset_mae

PROTOCOL = HERE / "support_offset_confirmation_protocol.md"
PREDICTIONS = HERE / "support_offset_confirmation_predictions.json"
ATTEMPT = HERE / "support_offset_confirmation_attempt.json"
RESULTS = HERE / "support_offset_confirmation_results.json"
INTAKE_ERRORS = (OSError, ValueError, KeyError, TypeError, QhullError, np.linalg.LinAlgError)


def publish_new(path, value):
    """Save without replacing a previously frozen artifact or one-attempt marker."""
    with TemporaryDirectory(prefix="potato-confirmation-publish-") as folder:
        temporary = Path(folder)/"artifact.json"
        write_json(temporary, value)
        with path.open("xb") as handle:
            handle.write(temporary.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())


def verify_development(source):
    with TemporaryDirectory(prefix="potato-confirmation-dev-") as folder:
        root = Path(folder)
        predictions = root/PREDICTION_FILE
        results = root/"support_offset_results.json"
        freeze_predictions(source, predictions)
        if predictions.read_bytes() != (HERE/predictions.name).read_bytes():
            raise ValueError("Development predictions differ from the archive")
        score_frozen(source, predictions, results)
        if results.read_bytes() != (HERE/results.name).read_bytes():
            raise ValueError("Development scores differ from the archive")
        summary = json.loads(results.read_text())
        print("Development prediction and scoring replay matched both archives byte for byte", flush=True)
        return {"status": "passed", "predictions_sha256": sha256(predictions), "results_sha256": sha256(results),
                "coverage": summary["coverage"], "body_mae_mm": summary["equal_tuber_body_mae_mm"],
                "shifted_mae_mm": summary["equal_tuber_shifted_mae_mm"],
                "shuffled_assignments": summary["shuffled_control"]["assignments_including_identity"]}


def provenance():
    tracked = [*HERE.glob("*.py"), *LOBE_STUDY.glob("*.py"), HERE.parent/"body_detail_v1/model.py",
               *(PROJECT/"src/potato3d").rglob("*.py")]
    code = {str(p.relative_to(PROJECT)): sha256(p) for p in sorted(tracked)}
    environment = {
        "python": sys.version, "interpreter_sha256": sha256(Path(sys.executable)),
        "platform": platform.platform(),
        "packages": {name: version(name) for name in ("numpy", "scipy", "trimesh", "Pillow", "matplotlib", "rtree")},
        "threads": {key: os.environ.get(key) for key in
                    ("OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "OMP_NUM_THREADS")},
        "dependencies_sha256": {name: sha256(PROJECT/name) for name in ("uv.lock", "pyproject.toml")},
    }
    prior = {str(p.relative_to(PROJECT)): sha256(p)
             for p in (DEMO_PATH, DEMO_AUDIT, HERE/"results.json", PRIOR_COHORT, PRIOR_INTAKE)}
    return {"protocol_sha256": sha256(PROTOCOL), "cohort_sha256": sha256(COHORT),
            "code_sha256": fingerprint(code), "code_hashes": code,
            "environment_sha256": fingerprint(environment), "environment": environment, "prior_input_hashes": prior}


def make_predictions(source):
    if any(p.exists() for p in (PREDICTIONS, ATTEMPT, RESULTS)):
        raise FileExistsError("A confirmation prediction or scoring artifact already exists")
    verification = verify_development(source)
    with TemporaryDirectory(prefix="potato-confirmation-scan-") as folder:
        root = Path(folder)
        cohort, scan_rows, source_hashes = stage_scans(source, root)
        camera = json.loads(safe_path(source, INTRINSICS).read_text())
        matrix = intrinsics_from_json(camera)
        size = camera["width"], camera["height"]
        predictions = []
        for metadata, row in zip(cohort, scan_rows, strict=True):
            row["cultivar"] = metadata["cultivar"]
            row["acquisition_group"] = metadata["ros_bag_name"]
            prediction = None
            if not row["input_failures"]:
                try:
                    prediction = predict_scan(root/row["object_id"], row, matrix, size)
                except INTAKE_ERRORS as error:
                    row["input_failures"].append({"stage": "rgbd_intake", "message": str(error)})
            predictions.append({"metadata": metadata, "scan": row, "prediction": prediction})
    scan_assets = {r["object_id"]: {role: asset["sha256"] for role, asset in r["files"].items()} for r in scan_rows}
    source_manifest = {**source_hashes, "scan_member_sha256": scan_assets}
    publish_new(PREDICTIONS, {
        "stage": "frozen_scan_only_confirmation_predictions", **provenance(),
        "development_replay": verification,
        "scan_source_sha256": fingerprint(source_manifest), "scan_source": source_manifest,
        "nominal_belt_depth_mm": BELT_DEPTH, "rule": "350 mm minus local plane depth, zero on fit failure",
        "bootstrap_seed": BOOTSTRAP_SEED, "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "pairs": predictions,
    })
    print(f"Fresh scan-only predictions saved at SHA-256 {sha256(PREDICTIONS)}", flush=True)


def measure_tuber(root, item, staged, intrinsics, coco):
    pred = item["prediction"]
    row = {**item["metadata"], "frame_id": staged["frame_id"], "input_files": staged["files"],
           "predicted_shift_mm": pred["predicted_shift_mm"] if pred is not None else None,
           "prediction_failure": pred["failure"] if pred is not None else None,
           "failures": list(staged["input_failures"]),
           "intake_passed": False, "scored_bands": 0, "scored_cells": 0, "scores_mm": None}
    if row["failures"]:
        return row, None
    obj = row["label"]
    if pred is None:
        raise ValueError(f"No frozen prediction or recorded intake failure for {obj}")
    try:
        intake, = build_manifest(root, allow_demo=False)["pairs"]
        record, = discover_demo(root)
        if (obj, staged["frame_id"]) != (intake["object_id"], intake["frame_id"]):
            raise ValueError("Scoring intake found a different object or frame")
        for role, asset in intake["files"].items():
            if asset["sha256"] != staged["files"][role]["sha256"]:
                raise ValueError(f"Staged {role} asset failed its hash check")
        row["intake_passed"] = True
        row["raster_check"] = intake["raster_check"]
        marker = pin_ellipses(coco, f"{obj}/{obj}_rgb_{record['frame_id']}.png")
        cells = {}
        measured, _ = run_pair(root, record, intrinsics, marker, cells, measure_probes=False)
    except INTAKE_ERRORS as error:
        row["failures"].append({"stage": "measurement_intake", "message": str(error)})
        return row, None
    for key in ("registration_overlap", "reference_rays", "body_fit", "scored_bands", "scored_cells"):
        if key in measured:
            row[key] = measured[key]
    row["bands"] = [{k: band[k] for k in ("band", "coverage", "scan_exclusion_flags")}
                    for band in measured.get("bands", [])]
    if measured["failure"] is not None:
        row["failures"].append(measured["failure"])
        return row, None

    if pred["failure"] is None:
        np.testing.assert_allclose(pred["belt_center_xy_mm"], measured["body_fit"]["center_xy_mm"], rtol=0, atol=1e-12)
    cells = cells[obj]
    bands = [common_sectors(cells, b["band"], np.isfinite(cells.nominal_lower), b["coverage"]["common"])
             for b in measured["bands"] if "errors_mm" in b]
    residual = cells.nominal_lower - cells.body_lower
    body = offset_mae(residual, bands, 0.)
    shifted = offset_mae(residual, bands, row["predicted_shift_mm"])
    np.testing.assert_allclose(body, measured["errors_mm"]["body"], rtol=0, atol=TOLERANCE_MM)
    row["scores_mm"] = {"body": body, "shifted": shifted, "shifted_minus_body": shifted-body}
    return row, (residual, bands)


def within_group_control(eligible, supports):
    groups = defaultdict(list)
    for row in eligible:
        groups[(row["cultivar"], row["ros_bag_name"])].append(row)
    results, matched, shuffled = [], [], []
    for (cultivar, group), rows in sorted(groups.items()):
        if len(rows) < 2:
            continue
        ids = [r["label"] for r in rows]
        shifts = [r["predicted_shift_mm"] for r in rows]
        costs = np.array([[offset_mae(*supports[obj], shift) for shift in shifts] for obj in ids])
        own = np.diag(costs)
        np.testing.assert_allclose(own, [r["scores_mm"]["shifted"] for r in rows], rtol=0, atol=TOLERANCE_MM)
        expected = costs.mean(axis=1)
        matched.extend(own)
        shuffled.extend(expected)
        results.append({"cultivar": cultivar, "acquisition_group": group,
                        "tuber_and_shift_source_order": ids, "tuber_by_assigned_shift_mae_mm": costs,
                        "matched_mae_mm": own.mean(), "expected_reassignment_mae_mm": expected.mean(),
                        "matched_minus_expected_mm": (own-expected).mean()})
    return {"contributing_groups": len(results), "contributing_tubers": len(matched),
            "correctly_matched_mae_mm": np.mean(matched) if matched else None,
            "expected_within_group_reassignment_mae_mm": np.mean(shuffled) if shuffled else None,
            "matched_minus_expected_mm": np.mean(matched)-np.mean(shuffled) if matched else None,
            "groups": results}


def mean_scores(rows):
    valid = [r["scores_mm"] for r in rows if r["scores_mm"] is not None]
    return {key: np.mean([v[key] for v in valid]) for key in valid[0]} if valid else None


def summarize(rows, supports):
    eligible = [r for r in rows if r["scores_mm"] is not None]
    deltas = np.array([r["scores_mm"]["shifted_minus_body"] for r in eligible])
    boot_rows = [{**r, "scores_mm": {"aligned_minus_body": r["scores_mm"]["shifted_minus_body"]}} for r in eligible]
    intervals = bootstrap_intervals(boot_rows)
    cultivar_rows, group_rows = {}, []
    for cultivar in CULTIVARS:
        subset = [r for r in rows if r["cultivar"] == cultivar]
        cultivar_rows[cultivar] = {**coverage_summary(subset), "scores_mm": mean_scores(subset)}
        for group in sorted({r["ros_bag_name"] for r in subset}):
            matched = [r for r in subset if r["ros_bag_name"] == group]
            rest = [r for r in eligible if (r["cultivar"], r["ros_bag_name"]) != (cultivar, group)]
            without = mean_scores(rest)
            group_rows.append({"cultivar": cultivar, "acquisition_group": group, **coverage_summary(matched),
                               "scores_mm": mean_scores(matched),
                               "mean_change_if_omitted_mm": without["shifted_minus_body"] if without else None})
    confirmed = (not intervals["missing_cultivars"] and intervals["tuber_percentile_95_mm"] is not None
                 and max(intervals[k][1] for k in ("tuber_percentile_95_mm", "group_percentile_95_mm")) < 0)
    prediction_failures = [r for r in rows if r["prediction_failure"] is not None]
    return {
        "coverage": coverage_summary(rows), "coverage_by_cultivar": cultivar_rows, "coverage_by_group": group_rows,
        "prediction_failures_by_stage": dict(Counter(r["prediction_failure"]["stage"] for r in prediction_failures)),
        "zero_shift_fallbacks": len(prediction_failures),
        "measurable_zero_shift_fallbacks": sum(r["scores_mm"] is not None for r in prediction_failures),
        "unevaluable_by_stage": dict(Counter(stage for r in rows for stage in {f["stage"] for f in r["failures"]})),
        "primary": {
            "scores_mm": mean_scores(eligible), "median_change_mm": np.median(deltas) if eligible else None,
            "wins": np.count_nonzero(deltas < -TOLERANCE_MM), "ties": np.count_nonzero(np.abs(deltas) <= TOLERANCE_MM),
            "losses": np.count_nonzero(deltas > TOLERANCE_MM),
            **intervals, "meets_confirmation_rule": bool(confirmed),
        },
        "within_group_control": within_group_control(eligible, supports),
    }


def score_once(source):
    if ATTEMPT.exists() or RESULTS.exists():
        raise FileExistsError("A fresh scoring attempt already exists")
    digest = sha256(PREDICTIONS)
    frozen = json.loads(PREDICTIONS.read_text())
    current = provenance()
    if (frozen["stage"] != "frozen_scan_only_confirmation_predictions"
            or frozen["cohort_sha256"] != COHORT_SHA256
            or frozen["development_replay"]["status"] != "passed"
            or any(frozen[k] != current[k] for k in current)):
        raise ValueError("Freeze, code, protocol, or environment differ from prediction time")
    with TemporaryDirectory(prefix="potato-confirmation-score-") as folder:
        root = Path(folder)
        cohort, scans, source_hashes = stage_scans(source, root)
        if any(source_hashes[k] != frozen["scan_source"][k] for k in source_hashes):
            raise ValueError("Fresh scan archive hashes differ from the frozen source")
        items = frozen["pairs"]
        for metadata, scan, item in zip(cohort, scans, items, strict=True):
            if metadata != item["metadata"] or any(scan[k] != item["scan"][k] for k in ("frame_id", "files")):
                raise ValueError(f"Staged scan differs from frozen prediction for {metadata['label']}")
            for failure in item["scan"]["input_failures"]:
                if failure not in scan["input_failures"]:
                    scan["input_failures"].append(failure)
        camera = json.loads(safe_path(source, INTRINSICS).read_text())
        matrix = intrinsics_from_json(camera)
        coco = json.loads(safe_path(source, METADATA["pin_regions.json"]).read_text())
        if sha256(PREDICTIONS) != digest:
            raise ValueError("Predictions changed before scoring")
        publish_new(ATTEMPT, {"stage": "fresh_reference_access_and_scoring_attempt_started",
                              "cohort_sha256": COHORT_SHA256, "protocol_sha256": current["protocol_sha256"],
                              "frozen_predictions_sha256": digest, "code_sha256": current["code_sha256"]})
        print("Single attempt recorded; opening fresh references", flush=True)
        reference_archive = stage_references(source, root, scans)
        rows, supports = [], {}
        for item, scan in zip(items, scans, strict=True):
            obj = item["metadata"]["label"]
            row, support = measure_tuber(root/obj, item, scan, matrix, coco)
            rows.append(row)
            if support is not None:
                supports[obj] = support
            status = ", ".join(f["stage"] for f in row["failures"]) or f"{row['scored_bands']} of 2 bands"
            print(f"{obj}: {status}", flush=True)

    if sha256(PREDICTIONS) != digest:
        raise ValueError("Predictions changed during scoring")
    publish_new(RESULTS, {
        "stage": "single_scored_support_offset_confirmation",
        "frozen_predictions_sha256": digest, "scoring_attempt_sha256": sha256(ATTEMPT),
        "protocol_sha256": current["protocol_sha256"], "cohort_sha256": COHORT_SHA256,
        "code_sha256": current["code_sha256"], "environment_sha256": current["environment_sha256"],
        "reference_archive_sha256": reference_archive,
        "summary": summarize(rows, supports), "pairs": rows,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("predict", "score"))
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    if args.phase == "predict":
        make_predictions(args.source)
    else:
        score_once(args.source)


if __name__ == "__main__":
    main()
