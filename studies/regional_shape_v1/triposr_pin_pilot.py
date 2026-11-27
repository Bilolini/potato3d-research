"""Freeze and score one exactly matched TripoSR pin-versus-peel intervention."""

import argparse
import json
from pathlib import Path
import site
import sys

import numpy as np
import open3d as o3d
from PIL import Image, ImageDraw, ImageFont
import torch

from . import corepp_cross_model_replay as replay

HERE = Path(__file__).resolve().parent
INPUTS = Path("outputs/corepp_pin_pilot/inputs")
PILOT = HERE / "corepp_pin_pilot"
PROTOCOL = HERE / "triposr_pin_pilot_protocol.md"
REPLAY = HERE / "corepp_cross_model/replay.json"
CONDITIONS = ("unchanged", "noop", "pin", "peel")
HASHES = ("tokenizer_input_sha256", "triplane_sha256", "density_sha256", "vertex_sha256", "faces_sha256")
DELTA_STEPS = 4096


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, data):
    with path.open("x") as file:
        json.dump(data, file, indent=2, allow_nan=False)
        file.write("\n")


def protocol_hashes():
    paths = (Path(__file__), PROTOCOL, Path(replay.__file__), REPLAY, PILOT / "frozen_inputs.json")
    return {str(p.relative_to(HERE)): replay.hash_file(p) for p in paths}


def crop_rgb(image, resize, processor):
    rgba = np.asarray(resize(image, 0.85)).astype(np.float32) / 255
    alpha = rgba[..., 3:]
    rgb8 = ((rgba[..., :3] * alpha + (1-alpha)*0.5)*255).astype(np.uint8)
    return processor([rgb8], replay.SIZE)[0].numpy(), rgb8.shape[0]


def transport(alpha, mask, resize, processor):
    packed = np.repeat(alpha[..., None], 4, axis=2)
    packed[..., :3] = mask[..., None].astype(np.uint8) * 255
    out = np.asarray(resize(Image.fromarray(packed), 0.85))[..., :3]
    return processor([out], replay.SIZE)[0, ..., 0].numpy()


def release_mask(name, pilot, shape):
    evidence = PILOT / f"{name}_mask.png"
    if replay.hash_file(evidence) != pilot["evidence_sha256"][evidence.name]:
        raise ValueError(f"Archived {name} mask changed")
    trace = pilot["crop_and_mask_trace"]
    y, x = trace["crop_origin_yx_px"]
    height, width = trace["crop_height_width_px"]
    left, top, _, _ = trace["pad_ltrb_px"]
    crop = np.asarray(Image.open(evidence)).astype(bool)
    mask = np.zeros(shape, dtype=bool)
    mask[y:y+height, x:x+width] = crop[top:top+height, left:left+width]
    if mask.sum() != crop.sum():
        raise ValueError(f"Archived {name} mask is outside its source crop")
    return mask


def matched_delta(original, pin, peel, proposal):
    pin_base, peel_base = (original[site[:, 0], site[:, 1]].astype(np.float64) for site in (pin, peel))
    proposed = np.rint(proposal[pin[:, 0], pin[:, 1]] * DELTA_STEPS).astype(np.int64)
    lower = np.ceil(-np.minimum(pin_base, peel_base) * DELTA_STEPS).astype(np.int64)
    upper = np.floor((1-np.maximum(pin_base, peel_base)) * DELTA_STEPS).astype(np.int64)
    bounded = np.clip(proposed, lower, upper)
    steps = bounded.copy()
    while True:
        delta = steps.astype(np.float64) / DELTA_STEPS
        a = (pin_base + delta).astype(np.float32).astype(np.float64) - pin_base
        b = (peel_base + delta).astype(np.float32).astype(np.float64) - peel_base
        unequal = a != b
        if not unequal.any():
            break
        steps[unequal] -= np.sign(steps[unequal])
    stats = {
        "quantization_steps_per_rgb_unit": DELTA_STEPS,
        "channels_capped_to_common_range": int((proposed != bounded).sum()),
        "channels_reduced_for_exact_float32_match": int((bounded != steps).sum()),
    }
    return a, stats


def apply(image, sites, delta):
    result = image.copy()
    y, x = sites.T
    result[y, x] = result[y, x].astype(np.float64) + delta
    return result


