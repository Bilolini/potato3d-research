"""Analytic sign, location, aggregation and registration-support checks."""
import numpy as np
import pytest

from studies.body_detail_v1.model import body_surfaces
from studies.regional_shape_v1.reflection_weight import select_fold_weights, weight_curve
from studies.regional_shape_v1.study import (
    band_results, coverage, error_summary, probe_results, region_cells, sector_masks,
)


@pytest.mark.parametrize("case", ["bilateral", "top_only", "displaced"])
def test_analytic_broad_deviations(case):
    # The known smooth body isolates errors in regional signs or scoring.
    body = {"center_xy_mm": [0., 0.], "radii_xy_mm": [32., 50.],
            "rotation_basis": [[0., -1.], [1., 0.]],
            "vertical_radius_mm": 28., "exponent": 2.}
    xy, bands, sectors, major = region_cells(body)
    np.testing.assert_array_equal(major, [1., 0.])
    top, bottom, _ = body_surfaces(xy, body)
    azimuth = np.arctan2(xy[:, 1]/32., xy[:, 0]/50.)
    broad = 1.5*np.cos(azimuth - np.pi/8)
    scan = top + 1 + 2*bands + broad
    lower_sign = {"bilateral": -1, "top_only": 0, "displaced": 1}[case]
    sfm = np.column_stack([bottom + lower_sign*broad, top + broad])
    rows, _ = band_results(sector_masks(bands, sectors), sectors, scan, scan-top,
                           sfm, top, bottom, bottom, {})
    for row in rows:
        correction = row["scan_correction_mm"]
        assert correction[0] > 1 and correction[4] < -1
        assert abs(correction.mean()) < 1e-12
        assert row["top_relief_mae_mm"] < 1e-12
        error = row["errors_mm"]
        assert error["shifted"] == pytest.approx(np.mean(error["each_shift"]))
        if case == "bilateral":
            assert error["aligned"] < .25
            assert error["aligned"] < error["body"] < error["shifted"]
        elif case == "top_only":
            assert error["body"] == 0 and error["aligned"] > .8
        else:
            assert np.argmin(error["each_shift"]) == 3  # Four sectors from the visible deviation.
            assert error["body"] < error["shifted"] < error["aligned"]


def test_half_coverage_and_cell_minimum_apply_to_joint_support():
    masks = [np.ones(40, dtype=bool), np.arange(40) < 19]
    scan = np.arange(40) < 29
    reference = np.arange(40) >= 10
    counts = coverage(masks, scan, reference)
    np.testing.assert_array_equal(counts["common"], [19, 9])
    np.testing.assert_array_equal(counts["required"], [20, 20])
    np.testing.assert_array_equal(counts["failed_sectors"], [0, 1])


def test_error_aggregation_uses_equal_sectors_and_averages_errors_of_shifts():
    bottom = np.zeros(4)
    masks = [np.array([True, False, False, False]), np.array([False, True, True, True])]
    measured = np.array([4., 0., 0., 0.])
    shifted = np.array([measured + 2, measured - 2])
    errors = error_summary(bottom, bottom, shifted, measured, masks)
    assert errors["body"] == 2
    assert errors["shifted"] == 2


def test_probe_rescores_nominal_and_perturbed_on_identical_cells():
    sectors = np.repeat(np.arange(8), 40)
    masks = [[sectors == s for s in range(8)]]
    bottom = np.full(len(sectors), 4.)
    top = np.full(len(sectors), 10.)
    scan = top + np.where(sectors == 0, 2., 0.)
    nominal = np.column_stack([bottom.copy(), top.copy()])
    nominal[0, 0] = 30
    perturbed = nominal.copy()
    perturbed[:, 0] += 1
    perturbed[0] = np.nan
    rows, _ = band_results(masks, sectors, scan, scan-top, nominal, top, bottom, bottom, {})
    score = probe_results(nominal, perturbed, scan-top, sectors, masks, top, bottom, rows)
    assert rows[0]["errors_mm"]["body"] > 0
    assert score["scored_cells"] == len(sectors)-1
    assert score["nominal_same_support_mm"]["body"] == 0
    assert score["perturbed_mm"]["body"] == 1
    assert score["bands"][0]["lost_cells"][0] == 1

    perturbed[:21] = np.nan
    score = probe_results(nominal, perturbed, scan-top, sectors, masks, top, bottom, rows)
    np.testing.assert_array_equal(score["bands"][0]["failed_sectors"], [0])
    assert score["scored_bands"] == 0 and score["nominal_same_support_mm"] is None


def test_weight_curve_applies_absolute_error_after_cell_prediction():
    body = np.array([2., 2., 2.])
    correction = np.array([2., 2., -2.])
    measured = np.array([1., 1., 3.])
    sectors = [np.array([True, True, False]), np.array([False, False, True])]
    np.testing.assert_array_equal(weight_curve(body, correction, measured, sectors),
                                  [1., .5, 0., .5, 1.])


def test_fold_selection_excludes_test_tuber_and_prefers_lower_tied_weight():
    curves = np.array([[4., 3., 2., 1., 0.],
                       [0., 1., 2., 3., 4.],
                       [0., 0., 1., 2., 3.]])
    folds = select_fold_weights(curves)
    assert [index for index, _ in folds] == [0, 1, 0]
    np.testing.assert_array_equal(folds[1][1], [2., 1.5, 1.5, 1.5, 1.5])
