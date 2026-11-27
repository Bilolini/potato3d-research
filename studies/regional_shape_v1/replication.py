"""Verify the frozen scorer on development data, then score the fixed replication cohort."""
import argparse
import hashlib
import json
import os
import platform
import sys
from collections import Counter, defaultdict
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from potato3d.io import sha256, write_json
from .reflection_weight import SCORE_KEYS, selected_scores
from .replication_intake import COHORT_PATH, DEMO_PATH, DEV_SELECTION, PROJECT, stage_replication
from .study import (BANDS, HERE, INTRINSICS, LOBE_STUDY, METADATA, SHIFTS, average_scores, build_manifest,
                    discover_demo, pin_ellipses, run_pair, run_study)

WEIGHT = .25
BOOTSTRAP_SEED = 5272101
BOOTSTRAP_REPLICATES = 10_000
CULTIVARS = ("Corolle", "Sayaka")


def assert_errors(actual, expected, keys):
    for key in keys:
        np.testing.assert_allclose(actual[key], expected[key], rtol=0, atol=1e-12, err_msg=key)


def verify_development(source):
    cells = {}
    original = HERE / "results.json"
    saved_weights = HERE / "reflection_weight_results.json"
    replay, _ = run_study(source, cells)
    with TemporaryDirectory(prefix="potato-replication-dev-") as folder:
        path = Path(folder) / "development.json"
        write_json(path, replay)
        if path.read_bytes() != original.read_bytes():
            raise ValueError("Development replay differs from original results")
    expected_quarter = {
        r["object_id"]: r["fold"]["all_weight_mae_curve_mm"][1]
        for r in json.loads(saved_weights.read_text())["pairs"] if r["fold"] is not None
    }
    quarter = []
    probe_cases = 0
    for row in replay["pairs"]:
        if row["errors_mm"] is None:
            continue
        obj = row["object_id"]
        zero, partial, full = [selected_scores(row, cells[obj], a)["nominal"] for a in (0, WEIGHT, 1)]
        baseline = row["errors_mm"]
        np.testing.assert_allclose([zero["aligned"], zero["shifted"]], baseline["body"], rtol=0, atol=1e-12)
        np.testing.assert_allclose(partial["aligned"], expected_quarter[obj], rtol=0, atol=1e-12)
        assert_errors(full, baseline, ("body", "aligned", "shifted", "each_shift"))
        assert_errors(partial, row["mirror_comparison_mm"], ("clipped_q95",))
        quarter.append(partial["aligned"])
        for key, probe in row["probes"].items():
            matched = selected_scores(row, cells[obj], 1, key)
            for which, old_key in (("nominal", "nominal_same_support_mm"), ("perturbed", "perturbed_mm")):
                assert_errors(matched[which], probe[old_key], ("body", "aligned", "shifted"))
                probe_cases += 1
    result = {"status": "passed", "original_results_sha256": sha256(original),
              "saved_weight_results_sha256": sha256(saved_weights),
              "selected_tubers": 12, "scored_tubers": len(quarter), "probe_reference_checks": probe_cases,
              "quarter_weight_mean_mae_mm": np.mean(quarter),
              "endpoint_mean_mae_mm": {key: replay["summary"]["errors_mm"][key]
                                       for key in ("body", "aligned")}}
    print(f"Development scorer verified on {len(quarter)} tubers and {probe_cases} matched probe/reference cases",
          flush=True)
    return result


