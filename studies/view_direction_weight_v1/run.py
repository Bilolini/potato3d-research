"""Freeze, fit and score the development-only centroid-ray comparison."""

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import io
from pathlib import Path
import re
import sys
from zipfile import ZipFile

import numpy as np
from PIL import Image

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from potato3d.calibration import intrinsics_from_json
from studies.multiframe_weight_v1 import run as baseline

ARCHIVED = baseline.HERE
HELD_OUT = STUDY.parent / "sam2_human_prompt_confirmation_v1" / "cohort_freeze.json"
IMAGES = baseline.RELEASE / "1_rgbd/1_images"
RGB_MEMBER = re.compile(r"(?P<tuber>[^/]+)/(?P=tuber)_rgb_(?P<suffix>\d+)\.png")
POSITIONS = ("lower", "center", "upper")
A_NAMES = ("intercept", "proxy_cm3")
B_NAMES = (*A_NAMES, "rx", "ry", "proxy_rx", "proxy_ry")
COEFFICIENT_TOLERANCE = 1e-9
PREDICTION_TOLERANCE_G = 1e-8


def source_hashes():
    files = (
        STUDY / "protocol.md", Path(__file__), ARCHIVED / "run.py",
        ARCHIVED / "frame_manifest.json", ARCHIVED / "train_fit.json",
        ARCHIVED / "per_frame_predictions.csv", ARCHIVED / "protocol.md",
        baseline.TRAITS, baseline.CAMERA, baseline.SPLIT_FILE, baseline.WARNINGS, HELD_OUT,
        ROOT / "src/potato3d/calibration.py",
        *(item[0] for item in baseline.RESERVATIONS.values()),
    )
    return {str(p.relative_to(ROOT)): baseline.sha(p) for p in files}


def rgb_members(required):
    matches = {}
    for path in sorted(IMAGES.glob("*.zip")):
        with ZipFile(path) as archive:
            for info in archive.infolist():
                hit = RGB_MEMBER.fullmatch(info.filename)
                if not hit:
                    continue
                key = hit["tuber"], int(hit["suffix"])
                if key not in required:
                    continue
                if key in matches:
                    raise ValueError(f"Ambiguous RGB frame {key}")
                matches[key] = {
                    "archive": path.name, "member": info.filename,
                    "crc32": info.CRC, "bytes": info.file_size,
                }
    missing = required - matches.keys()
    if missing:
        raise ValueError(f"Missing full-resolution RGB(A) members: {sorted(missing)}")
    return matches


def linked_frames(archived):
    seen = set()
    roster = []
    for row in archived["frames"]:
        tuber = row["tuber"]
        split = row["split"]
        members = {m["suffix"]: m for m in row["members"]}
        if tuber in seen or len(members) != len(row["members"]):
            raise ValueError(f"Duplicate archived tuber or frame: {tuber}")
        seen.add(tuber)
        if split == "train":
            if list(members) != row["available_suffixes"]:
                raise ValueError(f"Expected every training frame in archived order: {tuber}")
            positions = zip(members, ["training"] * len(members), strict=True)
        elif split == "val":
            spaced = row["frames"]["spaced"]
            if len(spaced) != 3 or not spaced[0] < spaced[1] < spaced[2] or spaced[1] != row["frames"]["center"][0]:
                raise ValueError(f"Invalid archived spaced frames: {tuber}")
            positions = zip(spaced, POSITIONS, strict=True)
        else:
            raise ValueError("Archived roster must contain train and validation potatoes only")
        roster.append({
            "tuber": tuber, "split": split, "cultivar": row["cultivar"],
            "acquisition_group": row["acquisition_group"],
            "frames": [{"suffix_px": suffix, "position": position, "ply": members[suffix]}
                       for suffix, position in positions],
        })
    return roster


