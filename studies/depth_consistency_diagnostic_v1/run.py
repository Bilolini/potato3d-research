"""Freeze depth-discrepancy scores, then evaluate their ranking of raw SfM errors."""

import argparse
from contextlib import ExitStack
import csv
import gzip
from pathlib import Path
import sys
from zipfile import ZipFile

import numpy as np

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
sys.path.insert(0, str(ROOT))
from studies.depth_consistency_fusion_v1 import run as prior

c = prior.c
align = prior.align
BASE_FREEZE = prior.STUDY / "frozen_filter.json"
GEOMETRY_ROSTER = c.PILOT / "frame_manifest.json"
RAWDIST_MM = 2.


def sources():
    paths = (Path(__file__), STUDY / "protocol.md", BASE_FREEZE, Path(prior.__file__), GEOMETRY_ROSTER)
    return {str(p.relative_to(ROOT)): c.prep.digest(p) for p in paths}


def signed_discrepancy(points, transform, matrix, depth, support):
    """Closest depth of the enclosing four supported pixels minus projected camera Z."""
    target = align.apply(points, transform)
    z = target[:, 2]
    positive = np.flatnonzero(z > 0.)
    projected = target[positive] @ matrix.T
    x, y = np.floor(projected[:, :2] / z[positive, None]).astype(int).T
    inside = (x >= 0) & (x < depth.shape[1]-1) & (y >= 0) & (y < depth.shape[0]-1)
    index, x, y = positive[inside], x[inside], y[inside]
    ys = y[None, :] + np.array([[0], [0], [1], [1]])
    xs = x[None, :] + np.array([[0], [1], [0], [1]])
    valid = support[ys, xs].all(axis=0)
    index = index[valid]
    result = np.full(len(points), np.nan)
    result[index] = depth[ys[:, valid], xs[:, valid]].min(axis=0) - z[index]
    return result


def freeze_case(old, case, prediction, tracking, archives, matrix, out):
    tuber = old["tuber"]
    if old["frames"] != case["selected"] or prediction["cloud_sha256"] != old["cloud_sha256"]:
        raise ValueError("Frozen frame or cloud cache mismatch")
    if tracking["mask_sha256"] != old["tracking_mask_sha256"]:
        raise ValueError("Frozen tracking mask mismatch")
    views = prior.load_views(case, prediction, tracking, archives, matrix)
    if [v["depth_sha256"] for v in views] != old["raw_depth_sha256"]:
        raise ValueError("Frozen depth frames changed")
    counts = [len(v["points"]) for v in views]
    if counts != old["raw_view_points"]:
        raise ValueError("Frozen source point counts changed")
    _, poses, _ = prior.archived_alignment(case, prediction)
    center, fused = prior.archived_clouds(tuber, old["cloud_sha256"])
    lifted = [align.apply(v["points"], t) for v, t in zip(views, poses, strict=True)]
    if not np.array_equal(center, views[1]["points"]) or not np.array_equal(fused, np.concatenate(lifted)):
        raise ValueError("Raw point order failed replay")

    pairs = {(p["source"], p["target"]): p for p in old["checks"]}
    scores, counts_by_point = [], []
    for src in (0, 2):
        source = views[src]
        discrepancies = []
        for dst in (i for i in range(3) if i != src):
            target = views[dst]
            pair = pairs[source["role"], target["role"]]
            tolerance = pair["tolerance_mm"]
            mapping = np.linalg.inv(poses[dst]) @ poses[src]
            signed = signed_discrepancy(source["points"], mapping, matrix, target["depth"], target["support"])
            old_front, old_usable, _ = prior.check_view(source["points"], mapping, matrix, target["depth"],
                                                       target["support"], tolerance)
            usable = np.isfinite(signed)
            if (not np.array_equal(usable, old_usable) or not np.array_equal(signed > tolerance, old_front)
                    or usable.sum() != pair["valid_observations"] or old_front.sum() != pair["contradictions"]):
                raise ValueError("Continuous discrepancy did not replay an archived view check")
            discrepancies.append(signed / tolerance)
        scores.append(np.fmax(*discrepancies))
        counts_by_point.append(np.sum(np.isfinite(discrepancies), axis=0).astype(np.uint8))
    score, usable_views = np.concatenate(scores), np.concatenate(counts_by_point)
    index = np.r_[np.arange(counts[0]), np.arange(sum(counts[:2]), sum(counts))].astype(np.int32)
    old_path = prior.verified(prior.STUDY / f"{tuber}.npz", old["decision_sha256"])
    with np.load(old_path, allow_pickle=False) as old_arrays:
        if not np.array_equal(score > 1., old_arrays["rejected"][index]):
            raise ValueError("Score > 1 disagrees with archived rejection mask")
    counts_no_usable = int((usable_views == 0).sum())
    if counts_no_usable != sum(r["no_evidence_in_either_view"] for r in old["added_views"]):
        raise ValueError("Unobservable point count differs from archive")
    destination = out / "scores" / f"{tuber}.npz"
    np.savez_compressed(destination, fused_index=index, score=score, usable_views=usable_views)
    return {"tuber": tuber, "frames": old["frames"], "cloud_sha256": old["cloud_sha256"],
            "points": len(score), "without_score": counts_no_usable, "scores_sha256": c.prep.digest(destination)}


