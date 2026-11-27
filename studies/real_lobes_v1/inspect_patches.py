"""Generate aligned RGB, raw-depth and registered SfM inspection panels."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree

from audit import reference_heights
from potato3d.geometry import camera_to_belt_mm, transform_points
from potato3d.io import discover_demo, load_demo_pair, write_json


def project(points, intrinsics):
    homogeneous = points @ intrinsics.T
    return homogeneous[:, :2] / homogeneous[:, 2:]


def inspect(root, pilot, out):
    path = root / "1_rgbd/0_camera_intrinsics/realsense_d405_camera_intrinsic.json"
    camera = json.loads(path.read_text())
    intrinsics = np.array(camera["intrinsic_matrix"]).reshape((3, 3), order="F")
    to_camera = np.linalg.inv(camera_to_belt_mm(350))
    registered = {r["object_id"]: r for r in discover_demo(root)}
    rows = []
    for pair in pilot["pairs"]:
        obj, frame = pair["object_id"], pair["frame_id"]
        record = registered[obj]
        if frame != record["frame_id"]:
            raise ValueError(f"Registration frame mismatch for {obj}")
        folder = root / "1_rgbd/1_image" / obj
        rgba = np.asarray(Image.open(folder / f"{obj}_rgb_{frame}.png"))
        raw = np.asarray(Image.open(folder / f"{obj}_depth_{frame}.png"))
        points, mesh, _ = load_demo_pair(root, record, belt_depth_mm=350)
        camera_points = transform_points(points, to_camera)
        pixels = np.rint(project(camera_points, intrinsics)).astype(int)
        x, y = pixels.T
        if raw.shape != (camera["height"], camera["width"]) or rgba.shape != (*raw.shape, 4):
            raise ValueError(f"Raster geometry differs from intrinsics for {obj}")
        if not ((0 <= x).all() and (x < raw.shape[1]).all()
                and (0 <= y).all() and (y < raw.shape[0]).all()):
            raise ValueError(f"Point projects outside raster for {obj}")
        error = np.abs(raw[y, x] - camera_points[:, 2])
        in_mask = (rgba[y, x, 3] > 0).mean()
        if error.max() > .01 or in_mask < .99:
            raise ValueError(f"Scan and raster fail round-trip for {obj}")
        summary = {"object_id": obj, "frame_id": frame, "points": len(points),
                   "inside_rgb_mask_fraction": in_mask, "depth_error_max_mm": error.max(),
                   "patches": []}
        rows.append(summary)
        if not pair["detections"]:
            continue

        fig, axes = plt.subplots(len(pair["detections"]), 4, squeeze=False,
                                 figsize=(12, 2.3*len(pair["detections"])))
        tree = cKDTree(points[:, :2])
        mask_distance = distance_transform_edt(rgba[..., 3] > 0)
        offset = np.arange(-10, 11)
        offsets = np.stack(np.meshgrid(offset, offset), axis=-1).reshape(-1, 2)
        dist = np.linalg.norm(offsets, axis=1)
        band = (dist >= 6) & (dist <= 9)
        for number, (panels, detection) in enumerate(zip(axes, pair["detections"]), start=1):
            candidate = detection["candidate"]
            center = np.asarray(candidate["xy_mm"])
            xyz = points[tree.query(center)[1]]
            px, py = project(transform_points(xyz[None], to_camera), intrinsics)[0]
            ix, iy = np.rint([px, py]).astype(int)
            half = 24
            rgb = rgba[iy-half:iy+half+1, ix-half:ix+half+1]
            depth = raw[iy-half:iy+half+1, ix-half:ix+half+1].astype(float)
            if rgb.shape[:2] != (2*half+1, 2*half+1):
                raise ValueError(f"RGB inspection window crosses raster edge for {obj}")
            valid = (rgb[..., 3] > 0) & (depth > 0)
            depth[~valid] = np.nan
            panels[0].imshow(rgb)
            panels[0].plot(px-ix+half, py-iy+half, "+", color="black", markersize=9, markeredgewidth=2)
            panels[0].plot(px-ix+half, py-iy+half, "+", color="white", markersize=7, markeredgewidth=1)
            panels[0].set_title(f"{number}. RGB at ({ix}, {iy}) px", fontsize=9)

            grid = offsets+center
            distances, neighbors = tree.query(grid, k=5)
            scan = np.median(points[neighbors, 2], axis=1)
            scan[distances[:, -1] > 1.5] = np.nan
            bounds = reference_heights(mesh, grid)[0]
            heights = [scan, bounds[:, 1], -bounds[:, 0]]
            nominal = candidate["reference"]["nominal"]
            values = [candidate["scan_relief_mm"], nominal["top"]["relief_mm"],
                      nominal["underside"]["relief_mm"]]
            # Display deviation from a local quadratic for both surfaces at the
            # same scale. Pilot's robust scalar estimates supply the captions.
            dx, dy = offsets.T/9
            design = np.column_stack([np.ones(len(dx)), dx, dy, dx*dx, dx*dy, dy*dy])
            for ax, z, title, value in zip(panels[1:], heights,
                                            ["RGB-D scan", "SfM top", "SfM underside"], values):
                good = band & np.isfinite(z)
                fit = np.linalg.lstsq(design[good], z[good], rcond=None)[0]
                residual = z-design@fit
                ax.imshow(residual.reshape(21, 21), origin="lower", extent=(-10.5, 10.5, -10.5, 10.5),
                          cmap="coolwarm", vmin=-3, vmax=3, interpolation="nearest")
                for radius, style in [(3, "-"), (6, ":"), (9, ":")]:
                    ax.add_patch(plt.Circle((0, 0), radius, fill=False, color=".2",
                                            linewidth=.8, linestyle=style))
                ax.set_title(f"{title} · pilot relief {value:+.2f} mm", fontsize=9)
            for ax in panels:
                ax.set_axis_off()
            summary["patches"].append({
                "number": number, "xy_mm": center, "projected_pixel_xy": [px, py],
                "rgb_mask_distance_px": mask_distance[iy, ix],
                "scan_hull_distance_mm": candidate["silhouette_distance_mm"],
                "raw_crop_valid_fraction": valid.mean(),
                "raw_crop_depth_mm": [np.nanmin(depth), np.nanmax(depth)],
                "scan_relief_mm": candidate["scan_relief_mm"],
                "reference": candidate["reference"],
                "has_matched_control": detection["control"] is not None,
            })

        fig.suptitle(f"{obj}   Frame {frame}", fontweight="bold")
        fig.text(.5, .012, "Left · original RGB    Right · local height residuals, blue −3 to red +3 mm",
                 ha="center", fontsize=9)
        fig.tight_layout(rect=(0, .028, 1, .97))
        fig.savefig(out / f"{obj}.png", dpi=130)
        plt.close(fig)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/raw/3DPotatoTwinDemo"))
    parser.add_argument("--pilot", type=Path, default=Path(__file__).with_name("demo_pilot.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = inspect(args.root, json.loads(args.pilot.read_text()), args.out)
    write_json(args.out / "projection_audit.json", {"pairs": rows})


if __name__ == "__main__":
    main()
