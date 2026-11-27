"""Audit only fixed input/reference frames; no completion, tuning, ICP or volume score."""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree
import trimesh

from potato3d.geometry import rigid_matrix, transform_points
from potato3d.io import sha256, write_json


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    report = {"role": "train/validation data-access smoke checks only; no method score", "objects": []}
    for split, pid in [("train", "lab1"), ("val", "lab15")]:
        root = args.data/"shape_completion_challenge"/split/pid
        k = np.array(json.loads((root/"input/intrinsic.json").read_text())["intrinsic_matrix"]).reshape(3, 3, order="F")
        depth = np.load(root/"input/depth/00001.npy", allow_pickle=False)
        with Image.open(root/"input/masks/00001.png") as im:
            mask = np.array(im)
        pose = rigid_matrix(np.loadtxt(root/"input/poses/00001.txt"))
        valid = (mask > 0) & np.isfinite(depth) & (depth > 0) & (depth < 1.)
        yy, xx = np.nonzero(valid)
        rays = np.column_stack([xx, yy, np.ones(len(xx))])@np.linalg.inv(k).T
        camera = rays*depth[yy, xx, None]
        canonical = transform_points(camera, pose)
        reference = trimesh.load(root/"gt/pcd/fruit.ply", process=False)
        vertices = np.asarray(reference.vertices)
        if not np.isfinite(canonical).all() or not np.isfinite(vertices).all() or not len(canonical):
            raise ValueError("Invalid/empty paired geometry")
        distances = cKDTree(vertices).query(canonical, workers=1)[0]*1000
        folder = args.out/f"{split}_{pid}"
        folder.mkdir()
        trimesh.points.PointCloud(canonical*1000).export(folder/"partial_canonical_mm.ply")
        trimesh.points.PointCloud(vertices*1000).export(folder/"reference_canonical_mm.ply")
        record = {"split": split, "object_id": pid, "frame": "00001", "depth_shape": list(depth.shape),
                  "mask_values": np.unique(mask).tolist(), "partial_points": len(canonical), "reference_points": len(vertices),
                  "reference_has_triangle_faces": bool(hasattr(reference, "faces") and len(reference.faces)),
                  "source_units": "meters, as used by the official loader; checked against fruit-scale extents",
                  "partial_depth_median_m": float(np.median(depth[valid])), "camera_to_canonical_m": pose.tolist(),
                  "canonical_partial_extents_mm": (np.ptp(canonical, axis=0)*1000).tolist(),
                  "canonical_reference_extents_mm": (np.ptp(vertices, axis=0)*1000).tolist(),
                  "raw_partial_to_reference_mean_mm": float(distances.mean()),
                  "raw_partial_to_reference_median_mm": float(np.median(distances)),
                  "raw_partial_to_reference_p95_mm": float(np.quantile(distances, .95)),
                  "alignment_policy": "provided pose only, as official loader; no ICP or direction search",
                  "download_manifest_sha256": sha256(args.data/"download_manifest.json")}
        report["objects"].append(record)
        write_json(args.out/"audit.json", report)
        print(split, pid, "points",len(canonical),"median/p95 raw overlap mm",record["raw_partial_to_reference_median_mm"],record["raw_partial_to_reference_p95_mm"],flush=True)
