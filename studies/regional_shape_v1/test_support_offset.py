"""Check the fixed depth-to-height conversion and exhaustive shuffle accounting."""
import numpy as np
import pytest

from studies.regional_shape_v1.support_offset import shift_at_center, shuffled_control


@pytest.mark.parametrize(("plane_depth", "expected_shift"), [(350., 0.), (353., -3.)])
def test_horizontal_plane_shift(plane_depth, expected_shift):
    _, depth, shift = shift_at_center([0., 0., plane_depth], [27., 36.])
    assert depth == plane_depth
    assert shift == expected_shift


def test_sloped_plane_uses_camera_y_down():
    camera_xy, depth, shift = shift_at_center([.01, .02, 353.], [20., 50.])
    np.testing.assert_array_equal(camera_xy, [20., -50.])
    assert depth == pytest.approx(352.2)
    assert shift == pytest.approx(-2.2)


def test_all_labelled_assignments_include_the_identity():
    control = shuffled_control(np.array([[1., 9., 8.], [8., 2., 8.], [8., 9., 3.]]))
    assert control["assignments_including_identity"] == 6
    assert control["assignments_strictly_better"] == 0
    assert control["assignments_tied"] == 1
    assert control["correct_assignment_rank_from_lowest"] == [1, 1]
    assert control["mean_assignment_mae_mm"] == pytest.approx(56/9)


def test_identical_shift_values_preserve_assignment_multiplicity():
    costs = np.array([[1., 1., 5.], [1., 1., 3.], [3., 3., 0.]])
    control = shuffled_control(costs)
    assert control["assignments_including_identity"] == 6
    assert control["assignments_strictly_better"] == 0
    assert control["correct_assignment_rank_from_lowest"] == [1, 2]
