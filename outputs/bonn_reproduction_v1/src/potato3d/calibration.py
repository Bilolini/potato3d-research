"""Reference-free depth/PLY checks and a background-plane *proxy* audit."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_dilation


def intrinsics_from_json(data):
    matrix = np.asarray(data["intrinsic_matrix"], dtype=float).reshape(3, 3, order="F")
    if not np.isfinite(matrix).all() or matrix[0, 0] <= 0 or matrix[1, 1] <= 0:
        raise ValueError("Invalid camera intrinsics")
    if not np.allclose(matrix[2], [0, 0, 1]):
        raise ValueError("Expected a pinhole intrinsic matrix")
    return matrix


def depth_points(depth_mm, pixels_xy, matrix):
    uv = np.asarray(pixels_xy)
    z = np.asarray(depth_mm)[uv[:, 1], uv[:, 0]].astype(float)
    rays = np.column_stack([uv, np.ones(len(uv))]) @ np.linalg.inv(matrix).T
    return rays*z[:, None]


def verify_ply_depth(points_mm, depth_mm, alpha, matrix):
    points = np.asarray(points_mm)
    projected = points @ matrix.T
    projected = projected[:, :2]/projected[:, 2:]
    pixels = np.rint(projected).astype(int)
    height, width = depth_mm.shape
    inside = ((pixels[:, 0] >= 0) & (pixels[:, 0] < width) &
              (pixels[:, 1] >= 0) & (pixels[:, 1] < height))
    if not inside.all():
        raise ValueError("PLY projects outside the source depth image")
    reconstructed = depth_points(depth_mm, pixels, matrix)
    distances = np.linalg.norm(reconstructed-points, axis=1)
    error = np.abs(projected-pixels)
    return {"points": len(points), "max_pixel_rounding_error": float(error.max()),
            "p99_xyz_reprojection_error_mm": float(np.quantile(distances, .99)),
            "max_xyz_reprojection_error_mm": float(distances.max()),
            "fraction_inside_object_alpha": float(np.mean(alpha[pixels[:, 1], pixels[:, 0]] > 0))}


def fit_plane_ransac(points, seed=527, iterations=256, threshold_mm=1.5, max_tilt_deg=15.):
    p = np.asarray(points, dtype=float)
    if len(p) < 20 or not np.isfinite(p).all():
        raise ValueError("Need at least 20 finite background candidates")
    design = np.column_stack([p[:, :2], np.ones(len(p))])
    rng = np.random.default_rng(seed)
    best = None
    best_count, best_median = -1, np.inf
    for _ in range(iterations):
        indices = rng.choice(len(p), 3, replace=False)
        if np.linalg.cond(design[indices]) > 1e8:
            continue
        coefficient = np.linalg.solve(design[indices], p[indices, 2])
        slope = np.linalg.norm(coefficient[:2])
        if np.degrees(np.arctan(slope)) > max_tilt_deg:
            continue
        residual = np.abs(p[:, 2]-design@coefficient)/np.sqrt(1+slope*slope)
        inliers = residual <= threshold_mm
        count = int(inliers.sum())
        median = np.median(residual[inliers]) if count else np.inf
        if count > best_count or (count == best_count and median < best_median):
            best, best_count, best_median = coefficient, count, median
    if best is None or best_count < 20:
        raise ValueError("No near-horizontal background plane supported")
    for _ in range(4):
        residual = np.abs(p[:, 2]-design@best)/np.sqrt(1+np.sum(best[:2]**2))
        inliers = residual <= threshold_mm
        if inliers.sum() < 20:
            raise ValueError("Plane refinement lost support")
        best = np.linalg.lstsq(design[inliers], p[inliers, 2], rcond=None)[0]
    if np.degrees(np.arctan(np.linalg.norm(best[:2]))) > max_tilt_deg:
        raise ValueError("Refined background plane exceeds allowed tilt")
    return best


def plane_transform(coefficients):
    """Camera-mm -> plane-height-mm, proper rotation with height toward camera."""
    a, b, d = coefficients
    normal = np.array([a, b, -1.])/np.sqrt(1+a*a+b*b)
    x_axis = np.array([1., 0, 0])-normal*normal[0]
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(normal, x_axis)
    transform = np.eye(4)
    transform[:3, :3] = [x_axis, y_axis, normal]
    transform[2, 3] = d/np.sqrt(1+a*a+b*b)
    return transform


def audit_background(depth_mm, alpha, matrix, seed=527):
    # Parameters describe the audit, not a validated conveyor support calibration.
    depth = np.asarray(depth_mm)
    h, w = depth.shape
    roi = np.zeros_like(depth, dtype=bool)
    roi[int(.05*h):int(.95*h), int(.10*w):int(.90*w)] = True
    mask = roi & ~binary_dilation(np.asarray(alpha) > 0, iterations=15)
    mask &= (depth >= 330) & (depth <= 375)
    yy, xx = np.nonzero(mask)
    if len(xx) < 1000:
        raise ValueError("Too few candidate background depth pixels")
    rng = np.random.default_rng(seed)
    indices = rng.choice(len(xx), min(12000, len(xx)), replace=False)
    pixels = np.column_stack([xx[indices], yy[indices]])
    points = depth_points(depth, pixels, matrix)
    split = int(.8*len(points))
    coefficient = fit_plane_ransac(points[:split], seed=seed)
    residual = np.abs(points[:, 2] - np.column_stack([points[:, :2], np.ones(len(points))])@coefficient)
    residual /= np.sqrt(1+np.sum(coefficient[:2]**2))
    inliers = residual <= 1.5
    heldout = residual[split:]
    tile = (pixels[inliers, 1]*4//h)*4 + pixels[inliers, 0]*4//w
    audit = {"status": "candidate background proxy; not certified physical belt calibration",
             "uses_reference_geometry": False, "uses_physical_measurements": False,
             "selection": "image x10-90%, y5-95%; target alpha dilated 15 px excluded; depth 330-375 mm",
             "candidate_pixels": len(xx), "sampled_pixels": len(points), "training_pixels": split,
             "heldout_pixels": len(points)-split, "seed": seed,
             "plane_z_ax_by_d": coefficient.tolist(),
             "camera_axis_intercept_mm": float(coefficient[2]),
             "tilt_deg": float(np.degrees(np.arctan(np.linalg.norm(coefficient[:2])))),
             "train_inlier_fraction_at_1p5mm": float(inliers[:split].mean()),
             "heldout_inlier_fraction_at_1p5mm": float(np.mean(heldout <= 1.5)),
             "heldout_all_candidates_median_residual_mm": float(np.median(heldout)),
             "heldout_inlier_median_residual_mm": float(np.median(heldout[heldout <= 1.5])) if np.any(heldout <= 1.5) else None,
             "inlier_coverage_tiles_of_16": len(np.unique(tile)),
             "camera_mm_to_proxy_plane_mm": plane_transform(coefficient).tolist(),
             "limitations": ["Other potatoes/rollers/voids are not semantically labeled",
                             "Dominant plane can intersect round rods instead of their support envelope",
                             "Single-frame holdout pixels validate fit support, not physical support height",
                             "No prediction or existing experiment is recalibrated"]}
    return audit, pixels, inliers
