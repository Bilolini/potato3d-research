"""Annular robust support with an explicit abrupt-boundary gate."""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from ..geometry import validate_points
from .confidence import DepthConfidence, local_depth_confidence
from .symmetry import complete as mirror


def other_neighbors(tree, xy, count):
    k = min(count, len(xy)-1)
    distances, indices = tree.query(xy, k=k+1, workers=1)
    positions = np.broadcast_to(np.arange(k+1), indices.shape)
    order = np.argsort(np.where(indices == np.arange(len(xy))[:, None], k+1, positions), axis=1, kind="stable")[:, :k]
    return np.take_along_axis(distances, order, axis=1), np.take_along_axis(indices, order, axis=1)


def annular_depth_confidence(points, inner_neighbors=32, outer_neighbors=160, threshold_mm=3.,
                             robust_iterations=3, sigma_multiplier=3., scale_floor_mm=.5):
    p = validate_points(points, minimum=8)
    if not isinstance(inner_neighbors, int) or not isinstance(outer_neighbors, int) or inner_neighbors < 0 or outer_neighbors-inner_neighbors < 6:
        raise ValueError("Annulus must contain at least six other neighbors")
    if len(p)-1-inner_neighbors < 6:
        raise ValueError("Too few observations outside the inner neighborhood")
    if not isinstance(robust_iterations, int) or robust_iterations < 1:
        raise ValueError("Positive IRLS iteration count required")
    if not all(np.isfinite([threshold_mm, sigma_multiplier, scale_floor_mm])) or min(threshold_mm, sigma_multiplier, scale_floor_mm) <= 0:
        raise ValueError("Positive finite confidence scales required")
    _, neighbors = other_neighbors(cKDTree(p[:, :2]), p[:, :2], outer_neighbors)
    neighbors = neighbors[:, inner_neighbors:]
    offsets = p[neighbors, :2]-p[:, None, :2]
    radius = np.maximum(np.linalg.norm(offsets, axis=2).max(axis=1), 1e-8)
    x, y = (offsets/radius[:, None, None]).transpose(2, 0, 1)
    design = np.stack([np.ones_like(x), x, y, x*x, x*y, y*y], axis=2)
    neighbor_z = p[neighbors, 2]
    center = np.median(neighbor_z, axis=1)
    target = neighbor_z-center[:, None]
    gram = np.einsum("nki,nkj->nij", design, design)
    eig = np.linalg.eigvalsh(gram)
    fallback = eig[:, 0] <= 1e-8*np.maximum(eig[:, -1], 1.)
    weights = np.ones_like(target)
    ridge = np.diag([0., 1e-6, 1e-6, 1e-6, 1e-6, 1e-6])
    for _ in range(robust_iterations):
        weighted = design*weights[:, :, None]
        gram = np.einsum("nki,nkj->nij", weighted, design)+ridge
        rhs = np.einsum("nki,nk->ni", weighted, target)
        coefficients = np.linalg.solve(gram, rhs[:, :, None])[:, :, 0]
        residuals = target-np.einsum("nki,ni->nk", design, coefficients)
        location = np.median(residuals, axis=1)
        scale = np.maximum(1.4826*np.median(np.abs(residuals-location[:, None]), axis=1), scale_floor_mm)
        weights = 1/(1+(residuals/(2.5*scale[:, None]))**2)
    predicted = center+coefficients[:, 0]
    predicted[fallback] = center[fallback]
    scale[fallback] = np.maximum(1.4826*np.median(np.abs(neighbor_z[fallback]-center[fallback, None]), axis=1), scale_floor_mm)
    residual = p[:, 2]-predicted
    threshold = np.maximum(threshold_mm, sigma_multiplier*scale)
    trusted = residual <= threshold
    score = np.ones(len(p))
    score[~trusted] = 1/(1+(residual[~trusted]/threshold[~trusted])**2)
    if not np.isfinite(predicted).all():
        raise ValueError("Non-finite annular predictions")
    return DepthConfidence(trusted, predicted, residual, threshold, score, fallback)


