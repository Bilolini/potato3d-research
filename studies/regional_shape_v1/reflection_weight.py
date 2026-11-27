"""Replay regional measurements and choose a reflection weight in each development fold."""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from potato3d.io import sha256, write_json
from .study import HERE, METHODS, SHIFTS, average_scores, error_summary, predict, run_study, sector_mae

WEIGHTS = np.array([0., .25, .5, .75, 1.])
SCORE_KEYS = (*METHODS, "each_shift", "clipped_q95")


def common_sectors(cells, band, reference_ok, expected_counts):
    common = cells.scan_ok & reference_ok
    sectors = [mask & common for mask in cells.sector_masks[band]]
    np.testing.assert_array_equal([m.sum() for m in sectors], expected_counts)
    return sectors


def weight_curve(body, correction_per_cell, measured, support):
    predictions = body - WEIGHTS[:, None] * correction_per_cell
    return sector_mae(predictions, measured, support)


def nominal_curve(row, cells):
    curves = []
    for band in row["bands"]:
        if "errors_mm" not in band:
            continue
        support = common_sectors(cells, band["band"], np.isfinite(cells.nominal_lower),
                                 band["coverage"]["common"])
        correction = np.asarray(band["scan_correction_mm"])[cells.sectors]
        curve = weight_curve(cells.body_lower, correction, cells.nominal_lower, support)
        np.testing.assert_allclose(curve[[0, -1]], [band["errors_mm"][k] for k in ("body", "aligned")],
                                   rtol=0, atol=1e-12)
        curves.append(curve)
    curve = np.mean(curves, axis=0)
    np.testing.assert_allclose(curve[[0, -1]], [row["errors_mm"][k] for k in ("body", "aligned")],
                               rtol=0, atol=1e-12)
    return curve


def select_fold_weights(curves):
    """Use equal tuber weights and the first minimum in ascending weight order."""
    selections = []
    for left_out in range(len(curves)):
        training_mean = np.delete(curves, left_out, axis=0).mean(axis=0)
        selections.append((int(np.argmin(training_mean)), training_mean))
    return selections


def selected_scores(row, cells, weight, probe=None):
    """Score a frozen weight for both references on their common scan support."""
    nominal = cells.nominal_lower
    perturbed = cells.probe_lower[probe] if probe is not None else nominal
    reference_ok = np.isfinite(nominal) & np.isfinite(perturbed)
    if probe is None:
        eligible = [(band, band["coverage"]["common"])
                    for band in row["bands"] if "errors_mm" in band]
        references = {"nominal": nominal}
    else:
        eligible = [(band, probe_band["common_cells"])
                    for band, probe_band in zip(row["bands"], row["probes"][probe]["bands"])
                    if "nominal" in probe_band]
        references = {"nominal": nominal, "perturbed": perturbed}
    scores = {key: [] for key in references}
    for band, counts in eligible:
        support = common_sectors(cells, band["band"], reference_ok, counts)
        correction = weight * np.asarray(band["scan_correction_mm"])
        aligned, shifted = predict(cells.body_lower, correction, cells.sectors)
        mirror_complete = np.isfinite(cells.mirror_lower[np.any(support, axis=0)]).all()
        for key, measured in references.items():
            result = error_summary(cells.body_lower, aligned, shifted, measured, support)
            result["clipped_q95"] = (
                sector_mae(cells.mirror_lower, measured, support) if mirror_complete else None)
            scores[key].append(result)
    matched = {}
    for key, scores_by_band in scores.items():
        mirror_complete = all(s["clipped_q95"] is not None for s in scores_by_band)
        result = average_scores(scores_by_band, SCORE_KEYS if mirror_complete else SCORE_KEYS[:-1])
        if result is not None and not mirror_complete:
            result["clipped_q95"] = None
        matched[key] = result
    return matched


