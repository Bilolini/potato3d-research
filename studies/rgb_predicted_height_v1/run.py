"""Fit and score compact silhouette and RGB height predictors at the archived centers."""

import argparse
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from PIL import Image
from scipy.ndimage import binary_erosion, distance_transform_edt
from scipy.spatial import ConvexHull, QhullError

from studies.rgb_only_height_value_v1 import run as benchmark

prior = benchmark.prior
HERE = Path(__file__).resolve().parent
BASE = benchmark.HERE
SHAPE = ("area_sqrt_mm", "log_silhouette_axis_ratio", "silhouette_hull_fill")
COLOR = ("luma_median", "luma_90_minus_10", "red_chromaticity_median",
         "green_chromaticity_median", "core_minus_rim_luma")
HEIGHT_FEATURES = {"sil_height": SHAPE, "rgb_height": (*SHAPE, *COLOR)}
ARMS = ("mask_only", "sil_height", "rgb_height", "camera_height")
PENALTIES = (.001, .01, .1, 1., 10.)
GEOMETRY = ("projected_area_mm2", "area_volume_proxy_cm3", "log_silhouette_axis_ratio")
SEED = 5272401
DRAWS = 10_000


def sources():
    paths = (Path(__file__), HERE / "protocol.md", BASE / "run.py", BASE / "frame_manifest.json",
             BASE / "train_fit.json", benchmark.HELD_OUT, prior.CAMERA, prior.WARNINGS,
             *(spec[0] for spec in prior.RESERVATIONS.values()))
    return {str(p.relative_to(prior.ROOT)): prior.sha(p) for p in paths}


def freeze(output):
    archive = prior.read_json(BASE / "frame_manifest.json")
    upstream_fit = prior.read_json(BASE / "train_fit.json")
    if upstream_fit["manifest_sha256"] != prior.sha(BASE / "frame_manifest.json"):
        raise ValueError("Upstream trait fit refers to a different archived dataset")
    held = {r["tuber"] for r in prior.read_json(benchmark.HELD_OUT)["roster"]}
    reserved = set(prior.published_id_exclusions()) | held
    ids = {r["tuber"] for r in archive["roster"]}
    if (len(held) != 45 or ids & reserved or len(ids) != 158
            or Counter(r["split"] for r in archive["roster"]) != {"train": 118, "val": 40}):
        raise ValueError("Unexpected train/development roster or reserved overlap")
    if (archive["belt_depth_mm"] != benchmark.BELT_MM
            or archive["sources_sha256"][str(prior.CAMERA.relative_to(prior.ROOT))] != prior.sha(prior.CAMERA)):
        raise ValueError("Archived fixed calibration differs")
    roster = [{**{k: r[k] for k in ("tuber", "split", "suffix_px", "acquisition_group")},
               "rgb": r["inputs"]["rgb"]} for r in archive["roster"]]
    prior.save_json(output / "frame_manifest.json", {
        "sources_sha256": sources(), "roster": roster, "belt_depth_mm": archive["belt_depth_mm"],
        "pixel_area_mm2": archive["projected_pixel_area_mm2"], "camera_matrix_px": archive["camera_matrix_px"],
        "image_payloads": "frozen center RGBA only",
        "height_features": HEIGHT_FEATURES, "ridge_penalties": PENALTIES, "bootstrap_seed": SEED, "bootstrap_draws": DRAWS,
        "trait_fit_sha256": prior.sha(BASE / "train_fit.json"),
    })
    print("Froze the 118 training and 40 development RGB centers and training-only selection rule.", flush=True)


def manifest(output):
    fixed = prior.read_json(output / "frame_manifest.json")
    if fixed["sources_sha256"] != sources():
        raise ValueError("Frozen input or code changed")
    return fixed


def shaped_features(mask, geometry):
    boundary = mask & ~binary_erosion(mask)
    y, x = np.nonzero(boundary)
    centers = np.column_stack((x, y))
    hull = ConvexHull(centers)
    offsets = np.asarray([[-.5, -.5], [-.5, .5], [.5, -.5], [.5, .5]])
    corners = (centers[hull.vertices, None, :] + offsets[None, :, :]).reshape(-1, 2)
    hull_pixels = ConvexHull(corners).volume
    return {"area_sqrt_mm": float(np.sqrt(geometry["projected_area_mm2"])),
            "silhouette_hull_fill": float(geometry["mask_pixels"] / hull_pixels)}


