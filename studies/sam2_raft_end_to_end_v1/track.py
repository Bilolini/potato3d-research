"""Freeze the exact sequences and extend the archived human SAM 2 tracks."""

import argparse
from contextlib import ExitStack
from pathlib import Path
import time
from unittest.mock import patch

import numpy as np

import common as c
from studies.sam2_center_weight_v1 import run as sam
from studies.sam2_human_prompt_v1 import score as human
from studies.sam2_pin_prompt_v1 import run as pin


def freeze():
    stimuli, responses, receipt = human.session(c.REPEAT)
    old_path = sam.STUDY / "frame_manifest.json"
    old = c.by_tuber(c.prep.read_json(old_path)["roster"])
    geom_path, traits_path = c.PILOT / "frame_manifest.json", c.TRAIT_STUDY / "frame_manifest.json"
    geometry = c.by_tuber(c.prep.read_json(geom_path)["roster"])
    traits = c.by_tuber([r for r in c.prep.read_json(traits_path)["roster"] if r["split"] == "val"])
    ids = {trial["tuber"] for trial in stimuli["trials"]}
    held = {r["tuber"] for r in c.prep.read_json(c.prep.HELD_OUT)["roster"]}
    reserved = set(held)
    for filename, section, key in c.prep.RESERVES:
        resource = c.prep.read_json(c.ROOT / filename)
        reserved.update(row[key] for row in (resource[section] if section else resource))
    if (len(ids) != 40 or ids != set(old) or len(held) != 45 or ids & reserved
            or len(geometry) != 10 or len(traits) != 30 or set(geometry) & set(traits)
            or ids != set(geometry) | set(traits)):
        raise ValueError("Split or holdout boundary differs from the development protocol")
    if c.prep.digest(sam.CHECKPOINT) != sam.CHECKPOINT_HASH or c.prep.digest(c.prep.CHECKPOINT) != c.prep.CHECKPOINT_HASH:
        raise ValueError("Unexpected checkpoint digest")

    roster = []
    with ExitStack() as stack:
        archives = c.prep.open_images(stack, (case["archive"] for case in old.values()))
        for trial, click in zip(stimuli["trials"], responses, strict=True):
            tuber = trial["tuber"]
            baseline = old[tuber]
            analysis = "geometry" if tuber in geometry else "traits"
            plan = (geometry if analysis == "geometry" else traits)[tuber]
            lower, center, upper = plan["selected_suffixes" if analysis == "geometry" else "selected"]
            archive = archives[baseline["archive"]]
            entry = baseline["entry_suffix_px"]
            rgb = {}
            for info in archive.infolist():
                match = c.prep.IMAGE_KEY.fullmatch(info.filename)
                if match and match["tuber"] == tuber and match["kind"] == "rgb":
                    suffix = int(match["suffix"])
                    if entry <= suffix <= upper:
                        if suffix in rgb:
                            raise ValueError(f"Duplicate RGB suffix {tuber} {suffix}")
                        rgb[suffix] = c.prep.asset(info, baseline["archive"])
            roi = [{"suffix": f["suffix"], "rgb": f["rgb"], "depth": f["depth"]} for f in plan["frames"]]
            before = [(f["suffix_px"], f["rgb_member"], f["crc32"]) for f in baseline["frames"]]
            now = [(s, x["member"], f'{x["crc32"]:08x}') for s, x in sorted(rgb.items()) if s <= center]
            if (not entry < lower < center < upper or before != now or center != baseline["center_suffix_px"]
                    or rgb[entry]["member"] != trial["entry_file"] or rgb[center]["member"] != trial["center_file"]
                    or [f["suffix"] for f in roi] != [s for s in sorted(rgb) if lower <= s <= upper]
                    or any(f["rgb"] != rgb[f["suffix"]] for f in roi)):
                raise ValueError(f"Archived tracking or fusion frames do not replay: {tuber}")
            for f in roi:
                depth = f["depth"]
                spec = c.prep.asset(archives[depth["archive"]].getinfo(depth["member"]), depth["archive"])
                if depth != spec:
                    raise ValueError(f"Raw depth member changed for {tuber} {f['suffix']}")
            archived_track = c.prep.read_json(c.REPEAT / "center_masks" / f"{tuber}.json")
            mask_path = c.REPEAT / "center_masks" / f"{tuber}.png"
            if archived_track["receipt"] != receipt or c.prep.digest(mask_path) != archived_track["mask_sha256"]:
                raise ValueError(f"Archived center mask or click receipt changed: {tuber}")
            roster.append({
                "tuber": tuber, "analysis": analysis, "archive": baseline["archive"],
                "selected": [lower, center, upper], "response": click["response"],
                "trial": click["trial"], "click_xy": [click["x"], click["y"]],
                "frames": [{"suffix_px": s, "rgb_member": x["member"], "crc32": f'{x["crc32"]:08x}', "rgb": x}
                           for s, x in sorted(rgb.items())],
                "links_rgbd": roi, "archived_center_sha256": archived_track["mask_sha256"],
            })
    sources = [Path(__file__), c.STUDY / "common.py", c.STUDY / "protocol.md", old_path, geom_path, traits_path,
               c.REPEAT / "frozen_clicks.csv", c.REPEAT / "trial_manifest.json", c.REPEAT / "click_freeze.json",
               sam.STUDY / "run.py", sam.STUDY / "tracking_config.json", human.STUDY / "score.py",
               c.PILOT / "alignment.py", c.PILOT / "flow.py", c.PILOT / "register.py", c.prep.CAMERA,
               c.TRAIT_STUDY / "train_fit.json", c.prep.HELD_OUT, *(c.ROOT / x[0] for x in c.prep.RESERVES)]
    fit_path = c.TRAIT_STUDY / "train_fit.json"
    source_fits = c.prep.read_json(fit_path)["models"]
    model_map = dict(A="A", B="A", C="D", D="D")
    c.prep.freeze_check(c.STUDY / "frame_manifest.json", {
        "sources_sha256": {str(p.relative_to(c.ROOT)): c.prep.digest(p) for p in sources},
        "sam2_checkpoint_sha256": sam.CHECKPOINT_HASH, "raft_checkpoint_sha256": c.prep.CHECKPOINT_HASH,
        "click_receipt": receipt, "model_source_method": model_map,
        "fits": {trait: {new: fits[old_key] for new, old_key in model_map.items()}
                 for trait, fits in source_fits.items()},
        "roster": roster,
    })
    print(f"Frozen {len(roster)} potatoes, {sum(len(r['frames']) for r in roster)} tracking frames, "
          f"{sum(len(r['links_rgbd'])-1 for r in roster)} RAFT links.", flush=True)


