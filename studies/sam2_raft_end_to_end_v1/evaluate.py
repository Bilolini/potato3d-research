"""Lock the analysis, then score the archived-calibration mask substitution."""

import argparse
from contextlib import ExitStack
import csv
import math
from pathlib import Path
import time
from zipfile import BadZipFile, ZipFile

import numpy as np

import common as c
import alignment as align
import score as geo

COMPARISONS = ("D-B", "D-C", "B-A")
GEOMETRY_METRICS = ("coverage_fraction", "far_fraction", "equal_coverage_fraction")
SEAL = c.STUDY / "analysis_freeze.json"
PREDICTIONS = c.STUDY / "predictions_before_targets.json"
FAILURES = (ValueError, RuntimeError, OSError, BadZipFile, KeyError, np.linalg.LinAlgError)


def sealed_inputs():
    files = [
        *(c.STUDY / name for name in ("protocol.md", "frame_manifest.json", "common.py", "track.py",
                                     "build.py", "provided.py", "evaluate.py", "audit.py")),
        c.PILOT / "score.py", c.PILOT / "score_freeze.json", c.PILOT / "registration.json",
        c.PILOT / "per_potato.csv", c.TRAIT_STUDY / "predictions_before_targets.json",
        c.TRAIT_STUDY / "train_fit.json", c.TRAITS,
    ]
    return {
        "files": {str(path.relative_to(c.ROOT)): c.prep.digest(path) for path in files},
        "bootstrap_draws": c.DRAWS, "bootstrap_seed": c.SEED, "geometry_voxel_mm": 1.,
        "geometry_samples": geo.SAMPLES, "distance_threshold_mm": geo.THRESHOLD,
        "equal_count_repeats": geo.REPEATS, "geometry_sample_seed": c.prep.SEED,
        "primary": "D-B weight absolute error",
    }


def seal():
    c.frame_manifest()
    c.prep.freeze_check(SEAL, sealed_inputs())
    print("Sealed scorer, source predictions, metrics and archived coefficient provenance.", flush=True)


def verify():
    if c.prep.read_json(SEAL) != sealed_inputs():
        raise ValueError("Analysis differs from the frozen protocol or source files")


def load_inputs():
    freeze, _ = c.tracking_bundle()
    manifest_hash = c.prep.digest(c.STUDY / "frame_manifest.json")
    predicted_ledger = c.prep.read_json(c.STUDY / "predicted_input_ledger.json")
    provided_ledger = c.prep.read_json(c.STUDY / "provided_replay.json")
    if (predicted_ledger["recipe"]["manifest_sha256"] != manifest_hash
            or provided_ledger["frame_manifest_sha256"] != manifest_hash):
        raise ValueError("Reconstruction receipts reference different frozen input IDs")
    roles = (("provided", provided_ledger), ("predicted", predicted_ledger))
    cases = [r["tuber"] for r in freeze["roster"]]
    records = []
    for stage, ledger in roles:
        if [row["tuber"] for row in ledger["records"]] != cases:
            raise ValueError("Reconstruction ledger lost an enrolled ID")
        by_tuber = {}
        for row in ledger["records"]:
            tuber = row["tuber"]
            path = c.OUTPUT / stage / f"{tuber}.json"
            if c.prep.digest(path) != row["sha256"]:
                raise ValueError(f"Frozen reconstruction changed: {path}")
            by_tuber[tuber] = c.prep.read_json(path)
        records.append(by_tuber)
    return freeze, *records


