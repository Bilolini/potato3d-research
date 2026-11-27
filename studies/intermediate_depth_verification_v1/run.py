"""Use one archived depth frame per outer source to check previously unobservable points."""

import argparse
from contextlib import ExitStack
import hashlib
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
sys.path.insert(0, str(ROOT))
from studies.depth_consistency_diagnostic_v1 import run as diagnostic

prior = diagnostic.prior
c, align = prior.c, prior.align
BASE = prior.STUDY / "frozen_filter.json"
DIAG = diagnostic.STUDY / "frozen_scores.json"
CATEGORIES = ("unobservable", "consistent", "contradiction", "potentially_occluded")


def sources():
    paths = (Path(__file__), STUDY / "protocol.md", BASE, DIAG, Path(diagnostic.__file__), Path(prior.__file__),
             prior.PRIOR / "frame_manifest.json", prior.PRIOR / "tracking_replay.json",
             prior.PRIOR / "predicted_input_ledger.json", c.prep.CAMERA)
    return {str(p.relative_to(ROOT)): c.prep.digest(p) for p in paths}


def choose(case):
    sequence = [f["suffix"] for f in case["links_rgbd"]]
    lower, center, upper = [sequence.index(s) for s in case["selected"]]
    rgb_order = [f["suffix_px"] for f in case["frames"] if sequence[0] <= f["suffix_px"] <= sequence[-1]]
    if sequence != rgb_order or sequence != sorted(set(sequence)) or not (lower+1 < center < upper-1):
        raise ValueError("Frozen capture order or eligible intermediate missing")
    return [(lower, lower+1), (upper, upper-1)]


def intermediate_depth(case, target_index, record, masks, archives):
    frame = case["links_rgbd"][target_index]
    suffix = frame["suffix"]
    member = frame["depth"]
    raw = c.prep.member_bytes(archives[member["archive"]], member)
    with Image.open(io.BytesIO(raw)) as img:
        depth = np.asarray(img)
    mask = c.unpack(masks[str(suffix)])
    if depth.dtype != np.uint16 or depth.shape != mask.shape:
        raise ValueError("Expected aligned axial depth in 1 mm units")
    support, bounds = prior.sam.filtered_support(depth, mask, record["measured_thickness_mm"])
    old = record["views"][target_index]
    if (old["suffix"] != suffix or old["error"] or
            (int(support.sum()), int(mask.sum()), list(bounds)) !=
            (old["support_pixels"], old["mask_pixels"], old["bounds_mm"])):
        raise ValueError("Archived intermediate depth support did not replay")
    return depth, support, hashlib.sha256(raw).hexdigest(), prior.depth_scatter(depth, support)


def replay_membership(old, saved, case, record, tracking, archives, matrix, scratch):
    tuber = old["tuber"]
    replay = diagnostic.freeze_case(old, case, record, tracking, archives, matrix, scratch)
    archived = prior.verified(diagnostic.STUDY / "scores" / f"{tuber}.npz", saved["scores_sha256"])
    generated = prior.verified(scratch / "scores" / f"{tuber}.npz", replay["scores_sha256"])
    with np.load(archived, allow_pickle=False) as a, np.load(generated, allow_pickle=False) as b:
        for key in ("fused_index", "usable_views", "score"):
            np.testing.assert_array_equal(a[key], b[key])
        result = a["fused_index"][a["usable_views"] == 0]
    if len(result) != saved["without_score"]:
        raise ValueError("Previously uncheckable membership did not replay")
    return result


def classify(old, case, record, indices, chosen, archives, k, tracking, out):
    tuber = old["tuber"]
    _, cloud = prior.archived_clouds(tuber, old["cloud_sha256"])
    lo, center, _ = old["raw_view_points"]
    lower = indices < lo
    upper = indices >= lo + center
    if not np.all(lower | upper) or len(np.unique(indices)) != len(indices):
        raise ValueError("Uncheckable membership contains center points or duplicates")
    track_path = prior.verified(c.track_path(tuber).with_suffix(".npz"), tracking["mask_sha256"])
    links = [np.asarray(r["transform"], dtype=float) for r in record["links"]]
    selected, archived_poses, _ = prior.archived_alignment(case, record)
    poses = align.to_center(links, selected[1])
    output = np.zeros(len(indices), dtype=np.uint8)
    checks = []
    with np.load(track_path, allow_pickle=False) as masks:
        for role, flag, (source, target), saved_pose in zip(
                ("lower", "upper"), (lower, upper), chosen, archived_poses[::2], strict=True):
            source_frame = case["links_rgbd"][source]["suffix"]
            target_frame = case["links_rgbd"][target]["suffix"]
            source_to_target = links[min(source, target)]
            if target < source:
                source_to_target = np.linalg.inv(source_to_target)
            np.testing.assert_allclose(np.linalg.inv(poses[target]) @ saved_pose, source_to_target, atol=1e-10, rtol=0)
            depth, support, sha, scatter = intermediate_depth(case, target, record, masks, archives)
            rmse = record["links"][min(source, target)]["ransac_rmse_mm"]
            source_scatter = old["depth_uncertainty"][role]["scatter_mm"]
            tolerance = float(2 * np.linalg.norm([source_scatter, scatter["scatter_mm"], rmse]))
            front, observed, behind = prior.check_view(cloud[indices[flag]], np.linalg.inv(poses[target]),
                                                       k, depth, support, tolerance)
            if np.any(front & behind) or np.any((front | behind) & ~observed):
                raise ValueError("Depth categories must be disjoint and supported")
            output[flag] = np.where(~observed, 0, np.where(front, 2, np.where(behind, 3, 1)))
            checks.append({"role": role, "source_frame": source_frame, "intermediate_frame": target_frame,
                           "depth_member": case["links_rgbd"][target]["depth"]["member"], "depth_sha256": sha,
                           "source_scatter_mm": source_scatter, "intermediate_scatter": scatter,
                           "adjacent_inlier_rmse_mm": rmse, "tolerance_mm": tolerance,
                           "counts": dict(zip(CATEGORIES, np.bincount(output[flag], minlength=4).tolist(), strict=True))})
    path = out / "classifications" / f"{tuber}.npz"
    np.savez_compressed(path, fused_index=indices, category=output)
    return {"tuber": tuber, "uncheckable_points": len(indices), "cloud_sha256": old["cloud_sha256"],
            "source_mask_sha256": tracking["mask_sha256"], "checks": checks,
            "classification_sha256": c.prep.digest(path)}


