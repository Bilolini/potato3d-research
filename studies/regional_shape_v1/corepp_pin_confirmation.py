"""Prepare and score the frozen fresh-potato CoRe++ confirmation."""

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import multiprocessing
from pathlib import Path
from statistics import mean, median
from tempfile import TemporaryDirectory
from time import perf_counter
from zipfile import ZipFile

import cv2 as cv
import numpy as np
import open3d as o3d
from PIL import Image
import torch

from . import corepp_pin_confirmation_inventory as inventory
from . import corepp_pin_grid_boundary as grid
from .corepp_pin_multituber import audit, pilot
from . import corepp_pin_multituber as multi

GRID_DIR = audit.HERE / "corepp_pin_grid_boundary"
EXPECTED_FAILURES = (ValueError, KeyError, OSError, AssertionError, RuntimeError, cv.error)
METRICS = ("primary", "strongest_peel")
BOOTSTRAP_SEED = 5273201
BOOTSTRAP_DRAWS = 20000
MIN_GROUPS = 6


def load_roster(args):
    roster = audit.read_json(args.out_dir / "roster.json")
    path = args.out_dir / "inventory.json"
    catalog = audit.read_json(path)
    if (roster["protocol_sha256"] != audit.sha256(inventory.PROTOCOL) or
            roster["inventory_sha256"] != audit.sha256(path) or
            roster["selection_source_sha256"] != audit.sha256(Path(inventory.__file__)) or
            roster["frames"] != inventory.roster(catalog["objects"])):
        raise ValueError("Frozen protocol, inventory or roster changed")
    for name, digest in catalog["prior_roster_sha256"].items():
        if audit.sha256(inventory.EXCLUSIONS[name]) != digest:
            raise ValueError("An exclusion roster changed")
    if not roster["frames"] or any(f["model_split"] != "test" for f in roster["frames"]):
        raise ValueError("The confirmation requires a nonempty released test cohort")
    return roster["frames"], catalog


def extract(args, pair, folder):
    folder.mkdir()
    with ZipFile(args.source / audit.MATRIX_ARCHIVE) as z:
        registration = z.read(pair["registration_member"])
    if hashlib.sha256(registration).hexdigest() != pair["registration_sha256"]:
        raise ValueError("Registered-frame metadata changed")
    for key, name in (("rgb", "original_rgba.png"), ("depth", "depth.png")):
        asset = pair[key]
        with ZipFile(args.source / asset["archive"]) as z:
            info = z.getinfo(asset["member"])
            if info.file_size != asset["bytes"] or f"{info.CRC:08x}" != asset["crc32"]:
                raise ValueError(f"{key} member differs from the metadata inventory")
            data = z.read(info)
        (folder / name).write_bytes(data)


def prepare(args, frames, catalog):
    if (args.out_dir / "intake.json").exists():
        raise FileExistsError("This confirmation already has a prepared intake")
    for name, digest in catalog["metadata_sha256"].items():
        if audit.sha256(args.source / name) != digest:
            raise ValueError("Release metadata changed before extraction")
    args.input_dir.mkdir(parents=True, exist_ok=False)
    runtime = multi.Runtime(args)
    colors = multi.donors()
    records = []
    for pair in frames:
        obj = pair["tuber"]
        local, folder = args.input_dir / obj, args.out_dir / obj
        folder.mkdir()
        record = {k: pair[k] for k in ("tuber", "frame", "cultivar", "group", "model_split", "dataset_exp_split",
                                       "annotation", "registration_sha256")}
        try:
            extract(args, pair, local)
            runtime.bind(local, record["annotation"])
            record.update(multi.freeze_frame(runtime, folder, local, record["annotation"], colors))
        except EXPECTED_FAILURES as exc:
            record["failure"] = f"{type(exc).__name__}: {exc}"
        record.update(input_sha256=multi.hashes(local), evidence_sha256=multi.hashes(folder))
        records.append(record)
        print(f"{obj}/{pair['frame']}: {record['failure'] or 'matched RGB deltas verified'}", flush=True)
    pilot.put_json(args.out_dir / "intake.json", {
        "roster_sha256": audit.sha256(args.out_dir / "roster.json"), "cpu_provenance": runtime.provenance_record,
        "donors": colors, "frames": records,
    })