def predict():
    verify()
    freeze, provided, predicted = load_inputs()
    old_file = c.TRAIT_STUDY / "predictions_before_targets.json"
    old = c.prep.read_json(old_file)
    if old["train_fit_sha256"] != c.prep.digest(c.TRAIT_STUDY / "train_fit.json"):
        raise ValueError("Archived predictions do not reference their evaluated fit")
    archived = c.by_tuber(old["predictions"])
    rows = []
    max_differences = {trait: {"A": 0., "C": 0.} for trait in c.TARGETS}
    for case in freeze["roster"]:
        if case["analysis"] != "traits":
            continue
        tuber = case["tuber"]
        features = {**provided[tuber]["features"], **predicted[tuber]["features"]}
        proxies = {name: value["proxy_cm3"] if value is not None else None for name, value in features.items()}
        result = {}
        for trait, models in freeze["fits"].items():
            guesses = {
                k: max(0., models[k]["intercept"] + models[k]["slope_per_cm3"] * x) if x is not None else None
                for k, x in proxies.items()
            }
            for method, original in (("A", "A"), ("C", "D")):
                diff = abs(guesses[method] - archived[tuber]["prediction"][trait][original])
                max_differences[trait][method] = max(max_differences[trait][method], diff)
                if diff > 1e-7:
                    raise ValueError(f"Provided-mask prediction did not replay: {tuber} {trait} {method}")
            result[trait] = guesses
        rows.append({"tuber": tuber, "selected": case["selected"], "proxy_cm3": proxies,
                     "predicted_mask_failures": predicted[tuber]["failures"], "predictions": result})
    c.prep.freeze_check(PREDICTIONS, {
        "analysis_sha256": c.prep.digest(SEAL), "provided_replay_sha256": c.prep.digest(c.STUDY / "provided_replay.json"),
        "predicted_input_sha256": c.prep.digest(c.STUDY / "predicted_input_ledger.json"),
        "provided_prediction_max_abs_change": max_differences, "rows": rows,
    })
    print("Replayed supplied-mask predictions and saved all four conditions before joining outcomes.", flush=True)


def trait_references(ids):
    rows = {}
    with c.TRAITS.open(newline="") as stream:
        for row in csv.DictReader(stream):
            tuber = row["label"]
            if tuber not in ids:
                continue
            if tuber in rows:
                raise ValueError(f"Duplicate physical trait row for {tuber}")
            measured = {}
            for trait, column in c.TARGETS.items():
                value = float(row[column]) if row[column] else float("nan")
                measured[trait] = value if math.isfinite(value) and value > 0 else None
            rows[tuber] = measured
    if set(rows) != ids:
        raise ValueError("Missing trait row for a frozen evaluation ID")
    return rows


def pair(rows, first, second, scale=1., direction=1, tie=1e-9):
    ok = [row for row in rows if row[first] is not None and row[second] is not None]
    a = np.asarray([r[first] for r in ok], dtype=float) * scale
    b = np.asarray([r[second] for r in ok], dtype=float) * scale
    if not ok:
        return {"n": 0, "ids": [], "first_mean": None, "baseline_mean": None, "change": None,
                "interval_95": None, "wins": 0, "ties": 0, "losses": 0}
    diff = a - b
    indices = np.random.default_rng(c.SEED).integers(len(ok), size=(c.DRAWS, len(ok)))
    interval = np.quantile(diff[indices].mean(axis=1), [0.025, 0.975]).tolist()
    return {"n": len(ok), "ids": [r["tuber"] for r in ok], "first_mean": float(a.mean()),
            "baseline_mean": float(b.mean()), "change": float(diff.mean()), "interval_95": interval,
            "wins": int((diff * direction > tie).sum()), "ties": int((abs(diff) <= tie).sum()),
            "losses": int((diff * direction < -tie).sum())}


def add_diff(row, left, right, key):
    row[key] = row[left] - row[right] if row[left] is not None and row[right] is not None else None


