"""Build B and D from predicted masks and raw RGB-D in center-camera coordinates."""

from contextlib import ExitStack
import csv
import io
from pathlib import Path
import time
from zipfile import BadZipFile

import numpy as np
from PIL import Image
from scipy.spatial import ConvexHull, QhullError
import torch
import torchvision

import common as c
import alignment as align
import flow as raft
from register import camera
from studies.sam2_center_weight_v1 import run as sam

ERRORS = (KeyError, OSError, ValueError, RuntimeError, OverflowError, BadZipFile, np.linalg.LinAlgError, QhullError)


def bulk(points):
    area = float(ConvexHull(points[:, :2]).volume)
    height = max(0., 350. - float(np.quantile(points[:, 2], .05)))
    if not np.isfinite(area) or area <= 0 or not np.isfinite(height):
        raise ValueError("Invalid XY hull area or height")
    return {"area_mm2": area, "height_mm": height, "proxy_cm3": area * height / 1000., "point_count": len(points)}


def merged_cloud(views, suffixes, selected, poses):
    transforms = align.to_center(poses, suffixes.index(selected[1]))
    by_suffix = {s: transforms[suffixes.index(s)] for s in selected}
    if any(not c.prep.safe_rigid(x) for x in by_suffix.values()):
        raise ValueError("Composed motion is not proper rigid")
    cloud = np.concatenate([align.apply(views[s]["points"], by_suffix[s]) for s in selected])
    if not np.isfinite(cloud).all() or len(cloud) < 40:
        raise ValueError("Invalid raw fused cloud")
    return cloud, {str(s): t.tolist() for s, t in by_suffix.items()}


def rgb_scene(archives, member):
    with Image.open(io.BytesIO(c.prep.member_bytes(archives[member["archive"]], member))) as image:
        if image.size != (1280, 720):
            raise ValueError("Unexpected released RGB resolution")
        return np.asarray(image.convert("RGB"))


def view(archives, frame, mask, thickness, intrinsic):
    if not mask.any():
        raise ValueError("Predicted mask is empty")
    member = frame["depth"]
    with Image.open(io.BytesIO(c.prep.member_bytes(archives[member["archive"]], member))) as image:
        depth = np.asarray(image)
    if depth.shape != mask.shape or depth.dtype != np.uint16:
        raise ValueError("Expected registered 16-bit raw depth in mm")
    support, bounds = sam.filtered_support(depth, mask, thickness)
    y, x = np.nonzero(support)
    pixels = np.column_stack((x, y))
    if len(pixels) < 3:
        raise ValueError(f"Only {len(pixels)} pixels passed the predicted-mask depth filter")
    points = align.unproject(pixels, depth[y, x], intrinsic)
    if not np.isfinite(points).all() or np.any(points[:, 2] <= 0):
        raise ValueError("Invalid camera-space depth points")
    return {"points": points, "pixels": pixels, "depth": depth, "support": support,
            "bounds_mm": list(bounds), "mask_pixels": int(mask.sum()), "mask": mask}


def estimate_link(first, second, tracker, normalize, rgb_first, rgb_second, intrinsic, detail):
    # The archived crop helper uses a fourth plane for mask membership.
    a = np.dstack((rgb_first, first["mask"].astype(np.uint8)))
    b = np.dstack((rgb_second, second["mask"].astype(np.uint8)))
    started = time.perf_counter()
    try:
        x0, y0, x1, y1 = raft.crop_bounds(a, b)
        detail["crop_xyxy"] = [x0, y0, x1, y1]
        a, b = rgb_first[y0:y1, x0:x1], rgb_second[y0:y1, x0:x1]
        flows = {"origin": np.array([x0, y0]), "forward": raft.predict(a, b, tracker, normalize),
                 "reverse": raft.predict(b, a, tracker, normalize)}
    finally:
        detail["flow_wall_s"] = time.perf_counter() - started
    started = time.perf_counter()
    try:
        src, dst = align.flow_matches(first, second, flows, intrinsic, detail)
        pose = align.ransac(src, dst, detail)
        if not c.prep.safe_rigid(pose):
            raise ValueError("Estimated link is not a proper rigid transform")
        return pose
    finally:
        detail["fit_wall_s"] = time.perf_counter() - started


