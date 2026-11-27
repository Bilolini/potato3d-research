"""Freeze eligibility from metadata, then prepare anonymous entry stimuli."""

from collections import Counter, defaultdict
from contextlib import ExitStack
from pathlib import Path
import argparse
import csv
import re
import sys
from zipfile import ZipFile

import numpy as np

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
sys.path.insert(0, str(ROOT))
from studies.sam2_center_weight_v1 import run as base
from studies.sam2_human_prompt_v1 import collector
from studies.sam2_human_prompt_v1.prepare import cue_for

REPEAT = collector.STUDY / "repeat_01"
ANNOTATIONS = base.DATA / "1_rgbd/pin_regions.json"
TRAITS = base.DATA / "3_pair/ground_truth.csv"
MEASURED_WEIGHT = "weight_g_inctack"
FIT = base.PREVIOUS / "train_fit.json"
CONFIG = base.STUDY / "tracking_config.json"
SEED = "sam2-human-confirmation-v1/133"
OBJECT = re.compile(r"(?:[1-5])?R\d+-\d+(?: / \d+)?")
RGB = re.compile(r"(?P<tuber>[^/]+)/(?P=tuber)_rgb_(?P<suffix>\d+)\.png")
ADDITIONAL_ROSTERS = (
    "studies/multiframe_weight_v1/frame_manifest.json",
    "studies/multiframe_weight_correction_v1/frame_manifest.json",
    "studies/sam2_center_weight_v1/frame_manifest.json",
    "studies/sam2_pin_prompt_v1/frozen_clicks.json",
    "studies/sam2_human_prompt_v1/trial_manifest.json",
    "studies/sam2_human_prompt_v1/repeat_01/trial_manifest.json",
    "studies/regional_shape_v1/corepp_pin_pilot/frozen_inputs.json",
    "studies/regional_shape_v1/corepp_pin_multituber/frozen_inputs.json",
    "studies/regional_shape_v1/corepp_pin_swap_replication/frozen_inputs.json",
    "studies/regional_shape_v1/corepp_pin_accuracy/frozen_protocol.json",
    "studies/regional_shape_v1/corepp_cross_model/replay.json",
    "studies/regional_shape_v1/triposr_pin_pilot/frozen_inputs.json",
)


def embedded_ids(value):
    if isinstance(value, str):
        if OBJECT.fullmatch(value):
            yield value.split(" / ")[0]
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from embedded_ids(key)
            yield from embedded_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from embedded_ids(item)


def seal_json(path, data):
    if path.exists():
        if base.read_json(path) != data:
            raise ValueError(f"Existing frozen data differs at {path.name}")
        return
    base.write_json(path, data)


def source_hashes(weight):
    paths = [
        STUDY / "protocol.md", STUDY / "prepare.py", STUDY / "score.py",
        weight.SPLIT_FILE, weight.TRAITS, weight.WARNINGS, base.INTRINSICS, ANNOTATIONS,
        FIT, CONFIG, REPEAT / "trial_manifest.json", REPEAT / "protocol.md",
        *(item[0] for item in weight.RESERVATIONS.values()),
        *(ROOT / item for item in ADDITIONAL_ROSTERS),
        ROOT / "studies/multiframe_weight_v1/run.py",
        base.STUDY / "run.py",
        ROOT / "src/potato3d/calibration.py",
        ROOT / "studies/sam2_pin_prompt_v1/run.py",
        collector.STUDY / "prepare.py", collector.STUDY / "score.py",
        collector.STUDY / "collector.py", collector.STUDY / "collector.html",
    ]
    return {str(p.relative_to(ROOT)): base.hash_file(p) for p in dict.fromkeys(paths)}


def pin_index():
    annotations = base.read_json(ANNOTATIONS)
    category = next(c["id"] for c in annotations["categories"] if c["name"] == "pin")
    images = defaultdict(list)
    polygons = defaultdict(list)
    for row in annotations["images"]:
        images[row["file_name"]].append(row)
    for row in annotations["annotations"]:
        segments = row["segmentation"]
        if row["category_id"] == category and isinstance(segments, list):
            polygons[row["image_id"]].extend(
                segment for segment in segments if len(segment) >= 6 and len(segment) % 2 == 0
            )
    return images, polygons


def image_index(ids):
    rgb = defaultdict(lambda: defaultdict(list))
    directories = {}
    for path in sorted(collector.ARCHIVES.glob("*.zip")):
        with ZipFile(path) as archive:
            names = defaultdict(list)
            for info in archive.infolist():
                name = info.filename
                if name.partition("/")[0] not in ids:
                    continue
                names[name].append(info)
                hit = RGB.fullmatch(name)
                if hit:
                    rgb[hit["tuber"]][int(hit["suffix"])].append((path.name, info))
        directories[path.name] = names
    return rgb, directories


def traits_metadata(ids):
    metadata = defaultdict(list)
    with TRAITS.open(newline="") as f:
        reader = csv.DictReader(f)
        required = {"label", "cultivar", "ros_bag_name", "x3_depth_mm", MEASURED_WEIGHT}
        if not required <= set(reader.fieldnames or ()):
            raise ValueError("The released measurement table schema changed")
        for row in reader:
            if row["label"] in ids:
                metadata[row["label"]].append({
                    "cultivar": row["cultivar"], "acquisition_group": row["ros_bag_name"],
                })
    return metadata


