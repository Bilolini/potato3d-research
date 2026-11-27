"""Reference-free RGB-D geometry, robust rigid ICP and 3D flow registration."""

import io

import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates
from scipy.spatial import cKDTree
import trimesh

import prepare as prep


def apply(points, t):
    return np.asarray(points) @ t[:3, :3].T + t[:3, 3]


def in_mm(transform_m):
    t = np.array(transform_m, dtype=float, copy=True)
    if not prep.safe_rigid(t):
        raise ValueError("Invalid meter-frame registration")
    t[:3, 3] *= 1000.
    return t


def unproject(uv, depth_mm, intrinsic):
    homogeneous = np.column_stack((uv, np.ones(len(uv))))
    return (homogeneous @ np.linalg.inv(intrinsic).T) * depth_mm[:, None]


def voxel(points, size):
    _, inverse = np.unique(np.floor(points / size).astype(np.int64), axis=0, return_inverse=True)
    counts = np.bincount(inverse)
    return np.column_stack([np.bincount(inverse, weights=x) / counts for x in points.T])


def read_view(frame, ply_archive, images, matrix):
    raw_ply = io.BytesIO(prep.member_bytes(ply_archive, frame["ply"]))
    cloud = trimesh.load(raw_ply, file_type="ply", process=False)
    points = np.asarray(cloud.vertices, dtype=float) * 1000.
    if len(points) < 40 or not np.isfinite(points).all() or np.any(points[:, 2] <= 0):
        raise ValueError("Invalid positive metric camera cloud")
    rgba = prep.read_rgba(images[frame["rgb"]["archive"]], frame["rgb"])
    file = prep.member_bytes(images[frame["depth"]["archive"]], frame["depth"])
    with Image.open(io.BytesIO(file)) as source:
        depth = np.array(source)
    mask = rgba[:, :, 3] > 0
    if depth.dtype != np.uint16 or depth.shape != mask.shape:
        raise ValueError("Expected registered 16-bit millimeter depth")

    projection = points @ matrix.T
    uv = projection[:, :2] / projection[:, 2:]
    pixels = np.rint(uv).astype(int)
    x, y = pixels.T
    if np.any(x < 0) or np.any(y < 0) or np.any(x >= mask.shape[1]) or np.any(y >= mask.shape[0]):
        raise ValueError("A released cloud projects outside its own frame")
    allowed = np.zeros_like(mask)
    allowed[y, x] = True
    if int(allowed.sum()) != len(points) or not mask[y, x].all() or np.any(depth[y, x] == 0):
        raise ValueError("PLY does not map one-to-one into provided alpha and valid depth")
    delta_px = float(np.max(np.abs(uv - pixels)))
    delta_mm = float(np.max(np.linalg.norm(unproject(pixels, depth[y, x], matrix) - points, axis=1)))
    if delta_px > .1 or delta_mm > .1:
        raise ValueError(f"PLY/raw calibration mismatch ({delta_px:.4g} px, {delta_mm:.4g} mm)")
    return {"points": points, "support": allowed, "depth": depth, "pixels": pixels,
            "calibration": {"point_count": len(points), "largest_pixel_error_px": delta_px,
                            "largest_xyz_error_mm": delta_mm}}


def rigid_fit(src, dst):
    src_center = src.mean(axis=0)
    dst_center = dst.mean(axis=0)
    u, s, v = np.linalg.svd((src - src_center).T @ (dst - dst_center))
    if not np.isfinite(s).all() or s[1] <= 1e-8:
        raise ValueError("Rigid fit has collinear correspondence support")
    if np.linalg.det(v.T @ u.T) < 0:
        v[-1, :] *= -1
    r = v.T @ u.T
    t = np.eye(4)
    t[:3, :3] = r
    t[:3, 3] = dst_center - r @ src_center
    return t


def translation(delta):
    t = np.eye(4)
    t[:3, 3] = delta
    return t


