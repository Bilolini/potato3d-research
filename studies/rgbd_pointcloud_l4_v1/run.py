"""Train and compare a full center-frame RGB-D point regressor against archived L3."""

import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
from pathlib import Path
import sys
import time
from zipfile import ZipFile

import numpy as np
from PIL import Image
import torch
from torch import nn

from potato3d.calibration import depth_points
from studies.rgb_only_height_value_v1 import run as l3
from studies.rgb_predicted_height_v1 import run as archived

prior = l3.prior
HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "raft_pointcloud_weight_v1"
sys.path.insert(0, str(OLD))
from studies.raft_pointcloud_weight_v1 import run as pc

SEEDS = (133, 527, 2401)
N_POINTS = 1024
L1 = HERE.parent / "rgb_monocular_height_v1"
LEVELS = dict(L0="silhouette", L1="monocular", L2="learned_rgb", L3="camera", L4="pointcloud")


class RGBPointRAFT(pc.CompactPointRAFT):
    """Local metric coordinates and RGB, with the separate archived height cue."""

    def __init__(self):
        super().__init__()
        self.local1 = pc.layers((6, 32, 32, 64))

    def forward(self, x):
        points = x["xyz"]
        pos1 = pc.gather(points, x["anchors1"])
        relative1 = pc.gather(points, x["knn1"]) - pos1[:, :, None, :]
        color = pc.gather(x["rgb"], x["knn1"])
        feat1 = self.local1(torch.cat((relative1, color), dim=-1)).amax(dim=2)
        pos2 = pc.gather(pos1, x["anchors2"])
        relative2 = pc.gather(pos1, x["knn2"]) - pos2[:, :, None, :]
        feat2 = self.local2(torch.cat((relative2, pc.gather(feat1, x["knn2"])), dim=-1)).amax(dim=2)
        global_feat = self.global_encoder(torch.cat((pos2, feat2), dim=-1)).amax(dim=1)
        height = self.height(x["height"][:, None])
        return self.regression(torch.cat((global_feat, height), dim=-1))[:, 0]


def sources():
    paths = (Path(__file__), HERE / "protocol.md", OLD / "run.py", OLD / "inputs.py",
             l3.HERE / "frame_manifest.json", l3.HERE / "run.py", l3.HERE / "train_fit.json",
             l3.HERE / "train_features.csv", l3.HERE / "validation_features.csv",
             l3.HELD_OUT, prior.CAMERA, prior.WARNINGS, *(spec[0] for spec in prior.RESERVATIONS.values()))
    return {str(p.relative_to(prior.ROOT)): prior.sha(p) for p in paths}


def freeze(output):
    path = l3.HERE / "frame_manifest.json"
    base = prior.read_json(path)
    fit = prior.read_json(l3.HERE / "train_fit.json")
    if fit["manifest_sha256"] != prior.sha(path) or fit["training_features_sha256"] != prior.sha(l3.HERE / "train_features.csv"):
        raise ValueError("The L3 input provenance changed")
    if base["sources_sha256"][str(prior.CAMERA.relative_to(prior.ROOT))] != prior.sha(prior.CAMERA):
        raise ValueError("Released camera calibration differs")
    roster = base["roster"]
    ids = {r["tuber"] for r in roster}
    held = {r["tuber"] for r in prior.read_json(l3.HELD_OUT)["roster"]}
    if len(held) != 45 or len(ids) != 158 or ids & (held | set(prior.published_id_exclusions())):
        raise ValueError("Roster or holdout boundaries differ")
    if Counter(r["split"] for r in roster) != {"train": 118, "val": 40}:
        raise ValueError("Expected the archived 118/40 split")
    training = sorted((r["tuber"] for r in roster if r["split"] == "train"),
                      key=lambda t: hashlib.sha256(f"raft-pointcloud-inner-v1/133/{t}".encode()).hexdigest())
    prior.save_json(output / "frame_manifest.json", {
        "sources_sha256": sources(), "roster": roster, "camera_matrix_px": base["camera_matrix_px"],
        "depth_rule": base["depth_rule"], "height_reference_mm": base["belt_depth_mm"],
        "inner_validation_ids": training[:24], "inner_fit_ids": training[24:], "seeds": SEEDS,
        "epochs": pc.EPOCHS, "batch_size": pc.BATCH, "points": N_POINTS,
        "architecture": "RGBPointRAFT", "parameters": sum(p.numel() for p in RGBPointRAFT().parameters()),
        "prediction": "mean over three independently fitted seed predictions",
        "device": "CPU", "torch": torch.__version__,
    })
    print("Frozen exact L3 IDs, frames, architecture, training budget and three seeds.", flush=True)