def appearance_features(scene, mask):
    y, x = np.nonzero(mask)
    crop = np.s_[y.min():y.max() + 1, x.min():x.max() + 1]
    local_mask = mask[crop]
    distance = distance_transform_edt(np.pad(local_mask, 1))[1:-1, 1:-1][local_mask]
    lower, upper = np.quantile(distance, [.25, .75])
    colors = scene[crop][:, :, :3][local_mask].astype(float) / 255.
    luma = colors @ np.array([.2126, .7152, .0722])
    q10, q50, q90 = np.quantile(luma, [.1, .5, .9])
    sums = colors.sum(axis=1, keepdims=True)
    chroma = np.divide(colors[:, :2], sums, out=np.zeros_like(colors[:, :2]), where=sums > 0.)
    red, green = np.median(chroma, axis=0)
    contrast = np.median(luma[distance >= upper]) - np.median(luma[distance <= lower])
    return dict(zip(COLOR, map(float, (q50, q90 - q10, red, green, contrast)), strict=True))


def extract(case, fixed, archives):
    row = {key: case[key] for key in ("tuber", "split", "suffix_px", "acquisition_group")}
    row.update(dict.fromkeys((*GEOMETRY, *HEIGHT_FEATURES["rgb_height"])))
    row["input_failure"] = None
    try:
        if case["rgb"] is None:
            raise ValueError("Archived center RGBA unavailable")
        with Image.open(benchmark.member_data(archives, case["rgb"])) as image:
            if image.mode != "RGBA" or image.size != (1280, 720):
                raise ValueError("Invalid full-resolution center RGBA")
            scene = np.asarray(image)
        alpha = scene[:, :, 3] > 0
        k = fixed["camera_matrix_px"]
        shape = benchmark.silhouette_features(alpha, k[0][0], k[1][1], fixed["pixel_area_mm2"])
        row.update({key: shape[key] for key in GEOMETRY})
        row.update(shaped_features(alpha, shape))
        row.update(appearance_features(scene, alpha))
    except (*benchmark.ERRORS, QhullError) as error:
        row["input_failure"] = f"{type(error).__name__}: {error}"
    return row


def inputs(fixed, split):
    chosen = [r for r in fixed["roster"] if r["split"] == split]
    names = {r["rgb"]["archive"] for r in chosen if r["rgb"] is not None}
    with ExitStack() as stack:
        archives = {name: stack.enter_context(ZipFile(benchmark.IMAGES / name)) for name in sorted(names)}
        return [extract(case, fixed, archives) for case in chosen]


def indexed(rows):
    index = {r["tuber"]: r for r in rows}
    if len(index) != len(rows):
        raise ValueError("Duplicate exact tuber label")
    return index


def replay_geometry(row, archived):
    if int(archived["suffix_px"]) != int(row["suffix_px"]):
        raise ValueError(f"Archived center disagrees for {row['tuber']}")
    for key in GEOMETRY:
        if not np.isclose(float(row[key]), float(archived[key]), atol=1e-10, rtol=0):
            raise ValueError(f"Archived fixed-scale silhouette feature changed for {row['tuber']}/{key}")


def ridge(x, y, penalty):
    location = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-12] = 1.
    z = (x - location) / scale
    intercept = float(y.mean())
    # Multiplying the MSE objective by n gives the corresponding normal equations.
    coefficients = np.linalg.solve(z.T @ z + len(x)*penalty*np.eye(x.shape[1]), z.T @ (y - intercept))
    return {"location": location.tolist(), "scale": scale.tolist(), "intercept_mm": intercept,
            "standardized_coefficients_mm": coefficients.tolist()}


def estimate(x, model):
    z = (x - np.asarray(model["location"])) / model["scale"]
    return np.maximum(0., model["intercept_mm"] + z @ np.asarray(model["standardized_coefficients_mm"]))


def select(x, y, groups):
    folds = [np.where(groups == g)[0] for g in sorted(set(groups))]
    trials = []
    for penalty in PENALTIES:
        predictions = np.empty_like(y)
        for left_out in folds:
            kept = np.ones(len(y), dtype=bool)
            kept[left_out] = False
            model = ridge(x[kept], y[kept], penalty)
            predictions[left_out] = estimate(x[left_out], model)
        trials.append({"penalty": penalty, "oof_mae_mm": float(np.abs(predictions - y).mean()),
                       "oof_bias_mm": float((predictions-y).mean())})
    best = min(r["oof_mae_mm"] for r in trials)
    chosen = max(r["penalty"] for r in trials if r["oof_mae_mm"] <= best+1e-12)
    return chosen, trials


