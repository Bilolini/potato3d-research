"""Freeze a source-locked frame roster without loading outcomes or SfM."""

import csv
from collections import Counter, defaultdict
from contextlib import ExitStack
from pathlib import Path
import sys
from zipfile import ZipFile

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
PILOT = STUDY.parent / "raft_fusion_geometry_v1"
OUTPUTS = ROOT / "outputs/raft_fusion_traits_v1"
sys.path.insert(0, str(PILOT))
# Import the pilot's read-only asset helpers with their original module name.
import prepare as pilot

ORIGINAL = STUDY.parent / "multiframe_weight_v1"
CORRECTION = STUDY.parent / "multiframe_weight_correction_v1"
TRAITS = pilot.RELEASE / "3_pair/ground_truth.csv"
ARCHIVE_TARGETS = {"weight": "weight_g_inctack", "volume": "volume_ml"}
SEED = 5272401


def indexed_rows(path, key="tuber"):
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    index = {row[key]: row for row in rows}
    if len(index) != len(rows):
        raise ValueError(f"Duplicate keys in {path}")
    return index


def source_hashes():
    paths = [
        STUDY / "protocol.md", Path(__file__), STUDY / "features.py",
        PILOT / "protocol.md", PILOT / "frame_manifest.json", PILOT / "alignment_freeze.json",
        PILOT / "flow.py", PILOT / "register.py", PILOT / "alignment.py", PILOT / "prepare.py",
        ORIGINAL / "frame_manifest.json", ORIGINAL / "per_frame_predictions.csv", ORIGINAL / "results.json",
        CORRECTION / "frame_manifest.json", CORRECTION / "scan_features.csv", TRAITS, pilot.CAMERA, pilot.HELD_OUT,
        *(ROOT / name for name, _, _ in pilot.RESERVES),
    ]
    return {str(path.relative_to(ROOT)): pilot.digest(path) for path in paths}


def frozen_inputs():
    original_path = ORIGINAL/"frame_manifest.json"
    prior = pilot.read_json(original_path)
    correction = pilot.read_json(CORRECTION/"frame_manifest.json")
    fit_report = pilot.read_json(ORIGINAL/"results.json")
    if prior["archive_bytes"] != pilot.CLOUDS.stat().st_size:
        raise ValueError("The archive size differs from the frame freeze")
    if prior["source_sha256"][str(TRAITS.relative_to(ROOT))] != pilot.digest(TRAITS):
        raise ValueError("Measured traits CSV changed since the development study")
    if correction["features_sha256"] != pilot.digest(CORRECTION/"scan_features.csv"):
        raise ValueError("Archived center features changed")
    if fit_report["per_frame_sha256"] != pilot.digest(ORIGINAL/"per_frame_predictions.csv"):
        raise ValueError("Archived validation frame features changed")
    base = {r["tuber"]: r for r in prior["frames"]}
    fixed = {r["tuber"]: r for r in correction["frames"]}
    if set(base) != set(fixed) or len(base) != 158:
        raise ValueError("Frame sources disagree about the enrolled potatoes")
    pilot_ids = {i["tuber"] for i in pilot.read_json(PILOT/"frame_manifest.json")["roster"]}
    hold = {i["tuber"] for i in pilot.read_json(pilot.HELD_OUT)["roster"]}
    reserves = set()
    for name, section, key in pilot.RESERVES:
        group = pilot.read_json(ROOT/name)
        reserves.update(r[key] for r in (group[section] if section else group))
    if len(hold) != 45 or len(pilot_ids) != 10 or (set(base) & (hold | reserves)):
        raise ValueError("Archived development boundary mismatch")
    if any(base[r]["split"] != "val" for r in pilot_ids):
        raise ValueError("A pilot potato was assigned to training")
    roster = [base[k] for k in sorted(base, key=lambda i: (base[i]["split"], i)) if k not in pilot_ids]
    counts = Counter(r["split"] for r in roster)
    if counts != {"train": 118, "val": 30}:
        raise ValueError(f"Expected 118 training and 30 other development potatoes: {counts}")
    return roster, fixed, sorted(pilot_ids)


