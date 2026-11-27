"""Unsquared distances in mm, volume in mL; no evaluation-time alignment."""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree
import trimesh

from .geometry import mesh_quality, sample_surface


def point_cloud_metrics(predicted, reference, thresholds_mm=(2., 5., 10.)) -> dict:
    p, r = np.asarray(predicted), np.asarray(reference)
    if not len(p) or not len(r) or not np.isfinite(p).all() or not np.isfinite(r).all():
        raise ValueError("Metric inputs must be nonempty and finite")
    pr = cKDTree(r).query(p, workers=1)[0]
    rp = cKDTree(p).query(r, workers=1)[0]
    result = {"chamfer_l1_mm": float((pr.mean()+rp.mean())/2),
              "pred_to_ref_mean_mm": float(pr.mean()), "ref_to_pred_mean_mm": float(rp.mean()),
              "symmetric_p95_mm": float(max(np.quantile(pr, .95), np.quantile(rp, .95)))}
    for threshold in thresholds_mm:
        if threshold <= 0:
            raise ValueError("Distance thresholds must be positive")
        precision, recall = float(np.mean(pr <= threshold)), float(np.mean(rp <= threshold))
        suffix = f"{threshold:g}mm"
        result.update({f"precision_{suffix}": precision, f"recall_{suffix}": recall,
                       f"fscore_{suffix}": 2*precision*recall/(precision+recall) if precision+recall else 0.})
    return result


def surface_distances(points, mesh, chunk_size=256):
    # Exact point-to-triangle distances via a CPU R-tree. Chunking limits candidate memory.
    p = np.asarray(points)
    if not len(p):
        raise ValueError("No observation points to evaluate")
    if np.any(mesh.area_faces <= 1e-10):
        # A query-only view avoids undefined triangle projections. Preserve the
        # released mesh, its topology audit and its unavailable volume target.
        mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces[mesh.area_faces > 1e-10], process=False)
    distances = np.concatenate([trimesh.proximity.closest_point(mesh, p[i:i+chunk_size])[1]
                                for i in range(0, len(p), chunk_size)])
    if not np.isfinite(distances).all():
        raise ValueError("Non-finite point-to-surface metric")
    return distances


def evaluate(prediction, reference, observations, config, reference_samples=None,
             visible_partition=None, analytic_volume_ml=None, physical_volume_ml=None,
             reported_sfm_volume_ml=None):
    seed = config["seed"]
    pred_samples, _ = sample_surface(prediction, config["surface_samples"], seed+11)
    ref_samples = (reference_samples if reference_samples is not None else
                   sample_surface(reference, config["surface_samples"], seed+17)[0])
    result = point_cloud_metrics(pred_samples, ref_samples, config["thresholds_mm"])
    obs_error = surface_distances(observations, prediction)
    result.update({"observed_to_surface_mean_mm": float(obs_error.mean()),
                   "observed_to_surface_p95_mm": float(np.quantile(obs_error, .95)),
                   "observed_metric_points": len(observations),
                   "observation_confidence": "all supplied points; no confidence labels assumed"})
    pq, rq = mesh_quality(prediction), mesh_quality(reference)
    result.update({f"prediction_{k}": v for k, v in pq.items()})
    result["reference_mesh_volume_ml"] = rq["volume_ml"]
    result["reference_watertight"] = rq["watertight"]
    for label, target in [("mesh", rq["volume_ml"]), ("analytic", analytic_volume_ml),
                          ("physical", physical_volume_ml), ("reported_sfm", reported_sfm_volume_ml)]:
        valid = target is not None and pq["volume_ml"] is not None and target > 0
        result[f"{label}_target_volume_ml"] = target
        result[f"volume_signed_error_{label}_ml"] = pq["volume_ml"]-target if valid else None
        result[f"volume_absolute_error_{label}_ml"] = abs(pq["volume_ml"]-target) if valid else None
        result[f"volume_relative_error_{label}"] = abs(pq["volume_ml"]-target)/target if valid else None
    result["region_partition"] = "unavailable: no verified visibility labels"
    if visible_partition is not None:
        pv, rv = visible_partition(pred_samples), visible_partition(ref_samples)
        for label, a, b in [("visible", pred_samples[pv], ref_samples[rv]),
                            ("hidden", pred_samples[~pv], ref_samples[~rv])]:
            if len(a) and len(b):
                region = point_cloud_metrics(a, b, config["thresholds_mm"])
                result[f"{label}_chamfer_l1_mm"] = region["chamfer_l1_mm"]
                result[f"{label}_fscore_5mm"] = region.get("fscore_5mm")
        result["region_partition"] = "analytic orthographic top visibility; evaluation only"
    return result