def evaluate(baseline, measurements):
    rows = baseline["pairs"]
    eligible = [r for r in rows if r.get("errors_mm") is not None]
    curves = np.array([nominal_curve(r, measurements[r["object_id"]]) for r in eligible])
    np.testing.assert_allclose(curves.mean(axis=0)[[0, -1]],
                               [baseline["summary"]["errors_mm"][k] for k in ("body", "aligned")],
                               rtol=0, atol=1e-12)
    folds = {}
    for row, curve, (index, training_mean) in zip(eligible, curves, select_fold_weights(curves)):
        obj = row["object_id"]
        cells = measurements[obj]
        weight = WEIGHTS[index]
        scores = selected_scores(row, cells, weight)["nominal"]
        np.testing.assert_allclose(scores["aligned"], curve[index], rtol=0, atol=1e-12)
        np.testing.assert_allclose(scores["clipped_q95"], row["mirror_comparison_mm"]["clipped_q95"],
                                   rtol=0, atol=1e-12)
        probes = {}
        for key, original in row["probes"].items():
            matched = selected_scores(row, cells, weight, key)
            if original["scored_bands"]:
                for case, original_case in (("nominal", "nominal_same_support_mm"),
                                            ("perturbed", "perturbed_mm")):
                    np.testing.assert_allclose(matched[case]["body"], original[original_case]["body"],
                                               rtol=0, atol=1e-12)
            probes[key] = {"scored_bands": original["scored_bands"],
                           "scored_cells": original["scored_cells"],
                           "nominal_same_support_mm": matched["nominal"],
                           "perturbed_mm": matched["perturbed"]}
        folds[obj] = {"selected_weight": weight,
                      "training_tubers": [r["object_id"] for r in eligible if r["object_id"] != obj],
                      "training_mae_curve_mm": training_mean,
                      "all_weight_mae_curve_mm": curve, "scores_mm": scores, "probes": probes}

    scores = average_scores([f["scores_mm"] for f in folds.values()], SCORE_KEYS)
    for obj, fold in folds.items():
        # Keep the other folds' choices fixed for this contribution diagnostic.
        omitted = np.mean([f["scores_mm"]["aligned_minus_body"]
                           for key, f in folds.items() if key != obj])
        fold["mean_delta_without_this_fold_mm"] = omitted
        fold["change_in_mean_if_omitted_mm"] = omitted - scores["aligned_minus_body"]

    probes = {}
    for key in baseline["summary"]["probes"]:
        valid = [f["probes"][key] for f in folds.values() if f["probes"][key]["scored_bands"]]
        probes[key] = {"scored_tubers": len(valid),
                       "scored_bands": sum(p["scored_bands"] for p in valid),
                       "scored_cells": sum(p["scored_cells"] for p in valid),
                       **{case: average_scores([p[case] for p in valid], SCORE_KEYS)
                          for case in ("nominal_same_support_mm", "perturbed_mm")}}

    pooled = curves.mean(axis=0)
    return {
        "candidate_weights": WEIGHTS, "shift_offsets_sectors": SHIFTS,
        "coverage": {k: baseline["summary"][k] for k in (
            "selected_tubers", "planned_bands", "scored_tubers", "scored_bands", "scored_cells")},
        "pooled_nominal_mae_curve_mm": pooled,
        "pooled_best_weight": WEIGHTS[np.argmin(pooled)],
        "out_of_fold_scores_mm": scores,
        "out_of_fold_registration_probes": probes,
        "pairs": [{"object_id": r["object_id"], "frame_id": r["frame_id"],
                   "scored_bands": r.get("scored_bands", 0), "scored_cells": r.get("scored_cells", 0),
                   "exclusion": r["failure"], "fold": folds.get(r["object_id"])}
                  for r in rows],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=HERE)
    args = parser.parse_args()
    saved = HERE / "results.json"

    cells = {}
    baseline, _ = run_study(args.source, cells)
    with TemporaryDirectory(prefix="potato-regional-weight-") as tmp:
        replay = Path(tmp) / "replay.json"
        write_json(replay, baseline)
        if replay.read_bytes() != saved.read_bytes():
            raise ValueError("Replayed measurements differ from the saved regional study")
    result = {"stage": "regional_reflection_weight_development",
              "decision_sha256": sha256(HERE / "astra_decision.md"),
              "baseline_sha256": sha256(saved), **evaluate(baseline, cells)}

    from .plot_reflection_weight import plot_reflection_weight
    plot_reflection_weight(result, args.out_dir / "reflection_weight_curve.png")
    write_json(args.out_dir / "reflection_weight_results.json", result)


if __name__ == "__main__":
    main()
