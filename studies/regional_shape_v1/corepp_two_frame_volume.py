"""Run the frozen development-only comparison of CoRe++ frame volumes."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
from itertools import batched
import math
import multiprocessing
from pathlib import Path
import platform
import re
from statistics import mean, median
from time import perf_counter, process_time
from zipfile import ZipFile

import cv2 as cv
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import torch

from . import corepp_pin_confirmation as cpu
from . import corepp_pin_multituber as multi
from . import corepp_rescan_screen as rescan
from .corepp_pin_multituber import audit, pilot

PROTOCOL = Path(__file__).with_name("corepp_two_frame_volume_protocol.md")
MEMBER = re.compile(r"(?P<tuber>[^/]+)/(?P=tuber)_(?P<role>rgb|depth)_(?P<frame>[0-9]+)\.png")
EXPECTED_ERRORS = (*cpu.EXPECTED_FAILURES, TypeError)
TIE_ML = 1e-8


def code_hashes():
    return rescan.code_hashes() | {
        PROTOCOL.name: audit.sha256(PROTOCOL), Path(__file__).name: audit.sha256(Path(__file__)),
        Path(rescan.__file__).name: audit.sha256(Path(rescan.__file__)),
    }


def image_pairs(source):
    members = {tuber: {} for tuber in multi.EXPECTED}
    for path in sorted((source / "1_rgbd/1_images").glob("*.zip")):
        with ZipFile(path) as archive:
            for entry in archive.infolist():
                if entry.filename.partition("/")[0] not in members:
                    continue
                match = MEMBER.fullmatch(entry.filename)
                if match is None:
                    continue
                pair = members[match["tuber"]].setdefault(int(match["frame"]), {})
                role = match["role"]
                if role in pair:
                    raise ValueError(f"Duplicate {role} for {entry.filename}")
                pair[role] = {"archive": str(path.relative_to(source)), "member": entry.filename,
                              "crc32": entry.CRC, "bytes": entry.file_size}
    return members


def freeze(args):
    hashes, archive_frames = rescan.archive()
    runtime = multi.Runtime(args)
    target = args.source / "3_pair/ground_truth.csv"
    target_hash = audit.sha256(target)
    recorded_hash = audit.read_json(multi.ROSTER)["metadata_sha256"]["ground_truth.csv"]
    if target_hash != recorded_hash:
        raise ValueError("Drainage source differs from archived release")
    reference = {}
    with target.open(newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), 2):
            tuber = row["label"]
            if tuber not in multi.EXPECTED:
                continue
            volume = float(row["volume_ml"])
            if tuber in reference or not math.isfinite(volume) or volume <= 0:
                raise ValueError(f"Duplicate or invalid drainage measurement for {tuber}")
            reference[tuber] = {"csv_line": line, "volume_ml": volume, "release_value": row["volume_ml"]}
    if reference.keys() != multi.EXPECTED.keys():
        raise ValueError(f"Missing drainage IDs: {sorted(set(multi.EXPECTED) - reference.keys())}")
    members = image_pairs(args.source)
    frames = []
    for archived, _ in archive_frames:
        tuber, center = archived["tuber"], archived["frame"]
        complete = sorted(i for i, pair in members[tuber].items() if pair.keys() == {"rgb", "depth"})
        index = (len(complete) - 1) // 4 if complete else None
        second = complete[index] if index is not None else None
        if int(center) not in complete:
            raise ValueError(f"Archived center is absent from the complete release pairs for {tuber}")
        frames.append({
            "tuber": tuber, "frame": center, "complete_suffixes": complete, "second_index": index,
            "second_frame": second, "second_members": members[tuber].get(second),
            "center_raw_sha256": {role: audit.sha256(path) for role, path in
                                  rescan.files_for(archived, args.input_dir).items()},
        })
    target_record = {"release_file": "3_pair/ground_truth.csv", "source_sha256": target_hash,
                     "field": "volume_ml", "join_key": "label", "method": "water displacement",
                     "by_tuber": reference}
    pilot.put_json(args.out_dir / "drainage_reference.json", target_record)
    pilot.put_json(args.out_dir / "frozen_protocol.json", {
        "stage": "frozen_before_inference_and_volume_errors", "frames": frames,
        "archived_grid_and_replay_sha256": hashes, "code_sha256": code_hashes(),
        "reference_sha256": audit.sha256(args.out_dir / "drainage_reference.json"),
        "cpu_runtime_provenance": runtime.provenance_record, "seeds": list(pilot.SEEDS), "tie_ml": TIE_ML,
    })
    for row in frames:
        print(row["tuber"], row["frame"], row["second_frame"], row["second_index"], len(row["complete_suffixes"]))
    print("Froze ten complete IDs and ten drainage references.", flush=True)


def frozen_inputs(args):
    frozen = audit.read_json(args.out_dir / "frozen_protocol.json")
    hashes, archive_frames = rescan.archive()
    if (frozen["code_sha256"] != code_hashes() or frozen["archived_grid_and_replay_sha256"] != hashes or
            [(r["tuber"], r["frame"]) for r in frozen["frames"]] !=
            [(r["tuber"], r["frame"]) for r, _ in archive_frames]):
        raise ValueError("Code, protocol, grid or roster changed after freeze")
    return frozen, archive_frames


def extract_second(source, members, temp):
    if members is None:
        raise ValueError("No complete RGB/depth pair")
    paths = {}
    for role, expected in members.items():
        with ZipFile(source / expected["archive"]) as archive:
            member = archive.getinfo(expected["member"])
            if member.CRC != expected["crc32"] or member.file_size != expected["bytes"]:
                raise ValueError(f"Frozen archive member changed: {member.filename}")
            paths[role] = temp / f"{role}.png"
            paths[role].write_bytes(archive.read(member))
    return paths


def prepare(paths, runtime):
    # As in the audited release pipeline, use the alpha and depth filters before padding.
    with Image.open(paths["rgb"]) as image:
        rgba = np.array(image)
    raw = cv.imread(str(paths["depth"]), cv.IMREAD_UNCHANGED)
    if rgba.ndim != 3 or rgba.shape[2] != 4 or raw is None or raw.shape != rgba.shape[:2]:
        raise ValueError("Unexpected RGB-D input shape")
    depth, alpha = raw.astype(np.float32), rgba[..., 3] // 255
    preprocess, histogram, pad_cls, _ = runtime.preprocessor
    pilot.set_rng(pilot.SEEDS[0])
    low, high = histogram(depth, alpha, 50, 0.05)
    valid = (alpha > 0) & (depth > 0) & (depth >= low) & (depth <= high)
    if not valid.any():
        raise ValueError("No valid foreground depth")
    color, masked_depth, mask, origin, *_ = preprocess(
        rgba[..., :3].copy(), depth.copy(), alpha, str(runtime.camera), runtime.cfg["detection_input"])
    row, col = map(int, origin)
    height, width = mask.shape
    np.testing.assert_array_equal(mask.astype(bool), valid[row:row+height, col:col+width])
    normalized = (masked_depth - runtime.cfg["depth_min"]) / (runtime.cfg["depth_max"] - runtime.cfg["depth_min"])
    normalized[masked_depth == 0] = 0
    pad = pad_cls(size=runtime.cfg["input_size"])
    rgb = np.array(pad(color))
    tensor = torch.cat((torch.from_numpy(rgb).permute(2, 0, 1).float() / 255,
                        torch.from_numpy(np.array(pad(normalized))).unsqueeze(0).float())).unsqueeze(0)
    if tensor.shape != (1, 4, 304, 304) or not torch.isfinite(tensor).all():
        raise ValueError("Invalid model tensor")
    return tensor, rgb, {"crop_origin_row_col": [row, col], "crop_height_width": [height, width],
                         "depth_filter_mm": [float(low), float(high)], "valid_pixels": int(mask.sum())}


def predict_frame(job):
    # Drainage values are never loaded into the prediction process.
    from tempfile import TemporaryDirectory

    args, frame, interior, expanded = job
    out = args.out_dir / "crops" / frame["tuber"]
    out.mkdir(parents=True, exist_ok=True)
    records = {}
    for role in ("center", "second"):
        record = {"seeds": [], "failures": [], "median_volume_ml": None}
        records[role] = record
        start = process_time()
        try:
            with TemporaryDirectory() as temp:
                if role == "center":
                    paths = rescan.files_for(frame, args.input_dir)
                else:
                    paths = extract_second(args.source, frame["second_members"], Path(temp))
                raw_hashes = {k: audit.sha256(p) for k, p in paths.items()}
                if role == "center" and raw_hashes != frame["center_raw_sha256"]:
                    raise ValueError("Raw center hash changed")
                tensor, rgb, trace = prepare(paths, rescan.MODEL.runtime)
            record.update(raw_sha256=raw_hashes, trace=trace)
        except EXPECTED_ERRORS as exc:
            record["failures"].append({"stage": "input", "detail": f"{type(exc).__name__}: {exc}"})
            record["cpu_seconds"] = process_time() - start
            continue
        prep_cpu = process_time() - start
        Image.fromarray(rgb).save(out / f"{role}.png")
        start = process_time()
        for seed, check, old in zip(pilot.SEEDS, interior["seeds"], expanded["pairs"], strict=True):
            try:
                result = rescan.MODEL.predict(tensor, seed)
                if result["mesh_failure"]:
                    raise ValueError(result["mesh_failure"])
                if role == "center":
                    if seed != check["seed"] or seed != old["seed"]:
                        raise ValueError("Archived seed order changed")
                    rescan.verify_native(result, check["conditions"]["original"], old["expanded_grid"]["original"])
                record["seeds"].append({
                    "seed": seed, "volume_ml": result["volume_ml"], "boundary": result["boundary"],
                    "hashes": result["hashes"], "archive_replay_passed": role == "center",
                })
            except EXPECTED_ERRORS as exc:
                record["failures"].append({"stage": "prediction", "seed": seed,
                                           "detail": f"{type(exc).__name__}: {exc}"})
        record["cpu_seconds"] = prep_cpu + process_time() - start
        if len(record["seeds"]) == len(pilot.SEEDS):
            record["median_volume_ml"] = median(r["volume_ml"] for r in record["seeds"])
    return {"tuber": frame["tuber"], "center_frame": frame["frame"], "second_frame": frame["second_frame"],
            "second_index": frame["second_index"], "complete_pairs": len(frame["complete_suffixes"]), **records}


def contact_sheets(folder, records):
    font = ImageFont.load_default(size=18)
    title = ImageFont.load_default(size=24)
    for page, rows in enumerate(batched(records, 5), 1):
        sheet = Image.new("RGB", (1032, 764), "#f6f3ea")
        draw = ImageDraw.Draw(sheet)
        draw.text((20, 15), "Two conveyor frames per potato", font=title, fill="#202321")
        draw.text((20, 46), "Model RGB inputs at the same scale. Physical viewing angles are unverified.",
                  font=font, fill="#303a32")
        for i, row in enumerate(rows):
            x, y = 20 + 337 * (i % 3), 92 + 327 * (i // 3)
            draw.text((x, y), row["tuber"], font=title, fill="#202321")
            for j, role in enumerate(("center", "second")):
                left = x + 160 * j
                draw.text((left, y+32), f"{role.title()} {row[f'{role}_frame']}", font=font, fill="#303a32")
                path = folder / "crops" / row["tuber"] / f"{role}.png"
                if path.is_file():
                    with Image.open(path) as img:
                        sheet.paste(img.resize((152, 152), Image.Resampling.LANCZOS), (left, y+57))
                else:
                    draw.text((left, y+57), "Crop unavailable", font=font, fill="#303a32")
        sheet.crop((0, 0, 1032, 656)).save(folder / f"paired_crops_{page}.png")


def predict(args):
    start = perf_counter()
    output = args.out_dir / "frame_predictions.json"
    if output.exists():
        raise FileExistsError(output)
    frozen, archived = frozen_inputs(args)
    jobs = [(args, row, a, b) for row, (a, b) in zip(frozen["frames"], archived, strict=True)]
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn"),
                             initializer=rescan.initialize, initargs=(args, frozen["cpu_runtime_provenance"])) as pool:
        records = []
        for record in pool.map(predict_frame, jobs):
            records.append(record)
            counts = [len(record[role]["seeds"]) for role in ("center", "second")]
            print(f"{record['tuber']}: {counts[0]} center replays, {counts[1]} second predictions", flush=True)
    wall = perf_counter() - start
    contact_sheets(args.out_dir, records)
    pilot.put_json(output, {
        "frozen_protocol_sha256": audit.sha256(args.out_dir / "frozen_protocol.json"),
        "stage": "predictions_saved_before_reference_join", "platform": platform.platform(), "workers": args.workers,
        "batch_wall_seconds": wall, "records": records,
    })


def compare(values):
    return {"n": len(values), "mean_change_ml": mean(values) if values else None,
            "median_change_ml": median(values) if values else None,
            "wins": sum(v < -TIE_ML for v in values), "ties": sum(abs(v) <= TIE_ML for v in values),
            "losses": sum(v > TIE_ML for v in values)}


def evaluate(args):
    frozen, _ = frozen_inputs(args)
    folder = args.out_dir
    output = folder / "results.json"
    if output.exists():
        raise FileExistsError(output)
    predictions = audit.read_json(folder / "frame_predictions.json")
    reference_path = folder / "drainage_reference.json"
    if (predictions["stage"] != "predictions_saved_before_reference_join" or
            predictions["frozen_protocol_sha256"] != audit.sha256(folder / "frozen_protocol.json") or
            frozen["reference_sha256"] != audit.sha256(reference_path)):
        raise ValueError("Staged inputs changed before evaluating")
    reference = audit.read_json(reference_path)["by_tuber"]
    rows = []
    for record, frame in zip(predictions["records"], frozen["frames"], strict=True):
        tuber = record["tuber"]
        if (tuber, record["center_frame"], record["second_frame"]) != (frame["tuber"], frame["frame"], frame["second_frame"]):
            raise ValueError("Prediction frame identity differs from the frozen frame")
        target = reference[tuber]["volume_ml"]
        center, second = (record[role]["median_volume_ml"] for role in ("center", "second"))
        average = mean((center, second)) if center is not None and second is not None else None
        center_error, second_error, average_error = (abs(v - target) if v is not None else None
                                                      for v in (center, second, average))
        rows.append({
            **{k: record[k] for k in ("tuber", "center_frame", "second_frame", "second_index", "complete_pairs")},
            "drainage_ml": target, "center_ml": center, "second_ml": second, "average_ml": average,
            "center_error_ml": center_error, "second_error_ml": second_error, "average_error_ml": average_error,
            "average_minus_center_error_ml": average_error - center_error if average is not None else None,
            "second_minus_center_error_ml": second_error - center_error if average is not None else None,
            "average_minus_second_error_ml": average_error - second_error if average is not None else None,
            "center_replays_passed": len(record["center"]["seeds"]), "second_seed_count": len(record["second"]["seeds"]),
            **{f"{role}_mesh_boundary_contacts": sum(bool(r["boundary"]["mesh_faces_touched"]) for r in record[role]["seeds"])
               for role in ("center", "second")},
            **{f"{role}_cpu_seconds": record[role]["cpu_seconds"] for role in ("center", "second")},
            "failures": " | ".join(f"{role} {f.get('seed', '')} {f['stage']}: {f['detail']}"
                                   for role in ("center", "second") for f in record[role]["failures"]),
        })
    complete = [r for r in rows if r["average_ml"] is not None]
    rescan.write_table(folder / "per_potato.csv", rows)
    result = {
        "n_selected": len(rows), "n_complete": len(complete), "failed_tubers": [r["tuber"] for r in rows if r["failures"]],
        "center_replays_passed": sum(r["center_replays_passed"] for r in rows),
        "second_predictions_passed": sum(r["second_seed_count"] for r in rows),
        "mean_absolute_error_ml": {role: mean(r[f"{role}_error_ml"] for r in complete) if complete else None
                                   for role in ("center", "second", "average")},
        "paired_comparisons": {key: compare([r[key] for r in complete]) for key in (
            "average_minus_center_error_ml", "second_minus_center_error_ml", "average_minus_second_error_ml")},
        "total_center_replay_cpu_seconds": sum(r["center_cpu_seconds"] for r in rows),
        "total_additional_second_frame_cpu_seconds": sum(r["second_cpu_seconds"] for r in rows),
        "batch_wall_seconds": predictions["batch_wall_seconds"],
        "prediction_sha256": audit.sha256(folder / "frame_predictions.json"), "reference_sha256": frozen["reference_sha256"],
    }
    pilot.put_json(output, result)
    print(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "predict", "evaluate"))
    for name in ("source", "upstream", "released", "input-dir", "out-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    {"freeze": freeze, "predict": predict, "evaluate": evaluate}[args.phase](args)


if __name__ == "__main__":
    main()
