import numpy as np
import pytest

from potato3d.completion import METHODS
from potato3d.geometry import mesh_quality
from potato3d.synthetic import AnalyticShape


@pytest.mark.parametrize("method", list(METHODS))
def test_baselines_produce_deterministic_closed_shapes(method):
    shape = AnalyticShape()
    points = shape.partial(1800, 527)
    assert np.min(points[:, 2]) > shape.axes[2]  # no underside supplied
    original = points.copy()
    a, _ = METHODS[method](points)
    b, _ = METHODS[method](points)
    assert np.array_equal(points, original)
    assert np.array_equal(a.vertices, b.vertices)
    q = mesh_quality(a)
    assert q["volume_valid"]
    assert q["degenerate_faces"] == 0
    assert q["nonmanifold_edges"] == 0
    assert a.bounds[0, 2] == pytest.approx(0, abs=1e-7)
    if method == "ellipsoid":
        assert q["volume_ml"] == pytest.approx(shape.volume_ml, rel=.015)
    if method == "symmetry":
        assert q["volume_ml"] == pytest.approx(shape.volume_ml, rel=.035)
    if method == "convex":
        # The flat base overfills a rounded underside: an intentional, explicit baseline limitation.
        assert q["volume_ml"] > shape.volume_ml*1.15


def test_upper_concavity_is_present_in_analytic_shape():
    shape = AnalyticShape(waist=.55, yaw=0)
    assert shape.volume_ml < AnalyticShape(yaw=0).volume_ml*.6
    m = shape.mesh()
    assert m.convex_hull.volume > m.volume*1.02


def test_symmetry_closes_quantized_rgbd_rows():
    # Pinhole rays with integer-mm depths create exactly collinear scan rows,
    # including nearly zero projected-area Delaunay faces on some platforms.
    u, v = np.meshgrid(np.arange(-50, 51), np.arange(-40, 41))
    mask = (u/50)**2 + (v/40)**2 < .99
    u, v = u[mask], v[mask]
    height = np.round(22 + 22*np.sqrt(1 - (u/50)**2 - (v/40)**2))
    depth = 350-height
    points = np.column_stack([u*depth/650, v*depth/650, height])
    mesh, _ = METHODS["symmetry"](points)
    quality = mesh_quality(mesh)
    assert quality["volume_valid"]
    assert quality["degenerate_faces"] == 0
    assert quality["nonmanifold_edges"] == 0