def freeze(output):
    archived_path = ARCHIVED / "frame_manifest.json"
    archive_fit = baseline.read_json(ARCHIVED / "train_fit.json")
    if archive_fit["frame_manifest_sha256"] != baseline.sha(archived_path):
        raise ValueError("Archived coefficient and frame manifests do not agree")
    archived = baseline.read_json(archived_path)
    if archived["archive_bytes"] != baseline.CLOUDS.stat().st_size:
        raise ValueError("Released PLY archive size changed")
    if archived["source_sha256"][str(baseline.TRAITS.relative_to(ROOT))] != baseline.sha(baseline.TRAITS):
        raise ValueError("Measured weights differ from the archived study source")
    roster = linked_frames(archived)
    ids = {r["tuber"] for r in roster}
    held_out = {r["tuber"] for r in baseline.read_json(HELD_OUT)["roster"]}
    reserved = set(baseline.published_id_exclusions())
    if len(held_out) != 45 or ids & (held_out | reserved):
        raise ValueError("Unexpected SAM 2 confirmation size or reserve overlap")
    counts = Counter(r["split"] for r in roster)
    frames = Counter()
    for row in roster:
        frames[row["split"]] += len(row["frames"])
    if counts != {"train": 118, "val": 40} or frames != {"train": 3368, "val": 120}:
        raise ValueError(f"Unexpected cohort or frame count: {counts}, {frames}")
    rgb = rgb_members({(row["tuber"], f["suffix_px"]) for row in roster for f in row["frames"]})
    for row in roster:
        for f in row["frames"]:
            f["rgb"] = rgb[row["tuber"], f["suffix_px"]]
    manifest = {
        "stage": "frozen_before_training_and_validation_errors", "source_sha256": source_hashes(),
        "ply_archive_bytes": archived["archive_bytes"], "potatoes": dict(counts), "frames": dict(frames),
        "sam2_confirmation_excluded_count": len(held_out), "reserved_overlap_count": 0, "roster": roster,
    }
    baseline.save_json(output / "frame_manifest.json", manifest)
    print(f"Frozen {counts['train']} train and {counts['val']} validation potatoes, {sum(frames.values())} frames.")


def read_freeze(output):
    manifest = baseline.read_json(output / "frame_manifest.json")
    if manifest["source_sha256"] != source_hashes() or manifest["ply_archive_bytes"] != baseline.CLOUDS.stat().st_size:
        raise ValueError("Frozen protocol, code or source changed")
    return manifest


def ray(u, v, matrix):
    return (u - matrix[0, 2]) / matrix[0, 0], (v - matrix[1, 2]) / matrix[1, 1]


def camera():
    data = baseline.read_json(baseline.CAMERA)
    size = data["width"], data["height"]
    if size != (1280, 720):
        raise ValueError("Released image dimensions differ from the frozen specification")
    m = intrinsics_from_json(data)
    expected = np.array([[m[0, 0], 0., m[0, 2]], [0., m[1, 1], m[1, 2]], [0., 0., 1.]])
    if not np.array_equal(m, expected):
        raise ValueError("Expected the published zero-skew pinhole model")
    cx, cy = m[0, 2], m[1, 2]
    fx, fy = m[0, 0], m[1, 1]
    landmarks = ((cx, cy), (cx + fx/4, cy), (cx, cy + fy/4), (cx - fx/4, cy - fy/4))
    answers = ((0., 0.), (.25, 0.), (0., .25), (-.25, -.25))
    if not np.allclose([ray(u, v, m) for u, v in landmarks], answers, rtol=0, atol=1e-12):
        raise ValueError("Camera ray landmark sign or scale check failed")
    return size, m


def mask_features(archive, member, size, camera_matrix):
    info = archive.getinfo(member["member"])
    if info.CRC != member["crc32"] or info.file_size != member["bytes"]:
        raise ValueError(f"RGB(A) member changed: {member['member']}")
    with Image.open(io.BytesIO(archive.read(info))) as image:
        if image.mode != "RGBA" or image.size != size:
            raise ValueError(f"Expected original full-resolution RGBA: {member['member']}")
        y, x = np.nonzero(np.asarray(image.getchannel("A")))
    if not len(x):
        raise ValueError(f"Empty provided alpha mask: {member['member']}")
    u, v = float(x.mean()), float(y.mean())
    rx, ry = ray(u, v, camera_matrix)
    projected = camera_matrix @ [rx, ry, 1.]
    if not np.allclose(projected, [u, v, 1.], rtol=0., atol=1e-10):
        raise ValueError("Centroid ray did not project back to its original pixel")
    return {"mask_pixels": len(x), "centroid_u_px": u, "centroid_v_px": v, "rx": rx, "ry": ry}


def extract(roster):
    rows = []
    size, matrix = camera()
    with ExitStack() as stack:
        ply = stack.enter_context(ZipFile(baseline.CLOUDS))
        needed = {f["rgb"]["archive"] for r in roster for f in r["frames"]}
        images = {name: stack.enter_context(ZipFile(IMAGES / name)) for name in sorted(needed)}
        for index, item in enumerate(roster, 1):
            for frame in item["frames"]:
                member = frame["rgb"]
                geometry = baseline.scan_features(ply, frame["ply"])
                mask = mask_features(images[member["archive"]], member, size, matrix)
                rows.append({"tuber": item["tuber"], "position": frame["position"],
                             "suffix_px": frame["suffix_px"], **geometry, **mask})
            if index % 25 == 0 or index == len(roster):
                print(f"Extracted {index}/{len(roster)} {item['split']} potatoes", flush=True)
    return rows


