"""Freeze and score a reference-free check of outer-view depth consistency."""

import argparse
from contextlib import ExitStack
import hashlib
import io
from itertools import product
from pathlib import Path
import sys
from time import perf_counter
from zipfile import BadZipFile, ZipFile

import numpy as np
from PIL import Image

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
PRIOR = STUDY.parent / "sam2_raft_end_to_end_v1"
sys.path.insert(0, str(PRIOR))
import common as c
import alignment as align
from register import camera
from studies.sam2_center_weight_v1 import run as sam

REPEATS = 20
VIEW_ROLES = ("lower", "center", "upper")
METHODS = ("center", "fusion", "filtered", "random")
METRICS = ("coverage_fraction", "far_fraction", "points", "new_area_mm2", "lost_center_area_mm2",
           "retained_new_area_mm2", "retained_new_fraction")
FAILURES = (ValueError, RuntimeError, OSError, BadZipFile, KeyError)


def verified(path, expected):
    if c.prep.digest(path) != expected:
        raise ValueError(f"Archived artifact changed: {path}")
    return path


def archived_clouds(tuber, cloud_hash):
    path = verified(c.OUTPUT / "predicted" / f"{tuber}.npz", cloud_hash)
    with np.load(path, allow_pickle=False) as file:
        return file["B"], file["D"]


def depth_scatter(depth, support):
    valid = (support[1:-1, 1:-1] & support[:-2, 1:-1] & support[2:, 1:-1]
             & support[1:-1, :-2] & support[1:-1, 2:])
    z = depth.astype(float)
    residual = z[1:-1, 1:-1] - (z[:-2, 1:-1] + z[2:, 1:-1] + z[1:-1, :-2] + z[1:-1, 2:]) / 4
    values = residual[valid]
    if not len(values):
        raise ValueError("No supported depth stencil for uncertainty")
    mad = float(np.median(np.abs(values - np.median(values))))
    return {"stencils": len(values), "residual_mad_mm": mad,
            "scatter_mm": max(.5, 1.4826 * mad / np.sqrt(1.25))}


def check_view(points, transform, matrix, depth, support, tolerance):
    """Return contradiction, usable observation, and possible occlusion masks."""
    target = align.apply(points, transform)
    z = target[:, 2]
    projections = target @ matrix.T
    pos = np.flatnonzero(z > 0)
    x, y = np.floor(projections[pos, :2] / z[pos, None]).astype(int).T
    inside = (x >= 0) & (y >= 0) & (x < depth.shape[1]-1) & (y < depth.shape[0]-1)
    pos, x, y = pos[inside], x[inside], y[inside]
    ys, xs = y[None, :] + np.array([[0], [0], [1], [1]]), x[None, :] + np.array([[0], [1], [0], [1]])
    valid = support[ys, xs].all(axis=0)
    pos = pos[valid]
    depths = depth[ys[:, valid], xs[:, valid]].astype(float)
    observed = np.zeros(len(points), dtype=bool)
    front, behind = observed.copy(), observed.copy()
    observed[pos] = True
    front[pos] = depths.min(axis=0) - z[pos] > tolerance
    behind[pos] = z[pos] - depths.max(axis=0) > tolerance
    return front, observed, behind


def check_projection():
    depth = np.full((4, 5), 100, dtype=np.uint16)
    support = np.ones_like(depth, dtype=bool)
    support[0, 3] = False
    z = np.array([95., 96., 104., 105., 95., 95., -95.])
    uv = np.array([[.5, .5]]*4 + [[3.2, .5], [5., .5], [.5, .5]])
    target = align.unproject(uv, z, np.eye(3))
    first = align.translation([24., -8., 2.])
    other = align.translation([16., 31., -17.])
    source = align.apply(align.apply(target, other), np.linalg.inv(first))
    front, valid, behind = check_view(source, np.linalg.inv(other) @ first, np.eye(3), depth, support, 4.)
    assert front.tolist() == [True, False, False, False, False, False, False]
    assert valid.tolist() == [True, True, True, True, False, False, False]
    assert behind.tolist() == [False, False, False, True, False, False, False]
    return {"test_depth_mm": 100, "test_tolerance_mm": 4, "front": front.tolist(),
            "usable_depth": valid.tolist(), "possible_occlusion": behind.tolist()}