def estimate_icp(source, target, diagnostics):
    source, target = source["points"], target["points"]
    pose = translation(voxel(target, 2.).mean(axis=0) - voxel(source, 2.).mean(axis=0))
    for size, gate in ((2., 12.), (1.5, 8.), (1., 5.)):
        a, b = voxel(source, size), voxel(target, size)
        tree = cKDTree(b)
        for _ in range(15):
            deformed = apply(a, pose)
            distance, match = tree.query(deformed)
            valid = np.flatnonzero(distance <= gate)
            if len(valid) < 40:
                diagnostics.update({"nearest_overlap_fraction": float(len(valid)/len(a)), "in_gate": len(valid)})
                raise ValueError(f"ICP {size:g} mm voxel stage has fewer than 40 in-gate matches")
            retained = valid[np.argsort(distance[valid], kind="stable")[:max(40, int(.8*len(valid)))]]
            pose = rigid_fit(deformed[retained], b[match[retained]]) @ pose
    distance, _ = tree.query(apply(a, pose))
    inliers = distance <= 5.
    overlap = float(inliers.mean())
    diagnostics.update({
        "nearest_overlap_fraction": overlap, "in_gate": int(inliers.sum()), "voxel_sources": len(a),
        "in_gate_rmse_mm": float(np.sqrt(np.mean(distance[inliers]**2))) if inliers.any() else None,
    })
    if overlap < .30 or inliers.sum() < 40:
        raise ValueError("ICP final overlap or correspondence count fell below the frozen threshold")
    return pose


def flow_matches(source, target, flow, matrix, diagnostics):
    forward, reverse = flow["forward"], flow["reverse"]
    origin = flow["origin"]
    if forward.shape != reverse.shape or forward.ndim != 3 or forward.shape[2] != 2:
        raise ValueError("Unmatched forward and reverse flow arrays")
    height, width = forward.shape[:2]
    pixels = source["pixels"]
    pixels = pixels[np.all(pixels % 2 == 0, axis=1)]
    local = pixels - origin
    if np.any(local < 0) or np.any(local[:, 0] >= width) or np.any(local[:, 1] >= height):
        raise ValueError("The flow crop lost provided masked depth support")
    q = local + forward[local[:, 1], local[:, 0], :]
    rounded = np.rint(q + origin).astype(int)
    x, y = rounded.T
    full_h, full_w = target["support"].shape
    valid = ((q[:, 0] >= 0) & (q[:, 0] <= width-1) & (q[:, 1] >= 0) & (q[:, 1] <= height-1)
             & (x >= 0) & (x < full_w) & (y >= 0) & (y < full_h))
    indices = np.flatnonzero(valid)
    indices = indices[target["support"][y[indices], x[indices]]]
    pred = q[indices]
    backward = np.column_stack([
        map_coordinates(reverse[:, :, axis], pred.T[::-1], order=1, mode="nearest", prefilter=False)
        for axis in range(2)
    ])
    cycle = np.linalg.norm(pred + backward - local[indices], axis=1)
    kept = indices[cycle <= 1.5]
    diagnostics.update({
        "sampled_source_pixels": len(pixels), "valid_target_support": len(indices),
        "flow_cycle_matches": len(kept), "cycle_median_px": float(np.median(cycle)) if len(cycle) else None,
    })
    src = pixels[kept]
    ax, ay = src.T
    return (unproject(src, source["depth"][ay, ax], matrix),
            unproject(q[kept] + origin, target["depth"][y[kept], x[kept]], matrix))