def fit(output):
    fixed = manifest(output)
    known = BASE / "train_features.csv"
    parent_fit = prior.read_json(BASE / "train_fit.json")
    if prior.sha(known) != parent_fit["training_features_sha256"]:
        raise ValueError("Archived training height inputs changed")
    archived = indexed(prior.read_csv(known))
    rows = inputs(fixed, "train")
    if set(indexed(rows)) != set(archived) or any(r["split"] != "train" for r in archived.values()):
        raise ValueError("Archived supervised heights do not match the training roster")
    for row in rows:
        source = archived[row["tuber"]]
        if row["input_failure"] is None:
            replay_geometry(row, source)
        row["label_height_mm"] = float(source["height_mm"]) if source["height_mm"] else None
    matched = [r for r in rows if r["input_failure"] is None and r["label_height_mm"] is not None]
    y = np.asarray([r["label_height_mm"] for r in matched], dtype=float)
    groups = np.asarray([r["acquisition_group"] for r in matched])
    if len(matched) < 20 or len(set(groups)) < 2 or not np.isfinite(y).all() or np.any(y <= 0.):
        raise ValueError("Insufficient or invalid archived training heights")
    models = {}
    for arm, names in HEIGHT_FEATURES.items():
        x = np.asarray([[r[n] for n in names] for r in matched], dtype=float)
        penalty, cv = select(x, y, groups)
        models[arm] = {"features": list(names), "chosen_penalty": penalty, "group_cv": cv,
                       **ridge(x, y, penalty)}
    prior.write_csv(output / "training_features.csv", rows)
    prior.save_json(output / "train_fit.json", {
        "manifest_sha256": prior.sha(output / "frame_manifest.json"),
        "training_features_sha256": prior.sha(output / "training_features.csv"),
        "archived_training_labels_sha256": prior.sha(known),
        "selection_rule": "leave one acquisition group out; equal-potato out-of-fold MAE",
        "groups": {g: sorted(r["tuber"] for r in matched if r["acquisition_group"] == g) for g in sorted(set(groups))},
        "fit_ids": [r["tuber"] for r in matched], "excluded_ids": sorted(set(archived)-{r["tuber"] for r in matched}),
        "models": models,
    })
    print("Selected penalties on training acquisition groups only:",
          {arm: fit["chosen_penalty"] for arm, fit in models.items()}, flush=True)


def trait_prediction(features, coefs, height=None):
    total = coefs["intercept"]
    for key in benchmark.FEATURES["mask_only"]:
        total += coefs[key] * float(features[key])
    if height is not None:
        total += coefs["area_height_cm3"] * float(features["projected_area_mm2"]) * height / 1000.
    return max(0., total)


def predict(output):
    fixed = manifest(output)
    model_path = output / "train_fit.json"
    fits = prior.read_json(model_path)
    if fits["manifest_sha256"] != prior.sha(output / "frame_manifest.json"):
        raise ValueError("Fitted heights refer to a different roster")
    upstream = prior.read_json(BASE / "train_fit.json")
    rows = inputs(fixed, "val")
    records = []
    for row in rows:
        h = dict.fromkeys(HEIGHT_FEATURES)
        traits = {trait: dict.fromkeys(ARMS[:-1]) for trait in benchmark.TARGETS}
        if row["projected_area_mm2"] is not None:
            for arm, recipe in fits["models"].items():
                values = [row[name] for name in recipe["features"]]
                if all(value is not None for value in values):
                    h[arm] = float(estimate(np.asarray(values), recipe))
            for trait, archived in upstream["traits"].items():
                coef = archived["coefficients"]
                traits[trait]["mask_only"] = trait_prediction(row, coef["mask_only"])
                for arm, value in h.items():
                    if value is not None:
                        traits[trait][arm] = trait_prediction(row, coef["depth_assisted"], value)
        records.append({**{key: row[key] for key in ("tuber", "suffix_px", "input_failure")},
                        "height_predictions_mm": h, "trait_predictions": traits})
    feature_path = output / "validation_rgb_features.csv"
    prior.write_csv(feature_path, rows)
    prior.save_json(output / "predictions_before_targets.json", {
        "fit_sha256": prior.sha(model_path), "trait_fit_sha256": fixed["trait_fit_sha256"],
        "validation_rgb_features_sha256": prior.sha(feature_path),
        "inputs": ["center RGB", "provided alpha", "fixed D405 intrinsics and scale", "fitted model coefficients"],
        "rows": records,
    })
    print("Saved both height predictions and frozen-coefficient substitutions before the validation outcome join.", flush=True)