def score_traits():
    started = time.perf_counter()
    saved = c.prep.read_json(PREDICTIONS)
    checks = {"analysis_sha256": SEAL, "provided_replay_sha256": c.STUDY / "provided_replay.json",
              "predicted_input_sha256": c.STUDY / "predicted_input_ledger.json"}
    if any(saved[key] != c.prep.digest(path) for key, path in checks.items()):
        raise ValueError("Sealed predictions differ from their source")
    predictions = saved["rows"]
    measured = trait_references({r["tuber"] for r in predictions})
    rows = []
    for record in predictions:
        tuber = record["tuber"]
        row = {"tuber": tuber, "lower": record["selected"][0], "center": record["selected"][1],
               "upper": record["selected"][2], **{f"{m}_proxy_cm3": x for m, x in record["proxy_cm3"].items()},
               **{f"{m}_failure": err for m, err in record["predicted_mask_failures"].items()}}
        for trait, estimates in record["predictions"].items():
            truth = measured[tuber][trait]
            row[f"{trait}_measured"] = truth
            for m in c.METHODS:
                x = estimates[m]
                row[f"{trait}_{m}_estimate"] = x
                row[f"{trait}_{m}_error"] = abs(x - truth) if x is not None and truth is not None else None
            for comparison in COMPARISONS:
                a, b = comparison.split("-")
                add_diff(row, f"{trait}_{a}_error", f"{trait}_{b}_error", f"{trait}_{comparison}")
            selected = "D" if estimates["D"] is not None else "B"
            row.update({f"{trait}_fallback_used": selected == "B" and estimates["B"] is not None,
                        f"{trait}_fallback_estimate": estimates[selected], f"{trait}_fallback_error": row[f"{trait}_{selected}_error"]})
        rows.append(row)
    summary = {}
    for trait in c.TARGETS:
        methods = {}
        for m in c.METHODS:
            values = [r[f"{trait}_{m}_error"] for r in rows if r[f"{trait}_{m}_error"] is not None]
            methods[m] = {"n": len(values), "mae": float(np.mean(values)) if values else None}
        summary[trait] = {"methods": methods, "paired": {}}
        for comparison in COMPARISONS:
            a, b = comparison.split("-")
            summary[trait]["paired"][comparison] = pair(rows, f"{trait}_{a}_error", f"{trait}_{b}_error", direction=-1)
        summary[trait]["fallback_vs_B"] = pair(rows, f"{trait}_fallback_error", f"{trait}_B_error", direction=-1)
    return rows, summary, saved["provided_prediction_max_abs_change"], time.perf_counter() - started


def read_clouds(directory, tuber, row):
    if row["cloud_sha256"] is None:
        return {}
    file = c.OUTPUT / directory / f"{tuber}.npz"
    if c.prep.digest(file) != row["cloud_sha256"]:
        raise ValueError(f"Frozen cloud cache changed: {file}")
    with np.load(file, allow_pickle=False) as data:
        return {name: data[name] for name in data.files}


def baseline_geometry(tuber, clouds, old_register, old_row, samples, scene):
    path = c.prep.ASSETS / "clouds" / f"{tuber}.npz"
    if c.prep.digest(path) != old_register["cloud_sha256"]:
        raise ValueError(f"Frozen geometry pilot clouds changed: {tuber}")
    with np.load(path, allow_pickle=False) as file:
        old_clouds = {k: file[k] for k in geo.METHODS}
    archived_count, archive_equal = geo.equal_counts(old_clouds, samples)
    if archived_count != int(old_row["equal_points"]):
        raise ValueError(f"Archived point-count baseline did not replay: {tuber}")
    diff_mm = {}
    for method, original in (("A", "center"), ("C", "raft")):
        old = old_clouds[original]
        current = clouds[method]
        if old.shape != current.shape or not np.allclose(current, old, rtol=0, atol=1e-8):
            raise ValueError(f"Frozen geometry cloud did not replay: {tuber} {method}")
        diff_mm[method] = float(np.abs(current - old).max())
        metrics, _ = geo.score_cloud(current, samples, scene)
        if (any(abs(v - float(old_row[f"{original}_{k}"])) > 1e-10 for k, v in metrics.items())
                or abs(archive_equal[original] - float(old_row[f"{original}_equal_coverage_fraction"])) > 1e-10):
            raise ValueError(f"Frozen geometry measurements did not replay: {tuber} {method}")
    return diff_mm


