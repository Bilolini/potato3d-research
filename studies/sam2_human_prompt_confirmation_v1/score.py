"""Score one frozen held-out collection and save mask and paired weight results."""

from collections import Counter
from contextlib import ExitStack
import csv
import fcntl
import math
from pathlib import Path
import sys
from zipfile import BadZipFile

import numpy as np
from scipy.stats import beta

STUDY = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY.parents[1]))
from studies.sam2_center_weight_v1 import run as base
from studies.sam2_human_prompt_confirmation_v1 import prepare
from studies.sam2_human_prompt_v1 import collector
from studies.sam2_human_prompt_v1 import score as human
from studies.sam2_pin_prompt_v1 import run as pin

ALPHA = .05
BOOTSTRAPS = 10_000
BOOTSTRAP_SEED = 5272401


def completed_session(frozen):
    for name in ("clicks.csv", "frozen_clicks.csv", "click_freeze.json"):
        if not (STUDY / name).is_file():
            raise ValueError("Collection incomplete. Wait for the frozen response file and receipt.")
    manifest = STUDY / "trial_manifest.json"
    session = collector.Collection(STUDY, manifest)
    if session.source != "confirmation" or len(session.rows) != frozen["eligible"]:
        raise ValueError("Expected one frozen response per enrolled potato")
    expected = base.read_json(prepare.REPEAT / "trial_manifest.json")["operator_instruction"]
    if session.manifest["operator_instruction"] != expected:
        raise ValueError("The held-out instruction differs from the coached repeat")
    receipt = base.read_json(session.receipt_file)
    receipt["cohort_sha256"] = base.hash_file(STUDY / "cohort_freeze.json")
    return session.rows, receipt


def read_measurements(ids):
    rows = {}
    with prepare.TRAITS.open(newline="") as file:
        for row in csv.DictReader(file):
            tuber = row["label"]
            if tuber not in ids:
                continue
            if tuber in rows:
                raise ValueError(f"Duplicate measured trait ID: {tuber}")
            rows[tuber] = row["x3_depth_mm"], row[prepare.MEASURED_WEIGHT]
    if set(rows) != ids:
        raise ValueError("Frozen measurement metadata join changed")
    return rows


def positive_number(data):
    try:
        value = float(data)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def score_weights(row, track, archive, frame, matrix, traits, mask_dir):
    thickness, actual = map(positive_number, traits)
    row.update({"thickness_mm": thickness, "measured_g": actual, "provided_g": None,
                "provided_abs_error_g": None, "paired_abs_error_change_g": None})
    if track["status"] != "returned":
        return
    if thickness is None or actual is None:
        row.update({"weight_status": "unscorable", "weight_error": "Missing or invalid measured thickness or weight"})
        return
    mask = pin.load_mask(mask_dir / f"{row['tuber']}.png", track["mask_sha256"])
    try:
        image, depth = base.center_inputs(archive, frame)
        provided = pin.estimate(depth, image[:, :, 3] > 0, matrix, thickness)["predicted_g"]
        guess = pin.estimate(depth, mask, matrix, thickness)["predicted_g"]
        if not np.isfinite([provided, guess]).all():
            raise ValueError("Nonfinite weight")
    except (ValueError, base.QhullError, OSError, BadZipFile, KeyError) as error:
        row.update({"weight_status": "unscorable", "weight_error": f"{type(error).__name__}: {str(error).splitlines()[0]}"})
    else:
        human_error, provided_error = abs(guess - actual), abs(provided - actual)
        row.update({
            "provided_g": provided, "human_g": guess,
            "provided_abs_error_g": provided_error, "human_abs_error_g": human_error,
            "paired_abs_error_change_g": human_error - provided_error, "weight_status": "scorable",
        })


def binomial_interval(matches, total):
    lower = float(beta.ppf(ALPHA / 2, matches, total - matches + 1)) if matches else 0.
    upper = float(beta.ppf(1 - ALPHA / 2, matches + 1, total - matches)) if matches < total else 1.
    return [lower, upper]