def freeze():
    roster, fixed, excluded_ids = frozen_inputs()
    ids = {r["tuber"] for r in roster}
    planned = []
    with ExitStack() as stack:
        ply = stack.enter_context(ZipFile(pilot.CLOUDS))
        archives = pilot.open_images(stack, (p.name for p in pilot.RGBD.glob("*.zip")))
        images = defaultdict(list)
        for name, zip_file in archives.items():
            for entry in zip_file.infolist():
                fields = pilot.IMAGE_KEY.fullmatch(entry.filename)
                if fields and fields["tuber"] in ids:
                    images[fields["tuber"], fields["kind"], int(fields["suffix"])].append((name, entry))
        for row in roster:
            tuber = row["tuber"]
            choice = fixed[tuber]
            lower, center, upper = choice["frames"]["spaced"]
            if not lower < center < upper or row["split"] != choice["split"]:
                raise ValueError(f"Invalid archived triplet for {tuber}")
            if row["split"] == "val" and choice["frames"]["spaced"] != row["frames"]["spaced"]:
                raise ValueError(f"Validation triplet changed: {tuber}")
            selected = {r["suffix"]: r for r in choice["members"]}
            frames = []
            for suffix in sorted(n for n in row["available_suffixes"] if lower <= n <= upper):
                frame = {"suffix": suffix, "problems": []}
                try:
                    info = ply.getinfo(f"2_pcd/{tuber}/{tuber}_pcd_{suffix}.ply")
                    frame["ply"] = pilot.asset(info)
                    if suffix in selected and any(frame["ply"][k] != selected[suffix][k] for k in ("crc32","bytes","member")):
                        frame["problems"].append("Selected PLY differs from archived checksum")
                except KeyError:
                    frame["problems"].append("Missing released PLY")
                for kind, fmt in (("rgb", (1280,720,8,6)), ("depth", (1280,720,16,0))):
                    records = images[tuber,kind,suffix]
                    if len(records) != 1:
                        frame["problems"].append(f"Missing or ambiguous {kind} archive member")
                        continue
                    name, info = records[0]
                    if pilot.png_header(archives[name],info) != fmt:
                        frame["problems"].append(f"Invalid {kind} PNG header for provided support")
                        continue
                    frame[kind] = pilot.asset(info,name)
                frames.append(frame)
            if not set((lower, center, upper)) <= {f["suffix"] for f in frames}:
                raise ValueError(f"Frozen archive roster is missing a selected suffix: {tuber}")
            planned.append({
                "tuber": tuber, "split": row["split"], "selected": [lower, center, upper],
                "acquisition_group": row["acquisition_group"], "cultivar": row["cultivar"], "frames": frames,
            })
    fit_check = pilot.read_json(PILOT/"alignment_freeze.json")
    if fit_check["alignment_code_sha256"] != pilot.digest(PILOT/"alignment.py"):
        raise ValueError("Pilot alignment code has changed")
    if pilot.digest(pilot.CHECKPOINT) != pilot.CHECKPOINT_HASH:
        raise ValueError("Pilot checkpoint hash differs")
    frozen = {
        "stage": "frozen_before_feature_extraction_and_scoring", "sources_sha256": source_hashes(),
        "archived_ply_bytes": pilot.CLOUDS.stat().st_size, "pilot_ids_excluded": excluded_ids,
        "train_n": 118, "evaluation_n": 30, "seed": SEED, "checkpoint_sha256": pilot.CHECKPOINT_HASH,
        "roster": planned,
    }
    pilot.freeze_check(STUDY/"frame_manifest.json", frozen)
    print("Frozen",len(planned),"potatoes,",sum(len(p["frames"])-1 for p in planned),"adjacent links;",
          sum(bool(f["problems"]) for r in planned for f in r["frames"]),"frames with metadata problems.")


def read_freeze():
    frozen = pilot.read_json(STUDY/"frame_manifest.json")
    if (frozen["sources_sha256"] != source_hashes()
            or frozen["archived_ply_bytes"] != pilot.CLOUDS.stat().st_size):
        raise ValueError("Frozen sources or archive changed")
    return frozen


if __name__ == "__main__":
    freeze()
