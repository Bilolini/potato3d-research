"""Audit and replay a frozen single-point SAM 2 prompt on the development roster."""

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from pathlib import Path
import sys
import time

import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

STUDY = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY.parents[1]))
from studies.sam2_center_weight_v1 import run as base

PIN_LABELS = base.DATA / "1_rgbd/pin_regions.json"
EXPECTED = {"inside_pin": 12, "inside_pin_ending_on_pin": 12,
            "outside_pin": 28, "outside_pin_ending_on_pin": 4}
CLEARANCE = 5
RECOVERY_IOU = 0.5


def inputs():
    manifest = base.load_manifest(base.STUDY)
    rows = base.read_csv(base.STUDY / "per_potato.csv")
    scores = {row["tuber"]: row for row in rows}
    if list(scores) != [row["tuber"] for row in manifest["roster"]] or len(rows) != len(scores):
        raise ValueError("Archived score IDs differ from the frozen 40-potato roster")
    config = base.read_json(base.STUDY / "tracking_config.json")
    if (config["manifest_sha256"] != base.hash_file(base.STUDY / "frame_manifest.json")
            or config["checkpoint_sha256"] != base.CHECKPOINT_HASH
            or config["source_commit"] != base.SOURCE_COMMIT
            or config["config"] != base.CONFIG
            or config["threads"] != base.THREADS
            or config["device"] != "cpu" or config["precision"] != "fp32"
            or config["interop_threads"] != 1 or config["optional_postprocessing"]):
        raise ValueError("Archived tracker configuration does not match the shared tracker")
    return manifest, scores, config


def load_polygons(manifest):
    members = {f["rgb_member"] for row in manifest["roster"] for f in row["frames"]}
    data = base.read_json(PIN_LABELS)
    images = [im for im in data["images"] if im["file_name"] in members]
    if len(images) != len(members) or {im["file_name"] for im in images} != members:
        raise ValueError("Missing or ambiguous exact pin annotation filename")
    by_id = defaultdict(list)
    pin_id = next(cat["id"] for cat in data["categories"] if cat["name"] == "pin")
    image_ids = {im["id"] for im in images}
    for ann in data["annotations"]:
        if ann["image_id"] in image_ids and ann["category_id"] == pin_id:
            by_id[ann["image_id"]].extend(
                np.asarray(p, dtype=np.float64).reshape(-1, 2) for p in ann["segmentation"]
            )
    if not all(by_id[im["id"]] for im in images):
        raise ValueError("Missing pin polygon on one or more frozen frames")
    return {im["file_name"]: by_id[im["id"]] for im in images}


def annotation_masks(archive, item, polygons):
    name = item["rgb_member"]
    info = archive.getinfo(name)
    if f"{info.CRC:08x}" != item["crc32"]:
        raise ValueError(f"Frozen RGB member changed: {name}")
    image = base.rgba_image(archive, info)
    alpha = image[:, :, 3] > 0
    pin = np.zeros(alpha.shape, dtype=np.uint8)
    for polygon in polygons[name]:
        cv2.fillPoly(pin, [polygon.astype(np.int32)], 1)
    return image, alpha, pin.astype(bool)


def load_mask(path, digest):
    if base.hash_file(path) != digest:
        raise ValueError(f"Mask digest mismatch: {path}")
    with Image.open(path) as image:
        return np.array(image) > 0


def metrics(mask, alpha, pin):
    if mask.shape != alpha.shape:
        raise ValueError("Predicted mask has an unexpected shape")
    area = int(mask.sum())
    potato_iou = base.iou(mask, alpha)
    pin_iou = base.iou(mask, pin)
    pin_share = float(np.count_nonzero(mask & pin) / area) if area else 0.
    if not area:
        state = "empty"
    elif potato_iou >= RECOVERY_IOU:
        state = "potato"
    elif pin_share > .5:
        state = "pin"
    else:
        state = "other"
    return {"mask_pixels": area, "potato_pixels": int(alpha.sum()), "pin_pixels": int(pin.sum()),
            "potato_iou": potato_iou, "pin_iou": pin_iou, "prediction_on_pin_fraction": pin_share,
            "state": state}


