"""Stage and screen the selected fresh 3DPotatoTwin development pairs."""
import argparse
import csv
import json
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import numpy as np

from potato3d.io import discover_demo, load_demo_pair, safe_path, sha256, write_json
from audit import reference_heights
from intake import INTRINSICS, build_manifest
from pilot import observed_grid
from screen import RULES, run_pair

HERE = Path(__file__).resolve().parent
METADATA = {
    "tmatrix.zip": "3_pair/tmatrix.zip",
    "non-perfect.txt": "3_pair/non-perfect.txt",
    "ground_truth.csv": "3_pair/ground_truth.csv",
    "pin_regions.json": "1_rgbd/pin_regions.json",
    Path(INTRINSICS).name: INTRINSICS,
}
OVERLAP_RULE = {"minimum_fraction": .9, "maximum_median_mm": 2., "maximum_p95_mm": 5.}


def stage(source, root, selection):
    for name, path in METADATA.items():
        if sha256(safe_path(source, path)) != selection["metadata_sha256"][name]:
            raise ValueError(f"Release metadata differs from selection: {path}")
    with (HERE / "fresh_download_members.tsv").open(newline="") as handle:
        members = {(row["tuber_id"], row["member_basename"]): row
                   for row in csv.DictReader(handle, delimiter="\t")}
    with ExitStack() as stack:
        archives = {}

        def copy_member(archive, member, target, size=None):
            if archive not in archives:
                archives[archive] = stack.enter_context(ZipFile(safe_path(source, archive)))
            info = archives[archive].getinfo(member)
            if size is not None and info.file_size != size:
                raise ValueError(f"Unexpected member size: {archive}/{member}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archives[archive].read(info))

        for pair in selection["pairs"]:
            obj = pair["object_id"]
            for target in [pair["partial"], pair["reference"],
                           f"1_rgbd/1_image/{obj}/{pair['rgb']}",
                           f"1_rgbd/1_image/{obj}/{pair['depth']}"]:
                entry = members[obj, Path(target).name]
                copy_member(entry["archive"], entry["member_path"], root / target,
                            int(entry["uncompressed_bytes"]))
            member = pair["registration_member"]
            copy_member(METADATA["tmatrix.zip"], member, root / "3_pair" / member)
    for target, source_path in [("ground_truth.csv", METADATA["ground_truth.csv"]),
                                ("3_pair/non-perfect.txt", METADATA["non-perfect.txt"]),
                                (INTRINSICS, INTRINSICS)]:
        path = root / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(safe_path(source, source_path).read_bytes())


def pin_ellipses(coco, filename):
    image_id, = [image["id"] for image in coco["images"] if image["file_name"] == filename]
    ellipses = []
    for annotation in coco["annotations"]:
        if annotation["image_id"] == image_id:
            x, y, width, height = annotation["bbox"]
            # Circumscribe the full published rectangle before applying the screen's buffer.
            ellipses.append([x+width/2, y+height/2, width/np.sqrt(2), height/np.sqrt(2)])
    if not ellipses:
        raise ValueError(f"No released pin annotation for {filename}")
    return ellipses


def registration_overlap(root, record):
    points, reference, _ = load_demo_pair(root, record, belt_depth_mm=350)
    xy, depth, height = observed_grid(points)
    interior = (depth >= 9) & np.isfinite(height)
    upper = reference_heights(reference, xy[interior])[0][:, 1]
    usable = np.isfinite(upper)
    error = np.abs(upper[usable]-height[interior][usable])
    coverage = float(usable.mean()) if len(usable) else 0.
    median, p95 = np.percentile(error, [50, 95]) if len(error) else (None, None)
    passes = (coverage >= OVERLAP_RULE["minimum_fraction"] and median is not None
              and median <= OVERLAP_RULE["maximum_median_mm"]
              and p95 <= OVERLAP_RULE["maximum_p95_mm"])
    return {"interior_grid_rays": len(usable), "paired_fraction": coverage,
            "median_abs_top_difference_mm": median, "p95_abs_top_difference_mm": p95,
            "passes": passes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    selection = json.loads((HERE / "fresh_selection.json").read_text())
    with TemporaryDirectory(prefix="potato-fresh-", dir=args.source.parent) as tmp:
        root = Path(tmp)
        stage(args.source, root, selection)
        intake = build_manifest(root, allow_demo=False)
        rows = discover_demo(root)
        camera = json.loads((root / INTRINSICS).read_text())
        matrix = np.asarray(camera["intrinsic_matrix"]).reshape(3, 3, order="F")
        coco = json.loads(safe_path(args.source, METADATA["pin_regions.json"]).read_text())
        results = []
        for row in rows:
            obj, frame = row["object_id"], row["frame_id"]
            overlap = registration_overlap(root, row)
            ellipses = pin_ellipses(coco, f"{obj}/{obj}_rgb_{frame}.png")
            screened = run_pair(root, row, matrix, ellipses) if overlap["passes"] else None
            results.append({"object_id": obj, "frame_id": frame, "registration_overlap": overlap,
                            "pin_ellipses": ellipses, "screen": screened})
        write_json(args.out, {"stage": "fresh_development", "selection_sha256": sha256(HERE / "fresh_selection.json"),
                              "intake": intake, "overlap_rule": OVERLAP_RULE, "screen_rules": RULES,
                              "pairs": results})


if __name__ == "__main__":
    main()