def design(rows, directed):
    proxy = np.asarray([r["bulk_proxy_cm3"] for r in rows])
    features = [np.ones(len(proxy)), proxy]
    if directed:
        rx = np.asarray([r["rx"] for r in rows])
        ry = np.asarray([r["ry"] for r in rows])
        features.extend([rx, ry, proxy * rx, proxy * ry])
    return np.column_stack(features)


def targets(ids):
    ids = set(ids)
    records = baseline.target_rows(ids)
    if set(records) != ids:
        raise ValueError("Some frozen measurement IDs are missing")
    weights = {}
    for tuber, rows in records.items():
        if len(rows) != 1 or not baseline.valid_weight(rows[0]["weight"]):
            raise ValueError(f"Missing, duplicate or invalid measured weight for {tuber}")
        weights[tuber] = float(rows[0]["weight"])
    return weights


def range_stats(values):
    return {"min": float(np.min(values)), "median": float(np.median(values)), "max": float(np.max(values))}


def ray_ranges(rows):
    return {key: range_stats([r[key] for r in rows]) for key in ("rx", "ry")}


def fit(output):
    manifest = read_freeze(output)
    train = [r for r in manifest["roster"] if r["split"] == "train"]
    features = extract(train)
    counts = Counter(r["tuber"] for r in features)
    train_targets = targets(counts.keys())
    y = np.asarray([train_targets[row["tuber"]] for row in features])
    scale = np.sqrt([1. / counts[row["tuber"]] for row in features])
    fits = {}
    for name, names in (("A", A_NAMES), ("B", B_NAMES)):
        weighted = design(features, directed=name == "B") * scale[:, None]
        coefs, _, rank, _ = np.linalg.lstsq(weighted, y * scale, rcond=None)
        if rank != len(names) or not np.isfinite(coefs).all():
            raise ValueError(f"Model {name} training design is rank deficient or nonfinite")
        fits[name] = {"coefficients": dict(zip(names, coefs.tolist(), strict=True)), "rank": int(rank)}
    archived = baseline.read_json(ARCHIVED / "train_fit.json")
    delta = {key: abs(fits["A"]["coefficients"][key] - archived[old]) for key, old in
             (("intercept", "intercept_g"), ("proxy_cm3", "slope_g_per_cm3"))}
    if max(delta.values()) > COEFFICIENT_TOLERANCE:
        raise ValueError(f"Model A didn't reproduce archived coefficients: {delta}")
    if len(counts) != archived["training_tubers"] or len(features) != archived["training_frames"]:
        raise ValueError("Training frame count differs from archived Model A")
    baseline.save_json(output / "train_fit.json", {
        "frame_manifest_sha256": baseline.sha(output / "frame_manifest.json"),
        "training_potatoes": len(counts), "training_frames": len(features),
        "frames_per_potato": range_stats(list(counts.values())),
        "weight_per_frame": "1 / number of archived frames for this tuber",
        "training_ray_ranges": ray_ranges(features), "models": fits,
        "model_a_archived_coefficient_abs_delta": delta,
    })
    print("Saved both train-only fits and verified Model A coefficients.", flush=True)


