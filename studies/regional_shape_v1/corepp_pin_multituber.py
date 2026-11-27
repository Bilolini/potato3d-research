"""Frozen RGB interventions and paired CPU scoring on the ten development frames."""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import cv2 as cv
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_erosion, distance_transform_edt
import torch

from . import corepp_pin_pilot as pilot
from .corepp_pin_pilot import audit


HERE = audit.HERE
PROTOCOL = HERE / "corepp_pin_multituber_protocol.md"
PILOT = HERE / "corepp_pin_pilot"
ROSTER = audit.DEV / "fresh_selection.json"
ARCHIVED = HERE / "results.json"
MEMBERS = audit.DEV / "fresh_download_members.tsv"
EDIT_NAMES = ("pin", "peel1", "peel2", "peel3")
CONDITIONS = ("original", *EDIT_NAMES)
COLORS = ((50, 226, 255), (255, 189, 41), (248, 129, 235), (116, 250, 114))
EXPECTED = {
    "5R1-4": "362", "5R3-1": "360", "2R2-6": "358", "2R3-10": "363", "R4-10": "352",
    "R8-2": "350", "R10-1": "362", "R12-7": "353", "3R2-10": "367", "3R5-2": "359",
}


class Runtime(pilot.Pilot):
    """Use the pilot's preprocessing and inference with independently bound RGB-D paths."""

    def __init__(self, args):
        sys.path.insert(0, str(args.upstream.resolve()))
        from dataloaders.cameralaser_w_masks import MaskedCameraLaserData, histogram_filtering
        from dataloaders.transforms import Pad, get_padding
        from deepsdf.networks.deep_sdf_decoder import Decoder
        from networks.models import EncoderBigPooled
        from networks.utils import load_without_parallel, set_require_grad
        from sdfrenderer.grid import Grid3D
        from utils import sdf2mesh_cuda

        saved = audit.read_json(pilot.AUDIT)
        replay = audit.read_json(PILOT / pilot.NOOP)
        for base, hashes in ((args.upstream, saved["upstream_file_sha256"]),
                             (args.released, saved["released_config_sha256"]),
                             (args.released, saved["checkpoint_sha256"])):
            if any(audit.sha256(base / filename) != sha for filename, sha in hashes.items()):
                raise ValueError("A pinned upstream source, config, or checkpoint changed")
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        cv.setNumThreads(1)
        self.camera = args.upstream / "data/potato_example/realsense/intrinsic.json"
        self.cfg = audit.read_json(args.released / "super3d_32.json")
        specs = audit.read_json(args.released / "specs.json")
        self.preprocessor = (MaskedCameraLaserData.preprocess_images, histogram_filtering, Pad, get_padding)
        self.mesh_builder = sdf2mesh_cuda
        self.box = replay["grid_bbox_m"]
        self.grid = Grid3D(self.cfg["grid_density"], "cpu", torch.float32, bbox=self.box).points.detach()
        self.grid_sha = audit.array_sha256(self.grid.numpy())
        if self.grid_sha != replay["grid_sha256"]:
            raise ValueError("Grid does not reproduce the one-frame pilot")
        grid = self.grid.numpy()
        self.faces = {
            axis + side: grid[:, i] == extreme(grid[:, i])
            for i, axis in enumerate("xyz") for side, extreme in (("min", np.min), ("max", np.max))
        }
        self.modes = tuple(replay["model_training_modes"][k] for k in ("encoder", "decoder"))
        self.provenance_record = {
            "study_code_sha256": audit.sha256(Path(__file__)), "pilot_code_sha256": audit.sha256(Path(pilot.__file__)),
            "protocol_sha256": audit.sha256(PROTOCOL), "cpu_audit_sha256": audit.sha256(pilot.AUDIT),
            "checkpoint_sha256": saved["checkpoint_sha256"],
            "pilot_no_op_sha256": audit.sha256(PILOT / pilot.NOOP), "grid_sha256": self.grid_sha,
            "grid_bbox_m": self.box, "grid_points": len(grid), "model_training_modes": dict(zip(("encoder", "decoder"), self.modes)),
            "cpu_threads": 1, "seeds": list(pilot.SEEDS), "surface_points_per_direction": 20000,
            "surface_sampling_seed": audit.CPU_SEED,
        }

        if args.phase in ("noop", "score"):
            decoder = Decoder(specs["CodeLength"], **specs["NetworkSpecs"]).cpu()
            pretrain = torch.load(args.released / "500.pth", map_location="cpu", weights_only=True)
            decoder.load_state_dict(load_without_parallel(pretrain), strict=True)
            set_require_grad(decoder, False)
            pilot.set_rng(audit.CPU_SEED)
            encoder = EncoderBigPooled(4, specs["CodeLength"], self.cfg["input_size"]).cpu()
            joint = torch.load(args.released / self.cfg["checkpoint_file"], map_location="cpu", weights_only=True)
            encoder.load_state_dict(joint["encoder_state_dict"], strict=True)
            decoder.load_state_dict(joint["decoder_state_dict"], strict=True)
            self.encoder, self.decoder = encoder, decoder
            self.models = (self.encoder, self.decoder)
            self.states = [{k: v.detach().clone() for k, v in model.state_dict().items()} for model in self.models]

    def bind(self, folder, annotation):
        self.paths = {"rgb": folder / "original_rgba.png", "depth": folder / "depth.png"}
        self.pin = annotation

    def boundary(self, run):
        inside = run["sdf"].ravel() < 0
        contact = np.logical_or.reduce(list(self.faces.values()))
        result = {
            "inside_on_any_grid_face": int((inside & contact).sum()),
            "inside_by_grid_face": {name: int((inside & indices).sum()) for name, indices in self.faces.items()},
            "mesh_faces_touched": None,
        }
        if run["mesh"] is not None:
            vertices = np.asarray(run["mesh"].vertices)
            grid = self.grid.numpy()
            result["mesh_faces_touched"] = [
                axis + side for i, axis in enumerate("xyz")
                for side, extreme in (("min", np.min), ("max", np.max))
                if np.any(np.abs(vertices[:, i] - extreme(grid[:, i])) <= 1e-7)
            ]
        return result

    def run(self, path, seed):
        result = self.infer(path, seed)
        if any(not np.isfinite(result[k]).all() for k in ("tensor", "latent", "sdf")):
            result.update(mesh=None, volume_ml=None, mesh_failure="Non-finite tensor, latent or SDF")
        if result["mesh"] is not None:
            mesh = result["mesh"]
            if (not np.isfinite(np.asarray(mesh.vertices)).all() or
                    not np.isfinite(result["volume_ml"]) or result["volume_ml"] <= 0):
                result.update(mesh=None, volume_ml=None, mesh_failure="Non-finite geometry or nonpositive volume")
        return result