def summarize(rows):
    total = len(rows)
    successes = sum(r["potato_match"] for r in rows)
    paired = [r for r in rows if r["weight_status"] == "scorable"]
    metrics = {
        "enrolled": total, "center_iou_threshold": pin.RECOVERY_IOU,
        "potato_matches": successes, "center_match_fraction": successes / total,
        "center_match_binomial_95": binomial_interval(successes, total),
        "responses": dict(Counter(r["response"] for r in rows)),
        "click_regions": dict(Counter(r["click_region"] for r in rows)),
        "scorable_paired_weights": len(paired),
        "paired_mae_g": None, "paired_mean_change_g": None, "paired_mean_change_bootstrap_95_g": None,
        "mask_failure_counts": dict(Counter(r["failure_category"] for r in rows if not r["potato_match"])),
        "mask_failure_ids": [r["tuber"] for r in rows if not r["potato_match"]],
        "weight_failure_ids": [r["tuber"] for r in rows if r["weight_status"] != "scorable"],
        "pin_at_entry_failure_ids": [r["tuber"] for r in rows if not r["potato_match"] and r["pin_selected_at_entry"]],
        "lost_potato_later_failure_ids": [r["tuber"] for r in rows if r["lost_potato_later"]],
        "tracking_wall_s": sum(r["tracking_wall_s"] for r in rows),
    }
    if paired:
        differences = np.asarray([r["paired_abs_error_change_g"] for r in paired])
        draws = np.random.default_rng(BOOTSTRAP_SEED).integers(len(paired), size=(BOOTSTRAPS, len(paired)))
        metrics.update({
            "paired_mae_g": {k: float(np.mean([r[f"{k}_abs_error_g"] for r in paired]))
                             for k in ("human", "provided")},
            "paired_mean_change_g": float(differences.mean()),
            "paired_mean_change_bootstrap_95_g": np.quantile(
                differences[draws].mean(axis=1), [ALPHA/2, 1-ALPHA/2]
            ).tolist(),
        })
    return metrics


def show_failures(rows):
    out = ["| Trial | Potato | Click (x, y) and region | Entry state | Center IoU | Lost potato later | Mask failure | Weight status |",
           "|---:|---|---|---|---:|---|---|---|"]
    for row in rows:
        if row["potato_match"] and row["weight_status"] == "scorable":
            continue
        click = "Cannot identify" if row["x"] is None else (
            f"({row['x']}, {row['y']}) {row['click_region'].replace('_', ' ')}"
        )
        iou = "—" if row["center_potato_iou"] is None else f"{row['center_potato_iou']:.3f}"
        detail = row["weight_error"] or row["tracking_error"]
        weight = row["weight_status"].replace("_", " ")
        if detail:
            weight += " (" + " ".join(detail.splitlines()).replace("|", "/") + ")"
        out.append(f"| {row['trial']} | {row['tuber']} | {click} | {row['entry_state'] or '—'} | {iou} | "
                   f"{'yes' if row['lost_potato_later'] else 'no'} | "
                   f"{row['failure_category'].replace('_', ' ') or '—'} | {weight} |")
    return "\n".join(out) if len(out) > 2 else "All masks matched and all paired weights were scorable."


def write_report(rows, summary):
    n = summary["enrolled"]
    lo, hi = summary["center_match_binomial_95"]
    m = summary["scorable_paired_weights"]
    weight_text = "The paired MAEs and bootstrap interval could not be estimated."
    if m:
        means = summary["paired_mae_g"]
        low, high = summary["paired_mean_change_bootstrap_95_g"]
        weight_text = (
            f"Human-click masks had **{means['human']:.2f} g MAE** and provided masks had "
            f"**{means['provided']:.2f} g MAE** on the same potatoes. The paired human-minus-provided change "
            f"was **{summary['paired_mean_change_g']:+.2f} g** (95% tuber-bootstrap interval **{low:+.2f} to {high:+.2f} g**)."
        )
    text = [
        "# Held-out SAM 2 peel-click confirmation", "",
        f"**{summary['potato_matches']}/{n}** center masks matched the intended potato at IoU ≥ 0.5 "
        f"(**{summary['center_match_fraction']:.1%}**, exact 95% binomial interval **{lo:.1%} to {hi:.1%}**). "
        f"The denominator includes all enrolled potatoes and {summary['responses'].get('cannot_identify', 0)} skips.", "",
        f"**{m}/{n}** paired weights were scorable. {weight_text}", "",
        "The previously unused targets come from the frozen PointRAFT test roster. One first-time operator "
        "used the frozen written instruction and annotation-derived arrows. The binomial interval describes "
        "variation across potatoes in this session. The weight pipeline used the archived Model A and measured thickness. "
        "[Protocol](protocol.md) · [Cohort audit](eligibility_audit.csv) · [Frozen click receipt](click_freeze.json)", "",
        "## Mask and weight failures", "",
        f"{len(summary['pin_at_entry_failure_ids'])} center failures selected the pin at entry. "
        f"{len(summary['lost_potato_later_failure_ids'])} center failures reached the potato threshold and later lost it.", "",
        show_failures(rows), "",
        "[Per-potato results](per_potato.csv) · [Frame-by-frame states](per_frame.csv) · [Full-precision summary](results.json)", "",
    ]
    (STUDY / "report.md").write_text("\n".join(text))