def replacement(x, y, alpha, pin):
    pin_distance = distance_transform_edt(~pin)
    edge_distance = distance_transform_edt(np.pad(alpha, 1))[1:-1, 1:-1]
    ys, xs = np.nonzero(alpha & (pin_distance >= CLEARANCE) & (edge_distance >= CLEARANCE))
    if not len(xs):
        raise ValueError("No eligible nearby peel pixel")
    squared = (xs - x)**2 + (ys - y)**2
    k = int(squared.argmin())  # np.nonzero enumerates in row-major order.
    yy, xx = int(ys[k]), int(xs[k])
    return xx, yy, float(np.sqrt(squared[k])), float(pin_distance[yy, xx]), float(edge_distance[yy, xx])


def freeze(output):
    manifest, scores, config = inputs()
    polygons = load_polygons(manifest)
    rows = []
    with ExitStack() as stack:
        archives = base.open_image_archives(stack, manifest)
        for frame in manifest["roster"]:
            tuber = frame["tuber"]
            archive = archives[frame["archive"]]
            entry, center = frame["frames"][0], frame["frames"][-1]
            _, alpha, pin = annotation_masks(archive, entry, polygons)
            _, center_alpha, center_pin = annotation_masks(archive, center, polygons)
            x, y = frame["click_xy"]
            if not alpha[y, x]:
                raise ValueError(f"Archived click falls outside the potato alpha: {tuber}")
            inside = any(
                cv2.pointPolygonTest(poly.astype(np.float32), (x, y), False) >= 0
                for poly in polygons[entry["rgb_member"]]
            )
            score = scores[tuber]
            mask = load_mask(base.STUDY / "center_masks" / f"{tuber}.png", score["center_mask_sha256"])
            old = metrics(mask, center_alpha, center_pin)
            if old["potato_iou"] != float(score["mask_iou"]):
                raise ValueError(f"Archived potato IoU differs on replay: {tuber}")
            xx, yy, movement, pin_distance, edge_distance = (
                replacement(x, y, alpha, pin) if inside else (x, y, 0., None, None)
            )
            rows.append({
                "tuber": tuber, "entry_file": entry["rgb_member"], "center_file": center["rgb_member"],
                "original_x": x, "original_y": y, "inside_pin_polygon": inside,
                "original_center_potato_iou": old["potato_iou"],
                "original_center_pin_iou": old["pin_iou"],
                "original_center_prediction_on_pin_fraction": old["prediction_on_pin_fraction"],
                "original_center_state": old["state"], "updated_x": xx, "updated_y": yy,
                "movement_px": movement, "new_pin_clearance_px": pin_distance,
                "new_edge_clearance_px": edge_distance,
            })
    groups = Counter((r["inside_pin_polygon"], r["original_center_state"] == "pin") for r in rows)
    counts = {
        "inside_pin": groups[True, True] + groups[True, False],
        "inside_pin_ending_on_pin": groups[True, True],
        "outside_pin": groups[False, True] + groups[False, False],
        "outside_pin_ending_on_pin": groups[False, True],
    }
    audit = {"observed": counts, "expected": EXPECTED,
             "observed_minus_expected": {k: counts[k] - EXPECTED[k] for k in EXPECTED},
             "outside_pin_failures": [r["tuber"] for r in rows if not r["inside_pin_polygon"]
                                      and r["original_center_state"] == "pin"]}
    base.write_json(output / "entry_audit.json", audit)
    base.write_csv(output / "clicks.csv", rows)
    print(audit, flush=True)
    if counts != EXPECTED:
        raise ValueError("Archived pin audit differs from expected counts. Diagnose before inference.")
    frozen = {
        "protocol_sha256": base.hash_file(STUDY / "protocol.md"),
        "parent_manifest_sha256": config["manifest_sha256"],
        "parent_scores_sha256": base.hash_file(base.STUDY / "per_potato.csv"),
        "parent_config_sha256": base.hash_file(base.STUDY / "tracking_config.json"),
        "pin_annotations_sha256": base.hash_file(PIN_LABELS),
        "clicks_sha256": base.hash_file(output / "clicks.csv"),
        "clicks": rows,
    }
    path = output / "frozen_clicks.json"
    if path.exists() and base.read_json(path) != frozen:
        raise ValueError("Click roster differs from the frozen design")
    base.write_json(path, frozen)