def continue_through_upper(predictor, archive, case, observer):
    """Replay the archived temporal encoding through center before extending the same state."""
    center = case["selected"][1]
    prefix = next(i + 1 for i, frame in enumerate(case["frames"]) if frame["suffix_px"] == center)
    propagate = predictor.propagate_in_video

    def extend(state, start_frame_idx):
        full_length = state["num_frames"]
        if start_frame_idx != 0 or not 0 < prefix < full_length:
            raise ValueError("Unexpected SAM 2 continuation bounds")
        state["num_frames"] = prefix
        try:
            yield from propagate(state, start_frame_idx=0)
        finally:
            state["num_frames"] = full_length
        yield from propagate(state, start_frame_idx=prefix)

    with patch.object(predictor, "propagate_in_video", extend):
        return sam.predict_track(predictor, archive, case, observer)


def track_one(predictor, archive, case, manifest_hash):
    tuber = case["tuber"]
    path = c.track_path(tuber)
    payload = path.with_suffix(".npz")
    record = {"tuber": tuber, "manifest_sha256": manifest_hash, "status": "skipped",
              "failure": None, "center_difference_pixels": None, "mask_sha256": None,
              "entry_click_inside": None, "empty_suffixes": [], "frame_wall_s": [],
              "center_elapsed_s": None, "post_center_wall_s": None, "wall_s": 0.}
    if case["response"] == "cannot_identify":
        return record
    center = case["selected"][1]
    masks, timestamps = {}, []
    last = None
    start = time.perf_counter()

    def observe(index, phase, mask):
        nonlocal last
        suffix = case["frames"][index]["suffix_px"]
        last = time.perf_counter() - start
        if mask.shape != (720, 1280):
            raise ValueError(f"Unexpected shape {mask.shape}")
        if phase == "prompt":
            masks["prompt"] = np.packbits(mask)
            return
        masks[str(suffix)] = np.packbits(mask)
        timestamps.append({"suffix": suffix, "elapsed_s": last})
        if suffix == center:
            record["center_elapsed_s"] = last

    try:
        _, includes_click, empty = continue_through_upper(predictor, archive, case, observe)
        record.update(status="returned", entry_click_inside=includes_click, empty_suffixes=empty)
        if [r["suffix"] for r in timestamps] != [f["suffix_px"] for f in case["frames"]]:
            raise ValueError("Propagation sequence incomplete or out of order")
    except (KeyError, ValueError, RuntimeError, OSError) as error:
        record.update(status="tracking_failure", failure=f"{type(error).__name__}: {error}")
    record["wall_s"] = time.perf_counter() - start
    record["frame_wall_s"] = timestamps
    if record["center_elapsed_s"] is not None:
        record["post_center_wall_s"] = record["wall_s"] - record["center_elapsed_s"]
        expected = pin.load_mask(c.REPEAT / "center_masks" / f"{tuber}.png", case["archived_center_sha256"])
        observed = c.unpack(masks[str(center)])
        record["center_difference_pixels"] = int(np.count_nonzero(expected != observed))
        if not observed.any():
            record.update(status="empty_center", failure="Propagated center mask is empty")

    if masks:
        record["empty_suffixes"] = [int(key) for key, value in masks.items() if key.isdigit() and not value.any()]
        with payload.with_suffix(".tmp").open("wb") as stream:
            np.savez_compressed(stream, **masks)
        payload.with_suffix(".tmp").replace(payload)
        record["mask_sha256"] = c.prep.digest(payload)
    return record