def fingerprint(mapping):
    return hashlib.sha256(json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def preflight(source, verification, staged, source_hashes):
    modules = [*HERE.glob("*.py"), *LOBE_STUDY.glob("*.py"),
               HERE.parent / "body_detail_v1/model.py", *(PROJECT / "src/potato3d").rglob("*.py")]
    code = {str(p.relative_to(PROJECT)): sha256(p) for p in sorted(modules)}
    environment = {
        "python": sys.version,
        "interpreter_sha256": sha256(Path(sys.executable)),
        "platform": platform.platform(),
        "packages": {name: version(name) for name in ("numpy", "scipy", "trimesh", "Pillow", "matplotlib", "rtree")},
        "thread_limits": {key: os.environ.get(key) for key in
                          ("OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "OMP_NUM_THREADS")},
        "dependency_file_sha256": {name: sha256(PROJECT / name) for name in ("uv.lock", "pyproject.toml")},
    }
    input_hashes = {**source_hashes, "selected_member_sha256": {
        row["object_id"]: {role: asset["sha256"] for role, asset in row["files"].items()} for row in staged}}
    return {
        "stage": "frozen_replication_preflight",
        "protocol_sha256": sha256(HERE / "replication_protocol.md"),
        "cohort_sha256": sha256(COHORT_PATH),
        "demo_manifest_sha256": sha256(DEMO_PATH),
        "development_selection_sha256": sha256(DEV_SELECTION),
        "development_verification": verification, "source_root": str(source.resolve()),
        "source_sha256": fingerprint(input_hashes), "source_inputs": input_hashes,
        "scorer_sha256": fingerprint(code), "code_sha256": code,
        "environment_sha256": fingerprint(environment), "environment": environment,
        "fixed_weight": WEIGHT, "bootstrap_seed": BOOTSTRAP_SEED, "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "staged_pairs": staged,
    }


def score_tuber(root, metadata, assets, camera, coco):
    obj = metadata["label"]
    result = {**metadata, "frame_id": assets["frame_id"], "failures": list(assets["failures"]),
              "intake_passed": False, "scored_bands": 0, "scored_cells": 0, "scores_mm": None}
    if result["failures"]:
        return result
    try:
        intake, = build_manifest(root, allow_demo=False)["pairs"]
        record, = discover_demo(root)
        if intake["object_id"] != obj or intake["frame_id"] != result["frame_id"]:
            raise ValueError("Staged object or frame differs from the released pairing")
        for role, asset in intake["files"].items():
            if asset["sha256"] != assets["files"][role]["sha256"]:
                raise ValueError(f"{role} differs from its preflight SHA-256")
        result["intake_passed"] = True
        result["raster_check"] = intake["raster_check"]
        result["released_registration_rmse_mm"] = record["published_registration_rmse_mm"]
    except (OSError, ValueError, TypeError, KeyError, np.linalg.LinAlgError) as error:
        result["failures"].append({"stage": "rgbd_intake", "message": str(error)})
        return result

    filename = f"{obj}/{obj}_rgb_{result['frame_id']}.png"
    try:
        markers = pin_ellipses(coco, filename)
    except ValueError as error:
        result["failures"].append({"stage": "released_marker", "message": str(error)})
        return result
    cells = {}
    try:
        row, _ = run_pair(root, record, camera, markers, cells)
    except (OSError, ValueError, TypeError, np.linalg.LinAlgError) as error:
        result["failures"].append({"stage": "registered_geometry", "message": str(error)})
        return result
    for key in ("registration_overlap", "body_fit", "reference_rays", "scored_cells", "scored_bands"):
        if key in row:
            result[key] = row[key]
    result["bands"] = [{k: band[k] for k in ("band", "coverage", "scan_exclusion_flags",
                                            "scan_correction_mm", "mirror_common_cells") if k in band}
                       for band in row.get("bands", [])]
    if row["failure"] is not None:
        result["failures"].append(row["failure"])
        return result
    result["scores_mm"] = selected_scores(row, cells[obj], WEIGHT)["nominal"]
    result["probes"] = {}
    for key, original in row["probes"].items():
        matched = selected_scores(row, cells[obj], WEIGHT, key)
        result["probes"][key] = {
            "transform": original["transform"], "bands": [
                {k: b[k] for k in ("band", "common_cells", "lost_cells", "failed_sectors")}
                for b in original["bands"]],
            "scored_bands": original["scored_bands"], "scored_cells": original["scored_cells"],
            "nominal_same_support_mm": matched["nominal"], "perturbed_mm": matched["perturbed"],
            "lower_abs_displacement_p95_mm": original["lower_abs_displacement_p95_mm"],
        }
    return result


def bootstrap_intervals(rows):
    strata = defaultdict(lambda: defaultdict(list))
    for row in rows:
        strata[row["cultivar"]][row["ros_bag_name"]].append(row["scores_mm"]["aligned_minus_body"])
    groups_per_cultivar = {cultivar: len(strata[cultivar]) for cultivar in CULTIVARS}
    result = {"seed": BOOTSTRAP_SEED, "replicates": BOOTSTRAP_REPLICATES,
              "evaluable_groups_by_cultivar": groups_per_cultivar,
              "missing_cultivars": [cultivar for cultivar, n in groups_per_cultivar.items() if n == 0],
              "sparse_group_cultivars": [cultivar for cultivar, n in groups_per_cultivar.items() if 0 < n <= 3],
              "tuber_percentile_95_mm": None, "group_percentile_95_mm": None}
    if not rows:
        return result

    tuber_rng = np.random.default_rng(BOOTSTRAP_SEED)
    group_rng = np.random.default_rng(BOOTSTRAP_SEED)
    tuber_sum = np.zeros(BOOTSTRAP_REPLICATES)
    group_sum = np.zeros(BOOTSTRAP_REPLICATES)
    group_n = np.zeros(BOOTSTRAP_REPLICATES, dtype=int)
    for cultivar in CULTIVARS:
        grouped = strata[cultivar]
        if not grouped:
            continue
        groups = [grouped[key] for key in sorted(grouped)]
        values = np.concatenate(groups)
        tuber_indices = tuber_rng.integers(len(values), size=(BOOTSTRAP_REPLICATES, len(values)))
        tuber_sum += values[tuber_indices].sum(axis=1)
        group_indices = group_rng.integers(len(groups), size=(BOOTSTRAP_REPLICATES, len(groups)))
        group_sum += np.array([sum(g) for g in groups])[group_indices].sum(axis=1)
        group_n += np.array([len(g) for g in groups])[group_indices].sum(axis=1)
    result["tuber_percentile_95_mm"] = np.percentile(tuber_sum / len(rows), [2.5, 97.5])
    result["group_percentile_95_mm"] = np.percentile(group_sum / group_n, [2.5, 97.5])
    return result


def coverage_summary(rows):
    evaluated = [row for row in rows if row["scores_mm"] is not None]
    return {"selected_tubers": len(rows), "intake_passed_tubers": sum(r["intake_passed"] for r in rows),
            "overlap_passed_tubers": sum(r.get("registration_overlap", {}).get("passes", False) for r in rows),
            "body_fits": sum("body_fit" in r for r in rows),
            "evaluable_tubers": len(evaluated), "planned_bands": len(rows)*len(BANDS),
            "evaluable_bands": sum(r["scored_bands"] for r in evaluated),
            "scored_cells": sum(r["scored_cells"] for r in evaluated)}


def score_summary(scores):
    valid = [s for s in scores if s is not None]
    complete_mirror = [s for s in valid if s["clipped_q95"] is not None]
    return {"scores_mm": average_scores(valid, SCORE_KEYS[:-1]),
            "mirror_matched_tubers": len(complete_mirror),
            "mirror_matched_scores_mm": average_scores(complete_mirror, ("body", "aligned", "clipped_q95"))}


def summarize_replication(rows):
    evaluated = [row for row in rows if row["scores_mm"] is not None]
    deltas = [r["scores_mm"]["aligned_minus_body"] for r in evaluated]
    mean = np.mean(deltas) if deltas else None
    for row in evaluated:
        remaining = [r["scores_mm"]["aligned_minus_body"] for r in evaluated if r is not row]
        omitted = np.mean(remaining) if remaining else None
        row["mean_delta_if_tuber_omitted_mm"] = omitted
        row["change_in_mean_if_tuber_omitted_mm"] = omitted - mean if remaining else None
    cultivar_summary, group_summary = {}, []
    for cultivar in CULTIVARS:
        subset = [r for r in rows if r["cultivar"] == cultivar]
        cultivar_summary[cultivar] = coverage_summary(subset)
        for group in sorted({r["ros_bag_name"] for r in subset}):
            group_rows = [r for r in subset if r["ros_bag_name"] == group]
            group_deltas = [r["scores_mm"]["aligned_minus_body"] for r in group_rows
                            if r["scores_mm"] is not None]
            others = [r["scores_mm"]["aligned_minus_body"] for r in evaluated
                      if (r["cultivar"], r["ros_bag_name"]) != (cultivar, group)]
            group_summary.append({"cultivar": cultivar, "acquisition_group": group, **coverage_summary(group_rows),
                                  "mean_delta_mm": np.mean(group_deltas) if group_deltas else None,
                                  "mean_delta_if_group_omitted_mm": np.mean(others) if others else None})
    probes = {}
    for key in sorted({k for row in evaluated for k in row["probes"]}):
        attempted = [r["probes"][key] for r in evaluated]
        probes[key] = {
            "evaluable_tubers": sum(p["scored_bands"] > 0 for p in attempted),
            "evaluable_bands": sum(p["scored_bands"] for p in attempted),
            "scored_cells": sum(p["scored_cells"] for p in attempted),
            "lost_scored_cells": sum(r["scored_cells"] for r in evaluated) - sum(p["scored_cells"] for p in attempted),
            **{case: score_summary([p[case] for p in attempted])
               for case in ("nominal_same_support_mm", "perturbed_mm")},
        }
    return {
        "coverage": coverage_summary(rows), "coverage_by_cultivar": cultivar_summary, "coverage_by_group": group_summary,
        "failure_tubers_by_stage": dict(Counter(stage for r in rows for stage in {f["stage"] for f in r["failures"]})),
        **score_summary([r["scores_mm"] for r in evaluated]),
        "primary": {"mean_delta_mm": mean, "median_delta_mm": np.median(deltas) if deltas else None,
                    "wins": sum(d < 0 for d in deltas), "ties": sum(d == 0 for d in deltas),
                    "losses": sum(d > 0 for d in deltas), **bootstrap_intervals(evaluated)},
        "registration_probes": probes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=HERE)
    args = parser.parse_args()
    verification = verify_development(args.source)
    if args.verify_only:
        return

    preflight_path = args.out_dir / "replication_preflight.json"
    with TemporaryDirectory(prefix="potato-replication-") as folder:
        root = Path(folder)
        cohort, staged, source_hashes = stage_replication(args.source, root)
        write_json(preflight_path, preflight(args.source, verification, staged, source_hashes))
        print("Replication inputs and scorer hashed before scoring", flush=True)
        camera = json.loads((args.source / INTRINSICS).read_text())
        intrinsics = np.asarray(camera["intrinsic_matrix"]).reshape(3, 3, order="F")
        coco = json.loads((args.source / METADATA["pin_regions.json"]).read_text())
        rows = []
        for metadata, assets in zip(cohort, staged, strict=True):
            row = score_tuber(root / metadata["label"], metadata, assets, intrinsics, coco)
            status = ", ".join(f["stage"] for f in row["failures"]) or f"{row['scored_bands']} of 2 bands"
            print(f"{metadata['label']}: {status}", flush=True)
            rows.append(row)
    result = {"stage": "fixed_quarter_weight_replication", "preflight_sha256": sha256(preflight_path),
              "weight": WEIGHT, "shift_offsets_sectors": SHIFTS, "summary": summarize_replication(rows), "pairs": rows}
    write_json(args.out_dir / "replication_results.json", result)


if __name__ == "__main__":
    main()
