"""Fixed paired confirmation criteria and full spatial-study reporting."""
from collections import defaultdict
import json
from pathlib import Path

import numpy as np

from .io import sha256, write_json
from .pipeline import write_csv
from .study_analysis import METRICS, cluster_estimate, paired_difference


def criterion_passes(result, criterion, expected_families):
    if result["missing_shape_pairs"] or result["ci95"] is None or result["independent_families"] != expected_families:
        return False
    upper = result["ci95"][1]
    limit = criterion["upper_difference_limit"]
    return bool(upper < limit if criterion["strict"] else upper <= limit)


def analyze_spatial_run(path):
    path = Path(path)
    config = json.loads((path/"config.json").read_text())
    rows = json.loads((path/"results.json").read_text())
    inputs = json.loads((path/"inputs.json").read_text())
    protocol, split = config["spatial_protocol"], config["split"]
    meta = {(i["object_id"], i["condition"]): i for i in inputs}
    metrics = [*METRICS, "confidence_flagged_fraction", "confidence_fallback_points"]
    summary = []
    for condition in protocol["conditions"]:
        for method in config["methods"]:
            for profile in [None, *protocol["underside_warps"]]:
                selected = [r for r in rows if r["condition"] == condition and r["method"] == method and
                            (profile is None or meta[(r["object_id"], condition)]["underside_warp"] == profile)]
                record = {"condition": condition, "method": method, "profile": "combined" if profile is None else profile,
                          "attempted_shapes": len(selected), "failed_shapes": sum(r["status"] != "ok" for r in selected)}
                for metric in metrics:
                    families = defaultdict(list)
                    for row in selected:
                        if row["status"] == "ok" and row.get(metric) is not None:
                            families[meta[(row["object_id"], condition)]["family_id"]].append(row[metric])
                    record[metric] = cluster_estimate(families, protocol["bootstrap_replicates"], protocol["bootstrap_seed"])
                summary.append(record)
    criteria = []
    if split == "confirmation":
        for criterion in protocol["confirmation_criteria"]:
            result = paired_difference(rows, inputs, "symmetry_spatial", criterion["baseline"],
                                       criterion["condition"], criterion["metric"], protocol)
            result.update(criterion=criterion, passed=criterion_passes(result, criterion, protocol["splits"][split]["families"]))
            criteria.append(result)
    comparisons = []
    candidates = (["symmetry_spatial", "symmetry_spatial_height", "symmetry_spatial_surface"]
                  if split == "confirmation" else [m for m in config["methods"] if m.startswith("symmetry_spatial_option_")])
    for condition in protocol["conditions"]:
        for candidate in candidates:
            for baseline in ["symmetry", "symmetry_robust95"]:
                for metric in ["hidden_chamfer_l1_mm", "volume_absolute_error_analytic_ml", "clean_observed_to_surface_mean_mm"]:
                    for profile in [None, *protocol["underside_warps"]]:
                        comparisons.append(paired_difference(rows, inputs, candidate, baseline, condition, metric, protocol, profile))
    twins = defaultdict(list)
    for case in inputs:
        twins[(case["family_id"], case["condition"])].append(case)
    input_pairs = prediction_pairs = identical_predictions = missing_predictions = 0
    for (_, condition), cases in twins.items():
        input_pairs += len(cases) == 2 and len({c["canonical_partial_sha256"] for c in cases}) == 1
        for method in config["methods"]:
            prediction_pairs += 1
            files = [path/c["object_id"]/condition/f"{method}.ply" for c in cases]
            if len(cases) != 2 or not all(p.exists() for p in files):
                missing_predictions += 1
            else:
                identical_predictions += len({sha256(p) for p in files}) == 1
    quality = []
    for case in inputs:
        if case["underside_warp"] != protocol["underside_warps"][0]:
            continue  # hidden twins have the same observations; count each scan once
        for method in candidates:
            parameters = path/case["object_id"]/case["condition"]/f"{method}_parameters.json"
            if not parameters.exists():
                continue
            fitted = json.loads(parameters.read_text())
            suspects = set(fitted["suspect_point_indices"])
            injected = set(case["injected_spike_indices_eval_only"])
            quality.append({"family_id": case["family_id"], "condition": case["condition"], "method": method,
                            "flagged_points": len(suspects), "injected_spikes": len(injected),
                            "true_positive": len(suspects & injected), "false_positive": len(suspects-injected),
                            "missed_spikes": len(injected-suspects),
                            "label_scope": "known injected spikes only; Gaussian noise has no binary spike labels"})
    expected = protocol["splits"][split]["families"]*len(protocol["underside_warps"])*len(protocol["conditions"])*len(config["methods"])
    failed = sum(r["status"] != "ok" for r in rows)
    complete = len(rows) == expected and failed == 0
    return {"protocol_id": protocol["protocol_id"], "split": split,
            "scope": "confirmation within a synthetic generator only" if split == "confirmation" else "candidate selection on synthetic development only",
            "results_sha256": sha256(path/"results.json"), "inputs_sha256": sha256(path/"inputs.json"),
            "config_sha256": sha256(path/"config.json"), "independent_families": protocol["splits"][split]["families"],
            "shape_objects": len({r["object_id"] for r in rows}), "expected_predictions": expected,
            "predictions": len(rows), "failed_predictions": failed, "complete": complete,
            "confirmation_criteria": criteria,
            "predefined_confirmation_supported": (bool(complete and all(c["passed"] for c in criteria)) if criteria else None),
            "identifiability": {"expected_twin_input_pairs": len(twins), "identical_twin_input_pairs": int(input_pairs),
                                "expected_twin_prediction_pairs": prediction_pairs, "identical_twin_prediction_pairs": int(identical_predictions),
                                "missing_twin_prediction_pairs": missing_predictions},
            "group_summary": summary, "paired_comparisons": comparisons, "confidence_detection_eval_only": quality}


def save_spatial_analysis(run_path, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report = analyze_spatial_run(run_path)
    write_json(output/"analysis.json", report)
    flat = []
    for row in report["group_summary"]:
        record = {k: v for k, v in row.items() if not isinstance(v, dict)}
        for metric, value in row.items():
            if isinstance(value, dict):
                for key, data in value.items():
                    record[f"{metric}_{key}"] = data
        flat.append(record)
    write_csv(output/"group_summary.csv", flat)
    write_csv(output/"paired_comparisons.csv", [{k: v for k, v in row.items() if k != "per_object_differences"}
                                              for row in report["paired_comparisons"]])
    write_csv(output/"confidence_detection.csv", report["confidence_detection_eval_only"])
    return report