def read_frozen(output):
    frozen = base.read_json(output / "frozen_clicks.json")
    for key, path in [
        ("protocol_sha256", STUDY / "protocol.md"),
        ("parent_manifest_sha256", base.STUDY / "frame_manifest.json"),
        ("parent_scores_sha256", base.STUDY / "per_potato.csv"),
        ("parent_config_sha256", base.STUDY / "tracking_config.json"),
        ("pin_annotations_sha256", PIN_LABELS),
        ("clicks_sha256", output / "clicks.csv"),
    ]:
        if base.hash_file(path) != frozen[key]:
            raise ValueError(f"Frozen input changed: {path}")
    return frozen["clicks"]


def save_mask(path, mask):
    temp = path.with_suffix(".tmp")
    Image.fromarray(mask.astype(np.uint8) * 255).save(temp, format="PNG")
    temp.replace(path)
    return base.hash_file(path)


def run_tracks(output):
    import torch

    manifest, scores, config = inputs()
    clicks = read_frozen(output)
    if len(clicks) != len(manifest["roster"]) or torch.__version__ != config["torch"]:
        raise ValueError("Expected frozen roster and PyTorch version")
    polygons = load_polygons(manifest)
    predictor = base.build_cpu_predictor()
    saved = output / "masks"
    saved.mkdir(exist_ok=True)
    joined = list(zip(manifest["roster"], clicks, strict=True))
    if any(f["tuber"] != c["tuber"] for f, c in joined):
        raise ValueError("Frozen click IDs do not match manifest")
    tasks = [(f, c, "outside_replay") for f, c in joined if not c["inside_pin_polygon"]
             and c["original_center_state"] == "pin"]
    tasks += [(f, c, "moved") for f, c in joined if c["inside_pin_polygon"]]
    tracks = []
    with ExitStack() as stack, torch.inference_mode():
        archives = base.open_image_archives(stack, manifest)
        for frame, click, kind in tasks:
            tuber = frame["tuber"]
            directory = saved / tuber
            directory.mkdir(exist_ok=True)
            path = directory / "track.json"
            if path.exists():
                record = base.read_json(path)
                if record["frozen_sha256"] != base.hash_file(output / "frozen_clicks.json"):
                    raise ValueError(f"Saved track has different frozen inputs: {tuber}")
            else:
                record = run_one(output, predictor, archives[frame["archive"]], frame,
                                 click, kind, polygons, scores[tuber], directory)
                base.write_json(path, record)
            print(f"{len(tracks)+1}/{len(tasks)} {tuber} {kind} {record['status']}", flush=True)
            tracks.append(record)
            if kind == "outside_replay" and record["status"] != "exact_replay":
                raise RuntimeError(f"Archived center mask failed replay. Details in {path}")
    base.write_json(output / "tracking.json", tracks)


