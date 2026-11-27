"""Freeze zero-comparison removal and measure what it contributes to fused geometry."""

import argparse
from pathlib import Path
import sys
from zipfile import ZipFile

import numpy as np

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
sys.path.insert(0, str(ROOT))
from studies.depth_consistency_fusion_v1 import run as prior

c, align = prior.c, prior.align
DIAGNOSTIC = STUDY.parent / "depth_consistency_diagnostic_v1"
GEOMETRY_PLAN = c.PILOT / "frame_manifest.json"
METHODS = ("fusion", "zero_removed", "random")
METRICS = ("far_fraction", "centroids", "retained_fraction", "lost_fraction", "lost_area_mm2")


def sources():
    paths = (Path(__file__), STUDY / "protocol.md", Path(prior.__file__), prior.STUDY / "frozen_filter.json",
             DIAGNOSTIC / "frozen_scores.json", GEOMETRY_PLAN, c.PILOT / "score.py")
    return {str(path.relative_to(ROOT)): c.prep.digest(path) for path in paths}


def freeze_case(row, diagnostic, out):
    tuber = row["tuber"]
    if (diagnostic["frames"], diagnostic["cloud_sha256"]) != (row["frames"], row["cloud_sha256"]):
        raise ValueError("Diagnostic score archive is from a different source cloud")
    lo, center, hi = row["raw_view_points"]
    n = lo + center + hi
    outer = (np.arange(lo), np.arange(lo + center, n))
    src = prior.verified(DIAGNOSTIC / "scores" / f"{tuber}.npz", diagnostic["scores_sha256"])
    with np.load(src, allow_pickle=False) as file:
        index, usable = file["fused_index"], file["usable_views"]
    if (not np.array_equal(index, np.concatenate(outer)) or usable.shape != index.shape
            or not np.isin(usable, [0, 1, 2]).all()):
        raise ValueError("Frozen indices and comparison counts do not identify exactly the two outer views")
    rejected = np.zeros(n, dtype=bool)
    rejected[index] = usable == 0
    counts = [int(rejected[view].sum()) for view in outer]
    if counts != [v["no_evidence_in_either_view"] for v in row["added_views"]] or sum(counts) != diagnostic["without_score"]:
        raise ValueError("No-comparison counts did not replay")
    rng = np.random.default_rng(row["random_seed"])
    random_drop = np.zeros((prior.REPEATS, n), dtype=bool)
    for draw in random_drop:
        for view, count in zip(outer, counts, strict=True):
            draw[rng.choice(view, count, replace=False)] = True
    destination = out / f"{tuber}.npz"
    np.savez_compressed(destination, rejected=rejected, random_drop=random_drop)
    return {"tuber": tuber, "frames": row["frames"], "cloud_sha256": row["cloud_sha256"],
            "raw_view_points": row["raw_view_points"], "removed_by_outer_view": counts,
            "removed_points": sum(counts), "random_seed": row["random_seed"],
            "score_archive_sha256": diagnostic["scores_sha256"], "decision_sha256": c.prep.digest(destination)}


def freeze(out):
    destination = out / "frozen_removals.json"
    if destination.exists():
        raise FileExistsError(destination)
    ledger = c.prep.read_json(prior.STUDY / "frozen_filter.json")
    diag = c.prep.read_json(DIAGNOSTIC / "frozen_scores.json")
    if (ledger["sources_sha256"] != prior.freeze_sources() or
            diag["stage"] != "continuous_scores_frozen_before_reference_meshes"):
        raise ValueError("An upstream freeze failed provenance verification")
    expected = ledger["rows"]
    keys = c.by_tuber(diag["rows"])
    if len(expected) != 10 or set(c.by_tuber(expected)) != set(keys) or any(row["failure"] for row in expected):
        raise ValueError("Expected the ten complete frozen geometry cases")
    rows = [freeze_case(r, keys[r["tuber"]], out) for r in expected]
    if sum(r["removed_points"] for r in rows) != 12144:
        raise ValueError("The frozen set must contain exactly 12,144 no-comparison points")
    c.prep.write_json(destination, {"stage": "removals_and_random_masks_frozen_before_reference",
                                   "sources_sha256": sources(), "random_repeats": prior.REPEATS, "rows": rows})
    print("Frozen 12,144 no-comparison points and 200 matched controls without reference inputs.", flush=True)


def measure(cloud, samples, scene, original_new, area, geo):
    metric, covered = geo.score_cloud(align.voxel(cloud, 1.), samples, scene)
    lost = original_new & ~covered
    return {"far_fraction": metric["far_fraction"], "centroids": metric["points"],
            "retained_fraction": float(1.0 - lost.sum() / original_new.sum()),
            "lost_fraction": float(lost.sum() / original_new.sum()),
            "lost_area_mm2": float(lost.mean() * area)}, lost