def verify_intake(args, frames):
    intake = audit.read_json(args.out_dir / "intake.json")
    if intake["roster_sha256"] != audit.sha256(args.out_dir / "roster.json"):
        raise ValueError("Intake and roster do not match")
    for row, pair in zip(intake["frames"], frames, strict=True):
        obj = row["tuber"]
        if any(row[k] != pair[k] for k in ("tuber", "frame", "annotation", "registration_sha256")):
            raise ValueError("Intake row differs from the roster")
        for directory, key in ((args.out_dir, "evidence_sha256"), (args.input_dir, "input_sha256")):
            if multi.hashes(directory / obj) != row[key]:
                raise ValueError(f"Changed intake artifact for {obj}")
    return intake


def code_and_grid_hashes():
    return {p.name: audit.sha256(p) for p in (
        Path(__file__), Path(multi.__file__), Path(grid.__file__), Path(pilot.__file__), Path(audit.__file__),
        GRID_DIR / grid.FREEZE, GRID_DIR / grid.GRID_FILE,
    )}


def seal(args, frames):
    intake = verify_intake(args, frames)
    if args.review is None:
        raise ValueError("Supply the pre-inference crop review")
    review = audit.read_json(args.review)
    expected = {r["tuber"]: len(r.get("patches", {}).get("patches", [])) for r in intake["frames"]}
    if set(review) != set(expected) or any(len(review[obj]) != n for obj, n in expected.items()):
        raise ValueError("Every selected patch and frame needs an explicit visual review entry")
    pilot.put_json(args.out_dir / "frozen_inputs.json", {
        "stage": "frozen_before_inference", "intake_sha256": audit.sha256(args.out_dir / "intake.json"),
        "code_and_grid_sha256": code_and_grid_hashes(), "visual_review_sha256": audit.sha256(args.review),
        "visual_peel_review": review, **intake,
    })


def load_frozen(args, frames):
    intake = verify_intake(args, frames)
    frozen = audit.read_json(args.out_dir / "frozen_inputs.json")
    if (frozen["intake_sha256"] != audit.sha256(args.out_dir / "intake.json") or
            frozen["code_and_grid_sha256"] != code_and_grid_hashes() or
            any(frozen[key] != value for key, value in intake.items())):
        raise ValueError("Inputs, scorer or fixed grid changed since freeze")
    return frozen


