"""Join the pinned L1 predictions to the archived L0, L2 and L3 outcomes."""

import argparse
from collections import Counter
from pathlib import Path

import numpy as np

from studies.rgb_monocular_height_v1 import infer as l1

base = l1.base
l2 = l1.learned
prior = l1.prior
ARMS = ("silhouette", "monocular", "learned_rgb", "camera")
COMPARISONS = {"mono_minus_silhouette": ("monocular", "silhouette"),
               "mono_minus_learned_rgb": ("monocular", "learned_rgb"),
               "mono_minus_camera": ("monocular", "camera")}


def analysis(output):
    return {"frame_manifest_sha256": prior.sha(output / "frame_manifest.json"),
            "scorer_sha256": prior.sha(Path(__file__)), "seed": l2.SEED, "resamples": l2.DRAWS,
            "primary": "monocular minus silhouette absolute weight error",
            "contrasts": {k: list(v) for k, v in COMPARISONS.items()}}


def freeze(output):
    l1.manifest(output)
    prior.save_json(output / "analysis_freeze.json", analysis(output))
    print("Scoring specification frozen before development predictions.", flush=True)


def references(ids):
    shape, traits, old, sources = l2.historical_targets(ids)
    previous_results = prior.read_json(l2.HERE / "results.json")
    old_l2_traces = l2.HERE / "predictions_before_targets.json"
    old_l2_scores = l2.HERE / "per_potato.csv"
    sources["l2_prediction"] = prior.sha(old_l2_traces)
    sources["l2_scores"] = prior.sha(old_l2_scores)
    if (sources["l2_prediction"] != previous_results["predictions_sha256"]
            or sources["l2_scores"] != previous_results["per_potato_sha256"]):
        raise ValueError("Archived L2 prediction or score changed")
    scored_l2 = l2.indexed(prior.read_csv(old_l2_scores))
    prediction_l2 = l2.indexed(prior.read_json(old_l2_traces)["rows"])
    if set(scored_l2) != ids or set(prediction_l2) != ids:
        raise ValueError("Archived L2 and camera-height cohorts differ")
    upstream = prior.read_json(base.HERE / "train_fit.json")["traits"]
    return shape, traits, old, scored_l2, prediction_l2, upstream, sources


def join(entries, refs):
    shape, traits, old, scored_l2, prediction_l2, upstream, _ = refs
    rows = []
    for record in entries:
        tuber = record["tuber"]
        item, cam, rgb = traits[tuber], old[tuber], prediction_l2[tuber]
        for member in (shape[tuber], item, cam, rgb):
            if int(member["suffix_px"]) != record["suffix_px"]:
                raise ValueError(f"Archived center disagreement for {tuber}")
        if record["geometry"] is not None:
            new = {**record["geometry"], "tuber": tuber, "suffix_px": record["suffix_px"]}
            l2.replay_geometry(new, shape[tuber])
        h_cam = cam["height_mm"]
        h_l2 = rgb["height_predictions_mm"]["rgb_height"]
        h_mono = record["estimated_height_mm"]
        l2.check_close(l2.optional_number(item["height_mm"]), h_cam, f"{tuber} camera")
        l2.check_close(l2.optional_number(scored_l2[tuber]["camera_height_mm"]), h_cam, f"{tuber} L2 camera ref")
        l2.check_close(l2.optional_number(scored_l2[tuber]["rgb_height_mm"]), h_l2, f"{tuber} L2 height")
        row = {key: record[key] for key in ("tuber", "suffix_px", "B_m", "T_m", "valid_background_pixels",
                                            "valid_target_pixels", "failure_type", "failure_detail", "wall_s")}
        row.update(camera_height_mm=h_cam, monocular_height_mm=h_mono, learned_rgb_height_mm=h_l2)
        for name, h in (("monocular", h_mono), ("learned_rgb", h_l2)):
            error = h - h_cam if h is not None and h_cam is not None else None
            row[f"{name}_height_signed_error_mm"] = error
            row[f"{name}_height_abs_error_mm"] = abs(error) if error is not None else None
        for trait in base.TARGETS:
            measured = l2.optional_number(item[f"{trait}_measured"])
            names = {
                "silhouette": cam["predictions"][trait]["mask_only"],
                "monocular": record["trait_predictions"][trait],
                "learned_rgb": rgb["trait_predictions"][trait]["rgb_height"],
                "camera": cam["predictions"][trait]["depth_assisted"],
            }
            l2.check_close(l2.optional_number(scored_l2[tuber][f"{trait}_measured"]), measured, f"{tuber}/{trait} reference")
            l2.check_close(l2.optional_number(scored_l2[tuber][f"{trait}_rgb_height_prediction"]),
                           names["learned_rgb"], f"{tuber}/{trait} L2 replay")
            l2.check_close(l2.optional_number(item[f"{trait}_mask_only_prediction"]),
                           names["silhouette"], f"{tuber}/{trait} L0 replay")
            l2.check_close(l2.optional_number(item[f"{trait}_depth_assisted_prediction"]),
                           names["camera"], f"{tuber}/{trait} L3 replay")
            if h_mono is not None and record["geometry"] is not None:
                expected = l2.trait_prediction(shape[tuber], upstream[trait]["coefficients"]["depth_assisted"], h_mono)
                l2.check_close(names["monocular"], expected, f"{tuber}/{trait} frozen height substitution")
            row[f"{trait}_reference"] = measured
            for arm, value in names.items():
                row[f"{trait}_{arm}_prediction"] = value
                row[f"{trait}_{arm}_abs_error"] = abs(value-measured) if value is not None and measured is not None else None
        rows.append(row)
    return rows