def freeze(out):
    destination = out / "frozen_classifications.json"
    selection_path = out / "frozen_frames.json"
    if destination.exists() or selection_path.exists():
        raise FileExistsError("Choose a new output directory")
    base = c.prep.read_json(BASE)
    diag = c.prep.read_json(DIAG)
    if (base["sources_sha256"] != prior.freeze_sources() or diag["sources_sha256"] != diagnostic.sources()
            or diag["stage"] != "continuous_scores_frozen_before_reference_meshes"):
        raise ValueError("Archived freeze receipts do not match source files")
    roster = base["rows"]
    cases = {r["tuber"]: r for r in c.prep.read_json(prior.PRIOR / "frame_manifest.json")["roster"]
             if r["analysis"] == "geometry"}
    saved = c.by_tuber(diag["rows"])
    if len(roster) != 10 or set(cases) != set(saved) or set(cases) != set(c.by_tuber(roster)):
        raise ValueError("The geometry study roster must contain the same ten IDs")
    selections = {r["tuber"]: choose(cases[r["tuber"]]) for r in roster}
    selections_frames = {t: [[cases[t]["links_rgbd"][i]["suffix"] for i in p] for p in pairs]
                         for t, pairs in selections.items()}
    c.prep.write_json(selection_path, {"stage": "selected_by_capture_order", "source_and_intermediate": selections_frames})
    tracking = c.by_tuber(c.prep.read_json(prior.PRIOR / "tracking_replay.json")["rows"])
    ledger = c.by_tuber(c.prep.read_json(prior.PRIOR / "predicted_input_ledger.json")["records"])
    names = {f["depth"]["archive"] for t in cases for f in cases[t]["links_rgbd"]
             if f["suffix"] in set(cases[t]["selected"]) | {p[1] for p in selections_frames[t]}}
    matrix = prior.camera()
    projection_check = prior.check_projection()
    (out / "classifications").mkdir()
    rows = []
    with TemporaryDirectory() as tmp, ExitStack() as stack:
        scratch = Path(tmp)
        (scratch / "scores").mkdir()
        archives = c.prep.open_images(stack, names)
        for old in roster:
            tuber = old["tuber"]
            position = prior.verified(c.OUTPUT / "predicted" / f"{tuber}.json", ledger[tuber]["sha256"])
            record = c.prep.read_json(position)
            case = cases[tuber]
            indices = replay_membership(old, saved[tuber], case, record, tracking[tuber], archives, matrix, scratch)
            row = classify(old, case, record, indices, selections[tuber], archives, matrix, tracking[tuber], out)
            rows.append(row)
            print(tuber, selections_frames[tuber], len(indices), "membership replayed", flush=True)
    if sum(r["uncheckable_points"] for r in rows) != 12144:
        raise ValueError("Expected the exact 12,144 uncheckable outer-view points")
    c.prep.write_json(destination, {"stage": "classified_before_sfm_label_join", "sources_sha256": sources(),
                                   "frame_choices_sha256": c.prep.digest(selection_path),
                                   "category_codes": dict(enumerate(CATEGORIES)), "projection_check": projection_check,
                                   "rows": rows})