class Release:
    def __init__(self, source):
        self.source = source
        selection = audit.read_json(ROSTER)
        self.pairs = [r for r in selection["pairs"] if r["object_id"] not in (audit.OBJECT, pilot.DONOR)]
        if len(self.pairs) != len(EXPECTED) or {r["object_id"]: r["frame"] for r in self.pairs} != EXPECTED:
            raise ValueError("The registered development roster does not match the ten fixed frames")
        for relative in (audit.PIN_LABELS, audit.INPUT_INTRINSICS, audit.MATRIX_ARCHIVE):
            path = source / relative
            if audit.sha256(path) != selection["metadata_sha256"][path.name]:
                raise ValueError(f"Development release metadata changed: {relative}")
        labels = audit.read_json(source / audit.PIN_LABELS)
        self.images = {row["file_name"]: row["id"] for row in labels["images"]}
        self.annotations = {}
        for row in labels["annotations"]:
            self.annotations.setdefault(row["image_id"], []).append(row)
        with MEMBERS.open(newline="") as f:
            self.members = {(r["tuber_id"], r["member_basename"]): r for r in csv.DictReader(f, delimiter="\t")}
        self.archived = {r["object_id"]: r["files"] for r in audit.read_json(ARCHIVED)["intake"]["pairs"]}

    def extract(self, pair, folder):
        obj, frame = pair["object_id"], pair["frame"]
        archived = self.archived[obj]
        with ZipFile(self.source / audit.MATRIX_ARCHIVE) as z:
            reg = z.read(pair["registration_member"])
        record = json.loads(reg)
        if (hashlib.sha256(reg).hexdigest() != archived["registration"]["sha256"] or
                record["rgbd_pcd_file"] != pair["partial"] or record["sfm_mesh_file"] != pair["reference"]):
            raise ValueError("Registration no longer identifies the archived pair")
        folder.mkdir()
        for role, dest in (("rgb", "original_rgba.png"), ("depth", "depth.png")):
            filename = f"{obj}_{role}_{frame}.png"
            if pair[role] != filename:
                raise ValueError(f"Expected registered {role} file {filename}")
            member = self.members[obj, filename]
            with ZipFile(self.source / member["archive"]) as z:
                data = z.read(member["member_path"])
            if len(data) != int(member["uncompressed_bytes"]) or hashlib.sha256(data).hexdigest() != archived[role]["sha256"]:
                raise ValueError(f"Released {role} does not match the archived selection")
            (folder / dest).write_bytes(data)
        annotation, = self.annotations[self.images[f"{obj}/{pair['rgb']}"]]
        return annotation, archived["registration"]["sha256"]