def geometry_row(plan, case, provided, predicted, old_register, old_row, ref_archive):
    tuber = case["tuber"]
    row = {"tuber": tuber, "lower": case["selected"][0], "center": case["selected"][1], "upper": case["selected"][2],
           "reference_failure": None, "reference_area_mm2": None, "equal_points": None}
    for m in c.METHODS:
        for metric in (*GEOMETRY_METRICS, "points", "new_area_mm2", "lost_area_mm2"):
            row[f"{m}_{metric}"] = None
        row[f"{m}_failure"] = predicted["failures"].get(m)
    try:
        mesh = geo.load_reference(ref_archive, plan["reference"])
        samples, _ = geo.sample_surface(mesh, geo.SAMPLES, c.prep.SEED)
        scene = geo.mesh_scene(mesh)
        row["reference_area_mm2"] = float(mesh.area)
    except FAILURES as error:
        row["reference_failure"] = str(error)
        return row
    raw = {**read_clouds("provided", tuber, provided), **read_clouds("predicted", tuber, predicted)}
    anchor = align.in_mm(plan["center_to_sfm_m"])
    clouds = {m: align.voxel(align.apply(points, anchor), 1.) for m, points in raw.items()}
    replay_diff = baseline_geometry(tuber, clouds, old_register, old_row, samples, scene)
    row.update({f"{m}_max_archived_xyz_diff_mm": x for m, x in replay_diff.items()})
    covered = {}
    scorable = {}
    for m, cloud in clouds.items():
        try:
            values, covered[m] = geo.score_cloud(cloud, samples, scene)
            row.update({f"{m}_{metric}": x for metric, x in values.items()})
            scorable[m] = cloud
        except FAILURES as error:
            row[f"{m}_failure"] = f"Geometry scoring: {error}"

    row["equal_points"], rates = equal_counts(scorable, samples)
    for m, value in rates.items():
        row[f"{m}_equal_coverage_fraction"] = value
    for m, base in (("D", "B"), ("C", "A")):
        if m in covered and base in covered:
            a, b = covered[m], covered[base]
            row[f"{m}_new_area_mm2"] = float((a & ~b).mean() * mesh.area)
            row[f"{m}_lost_area_mm2"] = float((~a & b).mean() * mesh.area)
    for comparison in COMPARISONS:
        a, b = comparison.split("-")
        for metric in GEOMETRY_METRICS:
            add_diff(row, f"{a}_{metric}", f"{b}_{metric}", f"{comparison}_{metric}")
    return row


def equal_counts(clouds, samples):
    from scipy.spatial import cKDTree

    n = min(map(len, clouds.values())) if clouds else None
    rates = {}
    for method, points in clouds.items():
        rng = np.random.default_rng(c.prep.SEED)
        subsets = [points] if len(points) == n else (
            points[rng.choice(len(points), size=n, replace=False)] for _ in range(geo.REPEATS)
        )
        rates[method] = float(np.mean([np.mean(cKDTree(subset).query(samples)[0] <= geo.THRESHOLD)
                                       for subset in subsets]))
    return n, rates