def ransac(src, dst, diagnostics):
    if len(src) < 40:
        raise ValueError("Fewer than 40 valid RAFT RGB-D matches")
    rng = np.random.default_rng(prep.SEED)
    best, count, spread = None, -1, np.inf
    for _ in range(256):
        chosen = rng.choice(len(src), 3, replace=False)
        try:
            pose = rigid_fit(src[chosen], dst[chosen])
        except ValueError:
            continue
        errors = np.linalg.norm(apply(src, pose) - dst, axis=1)
        keep = errors <= 2.5
        n = int(keep.sum())
        if n > count or (n == count and n > 0 and np.median(errors[keep]) < spread):
            best, count = keep, n
            spread = float(np.median(errors[keep])) if n else np.inf
    if best is None or count < 40:
        diagnostics["ransac_inliers"] = max(0, count)
        raise ValueError("RAFT RANSAC could not find 40 initial inliers")
    for _ in range(3):
        if best.sum() < 40:
            raise ValueError("RAFT lost inliers during rigid refinement")
        pose = rigid_fit(src[best], dst[best])
        errors = np.linalg.norm(apply(src, pose) - dst, axis=1)
        best = errors <= 2.5
    spans = []
    for points in (src[best], dst[best]):
        axes = np.linalg.svd(points - points.mean(axis=0), compute_uv=False)
        spans.append(float(axes[1] / np.sqrt(len(points))) if len(axes) >= 2 else 0.)
    diagnostics.update({
        "ransac_inliers": int(best.sum()), "ransac_inlier_fraction": float(best.mean()),
        "ransac_secondary_spans_mm": spans,
        "ransac_rmse_mm": float(np.sqrt(np.mean(errors[best]**2))) if best.any() else None,
    })
    if best.sum() < 40 or best.mean() < .30 or min(spans) < 4.:
        raise ValueError("RAFT final rigid inlier count, fraction or spatial spread too small")
    return pose


def to_center(links, center):
    transforms = [None] * (len(links) + 1)
    transforms[center] = np.eye(4)
    for i in range(center - 1, -1, -1):
        transforms[i] = transforms[i+1] @ links[i]
    for i in range(center + 1, len(transforms)):
        transforms[i] = transforms[i-1] @ np.linalg.inv(links[i-1])
    return transforms


def geometry_check(k):
    rng = np.random.default_rng(prep.SEED)
    src = rng.uniform([-48., -32., 273.], [72., 42., 341.], size=(450, 3))

    def motion(angle, offset):
        c, s = np.cos(angle), np.sin(angle)
        t = translation(offset)
        t[:3, :3] = [[c, -s, 0], [s, c, 0], [0, 0, 1]]
        return t

    link_01 = motion(.08, [7., -11., 2.])
    link_12 = motion(-.06, [9., -7., -4.])
    at_center = apply(src, link_01)
    observed = apply(at_center, link_12)
    transforms = to_center([link_01, link_12], 1)
    copies = [apply(p, t) for p, t in zip((src, at_center, observed), transforms, strict=True)]
    chain_error = max(float(np.max(np.linalg.norm(points - at_center, axis=1))) for points in copies)
    uvw = at_center @ k.T
    uv = uvw[:, :2] / uvw[:, 2:]
    lift_error = float(np.max(np.linalg.norm(unproject(uv, at_center[:, 2], k) - at_center, axis=1)))
    corrupted = at_center.copy()
    corrupted[::5] += rng.uniform(18, 50, size=corrupted[::5].shape)
    robust = ransac(src, corrupted, {})
    rigid_error = float(np.max(np.linalg.norm(apply(src, robust) - at_center, axis=1)))
    anchored = motion(.39, [.12, -.024, .18])
    anchor_error = float(np.max(np.linalg.norm(apply(src / 1000, anchored)*1000 - apply(src, in_mm(anchored)), axis=1)))
    icp_target = src + np.array([4., -8., 3.])
    test_icp = estimate_icp({"points": src}, {"points": icp_target}, {})
    icp_error = float(np.max(np.linalg.norm(apply(src, test_icp) - icp_target, axis=1)))
    check = {"chain_round_trip_mm": chain_error, "pinhole_lift_error_mm": lift_error,
             "rigid_ransac_with_outliers_mm": rigid_error, "m_to_mm_anchor_error_mm": anchor_error,
             "icp_translation_error_mm": icp_error}
    if max(check.values()) > 1e-8:
        raise ValueError(f"Synthetic transformation preflight failed: {check}")
    return check