def freeze_sources():
    sources = [Path(__file__), STUDY / "protocol.md", c.prep.CAMERA, PRIOR / "frame_manifest.json",
               PRIOR / "predicted_input_ledger.json", PRIOR / "tracking_replay.json",
               c.PILOT / "alignment.py", Path(sam.__file__)]
    return {str(path.relative_to(ROOT)): c.prep.digest(path) for path in sources}


def load_views(case, record, tracking, archives, k):
    tuber = case["tuber"]
    track_path = verified(c.track_path(tuber), tracking["tracking_record_sha256"])
    track = c.prep.read_json(track_path)
    mask_path = verified(track_path.with_suffix(".npz"), tracking["mask_sha256"])
    if track["mask_sha256"] != tracking["mask_sha256"] or record["tracking_record_sha256"] != tracking["tracking_record_sha256"]:
        raise ValueError("Archived mask, replay and pose records disagree")
    frames = {f["suffix"]: f for f in case["links_rgbd"]}
    archived_views = {f["suffix"]: f for f in record["views"]}
    views = []
    with np.load(mask_path, allow_pickle=False) as packed:
        for name, suffix in zip(VIEW_ROLES, case["selected"], strict=True):
            member = frames[suffix]["depth"]
            raw = c.prep.member_bytes(archives[member["archive"]], member)
            with Image.open(io.BytesIO(raw)) as image:
                depth = np.asarray(image)
            mask = c.unpack(packed[str(suffix)])
            if depth.dtype != np.uint16 or depth.shape != mask.shape:
                raise ValueError("Expected 16-bit axial depth on the archived RGB grid")
            support, bounds = sam.filtered_support(depth, mask, record["measured_thickness_mm"])
            prior = archived_views[suffix]
            if prior["error"] or (int(support.sum()), int(mask.sum()), list(bounds)) != (
                    prior["support_pixels"], prior["mask_pixels"], prior["bounds_mm"]):
                raise ValueError(f"Archived depth support did not replay: {tuber}/{suffix}")
            y, x = np.nonzero(support)
            views.append({"points": align.unproject(np.column_stack((x, y)), depth[y, x], k),
                          "support": support, "depth": depth, "suffix": suffix, "role": name,
                          "depth_sha256": hashlib.sha256(raw).hexdigest(),
                          "depth_uncertainty": depth_scatter(depth, support)})
    return views


def archived_alignment(case, record):
    sequence = [f["suffix"] for f in case["links_rgbd"]]
    links = record["links"]
    if [(r["source"], r["target"]) for r in links] != list(zip(sequence[:-1], sequence[1:])):
        raise ValueError("Archived adjacent links differ from frozen frame sequence")
    transforms = [np.asarray(r["transform"], dtype=float) for r in links]
    if any(r["failure"] for r in links) or not all(c.prep.safe_rigid(t) for t in transforms):
        raise ValueError("Invalid archived rigid transform")
    rmse = np.array([r["ransac_rmse_mm"] for r in links])
    if not np.isfinite(rmse).all() or (rmse < 0).any():
        raise ValueError("Archived registration uncertainty unavailable")
    selected = [sequence.index(x) for x in case["selected"]]
    composed = align.to_center(transforms, selected[1])
    poses = [np.array(record["fused_to_center"][str(s)]) for s in case["selected"]]
    if not all(np.array_equal(composed[i], pose) for i, pose in zip(selected, poses, strict=True)):
        raise ValueError("Composed registration did not replay")
    return selected, poses, rmse


