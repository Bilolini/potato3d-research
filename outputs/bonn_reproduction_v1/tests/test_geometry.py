import numpy as np
import pytest
import trimesh

from potato3d.geometry import (camera_to_belt_mm, check_scale_mm, mesh_quality,
                               rigid_matrix, sample_surface, transform_points)
from potato3d.synthetic import AnalyticShape


def test_units_and_handedness():
    t = camera_to_belt_mm(350)
    assert np.linalg.det(t[:3, :3]) == 1
    assert np.allclose(transform_points([[10, 20, 300]], t), [[10, -20, 50]])
    assert np.allclose(transform_points(transform_points([[10, 20, 300]], t), np.linalg.inv(t)), [[10, 20, 300]])
    with pytest.raises(ValueError, match="scaling"):
        rigid_matrix(np.diag([2., 2., 2., 1.]))
    with pytest.raises(ValueError, match="units"):
        check_scale_mm(trimesh.creation.icosphere(radius=.04).vertices)
    with pytest.raises(ValueError, match="Non-finite"):
        check_scale_mm(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, np.nan]]))


@pytest.mark.parametrize("waist", [0., .55])
def test_analytic_volume_independent_of_mesh(waist):
    shape = AnalyticShape(waist=waist)
    mesh = shape.mesh()
    q = mesh_quality(mesh)
    assert q["volume_valid"]
    assert abs(q["volume_ml"] / shape.volume_ml - 1) < .003
    assert mesh.bounds[0, 2] == pytest.approx(0, abs=1e-8)


def test_sampling_is_local_and_area_weighted():
    # Two disconnected triangles, area ratio 1:4, beyond accidental location bias.
    mesh = trimesh.Trimesh(vertices=[[0,0,0],[1,0,0],[0,1,0],[10,0,0],[12,0,0],[10,2,0]],
                           faces=[[0,1,2],[3,4,5]], process=False)
    np.random.seed(123)
    expected = np.random.random()
    np.random.seed(123)
    a, face = sample_surface(mesh, 12000, 527)
    assert np.random.random() == expected
    assert np.array_equal(a, sample_surface(mesh, 12000, 527)[0])
    assert np.mean(face == 1) == pytest.approx(.8, abs=.015)


def test_open_mesh_volume_is_unavailable():
    box = trimesh.creation.box(extents=[20, 30, 40])
    box.update_faces(np.arange(len(box.faces)-1))
    q = mesh_quality(box)
    assert not q["watertight"]
    assert q["volume_ml"] is None
    assert q["boundary_edges"] > 0
