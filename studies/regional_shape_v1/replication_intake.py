"""Select, stage and hash the released assets without scoring replication outcomes."""
import csv
import hashlib
import json
from collections import defaultdict, deque
from contextlib import ExitStack
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from potato3d.geometry import rigid_matrix
from potato3d.io import safe_path, sha256
from .study import HERE, INTRINSICS, LOBE_STUDY, METADATA

PROJECT = HERE.parents[1]
DEMO_PATH = PROJECT / "data/demo_manifest.json"
DEV_SELECTION = LOBE_STUDY / "fresh_selection.json"
COHORT_PATH = HERE / "replication_cohort.json"
COHORT_SHA256 = "d9eb49dde8cc1111d564fcdcb528225d6d847d12205d33962b3d9fb69226a809"
COHORT_FIELDS = ("label", "cultivar", "ros_bag_name", "exp_split")
TARGET_COUNTS = {"Corolle": 12, "Sayaka": 24}
IMAGE_ARCHIVES = tuple(f"1_rgbd/1_images/{part}.zip" for part in ("1R-A", "1R-B", "3R", "4R", "5R"))
PCD_ARCHIVE = "1_rgbd/2_pcd.zip"
MESH_ARCHIVE = "2_sfm/1_mesh.zip"
REG_ARCHIVE = METADATA["tmatrix.zip"]
SHARED_FILES = {
    "ground_truth.csv": METADATA["ground_truth.csv"],
    "3_pair/non-perfect.txt": METADATA["non-perfect.txt"],
    INTRINSICS: INTRINSICS,
}


def order_hash(name):
    return hashlib.sha256(("regional-replication-v1/" + name).encode("utf-8")).hexdigest()


def cohort_from_metadata(traits, registered, excluded):
    cohort = []
    for cultivar, target in TARGET_COUNTS.items():
        grouped = defaultdict(list)
        for row in traits:
            if (row["cultivar"] == cultivar and row["label"] in registered
                    and row["label"] not in excluded and row["exp_split"] in ("train", "test")):
                grouped[row["ros_bag_name"]].append({k: row[k] for k in COHORT_FIELDS})
        groups = [
            deque(sorted(grouped[group], key=lambda r: order_hash(r["label"])))
            for group in sorted(grouped, key=order_hash)
        ]
        selected = []
        while len(selected) < target:
            batch = [queue.popleft() for queue in groups if queue]
            if not batch:
                raise ValueError(f"Too few eligible metadata rows for {cultivar}")
            selected.extend(batch)
        cohort.extend(selected[:target])
    return cohort


def collect_metadata(source, matrices):
    if sha256(COHORT_PATH) != COHORT_SHA256:
        raise ValueError("Cohort file differs from the hash declared by the protocol")
    cohort = json.loads(COHORT_PATH.read_text())
    dev = json.loads(DEV_SELECTION.read_text())
    demo = json.loads(DEMO_PATH.read_text())["objects"]
    metadata_hashes = {path: sha256(safe_path(source, path)) for path in METADATA.values()}
    for name, path in METADATA.items():
        if metadata_hashes[path] != dev["metadata_sha256"][name]:
            raise ValueError(f"Release metadata differs from the archived development source: {path}")

    warnings = safe_path(source, METADATA["non-perfect.txt"]).read_text().splitlines()
    warnings = {line.partition("#")[0].strip() for line in warnings} - {""}
    prior_ids = {p["object_id"] for p in demo} | {p["object_id"] for p in dev["pairs"]}
    excluded = prior_ids | warnings | set(dev["warning_ids"])
    registered = {Path(p).stem for p in matrices.namelist()
                  if Path(p).parent == Path("tmatrix") and Path(p).suffix == ".json"}
    with safe_path(source, METADATA["ground_truth.csv"]).open(newline="") as handle:
        rebuilt = cohort_from_metadata(list(csv.DictReader(handle)), registered, excluded)
    if cohort != rebuilt or len({r["label"] for r in cohort}) != 36:
        raise ValueError("Fixed cohort differs from the protocol's metadata-only selection")
    return cohort, metadata_hashes


def extract_member(archives, candidates, target, root):
    found = [(archive, info) for archive, member in candidates if archive in archives
             for info in archives[archive][1].get(member, [])]
    if not found:
        raise FileNotFoundError(f"No archive entry for {target}")
    if len(found) != 1:
        raise ValueError(f"Multiple archive entries for {target}")
    archive, info = found[0]
    data = archives[archive][0].read(info)  # ZipFile checks the member CRC.
    path = root / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": target, "archive": archive, "member": info.filename,
            "size_bytes": info.file_size, "crc32": f"{info.CRC:08x}", "sha256": sha256(path)}


