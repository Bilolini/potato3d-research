"""Freeze the CPU ellipsoid disagreement policy, then evaluate it on archived volumes."""

import argparse
import csv
from hashlib import sha256 as bytes_sha256
from itertools import combinations
import json
from math import isfinite
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

import numpy as np
from potato3d.completion import ellipsoid
from potato3d.geometry import camera_to_belt_mm, mesh_quality, transform_points
from potato3d.io import load_points, safe_path, sha256

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "corepp_two_frame_volume"
PROTOCOL = HERE / "corepp_volume_rescan_protocol.md"
DEV = HERE.parent / "real_lobes_v1"
CENTER_COLUMNS = ("tuber", "center_frame", "center_ml")
N = 10
BUDGET = 2
BELT_DEPTH_MM = 350.
SCAN_ARCHIVE = "1_rgbd/2_pcd.zip"
REGISTRATION_ARCHIVE = "3_pair/tmatrix.zip"


def read_json(path):
    return json.loads(path.read_text())


def save_json(path, data):
    with path.open("x") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")


def save_csv(path, rows):
    with path.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def code_hashes():
    return {p.name: sha256(p) for p in (Path(__file__), PROTOCOL)}


def read_centers():
    roster = {r["tuber"]: r["frame"] for r in read_json(ARCHIVE / "frozen_protocol.json")["frames"]}
    with (ARCHIVE / "per_potato.csv").open(newline="") as stream:
        rows = [{k: r[k] for k in CENTER_COLUMNS} for r in csv.DictReader(stream)]
    if len(rows) != N or len(roster) != N or {r["tuber"]: r["center_frame"] for r in rows} != roster:
        raise ValueError("Center predictions must match the frozen ten development frames")
    for row in rows:
        row["center_ml"] = float(row["center_ml"])
        if not isfinite(row["center_ml"]) or row["center_ml"] <= 0:
            raise ValueError(f"Invalid archived center volume for {row['tuber']}")
    return rows


def fit_one(center, release_pair, members, clouds, registrations, staged):
    tuber, frame = center["tuber"], center["center_frame"]
    name = f"{tuber}_pcd_{frame}.ply"
    reg_name = release_pair["registration_member"]
    reg = json.loads(registrations.read(reg_name))
    if (release_pair["frame"] != frame or reg["rgbd_pcd_file"] != release_pair["partial"] or
            Path(reg["rgbd_pcd_file"]).name != name):
        raise ValueError(f"Released center registration mismatch for {tuber}")
    record = {**center, "registration_member": reg_name, "ellipsoid_ml": None,
              "disagreement_ml": None, "fit_failure": None}
    try:
        entry = members[tuber, name]
        info = clouds.getinfo(entry["member_path"])
        if info.filename != f"2_pcd/{tuber}/{name}" or info.file_size != int(entry["uncompressed_bytes"]):
            raise ValueError("Cloud member differs from development manifest")
        raw = clouds.read(info)
        record.update(partial_member=info.filename, partial_sha256=bytes_sha256(raw).hexdigest())
        staged.write_bytes(raw)
        points = transform_points(load_points(staged, "m"), camera_to_belt_mm(BELT_DEPTH_MM))
        record.update(point_count=len(points), min_height_mm=float(points[:, 2].min()),
                      max_height_mm=float(points[:, 2].max()))
        mesh, params = ellipsoid(points)
        volume = mesh_quality(mesh)["volume_ml"]
        if volume is None or not isfinite(volume) or volume <= 0:
            raise ValueError("Ellipsoid lacks a valid positive mesh volume")
        record.update(ellipsoid_ml=volume, disagreement_ml=abs(volume - center["center_ml"]),
                      axes_mm=[float(a) for a in params["axes_mm"]])
    except (ValueError, OSError, KeyError, RuntimeError, BadZipFile, np.linalg.LinAlgError) as error:
        record["fit_failure"] = f"{type(error).__name__}: {error}"
    return record


def select(args):
    output = args.out / "frozen_selection.json"
    if output.exists():
        raise FileExistsError(output)
    centers = read_centers()
    ids = {r["tuber"] for r in centers}
    selection_file = DEV / "fresh_selection.json"
    members_file = DEV / "fresh_download_members.tsv"
    selection = read_json(selection_file)
    releases = {p["object_id"]: p for p in selection["pairs"] if p["object_id"] in ids}
    registration_path = safe_path(args.source, REGISTRATION_ARCHIVE)
    if sha256(registration_path) != selection["metadata_sha256"]["tmatrix.zip"] or releases.keys() != ids:
        raise ValueError("The registered center cohort differs from the development archive")
    with members_file.open(newline="") as stream:
        members = {(r["tuber_id"], r["member_basename"]): r for r in csv.DictReader(stream, delimiter="\t")
                   if r["tuber_id"] in ids and r["archive"] == SCAN_ARCHIVE}
    with (TemporaryDirectory(prefix="volume-rescan-") as folder,
          ZipFile(safe_path(args.source, SCAN_ARCHIVE)) as clouds,
          ZipFile(registration_path) as registrations):
        rows = [fit_one(r, releases[r["tuber"]], members, clouds, registrations, Path(folder) / "scan.ply")
                for r in centers]
    disagreement = sorted(rows, key=lambda r: (
        r["fit_failure"] is None, -(r["disagreement_ml"] or 0), r["tuber"]))
    size = sorted(rows, key=lambda r: (-r["center_ml"], r["tuber"]))
    for i, r in enumerate(disagreement, 1):
        r.update(disagreement_rank=i, disagreement_flagged=i <= BUDGET)
    for i, r in enumerate(size, 1):
        r.update(size_rank=i, size_flagged=i <= BUDGET)
    flags = {"disagreement": [r["tuber"] for r in disagreement[:BUDGET]],
             "size": [r["tuber"] for r in size[:BUDGET]]}
    save_json(output, {
        "stage": "center_only_selection_frozen_before_outcome_join", "code_sha256": code_hashes(),
        "center_roster_sha256": sha256(ARCHIVE / "frozen_protocol.json"),
        "dev_manifest_sha256": sha256(selection_file), "partial_index_sha256": sha256(members_file),
        "points_archive": SCAN_ARCHIVE, "registration_archive": REGISTRATION_ARCHIVE,
        "belt_depth_mm": BELT_DEPTH_MM, "budget": BUDGET, "flags": flags, "per_potato": rows,
    })
    print(f"Center-only selections frozen at {output}.")
    print(flags)


