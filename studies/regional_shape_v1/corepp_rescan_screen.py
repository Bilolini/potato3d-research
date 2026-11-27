"""Evaluate one predeclared scan-only screen at an exact two-rescan budget."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
from itertools import combinations
import multiprocessing
from pathlib import Path
import platform
from statistics import mean, median
from time import perf_counter, process_time

import cv2 as cv
import numpy as np
from PIL import Image
import torch

from . import corepp_pin_confirmation as cpu
from . import corepp_pin_grid_boundary as grid
from . import corepp_pin_multituber as multi
from . import corepp_pin_swap_pilot as swap
from .corepp_pin_multituber import audit, pilot

PROTOCOL = audit.HERE / "corepp_rescan_screen_protocol.md"
TARGET = audit.HERE / "corepp_pin_accuracy/per_potato.csv"
TARGET_FIELD = "original_error_median_mm"
GRID = cpu.GRID_DIR
ARCHIVE_NAMES = (grid.FREEZE, grid.GRID_FILE, grid.REPLAY, grid.RESULTS)
GAINS = {"gain09": 9, "gain10": 10, "gain11": 11}
BUDGET = 2
MODEL = None


def files_for(frame, folder):
    return {role: folder / frame["tuber"] / name
            for role, name in (("rgb", "original_rgba.png"), ("depth", "depth.png"))}


def code_hashes():
    return {p.name: audit.sha256(p) for p in
            (Path(__file__), PROTOCOL, Path(cpu.__file__), Path(grid.__file__),
             Path(multi.__file__), Path(swap.__file__), Path(swap.accuracy.__file__),
             Path(pilot.__file__), Path(audit.__file__))}


def archive():
    hashes = {name: audit.sha256(GRID / name) for name in ARCHIVE_NAMES}
    manifest = audit.read_json(GRID / grid.FREEZE)
    replay = audit.read_json(GRID / grid.REPLAY)
    expanded = audit.read_json(GRID / grid.RESULTS)
    if (hashes[grid.GRID_FILE] != manifest["expanded_grid_npy_sha256"] or
            replay["frozen_grid_sha256"] != hashes[grid.FREEZE] or
            expanded["frozen_grid_sha256"] != hashes[grid.FREEZE] or
            expanded["interior_replay_sha256"] != hashes[grid.REPLAY]):
        raise ValueError("The native replay and expanded prediction archives do not match the grid")
    frames = list(zip(replay["frames"], expanded["frames"], strict=True))
    if len(frames) != 10 or {a["tuber"]: a["frame"] for a, _ in frames} != multi.EXPECTED:
        raise ValueError("The fixed ten development frames are required")
    if any((a["tuber"], a["frame"]) != (b["tuber"], b["frame"]) for a, b in frames):
        raise ValueError("Archive frame identities differ")
    return hashes, frames


def freeze(args):
    hashes, pairs = archive()
    runtime = multi.Runtime(args)
    frames = []
    for source, _ in pairs:
        row = {name: source[name] for name in ("tuber", "frame")}
        row["raw_sha256"] = {k: audit.sha256(path) for k, path in files_for(row, args.input_dir).items()}
        frames.append(row)
    pilot.put_json(args.out_dir / "frozen_protocol.json", {
        "stage": "frozen_before_scan_scoring_and_reference_join", "code_sha256": code_hashes(),
        "target": str(TARGET.relative_to(audit.HERE)), "target_sha256": audit.sha256(TARGET), "target_field": TARGET_FIELD,
        "acquisition": frames, "archived_grid_and_replay_sha256": hashes,
        "cpu_runtime_provenance": runtime.provenance_record,
        "gains": {k: v / 10 for k, v in GAINS.items()}, "rescan_budget": BUDGET,
        "seeds": list(pilot.SEEDS), "ties": "ascending case-sensitive object ID",
    })
    print("Froze ten frame identities, raw input hashes, gains, rules and target checksum", flush=True)


def frozen_inputs(args):
    frozen = audit.read_json(args.out_dir / "frozen_protocol.json")
    hashes, archive_frames = archive()
    if (frozen["code_sha256"] != code_hashes() or frozen["archived_grid_and_replay_sha256"] != hashes or
            [(r["tuber"], r["frame"]) for r in frozen["acquisition"]] != [(r["tuber"], r["frame"]) for r, _ in archive_frames]):
        raise ValueError("Code, protocol, grid or roster changed after freeze")
    return frozen, archive_frames


def exposed(rgb, valid, numerator):
    value = rgb[valid].astype(np.int16) * numerator / 10
    rounded = np.rint(value)
    result = rgb.copy()
    result[valid] = np.clip(rounded, 0, 255).astype(np.uint8)
    return result, int(np.count_nonzero(rounded > 255))


def prepare_tensors(frame, paths, runtime):
    # Same released mask, filter, crop, padding and normalization as the CPU audit.
    # This path uses raw foreground/depth only; it never loads a marker annotation.
    with Image.open(paths["rgb"]) as image:
        rgba = np.array(image)
    raw_depth = cv.imread(str(paths["depth"]), cv.IMREAD_UNCHANGED)
    if rgba.ndim != 3 or rgba.shape[2] != 4 or raw_depth is None or raw_depth.shape != rgba.shape[:2]:
        raise ValueError("Unexpected RGB-D input shape")
    rgb, alpha = rgba[..., :3].copy(), rgba[..., 3] // 255
    depth = raw_depth.astype(np.float32)
    prepare_images, histogram, pad_cls, get_padding = runtime.preprocessor
    low, high = histogram(depth, alpha, 50, 0.05)
    foreground = alpha != 0
    valid = foreground & (depth != 0) & (depth >= low) & (depth <= high)
    if not foreground.any() or not valid.any():
        raise ValueError("Empty foreground or valid depth")
    rejected = foreground & ~valid
    pad = pad_cls(size=runtime.cfg["input_size"])
    tensors, clipping, rgb_changes = {}, {}, {}
    expected_trace, padded_depth, native_rgb = None, None, None
    variants = {"original": (rgb, 0)} | {name: exposed(rgb, valid, gain) for name, gain in GAINS.items()}
    for name, (image, clipped) in variants.items():
        pilot.set_rng(pilot.SEEDS[0])
        color, masked_depth, mask, origin, *_ = prepare_images(
            image.copy(), depth.copy(), alpha, str(runtime.camera), runtime.cfg["detection_input"])
        h, w = masked_depth.shape
        row, col = map(int, origin)
        area = np.s_[row:row+h, col:col+w]
        np.testing.assert_array_equal(mask.astype(bool), valid[area])
        trace = (row, col, h, w, *get_padding(Image.fromarray(color), runtime.cfg["input_size"]))
        reduced = (masked_depth - runtime.cfg["depth_min"]) / (runtime.cfg["depth_max"] - runtime.cfg["depth_min"])
        reduced[masked_depth == 0] = 0
        new_depth = np.array(pad(reduced))
        new_rgb = np.array(pad(color))
        left, top, right, bottom = trace[4:]
        valid_padded = np.pad(valid[area], ((top, bottom), (left, right)))
        if name == "original":
            expected_trace, padded_depth, native_rgb = trace, new_depth, new_rgb
        else:
            if trace != expected_trace:
                raise ValueError("Exposure changed the crop or padding")
            np.testing.assert_array_equal(new_depth, padded_depth)
            np.testing.assert_array_equal(new_rgb[~valid_padded], native_rgb[~valid_padded])
            # The transformed model RGB must match the intended raw pixel values exactly.
            np.testing.assert_array_equal(new_rgb[valid_padded], image[area][valid[area]])
        tensors[name] = torch.cat((torch.from_numpy(new_rgb).permute(2, 0, 1).float() / 255,
                                   torch.from_numpy(new_depth).unsqueeze(0).float()), dim=0).unsqueeze(0)
        if tensors[name].shape != (1, 4, 304, 304) or not torch.isfinite(tensors[name]).all():
            raise ValueError(f"Invalid model input on {frame['tuber']}/{name}")
        clipping[name] = clipped
        rgb_changes[name] = int(np.count_nonzero(np.any(new_rgb != native_rgb, axis=2)))
    if not torch.equal(tensors["original"], tensors["gain10"]):
        raise ValueError("Gain 1.0 did not reproduce the original input")
    fg, dropped = int(foreground.sum()), int(rejected.sum())
    return tensors, {"foreground_pixels": fg, "depth_rejected_pixels": dropped,
                     "depth_rejected_fraction": dropped / fg, "filter_mm": [float(low), float(high)],
                     "crop_and_pad": expected_trace, "gain_clipped_channels": clipping, "gain_model_rgb_changed_pixels": rgb_changes,
                     "tensor_sha256": {k: audit.array_sha256(t.numpy()) for k, t in tensors.items()}}


def initialize(args, provenance):
    global MODEL
    MODEL = cpu.Model(args, provenance)


def verify_native(run, inner, expanded):
    h = run["hashes"]
    if (any(h[k] != inner["hashes"][k] for k in ("tensor", "latent")) or
            h["interior_sdf"] != inner["hashes"]["sdf"] or h["shell_sdf"] != expanded["shell_sdf_sha256"] or
            h["sdf"] != expanded["expanded_sdf_sha256"] or run["mesh_failure"] or
            abs(run["volume_ml"] - expanded["volume_ml"]) > 1e-8):
        raise ValueError("The unchanged prediction failed the expanded-grid archive replay")


def score_frame(job):
    args, frame, interior, expanded = job
    began_cpu, began_wall = process_time(), perf_counter()
    paths = files_for(frame, args.input_dir)
    if any(audit.sha256(p) != frame["raw_sha256"][k] for k, p in paths.items()):
        raise ValueError("Raw scan input changed since freeze")
    tensors, scan = prepare_tensors(frame, paths, MODEL.runtime)
    rows = []
    for seed, check, old in zip(pilot.SEEDS, interior["seeds"], expanded["pairs"], strict=True):
        if seed != check["seed"] or seed != old["seed"]:
            raise ValueError("Archived seed order changed")
        original = MODEL.predict(tensors["original"], seed)
        verify_native(original, check["conditions"]["original"], old["expanded_grid"]["original"])
        replay = MODEL.predict(tensors["gain10"], seed)
        if replay["mesh_failure"] or original["hashes"] != replay["hashes"] or original["volume_ml"] != replay["volume_ml"]:
            raise ValueError(f"Gain 1.0 replay mismatch at {frame['tuber']}/{seed}")
        same = pilot.surface_pair(swap.canonical_mesh(original["mesh"]), swap.canonical_mesh(replay["mesh"]))
        if not same["identical_mesh_arrays"] or same["max_mm"] > pilot.SURFACE_TOL_MM:
            raise ValueError(f"Gain 1.0 geometry mismatch at {frame['tuber']}/{seed}")
        by_gain = {}
        for name in ("gain09", "gain11"):
            edited = MODEL.predict(tensors[name], seed)
            if edited["mesh_failure"]:
                raise ValueError(f"{frame['tuber']}/{seed}/{name}: {edited['mesh_failure']}")
            by_gain[name] = swap.measure(original, edited) | {k: edited[k] for k in ("hashes", "boundary")}
        rows.append({"seed": seed, "gain10_exact_replay": True, "gain10_max_self_distance_mm": same["max_mm"],
                     "gain10_raw_mesh_arrays_equal": pilot.same_mesh(original["mesh"], replay["mesh"]),
                     "native_hashes": original["hashes"], "native_boundary": original["boundary"], "gains": by_gain,
                     "average_displacement_mm": mean(v["surface_mm"] for v in by_gain.values())})
    return {"tuber": frame["tuber"], "frame": frame["frame"], "scan_only": scan, "seeds": rows,
            "sensitivity_mm": median(r["average_displacement_mm"] for r in rows),
            "cpu_seconds": process_time() - began_cpu, "worker_wall_seconds": perf_counter() - began_wall}


def score(args):
    frozen, archived_frames = frozen_inputs(args)
    out = args.out_dir / "scan_only_scores.json"
    if out.exists():
        raise FileExistsError(out)
    start = perf_counter()
    jobs = [(args, row, a, b) for row, (a, b) in zip(frozen["acquisition"], archived_frames, strict=True)]
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=context, initializer=initialize,
                             initargs=(args, frozen["cpu_runtime_provenance"])) as pool:
        records = []
        for record in pool.map(score_frame, jobs):
            records.append(record)
            print(f"{record['tuber']}: 16 paired seed sets and exact gain 1.0 replay", flush=True)
    exposure = sorted(records, key=lambda r: (-r["sensitivity_mm"], r["tuber"]))
    depth = sorted(records, key=lambda r: (-r["scan_only"]["depth_rejected_fraction"], r["tuber"]))
    ranks = {name: [row["tuber"] for row in ordered] for name, ordered in (("sensitivity", exposure), ("depth", depth))}
    pilot.put_json(out, {
        "frozen_protocol_sha256": audit.sha256(args.out_dir / "frozen_protocol.json"),
        "stage": "scan_only_scores_and_rankings_saved_before_target_join", "records": records, "rankings": ranks,
        "flagged": {name: order[:BUDGET] for name, order in ranks.items()},
        "hardware": platform.platform(), "workers": args.workers,
        "cpu_seconds": sum(r["cpu_seconds"] for r in records), "scoring_wall_seconds": perf_counter() - start,
    })


def write_table(path, records):
    with path.open("x", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def evaluate(args):
    frozen, _ = frozen_inputs(args)
    scores = audit.read_json(args.out_dir / "scan_only_scores.json")
    if (scores["stage"] != "scan_only_scores_and_rankings_saved_before_target_join" or
            scores["frozen_protocol_sha256"] != audit.sha256(args.out_dir / "frozen_protocol.json") or
            audit.sha256(TARGET) != frozen["target_sha256"]):
        raise ValueError("The frozen target, protocol or scan-only scores changed")
    if (args.out_dir / "results.json").exists():
        raise FileExistsError(args.out_dir / "results.json")
    with TARGET.open(newline="") as file:
        target_rows = list(csv.DictReader(file))
    records = {r["tuber"]: r for r in scores["records"]}
    target = {r["potato"]: float(r[TARGET_FIELD]) for r in target_rows if not r["failure"]}
    if set(records) != set(target) or len(target_rows) != 10 or any(not np.isfinite(v) for v in target.values()):
        raise ValueError("Frozen score roster and archived reference errors differ")
    for row in target_rows:
        if row["frame"] != records[row["potato"]]["frame"]:
            raise ValueError(f"Reference frame differs for {row['potato']}")

    def evaluate_pair(flagged):
        return {"flagged": list(flagged), "flagged_errors_mm": [target[x] for x in flagged],
                "accepted_mean_mm": mean(target[n] for n in sorted(target) if n not in flagged)}

    random = [evaluate_pair(pair) for pair in combinations(sorted(target), BUDGET)]
    assert len(random) == 45
    rules = {rule: evaluate_pair(scores["flagged"][rule]) for rule in ("sensitivity", "depth")}
    value = rules["sensitivity"]["accepted_mean_mm"]
    random_values = [row["accepted_mean_mm"] for row in random]
    random_mean = mean(random_values)
    difference = {"sensitivity_minus_depth_mm": value - rules["depth"]["accepted_mean_mm"],
                  "sensitivity_minus_random_mean_mm": value - random_mean}
    conclusion = "lower_error_than_both_baselines" if all(v < 0 for v in difference.values()) else "candidate_closed"
    write_table(args.out_dir / "random_pairs.csv", [
        {"flagged_1": r["flagged"][0], "flagged_1_error_mm": r["flagged_errors_mm"][0],
         "flagged_2": r["flagged"][1], "flagged_2_error_mm": r["flagged_errors_mm"][1],
         "accepted_mean_error_mm": r["accepted_mean_mm"]} for r in random])
    rows = []
    for obj, record in records.items():
        scan = record["scan_only"]
        rows.append({"potato": obj, "frame": record["frame"], TARGET_FIELD: target[obj],
                     "sensitivity_mm": record["sensitivity_mm"], "depth_rejected_fraction": scan["depth_rejected_fraction"],
                     "foreground_pixels": scan["foreground_pixels"], "depth_rejected_pixels": scan["depth_rejected_pixels"],
                     **{f"{rule}_rank": order.index(obj) + 1 for rule, order in scores["rankings"].items()},
                     **{f"{rule}_flagged": obj in pair["flagged"] for rule, pair in rules.items()},
                     "gain10_pairs_passed": sum(s["gain10_exact_replay"] for s in record["seeds"]),
                     "cpu_seconds": record["cpu_seconds"]})
    write_table(args.out_dir / "per_potato.csv", rows)
    pilot.put_json(args.out_dir / "results.json", {
        "frozen_protocol_sha256": audit.sha256(args.out_dir / "frozen_protocol.json"),
        "scan_only_scores_sha256": audit.sha256(args.out_dir / "scan_only_scores.json"),
        "target_sha256": frozen["target_sha256"], "rules": rules, "differences": difference,
        "random": {"n_pairs": len(random), "accepted_mean_mm": random_mean,
                   "min_accepted_mean_mm": min(random_values), "max_accepted_mean_mm": max(random_values),
                   "pairs_with_smaller_accepted_mean": sum(v < value for v in random_values),
                   "pairs_with_equal_accepted_mean": sum(v == value for v in random_values),
                   "pairs_with_larger_accepted_mean": sum(v > value for v in random_values)},
        "decision": conclusion,
    })
    print(audit.read_json(args.out_dir / "results.json"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "score", "evaluate"))
    for name in ("upstream", "released", "input-dir", "out-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    {"freeze": freeze, "score": score, "evaluate": evaluate}[args.phase](args)


if __name__ == "__main__":
    main()