def read_manifest(output):
    m = prior.read_json(output / "frame_manifest.json")
    if m["sources_sha256"] != sources():
        raise ValueError("Frozen input or analysis code changed")
    old = prior.read_json(l3.HERE / "frame_manifest.json")
    if m["roster"] != old["roster"] or m["torch"] != torch.__version__:
        raise ValueError("Frozen roster or PyTorch version differs")
    return m


def point_data(case, old, archives, matrix, fixed):
    members = case["inputs"]
    if not all(members.values()):
        raise ValueError("Frozen raw RGB-D frame unavailable")
    with Image.open(l3.member_data(archives, members["rgb"])) as file:
        if file.mode != "RGBA" or file.size != (1280, 720):
            raise ValueError("Expected the original full-resolution RGBA and alpha")
        rgba = np.asarray(file)
    with Image.open(l3.member_data(archives, members["depth"])) as file:
        depth = np.asarray(file)
    mask = rgba[:, :, 3] > 0
    if depth.shape != mask.shape or depth.dtype != np.uint16:
        raise ValueError("Expected aligned raw uint16 depth in millimeters")
    rule = fixed["depth_rule"]
    support = mask & (depth >= rule["min_z_inclusive_mm"]) & (depth < rule["max_z_exclusive_mm"])
    n = int(support.sum())
    proportion = n / max(1, int(mask.sum()))
    if n < rule["min_count"] or proportion < rule["min_fraction"]:
        raise ValueError("Insufficient L3 depth support")
    height = fixed["height_reference_mm"] - float(np.quantile(depth[support], rule["quantile"]))
    if height <= 0:
        raise ValueError("Nonpositive L3 camera height")
    if (height != float(old["height_mm"]) or n != int(old["valid_depth_pixels"])
            or int(mask.sum()) != int(old["mask_pixels"]) or proportion != float(old["valid_depth_fraction"])):
        raise RuntimeError(f"L3 input support or height did not replay: {case['tuber']}")
    yy, xx = np.nonzero(support)
    uv = np.column_stack((xx, yy))
    xyz = depth_points(depth, uv, matrix)
    projection = xyz @ matrix.T
    error = float(np.max(abs(projection[:, :2] / projection[:, 2:] - uv)))
    if error > 1e-8 or not np.array_equal(xyz[:, 2], depth[support]):
        raise RuntimeError("Metric depth or image-to-cloud projection failed")
    seed = int.from_bytes(hashlib.sha256(f"rgbd-l4-sample-v1/{case['tuber']}".encode()).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    sample = (np.sort(rng.choice(n, N_POINTS, replace=False)) if n >= N_POINTS
              else np.concatenate((np.arange(n), rng.choice(n, N_POINTS-n, replace=True))))
    points = xyz[sample]
    points = (points - points.mean(axis=0)) / 100.
    a = pc.data.fps(points, 64)
    anchors = points[a]
    b = pc.data.fps(anchors - anchors.mean(axis=0), 16)
    arrays = {"xyz": points.astype(np.float32), "rgb": rgba[yy[sample], xx[sample], :3].astype(np.float32) / 255.,
              "height": np.float32(height / 100.), "anchors1": a, "anchors2": b,
              "knn1": pc.data.groups(points, a, 2.), "knn2": pc.data.groups(anchors, b, 4.)}
    return arrays, {"height_mm": height, "source_points": n, "sample_points": len(sample),
                    "projection_max_error_px": error, "used_replacement": n < N_POINTS}


def input_store(output):
    return prior.ROOT / "outputs/rgbd_pointcloud_l4_v1" / f"{prior.sha(output / 'frame_manifest.json')}.npz"


def extract(output):
    start = time.perf_counter()
    m = read_manifest(output)
    previous = archived.indexed([*prior.read_csv(l3.HERE / "train_features.csv"),
                                 *prior.read_csv(l3.HERE / "validation_features.csv")])
    matrix = np.asarray(m["camera_matrix_px"])
    arrays, records = [], []
    member_names = {a["archive"] for r in m["roster"] for a in r["inputs"].values() if a}
    with ExitStack() as stack:
        archives = {name: stack.enter_context(ZipFile(l3.IMAGES / name)) for name in sorted(member_names)}
        for case in m["roster"]:
            tuber = case["tuber"]
            old = previous[tuber]
            if (case["suffix_px"], case["split"]) != (int(old["suffix_px"]), old["split"]):
                raise ValueError("Archived features refer to different frame or split")
            record = {"tuber": tuber, "split": case["split"], "suffix_px": case["suffix_px"],
                      "input_index": None, "failure": None}
            try:
                packed, checks = point_data(case, old, archives, matrix, m)
                record.update(input_index=len(arrays), **checks)
                arrays.append(packed)
            except l3.ERRORS as exc:
                record["failure"] = str(exc)
            records.append(record)
    cache = input_store(output)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.with_suffix(".tmp").open("wb") as stream:
        np.savez_compressed(stream, **{k: np.stack([r[k] for r in arrays]) for k in arrays[0]})
    cache.with_suffix(".tmp").replace(cache)
    prior.save_json(output / "inputs_manifest.json", {
        "frame_manifest_sha256": prior.sha(output / "frame_manifest.json"),
        "dataset_sha256": prior.sha(cache), "raw_archives": sorted(member_names), "records": records,
        "elapsed_s": time.perf_counter()-start,
    })
    print("Replayed exact L3 height and support for", len(arrays), "frames.", flush=True)


def load_data(output, m):
    info = prior.read_json(output / "inputs_manifest.json")
    cache = input_store(output)
    if (info["frame_manifest_sha256"] != prior.sha(output / "frame_manifest.json")
            or info["dataset_sha256"] != prior.sha(cache)
            or [(r["tuber"], r["suffix_px"]) for r in info["records"]]
            != [(r["tuber"], r["suffix_px"]) for r in m["roster"]]):
        raise ValueError("Point input cache differs")
    with np.load(cache, allow_pickle=False) as source:
        tensors = {k: torch.from_numpy(source[k]) for k in source.files}
    return tensors, archived.indexed(info["records"])


def fit_network(cloud, ids, by_id, truth, seed, epochs, inner=None):
    """Archived optimization loop with an RGB model factory and trait-neutral labels."""
    torch.manual_seed(seed)
    shuffle = torch.Generator().manual_seed(seed)
    net = RGBPointRAFT()
    opt = torch.optim.Adam(net.parameters(), lr=.001, weight_decay=.0001)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=pc.EPOCHS, eta_min=.0001)
    idx, y = pc.normalized_truth(ids, by_id, truth)
    mu, sd = y.mean().item(), y.std(unbiased=False).item()
    if sd <= 0:
        raise ValueError("Training target requires nonzero variation")
    scaled = (y-mu)/sd
    loss_fn = nn.SmoothL1Loss(beta=20./sd)
    losses = []
    if inner:
        inner_idx, inner_y = pc.normalized_truth(inner, by_id, truth)
    started = time.perf_counter()
    for _ in range(epochs):
        net.train()
        order = torch.randperm(len(idx), generator=shuffle)
        for positions in order.split(pc.BATCH):
            opt.zero_grad(set_to_none=True)
            loss = loss_fn(net(pc.batch(cloud, idx[positions])), scaled[positions])
            if not torch.isfinite(loss):
                raise ValueError(f"Nonfinite loss at seed {seed}")
            loss.backward()
            opt.step()
        scheduler.step()
        if inner:
            estimated = pc.inference(net, cloud, inner_idx, mu, sd)
            losses.append(float(torch.mean(torch.abs(estimated-inner_y))))
    return net, {"mean": mu, "sd": sd, "inner_maes": losses, "elapsed_s": time.perf_counter()-started}


