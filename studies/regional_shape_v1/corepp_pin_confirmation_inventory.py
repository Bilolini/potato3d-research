"""Build the fresh CoRe++ inventory from release metadata and ZIP directories."""

import argparse
import ast
from collections import Counter, defaultdict, deque
import csv
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PROTOCOL = HERE / "corepp_pin_confirmation_protocol.md"
RELEASE_FILES = ("3_pair/ground_truth.csv", "3_pair/non-perfect.txt", "3_pair/tmatrix.zip", "1_rgbd/pin_regions.json")
SPLIT_FILES = ("data_preparation/make_splits.py", "data/potato/split.json")
EXCLUSIONS = {
    "demo": REPO / "data/demo_manifest.json",
    "development": HERE.parent / "real_lobes_v1/fresh_selection.json",
    "closed_replication": HERE / "replication_cohort.json",
    "closed_support_offset": HERE / "support_offset_confirmation_cohort.json",
}
ORDER_PREFIX = "corepp-pin-confirmation-v1/"
MAX_N = 36


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def save(path, data):
    with path.open("x") as f:
        json.dump(data, f, indent=2, allow_nan=False)
        f.write("\n")


def released_split(upstream, labels):
    source = ast.parse((upstream / SPLIT_FILES[0]).read_text())
    prefixes = {line.targets[0].id: tuple(ast.literal_eval(line.value)) for line in source.body
                if isinstance(line, ast.Assign) and isinstance(line.targets[0], ast.Name)
                and line.targets[0].id in ("val_split", "test_split")}
    assignments = {}
    for obj in labels:
        held_out = [k.removesuffix("_split") for k, p in prefixes.items() if obj.startswith(p)]
        if len(held_out) > 1:
            raise ValueError(f"{obj} occurs in more than one full split")
        assignments[obj] = held_out[0] if held_out else "train"
    if Counter(assignments.values()) != {"train": 237, "val": 51, "test": 51}:
        raise ValueError("Full split does not match the authors' published cohort sizes")
    return assignments, prefixes


def prior_objects():
    return {
        "demo": sorted(r["object_id"] for r in read(EXCLUSIONS["demo"])["objects"]),
        "development": sorted(r["object_id"] for r in read(EXCLUSIONS["development"])["pairs"]),
        **{name: sorted(r["label"] for r in read(EXCLUSIONS[name]))
           for name in ("closed_replication", "closed_support_offset")},
    }


def archive_members(source):
    members = {}
    for path in sorted((source / "1_rgbd/1_images").glob("*.zip")):
        with ZipFile(path) as z:
            for i in z.infolist():
                if i.filename.endswith(".png"):
                    if i.filename in members:
                        raise ValueError(f"Duplicated RGB-D ZIP member {i.filename}")
                    members[i.filename] = {"archive": path.relative_to(source).as_posix(),
                                           "member": i.filename, "bytes": i.file_size, "crc32": f"{i.CRC:08x}"}
    return members


def candidate(meta, z, records, images, annotations):
    obj = meta["label"]
    registration_member = f"tmatrix/{obj}.json"
    try:
        raw = z.read(registration_member)
    except KeyError:
        return {"state": "missing_registration"}
    registration = json.loads(raw)
    point = Path(registration["rgbd_pcd_file"])
    match = re.fullmatch(re.escape(obj) + r"_pcd_(\d+)\.ply", point.name)
    if not match or point.parent.name != obj or Path(registration["sfm_mesh_file"]).stem != obj:
        return {"state": "invalid_registration_identity"}
    frame = match[1]
    rgb, depth = (f"{obj}/{obj}_{kind}_{frame}.png" for kind in ("rgb", "depth"))
    if rgb not in records or depth not in records:
        return {"state": "missing_rgbd_member", "frame": frame}
    labels = annotations.get(images.get(rgb), [])
    if len(labels) != 1 or len(labels[0].get("segmentation", [])) != 1:
        return {"state": "missing_unique_polygon", "frame": frame}
    contour, = labels[0]["segmentation"]
    if not isinstance(contour, list) or len(contour) < 6 or len(contour) % 2:
        return {"state": "invalid_polygon", "frame": frame}
    return {"state": "eligible", "frame": frame, "annotation": labels[0],
            "registration_member": registration_member, "registration_sha256": hashlib.sha256(raw).hexdigest(),
            "rgb": records[rgb], "depth": records[depth]}