class Model:
    def __init__(self, args, expected_provenance):
        self.runtime = multi.Runtime(argparse.Namespace(**(vars(args) | {"phase": "score"})))
        if expected_provenance != self.runtime.provenance_record:
            raise ValueError("Runtime differs from frozen checkpoint and configuration")
        points = np.load(GRID_DIR / grid.GRID_FILE, allow_pickle=False)
        manifest = audit.read_json(GRID_DIR / grid.FREEZE)
        expected, self.inside, _, _ = grid.grid_layout(self.runtime)
        np.testing.assert_array_equal(points, expected)
        if manifest["expanded_grid_npy_sha256"] != audit.sha256(GRID_DIR / grid.GRID_FILE):
            raise ValueError("The verified development lattice changed")
        self.shell = torch.from_numpy(points[~self.inside])
        self.shell_seeds = manifest["shell_seed_by_interior_seed"]
        self.mesh_runtime = argparse.Namespace(
            grid=torch.from_numpy(points), mesh_builder=self.runtime.mesh_builder,
            faces={axis + side: points[:, i] == extreme(points[:, i])
                   for i, axis in enumerate("xyz") for side, extreme in (("min", np.min), ("max", np.max))},
        )
        self.args = args

    def tensor(self, path, expected):
        tensor, _, _ = self.runtime.prepare(path, pilot.SEEDS[0])
        if audit.array_sha256(tensor.numpy()) != expected:
            raise ValueError(f"Preprocessed tensor differs from frozen inputs for {path.name}")
        return tensor

    @torch.no_grad()
    def predict(self, tensor, seed):
        start = perf_counter()
        latent, interior = grid.interior_run(self.runtime, tensor, seed)
        self.runtime.decoder.load_state_dict(self.runtime.states[1], strict=True)
        shell = grid.decode(self.runtime.decoder, latent, self.shell, self.shell_seeds[str(seed)])
        interior, shell = interior.numpy(), shell.numpy()
        sdf = np.empty((len(self.inside), 1), dtype=np.float32)
        sdf[self.inside], sdf[~self.inside] = interior, shell
        result = grid.mesh_prediction(self.mesh_runtime, sdf, seed)
        result.update(tensor=tensor.numpy(), latent=latent.numpy(), runtime_seconds=perf_counter() - start)
        result["boundary"] = multi.Runtime.boundary(self.mesh_runtime, result)
        result["boundary"]["inside_on_any_logical_grid_face"] = grid.logical_boundary(sdf, grid.NEW_N)
        result["hashes"] = pilot.numeric_hashes({"tensor": tensor.numpy(), "latent": latent.numpy(), "sdf": sdf})
        result["hashes"].update(interior_sdf=audit.array_sha256(interior), shell_sdf=audit.array_sha256(shell),
                                grid_labels=audit.array_sha256(sdf.ravel() < 0))
        return result


MODEL = None


def worker_init(args, provenance):
    global MODEL
    MODEL = Model(args, provenance)


def frame_identity(record):
    return {k: record[k] for k in ("tuber", "frame", "cultivar", "group")}


def replay_frame(record):
    model = MODEL
    obj = record["tuber"]
    local = model.args.input_dir / obj
    model.runtime.bind(local, record["annotation"])
    rgb = np.array(Image.open(local / "original_rgba.png"))
    y, x = np.nonzero(rgb[..., 3] > 0)
    zero = np.zeros((len(x), 3), dtype=np.int16)
    checks, arrays = [], {}
    expected = record["tensor_sha256"]["original"]
    with TemporaryDirectory(prefix="corepp-confirmation-noop-") as directory:
        noop_path = Path(directory) / "noop_rgba.png"
        Image.fromarray(pilot.apply_delta(rgb, y, x, zero)).save(noop_path)
        original = model.tensor(local / "original_rgba.png", expected)
        noop = model.tensor(noop_path, expected)
        for seed in pilot.SEEDS:
            a, b = (model.predict(tensor, seed) for tensor in (original, noop))
            surface = None if a["mesh"] is None or b["mesh"] is None else pilot.surface_pair(a["mesh"], b["mesh"])
            passed = (a["hashes"] == b["hashes"] and a["volume_ml"] == b["volume_ml"] and surface is not None
                      and surface["identical_mesh_arrays"] and surface["max_mm"] <= pilot.SURFACE_TOL_MM)
            checks.append({
                "seed": seed, "passed": passed, "original_hashes": a["hashes"], "noop_hashes": b["hashes"],
                "original_volume_ml": a["volume_ml"], "noop_volume_ml": b["volume_ml"], "boundary": a["boundary"],
                "surface_distance": surface, "mesh_failures": [r["mesh_failure"] for r in (a, b)],
            })
            if passed:
                arrays.update({f"latent_{seed}": a["latent"], f"sdf_{seed}": a["sdf"],
                               f"vertices_{seed}": np.array(a["mesh"].vertices), f"triangles_{seed}": np.array(a["mesh"].triangles)})
    result = frame_identity(record) | {"pairs": checks, "passed": sum(r["passed"] for r in checks)}
    if result["passed"] != len(pilot.SEEDS):
        return result | {"failure": "At least one expanded-grid no-op pair failed the exact replay"}
    path = model.args.cache_dir / f"{obj}.npz"
    np.savez(path, **arrays)
    return result | {"cache_sha256": audit.sha256(path), "failure": None}