def run_one(output, predictor, archive, frame, click, kind, polygons, original, directory):
    tuber = frame["tuber"]
    treated = dict(frame, click_xy=[click["updated_x"], click["updated_y"]])
    history = []

    def observe(index, phase, mask):
        item = frame["frames"][index]
        _, alpha, pin = annotation_masks(archive, item, polygons)
        filename = directory / f"{index:02}_{phase}.png"
        history.append({
            "tuber": tuber, "frame_index": index, "phase": phase,
            "suffix_px": item["suffix_px"], "rgb_file": item["rgb_member"],
            **metrics(mask, alpha, pin),
            "mask_file": str(filename.relative_to(output)), "mask_sha256": save_mask(filename, mask),
        })

    start = time.perf_counter()
    row = {"tuber": tuber, "kind": kind, "click_xy": treated["click_xy"],
           "frozen_sha256": base.hash_file(output / "frozen_clicks.json")}
    try:
        # Observe every frame for the outside-click diagnostic. For moved runs save center only.
        observer = observe if kind == "outside_replay" else None
        center, includes_click, empty = base.predict_track(predictor, archive, treated, observer)
        if kind == "moved":
            observe(len(frame["frames"]) - 1, "propagation", center)
        archived = load_mask(base.STUDY / "center_masks" / f"{tuber}.png", original["center_mask_sha256"])
        xor = int(np.count_nonzero(center ^ archived))
        row.update({"status": ("exact_replay" if xor == 0 else "replay_mismatch")
                              if kind == "outside_replay" else ("returned" if center.any() else "empty"),
                    "center_xor_pixels_vs_original": xor, "entry_includes_click": includes_click,
                    "empty_suffixes": empty})
    except (RuntimeError, ValueError) as error:
        row.update({"status": "failure", "failure": f"{type(error).__name__}: {error}"})
    row["wall_seconds"] = time.perf_counter() - start
    row["history"] = history
    return row


def replay_summary(tracks, expected):
    summaries = []
    for track in tracks:
        if track["kind"] != "outside_replay":
            continue
        history = track["history"]
        propagated = history[1:]
        if (track["status"] != "exact_replay" or track["center_xor_pixels_vs_original"] != 0
                or history[0]["phase"] != "prompt" or propagated[-1]["state"] != "pin"
                or [row["frame_index"] for row in propagated] != list(range(len(propagated)))):
            raise ValueError(f"Invalid unchanged replay for {track['tuber']}")
        first_pin = next(r for r in history if r["state"] == "pin")
        summaries.append({
            "tuber": track["tuber"], "entry_suffix_px": history[0]["suffix_px"],
            "entry_prompt_state": history[0]["state"],
            "entry_prompt_potato_iou": history[0]["potato_iou"],
            "entry_prompt_pin_iou": history[0]["pin_iou"],
            "entry_prediction_includes_click": track["entry_includes_click"],
            "first_pin_phase": first_pin["phase"], "first_pin_suffix_px": first_pin["suffix_px"],
            "first_pin_frame_index": first_pin["frame_index"],
            "potato_frames_before_first_pin": sum(
                r["state"] == "potato" and r["frame_index"] < first_pin["frame_index"]
                for r in propagated
            ),
            "center_suffix_px": propagated[-1]["suffix_px"],
            "center_potato_iou": propagated[-1]["potato_iou"],
            "center_pin_iou": propagated[-1]["pin_iou"],
            "center_archive_xor_pixels": track["center_xor_pixels_vs_original"],
            "propagated_states": " ".join(r["state"] for r in propagated),
            "wall_seconds": track["wall_seconds"],
        })
    if len(summaries) != expected:
        raise ValueError("Missing outside-pin replays")
    return summaries


def estimate(depth, mask, matrix, thickness):
    support, _ = base.filtered_support(depth, mask, thickness)
    description, _ = base.describe_support(depth, support, matrix)
    return description