def freeze(out):
    path = out / "frozen_scores.json"
    if path.exists():
        raise FileExistsError(path)
    archived = c.prep.read_json(BASE_FREEZE)
    if archived["sources_sha256"] != prior.freeze_sources():
        raise ValueError("Frozen depth-consistency sources changed")
    expected = archived["rows"]
    if len(c.by_tuber(expected)) != 10 or any(row["failure"] for row in expected):
        raise ValueError("Expected complete archived ten-potato input roster")
    cases = {r["tuber"]: r for r in c.prep.read_json(prior.PRIOR / "frame_manifest.json")["roster"]
             if r["analysis"] == "geometry"}
    if set(cases) != {r["tuber"] for r in expected}:
        raise ValueError("Archived geometry roster changed")
    ledger = c.by_tuber(c.prep.read_json(prior.PRIOR / "predicted_input_ledger.json")["records"])
    tracking = c.by_tuber(c.prep.read_json(prior.PRIOR / "tracking_replay.json")["rows"])
    names = {f["depth"]["archive"] for case in cases.values() for f in case["links_rgbd"] if f["suffix"] in case["selected"]}
    matrix = prior.camera()
    prior.check_projection()
    rows = []
    (out / "scores").mkdir()
    with ExitStack() as stack:
        archives = c.prep.open_images(stack, names)
        for old in expected:
            tuber = old["tuber"]
            cached = prior.verified(c.OUTPUT / "predicted" / f"{tuber}.json", ledger[tuber]["sha256"])
            row = freeze_case(old, cases[tuber], c.prep.read_json(cached), tracking[tuber], archives, matrix, out)
            rows.append(row)
            print(f"{tuber}: {row['points']:,} saved scores, {row['without_score']:,} without usable depth", flush=True)
    c.prep.write_json(path, {"stage": "continuous_scores_frozen_before_reference_meshes",
                            "sources_sha256": sources(), "rows": rows})


