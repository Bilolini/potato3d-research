"""Freeze the private roster and coarse target cues for the human prompt pilot."""

import argparse
from contextlib import ExitStack
import hashlib
from pathlib import Path
import sys

import numpy as np
from PIL import Image
from PIL import ImageDraw

STUDY = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY.parents[1]))
from studies.sam2_center_weight_v1 import run as base

PARENT = STUDY.parent / "sam2_pin_prompt_v1"
ORDER_SEED = "sam2-human-operator-order-v1/133"


def cue_for(rgb, target):
    y, x = np.nonzero(target)
    left, right, top, bottom = int(x.min()), int(x.max()), int(y.min()), int(y.max())
    mid_x = 24 * ((left + right + 24) // 48)
    mid_y = 24 * ((top + bottom + 24) // 48)
    candidates = [
        ((mid_x, bottom + 15), (0, -1), "below"),
        ((left - 15, mid_y), (1, 0), "left"),
        ((right + 15, mid_y), (-1, 0), "right"),
        ((mid_x, top - 15), (0, 1), "above"),
    ]
    height, width = target.shape
    valid = []
    for tip, (dx, dy), side in candidates:
        tx, ty = tip
        tail = (tx - 30 * dx, ty - 30 * dy)
        wing_a = (tx - 13 * dx - 8 * dy, ty - 13 * dy + 8 * dx)
        wing_b = (tx - 13 * dx + 8 * dy, ty - 13 * dy - 8 * dx)
        xs, ys = zip(tail, tip, wing_a, wing_b, strict=True)
        box = [min(xs) - 3, min(ys) - 3, max(xs) + 4, max(ys) + 4]
        xmin, ymin, xmax, ymax = box
        if xmin < 0 or ymin < 0 or xmax > width or ymax > height:
            continue
        if target[ymin:ymax, xmin:xmax].any():
            raise ValueError("A cue candidate overlaps the silhouette")
        brightness = float(np.quantile(rgb[ymin:ymax, xmin:xmax].mean(axis=2), .9))
        valid.append({
            "side": side, "lines": [[*tail, *tip], [*wing_a, *tip], [*wing_b, *tip]],
            "bounds_xyxy_exclusive_max": box, "patch_p90_rgb": brightness,
        })
    if not valid:
        raise ValueError("No target cue fits outside the annotated bounding box")
    return min(valid, key=lambda c: c["patch_p90_rgb"]), [left, top, right, bottom]


def freeze():
    manifest = base.load_manifest(base.STUDY)
    prior_path = PARENT / "frozen_clicks.json"
    prior = base.read_json(prior_path)
    target_rows = [(r["tuber"], r["entry_file"], r["center_file"]) for r in prior["clicks"]]
    current = [(r["tuber"], r["frames"][0]["rgb_member"], r["frames"][-1]["rgb_member"])
               for r in manifest["roster"]]
    if target_rows != current or len(current) != 40:
        raise ValueError("Entry and center roster does not match the 40 development potatoes")
    ordered = sorted(manifest["roster"],
                     key=lambda r: hashlib.sha256(f"{ORDER_SEED}/{r['tuber']}".encode()).hexdigest())
    trials = []
    with ExitStack() as stack:
        archives = base.open_image_archives(stack, manifest)
        for position, row in enumerate(ordered, 1):
            archive = archives[row["archive"]]
            entry = row["frames"][0]
            info = archive.getinfo(entry["rgb_member"])
            if f"{info.CRC:08x}" != entry["crc32"]:
                raise ValueError("An archived entry file changed")
            image = base.rgba_image(archive, info)
            rgb = np.ascontiguousarray(image[:, :, :3])
            alpha = image[:, :, 3] > 0
            cue, bbox = cue_for(rgb, alpha)
            trials.append({
                "trial": position, "tuber": row["tuber"], "archive": row["archive"],
                "entry_file": entry["rgb_member"], "entry_crc32": entry["crc32"],
                "center_file": row["frames"][-1]["rgb_member"],
                "width": image.shape[1], "height": image.shape[0],
                "rgb_pixels_sha256": hashlib.sha256(rgb).hexdigest(),
                "cue": cue, "private_target_bbox_xyxy": bbox,
            })
    frozen = {
        "schema": 1, "source": "development", "order_seed": ORDER_SEED,
        "protocol_sha256": base.hash_file(STUDY / "protocol.md"),
        "parent_frame_manifest_sha256": base.hash_file(base.STUDY / "frame_manifest.json"),
        "parent_pin_manifest_sha256": base.hash_file(prior_path),
        "prior_scores_sha256": base.hash_file(PARENT / "per_potato.csv"),
        "parent_scores_sha256": base.hash_file(base.STUDY / "per_potato.csv"),
        "parent_tracking_config_sha256": base.hash_file(base.STUDY / "tracking_config.json"),
        "pin_annotations_sha256": base.hash_file(base.DATA / "1_rgbd/pin_regions.json"),
        "trials": trials,
    }
    path = STUDY / "trial_manifest.json"
    if path.exists() and base.read_json(path) != frozen:
        raise ValueError("Existing trial manifest differs from the proposed stimuli")
    base.write_json(path, frozen)
    print(f"Prepared {len(trials)} trials. Manifest SHA-256 {base.hash_file(path)}")
    return frozen


def review(frozen, path):
    from PIL import ImageFont

    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 16)
    cells = (320, 205)
    sheet = Image.new("RGB", (cells[0]*5, cells[1]*8), "white")
    draw = ImageDraw.Draw(sheet)
    manifest = base.load_manifest(base.STUDY)
    with ExitStack() as stack:
        archives = base.open_image_archives(stack, manifest)
        for i, t in enumerate(frozen["trials"]):
            rgba = base.rgba_image(archives[t["archive"]], t["entry_file"])
            rgb = Image.fromarray(rgba[:, :, :3])
            marker = ImageDraw.Draw(rgb)
            for stroke in (6, 3):
                for line in t["cue"]["lines"]:
                    marker.line(line, fill="#161b16" if stroke == 6 else "#d7ff53", width=stroke)
            rgb.thumbnail((cells[0]-12, cells[1]-24))
            x, y = i % 5 * cells[0], i // 5 * cells[1]
            sheet.paste(rgb, (x + 6, y + 22))
            draw.text((x + 6, y + 2), f"{t['trial']:02}     {t['cue']['side']}", fill="#16211a", font=font)
    sheet.save(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, help="Write an offline check of the anonymous arrow placement")
    options = parser.parse_args()
    manifest = freeze()
    if options.review:
        review(manifest, options.review)