def paired_rows(output, manifest, scores, clicks, tracks, polygons):
    results = []
    matrix = base.intrinsics_from_json(base.read_json(base.INTRINSICS))
    by_id = {r["tuber"]: r for r in tracks}
    with ExitStack() as stack:
        archives = base.open_image_archives(stack, manifest)
        for frame, click in zip(manifest["roster"], clicks, strict=True):
            tuber = frame["tuber"]
            if tuber != click["tuber"]:
                raise ValueError("Click roster order changed")
            old = scores[tuber]
            moved = click["inside_pin_polygon"]
            measured = float(old["measured_g"])
            result = {
                **click, "measured_g": measured, "provided_g": float(old["provided_predicted_g"]),
                "original_g": float(old["sam2_predicted_g"]),
                "original_abs_error_g": float(old["sam2_abs_error_g"]),
                "provided_abs_error_g": float(old["provided_abs_error_g"]),
                "updated_center_potato_iou": click["original_center_potato_iou"],
                "updated_center_pin_iou": click["original_center_pin_iou"],
                "updated_center_state": click["original_center_state"],
                "updated_g": float(old["sam2_predicted_g"]), "recovered": None,
                "weight_status": "archived", "tracking_status": "archived",
                "updated_mask_sha256": old["center_mask_sha256"],
                "failure": "",
            }
            if moved:
                track = by_id[tuber]
                result.update({"tracking_status": track["status"], "weight_status": "unscorable",
                               "updated_g": None, "updated_center_potato_iou": None,
                               "updated_center_pin_iou": None, "updated_center_state": "unavailable",
                               "updated_mask_sha256": None, "recovered": False,
                               "failure": track.get("failure", "")})
                if track["history"]:
                    center = track["history"][-1]
                    archive = archives[frame["archive"]]
                    mask = load_mask(output / center["mask_file"], center["mask_sha256"])
                    image, depth = base.center_inputs(archive, frame)
                    _, alpha, pin = annotation_masks(archive, frame["frames"][-1], polygons)
                    if not np.array_equal(alpha, image[:, :, 3] > 0):
                        raise ValueError(f"Depth and annotation frame mismatch: {tuber}")
                    score = metrics(mask, alpha, pin)
                    if any(center[key] != value for key, value in score.items()):
                        raise ValueError(f"Saved mask statistics mismatch: {tuber}")
                    result.update({
                        "updated_center_potato_iou": score["potato_iou"],
                        "updated_center_pin_iou": score["pin_iou"],
                        "updated_center_state": score["state"],
                        "recovered": score["potato_iou"] >= RECOVERY_IOU,
                        "updated_mask_sha256": center["mask_sha256"],
                    })
                    original_mask = load_mask(
                        base.STUDY / "center_masks" / f"{tuber}.png", old["center_mask_sha256"]
                    )
                    thickness = float(old["thickness_mm"])
                    archived_provided = estimate(depth, alpha, matrix, thickness)
                    archived_sam = estimate(depth, original_mask, matrix, thickness)
                    if (abs(archived_provided["predicted_g"] - result["provided_g"]) > 1e-8
                            or abs(archived_sam["predicted_g"] - result["original_g"]) > 1e-8):
                        raise ValueError(f"Archived weight pipeline does not replay on {tuber}")
                    try:
                        treatment = estimate(depth, mask, matrix, thickness)
                        result.update({
                            "updated_g": treatment["predicted_g"], "weight_status": "scored",
                            "updated_area_mm2": treatment["area_mm2"],
                            "updated_height_mm": treatment["height_mm"],
                        })
                    except (ValueError, base.QhullError) as error:
                        result["failure"] = f"{type(error).__name__}: {str(error).splitlines()[0]}"
            updated = result["updated_g"]
            error = abs(updated - measured) if updated is not None else None
            result.update({
                "updated_abs_error_g": error,
                "updated_minus_original_abs_error_g": None if error is None
                else error - result["original_abs_error_g"],
            })
            results.append(result)
    return results


