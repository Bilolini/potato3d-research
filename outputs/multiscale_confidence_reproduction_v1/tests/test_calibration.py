import numpy as np
import pytest

from potato3d.calibration import depth_points, fit_plane_ransac, intrinsics_from_json, plane_transform, verify_ply_depth
from potato3d.geometry import rigid_matrix, transform_points


def test_pinhole_reprojection_uses_column_major_intrinsics():
    matrix = np.array([[500., 0, 2], [0, 510., 3], [0, 0, 1]])
    loaded = intrinsics_from_json({"intrinsic_matrix": matrix.flatten(order="F").tolist()})
    assert np.array_equal(matrix, loaded)
    depth = np.full((7, 8), 350.)
    pixels = np.array([[1, 1], [3, 4], [6, 5]])
    points = depth_points(depth, pixels, matrix)
    audit = verify_ply_depth(points, depth, np.ones_like(depth), matrix)
    assert audit["max_xyz_reprojection_error_mm"] < 1e-10
    assert audit["fraction_inside_object_alpha"] == 1


def test_background_ransac_plane_is_reference_free_and_proper():
    rng = np.random.default_rng(94)
    xy = rng.uniform(-120, 120, (1000, 2))
    z = .02*xy[:, 0]-.01*xy[:, 1]+351+rng.normal(0, .15, len(xy))
    z[:300] -= rng.uniform(5, 40, 300)
    coefficients = fit_plane_ransac(np.column_stack([xy, z]), seed=95)
    assert coefficients == pytest.approx([.02, -.01, 351], abs=.04)
    t = rigid_matrix(plane_transform(coefficients))
    exact = np.column_stack([xy, np.column_stack([xy, np.ones(len(xy))])@coefficients])
    assert np.max(np.abs(transform_points(exact, t)[:, 2])) < 1e-9
    assert transform_points([[0, 0, 300]], t)[0, 2] > 0


def test_too_few_background_points_fail_explicitly():
    with pytest.raises(ValueError, match="at least 20"):
        fit_plane_ransac(np.zeros((4, 3)))