def run():
    frozen = prepare.read_cohort()
    clicks, receipt = completed_session(frozen)
    if (STUDY / "results.json").exists():
        raise ValueError("Confirmation already scored. Read results.json and report.md.")
    prepare.seal_json(STUDY / "score_started.json", receipt)
    import torch

    config = base.read_json(prepare.CONFIG)
    expected = {"torch": torch.__version__, "checkpoint_sha256": base.CHECKPOINT_HASH,
                "source_commit": base.SOURCE_COMMIT, "config": base.CONFIG, "threads": base.THREADS,
                "device": "cpu", "precision": "fp32", "interop_threads": 1, "optional_postprocessing": False}
    if any(config[key] != value for key, value in expected.items()):
        raise ValueError("Use the frozen CPU tracker settings and archived environment")
    rows = frozen["roster"]
    allowed = {r["tuber"] for r in rows}
    measurements = read_measurements(allowed)
    polygons = pin.load_polygons(frozen)
    matrix = base.intrinsics_from_json(base.read_json(base.INTRINSICS))
    masks = STUDY / "center_masks"
    masks.mkdir(exist_ok=True)
    needs_inference = any(click["response"] == "click" and not (masks/f"{frame['tuber']}.json").exists()
                          for click, frame in zip(clicks, rows, strict=True))
    predictor = base.build_cpu_predictor() if needs_inference else None
    results, states = [], []
    with ExitStack() as stack, torch.inference_mode():
        archives = base.open_image_archives(stack, frozen)
        for frame, click in zip(rows, clicks, strict=True):
            tuber = frame["tuber"]
            archive = archives[frame["archive"]]
            path = masks / f"{tuber}.json"
            if path.is_file():
                track = base.read_json(path)
                if track["receipt"] != receipt:
                    raise ValueError("A saved track belongs to a different click freeze")
            else:
                try:
                    track = human.track_one(predictor, archive, frame, click, polygons, masks, receipt)
                except (BadZipFile, OSError, KeyError) as error:
                    track = {"tuber": tuber, "receipt": receipt, "history": [], "wall_seconds": 0.,
                             "status": "inference_failure", "mask_sha256": None,
                             "error": f"{type(error).__name__}: {error}"}
                base.write_json(path, track)
            result = {**click, "tuber": tuber, "entry_file": frame["frames"][0]["rgb_member"],
                      "center_file": frame["frames"][-1]["rgb_member"], **human.mask_metrics(track)}
            try:
                result.update(human.click_placement(archive, frame, click, polygons))
            except (ValueError, BadZipFile, OSError, KeyError) as error:
                result.update({"click_region": "unavailable", "click_pin_signed_distance_px": None,
                               "click_region_error": f"{type(error).__name__}: {error}"})
            score_weights(result, track, archive, frame, matrix, measurements[tuber], masks)
            results.append(result)
            states.extend(track["history"])
            print(f"Scored {len(results)}/{len(rows)}", flush=True)

    summary = summarize(results)
    summary["freeze_receipt"] = receipt
    base.write_csv(STUDY / "per_potato.csv", results)
    if states:
        base.write_csv(STUDY / "per_frame.csv", states)
    else:
        (STUDY / "per_frame.csv").write_text(
            "tuber,frame_index,phase,suffix_px,rgb_file,mask_pixels,potato_pixels,"
            "pin_pixels,potato_iou,pin_iou,prediction_on_pin_fraction,state\n"
        )
    write_report(results, summary)
    base.write_json(STUDY / "results.json", summary)
    print(f"Saved report to {STUDY / 'report.md'}")


if __name__ == "__main__":
    with (STUDY / ".confirmation_score.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run()
        except (BlockingIOError, ValueError) as error:
            raise SystemExit(str(error)) from error