def trait_summary(rows, trait):
    names = {arm: f"{trait}_{arm}_abs_error" for arm in ARMS}
    common = [r for r in rows if all(r[n] is not None for n in names.values())]
    arms = {
        arm: {"scored": sum(r[name] is not None for r in rows),
              "mae_common": float(np.mean([r[name] for r in common])) if common else None}
        for arm, name in names.items()
    }
    comparisons = {name: l2.paired_stats(common, names[first], names[baseline])
                   for name, (first, baseline) in COMPARISONS.items()}
    return {"common_ids": [r["tuber"] for r in common], "arms": arms, "comparisons": comparisons}


def height_summary(rows):
    arms = ("monocular", "learned_rgb")
    common = [r for r in rows if all(r[f"{a}_height_abs_error_mm"] is not None for a in arms)]
    return {
        "common_ids": [r["tuber"] for r in common],
        "camera_reference_n": sum(r["camera_height_mm"] is not None for r in rows),
        "arms": {a: {"scored": sum(r[f"{a}_height_abs_error_mm"] is not None for r in rows),
                     "mae_mm": float(np.mean([r[f"{a}_height_abs_error_mm"] for r in common])) if common else None,
                     "bias_mm": float(np.mean([r[f"{a}_height_signed_error_mm"] for r in common])) if common else None}
                 for a in arms},
        "mono_minus_learned_rgb_abs_error": l2.paired_stats(common, "monocular_height_abs_error_mm",
                                                           "learned_rgb_height_abs_error_mm"),
    }


def score(output):
    fixed = l1.manifest(output)
    sealed = prior.read_json(output / "analysis_freeze.json")
    if sealed != analysis(output):
        raise ValueError("Scorer differs from frozen analysis")
    result_path = output / "results.json"
    if result_path.exists():
        raise ValueError("Frozen comparison already scored")
    pred_path = output / "predictions_before_targets.json"
    predictions = prior.read_json(pred_path)
    if (predictions["manifest_sha256"] != prior.sha(output / "frame_manifest.json")
            or predictions["training_preflight_sha256"] != prior.sha(output / "training_preflight.json")
            or predictions["checkpoint_sha256"] != l1.WEIGHT_HASH or predictions["model_revision"] != l1.REVISION):
        raise ValueError("Predictions differ from the checked model and input freeze")
    records = predictions["per_frame"]
    if [(r["tuber"], r["suffix_px"]) for r in records] != [(r["tuber"], r["suffix_px"]) for r in fixed["evaluation"]]:
        raise ValueError("Frozen 40-case prediction roster differs")
    refs = references({r["tuber"] for r in records})
    rows = join(records, refs)
    results = {
        "enrolled": len(rows), "predictions_sha256": prior.sha(pred_path),
        "archived_scores_sha256": refs[-1], "height": height_summary(rows),
        "traits": {trait: trait_summary(rows, trait) for trait in base.TARGETS},
        "failures": dict(Counter(r["failure_type"] for r in rows if r["failure_type"])),
        "failure_ids": {r["tuber"]: r["failure_type"] for r in rows if r["failure_type"]},
        "runtime": {
            "load_s": predictions["load_s"], "sum_frame_wall_s": sum(r["wall_s"] for r in records),
            "median_frame_wall_s": float(np.median([r["wall_s"] for r in records])),
            "sum_forward_s": sum(r["runtime"]["forward_s"] for r in records if r["runtime"]),
        },
    }
    prior.write_csv(output / "per_potato.csv", rows)
    results["per_potato_sha256"] = prior.sha(output / "per_potato.csv")
    prior.save_json(result_path, results)
    print("Weight results:", {k: v for k, v in results["traits"]["weight"].items() if k != "common_ids"}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "score"))
    parser.add_argument("--out", type=Path, default=l1.HERE)
    args = parser.parse_args()
    {"freeze": freeze, "score": score}[args.stage](args.out)