def baseline_from_cache(archive, replay):
    seed = replay["seed"]
    latent, sdf = (archive[f"{name}_{seed}"] for name in ("latent", "sdf"))
    if any(audit.array_sha256(value) != replay["original_hashes"][name]
           for name, value in (("latent", latent), ("sdf", sdf))):
        raise ValueError(f"Baseline cache comparison failed at seed {seed}")
    mesh = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(archive[f"vertices_{seed}"]),
                                    o3d.utility.Vector3iVector(archive[f"triangles_{seed}"]))
    return {"mesh": mesh, "mesh_failure": None, "latent": latent, "sdf": sdf,
            "volume_ml": replay["original_volume_ml"], "boundary": replay["boundary"]}


def score_frame(record, replay):
    model = MODEL
    obj = record["tuber"]
    local = model.args.input_dir / obj
    model.runtime.bind(local, record["annotation"])
    path = model.args.cache_dir / f"{obj}.npz"
    if audit.sha256(path) != replay["cache_sha256"]:
        raise ValueError("Unchanged baseline cache hash does not match the no-op replay")
    tensors = {name: model.tensor(local / f"{name}_rgba.png", record["tensor_sha256"][name]) for name in multi.EDIT_NAMES}
    rows = []
    with np.load(path, allow_pickle=False) as cache:
        for paired in replay["pairs"]:
            seed = paired["seed"]
            baseline = baseline_from_cache(cache, paired)
            row = {"seed": seed, "shell_seed": model.shell_seeds[str(seed)],
                   "original_boundary": baseline["boundary"], "original_volume_ml": baseline["volume_ml"], "conditions": {}}
            for name, tensor in tensors.items():
                try:
                    result = model.predict(tensor, seed)
                    metrics = pilot.compare(baseline, result) if np.isfinite(result["sdf"]).all() else {}
                    metrics.update(boundary=result["boundary"], mesh_failure=result["mesh_failure"], hashes=result["hashes"])
                except EXPECTED_FAILURES as exc:
                    metrics = {"failure": f"{type(exc).__name__}: {exc}"}
                row["conditions"][name] = metrics
            surface = {name: val["surface_distance"]["mean_mm"] for name, val in row["conditions"].items()
                       if val.get("surface_distance") is not None}
            if len(surface) == len(multi.EDIT_NAMES):
                peel = [surface[name] for name in multi.EDIT_NAMES[1:]]
                row.update(pin_minus_mean_peel_mm=surface["pin"] - mean(peel),
                           pin_minus_seedwise_max_peel_mm=surface["pin"] - max(peel))
            rows.append(row)
    summary = multi.frame_summary(rows)
    return frame_identity(record) | {
        "pairs": rows, "summary": summary,
        "failure": None if "primary" in summary else "At least one edited condition or mesh failed",
    }


def worker(job):
    phase, row, prior = job
    try:
        result = replay_frame(row) if phase == "noop" else score_frame(row, prior)
    except EXPECTED_FAILURES as exc:
        result = frame_identity(row) | {"failure": f"{type(exc).__name__}: {exc}", "pairs": []}
    path = MODEL.args.out_dir / f"{phase}_rows" / f"{row['tuber']}.json"
    pilot.put_json(path, result)
    return result