def frame_audit(tuber, rgb, directories, clouds, images, polygons, midpoint, size):
    reasons, missing_labels = [], []
    if not clouds:
        return None, ["missing_released_ply_index"], missing_labels
    center = min(clouds, key=lambda s: (abs(s - midpoint), s))
    suffixes = sorted(s for s in rgb if s <= center)
    row = {"tuber": tuber, "center_suffix_px": center, "center_ply_metadata": clouds[center]}
    if center not in rgb or len(suffixes) < 2:
        return row, ["missing_complete_entry_to_center_rgb_sequence"], missing_labels
    if any(len(rgb[s]) != 1 for s in suffixes):
        return row, ["ambiguous_rgb_member_or_numeric_suffix"], missing_labels
    files = [rgb[s][0] for s in suffixes]
    archive = files[-1][0]
    if any(name != archive for name, _ in files):
        return row, ["entry_to_center_spans_multiple_archives"], missing_labels
    depth_name = files[-1][1].filename.replace("_rgb_", "_depth_")
    depths = directories[archive][depth_name]
    if len(depths) != 1 or not depths[0].file_size:
        reasons.append("missing_or_ambiguous_center_depth_member")
    frames = []
    for suffix, (_, info) in zip(suffixes, files, strict=True):
        records = images[info.filename]
        if len(records) != 1 or not polygons[records[0]["id"]]:
            missing_labels.append(info.filename)
        elif (records[0]["width"], records[0]["height"]) != size:
            reasons.append("pin_annotation_image_size_mismatch")
        if not info.file_size:
            reasons.append("empty_rgb_member")
        frames.append({
            "suffix_px": suffix, "rgb_member": info.filename,
            "crc32": f"{info.CRC:08x}", "bytes": info.file_size,
        })
    if missing_labels:
        reasons.append("missing_or_ambiguous_pin_annotation")
    row.update({
        "archive": archive, "width": size[0], "height": size[1],
        "entry_suffix_px": suffixes[0], "frames": frames,
        "center_depth_member": depth_name,
        "center_depth_crc32": f"{depths[0].CRC:08x}" if len(depths) == 1 else None,
        "center_depth_bytes": depths[0].file_size if len(depths) == 1 else None,
    })
    return row, sorted(set(reasons)), missing_labels


def freeze_cohort():
    from studies.multiframe_weight_v1 import run as weight

    split = weight.read_csv(weight.SPLIT_FILE)
    if len(split) != len({r["label"] for r in split}):
        raise ValueError("Duplicate PointRAFT split labels")
    test = {r["label"] for r in split if r["split"] == "test"}
    published_exclusions = weight.published_id_exclusions()
    candidates = test - published_exclusions.keys()
    if len(candidates) != 46:
        raise ValueError(f"Expected 46 candidates, found {len(candidates)}")
    overlap = defaultdict(list)
    for path in ADDITIONAL_ROSTERS:
        for tuber in candidates & set(embedded_ids(base.read_json(ROOT / path))):
            overlap[tuber].append(path)
    rgb, directories = image_index(candidates)
    clouds = weight.member_index(candidates)
    images, polygons = pin_index()
    metadata = traits_metadata(candidates)
    info = base.read_json(base.INTRINSICS)
    size = info["width"], info["height"]

    audits, roster = [], []
    for tuber in sorted(test):
        reasons = sorted(published_exclusions[tuber])
        audit = {"tuber": tuber, "candidate_after_existing_exclusions": tuber in candidates,
                 "existing_exclusions": reasons, "prior_overlap_sources": [],
                 "measurement_rows": None, "entry_suffix_px": None, "center_suffix_px": None,
                 "rgb_frames_to_center": None, "missing_pin_records": [], "additional_exclusions": [],
                 "eligible": False}
        audits.append(audit)
        if tuber not in candidates:
            continue
        frame, issues, missing = frame_audit(
            tuber, rgb[tuber], directories, clouds[tuber], images, polygons, size[1] / 2, size
        )
        count = len(metadata[tuber])
        if overlap[tuber]:
            issues.append("previously_used_object")
        if count != 1:
            issues.append("missing_or_ambiguous_measurement_row")
        audit.update({
            "prior_overlap_sources": sorted(overlap[tuber]), "measurement_rows": count,
            "entry_suffix_px": frame.get("entry_suffix_px") if frame else None,
            "center_suffix_px": frame.get("center_suffix_px") if frame else None,
            "rgb_frames_to_center": len(frame.get("frames", [])) if frame else 0,
            "missing_pin_records": missing, "additional_exclusions": sorted(issues), "eligible": not issues,
        })
        if not issues:
            roster.append({**frame, **metadata[tuber][0]})
    if not roster:
        raise ValueError("No eligible confirmation potatoes")
    roster.sort(key=lambda r: collector.digest(f"{SEED}/{r['tuber']}".encode()))
    coefficients = base.read_json(FIT)["models"]["A"]
    if (coefficients["intercept_g"], coefficients["center_proxy_cm3_coefficient_g_per_cm3"]) != base.MODEL_A:
        raise ValueError("Archived Model A differs from the shared estimator")
    if base.hash_file(base.CHECKPOINT) != base.CHECKPOINT_HASH:
        raise ValueError("Archived checkpoint hash differs")
    hashes = source_hashes(weight)
    frozen = {
        "stage": "frozen_from_metadata_before_stimulus_preparation",
        "protocol_sha256": hashes[str((STUDY / "protocol.md").relative_to(ROOT))],
        "source_sha256": hashes, "order_seed": SEED,
        "tracker_checkpoint_sha256": base.CHECKPOINT_HASH, "model_a": coefficients,
        "test_ids": len(test), "candidates_after_existing_exclusions": len(candidates),
        "existing_excluded": len(test - candidates), "eligible": len(roster),
        "cohort_by_cultivar": dict(Counter(r["cultivar"] for r in roster)),
        "cohort_by_group": dict(Counter(r["acquisition_group"] for r in roster)),
        "audit": audits, "roster": roster,
    }
    seal_json(STUDY / "cohort_freeze.json", frozen)
    base.write_csv(STUDY / "eligibility_audit.csv", [
        {key: " | ".join(value) if isinstance(value, list) else value for key, value in r.items()}
        for r in audits
    ])
    print(f"Frozen {len(roster)} of {len(candidates)} candidates")
    for row in audits:
        if row["candidate_after_existing_exclusions"] and not row["eligible"]:
            print(row["tuber"], row["additional_exclusions"], row["missing_pin_records"])