def ranking(score, labels, index):
    """Descending scores, with stable ordering of fused point indices at the decile cutoff."""
    order = np.lexsort((index, -score))
    n = len(order)
    if not n:
        return {"top_points": 0, "top_errors": 0, "top_fraction": None, "average_precision": None}, None
    k = (n + 9) // 10
    ordered_score = score[order]
    ordered_labels = labels[order]
    cumulative = ordered_labels.cumsum()
    cutoff = ordered_score[k-1]
    thresholds = np.r_[np.flatnonzero(ordered_score[:-1] != ordered_score[1:]), n-1]
    precision = cumulative[thresholds] / (1 + thresholds)
    if cumulative[-1]:
        recall = cumulative[thresholds] / cumulative[-1]
        average_precision = float(np.dot(precision, np.diff(np.r_[0., recall])))
        curve = (ordered_score[thresholds], recall, precision, 1 + thresholds)
    else:
        average_precision, curve = None, None
    return {"top_points": k, "top_errors": int(cumulative[k-1]), "top_fraction": float(cumulative[k-1]/k),
            "top_cutoff": float(cutoff), "top_cutoff_tied_points": int((ordered_score == cutoff).sum()),
            "average_precision": average_precision}, curve


def fraction(labels):
    return float(labels.mean()) if len(labels) else None


def evaluate_case(row, arrays, plan, archive, geo, out):
    tuber = row["tuber"]
    if row["frames"] != plan["selected_suffixes"]:
        raise ValueError("Reference pose does not match the selected triplet")
    _, cloud = prior.archived_clouds(tuber, row["cloud_sha256"])
    score, views, index = (arrays[k] for k in ("score", "usable_views", "fused_index"))
    if not np.array_equal(np.isfinite(score), views > 0) or (views == 0).sum() != row["without_score"]:
        raise ValueError("Frozen score eligibility mismatch")
    ref = geo.load_reference(archive, plan["reference"])
    anchor = align.in_mm(plan["center_to_sfm_m"])
    distance = geo.mesh_distance(align.apply(cloud[index], anchor), geo.mesh_scene(ref))
    if len(distance) != row["points"] or not np.isfinite(distance).all():
        raise ValueError("Missing or invalid raw-point SfM distances")
    inaccurate = distance > RAWDIST_MM
    np.savez_compressed(out / "labels" / f"{tuber}.npz", fused_index=index, distance_mm=distance, inaccurate=inaccurate)

    valid = views > 0
    usable, missing = inaccurate[valid], inaccurate[~valid]
    stats, curve = ranking(score[valid], usable, index[valid])
    stats.update(tuber=tuber, raw_added_points=len(inaccurate), all_errors=int(inaccurate.sum()),
                 all_prevalence=fraction(inaccurate), usable_points=int(valid.sum()), usable_errors=int(usable.sum()),
                 usable_prevalence=fraction(usable), missing_points=len(missing), missing_errors=int(missing.sum()),
                 missing_prevalence=fraction(missing))
    for value, key in (("top_fraction", "top_minus_usable"), ("average_precision", "ap_minus_usable")):
        stats[key] = stats[value] - stats["usable_prevalence"] if stats[value] is not None else None
    stats["top_recall"] = stats["top_errors"] / stats["usable_errors"] if stats["usable_errors"] else None
    return stats, curve


def plot(out, rows, curves):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.ticker import PercentFormatter

    fig, axes = plt.subplots(2, 5, figsize=(14, 5.7), sharex=True, sharey=True, layout="constrained")
    fig.suptitle("Does cross-view depth discrepancy rank inaccurate added points?", fontsize=15, fontweight="bold")
    for r, ax in zip(rows, axes.flat, strict=True):
        tuber = r["tuber"]
        ax.set_title(tuber, loc="left", fontsize=10, fontweight="bold")
        ax.set(xlim=(0, 1), ylim=(0, 1), xticks=[0, .5, 1], yticks=[0, .5, 1])
        ax.grid(axis="y", color="#dce3e6", linewidth=.6)
        ax.spines[["top", "right"]].set_visible(False)
        if tuber not in curves:
            ax.text(.06, .75, "Curve unavailable", transform=ax.transAxes)
            continue
        _, recall, precision, _ = curves[tuber]
        ax.step(np.r_[0., recall], np.r_[1., precision], where="pre", color="#1d7263", linewidth=1.35)
        ax.axhline(r["usable_prevalence"], color="#6e7885", linestyle="--", linewidth=.9)
        ax.scatter(r["top_recall"], r["top_fraction"], s=20, color="#a55324", zorder=4)
        ax.text(.04, .91, f"AP {r['average_precision']:.1%}  ·  baseline {r['usable_prevalence']:.1%}",
                transform=ax.transAxes, fontsize=8.5, va="top")
    axes[0,0].xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    axes[0,0].yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    fig.supxlabel("Recall of inaccurate scored points   ·   Dot marks the highest-scoring tenth", fontsize=10)
    fig.supylabel("Precision", fontsize=10)
    fig.savefig(out / "precision_recall.png", dpi=180)
    plt.close(fig)


