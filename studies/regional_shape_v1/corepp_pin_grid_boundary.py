"""Replay the archived CoRe++ lattice and score a fixed five-point extension."""

import argparse
from pathlib import Path
from statistics import mean, median

import numpy as np
import torch

from . import corepp_pin_multituber as multi
from .corepp_pin_multituber import audit, pilot

ARCHIVE = audit.HERE / "corepp_pin_multituber"
ARCHIVE_FILES = ("frozen_inputs.json", "no_op_replay.json", "results.json")
PAD = 5
OLD_N = 20
NEW_N = OLD_N + 2 * PAD
SHELL_SEED_OFFSET = 10000
GRID_FILE = "expanded_grid.npy"
FREEZE = "frozen_grid.json"
REPLAY = "interior_replay.json"
RESULTS = "results.json"
METRICS = ("primary", "strongest_peel", "seedwise_max_peel", "archived_strongest_peel")


def load_archive(args, runtime):
    frozen, noop, scored = (audit.read_json(ARCHIVE / name) for name in ARCHIVE_FILES)
    hashes = {name: audit.sha256(ARCHIVE / name) for name in ARCHIVE_FILES}
    if (frozen["provenance"] != runtime.provenance_record or scored["provenance"] != runtime.provenance_record or
            noop["frozen_inputs_sha256"] != hashes["frozen_inputs.json"] or
            scored["frozen_inputs_sha256"] != hashes["frozen_inputs.json"] or
            scored["no_op_sha256"] != hashes["no_op_replay.json"]):
        raise ValueError("Archived inputs, model and predictions do not form the same frozen run")
    frames = list(zip(frozen["frames"], noop["frames"], scored["frames"], strict=True))
    if len(frames) != 10 or {f["tuber"]: f["frame"] for f, _, _ in frames} != multi.EXPECTED:
        raise ValueError("Expected the ten registered development frames")
    for frame, baseline, score in frames:
        obj = frame["tuber"]
        if (frame["failure"] or baseline["failure"] or score["failure"] or
                len(score["pairs"]) != len(pilot.SEEDS) or baseline["passed"] != len(pilot.SEEDS) or
                any((row["tuber"], row["frame"]) != (obj, frame["frame"]) for row in (baseline, score)) or
                [r["seed"] for r in baseline["pairs"]] != list(pilot.SEEDS) or
                [r["seed"] for r in score["pairs"]] != list(pilot.SEEDS)):
            raise ValueError(f"Incomplete or inconsistent archived score for {obj}")
        for folder, key in ((args.input_dir, "input_sha256"), (ARCHIVE, "evidence_sha256")):
            if multi.hashes(folder / obj) != frame[key]:
                raise ValueError(f"Frozen development files changed for {obj}")
    return frames, hashes


def grid_layout(runtime):
    old = runtime.grid.numpy()
    axes, spacing = [], []
    for axis in "xyz":
        low, high = (runtime.box[axis + end] for end in ("min", "max"))
        step = (high - low) / (OLD_N - 1)
        coords = np.linspace(low, high, OLD_N)
        left = low + step * np.arange(-PAD, 0)
        right = high + step * np.arange(1, PAD + 1)
        axes.append(np.concatenate((left, coords, right)))
        spacing.append(step)
    # Released Grid3D shifts x and y on every odd original z index. Carry the
    # original phase and shift through the extension, including negative indices.
    stagger = (runtime.box["xmax"] - runtime.box["xmin"]) / OLD_N / 2
    points = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1)
    points[:, :, np.arange(-PAD, OLD_N + PAD) % 2 == 1, :2] += stagger
    points = points.astype(np.float32).reshape(-1, 3)
    inner = np.zeros((NEW_N,) * 3, dtype=bool)
    inner[PAD:-PAD, PAD:-PAD, PAD:-PAD] = True
    inside = inner.ravel()
    np.testing.assert_array_equal(points[inside], old)
    return points, inside, spacing, stagger


