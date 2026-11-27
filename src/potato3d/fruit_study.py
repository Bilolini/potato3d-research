"""Sealed real-data runner with observation/reference separation and object holdout."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import time

import numpy as np
import plotly.graph_objects as go
import trimesh

from .bonn import load_observations, load_reference, validate_manifest
from .fruit_completion import TemplateCompleter, build_prior, ellipsoid_mesh, fit_ellipsoid, load_prior
from .geometry import mesh_quality, sample_surface, subset
from .io import sha256, write_json
from .metrics import point_cloud_metrics, surface_distances
from .pipeline import environment, write_csv


CONFIG = Path("configs/bonn_real_v1.json")
MANIFEST = Path("data/bonn_real_v1_manifest.json")
SEAL = Path("docs/bonn_real_v1_seal.json")


def fingerprint():
    paths = [*Path("src/potato3d").rglob("*.py"), *Path("scripts").glob("*.py"),
             *Path("tests").glob("*.py"), CONFIG, MANIFEST, Path("uv.lock"), Path("pyproject.toml"),
             Path("docs/bonn_real_v1_protocol.md")]
    return {str(p): sha256(p) for p in sorted(paths)}


def verify_seal():
    seal = json.loads(SEAL.read_text())
    if seal["fingerprint"] != fingerprint():
        raise ValueError("Sealed source/config/protocol changed; do not rescore with this protocol ID")
    return sha256(SEAL)


def prior_hashes(folder):
    return {str(p.relative_to(folder)): sha256(p) for p in sorted(Path(folder).glob("*")) if p.is_file()}


def verify_selection(selection_path, prior_folder=None):
    selection = json.loads(Path(selection_path).read_text())
    if selection["seal_sha256"] != verify_seal():
        raise ValueError("Selection belongs to a different seal")
    if prior_folder is not None and selection["prior_hashes"] != prior_hashes(prior_folder):
        raise ValueError("Training prior differs from development selection")
    if selection["ellipsoid_strength"] not in json.loads(CONFIG.read_text())["ellipsoid_strengths"]:
        raise ValueError("Selection has an unregistered ellipsoid strength")
    return selection


def train(data_root, output):
    verify_seal()
    config = json.loads(CONFIG.read_text())
    manifest = validate_manifest(json.loads(MANIFEST.read_text()))
    return build_prior(data_root, [o for o in manifest["objects"] if o["role"] == "train"], output,
                       config["seed"], config["template_samples"])


def evaluate_cloud(prediction, reference_points, raw, used, config, seed):
    predicted, _ = sample_surface(prediction, config["surface_samples"], seed+11)
    metrics = point_cloud_metrics(predicted, reference_points, config["thresholds_mm"])
    for label, points in [("raw", raw), ("used", used)]:
        chosen = subset(points, config["max_fidelity_points"], seed+19)
        distance = surface_distances(chosen, prediction)
        metrics.update({f"{label}_to_surface_mean_mm": float(distance.mean()),
                        f"{label}_to_surface_p95_mm": float(np.quantile(distance, .95)),
                        f"{label}_metric_points": len(chosen)})
    metrics.update({f"prediction_{key}": value for key, value in mesh_quality(prediction).items()})
    metrics.update(reference_points=len(reference_points), prediction_samples=len(predicted),
                   reference_mesh_volume_ml=None, physical_target_volume_ml=None,
                   volume_relative_error_mesh=None, volume_relative_error_physical=None,
                   region_partition="unavailable: no verified visibility labels",
                   reference_metric="all native laser points; density weighted; unsquared mm")
    return metrics


def viewer(folder, raw, reference, predictions, seed):
    figure = go.Figure()
    for name, points, color in [("raw observation", raw, "orange"), ("laser reference", reference, "black")]:
        p = subset(points, 4000, seed)
        figure.add_trace(go.Scatter3d(x=p[:, 0], y=p[:, 1], z=p[:, 2], mode="markers", name=name,
                                      marker={"size": 1.5, "color": color, "opacity": .6}))
    for i, (name, mesh) in enumerate(predictions.items()):
        v, f = mesh.vertices, mesh.faces
        figure.add_trace(go.Mesh3d(x=v[:, 0], y=v[:, 1], z=v[:, 2], i=f[:, 0], j=f[:, 1], k=f[:, 2],
                                  opacity=.35, name=name, showlegend=True, visible="legendonly"))
    figure.update_layout(title="Canonical fruit frame (mm); toggle predictions in legend",
                         scene={"aspectmode": "data", "xaxis_title": "x (mm)", "yaxis_title": "y (mm)", "zaxis_title": "z (mm)"})
    figure.write_html(folder/"comparison.html", include_plotlyjs=True)


def run(data_root, prior_folder, split, output, selection_path=None):
    seal_sha = verify_seal()
    config = json.loads(CONFIG.read_text())
    manifest = validate_manifest(json.loads(MANIFEST.read_text()))
    if split not in {"development", "holdout"}:
        raise ValueError("Invalid evaluation split")
    selection = verify_selection(selection_path, prior_folder) if split == "holdout" else None
    prior = load_prior(prior_folder)
    if prior["training_ids"] != manifest["roles"]["train"]:
        raise ValueError("Unexpected prior training IDs")
    methods = {"population": None, "template": None}
    for strength in (config["ellipsoid_strengths"] if selection is None else [selection["ellipsoid_strength"]]):
        methods[f"ellipsoid_{strength:g}"] = strength
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output/"config.json", config)
    env = environment()
    env["packages"]["Pillow"] = importlib.metadata.version("Pillow")
    write_json(output/"environment.json", env)
    provenance = {"protocol_id": config["protocol_id"], "split": split, "seal_sha256": seal_sha,
                  "manifest_sha256": sha256(MANIFEST), "prior_hashes": prior_hashes(prior_folder),
                  "object_ids": manifest["roles"][split], "methods": list(methods),
                  "selection_sha256": sha256(selection_path) if selection_path else None}
    write_json(output/"provenance.json", provenance)
    completer = TemplateCompleter(prior_folder, prior)
    rows, inputs = [], []
    started = time.perf_counter()
    with (output/"events.jsonl").open("w") as events:
        def event(kind, pid, **extra):
            events.write(json.dumps({"event": kind, "object_id": pid, **extra})+"\n"); events.flush()
        for record in [o for o in manifest["objects"] if o["role"] == split]:
            pid = record["object_id"]
            seed = config["seed"]+int(hashlib.sha256(pid.encode()).hexdigest()[:7], 16)
            folder = output/pid; folder.mkdir()
            pending, predictions = [], {}
            try:
                conditions, audit = load_observations(data_root, record, config["component_jump_mm"], config["component_minimum_points"])
                inputs.append(audit)
                event("observations_loaded", pid)
                for condition, used in conditions.items():
                    condition_folder = folder/condition; condition_folder.mkdir()
                    trimesh.points.PointCloud(used).export(condition_folder/"input_mm.ply")
                    fit = subset(used, config["max_fit_points"], seed+3)
                    for method, strength in methods.items():
                        row = {"object_id": pid, "frame_id": record["frame_id"], "scenario": record["scenario"],
                               "condition": condition, "method": method, "split": split,
                               "status": "failed", "raw_points": len(conditions["raw_valid"]), "used_points": len(used),
                               "fit_points": len(fit), "retained_fraction": len(used)/len(conditions["raw_valid"])}
                        fit_started = time.perf_counter()
                        try:
                            if method == "population":
                                mesh = ellipsoid_mesh(prior["center_mm"], prior["radii_mm"], config["ellipsoid_subdivisions"])
                                parameters = {"training_ids": prior["training_ids"], "center_mm": prior["center_mm"], "radii_mm": prior["radii_mm"]}
                            elif method == "template":
                                mesh, parameters = completer.complete(fit, config["template_strength"], config["template_iterations"])
                            else:
                                mesh, parameters = fit_ellipsoid(fit, prior, strength, config["ellipsoid_subdivisions"])
                            row["fit_seconds"] = time.perf_counter()-fit_started
                            if not mesh_quality(mesh)["volume_valid"]:
                                raise ValueError("Prediction mesh invalid")
                            mesh_path = condition_folder/(method+".ply"); mesh.export(mesh_path)
                            write_json(condition_folder/(method+"_parameters.json"), parameters)
                            row["prediction_sha256"] = sha256(mesh_path)
                            row["optimizer_success"] = parameters.get("optimizer_success")
                            event("prediction_exported", pid, condition=condition, method=method, sha256=row["prediction_sha256"])
                            predictions[condition+"/"+method] = mesh
                            pending.append((row, mesh, conditions["raw_valid"], used))
                        except Exception as error:
                            row["error"] = f"{type(error).__name__}: {error}"
                            rows.append(row)
                            event("prediction_failed", pid, condition=condition, method=method, error=row["error"])
            except Exception as error:
                # Record every planned prediction when observation loading fails.
                for condition in ["raw_valid", "depth_component"]:
                    for method in methods:
                        rows.append({"object_id": pid, "frame_id": record["frame_id"], "scenario": record["scenario"],
                                     "condition": condition, "method": method, "split": split, "status": "failed",
                                     "error": f"{type(error).__name__}: {error}"})
                event("observation_failure", pid, error=str(error))
            # All prediction attempts for this fruit finish before opening its laser reference.
            event("reference_loading", pid)
            try:
                reference = load_reference(data_root, record)
                trimesh.points.PointCloud(reference).export(folder/"reference_mm.ply")
                for row, mesh, raw, used in pending:
                    try:
                        row.update(evaluate_cloud(mesh, reference, raw, used, config, seed))
                        row["status"] = "ok"
                    except Exception as error:
                        row["error"] = f"{type(error).__name__}: {error}"
                    rows.append(row)
                if pending:
                    viewer(folder, pending[0][2], reference, predictions, seed)
            except Exception as error:
                for row, *_ in pending:
                    row["error"] = f"Reference: {type(error).__name__}: {error}"
                    rows.append(row)
            write_json(output/"results.json", rows)
            write_json(output/"inputs.json", inputs)
            print(split, pid, f"{sum(r['status']=='ok' for r in rows)}/{len(rows)} valid predictions", flush=True)
    write_csv(output/"results.csv", rows)
    expected = len(manifest["roles"][split])*2*len(methods)
    write_json(output/"run.json", {**provenance, "expected_predictions": expected,
                                  "attempted_predictions": len(rows), "successful_predictions": sum(r["status"] == "ok" for r in rows),
                                  "elapsed_seconds": time.perf_counter()-started, "complete": len(rows) == expected})
    return rows


def select(development, output):
    verify_seal()
    folder = Path(development)
    provenance = json.loads((folder/"provenance.json").read_text())
    manifest = json.loads(MANIFEST.read_text()); config = json.loads(CONFIG.read_text())
    if provenance["split"] != "development" or provenance["seal_sha256"] != sha256(SEAL):
        raise ValueError("Selection requires matching sealed development evidence")
    rows = json.loads((folder/"results.json").read_text())
    expected = {(pid, c, m) for pid in manifest["roles"]["development"] for c in ["raw_valid", "depth_component"]
                for m in provenance["methods"]}
    if len(rows) != len(expected) or {(r["object_id"], r["condition"], r["method"]) for r in rows} != expected:
        raise ValueError("Incomplete/duplicate development evidence")
    if any(r["status"] != "ok" for r in rows):
        raise ValueError("Development contains failures; no candidate selection")
    scores = {str(strength): float(np.mean([r["chamfer_l1_mm"] for r in rows if r["method"] == f"ellipsoid_{strength:g}"]))
              for strength in config["ellipsoid_strengths"]}
    chosen = min(config["ellipsoid_strengths"], key=lambda s: (scores[str(s)], -s))
    if Path(output).exists():
        raise FileExistsError(output)
    selection = {"protocol_id": config["protocol_id"], "seal_sha256": sha256(SEAL),
                 "prior_hashes": provenance["prior_hashes"], "development_results_sha256": sha256(folder/"results.json"),
                 "ellipsoid_strength": chosen, "candidate_mean_chamfer_mm": scores,
                 "rule": "minimum development object mean Chamfer averaged equally over both input conditions; exact ties favor stronger prior"}
    write_json(output, selection)
    return selection


def analyze(folder, output):
    folder = Path(folder); rows = json.loads((folder/"results.json").read_text())
    run_info = json.loads((folder/"run.json").read_text())
    config = json.loads((folder/"config.json").read_text())
    groups = []
    for condition, method in sorted({(r["condition"], r["method"]) for r in rows}):
        selected = [r for r in rows if r["condition"] == condition and r["method"] == method]
        good = [r for r in selected if r["status"] == "ok"]
        summary = {"condition": condition, "method": method, "attempted": len(selected), "successful": len(good)}
        for key in ["chamfer_l1_mm", "fscore_5mm", "raw_to_surface_mean_mm", "used_to_surface_mean_mm", "fit_seconds", "retained_fraction"]:
            summary["mean_"+key] = float(np.mean([r[key] for r in good])) if good else None
        summary["optimizer_nonconverged"] = sum(r.get("optimizer_success") is False for r in good)
        groups.append(summary)
    result = {"run": run_info, "summary": groups, "primary_checks": None,
              "interpretation": "Lab-only local holdout from public validation; not official hidden-test or potato generalization"}
    if run_info["split"] == "holdout":
        complete = run_info["complete"] and all(r["status"] == "ok" for r in rows)
        population = {r["object_id"]: r for r in rows if r["method"] == "population" and r["condition"] == "depth_component"}
        fitted = {r["object_id"]: r for r in rows if r["method"].startswith("ellipsoid_") and r["condition"] == "depth_component"}
        checks = {}
        for metric, direction in [("chamfer_l1_mm", "lower"), ("fscore_5mm", "higher")]:
            if not complete or set(population) != set(run_info["object_ids"]) or set(fitted) != set(population):
                checks[metric] = {"pass": False, "reason": "incomplete planned holdout; no successful-only inference"}
                continue
            ids = sorted(population)
            delta = np.array([fitted[pid][metric]-population[pid][metric] for pid in ids])
            rng = np.random.default_rng(config["seed"]+101)
            boot = rng.choice(delta, (config["bootstrap_replicates"], len(delta)), replace=True).mean(axis=1)
            ci = np.quantile(boot, [.025, .975])
            checks[metric] = {"mean_paired_delta": float(delta.mean()), "ci95_paired_delta": ci.tolist(),
                              "objects": len(delta), "pass": bool(ci[1] < 0 if direction == "lower" else ci[0] > 0)}
        result["primary_checks"] = checks
        result["full_primary_hypothesis_passed"] = all(c["pass"] for c in checks.values())
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    write_json(output, result)
    return result