def evaluate(out):
    frozen_path = out / "frozen_scores.json"
    frozen = c.prep.read_json(frozen_path)
    if frozen["stage"] != "continuous_scores_frozen_before_reference_meshes" or frozen["sources_sha256"] != sources():
        raise ValueError("Score receipt does not match frozen protocol or sources")
    target = out / "results.json"
    if target.exists():
        raise FileExistsError(target)
    scores = {}
    for row in frozen["rows"]:
        path = prior.verified(out / "scores" / f"{row['tuber']}.npz", row["scores_sha256"])
        with np.load(path, allow_pickle=False) as file:
            scores[row["tuber"]] = dict(file)
    import score as geo

    geo.metric_check()
    archive_scores = c.by_tuber(c.csv_rows(prior.STUDY / "per_potato.csv"))
    plans = c.by_tuber(c.prep.read_json(GEOMETRY_ROSTER)["roster"])
    rows, curves = [], {}
    (out / "labels").mkdir()
    with ZipFile(c.prep.MESHES) as archive:
        for row in frozen["rows"]:
            tuber = row["tuber"]
            try:
                stats, curve = evaluate_case(row, scores[tuber], plans[tuber], archive, geo, out)
                stats["archived_fusion_voxel_centroids"] = int(archive_scores[tuber]["fusion_points"])
                stats["archived_fusion_voxel_far_fraction"] = float(archive_scores[tuber]["fusion_far_fraction"])
                stats["labels_sha256"] = c.prep.digest(out / "labels" / f"{tuber}.npz")
                stats["failure"] = None
                if curve is not None:
                    curves[tuber] = curve
            except prior.FAILURES as error:
                stats = {"tuber": tuber, "raw_added_points": row["points"], "failure": str(error)}
            rows.append(stats)
            print(tuber, stats["failure"] or f"AP {stats['average_precision']:.3f} versus {stats['usable_prevalence']:.3f}", flush=True)

    with gzip.open(out / "precision_recall.csv.gz", "wt", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("tuber", "min_score", "recall", "precision", "predicted_inaccurate_count"))
        for tuber, curve in curves.items():
            writer.writerows((tuber, *p) for p in zip(*curve, strict=True))
    plot(out, rows, curves)
    c.write_csv(out / "per_potato.csv", rows)
    metrics = ("all_prevalence", "usable_prevalence", "top_fraction", "top_minus_usable", "top_recall",
               "average_precision", "ap_minus_usable", "missing_prevalence", "archived_fusion_voxel_far_fraction")
    means = {}
    for k in metrics:
        values = [r[k] for r in rows if r.get(k) is not None]
        means[k] = {"n": len(values), "mean": float(np.mean(values)) if values else None}
    c.prep.write_json(target, {"frozen_scores_sha256": c.prep.digest(frozen_path), "rows": rows,
                              "scored": sum(not r["failure"] for r in rows), "enrolled": len(rows),
                              "equal_potato": means,
                              "top_tenth_enrichment": sum((r.get("top_minus_usable") or 0) > 1e-12 for r in rows),
                              "average_precision_above_prevalence": sum((r.get("ap_minus_usable") or 0) > 1e-12 for r in rows)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "evaluate"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"freeze": freeze, "evaluate": evaluate}[args.phase](args.out)


if __name__ == "__main__":
    main()
