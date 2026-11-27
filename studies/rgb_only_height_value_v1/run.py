"""Measure the added value of a single camera-height feature on frozen center frames."""

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import csv
import io
import math
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile

import numpy as np
from PIL import Image

from studies.multiframe_weight_v1 import run as prior
from potato3d.calibration import intrinsics_from_json

HERE = Path(__file__).resolve().parent
ARCHIVED = prior.HERE / "frame_manifest.json"
CORRECTION = HERE.parent / "multiframe_weight_correction_v1/frame_manifest.json"
HELD_OUT = HERE.parent / "sam2_human_prompt_confirmation_v1/cohort_freeze.json"
IMAGES = prior.RELEASE / "1_rgbd/1_images"
EXPECTED = {"train": 118, "val": 40}
FILENAME = re.compile(r"(?P<tuber>[^/]+)/(?P=tuber)_(?P<type>rgb|depth)_(?P<suffix>[0-9]+)\.png")
BELT_MM = 350.
Z_BOUNDS_MM = (150., 400.)
DEPTH_QUANTILE = .05
MIN_DEPTH_PIXELS = 100
MIN_DEPTH_FRACTION = .5
FEATURES = {
    "mask_only": ("area_volume_proxy_cm3", "log_silhouette_axis_ratio"),
    "depth_assisted": ("area_volume_proxy_cm3", "log_silhouette_axis_ratio", "area_height_cm3"),
}
TARGETS = {"weight": ("weight_g_inctack", "g"), "volume": ("volume_ml", "mL")}
SEED = 5272401
DRAWS = 10_000
ERRORS = (ValueError, OSError, KeyError, BadZipFile, np.linalg.LinAlgError)


def sources():
    paths = (Path(__file__), HERE / "protocol.md", ARCHIVED, CORRECTION, HELD_OUT, prior.CAMERA, prior.TRAITS,
             *(row[0] for row in prior.RESERVATIONS.values()))
    return {str(path.relative_to(prior.ROOT)): prior.sha(path) for path in paths}


def frozen_roster():
    old = prior.read_json(ARCHIVED)
    correction = prior.read_json(CORRECTION)
    if old["source_sha256"] != prior.sources():
        raise ValueError("Original study's frozen source checksums differ")
    if correction["source_sha256"][str(ARCHIVED.relative_to(prior.ROOT))] != prior.sha(ARCHIVED):
        raise ValueError("Archived center follow-up refers to a different cohort")
    centers = {r["tuber"]: r for r in correction["frames"]}
    ids = {r["tuber"] for r in old["frames"]}
    held = {r["tuber"] for r in prior.read_json(HELD_OUT)["roster"]}
    if (len(ids) != 158 or len(centers) != len(correction["frames"]) or ids != set(centers)
            or len(held) != 45 or ids & (held | set(prior.published_id_exclusions()))
            or Counter(r["split"] for r in old["frames"]) != EXPECTED):
        raise ValueError("Archived roster or reserved cohort boundary changed")
    roster = []
    midpoint = old["camera_midpoint_suffix_px"]
    for row in old["frames"]:
        tuber = row["tuber"]
        chosen = centers[tuber]
        center = chosen["frames"]["spaced"][1]
        expected = min(row["available_suffixes"], key=lambda s: (abs(s - midpoint), s))
        if (center != expected or (row["split"] == "val" and [center] != row["frames"]["center"])
                or row["split"] != chosen["split"] or not row["acquisition_group"].startswith("2023")):
            raise ValueError(f"Frozen 2023 center frame does not replay for {tuber}")
        roster.append({"tuber": tuber, "split": row["split"], "suffix_px": center,
                       "acquisition_group": row["acquisition_group"], "cultivar": row["cultivar"]})
    return roster


def image_members(roster):
    centers = {row["tuber"]: row["suffix_px"] for row in roster}
    members = defaultdict(list)
    for path in sorted(IMAGES.glob("*.zip")):
        with ZipFile(path) as archive:
            for info in archive.infolist():
                match = FILENAME.fullmatch(info.filename)
                if match and centers.get(match["tuber"]) == int(match["suffix"]):
                    members[match["tuber"], match["type"]].append({
                        "archive": path.name, "member": info.filename, "crc32": info.CRC, "bytes": info.file_size,
                    })
    for row in roster:
        tuber = row["tuber"]
        options = {kind: members[tuber, kind] for kind in ("rgb", "depth")}
        row["inputs"] = {kind: items[0] if len(items) == 1 else None for kind, items in options.items()}
        row["metadata_failures"] = {kind: f"{len(items)} exact center archive members"
                                    for kind, items in options.items() if len(items) != 1}
        if all(row["inputs"].values()) and row["inputs"]["rgb"]["archive"] != row["inputs"]["depth"]["archive"]:
            row["inputs"]["depth"] = None
            row["metadata_failures"]["depth"] = "RGB and depth archive mismatch"
    return roster