def check_edits(images, sites, delta):
    original = images["unchanged"]
    np.testing.assert_array_equal(images["noop"], original)
    report = {}
    for name, xy in sites.items():
        difference = images[name].astype(np.float64) - original
        y, x = xy.T
        allowed = np.zeros(original.shape[:2], dtype=bool)
        allowed[y, x] = True
        np.testing.assert_array_equal(difference[y, x], delta)
        changed = np.any(difference != 0, axis=-1)
        off_mask = int((changed & ~allowed).sum())
        changed_count = int(changed.sum())
        if off_mask or changed_count == 0 or images[name].min() < 0 or images[name].max() > 1:
            raise ValueError(f"Invalid frozen edit {name}")
        report[name] = {"paired_mask_pixels": len(xy), "changed_pixels": changed_count, "off_mask_changes": off_mask}
    strength = np.linalg.norm(delta, axis=1) * 255
    report["shared_delta"] = {
        "mean_rgb_l2_8bit_equivalent": float(strength.mean()),
        "max_rgb_l2_8bit_equivalent": float(strength.max()),
        "mean_signed_rgb_change_8bit_equivalent": (delta.mean(axis=0)*255).tolist(),
    }
    return report


def save_crops(out, images, sites):
    def display(array):
        return Image.fromarray(np.rint(array * 255).astype(np.uint8))

    full = display(images["unchanged"])
    panel = Image.new("RGB", (828, 488), "#f1eee7")
    draw = ImageDraw.Draw(panel)
    font = ImageFont.load_default(size=18)
    draw.text((20, 13), "TripoSR input, frame 2R1-10 / 364", font=font, fill="#242822")
    for i, label in enumerate(("Unchanged", "Paired mask", "Recolored")):
        draw.text((114+235*i, 47), label, font=font, fill="#242822")
    for i, (name, coords) in enumerate(sites.items()):
        yc, xc = np.rint(coords.mean(axis=0)).astype(int)
        bounds = (xc-46, yc-40, xc+46, yc+40)
        mask = np.zeros(full.size[::-1], dtype=np.uint8)
        mask[coords[:, 0], coords[:, 1]] = 96
        under = full.copy()
        under.paste("#59e3c5", (0, 0, *full.size), Image.fromarray(mask))
        full_outline = ImageDraw.Draw(full)
        full_outline.rectangle(bounds, outline="#32d1bf" if name == "pin" else "#ffa957", width=2)
        draw.text((20, 98+201*i), name.title(), font=font, fill="#242822")
        for j, img in enumerate((display(images["unchanged"]), under, display(images[name]))):
            crop = img.crop(bounds).resize((207, 180), Image.Resampling.NEAREST)
            panel.paste(crop, (114+235*j, 75+201*i))
    full.save(out / "mask_locations.png")
    panel.save(out / "paired_crops.png")


