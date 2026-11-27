"""Frozen center-weight replay, one-click SAM 2 tracking, and paired scoring."""

import argparse
from collections import defaultdict
from contextlib import ExitStack
import csv
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import sys
import time
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
from scipy.spatial import ConvexHull, QhullError

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
sys.path.insert(0, str(ROOT / "src"))
from potato3d.calibration import depth_points, intrinsics_from_json

PREVIOUS = STUDY.parent / "multiframe_weight_correction_v1"
DATA = ROOT / "data/raw/3DPotatoTwin"
INTRINSICS = DATA / "1_rgbd/0_camera_intrinsics/realsense_d405_camera_intrinsic.json"
ASSETS = ROOT / "outputs/sam2_center_weight_v1/assets"
CHECKPOINT = ASSETS / "sam2.1_hiera_tiny.pt"
CHECKPOINT_HASH = "7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"
SOURCE_COMMIT = "2b90b9f5ceec907a1c18123530e92e794ad901a4"
CONFIG = "configs/sam2.1/sam2.1_hiera_t.yaml"
SEED = 5272401
BOOTSTRAPS = 10_000
TIE = 1e-9
N_TUBERS = 40
THREADS = 6
MODEL_A = (11.134798597815616, 0.7656776613331925)


def hash_file(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def read_csv(path):
    with path.open(newline="") as file:
        return list(csv.DictReader(file))


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def write_csv(path, rows):
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def rgba_image(archive, entry):
    with Image.open(io.BytesIO(archive.read(entry))) as image:
        if image.mode != "RGBA":
            raise ValueError(f"{entry} must be RGBA")
        return np.array(image)


def center_inputs(archive, frame):
    center = frame["frames"][-1]
    rgb = archive.getinfo(center["rgb_member"])
    depth_entry = archive.getinfo(frame["center_depth_member"])
    if f"{rgb.CRC:08x}" != center["crc32"] or f"{depth_entry.CRC:08x}" != frame["center_depth_crc32"]:
        raise ValueError(f"Frozen RGB-D input changed: {frame['tuber']}")
    image = rgba_image(archive, rgb)
    with Image.open(io.BytesIO(archive.read(depth_entry))) as source:
        depth = np.array(source)
    if depth.dtype != np.uint16 or depth.shape != image.shape[:2]:
        raise ValueError(f"Invalid raw depth for {frame['tuber']}")
    return image, depth


def archived_validation():
    rows = read_csv(PREVIOUS / "predictions.csv")
    if len(rows) != N_TUBERS or len({r["tuber"] for r in rows}) != N_TUBERS:
        raise ValueError("Expected exactly 40 unique archived validation IDs")
    if {row["split"] for row in rows} != {"val"}:
        raise ValueError("The roster must contain validation IDs only")
    return rows


def thicknesses(ids):
    path = DATA / "3_pair/ground_truth.csv"
    rows = [row for row in read_csv(path) if row["label"] in ids]
    thickness = {row["label"]: float(row["x3_depth_mm"]) for row in rows}
    if len(rows) != N_TUBERS or set(thickness) != ids or not all(
        np.isfinite(x) and x > 0 for x in thickness.values()
    ):
        raise ValueError("Missing or ambiguous measured thickness")
    return thickness


def freeze(output):
    archived = archived_validation()
    ids = {row["tuber"] for row in archived}
    by_tuber = defaultdict(dict)
    with ExitStack() as stack:
        archives = {}
        for path in sorted((DATA / "1_rgbd/1_images").glob("*.zip")):
            zip_file = stack.enter_context(ZipFile(path))
            archives[path.name] = zip_file
            for entry in zip_file.infolist():
                name = Path(entry.filename)
                tuber = name.parent.name
                if tuber not in ids:
                    continue
                match = re.fullmatch(re.escape(tuber) + r"_rgb_(\d+)\.png", name.name)
                if match:
                    suffix = int(match[1])
                    if suffix in by_tuber[tuber]:
                        raise ValueError(f"Duplicate RGB frame for {tuber} / {suffix}")
                    by_tuber[tuber][suffix] = (path.name, entry)

        roster = []
        for row in archived:
            tuber = row["tuber"]
            center = int(row["center_suffix_px"])
            sequence = sorted(by_tuber[tuber].items())
            if center not in by_tuber[tuber]:
                raise ValueError(f"Missing archived center frame for {tuber}")
            frames = [(suffix, entry) for suffix, entry in sequence if suffix <= center]
            zip_name = frames[0][1][0]
            if len({archive for _, (archive, _) in frames}) != 1 or len(frames) < 2:
                raise ValueError(f"Invalid RGB sequence for {tuber}")
            archive = archives[zip_name]
            depth = archive.getinfo(frames[-1][1][1].filename.replace("_rgb_", "_depth_"))
            entry_alpha = rgba_image(archive, frames[0][1][1])[:, :, 3] > 0
            interior = distance_transform_edt(entry_alpha)
            y, x = np.unravel_index(interior.argmax(), interior.shape)
            if not entry_alpha[y, x]:
                raise ValueError(f"No foreground for entry prompt: {tuber}")
            roster.append({
                "tuber": tuber, "archive": zip_name, "entry_suffix_px": frames[0][0],
                "center_suffix_px": center, "click_xy": [int(x), int(y)],
                "click_clearance_px": float(interior[y, x]),
                "center_depth_member": depth.filename, "center_depth_crc32": f"{depth.CRC:08x}",
                "frames": [
                    {"suffix_px": suffix, "rgb_member": item.filename, "crc32": f"{item.CRC:08x}"}
                    for suffix, (_, item) in frames
                ],
            })
    coefficients = read_json(PREVIOUS / "train_fit.json")["models"]["A"]
    if (coefficients["intercept_g"], coefficients["center_proxy_cm3_coefficient_g_per_cm3"]) != MODEL_A:
        raise ValueError("Model A coefficients changed")
    manifest = {
        "protocol_sha256": hash_file(STUDY / "protocol.md"),
        "archived_validation_csv_sha256": hash_file(PREVIOUS / "predictions.csv"),
        "archived_fit_sha256": hash_file(PREVIOUS / "train_fit.json"),
        "intrinsics_sha256": hash_file(INTRINSICS), "checkpoint_sha256": CHECKPOINT_HASH,
        "source_commit": SOURCE_COMMIT, "config": CONFIG, "roster": roster,
    }
    path = output / "frame_manifest.json"
    if path.exists() and read_json(path) != manifest:
        raise ValueError("Frozen manifest changed. Use a new output directory.")
    write_json(path, manifest)
    print(f"Frozen {len(roster)} potatoes and {sum(len(r['frames']) for r in roster)} RGB frames.", flush=True)


def load_manifest(output):
    manifest = read_json(output / "frame_manifest.json")
    for field, source in [
        ("protocol_sha256", STUDY / "protocol.md"),
        ("archived_validation_csv_sha256", PREVIOUS / "predictions.csv"),
        ("archived_fit_sha256", PREVIOUS / "train_fit.json"),
        ("intrinsics_sha256", INTRINSICS),
    ]:
        if manifest[field] != hash_file(source):
            raise ValueError(f"Frozen input changed: {source}")
    archived = [(r["tuber"], int(r["center_suffix_px"])) for r in archived_validation()]
    if [(r["tuber"], r["center_suffix_px"]) for r in manifest["roster"]] != archived:
        raise ValueError("Manifest does not replay the frozen validation roster")
    return manifest


def valid_depth(depth):
    return (depth > 0) & (depth < 400)


def release_depth_bounds(depth, mask, thickness_mm):
    """Port histogram_filtering in the release's 1_rgbd/pin_regions.py."""
    z = depth[mask & (depth > 0)]
    if len(z) < 2:
        return 0., 0.
    if float(z.max() - z.min()) > thickness_mm:
        count, edges = np.histogram(z)
        peak_bin = int(count.argmax())
        lo, hi = map(int, edges[peak_bin:peak_bin + 2])
        by_depth = np.bincount(z.astype(np.int64))
        peak = int(by_depth.argmax())
        if not lo < peak < hi:
            peak = lo + int(by_depth[lo:hi].argmax())
        candidates = []
        for shift in range(0, 100, 10):
            lower = peak - (thickness_mm - shift)
            candidates.append(z[(z >= lower) & (z <= lower + thickness_mm)])
        z = max(candidates, key=len)
    count, edges = np.histogram(z)
    bins = np.flatnonzero(count / count.sum() >= 0.02)
    return float(edges[bins[0]]), float(edges[bins[-1] + 1])


def filtered_support(depth, mask, thickness):
    lo, hi = release_depth_bounds(depth, mask, thickness)
    return mask & valid_depth(depth) & (depth >= lo) & (depth <= hi), (lo, hi)


def describe_support(depth, mask, matrix):
    y, x = np.nonzero(mask)
    if len(x) < 3:
        raise ValueError("Fewer than three accepted depth points")
    pixels = np.column_stack([x, y])
    points = depth_points(depth, pixels, matrix)
    hull = ConvexHull(points[:, :2])
    height = max(0., 350. - float(np.quantile(points[:, 2], 0.05)))
    proxy = hull.volume * height / 1000.
    return {
        "area_mm2": float(hull.volume), "height_mm": height, "proxy_cm3": proxy,
        "predicted_g": float(MODEL_A[0] + MODEL_A[1] * proxy), "depth_pixels": len(x),
    }, pixels[hull.vertices]


def relative_to_archive(row, geometry):
    return {
        key: geometry[key] - float(row[column]) for key, column in [
            ("area_mm2", "center_area_mm2"), ("height_mm", "center_height_mm"),
            ("proxy_cm3", "center_proxy_cm3"), ("predicted_g", "A_predicted_g"),
        ]
    }


def archive_reprojection(ply_archive, frame, depth, intrinsic):
    import trimesh

    tuber, suffix = frame["tuber"], frame["center_suffix_px"]
    key = f"2_pcd/{tuber}/{tuber}_pcd_{suffix}.ply"
    cloud = trimesh.load(io.BytesIO(ply_archive.read(key)), file_type="ply", process=False)
    archived = np.asarray(cloud.vertices, dtype=float) * 1000.
    projection = archived @ intrinsic.T
    pixels = np.rint(projection[:, :2] / projection[:, 2:]).astype(int)
    x, y = pixels.T
    if np.any((x < 0) | (x >= depth.shape[1]) | (y < 0) | (y >= depth.shape[0])):
        raise ValueError(f"Archived points project outside the center frame: {tuber}")
    support = np.zeros(depth.shape, dtype=bool)
    support[y, x] = True
    if support.sum() != len(archived):
        raise ValueError(f"Archived cloud has duplicate projected pixels: {tuber}")
    reconstructed = depth_points(depth, pixels, intrinsic)
    difference = float(np.max(np.linalg.norm(archived - reconstructed, axis=1)))
    return support, difference


def flatten(prefix, values):
    return {f"{prefix}_{key}": value for key, value in values.items()}


def abs_summary(values):
    values = np.abs(values)
    return {"median": float(np.median(values)), "max": float(np.max(values))}


def baseline(output):
    manifest = load_manifest(output)
    matrix = intrinsics_from_json(read_json(INTRINSICS))
    archival_rows = {row["tuber"]: row for row in archived_validation()}
    thickness = thicknesses(set(archival_rows))
    rows = []
    with ExitStack() as stack:
        pcd = stack.enter_context(ZipFile(DATA / "1_rgbd/2_pcd.zip"))
        archives = open_image_archives(stack, manifest)
        for frame in manifest["roster"]:
            tuber = frame["tuber"]
            image, depth = center_inputs(archives[frame["archive"]], frame)
            alpha = image[:, :, 3] > 0
            raw_support = alpha & valid_depth(depth)
            release_support, (lo, hi) = filtered_support(depth, alpha, thickness[tuber])
            archived_support, xyz_difference = archive_reprojection(pcd, frame, depth, matrix)
            raw, _ = describe_support(depth, raw_support, matrix)
            provided, _ = describe_support(depth, release_support, matrix)
            archived = archival_rows[tuber]
            rows.append({
                "tuber": tuber, "center_suffix_px": frame["center_suffix_px"],
                "thickness_mm": thickness[tuber], "depth_lo_mm": lo, "depth_hi_mm": hi,
                "raw_minus_archive_pixels": int(np.count_nonzero(raw_support & ~archived_support)),
                "archive_minus_raw_pixels": int(np.count_nonzero(archived_support & ~raw_support)),
                "release_archive_xor_pixels": int(np.count_nonzero(release_support ^ archived_support)),
                "archive_xyz_max_difference_mm": xyz_difference,
                "archived_area_mm2": float(archived["center_area_mm2"]),
                "archived_height_mm": float(archived["center_height_mm"]),
                "archived_proxy_cm3": float(archived["center_proxy_cm3"]),
                "archived_predicted_g": float(archived["A_predicted_g"]),
                "nonzero_scene_pixels_outside_alpha": int(np.count_nonzero(
                    np.any(image[:, :, :3] > 0, axis=2) & ~alpha
                )),
                **flatten("unfiltered", raw), **flatten("provided", provided),
                **flatten("unfiltered_minus_archived", relative_to_archive(archived, raw)),
                **flatten("provided_minus_archived", relative_to_archive(archived, provided)),
            })
    summary = {
        "tubers": len(rows),
        "exact_pixel_replay": sum(row["release_archive_xor_pixels"] == 0 for row in rows),
        "max_xyz_difference_mm": max(row["archive_xyz_max_difference_mm"] for row in rows),
        "raw_extra_pixels": int(sum(row["raw_minus_archive_pixels"] for row in rows)),
    }
    for mode in ("unfiltered", "provided"):
        summary[f"{mode}_absolute_replay_discrepancy"] = {
            key: abs_summary([row[f"{mode}_minus_archived_{key}"] for row in rows])
            for key in ("area_mm2", "height_mm", "proxy_cm3", "predicted_g")
        }
    summary["passed"] = (
        summary["exact_pixel_replay"] == N_TUBERS and summary["max_xyz_difference_mm"] <= 0.0001
        and summary["provided_absolute_replay_discrepancy"]["predicted_g"]["max"] <= 0.001
    )
    write_csv(output / "baseline_replay.csv", rows)
    write_json(output / "baseline_replay.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    if not summary["passed"]:
        raise RuntimeError("Center pipeline replay failed")


def open_image_archives(stack, manifest):
    return {
        name: stack.enter_context(ZipFile(DATA / "1_rgbd/1_images" / name))
        for name in sorted({r["archive"] for r in manifest["roster"]})
    }


def build_cpu_predictor():
    import torch

    if hash_file(CHECKPOINT) != CHECKPOINT_HASH:
        raise ValueError("Unexpected SAM 2 checkpoint digest")

    sys.path[:0] = [str(ASSETS / "sam2-main"), str(ASSETS / "deps")]
    from sam2.build_sam import build_sam2_video_predictor

    torch.set_num_threads(THREADS)
    torch.set_num_interop_threads(1)
    torch.manual_seed(133)
    build_start = time.perf_counter()
    predictor = build_sam2_video_predictor(
        CONFIG, str(CHECKPOINT), device="cpu", apply_postprocessing=False
    )
    print(f"SAM 2 predictor loaded in {time.perf_counter() - build_start:.2f} s", flush=True)

    return predictor


def predict_track(predictor, archive, frame, observer=None):
    """Run the frozen tracker, optionally observing initial and propagated masks."""
    import torch
    from sam2 import sam2_video_predictor
    from sam2.utils.misc import _load_img_as_tensor

    members = frame["frames"]

    def png_loader(video_path, image_size, offload_video_to_cpu,
                   img_mean=(0.485, 0.456, 0.406), img_std=(0.229, 0.224, 0.225),
                   async_loading_frames=False, compute_device=None):
        if video_path != frame["tuber"] or not offload_video_to_cpu or async_loading_frames:
            raise ValueError("Unexpected PNG adapter arguments")
        images = torch.empty((len(members), 3, image_size, image_size), dtype=torch.float32)
        original_size = None
        for i, item in enumerate(members):
            member = archive.getinfo(item["rgb_member"])
            if f"{member.CRC:08x}" != item["crc32"]:
                raise ValueError(f"RGB member changed: {member.filename}")
            loaded, height, width = _load_img_as_tensor(io.BytesIO(archive.read(member)), image_size)
            if original_size is not None and original_size != (height, width):
                raise ValueError("Source frame size changed during tracking")
            original_size = (height, width)
            images[i] = loaded
        images -= torch.tensor(img_mean, dtype=torch.float32)[:, None, None]
        images /= torch.tensor(img_std, dtype=torch.float32)[:, None, None]
        return images, *original_size

    with patch.object(sam2_video_predictor, "load_video_frames", png_loader):
        state = predictor.init_state(
            frame["tuber"], offload_video_to_cpu=True, offload_state_to_cpu=True
        )
    x, y = frame["click_xy"]
    _, _, entry_logits = predictor.add_new_points_or_box(
        state, frame_idx=0, obj_id=1, points=[[x, y]], labels=[1]
    )
    click_inside = bool(entry_logits[0, 0, y, x] > 0)
    if observer is not None:
        observer(0, "prompt", (entry_logits[0, 0] > 0).numpy())
    empty = []
    center = None
    for index, ids, logits in predictor.propagate_in_video(state, start_frame_idx=0):
        if ids != [1] or not bool(torch.isfinite(logits).all()):
            raise ValueError(f"Unexpected object IDs or logits on index {index}")
        mask = (logits[0, 0] > 0).numpy()
        if observer is not None:
            observer(index, "propagation", mask)
        if not mask.any():
            empty.append(members[index]["suffix_px"])
        if index == len(members) - 1:
            center = mask
    if center is None:
        raise ValueError("Propagation did not yield the frozen center")
    return center, click_inside, empty


def track(output):
    import torch

    manifest = load_manifest(output)
    if not read_json(output / "baseline_replay.json")["passed"]:
        raise RuntimeError("A passing baseline replay is required")
    mask_dir = output / "center_masks"
    mask_dir.mkdir(exist_ok=True)
    hash_manifest = hash_file(output / "frame_manifest.json")
    run_info = {
        "manifest_sha256": hash_manifest, "checkpoint_sha256": CHECKPOINT_HASH,
        "source_commit": SOURCE_COMMIT, "config": CONFIG, "device": "cpu", "precision": "fp32",
        "torch": torch.__version__, "python": platform.python_version(),
        "host_machine": platform.machine(),
        "host_os": platform.platform(), "threads": THREADS, "interop_threads": 1,
        "optional_postprocessing": False,
    }
    info_path = output / "tracking_config.json"
    if info_path.exists() and read_json(info_path) != run_info:
        raise ValueError("A different frozen tracking configuration already ran here")
    write_json(info_path, run_info)

    predictor = build_cpu_predictor()
    rows = []
    with ExitStack() as stack, torch.inference_mode():
        archives = open_image_archives(stack, manifest)
        for index, frame in enumerate(manifest["roster"], 1):
            tuber = frame["tuber"]
            stamp = mask_dir / f"{tuber}.json"
            filename = mask_dir / f"{tuber}.png"
            if stamp.exists():
                row = read_json(stamp)
                if row["mask_sha256"] is not None and hash_file(filename) != row["mask_sha256"]:
                    raise ValueError(f"Saved mask changed: {tuber}")
                rows.append(row)
                continue
            start, cpu_start = time.perf_counter(), time.process_time()
            row = {
                "tuber": tuber, "entry_suffix_px": frame["entry_suffix_px"],
                "center_suffix_px": frame["center_suffix_px"], "rgb_frames": len(frame["frames"]),
                "click_x": frame["click_xy"][0], "click_y": frame["click_xy"][1],
                "click_clearance_px": frame["click_clearance_px"],
                "entry_prediction_includes_click": None, "empty_mask_suffixes_px": None,
                "status": "failure", "error": "", "mask_sha256": None, "mask_pixels": None,
            }
            try:
                mask, click_inside, empty = predict_track(predictor, archives[frame["archive"]], frame)
                Image.fromarray(mask.astype(np.uint8) * 255).save(filename)
                row.update({
                    "entry_prediction_includes_click": click_inside,
                    "empty_mask_suffixes_px": empty, "mask_sha256": hash_file(filename),
                    "mask_pixels": int(mask.sum()),
                })
                if mask.any():
                    row["status"] = "tracked"
                else:
                    row["error"] = "Empty center mask"
            except (ValueError, RuntimeError) as error:
                row["error"] = f"{type(error).__name__}: {error}"
            row["wall_seconds"] = time.perf_counter() - start
            row["process_cpu_seconds"] = time.process_time() - cpu_start
            write_json(stamp, row)
            rows.append(row)
            print(f"{index}/{N_TUBERS} {tuber}: {row['status']} in {row['wall_seconds']:.1f} s {row['error']}",
                  flush=True)
    write_json(output / "tracking.json", rows)


def iou(left, right):
    union = np.count_nonzero(left | right)
    return float(np.count_nonzero(left & right) / union) if union else None


def depth_stats(depth, support):
    values = depth[support]
    result = {"pixels": len(values)}
    if len(values):
        result.update({
            "depth_min_mm": int(values.min()), "depth_median_mm": float(np.median(values)),
            "depth_max_mm": int(values.max()),
        })
    return result


def build_case(image, provided, predicted, original_support, tracked_support,
               original_hull, tracked_hull):
    y, x = np.nonzero(provided | predicted)
    left, top = max(0, int(x.min()) - 20), max(0, int(y.min()) - 20)
    right = min(image.shape[1], int(x.max()) + 21)
    bottom = min(image.shape[0], int(y.max()) + 21)
    window = np.s_[top:bottom, left:right]
    return {
        "image": image[window][:, :, :3], "provided": provided[window],
        "predicted": predicted[window], "original_support": original_support[window],
        "tracked_support": tracked_support[window],
        "original_hull": original_hull - [left, top], "tracked_hull": tracked_hull - [left, top],
    }


def render_cases(output, cases, rows):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.patches import Patch

    ordered = sorted(rows, key=lambda row: (-abs(row["predicted_weight_change_g"]), row["tuber"]))[:3]
    if not ordered:
        return
    gold, blue = np.array([1., .59, .17]), np.array([.17, .78, .97])
    fig, axes = plt.subplots(len(ordered), 3, squeeze=False, figsize=(10.4, 3.25 * len(ordered)))
    for index, row in enumerate(ordered):
        case = cases[row["tuber"]]
        image = case["image"].astype(float) / 255.
        raw = case["provided"], case["predicted"]
        support = case["original_support"], case["tracked_support"]
        captions = [
            f"{row['tuber']} · center {row['center_suffix_px']}\n"
            f"{row['provided_predicted_g']:.1f} → {row['sam2_predicted_g']:.1f} g",
            f"Raw mask changes\nIoU {row['mask_iou']:.3f}",
            f"Accepted depth + XY hull vertices\nError change {row['sam2_minus_provided_abs_error_g']:+.1f} g",
        ]
        for col, ax in enumerate(axes[index]):
            overlay = image.copy()
            if col:
                first, second = raw if col == 1 else support
                lost, added = first & ~second, second & ~first
                overlay[lost] = 0.27 * image[lost] + 0.73 * blue
                overlay[added] = 0.27 * image[added] + 0.73 * gold
            ax.imshow(overlay)
            if col == 0:
                ax.contour(raw[0], levels=[0.5], colors=[blue], linewidths=0.8)
                ax.contour(raw[1], levels=[0.5], colors=[gold], linewidths=0.8)
            if col == 2:
                for hull, keep, other, color in [
                    (case["original_hull"], support[0], support[1], blue),
                    (case["tracked_hull"], support[1], support[0], gold),
                ]:
                    x, y = hull.T
                    unique = (keep & ~other)[y, x]
                    ax.scatter(x[unique], y[unique], s=15, color=color,
                               edgecolors="black", linewidths=.35, zorder=3)
            ax.set_title(captions[col], fontsize=10, loc="left")
            ax.set_axis_off()
    fig.legend(handles=[Patch(color=blue, label="Provided mask / provided only"),
                        Patch(color=gold, label="SAM 2 mask / SAM 2 only")],
               loc="lower center", ncol=2, frameon=False)
    fig.tight_layout(rect=(0, .045, 1, 1))
    fig.savefig(output / "largest_weight_changes.png", dpi=180)
    plt.close(fig)


def score(output):
    manifest = load_manifest(output)
    replay = read_json(output / "baseline_replay.json")
    if not replay["passed"]:
        raise ValueError("No passing baseline replay")
    config = read_json(output / "tracking_config.json")
    if config["manifest_sha256"] != hash_file(output / "frame_manifest.json"):
        raise ValueError("Tracking manifest mismatch")
    tracking_rows = read_json(output / "tracking.json")
    if [row["tuber"] for row in tracking_rows] != [r["tuber"] for r in manifest["roster"]]:
        raise ValueError("Tracking output does not cover the frozen roster")
    archived = {row["tuber"]: row for row in archived_validation()}
    if not all(np.isfinite(float(row["measured_g"])) and float(row["measured_g"]) > 0
               for row in archived.values()):
        raise ValueError("Invalid archived measured weight")
    baseline_rows = {row["tuber"]: row for row in read_csv(output / "baseline_replay.csv")}
    matrix = intrinsics_from_json(read_json(INTRINSICS))
    thickness = thicknesses(set(archived))
    rows, cases = [], {}
    with ExitStack() as stack:
        archives = open_image_archives(stack, manifest)
        for frame, tracked in zip(manifest["roster"], tracking_rows, strict=True):
            tuber = frame["tuber"]
            image, depth = center_inputs(archives[frame["archive"]], frame)
            alpha = image[:, :, 3] > 0
            original_support, _ = filtered_support(depth, alpha, thickness[tuber])
            original, original_hull = describe_support(depth, original_support, matrix)
            audit = baseline_rows[tuber]
            if (thickness[tuber] != float(audit["thickness_mm"])
                    or original["predicted_g"] != float(audit["provided_predicted_g"])):
                raise ValueError(f"Provided-mask pipeline changed after replay: {tuber}")
            measured = float(archived[tuber]["measured_g"])
            provided_error = abs(original["predicted_g"] - measured)
            row = {
                "tuber": tuber, "entry_suffix_px": frame["entry_suffix_px"],
                "center_suffix_px": frame["center_suffix_px"], "rgb_frames": tracked["rgb_frames"],
                "click_x": tracked["click_x"], "click_y": tracked["click_y"],
                "measured_g": measured, "thickness_mm": thickness[tuber],
                "archived_predicted_g": float(audit["archived_predicted_g"]),
                **flatten("provided", original), "provided_abs_error_g": provided_error,
                "provided_depth_lo_mm": float(audit["depth_lo_mm"]),
                "provided_depth_hi_mm": float(audit["depth_hi_mm"]),
                "tracking_status": tracked["status"],
                "scoring_status": "unscorable", "failure": tracked["error"],
                "tracking_wall_s": tracked["wall_seconds"],
                "tracking_process_cpu_s": tracked["process_cpu_seconds"],
                "center_mask_sha256": tracked["mask_sha256"],
            }
            rows.append(row)
            if tracked["mask_sha256"] is None:
                continue
            mask_path = output / "center_masks" / f"{tuber}.png"
            if hash_file(mask_path) != tracked["mask_sha256"]:
                raise ValueError(f"Center mask changed after tracking: {tuber}")
            with Image.open(mask_path) as source:
                mask = np.array(source) > 0
            if mask.shape != alpha.shape or int(mask.sum()) != tracked["mask_pixels"]:
                raise ValueError(f"Invalid saved center mask: {tuber}")
            row.update({
                "mask_iou": iou(alpha, mask), "provided_mask_pixels": int(alpha.sum()),
                "sam2_mask_pixels": int(mask.sum()), "provided_only_mask_pixels": int((alpha & ~mask).sum()),
                "sam2_only_mask_pixels": int((mask & ~alpha).sum()),
            })
            if tracked["status"] != "tracked":
                continue
            tracked_support, (lo, hi) = filtered_support(depth, mask, thickness[tuber])
            lost, added = original_support & ~tracked_support, tracked_support & ~original_support
            row.update({
                "depth_support_iou": iou(original_support, tracked_support),
                "sam2_depth_lo_mm": lo, "sam2_depth_hi_mm": hi,
                **flatten("provided_only_accepted", depth_stats(depth, lost)),
                **flatten("sam2_only_accepted", depth_stats(depth, added)),
                "accepted_added_outside_provided_mask": int(np.count_nonzero(added & ~alpha)),
                "accepted_added_inside_provided_mask": int(np.count_nonzero(added & alpha)),
                "accepted_lost_outside_sam2_mask": int(np.count_nonzero(lost & ~mask)),
                "accepted_lost_inside_sam2_mask": int(np.count_nonzero(lost & mask)),
            })
            try:
                estimated, sam_hull = describe_support(depth, tracked_support, matrix)
            except (ValueError, QhullError) as error:
                row["failure"] = f"{type(error).__name__}: {str(error).splitlines()[0]}"
                continue
            err = abs(estimated["predicted_g"] - measured)
            row.update({
                **flatten("sam2", estimated),
                "sam2_abs_error_g": err, "sam2_minus_provided_abs_error_g": err - provided_error,
                "predicted_weight_change_g": estimated["predicted_g"] - original["predicted_g"],
                "area_change_mm2": estimated["area_mm2"] - original["area_mm2"],
                "height_change_mm": estimated["height_mm"] - original["height_mm"],
                "provided_only_accepted_hull_vertices": int(lost[original_hull[:, 1], original_hull[:, 0]].sum()),
                "sam2_only_accepted_hull_vertices": int(added[sam_hull[:, 1], sam_hull[:, 0]].sum()),
                "scoring_status": "scorable",
            })
            try:
                overlap, _ = describe_support(depth, original_support & tracked_support, matrix)
                row.update({
                    "shared_support_predicted_g": overlap["predicted_g"],
                    "removed_support_step_g": overlap["predicted_g"] - original["predicted_g"],
                    "added_support_step_g": estimated["predicted_g"] - overlap["predicted_g"],
                })
            except (ValueError, QhullError):
                row["shared_support_predicted_g"] = None
            cases[tuber] = build_case(
                image, alpha, mask, original_support, tracked_support, original_hull, sam_hull
            )

    paired = [r for r in rows if r["scoring_status"] == "scorable"]
    failures = [{"tuber": r["tuber"], "reason": r["failure"]} for r in rows if r not in paired]
    ious = [r["mask_iou"] for r in rows if r.get("mask_iou") is not None]
    stats = {
        "roster": len(rows), "tracked": sum(row["status"] == "tracked" for row in tracking_rows),
        "scorable_pairs": len(paired), "failed_pairs": failures,
        "provided_mae_all_g": float(np.mean([r["provided_abs_error_g"] for r in rows])),
        "mask_iou": {
            "n": len(ious), "mean": float(np.mean(ious)), "median": float(np.median(ious)),
            "min": float(np.min(ious)), "max": float(np.max(ious)),
            "zero": int(np.count_nonzero(np.asarray(ious) == 0.)),
        } if ious else None,
        "tracking_total_wall_seconds_excl_model_load": sum(r["wall_seconds"] for r in tracking_rows),
        "tracking_total_process_cpu_seconds_excl_model_load": sum(r["process_cpu_seconds"] for r in tracking_rows),
        "tracking_wall_seconds_per_tuber_median": float(np.median([r["wall_seconds"] for r in tracking_rows])),
        "tracking_rgb_frames": sum(r["rgb_frames"] for r in tracking_rows),
        "entry_predictions_missed_click": [r["tuber"] for r in tracking_rows
                                            if r["entry_prediction_includes_click"] is False],
        "intermediate_empty_masks": {r["tuber"]: r["empty_mask_suffixes_px"] for r in tracking_rows
                                     if r["empty_mask_suffixes_px"]},
    }
    if paired:
        delta = np.asarray([r["sam2_minus_provided_abs_error_g"] for r in paired])
        bootstrap_indices = np.random.default_rng(SEED).integers(len(delta), size=(BOOTSTRAPS, len(delta)))
        stats.update({
            "provided_mae_paired_g": float(np.mean([r["provided_abs_error_g"] for r in paired])),
            "sam2_mae_paired_g": float(np.mean([r["sam2_abs_error_g"] for r in paired])),
            "mean_paired_change_g": float(delta.mean()), "median_paired_change_g": float(np.median(delta)),
            "interval_95_g": np.quantile(delta[bootstrap_indices].mean(axis=1), [.025, .975]).tolist(),
            "improved": int(np.count_nonzero(delta < -TIE)),
            "tied": int(np.count_nonzero(np.abs(delta) <= TIE)),
            "worsened": int(np.count_nonzero(delta > TIE)),
            "largest_predicted_weight_changes": [
                r["tuber"] for r in sorted(
                    paired, key=lambda row: (-abs(row["predicted_weight_change_g"]), row["tuber"])
                )[:3]
            ],
        })
    write_csv(output / "per_potato.csv", rows)
    write_json(output / "results.json", stats)
    render_cases(output, cases, paired)
    print(json.dumps(stats, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["freeze", "baseline", "track", "score"])
    parser.add_argument("--output", type=Path, default=STUDY)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    globals()[args.stage](args.output)


if __name__ == "__main__":
    main()