def freeze_grid(args, runtime, frames, hashes):
    if (args.out_dir / GRID_FILE).exists() or (args.out_dir / FREEZE).exists():
        raise FileExistsError("The expanded grid is already frozen")
    points, inside, spacing, stagger = grid_layout(runtime)
    path = args.out_dir / GRID_FILE
    np.save(path, points, allow_pickle=False)
    pilot.put_json(args.out_dir / FREEZE, {
        "stage": "frozen_before_replay_and_scoring", "script_sha256": audit.sha256(Path(__file__)),
        "archived_sha256": hashes, "frames": [[f["tuber"], f["frame"]] for f, _, _ in frames],
        "original_shape": [OLD_N] * 3, "expanded_shape": [NEW_N] * 3, "points_per_side_added": PAD,
        "original_grid_sha256": runtime.grid_sha, "expanded_grid_npy_sha256": audit.sha256(path),
        "expanded_grid_array_sha256": audit.array_sha256(points), "interior_mask_sha256": audit.array_sha256(inside),
        "original_points": int(inside.sum()), "added_points": int((~inside).sum()), "spacing_m": spacing,
        "odd_z_plane_xy_shift_m": stagger, "z_index_of_first_expanded_plane": -PAD,
        "expanded_min_xyz_m": points.min(axis=0).tolist(), "expanded_max_xyz_m": points.max(axis=0).tolist(),
        "original_interior_coordinates_bitwise_equal": True,
        "shell_seed_by_interior_seed": {str(s): s + SHELL_SEED_OFFSET for s in pilot.SEEDS},
        "shell_order": "C-order ij-indexed grid with the original interior omitted",
        "decoder_batches": "archived interior first, then one separate shell batch for the same latent",
    })
    print(f"Froze {NEW_N}³ grid with {int(inside.sum())} exact archived coordinates", flush=True)


def check_grid(args, runtime, hashes):
    manifest = audit.read_json(args.out_dir / FREEZE)
    path = args.out_dir / GRID_FILE
    if (manifest["archived_sha256"] != hashes or manifest["script_sha256"] != audit.sha256(Path(__file__)) or
            manifest["expanded_grid_npy_sha256"] != audit.sha256(path)):
        raise ValueError("The grid freeze or archived input hashes changed")
    points = np.load(path, allow_pickle=False)
    expected, inside, _, _ = grid_layout(runtime)
    np.testing.assert_array_equal(points, expected)
    return points, inside, manifest


def decode(decoder, latent, points, seed):
    values = torch.cat((latent.expand(len(points), -1), points), dim=1)
    pilot.set_rng(seed)
    return decoder(values)


def interior_run(runtime, tensor, seed):
    for model, state, mode in zip(runtime.models, runtime.states, runtime.modes):
        model.load_state_dict(state, strict=True)
        model.train(mode)
    pilot.set_rng(seed)
    latent = runtime.encoder(tensor)
    sdf = decode(runtime.decoder, latent, runtime.grid, seed)
    return latent, sdf