def fit(output):
    m = read_manifest(output)
    cloud, cases = load_data(output, m)
    train = [r["tuber"] for r in m["roster"] if r["split"] == "train"]
    evaluation = [r["tuber"] for r in m["roster"] if r["split"] == "val"]
    test = [t for t in evaluation if cases[t]["input_index"] is not None]
    test_idx = torch.tensor([cases[t]["input_index"] for t in test], dtype=torch.long)
    targets = l3.read_targets(set(train))
    fit_dir = output / "fits"
    fit_dir.mkdir(exist_ok=False)
    predictions = {t: {} for t in evaluation}
    records = {}
    for trait in l3.TARGETS:
        truth = {t: targets[t][trait] for t in train
                 if cases[t]["input_index"] is not None and targets[t][trait] is not None}
        fit_ids = [t for t in train if t in truth]
        inner_ids = [t for t in m["inner_validation_ids"] if t in truth]
        pool = [t for t in m["inner_fit_ids"] if t in truth]
        if len(inner_ids) < 2 or len(pool) < 2:
            raise ValueError("Insufficient training-only rows")
        records[trait] = {"fit_ids": fit_ids, "inner_validation_ids": inner_ids,
                          "inner_fit_ids": pool, "excluded_ids": sorted(set(train)-set(fit_ids)),
                          "seeds": {}}
        by_seed = {}
        for seed in SEEDS:
            _, selection = fit_network(cloud, pool, cases, truth, seed, pc.EPOCHS, inner_ids)
            epoch = int(np.argmin(selection["inner_maes"])) + 1
            net, refit = fit_network(cloud, fit_ids, cases, truth, seed, epoch)
            checkpoint = fit_dir / f"{trait}_{seed}.pt"
            torch.save(net.state_dict(), checkpoint)
            start = time.perf_counter()
            estimates = pc.inference(net, cloud, test_idx, refit["mean"], refit["sd"]).tolist() if test else []
            prediction_s = time.perf_counter()-start
            if not np.isfinite(estimates).all():
                raise ValueError(f"Nonfinite prediction at {trait}/{seed}")
            by_seed[seed] = dict(zip(test, estimates, strict=True))
            records[trait]["seeds"][seed] = {"chosen_epoch": epoch, "selection": selection, "refit": refit,
                                              "checkpoint_sha256": prior.sha(checkpoint),
                                              "inference_s": prediction_s}
            print(f"{trait} seed {seed}: trained and predicted at epoch {epoch}.", flush=True)
        for t in evaluation:
            guesses = {s: by_seed[s].get(t) for s in SEEDS}
            predictions[t][trait] = {"seeds": guesses,
                                     "mean": sum(guesses.values()) / len(SEEDS) if t in test else None}
    prior.save_json(output / "train_fit.json", {
        "manifest_sha256": prior.sha(output / "frame_manifest.json"),
        "inputs_sha256": prior.sha(output / "inputs_manifest.json"), "traits": records,
    })
    prior.save_json(output / "predictions_before_targets.json", {
        "fit_sha256": prior.sha(output / "train_fit.json"),
        "rows": [{"tuber": t, "suffix_px": cases[t]["suffix_px"], "input_failure": cases[t]["failure"],
                  "predictions": predictions[t]} for t in evaluation],
    })
    print("Frozen all 40 validation prediction records before joining outcomes.", flush=True)