def freeze_case(case, record, tracking, archives, k, roster_index, out):
    tuber = case["tuber"]
    if record["selected"] != case["selected"] or any(record["failures"][key] for key in ("B", "D")):
        raise ValueError("Cached cloud missing or for a different triplet")
    views = load_views(case, record, tracking, archives, k)
    sequence_ids, poses, rmse = archived_alignment(case, record)
    center, fused = archived_clouds(tuber, record["cloud_sha256"])
    replay = np.concatenate([align.apply(v["points"], pose) for v, pose in zip(views, poses, strict=True)])
    if not np.array_equal(center, views[1]["points"]) or not np.array_equal(fused, replay):
        raise ValueError("Source view provenance does not reconstruct archived point arrays exactly")
    counts = [len(v["points"]) for v in views]
    portions = np.split(np.arange(len(fused)), np.cumsum(counts)[:-1])
    rejected = np.zeros(len(fused), dtype=bool)
    raw_before = perf_counter()
    checks, source_masks = [], []
    for src in (0, 2):
        source, points = views[src], views[src]["points"]
        drop, evidence = np.zeros(len(points), dtype=bool), np.zeros(len(points), dtype=bool)
        for dst in (i for i in range(3) if i != src):
            target = views[dst]
            a, b = sorted((sequence_ids[src], sequence_ids[dst]))
            motion = float(np.linalg.norm(rmse[a:b]))
            z_src = source["depth_uncertainty"]["scatter_mm"]
            z_dst = target["depth_uncertainty"]["scatter_mm"]
            tolerance = float(2 * np.linalg.norm([motion, z_src, z_dst]))
            mapping = np.linalg.inv(poses[dst]) @ poses[src]
            front, observed, behind = check_view(points, mapping, k, target["depth"], target["support"], tolerance)
            drop |= front
            evidence |= observed
            checks.append({"source": VIEW_ROLES[src], "target": VIEW_ROLES[dst], "links": b-a,
                           "registration_scale_mm": motion, "tolerance_mm": tolerance,
                           "valid_observations": int(observed.sum()), "contradictions": int(front.sum()),
                           "possible_occlusions": int(behind.sum()), "no_observation": int((~observed).sum())})
        rejected[portions[src]] = drop
        source_masks.append({"source": VIEW_ROLES[src], "points": len(points),
                             "rejected": int(drop.sum()), "no_evidence_in_either_view": int((~evidence).sum())})
    rng = np.random.default_rng(c.SEED + roster_index)
    random_drop = np.zeros((REPEATS, len(fused)), dtype=bool)
    for row, src in product(random_drop, (0, 2)):
        n_remove = int(rejected[portions[src]].sum())
        row[rng.choice(portions[src], n_remove, replace=False)] = True
    array_path = out / f"{tuber}.npz"
    np.savez_compressed(array_path, rejected=rejected, random_drop=random_drop)
    return {"tuber": tuber, "frames": case["selected"], "cloud_sha256": record["cloud_sha256"],
            "tracking_mask_sha256": tracking["mask_sha256"], "raw_view_points": counts,
            "raw_depth_sha256": [v["depth_sha256"] for v in views],
            "depth_uncertainty": {v["role"]: v["depth_uncertainty"] for v in views},
            "checks": checks, "added_views": source_masks, "removed_points": int(rejected.sum()),
            "decision_sha256": c.prep.digest(array_path), "random_seed": c.SEED + roster_index,
            "wall_s_filter_and_control": perf_counter()-raw_before, "failure": None}


