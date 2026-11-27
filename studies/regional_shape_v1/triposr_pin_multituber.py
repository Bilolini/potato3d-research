"""Freeze and score TripoSR edits on the ten archived CoRe++ development frames."""

import argparse
from collections import Counter
from itertools import combinations
import csv
import json
from pathlib import Path
import platform
import site
import sys
from time import perf_counter

import numpy as np
from PIL import Image, ImageDraw
import torch

from . import triposr_pin_pilot as pilot
from . import corepp_cross_model_replay as replay

HERE = Path(__file__).resolve().parent
STUDY = HERE / "triposr_pin_multituber"
MULTI = HERE / "corepp_pin_multituber"
GRID_RESULTS = HERE / "corepp_pin_grid_boundary/results.json"
SITES = ("pin", "peel1", "peel2", "peel3")
CONDITIONS = ("unchanged", "noop", *SITES)
TIE = 1e-6
COLORS = ("#20dbcb", "#ffbb59", "#ef91ff", "#9ae166")
FAILURES = (ValueError, RuntimeError, OSError, AssertionError)


def hashes(paths):
    return {path.name: replay.hash_file(path) for path in paths}


def sources():
    paths = (Path(__file__), STUDY / "protocol.md", Path(pilot.__file__), pilot.PROTOCOL,
             Path(replay.__file__), pilot.REPLAY, MULTI / "frozen_inputs.json", GRID_RESULTS)
    return {str(p.relative_to(HERE)): replay.hash_file(p) for p in paths}


def asset_hashes(args, prior):
    assets = {f"{key}_sha256": replay.hash_file(args.checkpoint / name)
              for key, name in (("checkpoint", "model.ckpt"), ("config", "config.yaml"),
                                ("dino_config", "dino_config.json"))}
    revision = pilot.read_json(args.checkpoint / "source_revision.json")["sha"]
    if any(prior[k] != v for k, v in assets.items()) or revision != prior["upstream_source"]:
        raise ValueError("Checkpoint, configurations or source revision differ from the pilot")
    return {**assets, "upstream_source": revision, "checkpoint_revision": prior["checkpoint_revision"]}


def source_mask(path, trace, shape):
    row, col = trace["crop_origin_yx_px"]
    height, width = trace["crop_height_width_px"]
    left, top, _, _ = trace["pad_ltrb_px"]
    with Image.open(path) as image:
        crop = np.asarray(image).astype(bool)
    mask = np.zeros(shape, dtype=bool)
    mask[row:row+height, col:col+width] = crop[top:top+height, left:left+width]
    if mask.sum() != crop.sum():
        raise ValueError(f"Mask extends outside the archived crop: {path.name}")
    return mask


def common_sites(support, valid, offsets):
    pin = np.argwhere(support["pin"] & valid)
    for name, shift in offsets.items():
        yx = pin + shift
        in_frame = ((yx >= 0) & (yx < replay.SIZE)).all(axis=1)
        pin, yx = pin[in_frame], yx[in_frame]
        pin = pin[(support[name] & valid)[tuple(yx.T)]]
    sites = {"pin": pin, **{name: pin + shift for name, shift in offsets.items()}}
    if not len(pin) or any(set(map(tuple, a)) & set(map(tuple, b))
                          for a, b in combinations(sites.values(), 2)):
        raise ValueError("Common four-site support is empty or overlaps")
    return sites


def matched_delta(original, sites, proposal):
    base = np.stack([original[tuple(yx.T)] for yx in sites.values()]).astype(np.float64)
    quant = pilot.DELTA_STEPS
    proposed = np.rint(proposal[tuple(sites["pin"].T)] * quant).astype(np.int64)
    lower = np.ceil(-base.min(axis=0) * quant).astype(np.int64)
    upper = np.floor((1 - base.max(axis=0)) * quant).astype(np.int64)
    bounded = np.clip(proposed, lower, upper)
    steps = bounded.copy()
    while True:
        realized = (base + steps / quant).astype(np.float32).astype(np.float64) - base
        unequal = np.any(realized != realized[0], axis=0)
        if not unequal.any():
            break
        steps[unequal] -= np.sign(steps[unequal])
    return realized[0], {"jointly_capped_channels": int(np.count_nonzero(proposed != bounded)),
                         "reduced_for_float32_match": int(np.count_nonzero(bounded != steps)),
                         "quantization_steps_per_rgb_unit": quant}


def display(image):
    return Image.fromarray(np.rint(image * 255).astype(np.uint8))


