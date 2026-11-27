"""Freeze, verify and run the pinned monocular model without opening validation outcomes."""

import argparse
from collections import Counter
from contextlib import ExitStack
from hashlib import sha1, sha256
import io
from pathlib import Path
import platform
import time
from types import SimpleNamespace
from zipfile import ZipFile

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation
from scipy.stats import spearmanr
import torch
from transformers import AutoImageProcessor, AutoModelForDepthEstimation, __version__ as transformers_version

from studies.rgb_only_height_value_v1 import run as base
from studies.rgb_predicted_height_v1 import run as learned

prior = base.prior
HERE = Path(__file__).resolve().parent
MODEL_DIR = prior.ROOT / "outputs/rgb_monocular_height_v1/checkpoint"
REPO = "depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf"
REVISION = "d2fc6a93601aabb1139a3bf0ebfcb4e89c67817f"
WEIGHT_HASH = "04d3295ff4f9cbee72b8998a85930fe870b45ba4431e7af47415fbded02388ca"
CONFIGS = {
    "config.json": "304986b2891231c224ad429a3efd50afe2d22e7d",
    "preprocessor_config.json": "4b48811870a9d567ee23549c08249fe943e57916",
}
ENV = ("2.7.1", "4.53.2")
THREADS = 6
NATIVE = (720, 1280)
BELT_MM = 350.


def verify_model(model_dir):
    for filename, digest in CONFIGS.items():
        data = (model_dir / filename).read_bytes()
        git_blob = b"blob " + str(len(data)).encode() + b"\0" + data
        if sha1(git_blob).hexdigest() != digest:
            raise ValueError(f"Checkpoint configuration changed: {filename}")
    if prior.sha(model_dir / "model.safetensors") != WEIGHT_HASH:
        raise ValueError("Official weight SHA-256 differs")
    config = prior.read_json(model_dir / "config.json")
    if config["depth_estimation_type"] != "metric" or config["max_depth"] != 20:
        raise ValueError("Expected the indoor metric head with 20 m maximum depth")
    return {"model": REPO, "revision": REVISION, "weight_sha256": WEIGHT_HASH,
            "config_git_blob_ids": CONFIGS, "nominal_unit": "m", "max_depth_m": config["max_depth"],
            "processor": prior.read_json(model_dir / "preprocessor_config.json")}


def sources():
    files = (Path(__file__), HERE / "protocol.md", base.HERE / "frame_manifest.json", base.HERE / "train_fit.json",
             base.HERE / "run.py", learned.HERE / "run.py", base.HELD_OUT, prior.CAMERA, prior.WARNINGS,
             *(spec[0] for spec in prior.RESERVATIONS.values()))
    return {str(p.relative_to(prior.ROOT)): prior.sha(p) for p in files}


def training_choice(roster):
    def sortkey(row):
        return sha256(("mono-l1-preflight-v1/" + row["tuber"]).encode()).hexdigest()
    seen = set()
    chosen = []
    for row in sorted((r for r in roster if r["split"] == "train"), key=sortkey):
        if row["acquisition_group"] in seen:
            continue
        chosen.append(row)
        seen.add(row["acquisition_group"])
        if len(chosen) == 3:
            break
    if len(chosen) != 3:
        raise ValueError("Training preflight needs three distinct acquisition groups")
    return chosen


def freeze(output, model_dir):
    model = verify_model(model_dir)
    archived = prior.read_json(base.HERE / "frame_manifest.json")
    fit = prior.read_json(base.HERE / "train_fit.json")
    if fit["manifest_sha256"] != prior.sha(base.HERE / "frame_manifest.json"):
        raise ValueError("Archived trait fit refers to a different input freeze")
    if archived["belt_depth_mm"] != BELT_MM:
        raise ValueError("Unexpected archived projection scale")
    hold = {r["tuber"] for r in prior.read_json(base.HELD_OUT)["roster"]}
    ids = {r["tuber"] for r in archived["roster"]}
    if (len(ids) != 158 or len(hold) != 45 or ids & (hold | set(prior.published_id_exclusions()))
            or Counter(r["split"] for r in archived["roster"]) != {"train": 118, "val": 40}):
        raise ValueError("Archive cohort no longer matches the frozen eligible split")
    validation = [
        {**{k: r[k] for k in ("tuber", "suffix_px", "acquisition_group")}, "rgb": r["inputs"]["rgb"]}
        for r in archived["roster"] if r["split"] == "val"
    ]
    prior.save_json(output / "frame_manifest.json", {
        "sources_sha256": sources(), "model": model, "training_preflight": training_choice(archived["roster"]),
        "evaluation": validation, "image_size_hw": NATIVE, "belt_mm": BELT_MM,
        "projection_pixel_area_mm2": archived["projected_pixel_area_mm2"],
        "camera_matrix_px": archived["camera_matrix_px"],
        "quantiles": {"background": .85, "target": .05},
        "python": platform.python_version(), "machine": platform.machine(), "torch": ENV[0],
        "transformers": ENV[1], "threads": THREADS, "precision": "float32",
    })
    print("Frozen official checkpoint, three training checks and 40 archived development centers.", flush=True)