def freeze(args):
    if (args.out / "frozen_inputs.json").exists():
        raise FileExistsError("Frozen inputs already exist")
    site.addsitedir(str(args.deps.resolve()))
    sys.path.insert(0, str(args.upstream.resolve()))
    from tsr.utils import ImagePreprocessor, resize_foreground

    torch.set_num_threads(4)
    processor = ImagePreprocessor()
    prior = read_json(REPLAY)
    pilot = read_json(PILOT / "frozen_inputs.json")
    original_path, proposed_path = (INPUTS / f"{name}_rgba.png" for name in ("original", "pin"))
    for path in (original_path, proposed_path):
        if replay.hash_file(path) != pilot["source_conditions"][path.name]:
            raise ValueError(f"Archived source input changed: {path}")
    with Image.open(original_path) as rgb, Image.open(proposed_path) as proposed_rgb:
        original, crop_size = crop_rgb(rgb, resize_foreground, processor)
        candidate, candidate_size = crop_rgb(proposed_rgb, resize_foreground, processor)
        alpha = np.array(rgb)[..., 3]
        if (not np.array_equal(alpha, np.asarray(proposed_rgb)[..., 3]) or crop_size != candidate_size or
                replay.hash_array(original) != prior["pin_trace"]["model_rgb_sha256"]):
            raise ValueError("Source crop or archived unchanged tokenizer input changed")
    masks = {name: transport(alpha, release_mask(name, pilot, alpha.shape), resize_foreground, processor) > 0.5
             for name in ("pin", "peel")}
    valid = transport(alpha, alpha == 255, resize_foreground, processor) >= 1 - 1e-7
    shift_xy = np.rint(np.array(pilot["translation"]["offset_xy_px"]) * replay.SIZE / crop_size).astype(int)
    shift = shift_xy[::-1]
    pin = np.argwhere(masks["pin"] & valid)
    peel = pin + shift
    in_frame = np.all((peel >= 0) & (peel < replay.SIZE), axis=1)
    pin, peel = pin[in_frame], peel[in_frame]
    keep = (masks["peel"] & valid)[peel[:, 0], peel[:, 1]]
    pin, peel = pin[keep], peel[keep]
    if len(pin) == 0 or set(map(tuple, pin)) & set(map(tuple, peel)):
        raise ValueError("Common paired mask is empty or overlapping")
    delta, caps = matched_delta(original, pin, peel, candidate - original)
    sites = {"pin": pin, "peel": peel}
    images = {"unchanged": original, "noop": apply(original, pin, np.zeros_like(delta))}
    images.update({name: apply(original, xy, delta) for name, xy in sites.items()})
    checks = check_edits(images, sites, delta)
    for name, image in images.items():
        received = processor([image], replay.SIZE)[0].numpy()
        np.testing.assert_array_equal(received, image, err_msg=f"512-pixel pass-through changed {name}")
    save_crops(args.out, images, sites)
    arrays = args.out / "inputs.npz"
    np.savez_compressed(arrays, **images, pin_yx=pin, peel_yx=peel, delta=delta)
    write_json(args.out / "frozen_inputs.json", {
        "stage": "matched_rgb_frozen_before_edited_inference", "frame": prior["frame"],
        "code_and_replay_sha256": protocol_hashes(), "input_archive_sha256": replay.hash_file(arrays),
        "source_sha256": {p.name: replay.hash_file(p) for p in
                          (original_path, proposed_path, PILOT / "pin_mask.png", PILOT / "peel_mask.png")},
        "images_sha256": {k: replay.hash_array(v) for k, v in images.items()},
        "visuals_sha256": {p: replay.hash_file(args.out/p) for p in ("paired_crops.png", "mask_locations.png")},
        "crop_size": crop_size, "shift_xy_model_px": shift_xy.tolist(),
        "transported_support_pixels": {k: int(m.sum()) for k, m in masks.items()},
        "checks": checks, "edit_construction": caps, "camera_transform": prior["metric"],
    })
    print(json.dumps({"checks": checks, "edit_construction": caps}), flush=True)


def distance(a, b):
    from potato3d.geometry import sample_surface

    points, _ = sample_surface(a, 20000, 133)
    scene = o3d.t.geometry.RaycastingScene(nthreads=1)
    scene.add_triangles(o3d.core.Tensor(b.vertices.astype(np.float32)),
                        o3d.core.Tensor(b.faces.astype(np.uint32)))
    return scene.compute_distance(o3d.core.Tensor(points.astype(np.float32)), nthreads=1).numpy()


def surface(a, b, scale):
    values = np.concatenate((distance(a, b), distance(b, a))).astype(np.float64)
    native = {"mean": float(values.mean()), "p95": float(np.quantile(values, 0.95)), "max": float(values.max())}
    return {"native_units": native, "approx_mm": {k: v*scale for k, v in native.items()}}