def save_overlay(folder, images, sites):
    full = display(images["unchanged"])
    draw = ImageDraw.Draw(full)
    panel = Image.new("RGB", (724, 535), "#f1eee7")
    panel.paste(full, (0, 23))
    labels = ImageDraw.Draw(panel)
    labels.text((12, 5), folder.name + "   TripoSR 512 px input", fill="#252826")
    labels.text((528, 5), "Before                 After", fill="#252826")
    for i, (name, color) in enumerate(zip(SITES, COLORS)):
        coords = sites[name]
        yc, xc = np.rint(coords.mean(axis=0)).astype(int)
        for y, x in coords:
            draw.point((int(x), int(y)), fill=color)
        labels.text((520, 24+i*128), name, fill="#252826")
        bounds = (xc-42, yc-42, xc+42, yc+42)
        for j, condition in enumerate(("unchanged", name)):
            crop = display(images[condition]).crop(bounds).resize((91, 91))
            panel.paste(crop, (520+j*98, 40+i*128))
    panel.paste(full, (0, 23))
    panel.save(folder / "overlay.png")


def freeze_frame(args, row, folder, resize, processor):
    tuber = row["tuber"]
    local = args.inputs / tuber
    paths = [local / "original_rgba.png", local / "pin_rgba.png",
             *(MULTI / tuber / f"{name}_mask.png" for name in SITES)]
    input_hashes = hashes(paths)
    expected = row["input_sha256"] | row["evidence_sha256"]
    if row["failure"] or any(expected[k] != v for k, v in input_hashes.items()):
        raise ValueError("Archived input or mask failed provenance check")
    with Image.open(paths[0]) as rgba, Image.open(paths[1]) as pin_edit:
        alpha = np.asarray(rgba)[..., 3]
        original, size = pilot.crop_rgb(rgba, resize, processor)
        candidate, edited_size = pilot.crop_rgb(pin_edit, resize, processor)
        if not np.array_equal(alpha, np.asarray(pin_edit)[..., 3]) or size != edited_size:
            raise ValueError("Archived pin edit changed the geometry of the input")
    masks = {name: source_mask(path, row["crop_trace"], alpha.shape)
             for name, path in zip(SITES, paths[2:])}
    support = {name: pilot.transport(alpha, mask, resize, processor) > .5 for name, mask in masks.items()}
    valid = pilot.transport(alpha, alpha == 255, resize, processor) >= 1-1e-7
    offsets = {name: np.rint(np.asarray(patch["offset_xy_px"])[::-1] * replay.SIZE / size).astype(int)
               for name, patch in zip(SITES[1:], row["patches"]["patches"], strict=True)}
    sites = common_sites(support, valid, offsets)
    delta, cap_stats = matched_delta(original, sites, candidate - original)
    images = {"unchanged": original, "noop": pilot.apply(original, sites["pin"], np.zeros_like(delta))}
    images.update({name: pilot.apply(original, site, delta) for name, site in sites.items()})
    checks = pilot.check_edits(images, sites, delta)
    for name, image in images.items():
        np.testing.assert_array_equal(processor([image], replay.SIZE)[0].numpy(), image, err_msg=name)
    save_overlay(folder, images, sites)
    arrays = folder / "inputs.npz"
    np.savez_compressed(arrays, **images, **{f"{k}_yx": v for k, v in sites.items()}, delta=delta)
    return {"checks": checks, "delta_checks": cap_stats, "source_crop_size": size,
            "resize_shifts_yx": {k: v.tolist() for k, v in offsets.items()},
            "transported_support_pixels": {k: int(v.sum()) for k, v in support.items()},
            "source_sha256": input_hashes, "images_sha256": {k: replay.hash_array(v) for k, v in images.items()},
            "artifacts_sha256": hashes([arrays, folder / "overlay.png"])}


