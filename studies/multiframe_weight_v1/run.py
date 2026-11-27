"""Freeze the development split, fit one CPU weight model, and compare three frame layouts."""

import argparse
import csv
from collections import Counter, defaultdict
from hashlib import file_digest
import io
import json
import math
from pathlib import Path
import re
from zipfile import ZipFile, BadZipFile

import numpy as np
from scipy.spatial import ConvexHull, QhullError
import trimesh

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RELEASE = ROOT / "data/raw/3DPotatoTwin"
SPLIT_FILE = ROOT / "outputs/corepp_cross_model/sources/pointraft_splits.csv"
TRAITS = RELEASE / "3_pair/ground_truth.csv"
WARNINGS = RELEASE / "3_pair/non-perfect.txt"
CAMERA = RELEASE / "1_rgbd/0_camera_intrinsics/realsense_d405_camera_intrinsic.json"
CLOUDS = RELEASE / "1_rgbd/2_pcd.zip"
TARGET = "weight_g_inctack"
BELT_MM = 350.
SEED = 5272401
DRAWS = 10000
TIE_G = 1e-9
RSHAPE = ROOT / "studies/regional_shape_v1"
RESERVATIONS = {
    "reflection_replication": (RSHAPE / "replication_cohort.json", None, "label"),
    "support_offset_confirmation": (RSHAPE / "support_offset_confirmation_cohort.json", None, "label"),
    "pin_sensitivity_confirmation": (RSHAPE / "corepp_pin_confirmation/roster.json", "frames", "tuber"),
    "prior_development": (ROOT / "studies/real_lobes_v1/fresh_selection.json", "pairs", "object_id"),
    "prior_demo": (ROOT / "data/demo_manifest.json", "objects", "object_id"),
}
MEMBER = re.compile(r"2_pcd/(?P<tuber>[^/]+)/(?P=tuber)_pcd_(?P<suffix>[0-9]+)\.ply")
CONDITIONS = ("center", "adjacent", "spaced")


def sha(path):
    with path.open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def save_json(path, data):
    with path.open("x") as handle:
        json.dump(data, handle, indent=2, allow_nan=False)
        handle.write("\n")


def write_csv(path, rows):
    with path.open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def target_rows(allowed):
    by_id = defaultdict(list)
    with TRAITS.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["label"] in allowed:
                by_id[row["label"]].append({
                    "weight": row[TARGET], "cultivar": row["cultivar"], "group": row["ros_bag_name"],
                })
    return by_id


def valid_weight(value):
    try:
        w = float(value)
        return math.isfinite(w) and w > 0
    except (ValueError, TypeError):
        return False


def published_id_exclusions():
    reasons = defaultdict(set)
    for name, (path, section, field) in RESERVATIONS.items():
        rows = read_json(path)
        if section:
            rows = rows[section]
        for row in rows:
            reasons[row[field]].add(name)
    warned = {line.partition("#")[0].strip() for line in WARNINGS.read_text().splitlines()} - {""}
    if "2R306" in warned:
        warned.add("2R3-6")
    for tuber in warned:
        reasons[tuber].add("release_non_perfect")
    return reasons


def sources():
    files = (SPLIT_FILE, TRAITS, WARNINGS, CAMERA, HERE / "protocol.md", Path(__file__),
             *(r[0] for r in RESERVATIONS.values()))
    return {str(path.relative_to(ROOT)): sha(path) for path in files}


def member_index(ids):
    by_id = defaultdict(dict)
    with ZipFile(CLOUDS) as archive:
        for entry in archive.infolist():
            match = MEMBER.fullmatch(entry.filename)
            if match is None or match["tuber"] not in ids:
                continue
            frames = by_id[match["tuber"]]
            suffix = int(match["suffix"])
            if suffix in frames:
                raise ValueError(f"Ambiguous numeric suffix for {entry.filename}")
            frames[suffix] = {"suffix": suffix, "member": entry.filename, "crc32": entry.CRC, "bytes": entry.file_size}
    return by_id