def score_case(row, old, plan, diag, masks, geo, archive):
    tuber = row["tuber"]
    if row["frames"] != plan["selected_suffixes"]:
        raise ValueError("Archived pose is from a different frame triplet")
    center, cloud = prior.archived_clouds(tuber, row["cloud_sha256"])
    anchor = align.in_mm(plan["center_to_sfm_m"])
    center, cloud = (align.apply(points, anchor) for points in (center, cloud))
    ref = geo.load_reference(archive, plan["reference"])
    samples, _ = geo.sample_surface(ref, geo.SAMPLES, c.prep.SEED)
    scene = geo.mesh_scene(ref)
    center_scores, covered_center = geo.score_cloud(align.voxel(center, 1.), samples, scene)
    official, covered = geo.score_cloud(align.voxel(cloud, 1.), samples, scene)
    for arm, metric in (("B", center_scores), ("D", official)):
        if any(abs(v - float(old[f"{arm}_{k}"])) > 1e-10 for k, v in metric.items()):
            raise ValueError(f"Archived {arm} score did not replay")
    original_new = covered & ~covered_center
    original_area = float(original_new.mean() * ref.area)
    if not original_new.any() or abs(original_area - float(old["D_new_area_mm2"])) > 1e-8:
        raise ValueError("Archived newly recovered area did not replay")
    rejected, random_drop = masks
    baseline = {"far_fraction": official["far_fraction"], "centroids": official["points"],
                "retained_fraction": 1., "lost_fraction": 0., "lost_area_mm2": 0.}
    removed, lost = measure(cloud[~rejected], samples, scene, original_new, ref.area, geo)
    repeats = [measure(cloud[~mask], samples, scene, original_new, ref.area, geo)[0] for mask in random_drop]
    random = {k: float(np.mean([r[k] for r in repeats])) for k in METRICS}
    metrics = {"fusion": baseline, "zero_removed": removed, "random": random}
    if row["removed_points"] != int(diag["missing_points"]):
        raise ValueError("Archived diagnostic raw-label denominator changed")
    values = {
        "tuber": tuber, "reference_samples": len(samples), "original_new_samples": int(original_new.sum()),
        "original_new_area_mm2": original_area, "zero_comparison_raw_points": row["removed_points"],
        "zero_comparison_raw_error_fraction": float(diag["missing_prevalence"]),
        "zero_removed_lost_samples": int(lost.sum()), "failure": None,
        **{f"{m}_{k}": value for m, arm in metrics.items() for k, value in arm.items()},
    }
    return values, repeats, (align.apply(samples, np.linalg.inv(anchor)), original_new, lost)


def visualize(out, rows, samples_by_tuber):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.lines import Line2D

    complete = [r for r in rows if r["tuber"] in samples_by_tuber]
    special = next((r for r in complete if r["tuber"] == "4R8-8"), None)
    examples = [special] if special else []
    remaining = [r for r in complete if r is not special]
    if remaining:
        examples.append(max(remaining, key=lambda r: (r["zero_removed_lost_area_mm2"], r["tuber"])))
    if not examples:
        return []
    fig = plt.figure(figsize=(9.5, 3.45 * len(examples) + .6))
    fig.subplots_adjust(left=.02, right=.98, bottom=.10, top=.90, wspace=.04, hspace=.22)
    fig.suptitle("Reference surface lost after removing zero-comparison points", fontsize=14, fontweight="bold")
    rng = np.random.default_rng(c.SEED)
    for i, row in enumerate(examples):
        coords, new, lost = samples_by_tuber[row["tuber"]]
        centered = coords - (coords.max(axis=0) + coords.min(axis=0)) / 2
        limit = np.ptp(centered, axis=0).max() / 2 + 1
        background = rng.choice(np.flatnonzero(~new), size=min(5000, int((~new).sum())), replace=False)
        for j, (elev, azim) in enumerate(((52, -64), (-52, 116))):
            ax = fig.add_subplot(len(examples), 2, 2*i+j+1, projection="3d", computed_zorder=False)
            ax.scatter(*centered[background].T, c="#cbd3db", alpha=.23, s=2, linewidths=0)
            ax.scatter(*centered[new & ~lost].T, c="#178071", alpha=.58, s=5, linewidths=0)
            ax.scatter(*centered[lost].T, c="#ba4c28", alpha=.9, s=9, linewidths=0)
            ax.set(xlim=(-limit, limit), ylim=(-limit, limit), zlim=(-limit, limit), box_aspect=(1, 1, 1))
            ax.view_init(elev=elev, azim=azim)
            ax.set_proj_type("ortho")
            ax.set_axis_off()
            ax.set_title(f"{row['tuber']}   ·   {row['zero_removed_lost_area_mm2']:.1f} mm² lost" if j == 0
                         else "Opposite view", fontsize=10, pad=1)
    markers = [("Other reference surface", "#cbd3db"), ("New surface retained", "#178071"), ("New surface lost", "#ba4c28")]
    fig.legend(handles=[Line2D([], [], marker="o", linestyle="", color=v, label=k) for k, v in markers],
               loc="lower center", ncols=3, frameon=False, fontsize=10)
    fig.savefig(out / "coverage_loss.png", dpi=190)
    plt.close(fig)
    return [r["tuber"] for r in examples]