@torch.no_grad()
def replay_interior(args, runtime, frames, points, inside):
    out = args.out_dir
    if (out / REPLAY).exists():
        raise FileExistsError(out / REPLAY)
    args.cache_dir.mkdir(parents=True, exist_ok=False)
    records, probe = [], None
    for frame, noop, archived in frames:
        obj = frame["tuber"]
        local = args.input_dir / obj
        runtime.bind(local, frame["annotation"])
        tensors = {name: runtime.prepare(local / f"{name}_rgba.png", pilot.SEEDS[0])[0] for name in multi.CONDITIONS}
        rows, all_latents, all_sdfs = [], [], []
        for original, old in zip(noop["pairs"], archived["pairs"], strict=True):
            seed, checks, latents, sdfs = old["seed"], {}, [], []
            for name, tensor in tensors.items():
                latent, sdf = interior_run(runtime, tensor, seed)
                observed = pilot.numeric_hashes({"tensor": tensor.numpy(), "latent": latent.numpy(), "sdf": sdf.numpy()})
                expected = original["hashes"] if name == "original" else old["conditions"][name]["hashes"]
                if observed != expected or observed["tensor"] != frame["tensor_sha256"][name]:
                    raise ValueError(f"{obj} seed {seed} {name} does not reproduce archived input, latent or SDF")
                labels = sdf.numpy().ravel() < 0
                changed = int(np.count_nonzero(labels != (sdfs[0].ravel() < 0))) if sdfs else 0
                if name != "original" and changed != old["conditions"][name]["grid_label_changes"]:
                    raise ValueError(f"{obj} seed {seed} {name} label changes do not match the archive")
                checks[name] = {"hashes": observed, "inside_labels_sha256": audit.array_sha256(labels),
                                "negative_points": int(labels.sum()), "label_changes_from_original": changed}
                if probe is None:
                    packed = decode(runtime.decoder, latent, torch.from_numpy(points), seed).numpy()[inside]
                    probe = {"tuber": obj, "seed": seed, "condition": name,
                             "different_interior_sdf_values": int(np.count_nonzero(packed != sdf.numpy())),
                             "different_interior_labels": int(np.count_nonzero((packed.ravel() < 0) != labels)),
                             "max_abs_interior_sdf_difference_mm": float(np.abs(packed - sdf.numpy()).max() * 1000)}
                latents.append(latent.numpy())
                sdfs.append(sdf.numpy())
            all_latents.append(latents)
            all_sdfs.append(sdfs)
            rows.append({"seed": seed, "conditions": checks})
        cache = args.cache_dir / f"{obj}.npz"
        np.savez(cache, latent=np.asarray(all_latents), sdf=np.asarray(all_sdfs))
        records.append({"tuber": obj, "frame": frame["frame"], "seeds": rows, "cache_sha256": audit.sha256(cache)})
        print(f"{obj}: 80/80 archived interior predictions reproduced exactly", flush=True)
    pilot.put_json(out / REPLAY, {
        "status": "all_archived_interior_sdf_hashes_and_labels_reproduced",
        "frozen_grid_sha256": audit.sha256(out / FREEZE), "verified_predictions": len(records) * 80,
        "packed_batch_probe": probe, "frames": records,
    })


def mesh_prediction(runtime, sdf, seed):
    mesh, volume, failure = None, None, None
    try:
        if not np.isfinite(sdf).all():
            raise ValueError("Non-finite SDF")
        pilot.set_rng(seed)
        mesh = runtime.mesh_builder(torch.from_numpy(sdf), runtime.grid, t=0.0)
        if not mesh.is_watertight() or not np.isfinite(np.asarray(mesh.vertices)).all():
            raise ValueError("Non-watertight or non-finite mesh")
        volume = mesh.get_volume() * 1e6
        if not np.isfinite(volume) or volume <= 0:
            raise ValueError("Non-finite or nonpositive mesh volume")
    except (ValueError, RuntimeError) as exc:
        mesh, volume, failure = None, None, str(exc)
    return {"mesh": mesh, "mesh_failure": failure, "volume_ml": volume, "sdf": sdf}


def surface_displacement(original, edited):
    a, b = original["mesh"], edited["mesh"]
    if a is None or b is None:
        return None
    return 0.0 if pilot.same_mesh(a, b) else pilot.surface_pair(a, b)["mean_mm"]


def old_conditions(row):
    conditions = {"original": {"boundary": row["original_boundary"], "displacement_mm": 0.0,
                              "volume_ml": row["original_volume_ml"], "mesh_failure": row["original_mesh_failure"]}}
    for name, value in row["conditions"].items():
        conditions[name] = {"boundary": value["boundary"], "displacement_mm": value["surface_distance"]["mean_mm"],
                            "volume_ml": row["original_volume_ml"] + value["volume_change_ml"],
                            "mesh_failure": value["mesh_failure"]}
    return conditions


def contrasts(conditions, archive_strongest):
    complete = [row for row in conditions if all(row[name]["displacement_mm"] is not None for name in multi.CONDITIONS)]
    if len(complete) != len(pilot.SEEDS):
        return {"complete_seeds": len(complete)}
    by_condition = {name: [row[name]["displacement_mm"] for row in complete] for name in multi.EDIT_NAMES}
    edit_medians = {name: median(values) for name, values in by_condition.items()}
    peel_names = multi.EDIT_NAMES[1:]
    strongest = max(peel_names, key=edit_medians.__getitem__)
    primary, fixed, worst, anchored = [], [], [], []
    for row in complete:
        pin = row["pin"]["displacement_mm"]
        peels = [row[name]["displacement_mm"] for name in peel_names]
        primary.append(pin - mean(peels))
        fixed.append(pin - row[strongest]["displacement_mm"])
        worst.append(pin - max(peels))
        anchored.append(pin - row[archive_strongest]["displacement_mm"])
    return {"complete_seeds": len(complete), "edit_medians_mm": edit_medians, "strongest_patch": strongest,
            "archived_strongest_patch": archive_strongest,
            **{k: pilot.summarize(v) for k, v in zip(METRICS, (primary, fixed, worst, anchored), strict=True)}}


