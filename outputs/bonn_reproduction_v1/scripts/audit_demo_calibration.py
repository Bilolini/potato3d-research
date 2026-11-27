"""Check depth/PLY consistency and reference-free background-plane proxies."""
import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path.cwd()/".cache"/"matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from potato3d.calibration import audit_background, intrinsics_from_json, verify_ply_depth
from potato3d.io import discover_demo, load_points, sha256, write_json
from potato3d.pipeline import environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/raw/3DPotatoTwinDemo"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    intrinsic_path = args.data/"1_rgbd/0_camera_intrinsics/realsense_d405_camera_intrinsic.json"
    matrix = intrinsics_from_json(json.loads(intrinsic_path.read_text()))
    report = {"source": str(args.data), "intrinsic_sha256": sha256(intrinsic_path),
              "calibration_source_sha256": sha256(Path(__file__).resolve()), "objects": []}
    for record in discover_demo(args.data):
        pid, frame = record["object_id"], record["frame_id"]
        image_root = args.data/"1_rgbd/1_image"/pid
        depth_path, rgb_path = image_root/f"{pid}_depth_{frame}.png", image_root/f"{pid}_rgb_{frame}.png"
        with Image.open(depth_path) as im:
            depth = np.array(im)
        with Image.open(rgb_path) as im:
            rgba = np.array(im)
        points = load_points(args.data/record["partial"], "m")
        consistency = verify_ply_depth(points, depth, rgba[:, :, 3], matrix)
        proxy, pixels, inliers = audit_background(depth, rgba[:, :, 3], matrix)
        report["objects"].append({"object_id": pid, "frame_id": frame, "depth_sha256": sha256(depth_path),
                                  "rgb_sha256": sha256(rgb_path), "partial_sha256": record["partial_sha256"],
                                  "ply_depth_consistency": consistency, "background_plane_proxy": proxy})
        fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
        axes[0].imshow(depth, vmin=275, vmax=390, cmap="viridis")
        axes[0].set_title("Raw depth (color range 275–390 mm)")
        axes[1].imshow(rgba[:, :, :3])
        selected = pixels[inliers]
        axes[1].scatter(selected[:, 0], selected[:, 1], s=.5, color="#37e6d0", alpha=.6)
        axes[1].set_title("Near-plane background candidates; no GT")
        for ax in axes:
            ax.set_axis_off()
        fig.suptitle(f"{pid}: plane proxy only, intercept {proxy['camera_axis_intercept_mm']:.2f} mm")
        fig.savefig(args.out/f"{pid}_background.png", dpi=140)
        plt.close(fig)
        print(pid, f"intercept={proxy['camera_axis_intercept_mm']:.3f} mm",
              f"tilt={proxy['tilt_deg']:.2f} deg", f"heldout support={proxy['heldout_inlier_fraction_at_1p5mm']:.1%}", flush=True)
        write_json(args.out/"audit.json", report)
    write_json(args.out/"environment.json", environment())


if __name__ == "__main__":
    main()
