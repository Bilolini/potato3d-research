"""Freeze the cohort, registration metadata and exact archive members."""

from collections import defaultdict
from contextlib import ExitStack
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import struct
import sys
from zipfile import ZipFile

import numpy as np
from PIL import Image

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
RELEASE = ROOT / "data/raw/3DPotatoTwin"
ASSETS = ROOT / "outputs/raft_fusion_geometry_v1"
ARCHIVED = ROOT / "studies/multiframe_weight_v1/frame_manifest.json"
HELD_OUT = ROOT / "studies/sam2_human_prompt_confirmation_v1/cohort_freeze.json"
RGBD = RELEASE / "1_rgbd/1_images"
CLOUDS = RELEASE / "1_rgbd/2_pcd.zip"
MESHES = RELEASE / "2_sfm/1_mesh.zip"
MATRICES = RELEASE / "3_pair/tmatrix.zip"
CAMERA = RELEASE / "1_rgbd/0_camera_intrinsics/realsense_d405_camera_intrinsic.json"
CHECKPOINT = ASSETS / "assets/raft_small_C_T_V2-01064c6d.pth"
CHECKPOINT_HASH = "01064c6dba73b0fc9fc8edf772248560a00a3acfd62ac6677e9eeebad9680e27"
SEED = 5272401
ORDER = "raft-fusion-geometry-v1/133/"
IMAGE_KEY = re.compile(r"(?P<tuber>[^/]+)/(?P=tuber)_(?P<kind>rgb|depth)_(?P<suffix>\d+)\.png")
RESERVES = (
    ("studies/regional_shape_v1/replication_cohort.json", None, "label"),
    ("studies/regional_shape_v1/support_offset_confirmation_cohort.json", None, "label"),
    ("studies/regional_shape_v1/corepp_pin_confirmation/roster.json", "frames", "tuber"),
)


def digest(path):
    with path.open("rb") as f:
        return sha256_file(f)


def sha256_file(file):
    import hashlib
    return hashlib.file_digest(file, "sha256").hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    payload = json.dumps(value, indent=2, allow_nan=False) + "\n"
    temp = path.with_suffix(".tmp")
    temp.write_text(payload)
    temp.replace(path)


def sealed_sources():
    return {str(p.relative_to(ROOT)): digest(p) for p in (
        STUDY / "prepare.py", STUDY / "protocol.md", ARCHIVED, HELD_OUT, CAMERA,
        *(ROOT / name for name, _, _ in RESERVES),
    )}


def freeze_check(path, data):
    if path.exists() and read_json(path) != data:
        raise ValueError(f"Frozen metadata differs at {path}")
    write_json(path, data)


def asset(info, archive=None):
    result = {"member": info.filename, "bytes": info.file_size, "crc32": info.CRC}
    if archive:
        result["archive"] = archive
    return result


def member_bytes(archive, record):
    info = archive.getinfo(record["member"])
    if info.file_size != record["bytes"] or info.CRC != record["crc32"]:
        raise ValueError(f"Frozen archive member changed: {info.filename}")
    return archive.read(info)


def open_images(context, names):
    return {name: context.enter_context(ZipFile(RGBD / name)) for name in sorted(set(names))}


def png_header(archive, entry):
    with archive.open(entry) as stream:
        header = stream.read(29)
    if header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise ValueError(f"Unexpected PNG header: {entry.filename}")
    return struct.unpack(">IIBB", header[16:26])


def read_rgba(archive, record):
    with Image.open(io.BytesIO(member_bytes(archive, record))) as img:
        if img.mode != "RGBA" or img.size != (1280, 720):
            raise ValueError("Expected the original RGBA frame with provided alpha")
        return np.array(img)


def safe_rigid(t):
    return (t.shape == (4, 4) and np.isfinite(t).all()
            and np.allclose(t[-1], [0., 0., 0., 1.], atol=1e-8, rtol=0)
            and np.allclose(t[:3, :3].T @ t[:3, :3], np.eye(3), atol=1e-5, rtol=0)
            and abs(np.linalg.det(t[:3, :3]) - 1.) <= 1e-5)


