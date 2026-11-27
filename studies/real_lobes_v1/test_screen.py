from types import SimpleNamespace

import numpy as np

from screen import patch_flags, screen_raster


def test_raster_detects_hole_step_and_marker_independently():
    foreground = np.ones((27, 31), dtype=bool)
    depth = np.full(foreground.shape, 300, dtype=np.uint16)
    depth[7, 10] = 0
    depth[:, 23:] = 304
    raster = screen_raster(foreground, depth, [(13, 19, 2, 2)])
    boundary = raster["foreground_boundary_or_missing_depth"]
    edge = raster["depth_discontinuity"]
    marker = raster["marker_overlap"]
    assert boundary[7, 11] and not edge[7, 11]
    assert edge[13, 22] and not boundary[13, 22]
    assert marker[19, 17] and not marker[19, 18]
    assert not boundary[10, 15] and not edge[10, 15] and not marker[10, 15]


def test_patch_checks_full_neighborhood_by_center():
    # The principal point is the XY origin. At z=300 mm one mm is one pixel.
    k = np.array([[300, 0, 50], [0, 300, 50], [0, 0, 1]])
    grid = np.array([[0., 0.], [8., 0.], [25., 0.], [26., 0.], [28., 0.]])
    points = np.column_stack([grid, np.full(len(grid), 50.)])
    mask = np.zeros((101, 101), dtype=bool)
    mask[50, 58] = True
    patches = [SimpleNamespace(center=0), SimpleNamespace(center=2)]
    assert patch_flags(points, grid, patches, k, {"marker_overlap": mask}) == {
        0: ["marker_overlap"], 2: [],
    }