def hsv(rgb):
    return cv.cvtColor(np.asarray(rgb, dtype=np.float32).reshape(1, -1, 3) / 255, cv.COLOR_RGB2HSV)[0]


def donors():
    prior = audit.read_json(PILOT / pilot.INPUTS)
    for name in ("pin_mask.png", "original_input_rgb.png", "donor_red_pin.png"):
        if audit.sha256(PILOT / name) != prior["evidence_sha256"][name]:
            raise ValueError(f"Archived pilot donor evidence changed: {name}")
    mask = np.asarray(Image.open(PILOT / "pin_mask.png"), dtype=bool)
    rgb = np.asarray(Image.open(PILOT / "original_input_rgb.png"))
    return {
        name: {"median_rgb": color, "hue_deg": float(hsv(color)[0, 0]), "saturation": float(hsv(color)[0, 1])}
        for name, color in (("red", prior["donor"]["median_rgb"]), ("pilot_pin", np.median(rgb[mask], axis=0).tolist()))
    }


def masks_for(annotation, trace, rgba, depth):
    row, col = trace["crop_origin_yx_px"]
    h, w = trace["crop_height_width_px"]
    left, top, right, bottom = trace["pad_ltrb_px"]
    low, high = trace["histogram_depth_range_mm"]
    alpha = rgba[..., 3] == 255
    valid = alpha & (depth != 0) & (depth >= low) & (depth <= high)
    crop = np.s_[row:row+h, col:col+w]
    pad = ((top, bottom), (left, right))
    silhouette, valid_crop = (np.pad(a[crop], pad) for a in (alpha, valid))
    polygon, = annotation["segmentation"]
    raw = Image.new("1", rgba.shape[:2][::-1])
    ImageDraw.Draw(raw).polygon(tuple(zip(polygon[::2], polygon[1::2])), fill=1)
    raw_mask = np.asarray(raw)
    contour = np.pad(raw_mask[crop], pad)
    mask = contour & valid_crop
    return silhouette, valid_crop, contour, mask, int(raw_mask.sum())


def proposed_delta(pin_rgb, colors):
    # Median in RGB, then circular distance between the resulting HSV hues.
    median = np.median(pin_rgb, axis=0)
    hue = float(hsv(median)[0, 0])
    gaps = {name: abs((donor["hue_deg"] - hue + 180) % 360 - 180) for name, donor in colors.items()}
    selected = max(gaps, key=lambda name: (gaps[name], name == "red"))
    tinted = hsv(pin_rgb)
    tinted[:, 0] = colors[selected]["hue_deg"]
    tinted[:, 1] = colors[selected]["saturation"]
    recolored = np.rint(cv.cvtColor(tinted[None], cv.COLOR_HSV2RGB)[0] * 255).astype(np.int16)
    np.testing.assert_array_equal(recolored.max(axis=1), pin_rgb.max(axis=1))
    return recolored - pin_rgb, {"pin_median_rgb": median.tolist(), "pin_hue_deg": hue,
                                "hue_distance_deg": gaps, "selected": selected}


