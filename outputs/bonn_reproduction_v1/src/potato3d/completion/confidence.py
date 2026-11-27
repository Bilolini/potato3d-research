"""Local robust height-field confidence; heuristic scores, not probabilities."""
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from ..geometry import validate_points
from .symmetry import complete as mirror


@dataclass
class DepthConfidence:
    trusted: np.ndarray
    predicted_height: np.ndarray
    residual: np.ndarray
    threshold: np.ndarray
    score: np.ndarray
    fallback: np.ndarray


def local_depth_confidence(points, neighbors=32, threshold_mm=3., robust_iterations=3,
                           sigma_multiplier=3., scale_floor_mm=.5):
    p = validate_points(points, minimum=8)
    if not isinstance(neighbors, int) or neighbors < 6:
        raise ValueError("At least six other neighbors required for a quadratic")
    if not isinstance(robust_iterations, int) or robust_iterations < 1:
        raise ValueError("Positive robust iteration count required")
    if not all(np.isfinite([threshold_mm, sigma_multiplier, scale_floor_mm])) or min(threshold_mm, sigma_multiplier, scale_floor_mm) <= 0:
        raise ValueError("Positive finite confidence scales required")
    k = min(neighbors, len(p)-1)
    _, indices = cKDTree(p[:, :2]).query(p[:, :2], k=k+1, workers=1)
    positions = np.broadcast_to(np.arange(k+1), indices.shape)
    # Remove self even with duplicate XY coordinates and distance ties.
    order = np.argsort(np.where(indices == np.arange(len(p))[:, None], k+1, positions), axis=1, kind="stable")
    indices = np.take_along_axis(indices, order[:, :k], axis=1)
    xy = p[indices, :2]-p[:, None, :2]
    radius = np.maximum(np.linalg.norm(xy, axis=2).max(axis=1), 1e-8)
    xy = xy/radius[:, None, None]
    x, y = xy[:, :, 0], xy[:, :, 1]
    design = np.stack([np.ones_like(x), x, y, x*x, x*y, y*y], axis=2)
    neighbor_z = p[indices, 2]
    center_z = np.median(neighbor_z, axis=1)
    target = neighbor_z-center_z[:, None]
    gram = np.einsum("nki,nkj->nij", design, design)
    eigenvalues = np.linalg.eigvalsh(gram)
    fallback = eigenvalues[:, 0] <= 1e-8*np.maximum(eigenvalues[:, -1], 1.)
    weights = np.ones_like(target)
    ridge = np.diag([0., 1e-6, 1e-6, 1e-6, 1e-6, 1e-6])
    coefficients = np.zeros((len(p), 6))
    scale = np.full(len(p), scale_floor_mm)
    for _ in range(robust_iterations):
        weighted = design*weights[:, :, None]
        matrix = np.einsum("nki,nkj->nij", weighted, design)+ridge
        rhs = np.einsum("nki,nk->ni", weighted, target)
        coefficients = np.linalg.solve(matrix, rhs[:, :, None])[:, :, 0]
        residual = target-np.einsum("nki,ni->nk", design, coefficients)
        residual_center = np.median(residual, axis=1)
        scale = np.maximum(1.4826*np.median(np.abs(residual-residual_center[:, None]), axis=1), scale_floor_mm)
        weights = 1/(1+(residual/(2.5*scale[:, None]))**2)
    predicted = center_z+coefficients[:, 0]
    predicted[fallback] = center_z[fallback]
    # Unsupported fits use their neighbor depth spread to avoid false certainty.
    scale[fallback] = np.maximum(1.4826*np.median(np.abs(neighbor_z[fallback]-center_z[fallback, None]), axis=1), scale_floor_mm)
    residual = p[:, 2]-predicted
    threshold = np.maximum(threshold_mm, sigma_multiplier*scale)
    trusted = residual <= threshold
    score = np.ones(len(p))
    score[~trusted] = 1/(1+(residual[~trusted]/threshold[~trusted])**2)
    if not np.isfinite(predicted).all():
        raise ValueError("Non-finite local height predictions")
    return DepthConfidence(trusted, predicted, residual, threshold, score, fallback)


def complete(points, intervention="full", neighbors=32, threshold_mm=3., robust_iterations=3,
             sigma_multiplier=3., scale_floor_mm=.5, **_):
    p = validate_points(points, minimum=8)
    if intervention not in ("full", "height", "surface"):
        raise ValueError("Unknown spatial-confidence intervention")
    confidence = local_depth_confidence(p, neighbors, threshold_mm, robust_iterations, sigma_multiplier, scale_floor_mm)
    if confidence.trusted.sum() < 8:
        raise ValueError("Too few reliable observations remain")
    trusted_height = float(p[confidence.trusted, 2].max())
    corrected = p.copy()
    suspect = ~confidence.trusted
    corrected[suspect, 2] = np.clip(confidence.predicted_height[suspect], 0., trusted_height)
    cap = p if intervention == "height" else corrected
    height = float(p[:, 2].max()) if intervention == "surface" else trusted_height
    mesh, parameters = mirror(cap, height_mm=height, clip_lower_to_belt=True)
    indices = np.flatnonzero(suspect)
    return mesh, {**parameters, "confidence_method": "leave-self-out local quadratic Cauchy IRLS; positive residual gate",
                  "confidence_is_calibrated_probability": False, "intervention": intervention,
                  "neighbors": neighbors, "threshold_mm": threshold_mm, "robust_iterations": robust_iterations,
                  "sigma_multiplier": sigma_multiplier, "scale_floor_mm": scale_floor_mm,
                  "ridge": 1e-6, "irls_scale_factor": 2.5,
                  "trusted_height_mm": trusted_height, "original_max_height_mm": float(p[:, 2].max()),
                  "flagged_points": len(indices), "flagged_fraction": float(suspect.mean()),
                  "unsupported_neighborhoods": int(confidence.fallback.sum()),
                  "threshold_p05_p50_p95_mm": np.quantile(confidence.threshold, [.05, .5, .95]).tolist(),
                  "suspect_point_indices": indices.tolist(),
                  "suspect_confidence_scores": confidence.score[suspect].tolist(),
                  "suspect_residuals_mm": confidence.residual[suspect].tolist(),
                  "suspect_repaired_height_mm": corrected[suspect, 2].tolist(),
                  "trusted_point_policy": "retain XYZ exactly; only suspect cap heights may be replaced",
                  "assumption": "same mirror prior and belt as baselines; spatial residual confidence does not recover hidden shape"}


def height_only(points, **kwargs):
    return complete(points, intervention="height", **kwargs)


def surface_only(points, **kwargs):
    return complete(points, intervention="surface", **kwargs)
