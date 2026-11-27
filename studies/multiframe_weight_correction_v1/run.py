"""Fit and score the two frozen one-row-per-potato weight regressions."""

import argparse
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from studies.multiframe_weight_v1 import run as prior

HERE = Path(__file__).resolve().parent
ARCHIVE = prior.HERE / "frame_manifest.json"
PROXY = "center_proxy_cm3"
CHANGE = "area_change_at_center_height_cm3"
MODEL_COLUMNS = {"A": (PROXY,), "B": (PROXY, CHANGE)}
EXPECTED = {"train": 118, "val": 40}


def provenance():
    paths = (ARCHIVE, prior.HERE / "per_frame_predictions.csv", HERE / "protocol.md", Path(__file__))
    return {str(p.relative_to(prior.ROOT)): prior.sha(p) for p in paths}


def select_triplet(suffixes, midpoint):
    lower, upper = suffixes[0], suffixes[-1]
    quarter_positions = (lower + (upper-lower)*.25, lower + (upper-lower)*.75)
    return [min(suffixes, key=lambda suffix: (abs(suffix-goal), suffix))
            for goal in (quarter_positions[0], midpoint, quarter_positions[1])]


def check_roster(rows):
    if (Counter(r["split"] for r in rows) != EXPECTED or
            len({r["tuber"] for r in rows}) != sum(EXPECTED.values())):
        raise ValueError("Expected the exact disjoint 118-train and 40-validation cohort")


def extract_features(rows):
    # The earlier archived table contains scan features and predictions, with no measured weights.
    old = {(r["tuber"], int(r["suffix_px"])): r
           for r in prior.read_csv(prior.HERE / "per_frame_predictions.csv")}
    with ZipFile(prior.CLOUDS) as archive:
        by_id, failed = prior.tabulate_features(archive, rows)
    if failed:
        raise ValueError(f"Frozen cloud extraction failed: {failed}")
    output = []
    for row in rows:
        tuber, split = row["tuber"], row["split"]
        lower, center, upper = row["frames"]["spaced"]
        left, mid, right = (by_id[tuber][suffix] for suffix in (lower, center, upper))
        for suffix, props in zip((lower, center, upper), (left, mid, right), strict=True):
            if split == "val":
                saved = old[tuber, suffix]
                if any(props[key] != float(saved[key]) for key in ("area_mm2", "height_mm", "bulk_proxy_cm3")):
                    raise ValueError(f"Archived features did not replay: {tuber}/{suffix}")
        area_diff = (left["area_mm2"] + right["area_mm2"]) / 2 - mid["area_mm2"]
        output.append({
            "tuber": tuber, "split": split, "lower_suffix_px": lower, "center_suffix_px": center,
            "upper_suffix_px": upper, "lower_area_mm2": left["area_mm2"], "center_area_mm2": mid["area_mm2"],
            "upper_area_mm2": right["area_mm2"], "center_height_mm": mid["height_mm"],
            "outer_mean_minus_center_area_mm2": area_diff,
            PROXY: mid["bulk_proxy_cm3"], CHANGE: area_diff * mid["height_mm"] / 1000,
        })
    return output


def feature_summary(features):
    summary = {}
    for split in EXPECTED:
        values = np.array([float(r[CHANGE]) for r in features if r["split"] == split])
        if not np.isfinite(values).all() or np.ptp(values) <= 1e-9:
            raise ValueError(f"Area-change feature did not vary within {split}")
        summary[split] = {
            "min_cm3": float(values.min()), "max_cm3": float(values.max()),
            "mean_cm3": float(values.mean()), "sample_sd_cm3": float(values.std(ddof=1)),
            "negative": int((values < 0).sum()), "positive": int((values > 0).sum()),
            "zero": int((values == 0).sum()),
        }
    return summary