def peel_patches(rgb, silhouette, valid, pin, contour, proposed):
    yy, xx = np.nonzero(pin)
    origin = np.array([yy.min(), xx.min()])
    y, x = np.array([yy, xx]) - origin[:, None]
    template = pin[yy.min():yy.max()+1, xx.min():xx.max()+1].astype(np.uint8)
    allowed = valid & ~contour
    overlap = cv.matchTemplate(allowed.astype(np.uint8), template, cv.TM_CCORR)
    r, c = np.nonzero(overlap > len(y) - 0.25)
    edge = distance_transform_edt(silhouette)
    luminance = rgb @ np.array([.2126, .7152, .0722])
    pin_edge, pin_luma = edge[pin].mean(), luminance[pin].mean()
    clips, edges, lumas = [], [], []
    for start in range(0, len(r), 1024):
        idx = slice(start, start+1024)
        ry, cx = r[idx, None] + y, c[idx, None] + x
        if not allowed[ry, cx].all():
            raise ValueError("Peel location search included an invalid or pin pixel")
        values = rgb[ry, cx].astype(np.int16) + proposed
        clips.extend(((values < 0) | (values > 255)).sum(axis=(1, 2)))
        edges.extend(edge[ry, cx].mean(axis=1))
        lumas.extend(luminance[ry, cx].mean(axis=1))
    ranking = np.lexsort((c, r, np.abs(np.asarray(lumas) - pin_luma),
                         np.abs(np.asarray(edges) - pin_edge), clips))
    occupied = contour.copy()
    patches, diagnostics = [], []
    for i in ranking:
        ry, cx = r[i] + y, c[i] + x
        if occupied[ry, cx].any():
            continue
        mask = np.zeros_like(pin)
        mask[ry, cx] = True
        patches.append(mask)
        occupied |= mask
        diagnostics.append({"offset_xy_px": [int(c[i] - origin[1]), int(r[i] - origin[0])],
                            "proposed_clipped_channels": int(clips[i]), "mean_edge_distance_px": float(edges[i]),
                            "mean_original_luminance": float(lumas[i])})
        if len(patches) == 3:
            break
    return patches, {"eligible_translations": len(r), "pin_mean_edge_distance_px": float(pin_edge),
                      "pin_mean_original_luminance": float(pin_luma), "patches": diagnostics}


def write_overlay(path, rgb, masks):
    annotated = rgb.copy()
    for mask, color in zip(masks, COLORS):
        annotated[mask & ~binary_erosion(mask)] = color
    Image.fromarray(annotated).save(path)