def reconstruct(case, archives, matrix, tracker, normalize, thickness):
    tuber = case["tuber"]
    track = c.prep.read_json(c.track_path(tuber))
    frames = case["links_rgbd"]
    lower, center, upper = case["selected"]
    packed = c.packed_masks(tuber, track) if track["mask_sha256"] else {}
    row = {"tuber": tuber, "analysis": case["analysis"], "selected": [lower, center, upper],
           "tracking_record_sha256": c.prep.digest(c.track_path(tuber)), "measured_thickness_mm": thickness,
           "views": [], "links": [], "features": dict(B=None, D=None), "failures": dict(B=None, D=None),
           "center_feature_wall_s": 0., "fuse_feature_wall_s": 0., "fused_to_center": None, "cloud_sha256": None}
    views, rgb, clouds = {}, {}, {}
    for frame in frames:
        suffix = frame["suffix"]
        started = time.perf_counter()
        detail = {"suffix": suffix, "error": None, "support_pixels": None, "mask_pixels": None, "bounds_mm": None}
        try:
            current = view(archives, frame, c.unpack(packed[suffix]), thickness, matrix)
            views[suffix] = current
            detail.update(support_pixels=len(current["pixels"]), mask_pixels=current["mask_pixels"],
                          bounds_mm=current["bounds_mm"])
        except ERRORS as error:
            detail["error"] = f"{type(error).__name__}: {error}"
        detail["wall_s"] = time.perf_counter() - started
        row["views"].append(detail)
    started = time.perf_counter()
    try:
        points = views[center]["points"]
        row["features"]["B"] = bulk(points)
        clouds["B"] = points
    except ERRORS as error:
        row["failures"]["B"] = f"Center support or hull unavailable: {error}"
    row["center_feature_wall_s"] = time.perf_counter() - started

    poses = []
    for a, b in zip(frames[:-1], frames[1:], strict=True):
        source, target = a["suffix"], b["suffix"]
        detail = {"source": source, "target": target, "failure": None, "transform": None,
                  "rgb_wall_s": 0., "flow_wall_s": 0., "fit_wall_s": 0.}
        pose = None
        try:
            if source not in views or target not in views:
                raise ValueError("Required source or target predicted-mask depth support unavailable")
            started = time.perf_counter()
            try:
                for frame in (a, b):
                    suffix = frame["suffix"]
                    if suffix not in rgb:
                        rgb[suffix] = rgb_scene(archives, frame["rgb"])
            finally:
                detail["rgb_wall_s"] = time.perf_counter() - started
            pose = estimate_link(views[source], views[target], tracker, normalize, rgb[source], rgb[target], matrix, detail)
            detail["transform"] = pose.tolist()
        except ERRORS as error:
            detail["failure"] = f"{type(error).__name__}: {error}"
        finally:
            rgb.pop(source, None)
        poses.append(pose)
        row["links"].append(detail)

    if any(pose is None for pose in poses):
        row["failures"]["D"] = "A required adjacent RAFT link failed"
    else:
        started = time.perf_counter()
        try:
            merged, relative = merged_cloud(views, [f["suffix"] for f in frames], case["selected"], poses)
            row["features"]["D"] = bulk(align.voxel(merged, 1.))
            row["fused_to_center"] = relative
            clouds["D"] = merged
        except ERRORS as error:
            row["failures"]["D"] = f"Fusion or hull unavailable: {error}"
        row["fuse_feature_wall_s"] = time.perf_counter() - started
    return row, clouds


def save_clouds(path, clouds):
    temp = path.with_suffix(".tmp")
    with temp.open("wb") as stream:
        np.savez_compressed(stream, **clouds)
    temp.replace(path)
    return c.prep.digest(path)


def read_thickness(ids):
    result = {}
    with c.TRAITS.open(newline="") as stream:
        for row in csv.DictReader(stream):
            tuber = row["label"]
            if tuber not in ids:
                continue
            if tuber in result:
                raise ValueError(f"Duplicate thickness for {tuber}")
            result[tuber] = float(row["x3_depth_mm"])
    if set(result) != ids or not all(np.isfinite(x) and x > 0. for x in result.values()):
        raise ValueError("Missing or invalid measured thickness for a frozen ID")
    return result


def reconstruct_all():
    freeze, receipt = c.tracking_bundle()
    if (torch.__version__, torchvision.__version__) != c.ENV:
        raise ValueError("Use the archived CPU RAFT environment")
    output = c.OUTPUT / "predicted"
    output.mkdir(parents=True, exist_ok=True)
    recipe = {
        "manifest_sha256": c.prep.digest(c.STUDY / "frame_manifest.json"),
        "tracking_replay_sha256": c.prep.digest(c.STUDY / "tracking_replay.json"),
        "code_sha256": c.prep.digest(Path(__file__)), "raft_checkpoint": c.prep.CHECKPOINT_HASH,
    }
    c.prep.freeze_check(output / "recipe.json", recipe)
    matrix = camera()
    geometry_check = align.geometry_check(matrix)
    ids = {r["tuber"] for r in freeze["roster"]}
    thicknesses = read_thickness(ids)
    record_hashes = []
    names = {f[key]["archive"] for case in freeze["roster"] for f in case["links_rgbd"] for key in ("rgb", "depth")}
    model_start = time.perf_counter()
    tracker, normalize, _ = raft.model()
    model_wall_s = time.perf_counter() - model_start
    with ExitStack() as stack, torch.inference_mode():
        preflight = raft.synthetic_check(tracker, normalize)
        archive = c.prep.open_images(stack, names)
        for i, case in enumerate(freeze["roster"], 1):
            tuber = case["tuber"]
            destination = output / f"{tuber}.json"
            if not destination.exists():
                row, clouds = reconstruct(case, archive, matrix, tracker, normalize, thicknesses[tuber])
                if clouds and case["analysis"] == "geometry":
                    row["cloud_sha256"] = save_clouds(destination.with_suffix(".npz"), clouds)
                c.prep.write_json(destination, row)
            else:
                row = c.prep.read_json(destination)
            if row["tracking_record_sha256"] != receipt["rows"][i-1]["tracking_record_sha256"]:
                raise ValueError(f"Prediction cache used a different tracking record: {tuber}")
            if row["cloud_sha256"] and row["cloud_sha256"] != c.prep.digest(destination.with_suffix(".npz")):
                raise ValueError(f"Cloud changed: {tuber}")
            record_hashes.append({"tuber": tuber, "sha256": c.prep.digest(destination)})
            print(f"Predicted-mask RGB-D {i}/40 {tuber}: B={row['features']['B'] is not None}, "
                  f"D={row['features']['D'] is not None}", flush=True)
    c.prep.write_json(c.STUDY / "predicted_input_ledger.json", {
        "recipe": recipe, "raw_image_archives_opened": sorted(names), "cloud_frame": "center camera, mm",
        "measured_input_columns": ["label", "x3_depth_mm"],
        "python_modules": ["SAM 2 archived depth filter", "RAFT archived model/crop", "archived 3D lift and RANSAC"],
        "geometry_preflight": geometry_check, "flow_preflight": preflight,
        "raft_setup_wall_s": model_wall_s, "records": record_hashes,
    })


if __name__ == "__main__":
    reconstruct_all()