def freeze():
    dev = [r for r in read_json(ARCHIVED)["frames"] if r["split"] == "val"]
    ids = {r["tuber"] for r in dev}
    held = {r["tuber"] for r in read_json(HELD_OUT)["roster"]}
    reserved = set()
    for name, section, key in RESERVES:
        source = read_json(ROOT / name)
        reserved.update(r[key] for r in (source[section] if section else source))
    if len(ids) != 40 or len(dev) != 40 or len(held) != 45 or ids & (held | reserved):
        raise ValueError("Development roster or held-out boundary changed")
    audited, eligible = [], []
    with ExitStack() as stack:
        reg, mesh, cloud = [stack.enter_context(ZipFile(p)) for p in (MATRICES, MESHES, CLOUDS)]
        zip_names = [p.name for p in RGBD.glob("*.zip")]
        images = open_images(stack, zip_names)
        by_key = defaultdict(list)
        for name, file in images.items():
            for entry in file.infolist():
                fields = IMAGE_KEY.fullmatch(entry.filename)
                if fields and fields["tuber"] in ids:
                    by_key[fields["tuber"], fields["kind"], int(fields["suffix"])].append((name, entry))
        for row in dev:
            tuber = row["tuber"]
            lo, center, hi = row["frames"]["spaced"]
            record = {"tuber": tuber, "selected_suffixes": [lo, center, hi],
                      "acquisition_group": row["acquisition_group"], "cultivar": row["cultivar"],
                      "reason": ""}
            try:
                reg_entry = reg.getinfo(f"tmatrix/{tuber}.json")
                metadata = json.loads(reg.read(reg_entry))
                t = np.asarray(metadata["T"], dtype=float)
                if not safe_rigid(t):
                    raise ValueError("Invalid released center-to-SfM rigid transform")
                if (metadata["rgbd_pcd_file"] != f"1_rgbd/2_pcd/{tuber}/{tuber}_pcd_{center}.ply"
                        or metadata["sfm_mesh_file"] != f"2_sfm/1_mesh/{tuber}/{tuber}.obj"):
                    raise ValueError("Released registration names another frame or object")
                if not lo < center < hi or center != row["frames"]["center"][0]:
                    raise ValueError("Archived quartiles do not bracket the registered center")
                ref = mesh.getinfo(f"3_mesh/{tuber}/{tuber}.obj")
                if not ref.file_size:
                    raise ValueError("Empty reference OBJ")
                frames = []
                for suffix in sorted(i for i in row["available_suffixes"] if lo <= i <= hi):
                    frame = {"suffix": suffix}
                    for kind, fmt in (("rgb", (1280, 720, 8, 6)), ("depth", (1280, 720, 16, 0))):
                        entries = by_key[tuber, kind, suffix]
                        if len(entries) != 1:
                            raise ValueError(f"Missing or ambiguous {kind} at suffix {suffix}")
                        name, entry = entries[0]
                        if png_header(images[name], entry) != fmt:
                            raise ValueError(f"Unexpected {kind} PNG dimensions or channel types at suffix {suffix}")
                        frame[kind] = asset(entry, name)
                    frame["ply"] = asset(cloud.getinfo(f"2_pcd/{tuber}/{tuber}_pcd_{suffix}.ply"))
                    if not frame["ply"]["bytes"]:
                        raise ValueError(f"Empty released cloud at suffix {suffix}")
                    frames.append(frame)
                if not set((lo, center, hi)) <= {f["suffix"] for f in frames}:
                    raise ValueError("Missing a selected view")
                record["frame_count"] = len(frames)
                eligible.append({
                    **record, "frames": frames, "reference": asset(ref), "registration": asset(reg_entry),
                    "center_to_sfm_m": t.tolist(),
                })
            except (KeyError, ValueError, OSError) as error:
                record["reason"] = str(error)
            audited.append(record)
    ordered = sorted(eligible, key=lambda r: (sha256((ORDER+r["tuber"]).encode()).hexdigest(), r["tuber"]))
    if len(ordered) < 10:
        raise ValueError("Fewer than ten metadata-eligible potatoes")
    selected = ordered[:10]
    manifest = {
        "stage": "metadata_only_freeze", "sources": sealed_sources(), "seed": SEED, "selection_order_key": ORDER,
        "candidate_count": len(dev), "eligible_count": len(ordered), "candidate_audit": audited, "roster": selected,
        "checkpoint_sha256": CHECKPOINT_HASH, "held_out_excluded_count": len(held),
    }
    freeze_check(STUDY / "frame_manifest.json", manifest)
    print(f"Selected ten of {len(ordered)} eligible development potatoes. "
          f"{sum(len(r['frames'])-1 for r in selected)} adjacent links.")
    print([(r["tuber"], r["selected_suffixes"]) for r in selected])
    print("Exclusions:", [r for r in audited if r["reason"]])


def load_manifest():
    frozen = read_json(STUDY / "frame_manifest.json")
    if frozen["sources"] != sealed_sources():
        raise ValueError("Frozen roster sources changed")
    return frozen


if __name__ == "__main__":
    freeze()