def draw_overlay(ax, image, alpha, pin, predicted=None, original=None, moved=None):
    union = (alpha | pin) if predicted is None else (alpha | pin | predicted)
    ys, xs = np.nonzero(union)
    x0, y0 = max(0, int(xs.min()) - 12), max(0, int(ys.min()) - 12)
    window = np.s_[y0:int(ys.max()) + 13, x0:int(xs.max()) + 13]
    ax.imshow(image[window][:, :, :3])
    for mask, color, style in [
        (alpha, "#27c7f7", "-"), (pin, "#ffdd49", "--"), (predicted, "#ff822e", "-")
    ]:
        if mask is not None and mask.any():
            ax.contour(mask[window], levels=[.5], colors=[color], linestyles=[style],
                       linewidths=.95 if mask is predicted else .75)
    if original is not None:
        ax.plot(original[0]-x0, original[1]-y0, marker="x", ms=7,
                mew=1.6, color="white", linestyle="None")
    if moved is not None:
        ax.plot(moved[0]-x0, moved[1]-y0, marker="+", ms=8,
                mew=1.6, color="#82ff4c", linestyle="None")
    ax.set_axis_off()


def render(output, manifest, results, tracks, polygons):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    by_id = {f["tuber"]: f for f in manifest["roster"]}
    tracks_by_id = {r["tuber"]: r for r in tracks}
    with ExitStack() as stack:
        archives = base.open_image_archives(stack, manifest)
        changed = [r for r in results if r["inside_pin_polygon"]]
        # Show the two widest click movements and the smallest movement as representative.
        changed.sort(key=lambda row: (-row["movement_px"], row["tuber"]))
        examples = [changed[0], changed[1], changed[-1]]
        fig, axes = plt.subplots(len(examples), 3, squeeze=False, figsize=(10, 8))
        for axes_row, result in zip(axes, examples, strict=True):
            tuber = result["tuber"]
            frame = by_id[tuber]
            archive = archives[frame["archive"]]
            image, alpha, pin = annotation_masks(archive, frame["frames"][0], polygons)
            draw_overlay(axes_row[0], image, alpha, pin, original=(result["original_x"], result["original_y"]),
                         moved=(result["updated_x"], result["updated_y"]))
            axes_row[0].set_title(f"{tuber}  |  entry click moved {result['movement_px']:.1f} px")
            image, alpha, pin = annotation_masks(archive, frame["frames"][-1], polygons)
            original_score = load_mask(base.STUDY / "center_masks" / f"{tuber}.png",
                                       base.read_json(base.STUDY / "center_masks" / f"{tuber}.json")["mask_sha256"])
            history = tracks_by_id[tuber]["history"]
            new_mask = load_mask(output / history[-1]["mask_file"], history[-1]["mask_sha256"]) if history else None
            for ax, label, mask, iou in [
                (axes_row[1], "Original center", original_score, result["original_center_potato_iou"]),
                (axes_row[2], "Updated center", new_mask, result["updated_center_potato_iou"]),
            ]:
                draw_overlay(ax, image, alpha, pin, mask)
                ax.set_title(f"{label}  |  IoU {iou:.3f}" if iou is not None else f"{label}  |  unavailable")
        fig.text(.5, .012, "Blue potato outline  ·  dashed yellow pin  ·  orange prediction  ·  white × original click  ·  green + peel click", ha="center", fontsize=9)
        fig.tight_layout(rect=(0, .04, 1, 1))
        fig.savefig(output / "peel_click_overlays.png", dpi=175)
        plt.close(fig)

        replays = [r for r in tracks if r["kind"] == "outside_replay"]
        fig, axes = plt.subplots(len(replays), 3, squeeze=False, figsize=(10, 10))
        for axes_row, track in zip(axes, replays, strict=True):
            frame = by_id[track["tuber"]]
            archive = archives[frame["archive"]]
            history = track["history"]
            first_pin = next(r for r in history if r["state"] == "pin")
            middle = history[2] if first_pin["phase"] == "prompt" else first_pin
            for ax, row, label in zip(axes_row, (history[0], middle, history[-1]),
                                      ("Entry prompt", "Propagation", "Center"), strict=True):
                item = frame["frames"][row["frame_index"]]
                image, alpha, pin = annotation_masks(archive, item, polygons)
                mask = load_mask(output / row["mask_file"], row["mask_sha256"])
                draw_overlay(ax, image, alpha, pin, mask,
                             original=track["click_xy"] if row["phase"] == "prompt" else None)
                ax.set_title(f"{track['tuber']}  |  {label} {row['suffix_px']}\n"
                             f"{row['state']}  ·  potato IoU {row['potato_iou']:.3f}")
        fig.text(.5, .012, "Blue potato outline  ·  dashed yellow pin  ·  orange prediction  ·  white × original click", ha="center", fontsize=9)
        fig.tight_layout(rect=(0, .035, 1, 1))
        fig.savefig(output / "outside_pin_replay_overlays.png", dpi=175)
        plt.close(fig)