def freeze(output):
    intrinsics = prior.read_json(prior.CAMERA)
    if (intrinsics["width"], intrinsics["height"]) != (1280, 720):
        raise ValueError("Unexpected ROI or image size")
    matrix = intrinsics_from_json(intrinsics)
    if matrix[0, 1] != 0 or matrix[1, 0] != 0:
        raise ValueError("Expected released zero-skew intrinsics")
    roster = image_members(frozen_roster())
    manifest = {
        "sources_sha256": sources(), "roster": roster, "model_features": FEATURES,
        "projected_pixel_area_mm2": BELT_MM**2 / (matrix[0, 0] * matrix[1, 1]),
        "camera_matrix_px": matrix.tolist(), "belt_depth_mm": BELT_MM,
        "depth_rule": {"min_z_inclusive_mm": Z_BOUNDS_MM[0], "max_z_exclusive_mm": Z_BOUNDS_MM[1],
                       "quantile": DEPTH_QUANTILE, "min_count": MIN_DEPTH_PIXELS, "min_fraction": MIN_DEPTH_FRACTION},
        "bootstrap_seed": SEED, "bootstrap_draws": DRAWS,
    }
    prior.save_json(output / "frame_manifest.json", manifest)
    print(f"Frozen {len(roster)} exact archived center frames and fixed silhouette/depth rules.", flush=True)


def load_manifest(output):
    frozen = prior.read_json(output / "frame_manifest.json")
    if frozen["sources_sha256"] != sources():
        raise ValueError("Frozen inputs or analysis code changed")
    return frozen


def member_data(archives, member):
    archive = archives[member["archive"]]
    entry = archive.getinfo(member["member"])
    if (entry.CRC, entry.file_size) != (member["crc32"], member["bytes"]):
        raise ValueError("Frozen PNG member changed")
    return io.BytesIO(archive.read(entry))


def read_mask(archives, member):
    with Image.open(member_data(archives, member)) as image:
        if image.mode != "RGBA" or image.size != (1280, 720):
            raise ValueError("Expected the full-resolution released RGBA")
        return np.asarray(image.getchannel("A")) > 0


def silhouette_features(mask, fx, fy, pixel_area):
    y, x = np.nonzero(mask)
    if len(x) < 3:
        raise ValueError("Fewer than three foreground pixels")
    xy = np.column_stack((x * (BELT_MM / fx), y * (BELT_MM / fy)))
    xy -= xy.mean(axis=0)
    low, high = np.linalg.eigvalsh(xy.T @ xy / len(x))
    if low <= 0 or not np.isfinite(high):
        raise ValueError("Degenerate silhouette axis ratio")
    area = len(x) * pixel_area
    return {"mask_pixels": len(x), "projected_area_mm2": area,
            "area_volume_proxy_cm3": area**1.5 / 1000.,
            "log_silhouette_axis_ratio": float(.5 * math.log(high / low))}


def depth_features(archives, member, mask, area):
    with Image.open(member_data(archives, member)) as image:
        depth = np.asarray(image)
    if depth.shape != mask.shape or depth.dtype != np.uint16:
        raise ValueError("Expected aligned, 16-bit metric depth at the same image size")
    z = depth[mask]
    accepted = z[(z >= Z_BOUNDS_MM[0]) & (z < Z_BOUNDS_MM[1])]
    coverage = len(accepted) / len(z)
    result = {"valid_depth_pixels": len(accepted), "valid_depth_fraction": coverage}
    if len(accepted) < MIN_DEPTH_PIXELS or coverage < MIN_DEPTH_FRACTION:
        return {**result, "height_failure": "Insufficient valid depth support"}
    top = float(np.quantile(accepted, DEPTH_QUANTILE))
    height = BELT_MM - top
    if height <= 0:
        return {**result, "near_surface_depth_mm": top, "height_failure": "Nonpositive height"}
    return {**result, "near_surface_depth_mm": top, "height_mm": height, "area_height_cm3": area * height / 1000.}


