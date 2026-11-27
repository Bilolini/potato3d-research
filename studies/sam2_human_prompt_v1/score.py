"""Score a completed and frozen human click session with the archived tracker."""

import argparse
from collections import Counter
from contextlib import ExitStack
import csv
from io import StringIO
import math
from pathlib import Path
import sys
import time

import cv2
import numpy as np

STUDY = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY.parents[1]))
from studies.sam2_center_weight_v1 import run as base
from studies.sam2_human_prompt_v1.collector import (
    FIELDS, digest, pilot_manifest, pilot_protocol, validate_response,
)
from studies.sam2_pin_prompt_v1 import run as pin

PRIOR = pin.STUDY / "per_potato.csv"


def session(directory):
    snapshot = directory / "frozen_clicks.csv"
    receipt_file = directory / "click_freeze.json"
    if not snapshot.is_file() or not receipt_file.is_file():
        raise ValueError("Collection is incomplete. The scorer requires the frozen 40-response snapshot.")
    manifest_file = pilot_manifest(directory)
    protocol_file = pilot_protocol(manifest_file)
    manifest_bytes = manifest_file.read_bytes()
    manifest = base.read_json(manifest_file)
    receipt = base.read_json(receipt_file)
    frozen = snapshot.read_bytes()
    verified = {
        "manifest_sha256": digest(manifest_bytes),
        "protocol_sha256": base.hash_file(protocol_file),
        "clicks_sha256": digest(frozen), "completed": 40,
    }
    if receipt != verified or (directory / "clicks.csv").read_bytes() != frozen:
        raise ValueError("Frozen click receipt, roster or click ledger changed")
    if manifest["source"] != "development" or len(manifest["trials"]) != 40:
        raise ValueError("Scoring requires the real 40-potato roster")
    if "repeat_of_manifest_sha256" in manifest:
        original = STUDY / "trial_manifest.json"
        if (base.hash_file(original) != manifest["repeat_of_manifest_sha256"]
                or base.read_json(original)["trials"] != manifest["trials"]
                or base.hash_file(STUDY / "results.json") != manifest["first_session_results_sha256"]):
            raise ValueError("The original trial manifest or first session summary changed")
    for field, path in [
        ("protocol_sha256", protocol_file),
        ("parent_frame_manifest_sha256", base.STUDY / "frame_manifest.json"),
        ("parent_pin_manifest_sha256", pin.STUDY / "frozen_clicks.json"),
        ("prior_scores_sha256", PRIOR),
        ("parent_scores_sha256", base.STUDY / "per_potato.csv"),
        ("parent_tracking_config_sha256", base.STUDY / "tracking_config.json"),
        ("pin_annotations_sha256", pin.PIN_LABELS),
    ]:
        if manifest[field] != base.hash_file(path):
            raise ValueError(f"Frozen scoring source changed: {path}")
    reader = csv.DictReader(StringIO(frozen.decode("utf-8"), newline=""))
    if tuple(reader.fieldnames or ()) != FIELDS:
        raise ValueError("Click snapshot schema changed")
    records = list(reader)
    if len(records) != 40:
        raise ValueError("Expected 40 click or cannot-identify records")
    for row, trial in zip(records, manifest["trials"], strict=True):
        row["trial"] = int(row["trial"])
        row["x"] = int(row["x"]) if row["x"] else None
        row["y"] = int(row["y"]) if row["y"] else None
        validate_response(row, trial)
    return manifest, records, verified


def track_one(predictor, archive, frame, click, polygons, data_dir, recipe):
    tuber = frame["tuber"]
    history = []
    row = {"tuber": tuber, "receipt": recipe, "history": history, "wall_seconds": 0.,
           "status": "cannot_identify" if click["response"] == "cannot_identify" else "missing_center",
           "mask_sha256": None, "error": ""}
    if click["response"] == "cannot_identify":
        return row
    coords = [click["x"], click["y"]]
    prompted = dict(frame, click_xy=coords)

    def observe(index, phase, mask):
        item = frame["frames"][index]
        _, alpha, annotation = pin.annotation_masks(archive, item, polygons)
        summary = pin.metrics(mask, alpha, annotation)
        history.append({"tuber": tuber, "frame_index": index, "phase": phase,
                        "suffix_px": item["suffix_px"], "rgb_file": item["rgb_member"], **summary})

    start = time.perf_counter()
    try:
        mask, includes_click, empty = base.predict_track(predictor, archive, prompted, observe)
        if len(history) != len(frame["frames"]) + 1 or history[-1]["phase"] != "propagation":
            raise ValueError("Track did not produce the complete frozen frame sequence")
        mask_digest = pin.save_mask(data_dir / f"{tuber}.png", mask)
        row.update({"status": "returned" if mask.any() else "empty_center",
                    "mask_sha256": mask_digest, "entry_includes_click": includes_click,
                    "empty_suffixes_px": empty})
    except (ValueError, RuntimeError) as error:
        row.update({"status": "inference_failure", "error": f"{type(error).__name__}: {error}"})
    row["wall_seconds"] = time.perf_counter() - start
    return row


