"""Measure how much development underside error a reference-fitted z shift can remove."""
import argparse
from math import lcm
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from potato3d.io import sha256, write_json
from .reflection_weight import common_sectors
from .study import HERE, run_study, sector_mae

SCORE_KEYS = ("body_mae_mm", "best_achievable_mae_mm", "best_change_mm",
              "held_out_body_mae_mm", "held_out_shifted_mae_mm", "held_out_change_mm")
TOLERANCE_MM = 1e-12


def weighted_offset(residual, bands):
    """Find an L1 minimizer, using the midpoint when the minimum is an interval."""
    sectors = [(residual[sector], len(band)) for band in bands for sector in band]
    counts = [len(values) for values, _ in sectors]
    denominators = [len(values) * band_size for values, band_size in sectors]
    # Integer masses make the half-weight test exact, even with unequal sector sizes.
    common = lcm(*denominators)
    weights = np.repeat(np.array([common // n for n in denominators], dtype=object), counts)
    values = np.concatenate([values for values, _ in sectors])
    order = np.argsort(values)
    twice_cumulative = 2 * np.cumsum(weights[order])
    total = common * len(bands)
    index = np.searchsorted(twice_cumulative, total)
    if twice_cumulative[index] == total:
        return np.mean(values[order[index:index+2]])
    return values[order[index]]


def offset_mae(residual, bands, offset):
    predicted = np.full_like(residual, offset)
    return np.mean([sector_mae(predicted, residual, band) for band in bands])


def score_offset(residual, bands):
    offset = weighted_offset(residual, bands)
    body = offset_mae(residual, bands, 0.)
    best = offset_mae(residual, bands, offset)
    directions = {}
    for parity, name in enumerate(("even_to_odd", "odd_to_even")):
        train = [band[parity::2] for band in bands]
        test = [band[1-parity::2] for band in bands]
        trained_offset = weighted_offset(residual, train)
        test_body = offset_mae(residual, test, 0.)
        test_shifted = offset_mae(residual, test, trained_offset)
        directions[name] = {
            "training_shift_mm": trained_offset,
            "training_cells": sum(np.count_nonzero(m) for band in train for m in band),
            "held_out_cells": sum(np.count_nonzero(m) for band in test for m in band),
            "body_mae_mm": test_body, "shifted_mae_mm": test_shifted,
            "change_mm": test_shifted - test_body,
        }
    return {
        "vertical_shift_mm": offset,
        "body_mae_mm": body, "best_achievable_mae_mm": best, "best_change_mm": best - body,
        "held_out_body_mae_mm": np.mean([s["body_mae_mm"] for s in directions.values()]),
        "held_out_shifted_mae_mm": np.mean([s["shifted_mae_mm"] for s in directions.values()]),
        "held_out_change_mm": np.mean([s["change_mm"] for s in directions.values()]),
        "directions": directions,
    }


def evaluate(baseline, measurements):
    rows = []
    for pair in baseline["pairs"]:
        obj = pair["object_id"]
        row = {key: pair[key] for key in ("object_id", "frame_id", "cultivar",
                                        "scored_bands", "scored_cells", "failure")}
        row["scores_mm"] = None
        if pair["scored_bands"]:
            cells = measurements[obj]
            ref_ok = np.isfinite(cells.nominal_lower)
            bands = [common_sectors(cells, b["band"], ref_ok, b["coverage"]["common"])
                     for b in pair["bands"] if "errors_mm" in b]
            score = score_offset(cells.nominal_lower - cells.body_lower, bands)
            for key in ("body_mae_mm", "held_out_body_mae_mm"):
                np.testing.assert_allclose(score[key], pair["errors_mm"]["body"], rtol=0, atol=TOLERANCE_MM)
            if score["best_change_mm"] > TOLERANCE_MM:
                raise ValueError(f"Fitted offset worsened its own fitting cells for {obj}")
            row["scores_mm"] = score
        rows.append(row)

    scored = [row for row in rows if row["scores_mm"] is not None]
    means = {key: np.mean([r["scores_mm"][key] for r in scored]) for key in SCORE_KEYS}
    archived_body = baseline["summary"]["errors_mm"]["body"]
    np.testing.assert_allclose(means["body_mae_mm"], archived_body, rtol=0, atol=TOLERANCE_MM)
    coverage = {key: baseline["summary"][key] for key in
                ("selected_tubers", "scored_tubers", "planned_bands", "scored_bands", "scored_cells")}
    observed = (len(rows), len(scored), sum(r["scored_bands"] for r in scored),
                sum(r["scored_cells"] for r in scored))
    if observed != (12, 7, 10, 12202):
        raise ValueError(f"Development support differs from the protocol: {observed}")

    deltas = np.array([r["scores_mm"]["held_out_change_mm"] for r in scored])
    omitted = [np.mean(np.delete(deltas, index)) for index in range(len(deltas))]
    for row, score_without in zip(scored, omitted):
        row["held_out_mean_change_if_omitted_mm"] = score_without
    return {
        "coverage": coverage,
        "archived_body_mean_mae_mm": archived_body,
        "equal_tuber_mean_mm": means,
        "held_out_wins": np.count_nonzero(deltas < -TOLERANCE_MM),
        "held_out_ties": np.count_nonzero(np.abs(deltas) <= TOLERANCE_MM),
        "held_out_losses": np.count_nonzero(deltas > TOLERANCE_MM),
        "held_out_tie_tolerance_mm": TOLERANCE_MM,
        "held_out_omit_one_mean_change_range_mm": [min(omitted), max(omitted)],
        "pairs": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=HERE)
    args = parser.parse_args()

    cells = {}
    baseline, _ = run_study(args.source, cells)
    archived = HERE / "results.json"
    with TemporaryDirectory(prefix="potato-offset-dev-") as tmp:
        replay = Path(tmp) / "results.json"
        write_json(replay, baseline)
        if replay.read_bytes() != archived.read_bytes():
            raise ValueError("Development replay differs from archived results")
    print("Archived development baseline reproduced byte for byte", flush=True)

    result = {
        "stage": "vertical_offset_development_diagnostic",
        "decision_sha256": sha256(HERE / "replication_decision.md"),
        "archived_development_sha256": sha256(archived),
        "development_selection_sha256": baseline["selection_sha256"],
        "archived_replay_byte_identical": True,
        **evaluate(baseline, cells),
    }
    write_json(args.out_dir / "vertical_offset_results.json", result)


if __name__ == "__main__":
    main()