def choose_frames(suffixes, camera_center):
    if len(suffixes) < 3:
        raise ValueError("fewer_than_three_released_clouds")

    def nearest(target):
        return min(suffixes, key=lambda suffix: (abs(suffix-target), suffix))

    center = nearest(camera_center)
    i = suffixes.index(center)
    if i == 0 or i == len(suffixes)-1:
        raise ValueError("center_lacks_two_neighbors")
    lo, hi = suffixes[0], suffixes[-1]
    targets = [lo + (hi-lo)*fraction for fraction in (.25, .75)]
    q1, q3 = map(nearest, targets)
    before, after = suffixes[i-1], suffixes[i+1]
    if not q1 < before < center < after < q3:
        raise ValueError("quartiles_do_not_bracket_outside_adjacent")
    return {"center": [center], "adjacent": [before, center, after], "spaced": [q1, center, q3]}, targets


def freeze(out):
    rows = read_csv(SPLIT_FILE)
    splits = {r["label"]: r["split"] for r in rows}
    if len(splits) != len(rows) or set(splits.values()) != {"train", "val", "test"}:
        raise ValueError("Expected unique train, val and test IDs in public split")
    roster = {k: v for k, v in splits.items() if v in ("train", "val")}
    excluded_ids = published_id_exclusions()
    candidates = set(roster) - excluded_ids.keys()
    targets = target_rows(candidates)
    members = member_index(candidates)
    midpoint = read_json(CAMERA)["height"] / 2
    frames, excluded = [], []
    for tuber in sorted(roster):
        split = roster[tuber]
        reasons = sorted(excluded_ids[tuber])
        if not reasons:
            rows_for_tuber = targets[tuber]
            if len(rows_for_tuber) != 1:
                reasons.append("missing_or_duplicate_weight_join")
            elif not valid_weight(rows_for_tuber[0]["weight"]):
                reasons.append("invalid_weight")
            else:
                suffixes = sorted(members[tuber])
                if not suffixes:
                    reasons.append("no_released_cloud")
                elif split == "val":
                    try:
                        picks, quartiles = choose_frames(suffixes, midpoint)
                    except ValueError as error:
                        reasons.append(str(error))
                if not reasons:
                    frame = {"tuber": tuber, "split": split, "cultivar": rows_for_tuber[0]["cultivar"],
                             "acquisition_group": rows_for_tuber[0]["group"], "available_suffixes": suffixes}
                    selected = suffixes
                    if split == "val":
                        frame.update(frames=picks, quartile_targets_px=quartiles)
                        selected = sorted(set(picks["adjacent"] + picks["spaced"]))
                    frame["members"] = [members[tuber][suffix] for suffix in selected]
                    frames.append(frame)
        if reasons:
            excluded.append({"tuber": tuber, "split": split, "reasons": reasons})
    counts = {split: dict(Counter(reason for row in excluded if row["split"] == split for reason in row["reasons"]))
              for split in ("train", "val")}
    save_json(out / "frame_manifest.json", {
        "stage": "frozen_before_fit_and_weight_errors", "source_sha256": sources(),
        "archive_bytes": CLOUDS.stat().st_size, "camera_midpoint_suffix_px": midpoint, "target": TARGET,
        "split_counts": dict(Counter(splits.values())), "eligible_counts": dict(Counter(r["split"] for r in frames)),
        "exclusion_counts_by_reason": counts, "excluded_train_and_val": excluded, "frames": frames,
    })
    print("Frozen", dict(Counter(r["split"] for r in frames)), "with exclusions", counts, flush=True)


