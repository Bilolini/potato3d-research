import json
import numpy as np
import pytest
import trimesh

from potato3d.geometry import transform_points
from potato3d.io import load_demo_pair, safe_path


def test_fixed_registration_inversion_and_meter_translation(tmp_path):
    # Make a reference by applying the *released convention* camera->SfM in meters.
    camera = trimesh.creation.icosphere(subdivisions=1, radius=.02)
    camera.apply_translation([.03, -.01, .30])
    t = np.eye(4)
    t[:3, :3] = [[0,-1,0],[1,0,0],[0,0,1]]
    t[:3, 3] = [.1, .2, .3]
    reference = camera.copy()
    reference.apply_transform(t)
    reference.export(tmp_path/"ref.ply")
    trimesh.points.PointCloud(camera.vertices).export(tmp_path/"partial.ply")
    record = {"partial": "partial.ply", "reference": "ref.ply", "unit": "m", "rgbd_to_sfm_m": t.tolist()}
    points, mesh, _ = load_demo_pair(tmp_path, record, 350)
    assert np.allclose(points, mesh.vertices, atol=1e-4)
    assert np.max(points[:, 2]) == pytest.approx(70, abs=1e-4)
    with pytest.raises(ValueError, match="escapes"):
        safe_path(tmp_path, "../private.json")