def boundary_counts(conditions):
    rows = [s[name] for s in conditions for name in multi.CONDITIONS]
    return {"predictions": len(rows), "valid_meshes": sum(r["mesh_failure"] is None for r in rows),
            "grid_contact": sum(r["boundary"]["inside_on_any_grid_face"] > 0 for r in rows),
            "logical_grid_contact": sum(r["boundary"]["inside_on_any_logical_grid_face"] > 0 for r in rows),
            "mesh_contact": sum(bool(r["boundary"]["mesh_faces_touched"]) for r in rows)}


def logical_boundary(sdf, n):
    inside = sdf.reshape(n, n, n) < 0
    return int(inside.sum() - inside[1:-1, 1:-1, 1:-1].sum())


def effect_sign(value):
    return "positive" if value > 0 else "negative" if value < 0 else "tied"


def aggregate(frames):
    output = {}
    for metric in METRICS:
        comparable = [row for row in frames if metric in row["expanded"]]
        before = [row["original"][metric]["median"] for row in comparable]
        after = [row["expanded"][metric]["median"] for row in comparable]
        result = {}
        for label, values in (("original", before), ("expanded", after)):
            result[label] = {"n": len(values), "mean_mm": mean(values) if values else None,
                             "median_mm": median(values) if values else None,
                             **{s: sum(effect_sign(v) == s for v in values) for s in ("positive", "tied", "negative")}}
        if before:
            differences = [a - b for a, b in zip(after, before, strict=True)]
            result.update(mean_change_mm=mean(differences),
                          median_change_mm=median(after)-median(before),
                          median_paired_tuber_change_mm=median(differences))
            if len(after) > 1:
                result["expanded_leave_one_tuber_out_mean_mm"] = pilot.summarize(
                    [mean(after[:i] + after[i+1:]) for i in range(len(after))])
        output[metric] = result
    return output