def score_geometry(freeze, provided, predicted):
    started = time.perf_counter()
    plans = c.by_tuber(c.prep.read_json(c.PILOT / "frame_manifest.json")["roster"])
    register = c.by_tuber(c.prep.read_json(c.PILOT / "registration.json")["potatoes"])
    old = c.by_tuber(c.csv_rows(c.PILOT / "per_potato.csv"))
    known = geo.metric_check()
    rows = []
    with ZipFile(c.prep.MESHES) as archive:
        for case in freeze["roster"]:
            if case["analysis"] != "geometry":
                continue
            tuber = case["tuber"]
            row = geometry_row(plans[tuber], case, provided[tuber], predicted[tuber], register[tuber], old[tuber], archive)
            rows.append(row)
            print(f"Geometry {len(rows)}/10: {tuber}", flush=True)
    methods = {}
    for m in c.METHODS:
        outcomes = {}
        for metric in (*GEOMETRY_METRICS, "new_area_mm2", "lost_area_mm2"):
            values = [r[f"{m}_{metric}"] for r in rows if r[f"{m}_{metric}"] is not None]
            outcomes[metric] = {"n": len(values), "mean": float(np.mean(values)) if values else None}
        methods[m] = outcomes
    paired = {}
    for comparison in COMPARISONS:
        a, b = comparison.split("-")
        paired[comparison] = {metric: pair(rows, f"{a}_{metric}", f"{b}_{metric}", scale=100.,
                                             direction=-1 if metric == "far_fraction" else 1)
                              for metric in GEOMETRY_METRICS}
    return rows, {"methods": methods, "paired_percentage_points": paired, "known_distances": known,
                  "provided_geometry_replay_n": sum(r.get("C_max_archived_xyz_diff_mm") is not None for r in rows),
                  "scoring_wall_s": time.perf_counter() - started}


def diagnostics(freeze, predicted, geo_rows):
    tracking = c.by_tuber(c.prep.read_json(c.STUDY / "tracking_replay.json")["rows"])
    audit = c.by_tuber(c.prep.read_json(c.STUDY / "tracking_audit.json")["rows"])
    failures, frame_checks, links, runtime = [], [], [], []
    for case in freeze["roster"]:
        tuber, analysis = case["tuber"], case["analysis"]
        row = predicted[tuber]
        track = tracking[tuber]
        tag = {"tuber": tuber, "analysis": analysis}
        if track["failure"]:
            failures.append({**tag, "stage": "tracking", "source": None, "target": None, "reason": track["failure"]})
        if track["status"] == "skipped":
            failures.append({**tag, "stage": "tracking", "source": None, "target": None, "reason": "Operator skipped"})
        for view in row["views"]:
            frame_checks.append({**tag, **view})
            if view["error"]:
                failures.append({**tag, "stage": "mask-depth support", "source": view["suffix"], "target": None,
                                 "reason": view["error"]})
        for link in row["links"]:
            links.append({**tag, **link})
            if link["failure"]:
                failures.append({**tag, "stage": "RAFT link", "source": link["source"], "target": link["target"],
                                 "reason": link["failure"]})
        for m, reason in row["failures"].items():
            if reason:
                failures.append({**tag, "stage": m, "source": None, "target": None, "reason": reason})
        center = case["selected"][1]
        runtime.append({
            **tag, "tracking_through_center_s": track["center_elapsed_s"], "tracking_total_s": track["wall_s"],
            "tracked_extension_s": track["post_center_wall_s"],
            "center_depth_s": sum(v["wall_s"] for v in row["views"] if v["suffix"] == center),
            "other_depth_s": sum(v["wall_s"] for v in row["views"] if v["suffix"] != center),
            "raft_rgb_decode_s": sum(x["rgb_wall_s"] for x in row["links"]),
            "raft_flow_s": sum(x["flow_wall_s"] for x in row["links"]),
            "raft_lift_fit_s": sum(x["fit_wall_s"] for x in row["links"]),
            "center_feature_s": row["center_feature_wall_s"], "merge_voxel_feature_s": row["fuse_feature_wall_s"],
        })
    for row in geo_rows:
        if row["reference_failure"]:
            failures.append({"tuber": row["tuber"], "analysis": "geometry", "stage": "SfM reference",
                             "source": None, "target": None, "reason": row["reference_failure"]})
        for m in c.METHODS:
            reason = row[f"{m}_failure"]
            if reason and reason.startswith("Geometry scoring:"):
                failures.append({"tuber": row["tuber"], "analysis": "geometry", "stage": m,
                                 "source": None, "target": None, "reason": reason})

    c.write_csv(c.STUDY / "registration_links.csv", links)
    c.write_csv(c.STUDY / "depth_support_by_frame.csv", frame_checks)
    c.write_csv(c.STUDY / "failures.csv", failures, ["tuber", "analysis", "stage", "source", "target", "reason"])
    c.write_csv(c.STUDY / "runtime_by_potato.csv", runtime)
    groups = {}
    for subset in ("geometry", "traits", "all"):
        timings = [r for r in runtime if subset == "all" or r["analysis"] == subset]
        records = [predicted[r["tuber"]] for r in timings]
        tracked = [tracking[r["tuber"]] for r in timings]
        group_audit = [audit[r["tuber"]] for r in timings]
        sums = {k: sum(r[k] or 0. for r in timings) for k in timings[0] if k not in ("tuber", "analysis")}
        incremental = ("tracked_extension_s", "other_depth_s", "raft_rgb_decode_s", "raft_flow_s",
                       "raft_lift_fit_s", "merge_voxel_feature_s")
        groups[subset] = {
            "n": len(timings), "center_exact_replays": sum(r["center_difference_pixels"] == 0 for r in tracked),
            "tracking_returned_through_upper": sum(r["status"] == "returned" for r in tracked),
            "skips": sum(r["status"] == "skipped" for r in tracked),
            "tracks_with_empty_frames": [r["tuber"] for r in tracked if r["empty_suffixes"]],
            "tracks_with_loss": [r["tuber"] for r in group_audit if r["loss_suffixes"]],
            "tracks_with_pin_takeover": [r["tuber"] for r in group_audit if r["pin_takeover_suffixes"]],
            "tracks_initial_pin": [r["tuber"] for r in group_audit if r["prompt_state"] == "pin"],
            "upper_potato_matches": sum(r["upper_state"] == "potato" for r in group_audit),
            "usable_geometry": {m: sum(r["features"][m] is not None for r in records) for m in "BD"},
            "failed_links": [f for f in failures if (subset == "all" or f["analysis"] == subset) and f["stage"] == "RAFT link"],
            "incremental_D_minus_B_wall_s": sum(sums[k] for k in incremental),
            "timed_components": sums,
        }
    return groups


