"""Bonn RGB-D adapter: declared metric units and supplied camera-to-fruit poses.

Observation loading deliberately has no reference argument or reference access.
No conveyor/belt frame, ICP, reference centering, or reference scale fitting.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from .geometry import check_scale_mm, rigid_matrix, transform_points
from .io import load_points, safe_path, sha256


def validate_manifest(manifest):
    roles = manifest["roles"]
    if set(roles) != {"train", "development", "holdout"}:
        raise ValueError("Require explicit train/development/holdout roles")
    ids = [pid for values in roles.values() for pid in values]
    if len(ids) != len(set(ids)):
        raise ValueError("Object IDs cross roles or are duplicated")
    records = manifest["objects"]
    if sorted(ids) != sorted(o["object_id"] for o in records):
        raise ValueError("Role/record IDs differ")
    for o in records:
        if o["object_id"] not in roles[o["role"]]:
            raise ValueError("Record has the wrong role")
        expected_split = "train" if o["role"] == "train" else "val"
        if o["source_split"] != expected_split:
            raise ValueError("Official hidden test cannot enter this protocol")
        prefix = f"shape_completion_challenge/{expected_split}/{o['object_id']}/"
        for member in o["members"]:
            name = member["name"]
            if not name.startswith(prefix) or ".." in Path(name).parts:
                raise ValueError("Unsafe or mismatched member identity")
        expected = {o["reference"]}
        if o["role"] != "train":
            expected.update(o[k] for k in ["intrinsic", "rgb", "depth", "mask", "pose"])
        if expected != {m["name"] for m in o["members"]}:
            raise ValueError("Member fields differ from member listing")
    return manifest


def verified_member(root, record, key):
    """Require a size/CRC-checked download receipt and matching content SHA."""
    receipt = json.loads((Path(root)/"download_manifest.json").read_text())
    byname = {m["name"]: m for m in receipt["members"]}
    name = record[key]
    item = byname[name]
    path = safe_path(Path(root), name)
    if not item["crc32_verified"] or path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
        raise ValueError(f"Unverified or modified dataset member: {name}")
    return path


def depth_component(valid, depth_m, jump_mm=10., minimum=100):
    """Largest 4-neighbor depth component; ties favor first row-major pixel."""
    if valid.shape != depth_m.shape or valid.ndim != 2 or jump_mm <= 0:
        raise ValueError("Invalid depth-component input")
    locations = np.flatnonzero(valid)
    if len(locations) < minimum:
        raise ValueError("Too few valid mask/depth pixels")
    index = np.full(valid.shape, -1, dtype=np.int32)
    index.flat[locations] = np.arange(len(locations))
    sources, targets = [], []
    for a, b in [(np.s_[:, :-1], np.s_[:, 1:]), (np.s_[:-1, :], np.s_[1:, :])]:
        adjacent = valid[a] & valid[b] & (np.abs(depth_m[a]-depth_m[b]) <= jump_mm/1000.)
        sources.append(index[a][adjacent]); targets.append(index[b][adjacent])
    source, target = np.concatenate(sources), np.concatenate(targets)
    graph = coo_matrix((np.ones(len(source), dtype=np.int8), (source, target)),
                       shape=(len(locations), len(locations))).tocsr()
    count, labels = connected_components(graph, directed=False)
    sizes = np.bincount(labels)
    largest = int(np.argmax(sizes))
    if sizes[largest] < minimum:
        raise ValueError("Largest depth component below fixed minimum")
    kept = np.zeros_like(valid, dtype=bool)
    kept.flat[locations[labels == largest]] = True
    return kept, {"components": count, "kept_points": int(kept.sum()),
                  "raw_valid_points": len(locations), "retained_fraction": float(kept.sum()/len(locations)),
                  "neighbor_jump_mm": jump_mm, "connectivity": 4, "minimum_points": minimum}


def load_observations(root, record, jump_mm=10., minimum=100):
    paths = {k: verified_member(root, record, k) for k in ["intrinsic", "depth", "mask", "pose"]}
    intrinsic = json.loads(paths["intrinsic"].read_text())
    k = np.asarray(intrinsic["intrinsic_matrix"], dtype=float).reshape(3, 3, order="F")
    if not np.isfinite(k).all() or k[0, 0] <= 0 or k[1, 1] <= 0 or not np.allclose(k[2], [0, 0, 1]):
        raise ValueError("Invalid pinhole intrinsic matrix")
    depth = np.load(paths["depth"], allow_pickle=False)
    with Image.open(paths["mask"]) as im:
        mask = np.asarray(im)
    if mask.ndim != 2 or depth.shape != mask.shape:
        raise ValueError("Depth/mask must be matching 2D arrays")
    if (intrinsic.get("height", depth.shape[0]), intrinsic.get("width", depth.shape[1])) != depth.shape:
        raise ValueError("Intrinsic image dimensions differ")
    pose = rigid_matrix(np.loadtxt(paths["pose"]))
    valid = (mask > 0) & np.isfinite(depth) & (depth > 0) & (depth < 1.)
    component, audit = depth_component(valid, depth, jump_mm, minimum)
    conditions = {}
    for name, pixels in [("raw_valid", valid), ("depth_component", component)]:
        yy, xx = np.nonzero(pixels)
        rays = np.column_stack([xx, yy, np.ones(len(xx))]) @ np.linalg.inv(k).T
        points = transform_points(rays*depth[yy, xx, None], pose)*1000.
        check_scale_mm(points)
        conditions[name] = points
    return conditions, {"object_id": record["object_id"], "frame_id": record["frame_id"],
                        "mask_values": np.unique(mask).tolist(), "depth_shape": depth.shape,
                        "camera_to_canonical_m": pose, "component_audit": audit,
                        "input_sha256": {key: sha256(path) for key, path in paths.items()},
                        "units": "source depth and pose translation m; canonical output mm",
                        "alignment": "provided pose only; no reference geometry accessed"}


def load_reference(root, record):
    return load_points(verified_member(root, record, "reference"), "m")
