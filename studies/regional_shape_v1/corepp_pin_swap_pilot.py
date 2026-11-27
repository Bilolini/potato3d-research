"""Paired color-swap pilot on the one archived CoRe++ development frame."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2 as cv
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import corepp_pin_accuracy as accuracy
from . import corepp_pin_confirmation as confirmation
from . import corepp_pin_grid_boundary as grid
from .corepp_pin_multituber import audit, pilot
from . import corepp_pin_multituber as multi

PROTOCOL = audit.HERE / "corepp_pin_swap_pilot_protocol.md"
PILOT = audit.HERE / "corepp_pin_pilot"
FRAME = "364"
LAYOUTS = ("native", "swapped")
SITES = ("pin", "peel")
CONDITIONS = ("base", *SITES)
SIGN_TOL_MM = pilot.SURFACE_TOL_MM


def archive(args):
    manifest = audit.read_json(PILOT / pilot.INPUTS)
    earlier = audit.read_json(PILOT / pilot.RESULTS)
    noop = audit.read_json(PILOT / pilot.NOOP)
    if ((earlier["tuber"], earlier["frame"]) != (audit.OBJECT, FRAME) or noop["status"] != "passed" or
            earlier["frozen_inputs_sha256"] != audit.sha256(PILOT / pilot.INPUTS) or
            earlier["no_op_sha256"] != audit.sha256(PILOT / pilot.NOOP)):
        raise ValueError("Pilot archive does not identify the registered development frame")
    for folder, hashes in ((args.pilot_input_dir, manifest["source_conditions"]),
                           (PILOT, manifest["evidence_sha256"])):
        if any(audit.sha256(folder / name) != digest for name, digest in hashes.items()):
            raise ValueError(f"Archived pilot files changed in {folder}")
    pin_path = args.source / audit.PIN_LABELS
    if audit.sha256(pin_path) != manifest["source_hashes"]["pin_annotation"]:
        raise ValueError("The release pin annotation changed")
    labels = audit.read_json(pin_path)
    image, = [r for r in labels["images"] if r["file_name"] == "2R1-10/2R1-10_rgb_364.png"]
    pin, = [r for r in labels["annotations"] if r["image_id"] == image["id"]]
    if pin["id"] != manifest["crop_and_mask_trace"]["coco_annotation_id"]:
        raise ValueError("The release annotation does not match the archived crop")
    return manifest, earlier, noop, pin


def input_path(directory, layout, condition):
    return directory / f"{layout}_{condition}_rgba.png"


def exchange(rgb, locations, swapped):
    result = rgb.copy()
    sources = locations[::-1] if swapped else locations
    for destination, source in zip(locations, sources, strict=True):
        dy, dx = destination
        sy, sx = source
        result[dy, dx, :3] = rgb[sy, sx, :3]
    return result


def read_image(path):
    with Image.open(path) as image:
        return np.array(image)


def crops(previews, masks, target):
    y, x = np.nonzero(masks["pin"] | masks["peel"])
    box = (int(x.min()) - 14, int(y.min()) - 14, int(x.max()) + 15, int(y.max()) + 15)
    size = ((box[2] - box[0]) * 2, (box[3] - box[1]) * 2)
    width, height = size
    margin, gap = 12, 12
    title_height, row_title = 39, 25
    canvas = Image.new("RGB", (3 * width + 2 * gap + 2 * margin,
                              title_height + 2 * (height + row_title) + margin), "white")
    draw = ImageDraw.Draw(canvas)
    title_font = ImageFont.load_default(size=18)
    row_font = ImageFont.load_default(size=16)
    col_font = ImageFont.load_default(size=14)
    ink = "#213040"
    draw.text((margin, 8), "2R1-10 / 364   ·   Model RGB crops at 2x", fill=ink, font=title_font)
    for i, layout in enumerate(LAYOUTS):
        y0 = title_height + i * (height + row_title)
        for j, condition in enumerate(CONDITIONS):
            x0 = margin + j * (width + gap)
            suffix = {"base": "Base", "pin": "Edit original pin site", "peel": "Edit original peel site"}[condition]
            draw.text((x0, y0), f"{layout.title()} · {suffix}", fill=ink, font=row_font if j == 0 else col_font)
            image = Image.fromarray(previews[layout][condition]).crop(box).resize(size, Image.Resampling.NEAREST)
            canvas.paste(image, (x0, y0 + row_title))
    canvas.save(target)
    return list(box)


def prepare(args, runtime, archived, annotation):
    out, local = args.out_dir, args.input_dir
    local.mkdir(parents=True, exist_ok=False)
    for filename in ("depth.png", "intrinsic.json"):
        (local / filename).write_bytes((args.pilot_input_dir / filename).read_bytes())
    if audit.sha256(runtime.camera) != archived["source_conditions"]["intrinsic.json"]:
        raise ValueError("The runtime camera differs from the archived camera")
    runtime.bind(local, annotation)

    baseline = read_image(args.pilot_input_dir / "original_rgba.png")
    original_rgb = read_image(PILOT / "original_input_rgb.png")
    masks = {site: read_image(PILOT / f"{site}_mask.png").astype(bool) for site in SITES}
    if any(m.shape != original_rgb.shape[:2] for m in masks.values()) or (masks["pin"] & masks["peel"]).any():
        raise ValueError("The pilot masks overlap or do not match the input crop")
    model_locations = [np.nonzero(masks[site]) for site in SITES]
    dx, dy = archived["translation"]["offset_xy_px"]
    np.testing.assert_array_equal(model_locations[1][0], model_locations[0][0] + dy)
    np.testing.assert_array_equal(model_locations[1][1], model_locations[0][1] + dx)

    trace = archived["crop_and_mask_trace"]
    row, col = trace["crop_origin_yx_px"]
    left, top, _, _ = trace["pad_ltrb_px"]
    locations = [(y + row - top, x + col - left) for y, x in model_locations]
    depths = cv.imread(str(local / "depth.png"), cv.IMREAD_UNCHANGED)
    depth_by_site = {n: {k: float(f(depths[location])) for k, f in (("mean", np.mean), ("min", np.min), ("max", np.max))}
                     for n, location in zip(SITES, locations, strict=True)}
    context = argparse.Namespace(rgba=baseline, depth=depths, pin=annotation)
    _, valid, pin, _ = pilot.model_masks(context, trace)
    np.testing.assert_array_equal(pin, masks["pin"])
    if not valid[masks["peel"]].all() or audit.array_sha256(valid) != archived["valid_mask_sha256"]:
        raise ValueError("Archived masks do not reproduce the valid depth support")
    deltas = []
    for site in SITES:
        edited = read_image(PILOT / f"{site}_input_rgb.png")
        deltas.append(edited[masks[site]].astype(np.int16) - original_rgb[masks[site]])
    np.testing.assert_array_equal(*deltas)
    delta = deltas[0]
    if audit.array_sha256(delta) != archived["intended_rgb_delta_sha256"]:
        raise ValueError("The recovered RGB changes differ from the archived edit")
    np.save(out / "rgb_delta.npy", delta, allow_pickle=False)
    for name in SITES:
        (out / f"{name}_mask.png").write_bytes((PILOT / f"{name}_mask.png").read_bytes())

    union = masks["pin"] | masks["peel"]
    source_union = np.zeros(baseline.shape[:2], dtype=bool)
    for yz in locations:
        source_union[yz] = True

    previews, tensors, change_checks = {}, {}, {}
    twice_equal = False
    for layout in LAYOUTS:
        swapped = layout == "swapped"
        base = exchange(baseline, locations, swapped)
        if swapped:
            np.testing.assert_array_equal(exchange(base, locations, swapped), baseline)
            twice_equal = True
        else:
            np.testing.assert_array_equal(base, baseline)
        np.testing.assert_array_equal(base[~source_union], baseline[~source_union])
        previews[layout], tensors[layout], change_checks[layout] = {}, {}, {}
        for condition in CONDITIONS:
            if condition == "base":
                rgba = base
            else:
                y, x = locations[SITES.index(condition)]
                proposed = base[y, x, :3].astype(np.int16) + delta
                if np.any((proposed < 0) | (proposed > 255)):
                    raise ValueError(f"RGB clipping in {layout}/{condition}")
                rgba = pilot.apply_delta(base, y, x, delta)
                changed = np.any(rgba != base, axis=2)
                if int(changed.sum()) != int(changed[y, x].sum()):
                    raise ValueError(f"Unexpected source-pixel changes in {layout}/{condition}")
            path = input_path(local, layout, condition)
            Image.fromarray(rgba).save(path)
            np.testing.assert_array_equal(read_image(path), rgba)
            np.testing.assert_array_equal(rgba[:, :, 3], baseline[:, :, 3])
            tensor, rgb, observed_trace = runtime.prepare(path, pilot.SEEDS[0])
            if observed_trace != trace or audit.array_sha256(tensor.numpy()[:, 3]) != archived["depth_channel_sha256"]:
                raise ValueError(f"Crop or model depth changed in {layout}/{condition}")
            if layout == "native":
                name = "original" if condition == "base" else condition
                if audit.array_sha256(tensor.numpy()) != archived["preprocessed_tensor_sha256"][name]:
                    raise ValueError(f"Native tensor differs from the archive in {condition}")
            if condition == "base":
                np.testing.assert_array_equal(rgb[~union], original_rgb[~union])
                sources = SITES[::-1] if swapped else SITES
                for dst, src in zip(SITES, sources, strict=True):
                    np.testing.assert_array_equal(rgb[masks[dst]], original_rgb[masks[src]])
            else:
                base_rgb = previews[layout]["base"]
                mask = masks[condition]
                np.testing.assert_array_equal(rgb[~mask], base_rgb[~mask])
                np.testing.assert_array_equal(rgb[mask].astype(np.int16) - base_rgb[mask], delta)
                change_checks[layout][condition] = pilot.rgb_change(base_rgb, rgb, mask) | {"clipped_channels": 0}
            previews[layout][condition] = rgb
            tensors[layout][condition] = audit.array_sha256(tensor.numpy())
            Image.fromarray(rgb).save(out / f"{layout}_{condition}_rgb.png")

    figure = out / "native_swapped_crops.png"
    box = crops(previews, masks, figure)
    # Save exactly the inputs inspected and used by the model.
    evidence = ["rgb_delta.npy", figure.name, *(f"{site}_mask.png" for site in SITES),
                *(f"{layout}_{condition}_rgb.png" for layout in LAYOUTS for condition in CONDITIONS)]
    pilot.put_json(out / "intake.json", {
        "tuber": audit.OBJECT, "frame": FRAME, "tensors_sha256": tensors, "identical_rgb_checks": change_checks,
        "native_identity_copy_exact": True, "double_swap_rgba_exact": twice_equal,
        "alpha_out_of_mask_and_depth_invariant": True, "depth_by_site_in_mm": depth_by_site,
        "rgb_delta_array_sha256": audit.array_sha256(delta), "expanded_origin_model_crop_xyxy": box,
        "annotation": annotation, "valid_mask_sha256": archived["valid_mask_sha256"],
        "cpu_runtime_provenance": runtime.provenance_record,
        "raw_files_sha256": multi.hashes(local), "evidence_sha256": {f: audit.sha256(out / f) for f in evidence},
    })
    print("Verified six input tensors, identical four-site deltas, and lossless swap round-trip", flush=True)


def verify_intake(args, annotation):
    intake = audit.read_json(args.out_dir / "intake.json")
    if (intake["tuber"], intake["frame"], intake["annotation"]) != (audit.OBJECT, FRAME, annotation):
        raise ValueError("Intake does not match the pilot frame")
    for folder, hashes in ((args.out_dir, intake["evidence_sha256"]), (args.input_dir, intake["raw_files_sha256"])):
        if any(audit.sha256(folder / name) != digest for name, digest in hashes.items()):
            raise ValueError(f"Intake files changed under {folder}")
    return intake


def provenance():
    return {f.name: audit.sha256(f) for f in (Path(__file__), PROTOCOL,
            PILOT / pilot.INPUTS, PILOT / pilot.NOOP, PILOT / pilot.RESULTS,
            confirmation.GRID_DIR / grid.FREEZE, confirmation.GRID_DIR / grid.GRID_FILE,
            Path(pilot.__file__), Path(multi.__file__), Path(grid.__file__),
            Path(confirmation.__file__), Path(accuracy.__file__))}


def seal(args, annotation):
    verify_intake(args, annotation)
    if args.review is None:
        raise ValueError("The six crops need visual review before sealing")
    review = audit.read_json(args.review)
    if review["status"] != "reviewed" or review["crop_sha256"] != audit.sha256(args.out_dir / "native_swapped_crops.png"):
        raise ValueError("The supplied visual review does not match the crop")
    pilot.put_json(args.out_dir / "frozen_inputs.json", {
        "stage": "sealed_before_inference", "intake_sha256": audit.sha256(args.out_dir / "intake.json"),
        "review_sha256": audit.sha256(args.review), "review": review, "provenance_sha256": provenance(),
        "cpu_seeds": list(pilot.SEEDS), "geometry_order": "canonical vertex and face ordering for surface metric",
    })


def native_hashes_match(result, old, seed, condition):
    if condition == "base":
        expected = next(row["hashes"] for row in old[1]["pairs"] if row["seed"] == seed)
    else:
        expected = next(row[condition]["hashes"] for row in old[0]["pairs"] if row["seed"] == seed)
    real = result["hashes"]
    if (real["tensor"], real["latent"], real["interior_sdf"]) != (expected["tensor"], expected["latent"], expected["sdf"]):
        raise ValueError(f"Original-lattice native replay differs at {seed}/{condition}")


def verified_intake(args, annotation):
    intake = verify_intake(args, annotation)
    sealed = audit.read_json(args.out_dir / "frozen_inputs.json")
    if (sealed["stage"] != "sealed_before_inference" or sealed["provenance_sha256"] != provenance() or
            sealed["intake_sha256"] != audit.sha256(args.out_dir / "intake.json")):
        raise ValueError("Frozen inputs or code changed")
    return intake


def canonical_mesh(mesh):
    return None if mesh is None else accuracy.ordered_surface(mesh)


def make_noop(args, intake, model, old):
    rows = []
    with TemporaryDirectory(prefix="corepp-swap-noop-") as directory:
        for layout in LAYOUTS:
            base_file = input_path(args.input_dir, layout, "base")
            base = read_image(base_file)
            y, x = np.nonzero(base[:, :, 3] > 0)
            path = Path(directory) / f"{layout}_noop.png"
            Image.fromarray(pilot.apply_delta(base, y, x, np.zeros((len(x), 3), dtype=np.int16))).save(path)
            np.testing.assert_array_equal(read_image(path), base)
            expected = intake["tensors_sha256"][layout]["base"]
            tensors = [model.tensor(current, expected) for current in (base_file, path)]
            for seed in pilot.SEEDS:
                a, b = [model.predict(tensor, seed) for tensor in tensors]
                if layout == "native":
                    native_hashes_match(a, old, seed, "base")
                if a["mesh"] is None or b["mesh"] is None:
                    raise ValueError(f"No-op mesh failure in {layout}/{seed}: {a['mesh_failure'] or b['mesh_failure']}")
                unordered_equal = pilot.same_mesh(a["mesh"], b["mesh"])
                surface = pilot.surface_pair(canonical_mesh(a["mesh"]), canonical_mesh(b["mesh"]))
                if (a["hashes"] != b["hashes"] or a["volume_ml"] != b["volume_ml"] or
                        not surface["identical_mesh_arrays"] or surface["max_mm"] > pilot.SURFACE_TOL_MM):
                    raise ValueError(f"Exact no-op replay failed in {layout}/{seed}")
                rows.append({"layout": layout, "seed": seed, "hashes": a["hashes"], "volumes_ml": [a["volume_ml"], b["volume_ml"]],
                             "raw_mesh_arrays_identical": unordered_equal, "surface_distance": surface})
    pilot.put_json(args.out_dir / "no_op_replay.json", {"status": "passed", "frozen_inputs_sha256": audit.sha256(args.out_dir / "frozen_inputs.json"),
                                                      "pairs": rows, "surface_tolerance_mm": pilot.SURFACE_TOL_MM})
    print(f"Passed all {len(rows)} exact no-op pairs", flush=True)


def measure(a, b):
    latent = float(np.linalg.norm(a["latent"] - b["latent"]))
    one, two = (canonical_mesh(run["mesh"]) for run in (a, b))
    surface = None
    if one is not None and two is not None:
        surface = 0.0 if pilot.same_mesh(one, two) else pilot.surface_pair(one, two)["mean_mm"]
    return {"surface_mm": surface, "latent_l2": latent}


def sign_summary(values):
    result = pilot.summarize(values)
    result.update(positive=sum(v > SIGN_TOL_MM for v in values), negative=sum(v < -SIGN_TOL_MM for v in values),
                  tied=sum(abs(v) <= SIGN_TOL_MM for v in values))
    return result


def summarize(rows):
    stats = {}
    for layout in LAYOUTS:
        block = {}
        for site in SITES:
            parts = [row[layout]["edits"][site] for row in rows]
            block[site] = {name: pilot.summarize([p[name] for p in parts if p[name] is not None])
                           for name in ("surface_mm", "latent_l2")}
        block["pin_minus_peel_mm"] = sign_summary([row[layout]["pin_minus_peel_mm"] for row in rows
                                                   if row[layout]["pin_minus_peel_mm"] is not None])
        stats[layout] = block
    stats["swapped_minus_native_contrast_mm"] = sign_summary([row["swapped_minus_native_contrast_mm"] for row in rows
                                                              if row["swapped_minus_native_contrast_mm"] is not None])
    stats["base_swap"] = {name: pilot.summarize([row["base_swap"][name] for row in rows if row["base_swap"][name] is not None])
                          for name in ("surface_mm", "latent_l2")}
    return stats


def score(args, intake, model, old):
    path = args.out_dir / "results.json"
    if path.exists():
        raise FileExistsError(path)
    no_op = audit.read_json(args.out_dir / "no_op_replay.json")
    required = {(layout, seed) for layout in LAYOUTS for seed in pilot.SEEDS}
    if (no_op["status"] != "passed" or no_op["frozen_inputs_sha256"] != audit.sha256(args.out_dir / "frozen_inputs.json") or
            {(r["layout"], r["seed"]) for r in no_op["pairs"]} != required):
        raise ValueError("The complete expanded-grid no-op must pass before scoring")
    replayed = {(r["layout"], r["seed"]): r for r in no_op["pairs"]}
    tensors = {layout: {name: model.tensor(input_path(args.input_dir, layout, name), intake["tensors_sha256"][layout][name])
                        for name in CONDITIONS} for layout in LAYOUTS}
    rows = []
    for seed in pilot.SEEDS:
        row = {"seed": seed, "outer_seed": model.shell_seeds[str(seed)]}
        bases = {}
        for layout in LAYOUTS:
            runs = {name: model.predict(tensors[layout][name], seed) for name in CONDITIONS}
            base = bases[layout] = runs["base"]
            expected = replayed[layout, seed]
            if base["hashes"] != expected["hashes"] or base["volume_ml"] != expected["volumes_ml"][0]:
                raise ValueError(f"The unchanged layout differs from no-op replay in {layout}/{seed}")
            if layout == "native":
                for name, result in runs.items():
                    native_hashes_match(result, old, seed, name)
            edits = {name: measure(base, runs[name]) for name in SITES}
            pin, peel = (edits[site]["surface_mm"] for site in SITES)
            row[layout] = {"edits": edits, "pin_minus_peel_mm": None if pin is None or peel is None else pin - peel,
                           "predictions": {name: {k: run[k] for k in ("hashes", "mesh_failure", "boundary", "volume_ml")}
                                           for name, run in runs.items()}}
        row["base_swap"] = measure(bases["native"], bases["swapped"])
        a, b = (row[layout]["pin_minus_peel_mm"] for layout in LAYOUTS)
        row["swapped_minus_native_contrast_mm"] = None if a is None or b is None else b - a
        rows.append(row)

    summary = summarize(rows)
    prior = old[0]
    legacy = {"grid_points": prior["grid_size"], "contrast": prior["pin_minus_peel_surface_mm"],
              "positive": prior["primary_pairs_positive"], "negative": prior["primary_pairs_negative"],
              "tied": prior["primary_pairs_tied"]}
    predictions = [r[layout]["predictions"][c] for r in rows for layout in LAYOUTS for c in CONDITIONS]
    summary["checks"] = {"predictions": len(predictions), "mesh_failures": sum(bool(p["mesh_failure"]) for p in predictions),
                         "outer_grid_contacts": sum(p["boundary"]["inside_on_any_logical_grid_face"] > 0 for p in predictions),
                         "mesh_boundary_contacts": sum(bool(p["boundary"]["mesh_faces_touched"]) for p in predictions),
                         "no_op_pairs_passed": len(replayed)}
    pilot.put_json(path, {"tuber": audit.OBJECT, "frame": FRAME, "sign_tolerance_mm": SIGN_TOL_MM,
                          "frozen_inputs_sha256": audit.sha256(args.out_dir / "frozen_inputs.json"),
                          "no_op_sha256": audit.sha256(args.out_dir / "no_op_replay.json"),
                          "legacy_native_20_cubed": legacy, "summary": summary, "pairs": rows})
    print(f"Scored {len(rows)} paired seeds on the one registered frame", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "seal", "noop", "score"))
    for name in ("source", "upstream", "released", "pilot-input-dir", "input-dir", "out-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    archived, earlier, noop, pin = archive(args)
    if args.phase == "prepare":
        runtime = multi.Runtime(args)
        prepare(args, runtime, archived, pin)
    elif args.phase == "seal":
        seal(args, pin)
    else:
        intake = verified_intake(args, pin)
        # Model verifies all upstream and checkpoint hashes and the archived 30³ grid.
        model = confirmation.Model(args, intake["cpu_runtime_provenance"])
        model.runtime.bind(args.input_dir, pin)
        action = make_noop if args.phase == "noop" else score
        action(args, intake, model, (earlier, noop))


if __name__ == "__main__":
    main()