@torch.no_grad()
def score_expanded(args, runtime, frames, points, inside, manifest):
    out = args.out_dir
    if (out / RESULTS).exists():
        raise FileExistsError(out / RESULTS)
    replay = audit.read_json(out / REPLAY)
    if replay["frozen_grid_sha256"] != audit.sha256(out / FREEZE) or replay["verified_predictions"] != 800:
        raise ValueError("Full archived replay on the frozen grid is required before scoring")
    runtime.grid = torch.from_numpy(points)
    runtime.faces = {axis + side: points[:, i] == extreme(points[:, i])
                     for i, axis in enumerate("xyz") for side, extreme in (("min", np.min), ("max", np.max))}
    shell_points = torch.from_numpy(points[~inside])
    records = []
    for (frame, _, archived), verified in zip(frames, replay["frames"], strict=True):
        obj = frame["tuber"]
        cache = args.cache_dir / f"{obj}.npz"
        if obj != verified["tuber"] or audit.sha256(cache) != verified["cache_sha256"]:
            raise ValueError(f"Interior cache changed for {obj}")
        with np.load(cache, allow_pickle=False) as inputs:
            latents, sdfs = inputs["latent"], inputs["sdf"]
        rows = []
        for i, (old, checked) in enumerate(zip(archived["pairs"], verified["seeds"], strict=True)):
            seed = old["seed"]
            if seed != checked["seed"]:
                raise ValueError("Interior replay seed order changed")
            shell_seed = manifest["shell_seed_by_interior_seed"][str(seed)]
            preceding = old_conditions(old)
            expanded = {}
            for j, name in enumerate(multi.CONDITIONS):
                interior_sdf = sdfs[i, j]
                expected = checked["conditions"][name]
                if (audit.array_sha256(interior_sdf) != expected["hashes"]["sdf"] or
                        audit.array_sha256(interior_sdf.ravel() < 0) != expected["inside_labels_sha256"] or
                        audit.array_sha256(latents[i, j]) != expected["hashes"]["latent"]):
                    raise ValueError(f"Replayed interior cache does not match {obj}, {seed}, {name}")
                runtime.decoder.load_state_dict(runtime.states[1], strict=True)
                runtime.decoder.train(runtime.modes[1])
                shell_sdf = decode(runtime.decoder, torch.from_numpy(latents[i, j]), shell_points, shell_seed).numpy()
                sdf = np.empty((len(points), 1), dtype=interior_sdf.dtype)
                sdf[inside], sdf[~inside] = interior_sdf, shell_sdf
                np.testing.assert_array_equal(sdf[inside], interior_sdf)
                mesh = mesh_prediction(runtime, sdf, seed)
                if name == "original":
                    original = mesh
                boundary = runtime.boundary(mesh)
                boundary["inside_on_any_logical_grid_face"] = logical_boundary(sdf, NEW_N)
                preceding[name]["boundary"]["inside_on_any_logical_grid_face"] = logical_boundary(interior_sdf, OLD_N)
                expanded[name] = {"boundary": boundary, "volume_ml": mesh["volume_ml"],
                                  "mesh_failure": mesh["mesh_failure"],
                                  "displacement_mm": surface_displacement(original, mesh),
                                  "expanded_sdf_sha256": audit.array_sha256(sdf),
                                  "shell_sdf_sha256": audit.array_sha256(shell_sdf),
                                  "negative_shell_points": int(np.count_nonzero(shell_sdf < 0))}
            rows.append({"seed": seed, "shell_seed": shell_seed, "original_grid": preceding, "expanded_grid": expanded})
        old_conditions_by_seed = [r["original_grid"] for r in rows]
        new_conditions_by_seed = [r["expanded_grid"] for r in rows]
        archive_patch = archived["summary"]["strongest_peel"]
        before, after = (contrasts(conditions, archive_patch) for conditions in (old_conditions_by_seed, new_conditions_by_seed))
        for this, original_key in zip(METRICS[:3], ("primary", "pin_minus_strongest_peel", "pin_minus_seedwise_max_peel"), strict=True):
            if abs(before[this]["median"] - archived["summary"][original_key]["median"]) > 1e-12:
                raise ValueError(f"Recomputed original contrast does not match archive for {obj}")
        comparisons = {}
        for metric in METRICS:
            if metric in after:
                a, b = before[metric]["median"], after[metric]["median"]
                comparisons[metric] = {"change_mm": b - a, "sign_before": effect_sign(a), "sign_after": effect_sign(b),
                                       "sign_changed": effect_sign(a) != effect_sign(b)}
        records.append({"tuber": obj, "frame": frame["frame"], "original": before, "expanded": after,
                        "changes": comparisons, "original_boundary": boundary_counts(old_conditions_by_seed),
                        "expanded_boundary": boundary_counts(new_conditions_by_seed), "pairs": rows})
        print(f"{obj}: {after['complete_seeds']}/16 expanded seed sets", flush=True)
    pilot.put_json(out / RESULTS, {
        "frozen_grid_sha256": audit.sha256(out / FREEZE), "interior_replay_sha256": audit.sha256(out / REPLAY),
        "intake_tubers": len(frames), "complete_tubers": sum("primary" in f["expanded"] for f in records),
        "cohort": aggregate(records), "frames": records,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "replay", "score"))
    for name in ("upstream", "released", "input-dir", "cache-dir", "out-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    runtime = multi.Runtime(argparse.Namespace(**(vars(args) | {"phase": "freeze" if args.phase == "freeze" else "score"})))
    frames, hashes = load_archive(args, runtime)
    if args.phase == "freeze":
        freeze_grid(args, runtime, frames, hashes)
    else:
        points, inside, manifest = check_grid(args, runtime, hashes)
        if args.phase == "replay":
            replay_interior(args, runtime, frames, points, inside)
        else:
            score_expanded(args, runtime, frames, points, inside, manifest)


if __name__ == "__main__":
    main()