def summarize(records):
    evaluable = [r for r in records if not r["failure"]]
    groups = sorted({r["group"] for r in evaluable})
    all_groups = sorted({r["group"] for r in records})
    by_group = {g: [r for r in evaluable if r["group"] == g] for g in groups}
    counts = np.array([len(by_group[g]) for g in groups])
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    draws = rng.integers(0, len(groups), size=(BOOTSTRAP_DRAWS, len(groups))) if groups else None
    result = {}
    for metric, key in zip(METRICS, ("primary", "pin_minus_strongest_peel"), strict=True):
        effect = lambda row: row["summary"][key]["median"]
        values = [effect(r) for r in evaluable]
        interval = None
        if draws is not None:
            sums = np.array([sum(effect(r) for r in by_group[g]) for g in groups])
            reps = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
            interval = np.quantile(reps, [0.025, 0.975]).tolist()
        leave_out = {}
        for group in all_groups:
            retained = [effect(row) for row in evaluable if row["group"] != group]
            leave_out[group] = {"n": len(retained), "mean_mm": mean(retained) if retained else None}
        result[metric] = {
            "selected_n": len(records), "evaluable_n": len(values),
            "mean_mm": mean(values) if values else None, "median_mm": median(values) if values else None,
            "positive": sum(v > 0 for v in values), "tied": sum(v == 0 for v in values), "negative": sum(v < 0 for v in values),
            "group_interval_95_mm": interval, "groups_evaluable": len(groups), "groups_selected": len(all_groups),
            "group_sizes_evaluable": dict(zip(groups, counts.tolist(), strict=True)),
            "leave_one_group_out": leave_out,
            "decision": ("descriptive_sparse_groups" if len(groups) < MIN_GROUPS else
                         "above_zero" if interval[0] > 0 else "not_above_zero"),
        }
    return result


def run_workers(args, frozen):
    out, phase = args.out_dir, args.phase
    freeze_hash = audit.sha256(out / "frozen_inputs.json")
    if phase == "noop":
        args.cache_dir.mkdir(parents=True, exist_ok=False)
        before, prior = None, {}
    else:
        before = audit.read_json(out / "no_op_replay.json")
        if before["frozen_inputs_sha256"] != freeze_hash:
            raise ValueError("No-op results belong to a different input freeze")
        prior = {r["tuber"]: r for r in before["frames"]}
        pilot.put_json(out / "score_started.json", {
            "stage": "one_score_started", "frozen_inputs_sha256": freeze_hash,
            "no_op_sha256": audit.sha256(out / "no_op_replay.json"),
        })
    (out / f"{phase}_rows").mkdir()
    records, jobs = {}, []
    for row in frozen["frames"]:
        obj = row["tuber"]
        previous = prior.get(obj)
        blocked = row["failure"] or (previous["failure"] if previous is not None else None)
        if blocked:
            records[obj] = frame_identity(row) | {"failure": blocked, "pairs": [],
                                                  "failure_stage": "input_freeze" if row["failure"] else "no_op_replay"}
        else:
            jobs.append((phase, row, previous))
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=context, initializer=worker_init,
                             initargs=(args, frozen["cpu_provenance"])) as pool:
        for result in pool.map(worker, jobs):
            records[result["tuber"]] = result
            print(f"{phase} {result['tuber']}: {result['failure'] or '16/16 seed sets complete'}", flush=True)
    ordered = [records[f["tuber"]] for f in frozen["frames"]]
    result = {"frozen_inputs_sha256": freeze_hash, "workers": args.workers, "frames": ordered}
    if phase == "score":
        result.update(no_op_sha256=audit.sha256(out / "no_op_replay.json"), summary=summarize(ordered),
                      bootstrap_draws=BOOTSTRAP_DRAWS, bootstrap_seed=BOOTSTRAP_SEED, min_evaluable_groups=MIN_GROUPS)
    pilot.put_json(out / ("no_op_replay.json" if phase == "noop" else "results.json"), result)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=("prepare", "seal", "noop", "score"))
    for name in ("source", "upstream", "released", "out-dir", "input-dir", "cache-dir"):
        p.add_argument(f"--{name}", type=Path, required=True)
    p.add_argument("--review", type=Path)
    p.add_argument("--workers", type=int, default=5)
    args = p.parse_args()
    frames, catalog = load_roster(args)
    if args.phase == "prepare":
        prepare(args, frames, catalog)
    elif args.phase == "seal":
        seal(args, frames)
    else:
        run_workers(args, load_frozen(args, frames))


if __name__ == "__main__":
    main()