def score(output):
    manifest = read_freeze(output)
    if (output / "results.json").exists():
        raise FileExistsError("The frozen comparison has already been scored")
    fitted_path = output / "train_fit.json"
    fitted = baseline.read_json(fitted_path)
    if fitted["frame_manifest_sha256"] != baseline.sha(output / "frame_manifest.json"):
        raise ValueError("Train fits do not match the frozen frame manifest")
    roster = [r for r in manifest["roster"] if r["split"] == "val"]
    rows = extract(roster)
    for model, names in (("A", A_NAMES), ("B", B_NAMES)):
        values = fitted["models"][model]["coefficients"]
        coef = np.array([values[name] for name in names])
        estimates = np.maximum(0., design(rows, directed=model == "B") @ coef)
        for row, estimate in zip(rows, estimates, strict=True):
            row[f"{model}_predicted_g"] = float(estimate)
    archived = {
        (r["tuber"], int(r["suffix_px"])): float(r["predicted_g"])
        for r in baseline.read_csv(ARCHIVED / "per_frame_predictions.csv")
    }
    archived_delta = max(abs(r["A_predicted_g"] - archived[r["tuber"], r["suffix_px"]]) for r in rows)
    if archived_delta > PREDICTION_TOLERANCE_G:
        raise ValueError(f"Model A didn't reproduce every archived validation prediction: {archived_delta} g")

    weights = targets(r["tuber"] for r in roster)
    by_tuber = defaultdict(list)
    for row in rows:
        measured = weights[row["tuber"]]
        row["measured_g"] = measured
        for model in ("A", "B"):
            error = row[f"{model}_predicted_g"] - measured
            row[f"{model}_signed_error_g"] = error
            row[f"{model}_abs_error_g"] = abs(error)
        row["B_minus_A_abs_error_g"] = row["B_abs_error_g"] - row["A_abs_error_g"]
        by_tuber[row["tuber"]].append(row)

    potatoes = []
    for tuber, frames in by_tuber.items():
        if [r["position"] for r in frames] != list(POSITIONS):
            raise ValueError(f"Missing or unordered validation frames for {tuber}")
        item = {
            "tuber": tuber, "measured_g": weights[tuber],
            **{f"{r['position']}_suffix_px": r["suffix_px"] for r in frames},
            **{f"{key}_span": float(np.ptp([r[key] for r in frames])) for key in ("rx", "ry")},
        }
        for model in ("A", "B"):
            item[f"{model}_mean_frame_abs_error_g"] = float(np.mean([f[f"{model}_abs_error_g"] for f in frames]))
            avg = float(np.mean([f[f"{model}_predicted_g"] for f in frames]))
            item[f"{model}_mean_prediction_g"] = avg
            item[f"{model}_aggregate_abs_error_g"] = abs(avg - weights[tuber])
        for endpoint in ("mean_frame_abs_error", "aggregate_abs_error"):
            item[f"B_minus_A_{endpoint}_g"] = item[f"B_{endpoint}_g"] - item[f"A_{endpoint}_g"]
        potatoes.append(item)

    draws = np.random.default_rng(baseline.SEED).integers(len(potatoes), size=(baseline.DRAWS, len(potatoes)))
    summary = {
        "validation_potatoes": len(potatoes), "scored_validation_frames": len(rows),
        "model_a_archived_prediction_max_abs_delta_g": archived_delta,
        "validation_ray_ranges": ray_ranges(rows),
        "validation_ray_ranges_by_position": {
            p: ray_ranges([row for row in rows if row["position"] == p]) for p in POSITIONS
        },
        "within_potato_ray_spans": {key: range_stats([r[f"{key}_span"] for r in potatoes])
                                    for key in ("rx", "ry")},
        "ry_strictly_decreasing_count": int(sum(
            group[0]["ry"] > group[1]["ry"] > group[2]["ry"] for group in by_tuber.values()
        )),
        "position_specific": {p: position_summary([row for row in rows if row["position"] == p]) for p in POSITIONS},
        "bootstrap_seed": baseline.SEED, "bootstrap_draws": baseline.DRAWS,
        "train_fit_sha256": baseline.sha(fitted_path),
    }
    for label, key in (("primary", "mean_frame_abs_error"), ("averaged_predictions", "aggregate_abs_error")):
        errors = {m: np.asarray([r[f"{m}_{key}_g"] for r in potatoes]) for m in ("A", "B")}
        summary[label] = {"mae_g": {m: float(v.mean()) for m, v in errors.items()},
                          "B_minus_A": baseline.compare("B", "A", errors, draws)}
    ordered = sorted(potatoes, key=lambda r: (r["B_minus_A_mean_frame_abs_error_g"], r["tuber"]))
    worst = min(potatoes, key=lambda r: (-r["B_minus_A_mean_frame_abs_error_g"], r["tuber"]))
    summary["primary_extremes"] = {
        key: {"potato": item, "frames": by_tuber[item["tuber"]]}
        for key, item in (("largest_gain", ordered[0]), ("largest_loss", worst))
    }
    baseline.write_csv(output / "per_frame.csv", rows)
    baseline.write_csv(output / "per_potato.csv", potatoes)
    baseline.save_json(output / "results.json", summary)
    print("Primary:", summary["primary"], flush=True)
    print("After averaging predictions:", summary["averaged_predictions"], flush=True)


def position_summary(rows):
    return {
        m: {"mae_g": float(np.mean([r[f"{m}_abs_error_g"] for r in rows])),
            "bias_g": float(np.mean([r[f"{m}_signed_error_g"] for r in rows]))}
        for m in ("A", "B")
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "fit", "score"))
    parser.add_argument("--out", type=Path, default=STUDY)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"freeze": freeze, "fit": fit, "score": score}[args.stage](args.out)
