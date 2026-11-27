"""Deterministic experiment runner with provenance and honest failure accounting."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import time

import numpy as np
import trimesh
import yaml

from .completion import METHODS
from .geometry import check_scale_mm, mesh_quality, sample_surface, subset
from .io import discover_demo, load_demo_pair, sha256, write_json
from .metrics import evaluate, surface_distances
from .synthetic import AnalyticShape
from .visualize import comparison


@dataclass
class Sample:
    object_id: str
    frame_id: str
    condition: str
    points: np.ndarray
    reference: trimesh.Trimesh
    metadata: dict
    shape: AnalyticShape | None = None
    clean_observations: np.ndarray | None = None


def load_config(path: Path):
    config = yaml.safe_load(Path(path).read_text())
    required = {"seed", "methods", "surface_samples", "thresholds_mm", "max_fit_points",
                "ellipsoid_subdivisions", "synthetic_points", "synthetic_noise_mm", "bootstrap_replicates"}
    if set(config) != required:
        raise ValueError(f"Config keys differ: {set(config) ^ required}")
    if not config["methods"] or set(config["methods"])-set(METHODS):
        raise ValueError("Invalid baseline methods")
    if len(set(config["methods"])) != len(config["methods"]):
        raise ValueError("Duplicate baseline method")
    for key in ["surface_samples", "max_fit_points", "synthetic_points", "bootstrap_replicates"]:
        if not isinstance(config[key], int) or config[key] < (4 if key != "bootstrap_replicates" else 1):
            raise ValueError(f"Invalid positive integer for {key}")
    if 5.0 not in config["thresholds_mm"] or any(t <= 0 for t in config["thresholds_mm"]):
        raise ValueError("Positive metric thresholds must include 5 mm")
    if config["synthetic_noise_mm"] < 0:
        raise ValueError("Noise must be nonnegative")
    if not isinstance(config["ellipsoid_subdivisions"], int) or not 1 <= config["ellipsoid_subdivisions"] <= 5:
        raise ValueError("Use ellipsoid subdivisions in [1,5] for this CPU prototype")
    return config


def synthetic_samples(config, study=False):
    shapes = [("ellipsoid", AnalyticShape()), ("waisted", AnalyticShape(waist=.55))] if study else [("ellipsoid", AnalyticShape())]
    regimes = [("clean", {}), ("depth_jitter_2mm", {"noise_mm": 2.}),
               ("outliers_2percent", {"outlier_fraction": .02}), ("depth_gap", {"gap": True})] if study else [("clean", {"noise_mm": config["synthetic_noise_mm"]})]
    for shape_index, (name, shape) in enumerate(shapes):
        for condition, noise in regimes:
            # Same object/seed: corruptions are matched, not independent objects.
            points = shape.partial(config["synthetic_points"], config["seed"]+shape_index, **noise)
            yield Sample(name, "000", condition, points, shape.mesh(),
                         {"split": "synthetic_development_only", "axes_mm": shape.axes,
                          "waist": shape.waist, "yaw_rad": shape.yaw,
                          "visibility": "orthographic top root; uniform unit-disk samples followed by shape warp",
                          "corruption": noise, "belt_depth_mm": None}, shape)


def inspect_demo(root: Path, belt_depth_mm: float):
    records = discover_demo(root)
    audit = []
    for record in records:
        points, reference, meta = load_demo_pair(root, record, belt_depth_mm)
        obs = subset(points, 1500, 527)
        distances = surface_distances(obs, reference)
        meta["alignment_check"] = {"points": len(obs), "seed": 527,
                                   "mean_point_to_reference_surface_mm": distances.mean(),
                                   "p95_point_to_reference_surface_mm": np.quantile(distances, .95)}
        warnings = []
        if not meta["reference_quality"]["volume_valid"]:
            warnings.append("Open/invalid reference: direct mesh-volume target is unavailable; no hole filling")
        if np.max(reference.extents) > 1.3*max(record["measured_dimensions_mm"]):
            warnings.append("Geometry extent exceeds largest listed physical dimension by >30%; metadata/scale needs review")
        if meta["alignment_check"]["p95_point_to_reference_surface_mm"] > 5:
            warnings.append("Registration/depth discrepancy exceeds 5 mm at the 95th percentile")
        meta["warnings"] = warnings
        audit.append(meta)
    return {"dataset": "CoRe++ public demo", "usage": "smoke only; not held-out research evidence",
            "unique_objects": len(records), "available_partial_frames": sum(r["available_frames"] for r in records),
            "registered_frames": len(records), "unit": "input m; canonical mm",
            "belt_depth_mm": belt_depth_mm, "objects": audit}


def environment():
    packages = {name: importlib.metadata.version(name) for name in
                ["potato3d", "numpy", "scipy", "trimesh", "rtree", "matplotlib", "plotly", "PyYAML"]}
    source_root = Path(__file__).resolve().parent
    source_hashes = {str(p.relative_to(source_root)): sha256(p) for p in sorted(source_root.rglob("*.py"))}
    return {"python": platform.python_version(), "platform": platform.platform(),
            "architecture": platform.machine(), "processor": platform.processor(),
            "cpu_model_declared": os.environ.get("POTATO3D_CPU_MODEL"),
            "thread_environment": {k: os.environ.get(k) for k in
                                   ["OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"]},
            "device": "CPU only; no neural framework/CUDA dependency", "packages": packages,
            "source_sha256": source_hashes,
            "lock_sha256": sha256(Path("uv.lock")) if Path("uv.lock").exists() else None}


def summarize(rows, bootstrap_replicates=1000, seed=527):
    summaries = []
    groups = sorted({(r["method"], r["condition"]) for r in rows})
    for method, condition in groups:
        selected = [r for r in rows if r["method"] == method and r["condition"] == condition]
        good = [r for r in selected if r["status"] == "ok"]
        result = {"method": method, "condition": condition,
                  "attempted_frames": len(selected), "successful_frames": len(good),
                  "failed_frames": len(selected)-len(good),
                  "attempted_objects": len({r["object_id"] for r in selected}),
                  "successful_objects": len({r["object_id"] for r in good})}
        metrics = ["chamfer_l1_mm", "fscore_5mm", "observed_to_surface_mean_mm", "fit_seconds",
                   "hidden_chamfer_l1_mm", "visible_chamfer_l1_mm",
                   "volume_absolute_error_mesh_ml", "volume_absolute_error_analytic_ml",
                   "volume_absolute_error_physical_ml", "volume_absolute_error_reported_sfm_ml"]
        for metric in metrics:
            objects = sorted({r["object_id"] for r in good if r.get(metric) is not None})
            values = np.array([np.mean([r[metric] for r in good if r["object_id"] == pid and r.get(metric) is not None])
                               for pid in objects])
            if not len(values):
                continue
            object_cluster = {}
            for pid in objects:
                labels = {r.get("analysis_cluster_id", pid) for r in good if r["object_id"] == pid}
                if len(labels) != 1:
                    raise ValueError(f"Object {pid} crosses analysis clusters")
                object_cluster[pid] = next(iter(labels))
            clusters = sorted(set(object_cluster.values()))
            cluster_values = np.array([np.mean([v for pid, v in zip(objects, values) if object_cluster[pid] == group])
                                       for group in clusters])
            result[f"mean_{metric}"] = float(cluster_values.mean())
            result[f"objects_with_{metric}"] = len(values)
            result[f"independent_clusters_with_{metric}"] = len(clusters)
            result[f"ci95_{metric}"] = None
            if len(clusters) >= 10:
                rng = np.random.default_rng(seed)
                boot = rng.choice(cluster_values, (bootstrap_replicates, len(clusters)), replace=True).mean(axis=1)
                result[f"ci95_{metric}"] = np.quantile(boot, [.025, .975]).tolist()
        for target in ["mesh", "analytic", "physical", "reported_sfm"]:
            key = f"volume_signed_error_{target}_ml"
            objects = sorted({r["object_id"] for r in good if r.get(key) is not None})
            if objects:
                mse = [np.mean([r[key]**2 for r in good if r["object_id"] == pid and r.get(key) is not None]) for pid in objects]
                result[f"volume_rmse_{target}_ml"] = float(np.sqrt(np.mean(mse)))
        result["ci_note"] = "Equal independent clusters (object IDs by default, explicit families when supplied); bootstrap at >=10 clusters"
        summaries.append(result)
    return summaries


def write_csv(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in row.items()})


def run(samples, config, output: Path, visualization=True):
    output = Path(output)
    # Never overwrite an experiment or mix old predictions with a changed config.
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    write_json(output/"config.json", config)
    write_json(output/"environment.json", environment())
    rows, inputs = [], []
    for sample in samples:
        sample_started = time.perf_counter()
        sample_dir = output/sample.object_id/sample.condition
        sample_dir.mkdir(parents=True)
        check_scale_mm(sample.points)
        fit_points = subset(sample.points, config["max_fit_points"], config["seed"])
        trimesh.points.PointCloud(sample.points).export(sample_dir/"partial.ply")
        sample.reference.export(sample_dir/"reference.ply")
        meta = {"object_id": sample.object_id, "frame_id": sample.frame_id,
                "condition": sample.condition, "input_points": len(sample.points),
                "fit_points": len(fit_points), **sample.metadata,
                "canonical_partial_sha256": sha256(sample_dir/"partial.ply"),
                "canonical_reference_sha256": sha256(sample_dir/"reference.ply")}
        inputs.append(meta)
        if sample.clean_observations is not None:
            trimesh.points.PointCloud(sample.clean_observations).export(sample_dir/"clean_observations_eval_only.ply")
            meta["clean_observations_eval_only_sha256"] = sha256(sample_dir/"clean_observations_eval_only.ply")
        write_json(output/"inputs.json", inputs)
        ref_samples, _ = sample_surface(sample.reference, config["surface_samples"], config["seed"]+17)
        predictions = {}
        for method in config["methods"]:
            row = {"object_id": sample.object_id, "frame_id": sample.frame_id,
                   "condition": sample.condition, "method": method,
                   "data_scope": sample.metadata["split"]}
            if "family_id" in sample.metadata:
                row["analysis_cluster_id"] = sample.metadata["family_id"]
            try:
                begin = time.perf_counter()
                options = config.get("method_options", {}).get(method, {})
                mesh, parameters = METHODS[method](fit_points, subdivisions=config["ellipsoid_subdivisions"], **options)
                row["fit_seconds"] = time.perf_counter()-begin
                if "flagged_fraction" in parameters:
                    row["confidence_flagged_fraction"] = parameters["flagged_fraction"]
                    row["confidence_fallback_points"] = parameters["unsupported_neighborhoods"]
                if not mesh_quality(mesh)["volume_valid"]:
                    raise ValueError("Baseline produced an invalid/non-watertight/orientation-failed closed mesh")
                mesh.export(sample_dir/f"{method}.ply")
                write_json(sample_dir/f"{method}_parameters.json", parameters)
                begin = time.perf_counter()
                row.update(evaluate(mesh, sample.reference, sample.points, config, ref_samples,
                                    visible_partition=sample.shape.visible if sample.shape else None,
                                    analytic_volume_ml=sample.shape.volume_ml if sample.shape else None,
                                    physical_volume_ml=sample.metadata.get("physical_volume_ml"),
                                    reported_sfm_volume_ml=sample.metadata.get("reported_sfm_volume_ml")))
                if sample.clean_observations is not None:
                    clean_error = surface_distances(sample.clean_observations, mesh)
                    row["clean_observed_to_surface_mean_mm"] = float(clean_error.mean())
                    row["clean_observed_to_surface_p95_mm"] = float(np.quantile(clean_error, .95))
                    feature_indices = sample.metadata.get("feature_observation_indices_eval_only", [])
                    if feature_indices:
                        feature_error = clean_error[np.asarray(feature_indices, dtype=int)]
                        row["feature_observed_to_surface_mean_mm"] = float(feature_error.mean())
                        row["feature_observed_to_surface_p95_mm"] = float(np.quantile(feature_error, .95))
                        row["feature_metric_points"] = len(feature_error)
                    true_belt = sample.metadata.get("true_belt_in_input_frame_mm", 0.)
                    row["prediction_below_true_belt_mm"] = float(max(0., true_belt-mesh.bounds[0, 2]))
                    if "height_mm" in parameters:
                        row["height_absolute_error_mm"] = abs(parameters["height_mm"]-sample.metadata["true_object_height_mm"])
                row["evaluation_seconds"] = time.perf_counter()-begin
                row["status"] = "ok"
                predictions[method] = mesh
            except (ValueError, RuntimeError) as exc:
                row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            rows.append(row)
            print(f"{sample.object_id}/{sample.condition}/{method}: {row['status']}", flush=True)
            write_json(output/"results.json", rows)
            write_csv(output/"results.csv", rows)
        if visualization:
            comparison(sample.points, predictions, sample.reference, sample_dir,
                       f"{sample.object_id} | {sample.condition} | {sample.metadata['split']}", config["seed"])
        meta["sample_total_seconds_including_visualization"] = time.perf_counter()-sample_started
    write_json(output/"inputs.json", inputs)
    summary = summarize(rows, config["bootstrap_replicates"], config["seed"])
    write_json(output/"summary.json", summary)
    write_csv(output/"summary.csv", summary)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    write_json(output/"run.json", {"finished_utc": datetime.now(timezone.utc).isoformat(),
                                 "total_seconds": time.perf_counter()-started,
                                 "unique_objects": len({r["object_id"] for r in rows}),
                                 "unique_frames": len({(r["object_id"], r["frame_id"]) for r in rows}),
                                 "condition_instances": len(inputs), "failed_predictions": sum(r["status"] != "ok" for r in rows),
                                 "process_peak_rss_mib": rss/(1024**2 if platform.system() == "Darwin" else 1024),
                                 "timing_boundary": "total includes input loading/generation, exports, metrics, visualization; excludes process startup/imports/downloads",
                                 "fit_timing_boundary": "completion and its mesh construction only; shared loading/subsampling excluded",
                                 "memory_boundary": "process lifetime high-water RSS, includes imports and visualization; not per-method peak"})
    return rows