def freeze(args):
    site.addsitedir(str(args.deps.resolve()))
    sys.path.insert(0, str(args.upstream.resolve()))
    from tsr.utils import ImagePreprocessor, resize_foreground

    torch.set_num_threads(4)
    prior = pilot.read_json(pilot.REPLAY)
    archive = pilot.read_json(MULTI / "frozen_inputs.json")
    cohort = [(r["tuber"], r["frame"]) for r in archive["frames"]]
    grid_cohort = [(r["tuber"], r["frame"]) for r in pilot.read_json(GRID_RESULTS)["frames"]]
    if len({t for t, _ in cohort}) != 10 or cohort != grid_cohort or any(t == "2R1-10" for t, _ in cohort):
        raise ValueError("Archived comparison roster mismatch or overlap with pilot")
    assets = asset_hashes(args, prior)
    processor = ImagePreprocessor()
    records = []
    for row in archive["frames"]:
        tuber = row["tuber"]
        folder = args.out / tuber
        folder.mkdir()
        record = {"tuber": tuber, "frame": row["frame"], "matching_failure": None}
        try:
            record.update(freeze_frame(args, row, folder, resize_foreground, processor))
        except FAILURES as error:
            record["matching_failure"] = str(error)
        records.append(record)
        print(tuber, record["matching_failure"] or record["checks"]["pin"], flush=True)
    sheet = Image.new("RGB", (724, 1350), "#f1eee7")
    for i, row in enumerate(records):
        path = args.out / row["tuber"] / "overlay.png"
        origin = (362*(i % 2), 270*(i//2))
        if path.exists():
            with Image.open(path) as panel:
                sheet.paste(panel.resize((362, 267), Image.Resampling.LANCZOS), origin)
        else:
            ImageDraw.Draw(sheet).text(origin, row["tuber"] + "  Matching failed", fill="#252826")
    overlay = args.out / "overlay_sheet.png"
    sheet.save(overlay)
    pilot.write_json(args.out / "frozen_inputs.json", {
        "stage": "all_ten_frozen_before_edited_inference", "sources_sha256": sources(), "assets": assets,
        "grid": replay.GRID, "threshold": replay.THRESHOLD, "triposr_tie_native": TIE,
        "overlay_sheet_sha256": replay.hash_file(overlay), "frames": records,
    })


def read_inputs(out, row):
    folder = out / row["tuber"]
    arrays = folder / "inputs.npz"
    if hashes([arrays, folder / "overlay.png"]) != row["artifacts_sha256"]:
        raise ValueError("Frozen input or overlay hash changed")
    with np.load(arrays, allow_pickle=False) as saved:
        images = {name: saved[name] for name in CONDITIONS}
        pilot.check_edits(images, {name: saved[f"{name}_yx"] for name in SITES}, saved["delta"])
    if any(replay.hash_array(v) != row["images_sha256"][k] for k, v in images.items()):
        raise ValueError("Frozen tensor hash changed")
    return images


def predict(model, image, expected_hash):
    mesh, record = replay.predict(model, torch.from_numpy(image))
    if record["tokenizer_input_sha256"] != expected_hash:
        raise ValueError("Frozen RGB changed before tokenizer normalization")
    radius = model.renderer.cfg.radius
    contacts = np.any(np.abs(np.abs(mesh.vertices) - radius) <= TIE, axis=1)
    record["mesh_vertices_on_boundary"] = int(contacts.sum())
    record["valid_mesh"] = bool(mesh.is_watertight and mesh.is_winding_consistent and
                                np.isfinite(mesh.volume) and mesh.volume > 0 and len(mesh.faces))
    record["failure"] = None
    if not record["valid_mesh"]:
        record["failure"] = "Invalid mesh"
    elif record["solid_grid_nodes_on_boundary"] or record["mesh_vertices_on_boundary"]:
        record["failure"] = "Surface contacted extraction boundary"
    return mesh, record


def direction(value, tolerance):
    if value is None:
        return "unavailable"
    if abs(value) <= tolerance:
        return "tie"
    return "pin" if value > 0 else "peel"


def score(args):
    start = perf_counter()
    frozen_path = args.out / "frozen_inputs.json"
    frozen = pilot.read_json(frozen_path)
    if (frozen["stage"] != "all_ten_frozen_before_edited_inference" or
            frozen["sources_sha256"] != sources() or
            frozen["overlay_sheet_sha256"] != replay.hash_file(args.out / "overlay_sheet.png") or
            frozen["assets"] != asset_hashes(args, pilot.read_json(pilot.REPLAY)) or
            (frozen["grid"], frozen["threshold"], frozen["triposr_tie_native"]) != (replay.GRID, replay.THRESHOLD, TIE)):
        raise ValueError("Frozen protocol or sources changed")
    archive = pilot.read_json(GRID_RESULTS)
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(133)
    model, _ = replay.load_model(args)
    baselines, images_by_tuber, gates = {}, {}, {}
    for row in frozen["frames"]:
        tuber = row["tuber"]
        gate = {"passed": False, "failure": row["matching_failure"], "conditions": {}}
        gates[tuber] = gate
        if not gate["failure"]:
            images = read_inputs(args.out, row)
            try:
                meshes = {}
                for name in ("unchanged", "noop"):
                    meshes[name], gate["conditions"][name] = predict(model, images[name], row["images_sha256"][name])
                a, b = (gate["conditions"][name] for name in ("unchanged", "noop"))
                if a["failure"] or b["failure"] or any(a[k] != b[k] for k in pilot.HASHES):
                    raise ValueError(a["failure"] or b["failure"] or "Exact no-op hashes differ")
                gate["self_distance_native"] = pilot.surface(meshes["unchanged"], meshes["unchanged"], 1)["native_units"]
                gate["no_op_distance_native"] = pilot.surface(meshes["unchanged"], meshes["noop"], 1)["native_units"]
                gate["passed"] = True
                baselines[tuber], images_by_tuber[tuber] = meshes["unchanged"], images
            except FAILURES as error:
                gate["failure"] = str(error)
        print(tuber, "exact no-op passed" if gate["passed"] else gate["failure"], flush=True)
    no_op_path = args.out / "no_op_replay.json"
    pilot.write_json(no_op_path, {"stage": "verified_before_edited_inference",
                                 "frozen_sha256": replay.hash_file(frozen_path), "gates": gates})
    rows, detail = [], {}
    comparisons = {"mean": Counter(), "strongest": Counter()}
    for row, core in zip(frozen["frames"], archive["frames"], strict=True):
        tuber = row["tuber"]
        gate = gates[tuber]
        edits = {}
        detail[tuber] = edits
        if gate["passed"]:
            for name in SITES:
                try:
                    mesh, record = predict(model, images_by_tuber[tuber][name], row["images_sha256"][name])
                    edits[name] = record
                    record["density_field_changed"] = record["density_sha256"] != gate["conditions"]["unchanged"]["density_sha256"]
                    if not record["failure"]:
                        record["displacement_native"] = pilot.surface(baselines[tuber], mesh, 1)["native_units"]
                except FAILURES as error:
                    edits.setdefault(name, {})["failure"] = str(error)
        distances = {k: edits.get(k, {}).get("displacement_native", {}).get("mean") for k in SITES}
        values = list(distances.values())
        paired = all(d is not None for d in values)
        strongest = max(SITES[1:], key=distances.get) if paired else None
        failures = [f"{name}: {record['failure']}" for name, record in edits.items() if record["failure"]]
        conditions = list(gate["conditions"].values()) + list(edits.values())
        result = {"tuber": tuber, "frame": row["frame"], "no_op_passed": gate["passed"],
                  "changed_pixels_per_edit": row.get("checks", {}).get("pin", {}).get("changed_pixels"),
                  "edit_mean_rgb_l2_8bit_equivalent": row.get("checks", {}).get("shared_delta", {}).get("mean_rgb_l2_8bit_equivalent"),
                  **{f"triposr_{k}_displacement_native": v for k, v in distances.items()},
                  "triposr_strongest_patch": strongest, "corepp_strongest_patch": core["expanded"]["strongest_patch"],
                  "valid_meshes": sum(r.get("valid_mesh", False) for r in conditions),
                  "mesh_predictions": len(conditions),
                  "grid_contact_predictions": sum(bool(r.get("solid_grid_nodes_on_boundary")) for r in conditions),
                  "mesh_contact_predictions": sum(bool(r.get("mesh_vertices_on_boundary")) for r in conditions),
                  "failure": gate["failure"] or " | ".join(failures) or None}
        for label, key, peel in (("mean", "primary", np.mean(values[1:]) if paired else None),
                                  ("strongest", "strongest_peel", distances.get(strongest))):
            tripo = float(values[0]-peel) if paired else None
            co = core["expanded"][key]["median"]
            a, b = direction(co, 0), direction(tripo, TIE)
            comparisons[label][f"corepp_{a}__triposr_{b}"] += 1
            result.update({f"triposr_pin_minus_{label}_peel_native": tripo, f"triposr_{label}_direction": b,
                           f"corepp_pin_minus_{label}_peel_mm": co, f"corepp_{label}_direction": a})
        rows.append(result)
        print(tuber, result["triposr_mean_direction"], result["triposr_strongest_direction"], result["failure"] or "", flush=True)
    with (args.out / "per_potato.csv").open("x", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    pilot.write_json(args.out / "results.json", {
        "frozen_sha256": replay.hash_file(frozen_path), "no_op_sha256": replay.hash_file(no_op_path),
        "coverage": sum(r["triposr_mean_direction"] != "unavailable" for r in rows), "enrolled": len(rows),
        "comparisons": comparisons, "rows": rows, "edit_conditions": detail, "elapsed_seconds": perf_counter()-start,
        "platform": platform.platform(), "python": platform.python_version(), "torch": torch.__version__,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "score"))
    assets = Path("outputs/corepp_cross_model/triposr")
    parser.add_argument("--upstream", type=Path, default=assets / "TripoSR-main")
    parser.add_argument("--deps", type=Path, default=assets / "deps")
    parser.add_argument("--checkpoint", type=Path, default=assets)
    parser.add_argument("--inputs", type=Path, default=Path("outputs/corepp_pin_multituber/inputs"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if (args.out / ("frozen_inputs.json" if args.phase == "freeze" else "no_op_replay.json")).exists():
        raise FileExistsError("Use a fresh output directory for each reproduction")
    {"freeze": freeze, "score": score}[args.phase](args)


if __name__ == "__main__":
    main()