def freeze_frame(runtime, folder, local, annotation, colors):
    tensor, rgb, trace = runtime.prepare(local / "original_rgba.png", pilot.SEEDS[0])
    rgba = np.array(Image.open(local / "original_rgba.png"))
    depth = cv.imread(str(local / "depth.png"), cv.IMREAD_UNCHANGED)
    silhouette, valid, contour, pin, pin_count = masks_for(annotation, trace, rgba, depth)
    Image.fromarray(rgb).save(folder / "original_rgb.png")
    Image.fromarray(pin).save(folder / "pin_mask.png")
    count = int(pin.sum())
    data = {"crop_trace": trace, "pin_contour_pixels": pin_count, "pin_retained_pixels": count,
            "pin_lost_pixels": pin_count - count, "valid_mask_sha256": audit.array_sha256(valid)}
    if count == 0:
        return data | {"failure": "No pin contour pixels reached the model input"}
    proposed, donor = proposed_delta(rgb[pin], colors)
    peel, selection = peel_patches(rgb, silhouette, valid, pin, contour, proposed)
    masks = [pin, *peel]
    for name, mask in zip(EDIT_NAMES, masks):
        Image.fromarray(mask).save(folder / f"{name}_mask.png")
    write_overlay(folder / "overlay.png", rgb, masks)
    data.update(donor_assignment=donor, patches=selection)
    if len(peel) != 3:
        return data | {"failure": f"Only {len(peel)} disjoint eligible peel patches"}
    base = np.stack([rgb[mask] for mask in masks]).astype(np.int16)
    realized = np.clip(proposed, -base.min(axis=0), 255-base.max(axis=0))
    np.save(folder / "proposed_rgb_delta.npy", proposed, allow_pickle=False)
    np.save(folder / "realized_rgb_delta.npy", realized, allow_pickle=False)
    proposed_strength = float(np.linalg.norm(proposed, axis=1).mean())
    strength = float(np.linalg.norm(realized, axis=1).mean())
    data.update({
        "proposed_mean_rgb_l2": proposed_strength, "realized_mean_rgb_l2": strength,
        "relative_attenuation": 1 - strength / proposed_strength if proposed_strength else None,
        "attenuated_channels": int(np.count_nonzero(proposed != realized)),
        "changed_pixels_per_condition": int(np.count_nonzero(np.any(realized != 0, axis=1))),
        "mean_signed_realized_rgb": realized.mean(axis=0).tolist(),
        "mean_abs_realized_rgb": np.abs(realized).mean(axis=0).tolist(),
        "max_realized_rgb_l2": float(np.linalg.norm(realized, axis=1).max()),
    })
    if strength == 0:
        return data | {"failure": "No nonzero RGB delta is feasible across all conditions"}
    row, col = trace["crop_origin_yx_px"]
    left, top, _, _ = trace["pad_ltrb_px"]
    tensors = {"original": audit.array_sha256(tensor.numpy())}
    for name, mask in zip(EDIT_NAMES, masks):
        y, x = np.nonzero(mask)
        path = local / f"{name}_rgba.png"
        edited = pilot.apply_delta(rgba, y+row-top, x+col-left, realized)
        Image.fromarray(edited).save(path)
        raw = np.array(Image.open(path))
        np.testing.assert_array_equal(raw[..., 3], rgba[..., 3])
        if np.any(raw[..., :3] != rgba[..., :3], axis=2).sum() != data["changed_pixels_per_condition"]:
            raise ValueError(f"{name} changed unexpected source pixels")
        new_tensor, new_rgb, new_trace = runtime.prepare(path, pilot.SEEDS[0])
        if new_trace != trace:
            raise ValueError(f"{name} changed preprocessing geometry")
        np.testing.assert_array_equal(new_tensor.numpy()[:, 3], tensor.numpy()[:, 3])
        np.testing.assert_array_equal(new_rgb[~mask], rgb[~mask])
        np.testing.assert_array_equal(new_rgb[mask].astype(np.int16)-rgb[mask], realized)
        np.testing.assert_array_equal(new_tensor.numpy()[0, :3].transpose(1, 2, 0), new_rgb.astype(np.float32)/255)
        Image.fromarray(new_rgb).save(folder / f"{name}_rgb.png")
        tensors[name] = audit.array_sha256(new_tensor.numpy())
    return data | {"failure": None, "tensor_sha256": tensors, "depth_tensor_sha256": audit.array_sha256(tensor.numpy()[:, 3])}


def hashes(folder):
    return {p.name: audit.sha256(p) for p in sorted(folder.iterdir()) if p.is_file()} if folder.exists() else {}