def score(args):
    if (args.out / "no_op_replay.json").exists():
        raise FileExistsError("Use a new output directory for a reproduction")
    frozen_path = args.out / "frozen_inputs.json"
    frozen, prior = read_json(frozen_path), read_json(REPLAY)
    arrays = args.out / "inputs.npz"
    if (frozen["stage"] != "matched_rgb_frozen_before_edited_inference" or
            frozen["code_and_replay_sha256"] != protocol_hashes() or
            frozen["input_archive_sha256"] != replay.hash_file(arrays) or
            frozen["camera_transform"] != prior["metric"]):
        raise ValueError("Frozen protocol or inputs changed")
    with np.load(arrays, allow_pickle=False) as saved:
        images = {name: saved[name] for name in CONDITIONS}
        check_edits(images, {name: saved[f"{name}_yx"] for name in ("pin", "peel")}, saved["delta"])
    if any(replay.hash_array(v) != frozen["images_sha256"][k] for k, v in images.items()):
        raise ValueError("Frozen tensor hash changed")
    asset_hashes = {k: replay.hash_file(args.checkpoint / name) for k, name in
                    (("checkpoint_sha256", "model.ckpt"), ("config_sha256", "config.yaml"),
                     ("dino_config_sha256", "dino_config.json"))}
    if (any(prior[k] != value for k, value in asset_hashes.items()) or
            read_json(args.checkpoint / "source_revision.json")["sha"] != prior["upstream_source"]):
        raise ValueError("Checkpoint or released configuration differs from the verified replay")
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(133)
    model, _ = replay.load_model(args)
    results, meshes = {}, {}

    def run(name):
        mesh, record = replay.predict(model, torch.from_numpy(images[name]))
        if record["tokenizer_input_sha256"] != frozen["images_sha256"][name]:
            raise ValueError(f"{name} tensor changed before normalization")
        valid = record["watertight"] and mesh.is_winding_consistent and np.isfinite(mesh.volume) and mesh.volume > 0
        record["valid_mesh"] = bool(valid)
        results[name], meshes[name] = record, mesh
        mesh.export(args.out / f"{name}_normalized.ply")
        print(f"{name}: {record['forward_and_mesh_seconds']:.2f}s, {record['faces']} faces, valid={valid}", flush=True)

    run("unchanged")
    run("noop")
    if (any(results["unchanged"][k] != prior["passes"][0][k] or
            results["unchanged"][k] != results["noop"][k] for k in HASHES) or
            any(not r["valid_mesh"] or r["solid_grid_nodes_on_boundary"] for r in results.values())):
        raise ValueError("Unchanged/no-op replay failed. Edited inference was skipped.")
    scale = frozen["camera_transform"]["uniform_mm_per_normalized_unit"]
    self_distance = surface(meshes["unchanged"], meshes["unchanged"], scale)
    no_op_distance = surface(meshes["unchanged"], meshes["noop"], scale)
    write_json(args.out / "no_op_replay.json", {
        "stage": "exact_no_op_verified_before_edited_inference", "passed": True,
        "frozen_inputs_sha256": replay.hash_file(frozen_path), "unchanged": results["unchanged"],
        "noop": results["noop"], "self_distance": self_distance, "no_op_distance": no_op_distance,
    })
    print(f"Exact archive and no-op replay passed. Self-distance {self_distance['native_units']['mean']:.3g} model units.",
          flush=True)
    for name in ("pin", "peel"):
        run(name)
        record = results[name]
        record["density_field_changed"] = record["density_sha256"] != results["unchanged"]["density_sha256"]
        record["displacement"] = None
        if record["valid_mesh"] and record["solid_grid_nodes_on_boundary"] == 0:
            record["displacement"] = surface(meshes["unchanged"], meshes[name], scale)
    displacement = [results[k]["displacement"] for k in ("pin", "peel")]
    contrast = None
    if all(value is not None for value in displacement):
        pin, peel = displacement
        contrast = {u: pin[u]["mean"] - peel[u]["mean"] for u in ("native_units", "approx_mm")}
    write_json(args.out / "results.json", {
        "frame": prior["frame"], "grid": replay.GRID, "threshold": replay.THRESHOLD,
        "frozen_inputs_sha256": replay.hash_file(frozen_path),
        "no_op_replay_sha256": replay.hash_file(args.out / "no_op_replay.json"),
        "asset_sha256": asset_hashes, "uniform_mm_per_native_unit": scale, "self_distance": self_distance,
        "no_op_distance": no_op_distance, "conditions": results, "pin_minus_peel": contrast,
    })
    print(json.dumps({"pin_minus_peel": contrast, "edit_displacements": displacement}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "score"))
    assets = Path("outputs/corepp_cross_model/triposr")
    parser.add_argument("--upstream", type=Path, default=assets / "TripoSR-main")
    parser.add_argument("--deps", type=Path, default=assets / "deps")
    parser.add_argument("--checkpoint", type=Path, default=assets)
    parser.add_argument("--out", type=Path, default=HERE / "triposr_pin_pilot")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"freeze": freeze, "score": score}[args.phase](args)


if __name__ == "__main__":
    main()