def frozen_predictions(output, fixed):
    path = output / "predictions_before_targets.json"
    saved = prior.read_json(path)
    need = {"fit_sha256": output / "train_fit.json", "trait_fit_sha256": BASE / "train_fit.json",
            "validation_rgb_features_sha256": output / "validation_rgb_features.csv"}
    if any(saved[key] != prior.sha(file) for key, file in need.items()):
        raise ValueError("Frozen height or trait predictions do not match their source hashes")
    validation = [(r["tuber"], r["suffix_px"]) for r in fixed["roster"] if r["split"] == "val"]
    if [(r["tuber"], r["suffix_px"]) for r in saved["rows"]] != validation:
        raise ValueError("Frozen prediction roster differs from validation")
    return saved


def historical_targets(ids):
    archived_result = prior.read_json(BASE / "results.json")
    archived_pred = prior.read_json(BASE / "predictions_before_targets.json")
    source_files = {"scores": BASE / "per_potato.csv", "features": BASE / "validation_features.csv",
                    "predictions": BASE / "predictions_before_targets.json"}
    hashes = {key: prior.sha(path) for key, path in source_files.items()}
    if (hashes["predictions"] != archived_result["predictions_sha256"]
            or hashes["scores"] != archived_result["per_potato_sha256"]
            or hashes["features"] != archived_pred["validation_features_sha256"]
            or prior.sha(BASE / "train_fit.json") != archived_pred["fit_sha256"]):
        raise ValueError("The archived validation targets or predictions changed")
    features = indexed(prior.read_csv(source_files["features"]))
    scored = indexed(prior.read_csv(source_files["scores"]))
    pred = indexed(archived_pred["predictions"])
    if not set(features) == set(scored) == set(pred) == ids:
        raise ValueError("Archived comparison uses a different validation roster")
    return features, scored, pred, hashes


def optional_number(s):
    return float(s) if s not in ("", None) else None


def check_close(new, archived, name):
    if new is None or archived is None:
        if new is archived:
            return
    elif np.isclose(new, archived, rtol=0, atol=1e-8):
        return
    raise ValueError(f"Historical feature or prediction did not replay: {name}")


def join_scores(saved, rgb_features, targets, upstream):
    features, scored, archived, _ = targets
    rows = []
    for item in saved["rows"]:
        tuber = item["tuber"]
        ft, row, old = features[tuber], scored[tuber], archived[tuber]
        from_rgb = rgb_features[tuber]
        check_close(item["suffix_px"], int(row["suffix_px"]), f"{tuber} center")
        if from_rgb["projected_area_mm2"]:
            replay_geometry(from_rgb, ft)
        truth = optional_number(ft["height_mm"])
        check_close(truth, old["height_mm"], f"{tuber} archived height")
        check_close(truth, optional_number(row["height_mm"]), f"{tuber} scored height")
        joined = {key: item[key] for key in ("tuber", "suffix_px", "input_failure")}
        joined.update(camera_height_mm=truth, archived_height_failure=ft["height_failure"])
        for arm, height in item["height_predictions_mm"].items():
            delta = height-truth if height is not None and truth is not None else None
            joined[f"{arm}_mm"] = height
            joined[f"{arm}_signed_error_mm"] = delta
            joined[f"{arm}_abs_error_mm"] = abs(delta) if delta is not None else None
        for trait in benchmark.TARGETS:
            prior_values = old["predictions"][trait]
            mask, camera = (prior_values[name] for name in ("mask_only", "depth_assisted"))
            if not ft["mask_failure"]:
                coef = upstream[trait]["coefficients"]
                check_close(trait_prediction(ft, coef["mask_only"]), mask, f"{tuber}/{trait} silhouette")
                if truth is not None:
                    check_close(trait_prediction(ft, coef["depth_assisted"], truth), camera, f"{tuber}/{trait} camera")
            check_close(optional_number(row[f"{trait}_mask_only_prediction"]), mask, f"{tuber}/{trait} L0")
            check_close(optional_number(row[f"{trait}_depth_assisted_prediction"]), camera, f"{tuber}/{trait} L3")
            if item["trait_predictions"][trait]["mask_only"] is not None:
                check_close(item["trait_predictions"][trait]["mask_only"], mask, f"{tuber}/{trait} replay L0")
            measured = optional_number(row[f"{trait}_measured"])
            joined[f"{trait}_measured"] = measured
            for arm in ARMS:
                value = {"mask_only": mask, "camera_height": camera}.get(arm, item["trait_predictions"][trait].get(arm))
                joined[f"{trait}_{arm}_prediction"] = value
                joined[f"{trait}_{arm}_abs_error"] = abs(value-measured) if value is not None and measured is not None else None
        rows.append(joined)
    return rows