def extract(case, archives, matrix, pixel_area):
    names = ("mask_pixels", "projected_area_mm2", *FEATURES["depth_assisted"],
             "valid_depth_pixels", "valid_depth_fraction", "near_surface_depth_mm", "height_mm")
    out = {k: case[k] for k in ("tuber", "split", "suffix_px", "acquisition_group", "cultivar")}
    out.update(dict.fromkeys(names))
    out.update(mask_failure=None, height_failure=None)
    rgb, depth = (case["inputs"][kind] for kind in ("rgb", "depth"))
    try:
        if rgb is None:
            raise ValueError(case["metadata_failures"]["rgb"])
        mask = read_mask(archives, rgb)
        out.update(silhouette_features(mask, matrix[0][0], matrix[1][1], pixel_area))
    except ERRORS as err:
        out.update(mask_failure=str(err), height_failure="Silhouette unavailable")
        return out
    try:
        if depth is None:
            raise ValueError(case["metadata_failures"]["depth"])
        out.update(depth_features(archives, depth, mask, out["projected_area_mm2"]))
    except ERRORS as err:
        out["height_failure"] = str(err)
    return out


def extract_split(frozen, split):
    roster = [r for r in frozen["roster"] if r["split"] == split]
    names = {m["archive"] for r in roster for m in r["inputs"].values() if m is not None}
    matrix = frozen["camera_matrix_px"]
    with ExitStack() as stack:
        archives = {name: stack.enter_context(ZipFile(IMAGES / name)) for name in sorted(names)}
        return [extract(r, archives, matrix, frozen["projected_pixel_area_mm2"]) for r in roster]


def read_targets(ids):
    measured = {}
    with prior.TRAITS.open(newline="") as stream:
        for row in csv.DictReader(stream):
            tuber = row["label"]
            if tuber not in ids:
                continue
            if tuber in measured:
                raise ValueError(f"Duplicate exact label {tuber}")
            measured[tuber] = {trait: float(row[column]) if prior.valid_weight(row[column]) else None
                               for trait, (column, _) in TARGETS.items()}
    return {tuber: measured.get(tuber, dict.fromkeys(TARGETS)) for tuber in ids}


def range_summary(rows):
    usable = [r for r in rows if r["height_mm"] is not None]
    return {
        "enrolled": len(rows), "silhouette_usable": sum(r["mask_failure"] is None for r in rows),
        "height_usable": len(usable), "height_failures": {r["tuber"]: r["height_failure"] for r in rows if r["height_failure"]},
        "height_range_mm": [min(r["height_mm"] for r in usable), max(r["height_mm"] for r in usable)] if usable else None,
        "valid_fraction_range": [min(r["valid_depth_fraction"] for r in usable),
                                 max(r["valid_depth_fraction"] for r in usable)] if usable else None,
    }


def design(rows, columns):
    return np.asarray([[1., *(row[name] for name in columns)] for row in rows])


def fit(output):
    frozen = load_manifest(output)
    train = extract_split(frozen, "train")
    summary = range_summary(train)
    if summary["height_usable"] < 5:
        raise ValueError("Insufficient training support for the fixed regressions")
    feature_path = output / "train_features.csv"
    prior.write_csv(feature_path, train)
    truth = read_targets({r["tuber"] for r in train})
    fits = {}
    for trait in TARGETS:
        scorable = [r for r in train if r["area_height_cm3"] is not None and truth[r["tuber"]][trait] is not None]
        y = np.asarray([truth[r["tuber"]][trait] for r in scorable])
        models = {}
        for arm, columns in FEATURES.items():
            coef, _, rank, _ = np.linalg.lstsq(design(scorable, columns), y, rcond=None)
            if rank != len(columns) + 1:
                raise ValueError(f"Rank-deficient training fit for {trait}/{arm}")
            models[arm] = dict(zip(("intercept", *columns), coef.tolist(), strict=True))
        fits[trait] = {"fit_ids": [r["tuber"] for r in scorable],
                       "excluded_ids": sorted(set(truth) - {r["tuber"] for r in scorable}), "coefficients": models}
    prior.save_json(output / "train_fit.json", {
        "manifest_sha256": prior.sha(output / "frame_manifest.json"),
        "training_features_sha256": prior.sha(feature_path), "height_check": summary, "traits": fits,
    })
    print(f"Height usable for {summary['height_usable']}/118 training potatoes; saved the matched train-only fits.", flush=True)