def score():
    verify()
    output = c.STUDY / "results.json"
    if output.exists():
        raise ValueError("Frozen evaluation already has a result")
    freeze, provided, predicted = load_inputs()
    trait_rows, traits, replay, trait_runtime = score_traits()
    geo_rows, geometry = score_geometry(freeze, provided, predicted)
    groups = diagnostics(freeze, predicted, geo_rows)
    c.write_csv(c.STUDY / "geometry_per_potato.csv", geo_rows)
    c.write_csv(c.STUDY / "traits_per_potato.csv", trait_rows)
    result = {
        "predictions_sha256": c.prep.digest(PREDICTIONS),
        "coverage_tracking_and_runtime": groups, "geometry": geometry, "traits": traits,
        "archived_provided_trait_prediction_max_error": replay, "trait_scoring_wall_s": trait_runtime,
        "raft_model_setup_wall_s": c.prep.read_json(c.STUDY / "predicted_input_ledger.json")["raft_setup_wall_s"],
        "provided_replay_wall_s": c.prep.read_json(c.STUDY / "provided_replay.json")["wall_s"],
        "geometry_scores_sha256": c.prep.digest(c.STUDY / "geometry_per_potato.csv"),
        "trait_scores_sha256": c.prep.digest(c.STUDY / "traits_per_potato.csv"),
        "fallback_ids": [r["tuber"] for r in trait_rows if r["weight_fallback_used"] or r["volume_fallback_used"]],
    }
    c.prep.write_json(output, result)
    print("Primary paired statistics:", result["traits"]["weight"]["paired"]["D-B"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "predict", "score"))
    args = parser.parse_args()
    {"freeze": seal, "predict": predict, "score": score}[args.stage]()