def freeze(out):
    frozen_path = out / "frame_manifest.json"
    if frozen_path.exists():
        raise FileExistsError(frozen_path)
    source = prior.read_json(ARCHIVE)
    if (source["stage"] != "frozen_before_fit_and_weight_errors" or
            source["source_sha256"] != prior.sources() or source["archive_bytes"] != prior.CLOUDS.stat().st_size):
        raise ValueError("The prior study's frozen inputs changed")
    check_roster(source["frames"])
    rows, adjacent_overlaps = [], []
    for old in source["frames"]:
        suffixes = old["available_suffixes"]
        triplet = select_triplet(suffixes, source["camera_midpoint_suffix_px"])
        lower, center, upper = triplet
        if not lower < center < upper:
            raise ValueError(f"Quarter/center positions out of order for {old['tuber']}: {triplet}")
        if old["split"] == "val" and triplet != old["frames"]["spaced"]:
            raise ValueError(f"Validation layout changed for {old['tuber']}")
        index = suffixes.index(center)
        if old["split"] == "train" and (lower == suffixes[index-1] or upper == suffixes[index+1]):
            adjacent_overlaps.append({"tuber": old["tuber"], "triplet": triplet,
                                      "adjacent": suffixes[index-1:index+2]})
        members = {m["suffix"]: m for m in old["members"]}
        rows.append({"tuber": old["tuber"], "split": old["split"], "frames": {"spaced": triplet},
                     "members": [members[i] for i in triplet]})
    features = extract_features(rows)
    summary = feature_summary(features)
    feature_path = out / "scan_features.csv"
    prior.write_csv(feature_path, features)
    prior.save_json(frozen_path, {
        "stage": "frames_features_and_model_specifications_frozen_before_fit", "source_sha256": provenance(),
        "features_sha256": prior.sha(feature_path), "frame_count": 3*len(rows),
        "validation_triples_and_features_replayed": True, "roster_counts": EXPECTED,
        "checked_area_change": summary, "model_features": MODEL_COLUMNS,
        "training_adjacent_overlaps": adjacent_overlaps, "frames": rows,
    })
    print("Frozen 118 training triplets and replayed 40 validation triplets.", summary, flush=True)


def design(rows, columns):
    return np.array([[1., *(float(row[column]) for column in columns)] for row in rows])


def weight_values(rows):
    ids = {r["tuber"] for r in rows}
    weights = prior.target_rows(ids)
    if any(len(weights[t]) != 1 or not prior.valid_weight(weights[t][0]["weight"]) for t in ids):
        raise ValueError("Expected a single positive measured weight per included potato")
    return np.array([float(weights[r["tuber"]][0]["weight"]) for r in rows])


def score(out):
    if (out / "results.json").exists():
        raise FileExistsError("A score already exists here")
    freeze_path = out / "frame_manifest.json"
    feature_path = out / "scan_features.csv"
    freeze = prior.read_json(freeze_path)
    if (freeze["stage"] != "frames_features_and_model_specifications_frozen_before_fit" or
            freeze["source_sha256"] != provenance() or freeze["features_sha256"] != prior.sha(feature_path)):
        raise ValueError("Frozen inputs changed")
    if prior.read_json(ARCHIVE)["source_sha256"] != prior.sources():
        raise ValueError("Original release metadata changed")
    rows = prior.read_csv(feature_path)
    check_roster(rows)
    train, val = ([r for r in rows if r["split"] == split] for split in ("train", "val"))
    target = weight_values(train)
    models, predictions = {}, {}
    for key, columns in MODEL_COLUMNS.items():
        train_x = design(train, columns)
        if np.linalg.matrix_rank(train_x) != train_x.shape[1]:
            raise ValueError(f"Non-full-rank training design for model {key}")
        coefficients = np.linalg.lstsq(train_x, target, rcond=None)[0]
        models[key] = dict(zip(("intercept_g", *(f"{c}_coefficient_g_per_cm3" for c in columns)),
                               map(float, coefficients), strict=True))
        predictions[key] = design(val, columns) @ coefficients
    prior.save_json(out / "train_fit.json", {
        "frame_manifest_sha256": prior.sha(freeze_path), "fitted_training_rows": len(train), "models": models,
    })
    observed = weight_values(val)
    errors = {key: np.abs(values-observed) for key, values in predictions.items()}
    delta = errors["B"] - errors["A"]
    scored = [{**row, "measured_g": float(observed[i]),
               "A_predicted_g": float(predictions["A"][i]), "B_predicted_g": float(predictions["B"][i]),
               "A_abs_error_g": float(errors["A"][i]), "B_abs_error_g": float(errors["B"][i]),
               "B_minus_A_error_g": float(delta[i])} for i, row in enumerate(val)]
    prediction_path = out / "predictions.csv"
    prior.write_csv(prediction_path, scored)
    indices = np.random.default_rng(prior.SEED).integers(0, len(val), (prior.DRAWS, len(val)))
    reference = prior.read_json(prior.HERE / "results.json")["mae_g"]["center"]
    summary = {
        "train_tubers": len(train), "validation_tubers": len(val), "models": models,
        "mae_g": {key: float(v.mean()) for key, v in errors.items()},
        "B_minus_A": prior.compare("B", "A", errors, indices),
        "earlier_center_mae_g_all_training_frames": reference,
        "bootstrap_draws": prior.DRAWS, "bootstrap_seed": prior.SEED,
        "predictions_sha256": prior.sha(prediction_path),
    }
    prior.save_json(out / "results.json", summary)
    print(summary["mae_g"], summary["B_minus_A"], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "score"))
    parser.add_argument("--out", type=Path, default=HERE)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"freeze": freeze, "score": score}[args.phase](args.out)


if __name__ == "__main__":
    main()