def read_cohort():
    frozen = base.read_json(STUDY / "cohort_freeze.json")
    if any(base.hash_file(ROOT / path) != digest for path, digest in frozen["source_sha256"].items()):
        raise ValueError("Frozen cohort sources or code changed")
    return frozen


def prepare_stimuli():
    frozen = read_cohort()
    previous = base.read_json(REPEAT / "trial_manifest.json")
    instruction = previous["operator_instruction"]
    prev_rgb_hashes = {t["rgb_pixels_sha256"] for t in previous["trials"]}
    used_hashes = set()
    images, polygons = pin_index()
    trials = []
    with ExitStack() as stack:
        archives = base.open_image_archives(stack, frozen)
        for position, row in enumerate(frozen["roster"], 1):
            archive = archives[row["archive"]]
            frame = row["frames"][0]
            entry = archive.getinfo(frame["rgb_member"])
            if f"{entry.CRC:08x}" != frame["crc32"] or entry.file_size != frame["bytes"]:
                raise ValueError("Frozen entry RGB member changed")
            image = base.rgba_image(archive, entry)
            rgb = np.ascontiguousarray(image[:, :, :3])
            alpha = image[:, :, 3] > 0
            if image.shape != (row["height"], row["width"], 4) or not alpha.any():
                raise ValueError("Entry frame differs from the frozen image metadata")
            cue, bbox = cue_for(rgb, alpha)
            x0, y0, x1, y1 = cue["bounds_xyxy_exclusive_max"]
            for poly in polygons[images[entry.filename][0]["id"]]:
                xy = np.asarray(poly).reshape(-1, 2)
                lx, ly = np.floor(xy.min(axis=0)).astype(int)
                hx, hy = np.ceil(xy.max(axis=0)).astype(int)
                if lx < x1 and ly < y1 and hx >= x0 and hy >= y0:
                    raise ValueError("Cue overlaps the entry pin bounding box")
            x, y, tx, ty = cue["lines"][0]
            dx, dy = np.sign([tx - x, ty - y])
            if not any(alpha[ty + dy*k, tx + dx*k] for k in range(100)
                       if 0 <= tx + dx*k < row["width"] and 0 <= ty + dy*k < row["height"]):
                raise ValueError("Coarse cue does not point toward the target silhouette")
            rgb_hash = collector.digest(rgb)
            if rgb_hash in prev_rgb_hashes or rgb_hash in used_hashes:
                raise ValueError("A frozen entry RGB duplicates a development or confirmation scene")
            used_hashes.add(rgb_hash)
            trials.append({
                "trial": position, "tuber": row["tuber"], "archive": row["archive"],
                "entry_file": entry.filename, "entry_crc32": frame["crc32"],
                "center_file": row["frames"][-1]["rgb_member"],
                "width": row["width"], "height": row["height"], "rgb_pixels_sha256": rgb_hash,
                "cue": cue, "private_target_bbox_xyxy": bbox,
            })
    seal_json(STUDY / "trial_manifest.json", {
        "schema": 1, "source": "confirmation", "order_seed": SEED,
        "protocol_sha256": frozen["protocol_sha256"], "operator_instruction": instruction,
        "cohort_sha256": base.hash_file(STUDY / "cohort_freeze.json"), "trials": trials,
    })
    print(f"Prepared {len(trials)} originals and unobscured cues without opening scoring outcomes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["audit", "prepare"])
    option = parser.parse_args()
    (freeze_cohort if option.stage == "audit" else prepare_stimuli)()
