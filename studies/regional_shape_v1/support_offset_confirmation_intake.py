"""Stage only scan assets until the confirmation predictions have been saved."""
import csv
import json
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from potato3d.io import safe_path, sha256
from .replication_intake import (
    COHORT_PATH as PRIOR_COHORT, COHORT_SHA256 as PRIOR_COHORT_SHA256,
    DEMO_PATH, DEV_SELECTION, IMAGE_ARCHIVES, MESH_ARCHIVE, PCD_ARCHIVE,
    PROJECT, REG_ARCHIVE, SHARED_FILES, cohort_from_metadata, extract_member,
)
from .study import HERE, INTRINSICS, METADATA

COHORT = HERE / "support_offset_confirmation_cohort.json"
COHORT_SHA256 = "8e1f11ecf292eefb167a4b3a8d6fe8af6dbeeeb933fcf45cf4b26fb0b76d2188"
DEMO_AUDIT = PROJECT / "docs/calibration_followup_evidence.json"
DEVELOPMENT = HERE / "results.json"
PRIOR_INTAKE = HERE / "replication_preflight.json"

ASSET_ERRORS = (OSError, ValueError, KeyError, TypeError, BadZipFile)


def reproduce_cohort(source, matrices):
    if sha256(COHORT) != COHORT_SHA256 or sha256(PRIOR_COHORT) != PRIOR_COHORT_SHA256:
        raise ValueError("Frozen cohort or prior replication roster has changed")
    cohort = json.loads(COHORT.read_text())
    previous = json.loads(PRIOR_COHORT.read_text())
    demo = json.loads(DEMO_PATH.read_text())["objects"]
    dev = json.loads(DEV_SELECTION.read_text())
    metadata_hashes = {path: sha256(safe_path(source, path)) for path in METADATA.values()}
    for name, path in METADATA.items():
        if metadata_hashes[path] != dev["metadata_sha256"][name]:
            raise ValueError(f"Release metadata differs from the development source: {path}")
    warnings = safe_path(source, METADATA["non-perfect.txt"]).read_text().splitlines()
    warnings = {line.partition("#")[0].strip() for line in warnings} - {""}
    excluded = ({r["object_id"] for r in demo + dev["pairs"]} | {r["label"] for r in previous}
                | set(dev["warning_ids"]) | warnings)
    registered = {Path(name).stem for name in matrices.namelist()
                  if Path(name).parent == Path("tmatrix") and Path(name).suffix == ".json"}
    with safe_path(source, METADATA["ground_truth.csv"]).open(newline="") as handle:
        rebuilt = cohort_from_metadata(list(csv.DictReader(handle)), registered, excluded)
    if cohort != rebuilt or len({r["label"] for r in cohort}) != 36 or len({r["ros_bag_name"] for r in cohort}) != 15:
        raise ValueError("The reserved cohort does not reproduce from release metadata")
    return cohort, metadata_hashes


def index_archive(archive):
    entries = defaultdict(list)
    for info in archive.infolist():
        entries[info.filename].append(info)
    return archive, entries


def stage_scan(archives, obj, root):
    row = {"object_id": obj, "frame_id": None, "unit": "m", "files": {}, "input_failures": []}
    reg_member = f"tmatrix/{obj}.json"
    try:
        registration = extract_member(archives, [(REG_ARCHIVE, reg_member)], f"3_pair/{reg_member}", root)
        row["files"]["registration"] = registration
        partial = json.loads((root/registration["path"]).read_text())["rgbd_pcd_file"]
        frame = Path(partial).stem.rsplit("_", 1)[-1]
        if not frame.isdecimal() or partial != f"1_rgbd/2_pcd/{obj}/{obj}_pcd_{frame}.ply":
            raise ValueError("Released registration does not name the object's expected frame")
        row.update(frame_id=frame, partial=partial)
    except ASSET_ERRORS as error:
        row["input_failures"].append({"stage": "frame_identity", "message": str(error)})
        return row
    names = {role: f"{obj}/{obj}_{role}_{frame}.png" for role in ("rgb", "depth")}
    uses = {
        "partial": (partial, [(PCD_ARCHIVE, f"2_pcd/{obj}/{Path(partial).name}")]),
        **{role: (f"1_rgbd/1_image/{name}", [(archive, name) for archive in IMAGE_ARCHIVES])
           for role, name in names.items()},
    }
    for role, (path, candidates) in uses.items():
        try:
            row["files"][role] = extract_member(archives, candidates, path, root)
        except ASSET_ERRORS as error:
            row["input_failures"].append({"stage": "scan_asset", "role": role, "message": str(error)})
    return row