def manifest(output):
    data = prior.read_json(output / "frame_manifest.json")
    if data["sources_sha256"] != sources():
        raise ValueError("Frozen model input source or code changed")
    return data


def checked_model(fixed, model_dir):
    if verify_model(model_dir) != fixed["model"]:
        raise ValueError("Checkpoint does not match the frozen manifest")
    if (torch.__version__, transformers_version) != ENV:
        raise ValueError("Use the frozen PyTorch and Transformers versions")
    torch.set_num_threads(THREADS)
    torch.set_num_interop_threads(1)
    start = time.perf_counter()
    processor = AutoImageProcessor.from_pretrained(model_dir, use_fast=False, local_files_only=True)
    net = AutoModelForDepthEstimation.from_pretrained(
        model_dir, local_files_only=True, use_safetensors=True, torch_dtype=torch.float32
    ).eval()
    if (next(net.parameters()).device.type != "cpu" or next(net.parameters()).dtype != torch.float32
            or not isinstance(net.head.activation2, torch.nn.Sigmoid) or net.head.max_depth != 20):
        raise ValueError("Expected CPU FP32 metric sigmoid depth head")
    return processor, net, time.perf_counter() - start


def rgb_alpha(archives, asset):
    if asset is None:
        raise ValueError("Missing exact center RGB member")
    with Image.open(base.member_data(archives, asset)) as frame:
        if frame.mode != "RGBA" or (frame.height, frame.width) != NATIVE:
            raise ValueError("Expected the original full-scene RGBA")
        rgb = frame.convert("RGB")
        mask = np.asarray(frame.getchannel("A")) > 0
    return rgb, mask


def pixel_alignment(processor):
    raw = np.zeros((*NATIVE, 3), dtype=np.uint8)
    points = [(91, 112), (871, 291), (1131, 630)]
    for i, (x, y) in enumerate(points):
        raw[y-8:y+9, x-8:x+9, i] = 255
    tensor = processor(images=Image.fromarray(raw), return_tensors="pt")["pixel_values"][0]
    errors = []
    for channel, (x, y) in enumerate(points):
        component = tensor[channel] * processor.image_std[channel] + processor.image_mean[channel]
        test = SimpleNamespace(predicted_depth=component[None])
        mapped = processor.post_process_depth_estimation(test, target_sizes=[NATIVE])[0]["predicted_depth"].numpy()
        yy, xx = np.nonzero(mapped > .5)
        errors.append(float(np.linalg.norm(np.array([xx.mean(), yy.mean()]) - [x, y])))
    if not np.isfinite(errors).all() or max(errors) > 1.:
        raise ValueError(f"Native grid round-trip landmarks failed: {errors}")
    return {"reference_xy": points, "error_px": errors, "processor_input_hw": list(tensor.shape[-2:])}


@torch.inference_mode()
def predict_depth(rgb, processor, net):
    t0 = time.perf_counter()
    model_inputs = processor(images=rgb, return_tensors="pt")
    t1 = time.perf_counter()
    result = net(**model_inputs)
    t2 = time.perf_counter()
    unscaled = result.predicted_depth
    if not torch.isfinite(unscaled).all() or unscaled.min() < 0. or unscaled.max() > 20.00001:
        raise ValueError("Raw metric model output outside its documented range")
    restored = processor.post_process_depth_estimation(result, target_sizes=[NATIVE])[0]["predicted_depth"].numpy()
    if restored.shape != NATIVE:
        raise ValueError("Returned depth does not match original mask grid")
    return restored, {
        "input_hw": list(model_inputs["pixel_values"].shape[-2:]), "raw_output_hw": list(unscaled.shape[-2:]),
        "preprocess_s": t1-t0, "forward_s": t2-t1, "postprocess_s": time.perf_counter()-t2,
        "raw_min_m": float(unscaled.min()), "raw_max_m": float(unscaled.max()),
    }