def track(shard, shards):
    import torch

    freeze = c.frame_manifest()
    manifest_hash = c.prep.digest(c.STUDY / "frame_manifest.json")
    config = c.prep.read_json(sam.STUDY / "tracking_config.json")
    if torch.__version__ != config["torch"] or sam.THREADS != config["threads"]:
        raise ValueError("Use the frozen SAM 2 environment")
    (c.OUTPUT / "tracking").mkdir(parents=True, exist_ok=True)
    predictor = None
    with ExitStack() as stack, torch.inference_mode():
        archives = c.prep.open_images(stack, (r["archive"] for r in freeze["roster"]))
        for i, case in enumerate(freeze["roster"], 1):
            if (i - 1) % shards != shard:
                continue
            tuber = case["tuber"]
            path = c.track_path(tuber)
            if path.exists():
                record = c.prep.read_json(path)
                if record["manifest_sha256"] != manifest_hash:
                    raise ValueError(f"Stale track {tuber}")
                if record["mask_sha256"] and c.prep.digest(path.with_suffix(".npz")) != record["mask_sha256"]:
                    raise ValueError(f"Saved masks changed: {tuber}")
            else:
                if predictor is None and case["response"] == "click":
                    predictor = sam.build_cpu_predictor()
                record = track_one(predictor, archives[case["archive"]], case, manifest_hash)
                c.prep.write_json(path, record)
            print(f"Tracked {i}/40 {tuber}: {record['status']}, "
                  f"center difference {record['center_difference_pixels']}, {record['wall_s']:.1f} s", flush=True)


def collect():
    freeze = c.frame_manifest()
    manifest_hash = c.prep.digest(c.STUDY / "frame_manifest.json")
    rows = []
    fields = ("tuber", "status", "failure", "center_difference_pixels", "entry_click_inside",
              "empty_suffixes", "center_elapsed_s", "post_center_wall_s", "wall_s", "mask_sha256")
    for case in freeze["roster"]:
        path = c.track_path(case["tuber"])
        record = c.prep.read_json(path)
        if record["manifest_sha256"] != manifest_hash or record["tuber"] != case["tuber"]:
            raise ValueError(f"Track cache disagrees with frozen inputs: {path}")
        rows.append({**{k: record[k] for k in fields}, "analysis": case["analysis"],
                     "tracking_record_sha256": c.prep.digest(path)})
    results = {
        "manifest_sha256": manifest_hash, "rows": rows,
        "exact_centers": sum(r["center_difference_pixels"] == 0 for r in rows),
        "mismatches": [r["tuber"] for r in rows if r["center_difference_pixels"] not in (0, None)],
        "unverified": [r["tuber"] for r in rows if r["center_difference_pixels"] is None],
    }
    c.write_csv(c.STUDY / "tracking_replay.csv", rows)
    c.prep.write_json(c.STUDY / "tracking_replay.json", results)
    print(f"Exact center replay {results['exact_centers']}/40", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "track", "collect"))
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args()
    if not 0 <= args.shard < args.shards:
        parser.error("Expected 0 <= shard < shards")
    {"freeze": freeze, "track": lambda: track(args.shard, args.shards), "collect": collect}[args.stage]()