def prepare(args, runtime):
    if (args.out_dir / "intake.json").exists() or (args.out_dir / "frozen_inputs.json").exists():
        raise FileExistsError("Existing intake or freeze evidence")
    args.input_dir.mkdir(parents=True, exist_ok=False)
    release = Release(args.source)
    colors = donors()
    records = []
    for pair in release.pairs:
        obj, frame = pair["object_id"], pair["frame"]
        folder, local = args.out_dir / obj, args.input_dir / obj
        folder.mkdir()
        record = {"tuber": obj, "frame": frame}
        try:
            annotation, registration_hash = release.extract(pair, local)
            record.update(annotation=annotation, registration_sha256=registration_hash)
            runtime.bind(local, annotation)
            record.update(freeze_frame(runtime, folder, local, annotation, colors))
        except (ValueError, KeyError, OSError, AssertionError, RuntimeError, cv.error) as exc:
            record["failure"] = f"{type(exc).__name__}: {exc}"
        record["input_sha256"], record["evidence_sha256"] = hashes(local), hashes(folder)
        records.append(record)
        print(f"{obj}/{frame}: {record['failure'] or 'RGB deltas verified'}", flush=True)
    pilot.put_json(args.out_dir / "intake.json", {
        "provenance": runtime.provenance_record, "roster_sha256": audit.sha256(ROSTER),
        "development_archive_sha256": audit.sha256(ARCHIVED), "release_members_sha256": audit.sha256(MEMBERS),
        "pilot_input_manifest_sha256": audit.sha256(PILOT / pilot.INPUTS), "donors": colors, "frames": records,
    })


def verify_intake(args, runtime):
    intake = audit.read_json(args.out_dir / "intake.json")
    if intake["provenance"] != runtime.provenance_record:
        raise ValueError("Intake provenance differs from the run")
    for record in intake["frames"]:
        obj = record["tuber"]
        for directory, key in ((args.input_dir, "input_sha256"), (args.out_dir, "evidence_sha256")):
            if hashes(directory / obj) != record[key]:
                raise ValueError(f"Intake artifacts changed: {obj}, {key}")
    return intake


def seal(args, runtime):
    if args.review is None:
        raise ValueError("A visual review of the proposed patches is required before sealing")
    intake = verify_intake(args, runtime)
    review = audit.read_json(args.review)
    expected = {r["tuber"]: len(r["patches"]["patches"]) for r in intake["frames"] if "patches" in r}
    if set(review) != set(expected) or any(len(review[obj]) != n for obj, n in expected.items()):
        raise ValueError("Visual review does not cover every selected peel patch")
    pilot.put_json(args.out_dir / "frozen_inputs.json", {
        "status": "frozen_before_edited_inference", "intake_sha256": audit.sha256(args.out_dir / "intake.json"),
        "review_sha256": audit.sha256(args.review), "visual_peel_review": review, **intake,
    })


def verify_seal(args, runtime):
    intake = verify_intake(args, runtime)
    freeze = audit.read_json(args.out_dir / "frozen_inputs.json")
    if (freeze["status"] != "frozen_before_edited_inference" or
            freeze["intake_sha256"] != audit.sha256(args.out_dir / "intake.json") or
            any(freeze[key] != value for key, value in intake.items())):
        raise ValueError("Frozen manifest no longer matches verified intake")
    return freeze


def replay_frame(runtime, local, record):
    runtime.bind(local, record["annotation"])
    rgb = np.array(Image.open(local / "original_rgba.png"))
    y, x = np.nonzero(rgb[..., 3] > 0)
    rows = []
    with TemporaryDirectory(prefix="corepp-multituber-noop-") as directory:
        noop_path = Path(directory) / "no_op_rgba.png"
        Image.fromarray(pilot.apply_delta(rgb, y, x, np.zeros((len(x), 3), dtype=np.int16))).save(noop_path)
        for seed in pilot.SEEDS:
            row = {"seed": seed}
            try:
                baseline, noop = (runtime.run(path, seed) for path in (local / "original_rgba.png", noop_path))
                original_hash = pilot.numeric_hashes(baseline)
                row.update(hashes=original_hash, original_volume_ml=baseline["volume_ml"],
                           boundary=runtime.boundary(baseline), surface_distance=None,
                           mesh_failures=[r["mesh_failure"] for r in (baseline, noop)])
                checks = {"numeric_hashes_equal": original_hash == pilot.numeric_hashes(noop),
                          "original_tensor_matches_frozen": original_hash["tensor"] == record["tensor_sha256"]["original"],
                          "grid_labels_equal": bool(np.array_equal(baseline["sdf"] < 0, noop["sdf"] < 0)),
                          "volumes_equal": baseline["volume_ml"] == noop["volume_ml"]}
                if baseline["mesh"] is not None and noop["mesh"] is not None:
                    surface = row["surface_distance"] = pilot.surface_pair(baseline["mesh"], noop["mesh"])
                    checks.update(identical_mesh_arrays=surface["identical_mesh_arrays"],
                                  surface_at_numerical_precision=surface["max_mm"] <= pilot.SURFACE_TOL_MM)
                row.update(checks=checks, passed=all(checks.values()) and row["surface_distance"] is not None)
            except (ValueError, OSError, AssertionError, RuntimeError, cv.error) as exc:
                row.update(passed=False, failure=f"{type(exc).__name__}: {exc}")
            rows.append(row)
    return rows