def calibrated_height(depth, target):
    finite = np.isfinite(depth) & (depth > 0)
    foreground = depth[finite & target]
    background = depth[finite & ~target]
    b = float(np.quantile(background.astype(float), .85)) if len(background) else None
    t = float(np.quantile(foreground.astype(float), .05)) if len(foreground) else None
    result = {"B_m": b, "T_m": t, "valid_background_pixels": len(background), "valid_target_pixels": len(foreground),
              "estimated_height_mm": None, "failure_type": None}
    if b is None or t is None or not np.isfinite([b, t]).all() or b <= 0. or t <= 0.:
        result["failure_type"] = "invalid_quantiles"
    else:
        height = BELT_MM * (1. - t/b)
        if height <= 0.:
            result["failure_type"] = "nonpositive_height"
        elif not np.isfinite(height):
            result["failure_type"] = "invalid_height"
        else:
            result["estimated_height_mm"] = height
    return result


def training_diagnostic(depth, camera, mask):
    ring = binary_dilation(mask, iterations=20) & ~mask
    camera_valid = (camera >= 150) & (camera < 400)
    joint = camera_valid & np.isfinite(depth) & (depth > 0)
    inner, outer = joint & mask, joint & ring
    if not inner.any() or not outer.any():
        raise ValueError("Training check has no valid aligned foreground or surrounding camera depth")
    inside_z, outside_z = float(np.median(camera[inner])), float(np.median(camera[outer]))
    inside_d, outside_d = float(np.median(depth[inner])), float(np.median(depth[outer]))
    rho = float(spearmanr(camera[inner | outer], depth[inner | outer]).statistic)
    return {"camera_mask_median_mm": inside_z, "camera_ring_median_mm": outside_z,
            "mono_mask_median_m": inside_d, "mono_ring_median_m": outside_d,
            "order_agrees": (inside_z < outside_z) == (inside_d < outside_d),
            "spearman_with_raw_camera_depth": rho if np.isfinite(rho) else None}