def prior_content():
    """Use archived digests from the demo, development, and 36-object replication."""
    known = defaultdict(set)
    demo = json.loads(DEMO_PATH.read_text())["objects"]
    demo_audit = json.loads(DEMO_AUDIT.read_text())["audit"]["objects"]
    for row in [*demo, *demo_audit]:
        for role in ("partial", "reference", "registration", "rgb", "depth"):
            if f"{role}_sha256" in row:
                known[(role, row[f"{role}_sha256"])].add(row["object_id"])
    development = json.loads(DEVELOPMENT.read_text())["intake"]["pairs"]
    prior = json.loads(PRIOR_INTAKE.read_text())["staged_pairs"]
    roster = {r["label"] for r in json.loads(PRIOR_COHORT.read_text())}
    if len(prior) != 36 or {r["object_id"] for r in prior} != roster:
        raise ValueError("Previous replication hash inventory differs from its frozen roster")
    for row in [*development, *prior]:
        for role, value in row["files"].items():
            known[(role, value["sha256"])].add(row["object_id"])
    return known


def mark_duplicates(rows, roles):
    known = prior_content()
    assets = [(row, role, asset["sha256"]) for row in rows
              for role, asset in row["files"].items() if role in roles]
    for row, role, digest in assets:
        known[(role, digest)].add(row["object_id"])
    for row, role, digest in assets:
        duplicates = sorted(known[(role, digest)] - {row["object_id"]})
        if duplicates:
            row["input_failures"].append({
                "stage": "duplicate_content", "role": role, "sha256": digest, "matching_object_ids": duplicates,
            })


def stage_scans(source, root):
    archive_hashes, archive_errors = {}, {}
    with ExitStack() as stack:
        matrices = stack.enter_context(ZipFile(safe_path(source, REG_ARCHIVE)))
        cohort, metadata_hashes = reproduce_cohort(source, matrices)
        archives = {REG_ARCHIVE: index_archive(matrices)}
        for relative in (PCD_ARCHIVE, *IMAGE_ARCHIVES):
            try:
                path = safe_path(source, relative)
                zip_file = stack.enter_context(ZipFile(path))
                archives[relative] = index_archive(zip_file)
                archive_hashes[relative] = sha256(path)
            except ASSET_ERRORS as error:
                archive_errors[relative] = type(error).__name__
        rows = [stage_scan(archives, row["label"], root/row["label"]) for row in cohort]
    mark_duplicates(rows, ("partial", "rgb", "depth", "registration"))
    return cohort, rows, {"metadata_sha256": metadata_hashes, "scan_archive_sha256": archive_hashes,
                          "unavailable_scan_archives": archive_errors}


def stage_references(source, root, rows):
    """Open the SfM archive only from the single scoring attempt."""
    archive_hash = None
    try:
        path = safe_path(source, MESH_ARCHIVE)
        archive_hash = sha256(path)
        mesh = ZipFile(path)
    except ASSET_ERRORS as error:
        for row in rows:
            row["input_failures"].append({"stage": "reference_archive", "message": str(error)})
        return archive_hash
    with mesh:
        archives = {MESH_ARCHIVE: index_archive(mesh)}
        for row in rows:
            if row["input_failures"]:
                continue
            obj = row["object_id"]
            staged = root/obj
            try:
                reg = json.loads((staged/row["files"]["registration"]["path"]).read_text())
                reference = reg["sfm_mesh_file"]
                if reference != f"2_sfm/1_mesh/{obj}/{obj}.obj":
                    raise ValueError("Released reference must name the same object as its scan")
                row["files"]["reference"] = extract_member(
                    archives, [(MESH_ARCHIVE, f"3_mesh/{obj}/{obj}.obj")], reference, staged)
                for target, relative in SHARED_FILES.items():
                    path = staged/target
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(safe_path(source, relative).read_bytes())
            except ASSET_ERRORS as error:
                row["input_failures"].append({"stage": "reference_intake", "message": str(error)})
    mark_duplicates(rows, ("reference",))
    return archive_hash
