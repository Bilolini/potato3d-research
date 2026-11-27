"""Analytic checks for offset sign, weighted medians and held-out sector isolation."""
import numpy as np
import pytest

from studies.regional_shape_v1.vertical_offset import score_offset, weighted_offset


def make_fixture(sector_values):
    values = np.concatenate([sector for band in sector_values for sector in band]).astype(float)
    cell = np.arange(len(values))
    masks = []
    start = 0
    for band in sector_values:
        band_masks = []
        for sector in band:
            stop = start + len(sector)
            band_masks.append((cell >= start) & (cell < stop))
            start = stop
        masks.append(band_masks)
    return values, masks


@pytest.mark.parametrize("offset", [-2.5, 3.25])
def test_constant_offset_transfers(offset):
    residual, masks = make_fixture([[[offset], [offset]*3], [[offset]*2, [offset]]])
    score = score_offset(residual, masks)
    assert score["vertical_shift_mm"] == offset
    assert score["body_mae_mm"] == abs(offset)
    assert score["best_achievable_mae_mm"] == 0
    assert score["held_out_shifted_mae_mm"] == 0
    assert score["held_out_change_mm"] == -abs(offset)


def test_zero_offset_with_nonzero_residual_error():
    residual, masks = make_fixture([[[-2, 0, 2], [-2, 0, 2]]])
    score = score_offset(residual, masks)
    assert score["vertical_shift_mm"] == 0
    assert score["best_achievable_mae_mm"] == score["body_mae_mm"] == pytest.approx(4/3)
    assert score["held_out_change_mm"] == 0


def test_band_and_sector_weights_balance_unequal_cell_counts():
    residual, masks = make_fixture([[[0]*100, [0]], [[4], [4]*3]])
    assert weighted_offset(residual, masks) == 2
    residual, masks = make_fixture([[[0]*100, [10]], [[10], [10]]])
    assert weighted_offset(residual, masks) == 10


def test_exact_sector_weights_can_exceed_fixed_size_integers():
    lengths = (101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151, 157, 163, 167, 173, 179)
    sectors = [[i]*size for i, size in enumerate(lengths)]
    residual, masks = make_fixture([sectors[:8], sectors[8:]])
    assert weighted_offset(residual, masks) == 7.5


def test_held_out_parities_do_not_enter_their_fit():
    residual, masks = make_fixture([[[4]*3, [-2], [4], [-2]*8]])
    score = score_offset(residual, masks)
    assert score["vertical_shift_mm"] == 1
    assert score["best_change_mm"] == 0
    assert score["directions"]["even_to_odd"]["training_shift_mm"] == 4
    assert score["directions"]["odd_to_even"]["training_shift_mm"] == -2
    assert score["held_out_body_mae_mm"] == 3
    assert score["held_out_change_mm"] == 3