def plot_training(output, rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(len(rows), 3, figsize=(15, 8), constrained_layout=True)
    for cols, (record, rgb, mask, mono, raw) in zip(axes, rows, strict=True):
        b, t = record["B_m"], record["T_m"]
        rgb_array = np.asarray(rgb).astype(float) / 255.
        upper = np.isfinite(mono) & ~mask & (mono >= b)
        rgb_array[upper] = .52 * rgb_array[upper] + .48 * np.array([0., .85, 1.])
        cols[0].imshow(rgb_array)
        cols[0].set_title(f"{record['tuber']} · RGB / upper background tail")
        dplot = cols[1].imshow(mono, cmap="viridis", vmin=np.nanquantile(mono, .01), vmax=np.nanquantile(mono, .99))
        cols[1].set_title(f"Monocular depth (m) · B {b:.3f}, T {t:.3f}")
        fig.colorbar(dplot, ax=cols[1], shrink=.75)
        cplot = cols[2].imshow(np.ma.masked_outside(raw, 150, 399), cmap="viridis", vmin=240, vmax=390)
        cols[2].set_title(f"Camera depth (mm) · camera height {record['camera_height_mm']:.1f}")
        fig.colorbar(cplot, ax=cols[2], shrink=.75)
        for ax in cols:
            ax.contour(mask, levels=[.5], colors=["#ff36d7"], linewidths=.8)
            ax.axis("off")
    fig.savefig(output / "training_overlays.png", dpi=150)
    plt.close(fig)


def open_archives(stack, members):
    names = {m["archive"] for m in members if m is not None}
    return {name: stack.enter_context(ZipFile(base.IMAGES / name)) for name in sorted(names)}


def preflight(output, model_dir):
    fixed = manifest(output)
    processor, model, load_s = checked_model(fixed, model_dir)
    alignment = pixel_alignment(processor)
    labels_path = base.HERE / "train_features.csv"
    if prior.sha(labels_path) != prior.read_json(base.HERE / "train_fit.json")["training_features_sha256"]:
        raise ValueError("Archived training height reference changed")
    labels = learned.indexed(prior.read_csv(labels_path))
    rows, panels = [], []
    chosen = fixed["training_preflight"]
    members = [m for case in chosen for m in case["inputs"].values()]
    with ExitStack() as stack:
        archives = open_archives(stack, members)
        for case in chosen:
            tuber = case["tuber"]
            rgb, mask = rgb_alpha(archives, case["inputs"]["rgb"])
            mono, runtime = predict_depth(rgb, processor, model)
            params = case["inputs"]["depth"]
            with Image.open(base.member_data(archives, params)) as image:
                camera = np.asarray(image)
            if camera.shape != NATIVE or camera.dtype != np.uint16 or labels[tuber]["split"] != "train":
                raise ValueError("Unexpected camera depth or training label")
            k = fixed["camera_matrix_px"]
            area = base.silhouette_features(mask, k[0][0], k[1][1], fixed["projection_pixel_area_mm2"])
            learned.replay_geometry({**area, "tuber": tuber, "suffix_px": case["suffix_px"]}, labels[tuber])
            physical = base.depth_features(archives, params, mask, area["projected_area_mm2"])
            learned.check_close(physical["height_mm"], float(labels[tuber]["height_mm"]), f"{tuber} camera height")
            row = {"tuber": tuber, "suffix_px": case["suffix_px"], "camera_height_mm": physical["height_mm"],
                   **calibrated_height(mono, mask), **training_diagnostic(mono, camera, mask), "runtime": runtime}
            rows.append(row)
            panels.append((row, rgb, mask, mono, camera))
            print("Training preflight:", row, flush=True)
    plot_training(output, panels)
    prior.save_json(output / "training_preflight.json", {
        "manifest_sha256": prior.sha(output / "frame_manifest.json"), "load_s": load_s,
        "alignment": alignment, "training_cases": rows, "overlay_sha256": prior.sha(output / "training_overlays.png"),
    })


def predict_one(case, fixed, archives, processor, model, coefficients):
    row = {k: case[k] for k in ("tuber", "suffix_px")}
    row.update(B_m=None, T_m=None, estimated_height_mm=None, valid_background_pixels=None, valid_target_pixels=None,
               runtime=None, failure_type=None, failure_detail=None, geometry=None,
               trait_predictions=dict.fromkeys(base.TARGETS))
    start = time.perf_counter()
    try:
        rgb, mask = rgb_alpha(archives, case["rgb"])
        mono, runtime = predict_depth(rgb, processor, model)
        row["runtime"] = runtime
        row.update(calibrated_height(mono, mask))
        k = fixed["camera_matrix_px"]
        geometry = base.silhouette_features(mask, k[0][0], k[1][1], fixed["projection_pixel_area_mm2"])
        row["geometry"] = geometry
        if row["estimated_height_mm"] is not None:
            for trait, fit in coefficients.items():
                row["trait_predictions"][trait] = learned.trait_prediction(
                    geometry, fit["coefficients"]["depth_assisted"], row["estimated_height_mm"]
                )
    except (*base.ERRORS, RuntimeError) as exc:
        if row["failure_type"] is None:
            row["failure_type"] = "image_or_inference"
        row["failure_detail"] = f"{type(exc).__name__}: {exc}"
    row["wall_s"] = time.perf_counter() - start
    return row


def predict(output, model_dir):
    fixed = manifest(output)
    train_path = output / "training_preflight.json"
    train = prior.read_json(train_path)
    if (train["manifest_sha256"] != prior.sha(output / "frame_manifest.json")
            or prior.sha(output / "training_overlays.png") != train["overlay_sha256"]):
        raise ValueError("Need a completed training preflight on the frozen model")
    if (output / "predictions_before_targets.json").exists():
        raise ValueError("The frozen predictions already exist")
    coeff = prior.read_json(base.HERE / "train_fit.json")["traits"]
    processor, model, load_s = checked_model(fixed, model_dir)
    rows = []
    chosen = fixed["evaluation"]
    with ExitStack() as stack:
        archives = open_archives(stack, (r["rgb"] for r in chosen))
        for case in chosen:
            row = predict_one(case, fixed, archives, processor, model, coeff)
            rows.append(row)
            print(f"{len(rows)}/40 {case['tuber']}: h={row['estimated_height_mm']} mm; "
                  f"{row['failure_type'] or 'ok'}, {row['wall_s']:.2f} s", flush=True)
    prior.save_json(output / "predictions_before_targets.json", {
        "manifest_sha256": prior.sha(output / "frame_manifest.json"), "training_preflight_sha256": prior.sha(train_path),
        "load_s": load_s, "model_revision": REVISION, "checkpoint_sha256": WEIGHT_HASH,
        "per_frame": rows,
    })
    print("All 40 RGB-only entries saved before opening validation references.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "preflight", "predict"))
    parser.add_argument("--out", type=Path, default=HERE)
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"freeze": freeze, "preflight": preflight, "predict": predict}[args.stage](args.out, args.model_dir)