def click_placement(archive, frame, click, polygons):
    """Describe submitted coordinates after collection with the released labels."""
    if click["response"] != "click":
        return {"click_region": "cannot_identify", "click_pin_signed_distance_px": None}
    entry = frame["frames"][0]
    image, alpha, _ = pin.annotation_masks(archive, entry, polygons)
    x, y = click["x"], click["y"]
    distance = max(cv2.pointPolygonTest(p.astype(np.float32), (x, y), True)
                   for p in polygons[entry["rgb_member"]])
    if distance >= 0:
        region = "pin_polygon"
    elif alpha[y, x]:
        region = "potato_outside_pin"
    else:
        region = "outside_potato"
    return {"click_region": region, "click_pin_signed_distance_px": distance}


def mask_metrics(track):
    history = track["history"]
    start = history[0] if history else None
    complete_track = track["mask_sha256"] is not None
    center = history[-1] if complete_track else None
    center_success = center is not None and center["potato_iou"] >= pin.RECOVERY_IOU
    pin_at_entry = start is not None and start["state"] == "pin"
    lost_later = (center is not None and not center_success
                  and any(f["state"] == "potato" for f in history[:-1]))
    if center_success:
        failure = ""
    elif track["status"] in {"cannot_identify", "inference_failure", "missing_center"}:
        failure = track["status"]
    elif pin_at_entry:
        failure = "pin_at_entry"
    elif lost_later:
        failure = "lost_potato_later"
    else:
        failure = "never_tracked_potato"
    return {
        "tracking_status": track["status"], "tracking_error": track["error"],
        "failure_category": failure, "entry_state": start["state"] if start else None,
        "entry_potato_iou": start["potato_iou"] if start else None,
        "entry_pin_iou": start["pin_iou"] if start else None,
        "entry_prediction_includes_click": track.get("entry_includes_click"),
        "pin_selected_at_entry": pin_at_entry, "lost_potato_later": lost_later,
        "center_state": center["state"] if center else None,
        "center_potato_iou": center["potato_iou"] if center else None,
        "center_pin_iou": center["pin_iou"] if center else None, "potato_match": center_success,
        "center_mask_sha256": track["mask_sha256"], "tracking_wall_s": track["wall_seconds"],
        "human_g": None, "human_abs_error_g": None,
        "weight_status": track["status"], "weight_error": "",
    }


def measure(row, track, directory, archive, frame, archived, matrix):
    row.update(mask_metrics(track))
    complete_track = track["mask_sha256"] is not None
    if not complete_track:
        return row
    if track["status"] == "empty_center":
        return row
    mask = pin.load_mask(directory / f"{row['tuber']}.png", track["mask_sha256"])
    image, depth = base.center_inputs(archive, frame)
    thickness = float(archived["thickness_mm"])
    provided = pin.estimate(depth, image[:, :, 3] > 0, matrix, thickness)
    if not math.isclose(provided["predicted_g"], row["provided_g"], rel_tol=0, abs_tol=1e-8):
        raise ValueError(f"Provided-mask weight failed replay on {row['tuber']}")
    try:
        estimate = pin.estimate(depth, mask, matrix, thickness)
    except (ValueError, base.QhullError) as error:
        row.update({"weight_status": "unscorable",
                    "weight_error": f"{type(error).__name__}: {str(error).splitlines()[0]}"})
    else:
        predicted = estimate["predicted_g"]
        row.update({"human_g": predicted, "human_abs_error_g": abs(predicted - row["measured_g"]),
                    "weight_status": "scorable"})
    return row


