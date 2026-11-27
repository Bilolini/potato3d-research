import numpy as np
import trimesh

from audit import reference_heights


def test_open_mesh_rays_reject_missing_and_extra_crossings():
    box = trimesh.creation.box(extents=(2, 2, 4))
    # Remove one of the two lower triangles. The opposite half remains usable.
    bottom = np.flatnonzero(box.face_normals[:, 2] < -.99)
    retained = np.ones(len(box.faces), dtype=bool)
    retained[bottom[0]] = False
    box.update_faces(retained)
    xy = np.array([[-.4, -.4], [.4, .4], [3., 3.]])
    bounds, counts = reference_heights(box, xy)
    np.testing.assert_array_equal(np.sort(counts), [0, 1, 2])
    np.testing.assert_allclose(bounds[counts == 2], [[-2, 2]])
    assert np.isnan(bounds[counts != 2]).all()

    nested = trimesh.util.concatenate([trimesh.creation.box(extents=(2, 2, 4)),
                                        trimesh.creation.box(extents=(1, 1, 1))])
    bounds, counts = reference_heights(nested, xy)
    np.testing.assert_array_equal(counts, [4, 4, 0])
    assert np.isnan(bounds).all()


def test_shared_triangle_edges_count_as_one_crossing():
    box = trimesh.creation.box(extents=(2, 2, 4))
    bounds, counts = reference_heights(box, np.array([[0., 0.]]))
    np.testing.assert_array_equal(counts, [2])
    np.testing.assert_allclose(bounds, [[-2, 2]])

    box.invert()
    bounds, counts = reference_heights(box, np.array([[0., 0.]]))
    np.testing.assert_array_equal(counts, [2])
    assert np.isnan(bounds).all()