def replay(args, runtime):
    freeze = verify_seal(args, runtime)
    path = args.out_dir / "no_op_replay.json"
    if path.exists():
        raise FileExistsError(path)
    records = []
    for record in freeze["frames"]:
        obj = record["tuber"]
        pairs = replay_frame(runtime, args.input_dir / obj, record) if not record["failure"] else []
        passed = sum(row["passed"] for row in pairs)
        records.append({"tuber": obj, "frame": record["frame"], "pairs": pairs, "passed": passed,
                        "failure": record["failure"] or (None if passed == len(pilot.SEEDS) else "Paired no-op check failed")})
        print(f"{obj}: {passed}/{len(pilot.SEEDS)} no-op pairs passed", flush=True)
    pilot.put_json(path, {"status": "replay_completed", "frozen_inputs_sha256": audit.sha256(args.out_dir / "frozen_inputs.json"),
                          "surface_tolerance_mm": pilot.SURFACE_TOL_MM, "frames": records})


def score_frame(runtime, local, record, replay_record):
    runtime.bind(local, record["annotation"])
    rows = []
    for pair in replay_record["pairs"]:
        seed = pair["seed"]
        row = {"seed": seed, "conditions": {}}
        try:
            baseline = runtime.run(local / "original_rgba.png", seed)
            row.update(original_volume_ml=baseline["volume_ml"], original_boundary=runtime.boundary(baseline),
                       original_mesh_failure=baseline["mesh_failure"])
            if (pilot.numeric_hashes(baseline) != pair["hashes"] or baseline["mesh"] is None or
                    baseline["volume_ml"] != pair["original_volume_ml"]):
                raise ValueError("Unchanged prediction did not match the paired no-op")
        except (ValueError, OSError, AssertionError, RuntimeError, cv.error) as exc:
            row["failure"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
            continue
        for name in EDIT_NAMES:
            try:
                edited = runtime.run(local / f"{name}_rgba.png", seed)
                if audit.array_sha256(edited["tensor"]) != record["tensor_sha256"][name]:
                    raise ValueError("Edited tensor did not match frozen input")
                if not np.isfinite(edited["sdf"]).all() or not np.isfinite(edited["latent"]).all():
                    data = {"mesh_failure": edited["mesh_failure"]}
                else:
                    data = pilot.compare(baseline, edited)
                data["boundary"] = runtime.boundary(edited)
            except (ValueError, OSError, AssertionError, RuntimeError, cv.error) as exc:
                data = {"failure": f"{type(exc).__name__}: {exc}"}
            row["conditions"][name] = data
        surface = {name: d["surface_distance"]["mean_mm"] for name, d in row["conditions"].items()
                   if d.get("surface_distance") is not None}
        if len(surface) == len(EDIT_NAMES):
            peel = [surface[name] for name in EDIT_NAMES[1:]]
            row.update(pin_minus_mean_peel_mm=surface["pin"]-float(np.mean(peel)),
                       pin_minus_seedwise_max_peel_mm=surface["pin"]-max(peel))
        rows.append(row)
    return rows


def frame_summary(rows):
    by_condition = {}
    for name in EDIT_NAMES:
        values = [r["conditions"].get(name, {}) for r in rows]
        metrics = ("latent_l2", "mean_abs_sdf_change_mm", "grid_label_changes", "volume_change_ml")
        by_condition[name] = {k: pilot.summarize([v[k] for v in values if v.get(k) is not None]) for k in metrics}
        by_condition[name]["mean_surface_mm"] = pilot.summarize(
            [v["surface_distance"]["mean_mm"] for v in values if v.get("surface_distance") is not None])
    full = [r for r in rows if "pin_minus_mean_peel_mm" in r]
    summary = {"complete_seed_pairs": len(full), "by_condition": by_condition}
    if len(full) == len(pilot.SEEDS):
        strongest = max(EDIT_NAMES[1:], key=lambda name: by_condition[name]["mean_surface_mm"]["median"])
        fixed = [
            r["conditions"]["pin"]["surface_distance"]["mean_mm"] -
            r["conditions"][strongest]["surface_distance"]["mean_mm"] for r in full
        ]
        summary.update(
            primary=pilot.summarize([r["pin_minus_mean_peel_mm"] for r in full]),
            strongest_peel=strongest, pin_minus_strongest_peel=pilot.summarize(fixed),
            pin_minus_seedwise_max_peel=pilot.summarize([r["pin_minus_seedwise_max_peel_mm"] for r in full]),
        )
    return summary


def cohort_summary(rows):
    values = {r["tuber"]: r["summary"]["primary"]["median"] for r in rows if "primary" in r["summary"]}
    loo = {obj: float(np.mean([v for key, v in values.items() if key != obj])) for obj in values} if len(values) > 1 else {}
    strongest = [r["summary"]["pin_minus_strongest_peel"]["median"] for r in rows if "primary" in r["summary"]]
    max_peel = [r["summary"]["pin_minus_seedwise_max_peel"]["median"] for r in rows if "primary" in r["summary"]]
    return {
        "intake_n": len(rows), "complete_n": len(values), "mean_mm": float(np.mean(list(values.values()))) if values else None,
        "primary_mm": pilot.summarize(list(values.values())), "positive": sum(v > 0 for v in values.values()),
        "zero": sum(v == 0 for v in values.values()), "negative": sum(v < 0 for v in values.values()),
        "leave_one_tuber_out_mm": pilot.summarize(list(loo.values())), "leave_one_tuber_out_by_tuber_mm": loo,
        "strongest_peel_mm": pilot.summarize(strongest), "strongest_peel_positive": sum(v > 0 for v in strongest),
        "seedwise_max_peel_mm": pilot.summarize(max_peel), "seedwise_max_peel_positive": sum(v > 0 for v in max_peel),
    }


def score(args, runtime):
    freeze = verify_seal(args, runtime)
    no_op_path = args.out_dir / "no_op_replay.json"
    replayed = audit.read_json(no_op_path)
    if replayed["frozen_inputs_sha256"] != audit.sha256(args.out_dir / "frozen_inputs.json"):
        raise ValueError("No-op replay was run on a different freeze")
    path = args.out_dir / "results.json"
    if path.exists():
        raise FileExistsError(path)
    records = []
    for record, replay_record in zip(freeze["frames"], replayed["frames"], strict=True):
        obj = record["tuber"]
        if obj != replay_record["tuber"] or record["frame"] != replay_record["frame"]:
            raise ValueError("No-op replay covered a different frame")
        blocked = record["failure"] or replay_record["failure"]
        pairs = [] if blocked else score_frame(runtime, args.input_dir / obj, record, replay_record)
        summary = frame_summary(pairs)
        failure = blocked or (None if "primary" in summary else "Incomplete edited comparisons")
        records.append({"tuber": obj, "frame": record["frame"], "summary": summary, "pairs": pairs, "failure": failure})
        print(f"{obj}: {summary['complete_seed_pairs']}/{len(pilot.SEEDS)} complete edited pairs", flush=True)
    pilot.put_json(path, {
        "frozen_inputs_sha256": audit.sha256(args.out_dir / "frozen_inputs.json"),
        "no_op_sha256": audit.sha256(no_op_path), "provenance": runtime.provenance_record,
        "cohort": cohort_summary(records), "frames": records,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "seal", "noop", "score"))
    for name in ("source", "upstream", "released", "out-dir", "input-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    runtime = Runtime(args)
    {"prepare": prepare, "seal": seal, "noop": replay, "score": score}[args.phase](args, runtime)


if __name__ == "__main__":
    main()