def stage_pair(source, root, row, archives):
    obj = row["label"]
    staged = {"object_id": obj, "frame_id": None, "files": {}, "failures": []}
    files = staged["files"]
    reg_member = f"tmatrix/{obj}.json"
    try:
        reg_asset = extract_member(archives, [(REG_ARCHIVE, reg_member)], f"3_pair/{reg_member}", root)
        files["registration"] = reg_asset
        reg = json.loads((root / reg_asset["path"]).read_text())
        partial, reference = reg["rgbd_pcd_file"], reg["sfm_mesh_file"]
        frame = Path(partial).stem.rsplit("_", 1)[-1]
        if (not frame.isdecimal() or partial != f"1_rgbd/2_pcd/{obj}/{obj}_pcd_{frame}.ply"
                or reference != f"2_sfm/1_mesh/{obj}/{obj}.obj"):
            raise ValueError("Released registration names unexpected paths or a different object")
        staged["frame_id"] = frame
        rigid_matrix(reg["T"])
    except (OSError, ValueError, KeyError, TypeError, BadZipFile) as error:
        staged["failures"].append({"stage": "registration_asset", "message": str(error)})
        return staged

    names = {role: f"{obj}/{obj}_{role}_{frame}.png" for role in ("rgb", "depth")}
    plan = {
        "partial": (partial, [(PCD_ARCHIVE, f"2_pcd/{Path(partial).parent.name}/{Path(partial).name}")]),
        "reference": (reference, [(MESH_ARCHIVE, f"3_mesh/{obj}/{obj}.obj")]),
        **{role: (f"1_rgbd/1_image/{name}", [(archive, name) for archive in IMAGE_ARCHIVES])
           for role, name in names.items()},
    }
    for role, (target, candidates) in plan.items():
        try:
            files[role] = extract_member(archives, candidates, target, root)
        except (OSError, ValueError, BadZipFile) as error:
            staged["failures"].append({"stage": "unavailable_asset", "role": role, "message": str(error)})
    for target, relative in SHARED_FILES.items():
        path = root / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(safe_path(source, relative).read_bytes())
    return staged


def mark_duplicates(staged):
    roles = ("partial", "reference", "registration", "rgb", "depth")
    known = defaultdict(set)
    for r in json.loads(DEMO_PATH.read_text())["objects"]:
        for role in roles:
            digest = r.get(f"{role}_sha256")
            if digest:
                known[(role, digest)].add(r["object_id"])
    for r in json.loads((HERE / "results.json").read_text())["intake"]["pairs"]:
        for role, asset in r["files"].items():
            known[(role, asset["sha256"])].add(r["object_id"])
    for r in staged:
        for role, asset in r["files"].items():
            known[(role, asset["sha256"])].add(r["object_id"])
    for r in staged:
        for role, asset in r["files"].items():
            duplicates = sorted(known[(role, asset["sha256"])] - {r["object_id"]})
            if duplicates:
                r["failures"].append({"stage": "duplicate_content", "role": role,
                                      "matching_object_ids": duplicates, "sha256": asset["sha256"]})


def stage_replication(source, root):
    archive_hashes, archive_errors = {}, {}
    with ExitStack() as stack:
        matrices = stack.enter_context(ZipFile(safe_path(source, REG_ARCHIVE)))
        cohort, metadata_hashes = collect_metadata(source, matrices)
        archives = {}
        for relative in (REG_ARCHIVE, PCD_ARCHIVE, MESH_ARCHIVE, *IMAGE_ARCHIVES):
            try:
                path = safe_path(source, relative)
                archive = matrices if relative == REG_ARCHIVE else stack.enter_context(ZipFile(path))
            except (OSError, BadZipFile) as error:
                archive_errors[relative] = type(error).__name__
                continue
            entries = defaultdict(list)
            for info in archive.infolist():
                entries[info.filename].append(info)
            archives[relative] = (archive, entries)
            archive_hashes[relative] = metadata_hashes[relative] if relative in metadata_hashes else sha256(path)
        staged = [stage_pair(source, root / row["label"], row, archives) for row in cohort]
    mark_duplicates(staged)
    return cohort, staged, {"metadata_sha256": metadata_hashes, "archive_sha256": archive_hashes,
                            "unavailable_archives": archive_errors}