def evaluate(out):
    frozen_path = out / "frozen_removals.json"
    frozen = c.prep.read_json(frozen_path)
    if (frozen["stage"] != "removals_and_random_masks_frozen_before_reference" or frozen["sources_sha256"] != sources()
            or frozen["random_repeats"] != prior.REPEATS):
        raise ValueError("Frozen protocol or selection inputs changed")
    destination = out / "results.json"
    if destination.exists():
        raise FileExistsError(destination)
    masks = {row["tuber"]: prior.read_decisions(row, out) for row in frozen["rows"]}
    import score as geo

    geo.metric_check()
    old = c.by_tuber(c.csv_rows(prior.PRIOR / "geometry_per_potato.csv"))
    diag = c.by_tuber(c.csv_rows(DIAGNOSTIC / "per_potato.csv"))
    plans = c.by_tuber(c.prep.read_json(GEOMETRY_PLAN)["roster"])
    rows, repeats, view_data = [], [], {}
    with ZipFile(c.prep.MESHES) as archive:
        for row in frozen["rows"]:
            tuber = row["tuber"]
            try:
                values, draws, view_data[tuber] = score_case(row, old[tuber], plans[tuber], diag[tuber],
                                                              masks[tuber], geo, archive)
                repeats.extend({"tuber": tuber, "draw": i, **rep} for i, rep in enumerate(draws, 1))
            except prior.FAILURES as error:
                values = {"tuber": tuber, "zero_comparison_raw_points": row["removed_points"], "failure": str(error)}
            rows.append(values)
            print(tuber, values["failure"] or f"{values['zero_removed_lost_area_mm2']:.2f} mm² lost", flush=True)
    c.write_csv(out / "per_potato.csv", rows)
    if repeats:
        c.write_csv(out / "random_repeats.csv", repeats)
    complete = [r for r in rows if not r["failure"]]
    means = {f"{m}_{k}": float(np.mean([r[f"{m}_{k}"] for r in complete])) if complete else None
             for m in METHODS for k in METRICS}
    metrics = ("far_fraction", "lost_fraction", "lost_area_mm2")
    comparisons = {f"zero_removed_minus_{b}": {k: prior.paired(complete, "zero_removed", b, k) for k in metrics}
                   for b in ("fusion", "random")}
    differences = [(r["zero_removed_far_fraction"] - r["random_far_fraction"],
                    r["zero_removed_lost_fraction"] - r["random_lost_fraction"]) for r in complete]
    tol = 1e-12
    decision = {"lower_far": sum(a < -tol for a, _ in differences),
                "less_surface_lost": sum(b < -tol for _, b in differences),
                "zero_removed_dominates": sum(a <= tol and b <= tol and (a < -tol or b < -tol) for a, b in differences),
                "random_dominates": sum(a >= -tol and b >= -tol and (a > tol or b > tol) for a, b in differences)}
    examples = visualize(out, rows, view_data)
    c.prep.write_json(destination, {
        "frozen_sha256": c.prep.digest(frozen_path), "archived_geometry_scores_sha256": c.prep.digest(prior.PRIOR / "geometry_per_potato.csv"),
        "diagnostic_labels_summary_sha256": c.prep.digest(DIAGNOSTIC / "per_potato.csv"),
        "scored": len(complete), "enrolled": len(rows), "mean_original_new_area_mm2": float(np.mean([r["original_new_area_mm2"] for r in complete])) if complete else None,
        "equal_potato": means, "paired": comparisons, "versus_random_counts": decision,
        "visualized_potatoes": examples, "rows": rows,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "evaluate"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"freeze": freeze, "evaluate": evaluate}[args.phase](args.out)


if __name__ == "__main__":
    main()