def freeze(out):
    target = out / "frozen_filter.json"
    if target.exists():
        raise FileExistsError(target)
    roster = [r for r in c.prep.read_json(PRIOR / "frame_manifest.json")["roster"] if r["analysis"] == "geometry"]
    if len(c.by_tuber(roster)) != 10:
        raise ValueError("Expected the ten archived geometry potatoes")
    ledger = c.by_tuber(c.prep.read_json(PRIOR / "predicted_input_ledger.json")["records"])
    tracking = c.by_tuber(c.prep.read_json(PRIOR / "tracking_replay.json")["rows"])
    names = {f["depth"]["archive"] for r in roster for f in r["links_rgbd"] if f["suffix"] in r["selected"]}
    k = camera()
    preflight = check_projection()
    rows = []
    with ExitStack() as stack:
        archives = c.prep.open_images(stack, names)
        for i, case in enumerate(roster):
            tuber = case["tuber"]
            try:
                path = verified(c.OUTPUT / "predicted" / f"{tuber}.json", ledger[tuber]["sha256"])
                row = freeze_case(case, c.prep.read_json(path), tracking[tuber], archives, k, i, out)
            except FAILURES as error:
                row = {"tuber": tuber, "frames": case["selected"], "failure": str(error)}
            rows.append(row)
            print(tuber, row["failure"] or f"{row['removed_points']} added points rejected", flush=True)
    c.prep.write_json(target, {"stage": "filter_and_random_controls_frozen_before_sfm", "sources_sha256": freeze_sources(),
                              "random_repeats": REPEATS, "projection_preflight": preflight, "rows": rows})


def summarize_measures(values, covered, center, new, area):
    retained = covered & new
    return values | {
        "new_area_mm2": float((covered & ~center).mean() * area),
        "lost_center_area_mm2": float((~covered & center).mean() * area),
        "retained_new_area_mm2": float(retained.mean() * area),
        "retained_new_fraction": float(retained.sum() / new.sum()) if new.any() else None,
    }


def evaluate_case(row, plan, old_row, out, decision, geo, archive):
    started = perf_counter()
    if plan["selected_suffixes"] != row["frames"]:
        raise ValueError("Reference plan has a different selected frame triplet")
    center, fused = archived_clouds(row["tuber"], row["cloud_sha256"])
    removed, controls = decision
    anchor = align.in_mm(plan["center_to_sfm_m"])
    ref = geo.load_reference(archive, plan["reference"])
    samples, _ = geo.sample_surface(ref, geo.SAMPLES, c.prep.SEED)
    scene = geo.mesh_scene(ref)
    center, fused = (align.apply(cloud, anchor) for cloud in (center, fused))

    def measure(cloud):
        return geo.score_cloud(align.voxel(cloud, 1.), samples, scene)

    center_scores, c_cover = measure(center)
    fused_scores, f_cover = measure(fused)
    new = f_cover & ~c_cover
    result = {}
    for method, arm, metrics, covered in (("center", "B", center_scores, c_cover),
                                           ("fusion", "D", fused_scores, f_cover)):
        if any(abs(v-float(old_row[f"{arm}_{k}"])) > 1e-10 for k, v in metrics.items()):
            raise ValueError(f"Archived {method} score did not replay")
        result[method] = summarize_measures(metrics, covered, c_cover, new, ref.area)
    if abs(result["fusion"]["new_area_mm2"]-float(old_row["D_new_area_mm2"])) > 1e-8:
        raise ValueError("Archived newly covered area did not replay")
    metrics, covered = measure(fused[~removed])
    result["filtered"] = summarize_measures(metrics, covered, c_cover, new, ref.area)
    repeats = []
    for r in controls:
        metrics, covered = measure(fused[~r])
        repeats.append(summarize_measures(metrics, covered, c_cover, new, ref.area))
    result["random"] = {k: float(np.mean([rep[k] for rep in repeats])) if repeats[0][k] is not None else None
                        for k in repeats[0]}
    return result, repeats, perf_counter() - started


def read_decisions(row, out):
    path = verified(out / f"{row['tuber']}.npz", row["decision_sha256"])
    with np.load(path, allow_pickle=False) as arrays:
        remove, controls = arrays["rejected"], arrays["random_drop"]
    counts = row["raw_view_points"]
    if remove.shape != (sum(counts),) or controls.shape != (REPEATS, len(remove)):
        raise ValueError("Frozen selection shape differs")
    offset = 0
    for role, n in zip(VIEW_ROLES, counts, strict=True):
        region = slice(offset, offset+n)
        n_reject = remove[region].sum()
        if (role == "center" and n_reject) or not (controls[:, region].sum(axis=1) == n_reject).all():
            raise ValueError("Random control failed to match per-view deletion count or center was changed")
        offset += n
    return remove, controls