def historical(ids):
    prior_path = L1 / "per_potato.csv"
    history = prior.read_json(L1 / "results.json")
    if history["per_potato_sha256"] != prior.sha(prior_path):
        raise ValueError("Archived L0–L3 scores differ from their recorded hash")
    old = archived.indexed(prior.read_csv(prior_path))
    if set(old) != ids:
        raise ValueError("Archived L0–L3 cohort differs")
    features, scored, predictions, _ = archived.historical_targets(ids)
    for tuber in ids:
        check = old[tuber]
        for trait in l3.TARGETS:
            saved = predictions[tuber]["predictions"][trait]
            for name, key in (("silhouette", "mask_only"), ("camera", "depth_assisted")):
                archived.check_close(float(check[f"{trait}_{name}_prediction"]), saved[key], f"{tuber}/{trait}/{name}")
            archived.check_close(float(check[f"{trait}_reference"]), float(scored[tuber][f"{trait}_measured"]),
                                 f"{tuber}/{trait} measurement")
        archived.check_close(float(check["camera_height_mm"]), float(features[tuber]["height_mm"]), f"{tuber} height")
    return old


def summarize(rows, trait):
    cols = {a: f"{trait}_{a}_error" for a in LEVELS}
    common = [r for r in rows if all(r[k] is not None for k in cols.values())]
    arms = {a: {"scored": sum(r[k] is not None for r in rows),
                "mae": float(np.mean([r[k] for r in common])) if common else None}
            for a, k in cols.items()}
    computed = archived.paired_stats(common, cols["L4"], cols["L3"])
    against_l0 = {a: archived.paired_stats(common, cols[a], cols["L0"]) for a in ("L1", "L2", "L3", "L4")}
    seeds = {}
    for seed in SEEDS:
        key = f"{trait}_L4_{seed}_error"
        seeds[seed] = {"mae": float(np.mean([r[key] for r in common])) if common else None,
                       "against_L3": archived.paired_stats(common, key, cols["L3"])}
    return {"common_ids": [r["tuber"] for r in common], "arms": arms, "L4_minus_L3": computed,
            "against_L0": against_l0, "seeds": seeds,
            "seed_mae_sd": float(np.std([x["mae"] for x in seeds.values()], ddof=1)) if common else None}