def supported_components(points, broad, boundary_neighbors=8, boundary_step_mm=6.,
                         minimum_boundary_points=2, connectivity_multiplier=3.):
    if not isinstance(boundary_neighbors, int) or boundary_neighbors < 1 or not isinstance(minimum_boundary_points, int) or minimum_boundary_points < 1:
        raise ValueError("Positive boundary neighbor/support counts required")
    if not np.isfinite([boundary_step_mm, connectivity_multiplier]).all() or min(boundary_step_mm, connectivity_multiplier) <= 0:
        raise ValueError("Positive finite component scales required")
    xy = np.asarray(points)[:, :2]
    tree = cKDTree(xy)
    distances3, _ = other_neighbors(tree, xy, 3)
    radius = max(float(connectivity_multiplier*np.median(distances3[:, -1])), 1e-8)
    suspect = np.flatnonzero(~broad.trusted)
    accepted = np.zeros(len(xy), dtype=bool)
    if not len(suspect):
        return accepted, {"components": 0, "accepted_components": 0, "sharp_boundary_points": 0, "connectivity_radius_mm": radius}
    pairs = cKDTree(xy[suspect]).query_pairs(radius, output_type="ndarray")
    graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(suspect), len(suspect))).tocsr()
    count, labels = connected_components(graph, directed=False)
    full_labels = np.full(len(xy), -1, dtype=int)
    full_labels[suspect] = labels
    distances, indices = other_neighbors(tree, xy, boundary_neighbors)
    outside = full_labels[indices] != full_labels[:, None]
    jump = broad.residual[:, None]-broad.residual[indices]
    sharp = np.any(outside & (distances <= radius) & (jump >= boundary_step_mm), axis=1)
    support = np.bincount(labels, weights=sharp[suspect], minlength=count)
    good = support >= minimum_boundary_points
    accepted[suspect] = good[labels]
    return accepted, {"components": int(count), "accepted_components": int(good.sum()),
                      "sharp_boundary_points": int(sharp[suspect].sum()), "connectivity_radius_mm": radius}


def complete(points, inner_neighbors=32, outer_neighbors=160, threshold_mm=3., robust_iterations=3,
             sigma_multiplier=3., scale_floor_mm=.5, boundary_neighbors=8, boundary_step_mm=6.,
             minimum_boundary_points=2, connectivity_multiplier=3., boundary_gate=True, **_):
    p = validate_points(points, minimum=8)
    fine = local_depth_confidence(p, 32, threshold_mm, robust_iterations, sigma_multiplier, scale_floor_mm)
    broad = annular_depth_confidence(p, inner_neighbors, outer_neighbors, threshold_mm,
                                    robust_iterations, sigma_multiplier, scale_floor_mm)
    accepted, component_info = supported_components(p, broad, boundary_neighbors, boundary_step_mm,
                                                    minimum_boundary_points, connectivity_multiplier)
    broad_repair = accepted if boundary_gate else ~broad.trusted
    suspect = ~fine.trusted | broad_repair
    trusted = ~suspect
    if trusted.sum() < 8:
        raise ValueError("Too few trusted observations for completion")
    height = float(p[trusted, 2].max())
    corrected = p.copy()
    predicted = np.where(broad_repair, broad.predicted_height, fine.predicted_height)
    corrected[suspect, 2] = np.clip(predicted[suspect], 0., height)
    mesh, parameters = mirror(corrected, height_mm=height, clip_lower_to_belt=True)
    ids = np.flatnonzero(suspect)
    scores = np.where(broad_repair, broad.score, fine.score)
    return mesh, {**parameters, "confidence_method": "local plus annular robust quadratic; abrupt-boundary component support",
                  "confidence_is_calibrated_probability": False, "boundary_gate": boundary_gate,
                  "inner_neighbors": inner_neighbors, "outer_neighbors": outer_neighbors,
                  "threshold_mm": threshold_mm, "robust_iterations": robust_iterations,
                  "sigma_multiplier": sigma_multiplier, "scale_floor_mm": scale_floor_mm,
                  "boundary_neighbors": boundary_neighbors, "boundary_step_mm": boundary_step_mm,
                  "minimum_boundary_points": minimum_boundary_points, "connectivity_multiplier": connectivity_multiplier,
                  "trusted_height_mm": height, "original_max_height_mm": float(p[:, 2].max()),
                  "flagged_points": len(ids), "flagged_fraction": float(suspect.mean()),
                  "local_flagged_points": int((~fine.trusted).sum()), "annular_flagged_points": int((~broad.trusted).sum()),
                  "broad_repaired_points": int(broad_repair.sum()),
                  "unsupported_neighborhoods": int(fine.fallback.sum()+broad.fallback.sum()),
                  **component_info, "suspect_point_indices": ids.tolist(),
                  "suspect_confidence_scores": scores[suspect].tolist(),
                  "suspect_residuals_mm": np.where(broad_repair, broad.residual, fine.residual)[suspect].tolist(),
                  "suspect_repaired_height_mm": corrected[suspect, 2].tolist(),
                  "trusted_point_policy": "retain XYZ exactly; repair only selected positive residuals",
                  "assumption": "abrupt patch boundaries distinguish this modeled noise from smooth true bumps; no hidden-shape identifiability"}


def annular_only(points, **kwargs):
    return complete(points, boundary_gate=False, **kwargs)
