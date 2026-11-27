"""One-frame, seed-paired CoRe++ pin and peel color pilot."""
import argparse
import csv
import hashlib
import io
import json
import random
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from zipfile import ZipFile

import cv2 as cv
import numpy as np
import open3d as o3d
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt
import torch

from . import corepp_cpu_audit as audit

SEEDS = tuple(range(133, 149))
PROTOCOL = audit.HERE / "corepp_pin_pilot_protocol.md"
AUDIT = audit.HERE / "corepp_cpu_audit.json"
NOOP = "no_op_replay.json"
INPUTS = "frozen_inputs.json"
RESULTS = "results.json"
SURFACE_TOL_MM = 1e-4
DONOR = "5R2-3"
DONOR_FRAME = "356"
SATURATION_CAP = .22
PEEL_ROI = (79, 148, 136, 204)  # xyxy, visually inspected ordinary peel
EDGE_DISTANCE_TOL_PX = 4


def put_json(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write("\n")


def set_rng(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    o3d.utility.random.seed(seed)


def apply_delta(rgba, rows, cols, delta):
    output = rgba.copy()
    output[rows, cols, :3] = np.clip(rgba[rows, cols, :3].astype(np.int16)+delta, 0, 255)
    return output


class Pilot:
    def __init__(self, args, temp):
        sys.path.insert(0, str(args.upstream.resolve()))
        from dataloaders.cameralaser_w_masks import MaskedCameraLaserData, histogram_filtering
        from dataloaders.transforms import Pad, get_padding
        from deepsdf.networks.deep_sdf_decoder import Decoder
        from networks.models import EncoderBigPooled
        from networks.utils import load_without_parallel, set_require_grad
        from sdfrenderer.grid import Grid3D
        from utils import sdf2mesh_cuda

        saved = audit.read_json(AUDIT)
        for base, checks in ((args.upstream, saved["upstream_file_sha256"]),
                             (args.released, saved["released_config_sha256"]),
                             (args.released, saved["checkpoint_sha256"])):
            if any(audit.sha256(base/name) != sha for name, sha in checks.items()):
                raise ValueError("A pinned upstream source, config, or checkpoint changed")
        self.camera = args.upstream/"data/potato_example/realsense/intrinsic.json"
        self.cfg = audit.read_json(args.released/"super3d_32.json")
        specs = audit.read_json(args.released/"specs.json")
        self.preprocessor = (MaskedCameraLaserData.preprocess_images, histogram_filtering, Pad, get_padding)
        self.mesh_builder = sdf2mesh_cuda
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        cv.setNumThreads(1)

        self.paths, self.source_hashes, frame, self.pin = audit.stage_frame(args.source, temp)
        if frame != "364":
            raise ValueError("Expected registered frame 2R1-10 / 364")
        self.rgba = np.array(Image.open(self.paths["rgb"]))
        self.depth = cv.imread(str(self.paths["depth"]), cv.IMREAD_UNCHANGED)
        self.grid = Grid3D(self.cfg["grid_density"], "cpu", torch.float32,
                           bbox=saved["grid_bbox_m_single_tuber_split"]).points.detach()
        self.box = saved["grid_bbox_m_single_tuber_split"]
        self.grid_sha = audit.array_sha256(self.grid.numpy())
        self.no_edit_hash = saved["runs"][0]["input_tensor_sha256"]

        self.decoder = Decoder(specs["CodeLength"], **specs["NetworkSpecs"]).cpu()
        pretrain = torch.load(args.released/"500.pth", map_location="cpu", weights_only=True)
        self.decoder.load_state_dict(load_without_parallel(pretrain), strict=True)
        set_require_grad(self.decoder, False)
        set_rng(audit.CPU_SEED)
        self.encoder = EncoderBigPooled(4, specs["CodeLength"], self.cfg["input_size"]).cpu()
        joint = torch.load(args.released/self.cfg["checkpoint_file"], map_location="cpu", weights_only=True)
        self.encoder.load_state_dict(joint["encoder_state_dict"], strict=True)
        self.decoder.load_state_dict(joint["decoder_state_dict"], strict=True)
        self.models = (self.encoder, self.decoder)
        self.states = [{k: v.detach().clone() for k, v in model.state_dict().items()} for model in self.models]
        self.modes = (saved["encoder_training_mode"], saved["decoder_training_mode"])
        self.temp = temp

    def prepare(self, rgb_path, seed):
        set_rng(seed)
        return audit.prepare_tensor({**self.paths, "rgb": rgb_path}, self.pin, self.camera,
                                    self.cfg, *self.preprocessor)[:3]

    def infer(self, rgb_path, seed):
        start = perf_counter()
        for model, state, mode in zip(self.models, self.states, self.modes):
            model.load_state_dict(state, strict=True)
            model.train(mode)
        tensor, _, _ = self.prepare(rgb_path, seed)
        with torch.no_grad():
            set_rng(seed)
            latent = self.encoder(tensor)
            decoder_input = torch.cat((latent.expand(len(self.grid), -1), self.grid), dim=1)
            set_rng(seed)
            sdf = self.decoder(decoder_input)
            mesh, failure, volume = None, None, None
            try:
                set_rng(seed)
                mesh = self.mesh_builder(sdf, self.grid, t=0.0)
                if not mesh.is_watertight():
                    raise ValueError("Non-watertight prediction")
                volume = mesh.get_volume()*1e6
            except (ValueError, RuntimeError) as exc:
                mesh, failure = None, str(exc)
        return {"tensor": tensor.numpy(), "latent": latent.numpy(), "sdf": sdf.numpy(), "mesh": mesh,
                "mesh_failure": failure, "volume_ml": volume, "runtime_seconds": perf_counter()-start}

    def provenance(self):
        return {
            "protocol_sha256": audit.sha256(PROTOCOL), "cpu_audit_sha256": audit.sha256(AUDIT),
            "source_hashes": self.source_hashes, "model_training_modes": dict(zip(("encoder","decoder"), self.modes)),
            "rng_reset_before": ["preprocessing", "encoder", "decoder", "mesh"], "cpu_threads": 1,
            "grid_sha256": self.grid_sha, "grid_size": len(self.grid), "grid_bbox_m": self.box,
        }


def same_mesh(a, b):
    return all(np.array_equal(np.asarray(getattr(a, k)), np.asarray(getattr(b, k)))
               for k in ("vertices", "triangles"))


def surface_pair(a, b):
    distances = np.concatenate((audit.surface_distances_mm(a, b), audit.surface_distances_mm(b, a)))
    return {"mean_mm": float(distances.mean()), "p95_mm": float(np.quantile(distances, .95)),
            "max_mm": float(distances.max()), "identical_mesh_arrays": same_mesh(a, b)}


def numeric_hashes(run):
    return {key: audit.array_sha256(run[key]) for key in ("tensor", "latent", "sdf")}


def run_noop(pilot, out):
    # A zero delta goes through the same clipping and PNG write as a color edit.
    yy, xx = np.nonzero(pilot.rgba[..., 3] > 0)
    rgba = apply_delta(pilot.rgba, yy, xx, np.zeros((len(xx), 3), dtype=np.int16))
    noop = pilot.temp/"noop_rgba.png"
    Image.fromarray(rgba).save(noop)
    rows = []
    for seed in SEEDS:
        original, edited = [pilot.infer(path, seed) for path in (pilot.paths["rgb"], noop)]
        pair = numeric_hashes(original), numeric_hashes(edited)
        if pair[0] != pair[1] or pair[0]["tensor"] != pilot.no_edit_hash:
            raise ValueError(f"No-op replay failed for seed {seed}: tensors, latents, or SDF differ")
        if original["mesh"] is None or edited["mesh"] is None:
            raise ValueError(f"No-op mesh failure for seed {seed}")
        surface = surface_pair(original["mesh"], edited["mesh"])
        if (original["volume_ml"] != edited["volume_ml"] or not surface["identical_mesh_arrays"]
                or surface["max_mm"] > SURFACE_TOL_MM):
            raise ValueError(f"No-op geometry changed for seed {seed}: {surface}")
        rows.append({"seed": seed, "hashes": pair[0], "grid_label_changes": 0,
                     "volume_change_ml": 0, "surface_distance": surface})
    put_json(out/NOOP, {"status": "passed", **pilot.provenance(),
                        "surface_tolerance_mm": SURFACE_TOL_MM, "pairs": rows})
    print(f"No-op replay passed for all {len(rows)} seeds", flush=True)


def verify_noop(pilot, out):
    result = audit.read_json(out/NOOP)
    if result["status"] != "passed" or [row["seed"] for row in result["pairs"]] != list(SEEDS):
        raise ValueError("An all-seed no-op pass is required before color edits")
    if any(result[key] != value for key, value in pilot.provenance().items()):
        raise ValueError("No-op provenance differs from this run")
    return result


def donor_hue(source, out):
    filename = f"{DONOR}_rgb_{DONOR_FRAME}.png"
    with (audit.DEV/"fresh_download_members.tsv").open(newline="") as f:
        member, = [r for r in csv.DictReader(f, delimiter="\t") if r["member_basename"] == filename]
    with ZipFile(source/member["archive"]) as z:
        data = z.read(member["member_path"])
    archived, = [row for row in audit.read_json(audit.HERE/"results.json")["intake"]["pairs"]
                 if row["object_id"] == DONOR]
    sha = hashlib.sha256(data).hexdigest()
    if sha != archived["files"]["rgb"]["sha256"] or len(data) != int(member["uncompressed_bytes"]):
        raise ValueError("Donor RGB differs from the archived development selection")
    labels = audit.read_json(source/audit.PIN_LABELS)
    image, = [im for im in labels["images"] if im["file_name"] == f"{DONOR}/{filename}"]
    pin, = [row for row in labels["annotations"] if row["image_id"] == image["id"]]
    x, y, w, h = map(int, pin["bbox"])
    cx, cy = x + w//2, y + h//2
    rgb = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
    sample = rgb[cy-2:cy+3, cx-2:cx+3]
    median = np.median(sample, axis=(0, 1)).astype(np.uint8)
    hsv = cv.cvtColor(median.reshape(1, 1, 3).astype(np.float32)/255, cv.COLOR_RGB2HSV)[0, 0]
    Image.fromarray(rgb[y-4:y+h+4, x-4:x+w+4]).save(out/"donor_red_pin.png")
    return {"tuber": DONOR, "frame": DONOR_FRAME, "annotation_id": pin["id"],
            "source_archive": member["archive"], "source_member": member["member_path"],
            "source_sha256": sha, "sample_center_xy": [cx, cy], "sample_size_px": 5,
            "median_rgb": median.tolist(), "hue_deg": float(hsv[0]), "saturation": float(hsv[1])}


def model_masks(pilot, trace):
    row, col = trace["crop_origin_yx_px"]
    h, w = trace["crop_height_width_px"]
    left, top, right, bottom = trace["pad_ltrb_px"]
    ymin, ymax = trace["histogram_depth_range_mm"]
    padding = ((top, bottom), (left, right))
    silhouette = pilot.rgba[row:row+h, col:col+w, 3] == 255
    cropped_depth = pilot.depth[row:row+h, col:col+w]
    valid = silhouette & (cropped_depth != 0) & (cropped_depth >= ymin) & (cropped_depth <= ymax)
    silhouette, valid = (np.pad(mask, padding) for mask in (silhouette, valid))

    # The released contour follows the visible pin rim. Transfer it to the audited crop.
    polygon, = pilot.pin["segmentation"]
    points = [(int(x-col+left), int(y-row+top)) for x, y in zip(polygon[::2], polygon[1::2])]
    canvas = Image.new("1", silhouette.shape[::-1])
    ImageDraw.Draw(canvas).polygon(points, fill=1)
    pin = np.array(canvas)
    bx, by, bw, bh = map(int, trace["bbox_in_model_xywh_px"])
    box = np.zeros_like(pin)
    box[by:by+bh, bx:bx+bw] = True
    if not pin.any() or np.any(pin & ~(box & valid)):
        raise ValueError("The pin contour leaves its annotation or the model's valid pixels")
    return silhouette, valid, pin, box


def choose_peel(rgb, silhouette, valid, pin, box, delta):
    y, x = np.nonzero(pin)
    edge_distance = distance_transform_edt(silhouette)
    pin_distance = edge_distance[y, x]
    rx0, ry0, rx1, ry1 = PEEL_ROI
    candidates = []
    for dy in range(ry0-y.min(), ry1-y.max()):
        for dx in range(rx0-x.min(), rx1-x.max()):
            yy, xx = y+dy, x+dx
            if np.any(~valid[yy, xx] | box[yy, xx]):
                continue
            distance_delta = edge_distance[yy, xx] - pin_distance
            if abs(distance_delta.mean()) > EDGE_DISTANCE_TOL_PX:
                continue
            proposed = rgb[yy, xx].astype(np.int16) + delta
            clipped = (proposed < 0) | (proposed > 255)
            candidates.append((int(clipped.any(axis=1).sum()), int(clipped.sum()),
                               abs(float(distance_delta.mean())), float(np.sqrt((distance_delta**2).mean())),
                               dy, dx))
    if not candidates:
        raise ValueError("No valid silhouette-distance match inside the visually selected peel region")
    pixels, channels, gap, rmse, dy, dx = min(candidates)
    peel = np.zeros_like(pin)
    peel[y+dy, x+dx] = True
    return peel, {"offset_xy_px": [dx, dy], "roi_xyxy_px": PEEL_ROI, "candidates": len(candidates),
                  "clipped_pixels": pixels, "clipped_channels": channels,
                  "mean_edge_distance_pin_px": float(pin_distance.mean()),
                  "mean_edge_distance_peel_px": float(edge_distance[peel].mean()),
                  "mean_edge_distance_gap_px": gap, "edge_distance_profile_rmse_px": rmse}


def rgb_change(before, after, mask):
    delta = after.astype(np.int16) - before
    changed = np.any(delta != 0, axis=2)
    if np.any(changed & ~mask) or not np.any(changed):
        raise ValueError("An edited RGB image changed outside its mask or had no change")
    magnitudes = np.linalg.norm(delta[mask], axis=1)
    return {"mask_pixels": int(mask.sum()), "changed_pixels": int(changed.sum()), "changed_outside_mask": 0,
            "mean_rgb_l2_per_mask_pixel": float(magnitudes.mean()), "max_rgb_l2": float(magnitudes.max()),
            "mean_abs_by_channel_per_mask_pixel": np.abs(delta[mask]).mean(axis=0).tolist(),
            "delta_sha256": audit.array_sha256(delta)}


def save_overlay(previews, pin, peel, out):
    from scipy.ndimage import binary_erosion

    overlay = previews["original"].copy()
    overlay[pin & ~binary_erosion(pin)] = (45, 217, 255)
    overlay[peel & ~binary_erosion(peel)] = (255, 191, 56)
    crop = (40, 76, 263, 229)
    panels = (("Original with masks", overlay), ("Pin edit", previews["pin"]), ("Peel edit", previews["peel"]))
    canvas = Image.new("RGB", (689, 184), "white")
    draw = ImageDraw.Draw(canvas)
    for i, (label, rgb) in enumerate(panels):
        x = 6 + i*228
        draw.text((x, 5), label, fill="black")
        canvas.paste(Image.fromarray(rgb).crop(crop), (x, 21))
    canvas.save(out/"masks_and_edits.png")


def freeze_edits(pilot, args):
    out, local = args.out_dir, args.input_dir
    verify_noop(pilot, out)
    if (out/INPUTS).exists():
        raise FileExistsError(out/INPUTS)
    local.mkdir(parents=True, exist_ok=False)
    original, original_rgb, trace = pilot.prepare(pilot.paths["rgb"], SEEDS[0])
    if audit.array_sha256(original.numpy()) != pilot.no_edit_hash:
        raise ValueError("Original preprocessing no longer matches the CPU audit")
    silhouette, valid, pin, box = model_masks(pilot, trace)
    donor = donor_hue(args.source, out)
    hsv = cv.cvtColor(original_rgb[pin].reshape(1, -1, 3).astype(np.float32)/255, cv.COLOR_RGB2HSV)
    hsv[..., 0] = donor["hue_deg"]
    hsv[..., 1] = min(donor["saturation"], SATURATION_CAP)
    tint = np.rint(cv.cvtColor(hsv, cv.COLOR_HSV2RGB).reshape(-1, 3)*255).astype(np.int16)
    np.testing.assert_array_equal(tint.max(axis=1), original_rgb[pin].max(axis=1))
    delta = tint - original_rgb[pin]
    peel, translation = choose_peel(original_rgb, silhouette, valid, pin, box, delta)

    row, col = trace["crop_origin_yx_px"]
    left, top, _, _ = trace["pad_ltrb_px"]
    originals = {"original_rgba.png": pilot.paths["rgb"], "depth.png": pilot.paths["depth"],
                 "intrinsic.json": pilot.camera}
    for name, path in originals.items():
        (local/name).write_bytes(path.read_bytes())
    previews = {"original": original_rgb}
    changes, tensor_hashes = {}, {"original": pilot.no_edit_hash}
    for name, mask in (("pin", pin), ("peel", peel)):
        yy, xx = np.nonzero(mask)
        sy, sx = yy+row-top, xx+col-left
        proposed = original_rgb[mask].astype(np.int16) + delta
        path = local/f"{name}_rgba.png"
        Image.fromarray(apply_delta(pilot.rgba, sy, sx, delta)).save(path)
        edited_rgba = np.array(Image.open(path))
        np.testing.assert_array_equal(edited_rgba[..., 3], pilot.rgba[..., 3])
        np.testing.assert_array_equal(edited_rgba[sy, sx, :3], np.clip(proposed, 0, 255))
        actual_raw = np.any(edited_rgba[..., :3] != pilot.rgba[..., :3], axis=2)
        if actual_raw.sum() != actual_raw[sy, sx].sum():
            raise ValueError("Raw RGB differences escape the intended mask")

        tensor, rgb, edit_trace = pilot.prepare(path, SEEDS[0])
        if edit_trace != trace:
            raise ValueError("Color edit changed the crop or mask trace")
        np.testing.assert_array_equal(tensor.numpy()[:, 3], original.numpy()[:, 3])
        np.testing.assert_array_equal(tensor.numpy()[0, :3].transpose(1, 2, 0), rgb.astype(np.float32)/255)
        np.testing.assert_array_equal(rgb[mask], np.clip(proposed, 0, 255))
        np.testing.assert_array_equal(rgb[~valid], original_rgb[~valid])
        changes[name] = rgb_change(original_rgb, rgb, mask)
        changes[name]["clipped_channels"] = int(((proposed < 0) | (proposed > 255)).sum())
        changes[name]["realized_delta_matches_intended"] = bool(np.array_equal(
            rgb[mask].astype(np.int16) - original_rgb[mask], delta))
        tensor_hashes[name] = audit.array_sha256(tensor.numpy())
        previews[name] = rgb
        Image.fromarray(mask).save(out/f"{name}_mask.png")

    for name, rgb in previews.items():
        Image.fromarray(rgb).save(out/f"{name}_input_rgb.png")
    save_overlay(previews, pin, peel, out)
    evidence = ["pin_mask.png", "peel_mask.png", "masks_and_edits.png", "donor_red_pin.png",
                *(f"{condition}_input_rgb.png" for condition in previews)]
    put_json(out/INPUTS, {
        "status": "frozen_before_scoring", **pilot.provenance(), "no_op_sha256": audit.sha256(out/NOOP),
        "source_conditions": {p.name: audit.sha256(p) for p in sorted(local.iterdir())},
        "evidence_sha256": {name: audit.sha256(out/name) for name in evidence},
        "preprocessed_tensor_sha256": tensor_hashes, "depth_channel_sha256": audit.array_sha256(original.numpy()[:, 3]),
        "valid_mask_sha256": audit.array_sha256(valid), "crop_and_mask_trace": trace,
        "donor": donor, "saturation_cap": SATURATION_CAP, "edge_distance_tolerance_px": EDGE_DISTANCE_TOL_PX,
        "translation": translation, "rgb_change_8bit": changes, "intended_rgb_delta_sha256": audit.array_sha256(delta),
    })
    print(json.dumps({"translation": translation, "rgb_change_8bit": changes}, indent=2), flush=True)


def compare(original, edited):
    sdf_delta = np.abs(edited["sdf"] - original["sdf"])
    signed_volume = None if edited["mesh"] is None else edited["volume_ml"] - original["volume_ml"]
    surface = None if edited["mesh"] is None else surface_pair(original["mesh"], edited["mesh"])
    if surface is not None and surface["identical_mesh_arrays"]:
        surface = {**surface, "mean_mm": 0., "p95_mm": 0., "max_mm": 0.}
    return {"latent_l2": float(np.linalg.norm(edited["latent"] - original["latent"])),
            "mean_abs_sdf_change_mm": float(sdf_delta.mean(dtype=np.float64)*1e3),
            "grid_label_changes": int(np.count_nonzero((edited["sdf"] < 0) != (original["sdf"] < 0))),
            "volume_change_ml": signed_volume,
            "abs_volume_change_ml": None if signed_volume is None else abs(signed_volume),
            "surface_distance": surface, "mesh_failure": edited["mesh_failure"],
            "runtime_seconds": edited["runtime_seconds"], "hashes": numeric_hashes(edited)}


def summarize(values):
    return {"n": len(values), "median": float(np.median(values)) if values else None,
            "min": min(values, default=None), "max": max(values, default=None)}


def score(pilot, args):
    out, local = args.out_dir, args.input_dir
    if (out/RESULTS).exists():
        raise FileExistsError(out/RESULTS)
    noop = verify_noop(pilot, out)
    frozen = audit.read_json(out/INPUTS)
    if (frozen["status"] != "frozen_before_scoring" or frozen["no_op_sha256"] != audit.sha256(out/NOOP)
            or any(frozen[key] != value for key, value in pilot.provenance().items())):
        raise ValueError("Frozen input provenance differs from the current run")
    for directory, hashes in ((local, frozen["source_conditions"]), (out, frozen["evidence_sha256"])):
        if any(audit.sha256(directory/name) != sha for name, sha in hashes.items()):
            raise ValueError("A frozen pilot input changed")
    rows = []
    for baseline in noop["pairs"]:
        seed = baseline["seed"]
        original = pilot.infer(local/"original_rgba.png", seed)
        if numeric_hashes(original) != baseline["hashes"] or original["mesh"] is None:
            raise ValueError(f"Unchanged input did not reproduce the archived no-op pair at {seed}")
        row = {"seed": seed, "original_volume_ml": original["volume_ml"],
               "original_runtime_seconds": original["runtime_seconds"]}
        for name in ("pin", "peel"):
            edited = pilot.infer(local/f"{name}_rgba.png", seed)
            if audit.array_sha256(edited["tensor"]) != frozen["preprocessed_tensor_sha256"][name]:
                raise ValueError(f"Frozen {name} input tensor changed at {seed}")
            row[name] = compare(original, edited)
        pin, peel = (row[k]["surface_distance"] for k in ("pin", "peel"))
        row["pin_minus_peel_surface_mm"] = None if pin is None or peel is None else pin["mean_mm"] - peel["mean_mm"]
        rows.append(row)
    primary = [r["pin_minus_peel_surface_mm"] for r in rows if r["pin_minus_peel_surface_mm"] is not None]
    aggregates = {}
    for name in ("pin", "peel"):
        pairs = [r[name] for r in rows]
        metrics = ("latent_l2", "mean_abs_sdf_change_mm", "grid_label_changes", "volume_change_ml", "abs_volume_change_ml")
        aggregates[name] = {key: summarize([r[key] for r in pairs if r[key] is not None]) for key in metrics}
        aggregates[name]["mean_symmetric_surface_mm"] = summarize([r["surface_distance"]["mean_mm"] for r in pairs
                                                                   if r["surface_distance"] is not None])
        aggregates[name]["mesh_failures"] = sum(r["mesh_failure"] is not None for r in pairs)
    put_json(out/RESULTS, {
        "tuber": audit.OBJECT, "frame": "364", **pilot.provenance(), "no_op_sha256": audit.sha256(out/NOOP),
        "scoring_code_sha256": audit.sha256(Path(__file__)), "frozen_inputs_sha256": audit.sha256(out/INPUTS),
        "surface_sampling": {"points_per_direction": 20000, "seed": audit.CPU_SEED},
        "by_condition": aggregates, "pin_minus_peel_surface_mm": summarize(primary),
        "primary_pairs_positive": sum(v > 0 for v in primary), "primary_pairs_tied": sum(v == 0 for v in primary),
        "primary_pairs_negative": sum(v < 0 for v in primary), "pairs": rows,
    })
    print(f"Pilot scored {len(primary)}/{len(SEEDS)} paired seeds", flush=True)


def main():
    options = argparse.ArgumentParser(description=__doc__)
    options.add_argument("phase", choices=("noop", "freeze", "score"))
    for name in ("source", "upstream", "released", "out-dir"):
        options.add_argument(f"--{name}", type=Path, required=True)
    options.add_argument("--input-dir", type=Path, default=Path("outputs/corepp_pin_pilot/inputs"))
    args = options.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="potato-corepp-pin-") as temp:
        pilot = Pilot(args, Path(temp))
        if args.phase == "noop":
            run_noop(pilot, args.out_dir)
        elif args.phase == "freeze":
            freeze_edits(pilot, args)
        else:
            score(pilot, args)


if __name__ == "__main__":
    main()