def paired_stats(rows, first, baseline):
    if not rows:
        return {"n": 0, "mean_change": None, "interval_95": None}
    differences = np.asarray([r[first]-r[baseline] for r in rows])
    draws = np.random.default_rng(SEED).integers(len(rows), size=(DRAWS, len(rows)))
    return {
        "n": len(rows), "mean_change": float(differences.mean()),
        "interval_95": np.quantile(differences[draws].mean(axis=1), [.025,.975]).tolist(),
        "wins": int((differences < -1e-9).sum()), "ties": int((abs(differences) <= 1e-9).sum()),
        "losses": int((differences > 1e-9).sum()),
    }


def summarize_height(rows):
    common = [r for r in rows if all(r[f"{arm}_abs_error_mm"] is not None for arm in HEIGHT_FEATURES)]
    return {
        "common_ids": [r["tuber"] for r in common],
        "camera_reference_n": sum(r["camera_height_mm"] is not None for r in rows),
        "arms": {
            arm: {
                "predicted": sum(r[f"{arm}_mm"] is not None for r in rows),
                "scorable": sum(r[f"{arm}_abs_error_mm"] is not None for r in rows),
                "mae_mm": float(np.mean([r[f"{arm}_abs_error_mm"] for r in common])) if common else None,
                "signed_bias_mm": float(np.mean([r[f"{arm}_signed_error_mm"] for r in common])) if common else None,
            } for arm in HEIGHT_FEATURES
        },
        "rgb_minus_sil": paired_stats(common, "rgb_height_abs_error_mm", "sil_height_abs_error_mm"),
    }


def summarize_trait(rows, trait):
    unit = benchmark.TARGETS[trait][1]
    cols = {arm:f"{trait}_{arm}_abs_error" for arm in ARMS}
    common = [r for r in rows if all(r[col] is not None for col in cols.values())]
    contrasts = {
        "rgb_minus_mask": ("rgb_height", "mask_only"),
        "rgb_minus_sil_height": ("rgb_height", "sil_height"),
        "rgb_minus_camera_height": ("rgb_height", "camera_height"),
        "camera_minus_mask": ("camera_height", "mask_only"),
    }
    scores = {
        arm: {"scored": sum(r[col] is not None for r in rows),
              "mae": float(np.mean([r[col] for r in common])) if common else None}
        for arm, col in cols.items()
    }
    comparisons = {name: paired_stats(common, cols[first], cols[baseline])
                   for name, (first, baseline) in contrasts.items()}
    return {"unit": unit, "common_ids": [r["tuber"] for r in common],
            "arms": scores, "comparisons": comparisons}


def score(output):
    fixed = manifest(output)
    if (output / "results.json").exists():
        raise RuntimeError("The frozen comparison already has a scored result")
    saved = frozen_predictions(output, fixed)
    rgb_features = indexed(prior.read_csv(output / "validation_rgb_features.csv"))
    ids = {r["tuber"] for r in saved["rows"]}
    if set(rgb_features) != ids:
        raise ValueError("RGB feature and prediction rosters differ")
    historical = historical_targets(ids)
    upstream = prior.read_json(BASE / "train_fit.json")["traits"]
    rows = join_scores(saved, rgb_features, historical, upstream)
    prior.write_csv(output / "per_potato.csv", rows)
    result = {
        "enrolled": len(rows), "predictions_sha256": prior.sha(output / "predictions_before_targets.json"),
        "per_potato_sha256": prior.sha(output / "per_potato.csv"), "archived_validation_sha256": historical[-1],
        "height": summarize_height(rows), "traits": {trait: summarize_trait(rows, trait) for trait in benchmark.TARGETS},
        "input_failures": {r["tuber"]: r["input_failure"] for r in rows if r["input_failure"]},
    }
    prior.save_json(output / "results.json", result)
    print("Height MAE and bias:", result["height"]["arms"], flush=True)
    print("Weight MAEs:", result["traits"]["weight"]["arms"], flush=True)
    print("Weight differences:", result["traits"]["weight"]["comparisons"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "fit", "predict", "score"))
    parser.add_argument("--out", type=Path, default=HERE)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"freeze": freeze, "fit": fit, "predict": predict, "score": score}[args.stage](args.out)