def score(output):
    manifest, original, _ = inputs()
    clicks = read_frozen(output)
    tracks = base.read_json(output / "tracking.json")
    intended = {r["tuber"] for r in clicks if r["inside_pin_polygon"]
                or r["original_center_state"] == "pin"}
    if len(tracks) != len(intended) or {r["tuber"] for r in tracks} != intended:
        raise ValueError("Incorrect set of inferred tracks")
    if any(r["frozen_sha256"] != base.hash_file(output / "frozen_clicks.json") for r in tracks):
        raise ValueError("Tracking run and frozen design disagree")
    replays = replay_summary(tracks, EXPECTED["outside_pin_ending_on_pin"])
    polygons = load_polygons(manifest)
    results = paired_rows(output, manifest, original, clicks, tracks, polygons)
    scorable = [row for row in results if row["updated_abs_error_g"] is not None]
    changed = [r for r in results if r["inside_pin_polygon"]]
    mae = {key: float(np.mean([r[f"{key}_abs_error_g"] for r in scorable]))
           for key in ("updated", "original", "provided")}
    summary = {
        "roster": len(results), "changed": len(changed),
        "unchanged_reused": len(results) - len(changed),
        "recovery_iou_threshold": RECOVERY_IOU,
        "recovered": sum(r["recovered"] for r in changed),
        "updated_potato_masks": sum(r["updated_center_state"] == "potato" for r in results),
        "updated_pin_masks": sum(r["updated_center_state"] == "pin" for r in results),
        "median_click_movement_px": float(np.median([r["movement_px"] for r in changed])),
        "min_click_movement_px": min(r["movement_px"] for r in changed),
        "max_click_movement_px": max(r["movement_px"] for r in changed),
        "scorable": len(scorable),
        "missing_weights": [r["tuber"] for r in results if r["updated_g"] is None],
        "mae_g": mae, "updated_minus_original_mae_g": mae["updated"] - mae["original"],
        "updated_minus_provided_mae_g": mae["updated"] - mae["provided"],
        "outside_pin_replays": replays,
        "tracking_wall_seconds": sum(r["wall_seconds"] for r in tracks),
    }
    base.write_csv(output / "per_potato.csv", results)
    base.write_csv(output / "outside_pin_replays.csv", replays)
    base.write_csv(output / "outside_pin_per_frame.csv", [
        f for r in tracks if r["kind"] == "outside_replay" for f in r["history"]
    ])
    base.write_json(output / "results.json", summary)
    render(output, manifest, results, tracks, polygons)
    print({k: v for k, v in summary.items() if k != "outside_pin_replays"}, flush=True)
    for row in replays:
        print(row, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["freeze", "track", "score"])
    parser.add_argument("--output", type=Path, default=STUDY)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    commands = {"freeze": freeze, "track": run_tracks}
    if args.stage == "score":
        score(args.output)
    else:
        commands[args.stage](args.output)


if __name__ == "__main__":
    main()