def paired(rows, first, second, metric):
    values = [r[f"{first}_{metric}"] - r[f"{second}_{metric}"] for r in rows
              if r.get(f"{first}_{metric}") is not None and r.get(f"{second}_{metric}") is not None]
    if not values:
        return {"n": 0, "mean": None, "interval_95": None}
    rng = np.random.default_rng(c.SEED)
    samples = rng.choice(values, (c.DRAWS, len(values)), replace=True)
    return {"n": len(values), "mean": float(np.mean(values)),
            "interval_95": np.quantile(samples.mean(axis=1), [.025, .975]).tolist()}


def score(out):
    destination = out / "results.json"
    if destination.exists():
        raise FileExistsError(destination)
    frozen = out / "frozen_filter.json"
    record = c.prep.read_json(frozen)
    if (record["stage"] != "filter_and_random_controls_frozen_before_sfm" or
            record["sources_sha256"] != freeze_sources() or record["random_repeats"] != REPEATS):
        raise ValueError("Protocol, inputs or filter decisions changed after freeze")
    decisions = {r["tuber"]: read_decisions(r, out) for r in record["rows"] if not r["failure"]}
    import score as geo

    plans = c.by_tuber(c.prep.read_json(c.PILOT / "frame_manifest.json")["roster"])
    old = c.by_tuber(c.csv_rows(PRIOR / "geometry_per_potato.csv"))
    metric_check = geo.metric_check()
    rows, repeat_rows = [], []
    with ZipFile(c.prep.MESHES) as archive:
        for f in record["rows"]:
            tuber = f["tuber"]
            row = {"tuber": tuber, **dict(zip(VIEW_ROLES, f["frames"], strict=True)), "failure": f["failure"]}
            if not row["failure"]:
                row.update(added_points=sum(f["raw_view_points"][::2]), removed_points=f["removed_points"],
                           tolerance_min_mm=min(r["tolerance_mm"] for r in f["checks"]),
                           tolerance_max_mm=max(r["tolerance_mm"] for r in f["checks"]))
                try:
                    values, repeats, wall = evaluate_case(f, plans[tuber], old[tuber], out, decisions[tuber], geo, archive)
                    row.update({f"{arm}_{k}": v for arm, res in values.items() for k, v in res.items()})
                    row["scoring_wall_s"] = wall
                    repeat_rows.extend({"tuber": tuber, "draw": i, **r} for i, r in enumerate(repeats, 1))
                except FAILURES as error:
                    row["failure"] = str(error)
            rows.append(row)
            print(tuber, row["failure"] or f"retained {row['filtered_retained_new_fraction']:.1%}", flush=True)
    c.write_csv(out / "per_potato.csv", rows)
    if repeat_rows:
        c.write_csv(out / "random_repeats.csv", repeat_rows)
    means = {}
    for method, metric in product(METHODS, METRICS):
        key = f"{method}_{metric}"
        values = [r[key] for r in rows if r.get(key) is not None]
        means[key] = float(np.mean(values)) if values else None
    paired_comparisons = {f"{a}_minus_{b}": {k: paired(rows, a, b, k) for k in
                          ("coverage_fraction", "far_fraction", "retained_new_fraction", "retained_new_area_mm2")}
                          for a, b in (("filtered", "fusion"), ("filtered", "random"))}
    c.prep.write_json(destination, {
        "frozen_sha256": c.prep.digest(frozen), "reference_manifest_sha256": c.prep.digest(c.PILOT / "frame_manifest.json"),
        "archive_score_sha256": c.prep.digest(PRIOR / "geometry_per_potato.csv"), "metrics_preflight": metric_check,
        "scored": sum(not r["failure"] for r in rows), "enrolled": len(rows), "means": means,
        "paired_comparisons": paired_comparisons, "rows": rows,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "score"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"freeze": freeze, "score": score}[args.phase](args.out)


if __name__ == "__main__":
    main()