def summarize(rows):
    matched = [r for r in rows if r["human_abs_error_g"] is not None]
    means = {
        key: float(np.mean([r[f"{key}_abs_error_g"] for r in matched])) if matched else None
        for key in ("human", "provided")
    }
    return {
        "roster": len(rows), "center_iou_threshold": pin.RECOVERY_IOU,
        "potato_matches": sum(r["potato_match"] for r in rows),
        "prior_potato_matches": sum(r["prior_potato_match"] for r in rows),
        "scorable": len(matched), "paired_mae_g": means,
        "paired_mae_change_g": means["human"] - means["provided"] if matched else None,
        "gains": [r["tuber"] for r in rows if r["potato_match"] and not r["prior_potato_match"]],
        "losses": [r["tuber"] for r in rows if r["prior_potato_match"] and not r["potato_match"]],
        "mask_failures": [{"tuber": r["tuber"], "category": r["failure_category"]}
                          for r in rows if not r["potato_match"]],
        "weight_failures": [{"tuber": r["tuber"], "category": r["weight_status"]}
                            for r in rows if r["human_abs_error_g"] is None],
        "pin_selected_at_entry_among_failures": [r["tuber"] for r in rows
                                                if not r["potato_match"] and r["pin_selected_at_entry"]],
        "lost_potato_later_among_failures": [r["tuber"] for r in rows
                                            if not r["potato_match"] and r["lost_potato_later"]],
        "click_regions": dict(Counter(r["click_region"] for r in rows)),
        "matches_by_click_region": dict(Counter(r["click_region"] for r in rows if r["potato_match"])),
        "tracking_wall_s": sum(r["tracking_wall_s"] for r in rows),
    }


def write_report(directory, rows, summary):
    total = summary["roster"]
    matches = summary["potato_matches"]
    means = summary["paired_mae_g"]
    regions = summary["click_regions"]
    skin_matches = summary["matches_by_click_region"].get("potato_outside_pin", 0)
    placement_note = (
        "This session primarily reflects pin clicks, so it provides little evidence about reliably placed peel clicks. "
        if regions.get("pin_polygon", 0) > total / 2 else ""
    )
    at_entry = len(summary["pin_selected_at_entry_among_failures"])
    lost_later = len(summary["lost_potato_later_among_failures"])
    other = sum(r["failure_category"] == "never_tracked_potato" for r in rows)
    mae = (f"Human-click masks had **{means['human']:.2f} g MAE**, and provided masks had "
           f"**{means['provided']:.2f} g MAE** on the same IDs. "
           f"The paired mean change was **{summary['paired_mae_change_g']:+.2f} g**."
           if summary["scorable"] else "A paired MAE could not be estimated.")
    lines = [
        "# One-click human-operator development results", "",
        f"**{matches}/{total}** center masks matched the potato at IoU ≥ 0.5. "
        f"The prior peel-click rule matched **{summary['prior_potato_matches']}/{total}**. "
        f"There were {len(summary['gains'])} gains and {len(summary['losses'])} losses.", "",
        f"**{summary['scorable']}/{total}** weights were scorable. {mae}", "",
        f"In the post-scoring placement audit, **{regions.get('pin_polygon', 0)}** clicks landed "
        f"on or inside the pin outline, **{regions.get('outside_potato', 0)}** landed outside the "
        f"intended potato, and **{regions.get('potato_outside_pin', 0)}** landed on the potato outside "
        f"the pin. Of those last clicks, **{skin_matches}** produced a potato match. {placement_note}"
        "Click regions were assigned from frozen coordinates and the released entry annotations. "
        "They were used only to describe the submitted responses. [Click regions and per-potato results](per_potato.csv)", "",
        f"Gains among prior failures were {', '.join(summary['gains']) or 'none'}. "
        f"Losses among prior matches were {', '.join(summary['losses']) or 'none'}.", "",
        "One operator used annotated coarse location cues. The weight pipeline used measured thickness, "
        "as in the archived study. Test and reserved cohorts stayed closed. "
        "[Frozen click receipt](click_freeze.json) · [Per-potato results](per_potato.csv) "
        "· [Per-frame states](per_frame.csv) · [Full-precision results](results.json)", "",
        "## Failures", "",
        f"Among the {total - matches} center-mask failures, **{at_entry}** selected the pin at entry "
        f"and **{lost_later}** acquired the potato and later lost it. "
        f"{other} had another entry mask and never reached the potato IoU threshold.", "",
        "| Trial | Potato | Mask failure | Entry mask | Center IoU | Weight status | Detail |",
        "|---:|---|---|---|---:|---|---|",
    ]
    if first := summary.get("first_human_session"):
        lines[4:4] = [
            f"The first human session matched **{first['potato_matches']}/{first['roster']}**. "
            "This was a coached repeat with clarified instructions on the same scenes.", "",
        ]
    for row in rows:
        if not row["potato_match"] or row["weight_status"] != "scorable":
            iou = "—" if row["center_potato_iou"] is None else f"{row['center_potato_iou']:.3f}"
            detail = " ".join((row["weight_error"] or row["tracking_error"] or "—").splitlines())
            detail = detail.replace("|", "/")
            lines.append(f"| {row['trial']} | {row['tuber']} | "
                         f"{row['failure_category'].replace('_', ' ') or '—'} | {row['entry_state'] or '—'} | "
                         f"{iou} | {row['weight_status'].replace('_', ' ')} | {detail} |")
    if all(r["potato_match"] and r["weight_status"] == "scorable" for r in rows):
        lines.append("| — | — | None | — | — | — | — |")
    lines += ["",
              "Separate flags in the per-potato table show whether a failure selected the pin at entry "
              "and whether it acquired a potato mask and later lost it. Both flags can apply. "
              "The failure table gives priority to the entry pin when both occur.", ""]
    (directory / "report.md").write_text("\n".join(lines))