def score(output):
    m = read_manifest(output)
    pred_path = output / "predictions_before_targets.json"
    save_path = output / "results.json"
    if save_path.exists():
        raise ValueError("The frozen evaluation has already been scored")
    p = prior.read_json(pred_path)
    fit_path = output / "train_fit.json"
    receipt = prior.read_json(fit_path)
    if (p["fit_sha256"] != prior.sha(fit_path)
            or receipt["manifest_sha256"] != prior.sha(output / "frame_manifest.json")
            or receipt["inputs_sha256"] != prior.sha(output / "inputs_manifest.json")):
        raise ValueError("Frozen prediction or fit provenance changed")
    if [(r["tuber"], r["suffix_px"]) for r in p["rows"]] != [
        (r["tuber"], r["suffix_px"]) for r in m["roster"] if r["split"] == "val"
    ]:
        raise ValueError("Frozen development predictions use a different roster")
    old = historical({r["tuber"] for r in p["rows"]})
    rows = []
    for record in p["rows"]:
        tuber = record["tuber"]
        saved = old[tuber]
        if record["suffix_px"] != int(saved["suffix_px"]):
            raise ValueError(f"Archived L0–L3 center differs: {tuber}")
        row = {k: record[k] for k in ("tuber", "suffix_px", "input_failure")}
        for trait in l3.TARGETS:
            target = float(saved[f"{trait}_reference"])
            row[f"{trait}_measured"] = target
            prediction = record["predictions"][trait]
            for level, arm in LEVELS.items():
                value = prediction["mean"] if level == "L4" else float(saved[f"{trait}_{arm}_prediction"])
                row[f"{trait}_{level}_prediction"] = value
                row[f"{trait}_{level}_error"] = abs(value - target) if value is not None else None
            for seed, value in prediction["seeds"].items():
                row[f"{trait}_L4_{seed}_prediction"] = value
                row[f"{trait}_L4_{seed}_error"] = abs(value - target) if value is not None else None
        rows.append(row)
    prior.write_csv(output / "per_potato.csv", rows)
    result = {trait: summarize(rows, trait) for trait in l3.TARGETS}
    prior.save_json(save_path, {
        "enrolled": len(rows), "traits": result, "prediction_sha256": prior.sha(pred_path),
        "per_potato_sha256": prior.sha(output / "per_potato.csv"),
        "input_failures": {r["tuber"]: r["input_failure"] for r in rows if r["input_failure"]},
    })
    print({trait: end["L4_minus_L3"] for trait, end in result.items()}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "extract", "fit", "score"))
    parser.add_argument("--out", type=Path, default=HERE)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    {"freeze": freeze, "extract": extract, "fit": fit, "score": score}[args.stage](args.out)