def order_key(value):
    return hashlib.sha256((ORDER_PREFIX + value).encode()).hexdigest()


def roster(rows):
    grouped = defaultdict(list)
    for row in rows:
        if row["state"] == "eligible" and row["model_split"] == "test":
            grouped[row["group"]].append(row)
    queues = [deque(sorted(grouped[group], key=lambda r: order_key(r["tuber"])))
              for group in sorted(grouped, key=order_key)]
    selected = []
    while len(selected) < MAX_N and any(queues):
        for queue in queues:
            if queue and len(selected) < MAX_N:
                selected.append(queue.popleft())
    return selected


def run(source, upstream, out):
    metadata = [source / name for name in RELEASE_FILES]
    input_hashes = {name: sha(path) for name, path in zip(RELEASE_FILES, metadata, strict=True)}
    if len(list((source / "1_rgbd/1_images").glob("*.zip"))) != 6:
        raise ValueError("Expected all six RGB-D image archives")
    with metadata[0].open(newline="") as f:
        traits = list(csv.DictReader(f))
    model_split, prefixes = released_split(upstream, [t["label"] for t in traits])
    demo_split = read(upstream / SPLIT_FILES[1])
    provenance = {name: sha(upstream / name) for name in SPLIT_FILES}
    image_data = read(metadata[3])
    images = {im["file_name"]: im["id"] for im in image_data["images"]}
    annotations = defaultdict(list)
    for entry in image_data["annotations"]:
        annotations[entry["image_id"]].append(entry)
    previous = prior_objects()
    warned = {line.split("#", 1)[0].strip().split()[0] for line in metadata[1].read_text().splitlines()
              if line.split("#", 1)[0].strip()}
    if "2R306" in warned:
        warned.add("2R3-6")
    members = archive_members(source)
    rows = []
    with ZipFile(metadata[2]) as z:
        for obj in traits:
            name = obj["label"]
            excluded = [reason for reason, ids in previous.items() if name in ids]
            row = {"tuber": name, "cultivar": obj["cultivar"], "group": obj["ros_bag_name"],
                   "model_split": model_split[name], "dataset_exp_split": obj["exp_split"]}
            if excluded:
                row.update(state="previously_studied", exclusion_sources=excluded)
            elif name in warned:
                row.update(state="registration_warning")
            else:
                row.update(candidate(obj, z, members, images, annotations))
            rows.append(row)
    chosen = roster(rows)
    eligible = [r for r in rows if r["state"] == "eligible"]
    availability = Counter((r["cultivar"], r["group"], r["model_split"]) for r in eligible)
    counts = [{"cultivar": c, "group": g, "model_split": s, "eligible": n}
              for (c, g, s), n in sorted(availability.items())]
    out.mkdir(parents=True, exist_ok=True)
    save(out / "inventory.json", {
        "metadata_sha256": input_hashes, "upstream_split_sha256": provenance,
        "full_model_split_counts": dict(Counter(model_split.values())), "full_split_prefixes": prefixes,
        "example_demo_split": demo_split, "prior_objects_by_source": previous,
        "prior_roster_sha256": {k: sha(v) for k, v in EXCLUSIONS.items()},
        "registration_warning_ids": sorted(warned), "availability": counts, "objects": rows,
    })
    save(out / "roster.json", {
        "stage": "metadata_only_before_input_opening", "inventory_sha256": sha(out / "inventory.json"),
        "protocol_sha256": sha(PROTOCOL), "selection_source_sha256": sha(Path(__file__)),
        "limit": MAX_N, "order_prefix": ORDER_PREFIX, "frames": chosen,
    })
    print("Published split", Counter(model_split.values()))
    print("Eligibility states", Counter(r["state"] for r in rows))
    print("Fresh eligibility by cultivar and model split", Counter((r["cultivar"], r["model_split"]) for r in eligible))
    print("Frozen selection by cultivar and acquisition group", Counter((r["cultivar"], r["group"]) for r in chosen))
    print("Roster SHA-256", sha(out / "roster.json"))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "upstream", "out-dir"):
        p.add_argument(f"--{name}", type=Path, required=True)
    args = p.parse_args()
    run(args.source, args.upstream, args.out_dir)