def run(directory):
    stimuli, clicks, recipe = session(directory)
    import torch

    manifest, archive_scores, config = pin.inputs()
    if torch.__version__ != config["torch"]:
        raise ValueError("Use the archived SAM 2 PyTorch environment")
    previous = {r["tuber"]: r for r in base.read_csv(PRIOR)}
    prior_matches = {t: float(r["updated_center_potato_iou"]) >= pin.RECOVERY_IOU
                     for t, r in previous.items()}
    by_tuber = {f["tuber"]: f for f in manifest["roster"]}
    frozen_ids = {trial["tuber"] for trial in stimuli["trials"]}
    if frozen_ids != set(by_tuber) or set(prior_matches) != frozen_ids or sum(prior_matches.values()) != 34:
        raise ValueError("Predecessor and stimulus rosters or the 34/40 comparator changed")
    polygons = pin.load_polygons(manifest)
    matrix = base.intrinsics_from_json(base.read_json(base.INTRINSICS))
    track_dir = directory / "center_masks"
    track_dir.mkdir(exist_ok=True)
    requires_inference = any(
        click["response"] == "click" and not (track_dir / f"{trial['tuber']}.json").exists()
        for trial, click in zip(stimuli["trials"], clicks, strict=True)
    )
    predictor = base.build_cpu_predictor() if requires_inference else None
    results, per_frame = [], []
    with ExitStack() as stack, torch.inference_mode():
        archives = base.open_image_archives(stack, manifest)
        for trial, click in zip(stimuli["trials"], clicks, strict=True):
            tuber = trial["tuber"]
            frame = by_tuber[tuber]
            archived = archive_scores[tuber]
            if trial["entry_file"] != frame["frames"][0]["rgb_member"]:
                raise ValueError(f"Frozen entry position changed for {tuber}")
            archive = archives[frame["archive"]]
            path = track_dir / f"{tuber}.json"
            if path.exists():
                track = base.read_json(path)
                if track["receipt"] != recipe:
                    raise ValueError(f"Saved track belongs to a different click file: {tuber}")
            else:
                track = track_one(predictor, archive, frame, click, polygons, track_dir, recipe)
                base.write_json(path, track)
            row = {**click, "tuber": tuber, "entry_file": trial["entry_file"],
                   "measured_g": float(archived["measured_g"]),
                   "provided_g": float(archived["provided_predicted_g"]),
                   "provided_abs_error_g": float(archived["provided_abs_error_g"]),
                   "prior_potato_match": prior_matches[tuber]}
            row.update(click_placement(archive, frame, click, polygons))
            results.append(measure(row, track, track_dir, archive, frame, archived, matrix))
            per_frame.extend(track["history"])
            print(f"Scored {len(results)}/40", flush=True)
    summary = summarize(results)
    summary["clicks_sha256"] = recipe["clicks_sha256"]
    if "repeat_of_manifest_sha256" in stimuli:
        first = base.read_json(STUDY / "results.json")
        summary["first_human_session"] = {
            "roster": first["roster"], "potato_matches": first["potato_matches"],
            "results_sha256": stimuli["first_session_results_sha256"],
        }
    base.write_json(directory / "results.json", summary)
    base.write_csv(directory / "per_potato.csv", results)
    if per_frame:
        base.write_csv(directory / "per_frame.csv", per_frame)
    else:
        (directory / "per_frame.csv").write_text(
            "tuber,frame_index,phase,suffix_px,rgb_file,mask_pixels,potato_pixels,"
            "pin_pixels,potato_iou,pin_iou,prediction_on_pin_fraction,state\n"
        )
    write_report(directory, results, summary)
    print(f"Saved report to {directory / 'report.md'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=STUDY)
    args = parser.parse_args()
    try:
        run(args.directory)
    except ValueError as error:
        raise SystemExit(str(error)) from error