def score_pair(pair, outcomes):
    return mean(row["average_error_ml"] if tuber in pair else row["center_error_ml"]
                for tuber, row in outcomes.items())


def evaluate(args):
    frozen_path = args.out / "frozen_selection.json"
    frozen = read_json(frozen_path)
    results = args.out / "results.json"
    if results.exists():
        raise FileExistsError(results)
    if (frozen["stage"] != "center_only_selection_frozen_before_outcome_join" or
            frozen["code_sha256"] != code_hashes() or
            frozen["center_roster_sha256"] != sha256(ARCHIVE / "frozen_protocol.json")):
        raise ValueError("Protocol, selection code or center roster changed after freezing")
    selection = {r["tuber"]: r for r in frozen["per_potato"]}
    source = ARCHIVE / "per_potato.csv"
    with source.open(newline="") as stream:
        archive_rows = list(csv.DictReader(stream))
    if len(archive_rows) != N or {r["tuber"] for r in archive_rows} != selection.keys():
        raise ValueError("Archived outcome IDs do not match the frozen ten")
    outcomes = {}
    for r in archive_rows:
        tuber = r["tuber"]
        center = float(r["center_ml"])
        if r["center_frame"] != selection[tuber]["center_frame"] or center != selection[tuber]["center_ml"]:
            raise ValueError(f"Center changed for {tuber}")
        drainage, second, average = (float(r[k]) for k in ("drainage_ml", "second_ml", "average_ml"))
        if (r["failures"] or not all(isfinite(v) and v > 0 for v in (drainage, second, average)) or
                abs(average - mean((center, second))) > 1e-8):
            raise ValueError(f"Missing or inconsistent archived outcome for {tuber}")
        ec, ea = abs(center - drainage), abs(average - drainage)
        outcomes[tuber] = {**selection[tuber], "second_frame": r["second_frame"],
                           "drainage_ml": drainage, "second_ml": second, "average_ml": average,
                           "center_error_ml": ec, "average_error_ml": ea, "rescan_improvement_ml": ec - ea}
    pairs = [{"pair": pair, "mae_ml": score_pair(pair, outcomes)}
             for pair in combinations(sorted(outcomes), BUDGET)]
    assert len(pairs) == 45
    best = min(pairs, key=lambda r: (r["mae_ml"], r["pair"]))
    flags = frozen["flags"]
    policies = {rule: {"pair": pair, "mae_ml": score_pair(pair, outcomes)}
                for rule, pair in ({"center_all": []} | flags).items()}
    policies["random"] = {"pair_count": len(pairs), "mae_ml": mean(r["mae_ml"] for r in pairs)}
    policies["oracle"] = best
    disagreement = policies["disagreement"]["mae_ml"]
    differences = {rule: disagreement - policies[rule]["mae_ml"]
                   for rule in ("center_all", "random", "size")}
    per_potato = []
    for tuber, r in outcomes.items():
        per_potato.append({
            **{k: r[k] for k in ("tuber", "center_frame", "second_frame", "ellipsoid_ml", "center_ml",
                                 "disagreement_ml", "disagreement_rank", "disagreement_flagged",
                                 "size_flagged", "fit_failure", "drainage_ml", "second_ml", "average_ml",
                                 "center_error_ml", "average_error_ml", "rescan_improvement_ml")},
            "disagreement_policy_error_ml": r["average_error_ml"] if tuber in flags["disagreement"] else r["center_error_ml"],
            "oracle_flagged": tuber in best["pair"],
        })
    save_csv(args.out / "per_potato.csv", per_potato)
    save_csv(args.out / "rescan_pairs.csv", [
        {"tuber_1": r["pair"][0], "tuber_2": r["pair"][1], "mae_ml": r["mae_ml"]} for r in pairs])
    save_json(results, {
        "frozen_selection_sha256": sha256(frozen_path), "outcomes_sha256": sha256(source),
        "n_potatoes": N, "budget": BUDGET,
        "failed_fits": {r["tuber"]: r["fit_failure"] for r in per_potato if r["fit_failure"]},
        "policies": policies, "disagreement_minus_baseline_mae_ml": differences,
        "all_three_baselines_beaten": all(v < 0 for v in differences.values()),
    })
    print(policies)
    print(differences)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("select", "evaluate"))
    parser.add_argument("--source", type=Path, default=Path("data/raw/3DPotatoTwin"))
    parser.add_argument("--out", type=Path, default=HERE / "corepp_volume_rescan")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"select": select, "evaluate": evaluate}[args.phase](args)


if __name__ == "__main__":
    main()
