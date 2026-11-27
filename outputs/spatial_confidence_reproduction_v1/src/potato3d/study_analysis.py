"""Predetermined, family-paired analysis for height_development_v1."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json

import numpy as np

from .io import sha256, write_json
from .pipeline import write_csv


METRICS = ["chamfer_l1_mm", "hidden_chamfer_l1_mm", "volume_absolute_error_analytic_ml",
           "observed_to_surface_mean_mm", "clean_observed_to_surface_mean_mm",
           "height_absolute_error_mm", "prediction_below_true_belt_mm", "fit_seconds"]


def cluster_estimate(values_by_cluster, replicates, seed):
    values = np.array([np.mean(v) for _, v in sorted(values_by_cluster.items()) if len(v)])
    if not len(values):
        return {"mean": None, "ci95": None, "independent_families": 0}
    ci = None
    if len(values) >= 10:
        bootstrap = np.random.default_rng(seed).choice(values, size=(replicates, len(values)), replace=True).mean(axis=1)
        ci = np.quantile(bootstrap, [.025, .975]).tolist()
    return {"mean": float(values.mean()), "ci95": ci, "independent_families": len(values)}


def paired_difference(rows, metadata, candidate, baseline, condition, metric, protocol, profile=None):
    lookup = {(r["object_id"], r["method"]): r for r in rows if r["condition"] == condition}
    cases = [m for m in metadata if m["condition"] == condition and
             (profile is None or m["underside_warp"] == profile)]
    families = defaultdict(list)
    missing, differences = [], []
    for case in cases:
        pid = case["object_id"]
        a, b = lookup.get((pid, candidate)), lookup.get((pid, baseline))
        if a is None or b is None or a["status"] != "ok" or b["status"] != "ok" or a.get(metric) is None or b.get(metric) is None:
            missing.append(pid)
            continue
        difference = a[metric]-b[metric]
        families[case["family_id"]].append(difference)
        differences.append({"object_id": pid, "family_id": case["family_id"], "difference": difference})
    return {"candidate": candidate, "baseline": baseline, "condition": condition, "metric": metric,
            "profile": "combined" if profile is None else profile,
            "difference_sign": "candidate minus baseline; negative favors candidate for these errors",
            "expected_shape_pairs": len(cases), "available_shape_pairs": len(differences),
            "missing_shape_pairs": missing, "complete_case_only": bool(missing),
            **cluster_estimate(families, protocol["bootstrap_replicates"], protocol["bootstrap_seed"]),
            "per_object_differences": differences}


def analyze(run_path: Path):
    path = Path(run_path)
    rows = json.loads((path/"results.json").read_text())
    inputs = json.loads((path/"inputs.json").read_text())
    config = json.loads((path/"config.json").read_text())
    protocol = config["development_protocol"]
    seal = json.loads(Path("docs/height_development_v1_seal.json").read_text())
    if config["protocol_sha256"] != seal["protocol_sha256"]:
        raise ValueError("Run does not match the sealed development protocol")
    comparisons = []
    comparison_metrics = ["hidden_chamfer_l1_mm", "volume_absolute_error_analytic_ml",
                          "clean_observed_to_surface_mean_mm", "height_absolute_error_mm"]
    for condition in protocol["conditions"]:
        for a, b in [("symmetry_height95", "symmetry"), ("symmetry_robust95", "symmetry"),
                     ("symmetry_robust95", "symmetry_height95")]:
            for metric in comparison_metrics:
                for profile in [None, *protocol["underside_warps"]]:
                    comparisons.append(paired_difference(rows, inputs, a, b, condition, metric, protocol, profile))
    a, b = protocol["primary_comparison"]
    primary = [paired_difference(rows, inputs, a, b, protocol["primary_condition"], metric, protocol)
               for metric in protocol["primary_metrics"]]
    guard = paired_difference(rows, inputs, a, b, "clean", "clean_observed_to_surface_mean_mm", protocol)
    primary_passed = all(r["mean"] is not None and r["mean"] < 0 and r["ci95"] is not None
                         and r["ci95"][1] < 0 and not r["missing_shape_pairs"] for r in primary)
    guard_passed = guard["mean"] is not None and guard["mean"] <= protocol["guardrail_max_degradation_mm"] and not guard["missing_shape_pairs"]
    grouped = []
    input_lookup = {(i["object_id"], i["condition"]): i for i in inputs}
    for condition in protocol["conditions"]:
        for method in protocol["methods"]:
            for profile in [None, *protocol["underside_warps"]]:
                selected = [r for r in rows if r["condition"] == condition and r["method"] == method and
                            (profile is None or input_lookup[(r["object_id"], condition)]["underside_warp"] == profile)]
                result = {"condition": condition, "method": method, "profile": "combined" if profile is None else profile,
                          "attempted_shapes": len(selected), "failed_shapes": sum(r["status"] != "ok" for r in selected)}
                for metric in METRICS:
                    values = defaultdict(list)
                    for row in selected:
                        if row["status"] == "ok" and row.get(metric) is not None:
                            values[input_lookup[(row["object_id"], condition)]["family_id"]].append(row[metric])
                    result[metric] = cluster_estimate(values, protocol["bootstrap_replicates"], protocol["bootstrap_seed"])
                grouped.append(result)
    twin_groups = defaultdict(list)
    for case in inputs:
        twin_groups[(case["family_id"], case["condition"])].append(case)
    identical_inputs = 0
    identical_predictions = 0
    prediction_pairs = 0
    missing_twin_predictions = 0
    for (_, condition), twins in twin_groups.items():
        if len(twins) != len(protocol["underside_warps"]):
            raise ValueError("Missing twin input in the experiment")
        identical_inputs += len({t["canonical_partial_sha256"] for t in twins}) == 1
        for method in protocol["methods"]:
            files = [path/t["object_id"]/condition/f"{method}.ply" for t in twins]
            prediction_pairs += 1
            if not all(f.exists() for f in files):
                missing_twin_predictions += 1
                continue
            identical_predictions += len({sha256(f) for f in files}) == 1
    report = {"protocol_id": protocol["protocol_id"], "scope": "synthetic development only; no real-data or novelty claim",
              "results_sha256": sha256(path/"results.json"), "inputs_sha256": sha256(path/"inputs.json"),
              "protocol_sha256": config["protocol_sha256"], "families": protocol["families"],
              "shape_objects": len({r["object_id"] for r in rows}), "predictions": len(rows),
              "failed_predictions": sum(r["status"] != "ok" for r in rows),
              "primary": primary, "clean_guardrail": guard,
              "primary_endpoints_passed": primary_passed, "clean_guardrail_passed": bool(guard_passed),
              "predefined_development_hypothesis_supported": bool(primary_passed and guard_passed),
              "identifiability_check": {"expected_twin_input_pairs": len(twin_groups),
                                        "identical_twin_input_pairs": int(identical_inputs),
                                        "expected_twin_prediction_pairs": prediction_pairs,
                                        "identical_twin_prediction_pairs": int(identical_predictions),
                                        "missing_twin_prediction_pairs": missing_twin_predictions,
                                        "interpretation": "Identical visible inputs must not reveal which hidden underside was used"},
              "group_summary": grouped, "paired_comparisons": comparisons}
    return report


def save_analysis(path: Path, output: Path):
    output.mkdir(parents=True, exist_ok=False)
    report = analyze(path)
    write_json(output/"analysis.json", report)
    flat = []
    for row in report["group_summary"]:
        record = {k: v for k, v in row.items() if k not in METRICS}
        for metric in METRICS:
            for label, value in row[metric].items():
                record[f"{metric}_{label}"] = value
        flat.append(record)
    write_csv(output/"group_summary.csv", flat)
    write_csv(output/"paired_comparisons.csv", [{k: v for k, v in row.items() if k != "per_object_differences"}
                                              for row in report["paired_comparisons"]])
    return report