def predict(output):
    frozen = load_manifest(output)
    fit_path = output / "train_fit.json"
    fits = prior.read_json(fit_path)
    if (fits["manifest_sha256"] != prior.sha(output / "frame_manifest.json")
            or fits["training_features_sha256"] != prior.sha(output / "train_features.csv")):
        raise ValueError("Fitted models do not match the frozen inputs")
    rows = extract_split(frozen, "val")
    feature_path = output / "validation_features.csv"
    prior.write_csv(feature_path, rows)
    predictions = []
    for row in rows:
        by_trait = {}
        for trait, fit_row in fits["traits"].items():
            by_trait[trait] = {}
            for arm, columns in FEATURES.items():
                values = [row[name] for name in columns]
                coef = fit_row["coefficients"][arm]
                weights = [coef[name] for name in columns]
                by_trait[trait][arm] = (max(0., coef["intercept"] + float(np.dot(values, weights)))
                                        if all(value is not None for value in values) else None)
        predictions.append({"tuber": row["tuber"], "suffix_px": row["suffix_px"],
                            "mask_failure": row["mask_failure"], "height_failure": row["height_failure"],
                            "height_mm": row["height_mm"], "predictions": by_trait})
    prior.save_json(output / "predictions_before_targets.json", {
        "fit_sha256": prior.sha(fit_path), "validation_features_sha256": prior.sha(feature_path),
        "validation_input_summary": range_summary(rows), "predictions": predictions,
    })
    print("Froze validation features and predictions before joining measured weights or volumes.", flush=True)


def endpoint(rows, trait):
    mask, assisted = (f"{trait}_{arm}_abs_error" for arm in FEATURES)
    stats = {}
    for arm, col in (("mask_only", mask), ("depth_assisted", assisted)):
        values = [r[col] for r in rows if r[col] is not None]
        stats[arm] = {"scored": len(values), "failed": len(rows) - len(values),
                      "mae": float(np.mean(values)) if values else None}
    paired = [r for r in rows if r[mask] is not None and r[assisted] is not None]
    if not paired:
        return {"available": stats, "paired": {"n": 0}}
    center = np.asarray([r[mask] for r in paired])
    depth = np.asarray([r[assisted] for r in paired])
    delta = depth - center
    samples = np.random.default_rng(SEED).integers(len(delta), size=(DRAWS, len(delta)))
    return {
        "available": stats,
        "paired": {"ids": [r["tuber"] for r in paired], "n": len(paired), "mask_only_mae": float(center.mean()),
                   "depth_assisted_mae": float(depth.mean()), "mean_change": float(delta.mean()),
                   "interval_95": np.quantile(delta[samples].mean(axis=1), [.025, .975]).tolist(),
                   "wins": int((delta < -1e-9).sum()), "ties": int((abs(delta) <= 1e-9).sum()),
                   "losses": int((delta > 1e-9).sum())},
    }


def score(output):
    freeze = load_manifest(output)
    if (output / "results.json").exists():
        raise RuntimeError("The frozen validation comparison has already been scored")
    path = output / "predictions_before_targets.json"
    saved = prior.read_json(path)
    if (saved["fit_sha256"] != prior.sha(output / "train_fit.json")
            or saved["validation_features_sha256"] != prior.sha(output / "validation_features.csv")
            or [(r["tuber"], r["suffix_px"]) for r in saved["predictions"]]
            != [(r["tuber"], r["suffix_px"]) for r in freeze["roster"] if r["split"] == "val"]):
        raise ValueError("Frozen validation predictions do not match their archived inputs")
    truth = read_targets({r["tuber"] for r in saved["predictions"]})
    scored = []
    for item in saved["predictions"]:
        tuber = item["tuber"]
        row = {k: item[k] for k in ("tuber", "suffix_px", "mask_failure", "height_failure", "height_mm")}
        for trait in TARGETS:
            measured = truth[tuber][trait]
            row[f"{trait}_measured"] = measured
            for arm in FEATURES:
                pred = item["predictions"][trait][arm]
                row[f"{trait}_{arm}_prediction"] = pred
                row[f"{trait}_{arm}_abs_error"] = abs(pred - measured) if pred is not None and measured is not None else None
            m, d = (row[f"{trait}_{arm}_abs_error"] for arm in FEATURES)
            row[f"{trait}_depth_minus_mask_abs_error"] = d - m if m is not None and d is not None else None
        scored.append(row)
    prior.write_csv(output / "per_potato.csv", scored)
    results = {name: {**endpoint(scored, name), "target": col, "unit": unit} for name, (col, unit) in TARGETS.items()}
    prior.save_json(output / "results.json", {
        "predictions_sha256": prior.sha(path), "per_potato_sha256": prior.sha(output / "per_potato.csv"),
        "training_input_summary": prior.read_json(output / "train_fit.json")["height_check"],
        "validation_input_summary": saved["validation_input_summary"], "traits": results,
    })
    print({trait: {k: v for k, v in data["paired"].items() if k != "ids"}
           for trait, data in results.items()}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "fit", "predict", "score"))
    parser.add_argument("--out", type=Path, default=HERE)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"freeze": freeze, "fit": fit, "predict": predict, "score": score}[args.stage](args.out)