def scan_features(archive, member):
    info = archive.getinfo(member["member"])
    if info.CRC != member["crc32"] or info.file_size != member["bytes"]:
        raise ValueError("Archive member changed since freeze")
    with archive.open(info) as stream:
        cloud = trimesh.load(io.BytesIO(stream.read()), file_type="ply", process=False)
    vertices = np.asarray(cloud.vertices, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 4 or not np.isfinite(vertices).all():
        raise ValueError("Invalid XYZ cloud")
    points = vertices * 1000
    depth = points[:, 2]
    q05, q50 = np.quantile(depth, [0.05, 0.5])
    if depth.min() <= 0 or not 150 <= q50 <= 600:
        raise ValueError("Cloud outside expected metric camera-depth range")
    area = ConvexHull(points[:, :2]).volume
    if not np.isfinite(area) or area <= 0:
        raise ValueError("Invalid camera-XY area")
    height = max(0., BELT_MM-q05)
    return {"point_count": len(points), "area_mm2": float(area), "q05_camera_depth_mm": float(q05),
            "median_camera_depth_mm": float(q50), "height_mm": height, "bulk_proxy_cm3": float(area*height/1000)}


def tabulate_features(archive, rows):
    usable, failures = {}, []
    for row in rows:
        tuber = row["tuber"]
        usable[tuber] = {}
        for member in row["members"]:
            suffix = member["suffix"]
            try:
                usable[tuber][suffix] = scan_features(archive, member)
            except (ValueError, OSError, KeyError, AttributeError, QhullError, BadZipFile) as error:
                failures.append({"tuber": tuber, "split": row["split"], "suffix": suffix,
                                 "detail": f"{type(error).__name__}: {error}"})
    return usable, failures


def compare(per_tuber, baseline, errors, draw_indices):
    delta = errors[per_tuber]-errors[baseline]
    low, high = np.quantile(delta[draw_indices].mean(axis=1), [0.025, 0.975])
    return {"mean_change_g": float(delta.mean()), "median_change_g": float(np.median(delta)),
            "bootstrap_95_g": [float(low), float(high)], "wins": int((delta < -TIE_G).sum()),
            "ties": int((np.abs(delta) <= TIE_G).sum()), "losses": int((delta > TIE_G).sum())}


def spacing(rows, name):
    n = np.array([r["frames"][name] for r in rows])
    return {label: {"median": float(np.median(x)), "min": int(x.min()), "max": int(x.max())}
            for label, x in (("lower_to_center_px", n[:, 1]-n[:, 0]),
                             ("center_to_upper_px", n[:, 2]-n[:, 1]), ("outer_span_px", n[:, 2]-n[:, 0]))}


def score(out):
    if (out / "results.json").exists():
        raise FileExistsError("An evaluation is already saved here")
    manifest_path = out / "frame_manifest.json"
    manifest = read_json(manifest_path)
    if (manifest["stage"] != "frozen_before_fit_and_weight_errors" or manifest["source_sha256"] != sources()
            or manifest["archive_bytes"] != CLOUDS.stat().st_size):
        raise ValueError("Frozen input or protocol changed")
    train = [r for r in manifest["frames"] if r["split"] == "train"]
    val = [r for r in manifest["frames"] if r["split"] == "val"]
    if not train or not val:
        raise ValueError("The fixed comparison needs both train and validation data")
    with ZipFile(CLOUDS) as archive:
        train_features, train_failed = tabulate_features(archive, train)
        targets = target_rows(train_features.keys())
        x, y, weights = [], [], []
        for tuber, frames in train_features.items():
            weight = float(targets[tuber][0]["weight"])
            for feature in frames.values():
                x.append([1., feature["bulk_proxy_cm3"]])
                y.append(weight)
                weights.append(1/len(frames))
        scale = np.sqrt(weights)
        coefficients, _, rank, _ = np.linalg.lstsq(np.asarray(x) * scale[:, None], np.asarray(y)*scale, rcond=None)
        if rank != 2:
            raise ValueError("Train-only intercept and slope could not be identified")
        fitted = {"model": "tuber-balanced weighted least squares on XY hull area times robust height",
                  "intercept_g": float(coefficients[0]), "slope_g_per_cm3": float(coefficients[1]),
                  "nominal_belt_depth_mm": BELT_MM, "training_tubers": sum(bool(v) for v in train_features.values()),
                  "training_frames": len(x), "failed_training_frames": train_failed,
                  "frame_manifest_sha256": sha(manifest_path)}
        save_json(out / "train_fit.json", fitted)
        print("Train-only estimator fitted", fitted["training_tubers"], fitted["training_frames"], flush=True)
        val_features, val_failed = tabulate_features(archive, val)

    # Save the inference-only frame estimates before reading validation labels.
    frame_predictions, prediction_rows = [], {}
    for row in val:
        tuber = row["tuber"]
        estimates = {}
        for suffix, feature in val_features[tuber].items():
            estimate = max(0., coefficients[0]+coefficients[1]*feature["bulk_proxy_cm3"])
            estimates[suffix] = float(estimate)
            frame_predictions.append({"tuber": tuber, "suffix_px": suffix, **feature, "predicted_g": float(estimate)})
        prediction_rows[tuber] = estimates
    write_csv(out / "per_frame_predictions.csv", frame_predictions)

    weights = target_rows(prediction_rows.keys())
    individual, completed = [], []
    for row in val:
        tuber = row["tuber"]
        estimates = prediction_rows[tuber]
        measured = float(weights[tuber][0]["weight"])
        record = {"tuber": tuber, "cultivar": row["cultivar"], "acquisition_group": row["acquisition_group"],
                  "measured_g": measured, "status": "complete" if len(estimates) == len(row["members"]) else "failed"}
        for name in CONDITIONS:
            ids = row["frames"][name]
            record[f"{name}_suffixes_px"] = "/".join(map(str, ids))
            record[f"{name}_frame_predictions_g"] = "/".join(str(estimates.get(i, "")) for i in ids)
            available = [estimates[i] for i in ids if i in estimates]
            prediction = float(np.mean(available)) if len(available) == len(ids) else None
            record[f"{name}_prediction_g"] = prediction
            record[f"{name}_abs_error_g"] = abs(prediction-measured) if prediction is not None else None
        record["spaced_minus_adjacent_error_g"] = (
            record["spaced_abs_error_g"] - record["adjacent_abs_error_g"] if record["status"] == "complete" else None)
        if record["status"] == "complete":
            completed.append(record)
        individual.append(record)
    write_csv(out / "per_potato_predictions.csv", individual)
    if not completed:
        raise ValueError("No complete comparable validation potatoes")
    errors = {name: np.array([r[f"{name}_abs_error_g"] for r in completed]) for name in CONDITIONS}
    rng = np.random.default_rng(SEED)
    draw_indices = rng.integers(0, len(completed), (DRAWS, len(completed)))
    endpoints = {f"{name}_minus_{base}": compare(name, base, errors, draw_indices)
                 for name, base in (("spaced", "adjacent"), ("spaced", "center"), ("adjacent", "center"))}
    primary = sorted(completed, key=lambda row: (row["spaced_minus_adjacent_error_g"], row["tuber"]))
    result = {
        "training": fitted, "validation_frozen": len(val), "validation_scored": len(completed),
        "validation_failures": val_failed,
        "validation_by_cultivar": dict(Counter(r["cultivar"] for r in completed)),
        "validation_acquisition_groups": len(set(r["acquisition_group"] for r in completed)),
        "mae_g": {k: float(v.mean()) for k, v in errors.items()}, "paired_comparisons": endpoints,
        "spacing": {name: spacing(val, name) for name in ("adjacent", "spaced")},
        "center_deviation_from_360_px": {
            "median": float(np.median([abs(r["frames"]["center"][0]-360) for r in val])),
            "max": max(abs(r["frames"]["center"][0]-360) for r in val),
        },
        "extremes": {"largest_improvement": primary[0], "largest_worsening": primary[-1]},
        "bootstrap_seed": SEED, "bootstrap_draws": DRAWS,
        "per_potato_sha256": sha(out / "per_potato_predictions.csv"),
        "per_frame_sha256": sha(out / "per_frame_predictions.csv"),
        "train_fit_sha256": sha(out / "train_fit.json"),
    }
    save_json(out / "results.json", result)
    print(result["mae_g"], endpoints, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "score"))
    parser.add_argument("--out", type=Path, default=HERE)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"freeze": freeze, "score": score}[args.phase](args.out)


if __name__ == "__main__":
    main()
