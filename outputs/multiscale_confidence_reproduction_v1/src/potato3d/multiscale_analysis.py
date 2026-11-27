"""Prespecified confirmation including localized genuine-feature guardrails."""
from collections import defaultdict
import json
from pathlib import Path

from .io import sha256, write_json
from .pipeline import write_csv
from .spatial_analysis import criterion_passes
from .study_analysis import METRICS, cluster_estimate, paired_difference


def analyze(path):
    path = Path(path)
    config = json.loads((path/"config.json").read_text())
    rows = json.loads((path/"results.json").read_text())
    inputs = json.loads((path/"inputs.json").read_text())
    protocol, split = config["multiscale_protocol"], config["split"]
    meta = {(m["object_id"], m["condition"]): m for m in inputs}
    metrics = [*METRICS, "feature_observed_to_surface_mean_mm", "feature_observed_to_surface_p95_mm", "confidence_flagged_fraction"]
    summaries = []
    for condition in protocol["conditions"]:
        for method in config["methods"]:
            for profile in [None, 0., 1.8]:
                selected = [r for r in rows if r["condition"] == condition and r["method"] == method and
                            (profile is None or meta[(r["object_id"], condition)]["underside_warp"] == profile)]
                result = {"condition": condition, "method": method, "profile": "combined" if profile is None else profile,
                          "attempted_shapes": len(selected), "failed_shapes": sum(r["status"] != "ok" for r in selected)}
                for metric in metrics:
                    values = defaultdict(list)
                    for row in selected:
                        if row["status"] == "ok" and row.get(metric) is not None:
                            values[meta[(row["object_id"], condition)]["family_id"]].append(row[metric])
                    result[metric] = cluster_estimate(values, protocol["bootstrap_replicates"], protocol["bootstrap_seed"])
                summaries.append(result)
    criteria = []
    if split == "confirmation":
        for criterion in protocol["confirmation_criteria"]:
            result = paired_difference(rows, inputs, "symmetry_multiscale", criterion["baseline"],
                                       criterion["condition"], criterion["metric"], protocol)
            result.update(criterion=criterion, passed=criterion_passes(result, criterion, protocol["splits"][split]["families"]))
            criteria.append(result)
    candidates = (["symmetry_multiscale", "symmetry_annular"] if split == "confirmation" else
                  [m for m in config["methods"] if m.startswith("symmetry_multiscale_option_")])
    comparisons = []
    for condition in protocol["conditions"]:
        endpoint_metrics = ["hidden_chamfer_l1_mm", "volume_absolute_error_analytic_ml", "clean_observed_to_surface_mean_mm"]
        if condition.startswith("genuine_"):
            endpoint_metrics.append("feature_observed_to_surface_mean_mm")
        for candidate in candidates:
            for baseline in ["symmetry_spatial", "symmetry_robust95", "symmetry"]:
                for metric in endpoint_metrics:
                    for profile in [None, 0., 1.8]:
                        comparisons.append(paired_difference(rows, inputs, candidate, baseline, condition, metric, protocol, profile))
    quality = []
    for case in inputs:
        for method in ["symmetry_spatial", *candidates]:
            parameter_path = path/case["object_id"]/case["condition"]/f"{method}_parameters.json"
            if not parameter_path.exists():
                continue
            fitted = json.loads(parameter_path.read_text())
            flagged = set(fitted["suspect_point_indices"])
            spikes = set(case["injected_spike_indices_eval_only"])
            feature = set(case["feature_observation_indices_eval_only"])
            quality.append({"object_id": case["object_id"], "family_id": case["family_id"], "condition": case["condition"],
                            "method": method, "flagged_points": len(flagged), "injected_spikes": len(spikes),
                            "true_positive_spikes": len(flagged & spikes), "missed_spikes": len(spikes-flagged),
                            "non_spike_flags": len(flagged-spikes), "feature_core_points": len(feature),
                            "feature_core_flagged": len(feature & flagged), "label_role": "evaluation-only injection and genuine-feature labels"})
    expected = protocol["splits"][split]["families"]*len(protocol["conditions"])*len(config["methods"])
    failed = sum(r["status"] != "ok" for r in rows)
    complete = len(rows) == expected and not failed
    return {"protocol_id": protocol["protocol_id"], "split": split, "scope": "synthetic confirmation only; genuine features are different clean geometries",
            "results_sha256": sha256(path/"results.json"), "inputs_sha256": sha256(path/"inputs.json"),
            "config_sha256": sha256(path/"config.json"), "independent_families": protocol["splits"][split]["families"],
            "shape_objects": len({m["object_id"] for m in inputs}), "condition_instances": len(inputs),
            "expected_predictions": expected, "predictions": len(rows), "failed_predictions": failed, "complete": bool(complete),
            "confirmation_criteria": criteria,
            "predefined_confirmation_supported": bool(complete and all(c["passed"] for c in criteria)) if criteria else None,
            "hidden_profile_note": "one alternating hidden profile per family; per-profile confidence intervals withheld below 10 families",
            "group_summary": summaries, "paired_comparisons": comparisons, "confidence_detection_eval_only": quality}


def save_analysis(path, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report = analyze(path)
    write_json(output/"analysis.json", report)
    flat = []
    for row in report["group_summary"]:
        record = {k: v for k, v in row.items() if not isinstance(v, dict)}
        for metric, value in row.items():
            if isinstance(value, dict):
                record.update({f"{metric}_{key}": data for key, data in value.items()})
        flat.append(record)
    write_csv(output/"group_summary.csv", flat)
    write_csv(output/"paired_comparisons.csv", [{k: v for k, v in r.items() if k != "per_object_differences"} for r in report["paired_comparisons"]])
    write_csv(output/"confidence_detection.csv", report["confidence_detection_eval_only"])
    return report