def joined_row(row, indexes, categories, label_record, labels):
    tuber = row["tuber"]
    archive_indices = labels["fused_index"]
    inaccurate = labels["inaccurate"]
    if (not np.all(np.diff(archive_indices) > 0) or
            not np.array_equal(inaccurate, labels["distance_mm"] > diagnostic.RAWDIST_MM)):
        raise ValueError("Archived raw accuracy data failed integrity checks")
    loc = np.searchsorted(archive_indices, indexes)
    if np.any(loc >= len(archive_indices)) or not np.array_equal(archive_indices[loc], indexes):
        raise ValueError("Could not exactly join archived fused point indices")
    errors = inaccurate[loc]
    if len(indexes) != label_record["missing_points"] or errors.sum() != label_record["missing_errors"]:
        raise ValueError("Original raw no-comparison label totals did not replay")
    item = {"tuber": tuber, "points": len(indexes)}
    for key in row["checks"]:
        item[key["role"] + "_source"] = key["source_frame"]
        item[key["role"] + "_intermediate"] = key["intermediate_frame"]
    for i, key in enumerate(CATEGORIES):
        n = int((categories == i).sum())
        b = int(errors[categories == i].sum())
        expected = sum(k["counts"][key] for k in row["checks"])
        if n != expected:
            raise ValueError("Frozen category membership or count mismatch")
        item.update({f"{key}_count": n, f"{key}_errors": b, f"{key}_error_fraction": b/n if n else None})
    resolved = item["consistent_count"] + item["contradiction_count"]
    item["observed"] = len(indexes) - item["unobservable_count"]
    item["observed_fraction"] = item["observed"] / len(indexes)
    item["comparison_decisive"] = resolved
    item["comparison_decisive_fraction"] = resolved / len(indexes)
    if item["consistent_count"] and item["contradiction_count"]:
        item["contradiction_minus_consistent"] = item["contradiction_error_fraction"] - item["consistent_error_fraction"]
    else:
        item["contradiction_minus_consistent"] = None
    return item


def evaluate(out):
    path = out / "frozen_classifications.json"
    frozen = c.prep.read_json(path)
    if (frozen["stage"] != "classified_before_sfm_label_join" or frozen["sources_sha256"] != sources()
            or frozen["frame_choices_sha256"] != c.prep.digest(out / "frozen_frames.json")):
        raise ValueError("Frozen classifications or protocol changed")
    destination = out / "results.json"
    if destination.exists():
        raise FileExistsError(destination)
    arrays = {}
    for row in frozen["rows"]:
        tuber = row["tuber"]
        file = prior.verified(out / "classifications" / f"{tuber}.npz", row["classification_sha256"])
        with np.load(file, allow_pickle=False) as data:
            arrays[tuber] = (data["fused_index"], data["category"])
    label_path = diagnostic.STUDY / "results.json"
    label_manifest = c.prep.read_json(label_path)
    if label_manifest["frozen_scores_sha256"] != c.prep.digest(DIAG):
        raise ValueError("Archived labels are from a different point set")
    label_records = c.by_tuber(label_manifest["rows"])
    rows = []
    for row in frozen["rows"]:
        tuber = row["tuber"]
        expected = label_records[tuber]
        label_file = prior.verified(diagnostic.STUDY / "labels" / f"{tuber}.npz", expected["labels_sha256"])
        with np.load(label_file, allow_pickle=False) as labels:
            items = joined_row(row, *arrays[tuber], expected, labels)
        rows.append(items)
        print(tuber, items["observed"], "observed", items["contradiction_count"], "contradictions", flush=True)

    def mean(key, subset):
        values = [r[key] for r in subset if r[key] is not None]
        return {"n_potatoes": len(values), "mean": float(np.mean(values)) if values else None}

    summary = {}
    for name in CATEGORIES:
        n = sum(r[f"{name}_count"] for r in rows)
        errors = sum(r[f"{name}_errors"] for r in rows)
        summary[name] = {"points": n, "errors": errors, "pooled_error_fraction": errors/n if n else None,
                         "equal_potato_error": mean(f"{name}_error_fraction", rows)}
    common = [r for r in rows if r["contradiction_minus_consistent"] is not None]
    direction = {"higher": sum(r["contradiction_minus_consistent"] > 1e-12 for r in common),
                 "similar": sum(abs(r["contradiction_minus_consistent"]) <= 1e-12 for r in common),
                 "lower": sum(r["contradiction_minus_consistent"] < -1e-12 for r in common)}
    c.write_csv(out / "per_potato.csv", rows)
    c.prep.write_json(destination, {"frozen_classifications_sha256": c.prep.digest(path),
                                   "label_manifest_sha256": c.prep.digest(label_path), "raw_points": sum(r["points"] for r in rows),
                                   "observed": sum(r["observed"] for r in rows),
                                   "observed_equal_potato": mean("observed_fraction", rows),
                                   "agreement_or_contradiction": sum(r["comparison_decisive"] for r in rows),
                                   "agreement_or_contradiction_equal_potato": mean("comparison_decisive_fraction", rows),
                                   "per_category": summary, "paired_potatoes": len(common), "ordering": direction,
                                   "complete_pair_consistent": mean("consistent_error_fraction", common),
                                   "complete_pair_contradiction": mean("contradiction_error_fraction", common),
                                   "paired_difference": mean("contradiction_minus_consistent", common), "rows": rows})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "evaluate"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"freeze": freeze, "evaluate": evaluate}[args.phase](args.out)


if __name__ == "__main__":
    main()
