"""Paths and provenance utilities shared by the replay and scoring stages."""

import csv
from pathlib import Path
import sys

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
PILOT = STUDY.parent / "raft_fusion_geometry_v1"
TRAIT_STUDY = STUDY.parent / "raft_fusion_traits_v1"
REPEAT = STUDY.parent / "sam2_human_prompt_v1/repeat_01"
OUTPUT = ROOT / "outputs/sam2_raft_end_to_end_v1"
OLD_TRAIT_ASSETS = ROOT / "outputs/raft_fusion_traits_v1"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PILOT))
sys.path.append(str(ROOT / "outputs/corepp_cross_model/triposr/deps"))
import prepare as prep

TRAITS = prep.RELEASE / "3_pair/ground_truth.csv"
ENV = ("2.7.1", "0.22.1")
METHODS = "ABCD"
TARGETS = {"weight": "weight_g_inctack", "volume": "volume_ml"}
SEED = 5272401
DRAWS = 10_000


def csv_rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def by_tuber(rows):
    keyed = {row["tuber"]: row for row in rows}
    if len(keyed) != len(rows):
        raise ValueError("Duplicate exact tuber ID")
    return keyed


def write_csv(path, rows, fields=None):
    columns = fields or list(dict.fromkeys(key for row in rows for key in row))
    temp = path.with_suffix(".tmp")
    with temp.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def frame_manifest():
    freeze = prep.read_json(STUDY / "frame_manifest.json")
    for filename, sha in freeze["sources_sha256"].items():
        current = prep.digest(ROOT / filename)
        if current == sha:
            continue
        # Preserve the tracking manifest and receipts for the downstream reader fix.
        correction = STUDY / "mask_reader_correction.json"
        if ROOT / filename == Path(__file__) and correction.is_file():
            receipt = prep.read_json(correction)
            if (receipt["frozen_manifest_sha256"] == prep.digest(STUDY / "frame_manifest.json")
                    and receipt["original_common_sha256"] == sha
                    and receipt["corrected_common_sha256"] == current):
                continue
        raise ValueError(f"Frozen tracking input changed: {filename}")
    return freeze


def tracking_bundle():
    freeze = frame_manifest()
    summary = prep.read_json(STUDY / "tracking_replay.json")
    if summary["manifest_sha256"] != prep.digest(STUDY / "frame_manifest.json"):
        raise ValueError("Tracking replay belongs to a different frozen roster")
    if [(r["tuber"], r["tracking_record_sha256"]) for r in summary["rows"]] != [
        (row["tuber"], prep.digest(track_path(row["tuber"]))) for row in freeze["roster"]
    ]:
        raise ValueError("A tracking record differs from the replay receipt")
    if summary["mismatches"] or summary["unverified"] or summary["exact_centers"] != len(freeze["roster"]):
        raise ValueError("Need to diagnose incomplete or discrepant center-mask replay before use")
    return freeze, summary


def track_path(tuber):
    return OUTPUT / "tracking" / f"{tuber}.json"


def packed_masks(tuber, record):
    import numpy as np

    filename = track_path(tuber).with_suffix(".npz")
    if prep.digest(filename) != record["mask_sha256"]:
        raise ValueError(f"Propagated mask file changed: {tuber}")
    with np.load(filename, allow_pickle=False) as contents:
        return {int(key) if key != "prompt" else key: value for key, value in contents.items()}


def unpack(bits):
    import numpy as np

    return np.unpackbits(bits, count=720 * 1280).reshape(720, 1280).astype(bool)
