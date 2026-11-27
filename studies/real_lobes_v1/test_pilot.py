import numpy as np

from pilot import detect_and_match, measure_patch, observed_grid


def test_scan_detects_coherent_lobe_and_ignores_isolated_spike():
    axis = np.arange(-24., 25.)
    xy = np.stack(np.meshgrid(axis, axis), axis=-1).reshape(-1, 2)
    background = 30 - np.sum(xy**2, axis=1) / 120
    lobe_center = np.array([10., 0.])
    r = np.linalg.norm(xy-lobe_center, axis=1)
    lobe = 4*np.maximum(1-r**2/36, 0)**2
    cloud = np.column_stack([xy, background + lobe])
    cloud[np.all(xy == [12, 10], axis=1), 2] += 20
    grid, depth, height = observed_grid(cloud)
    matches, eligible = detect_and_match(grid, depth, height)
    assert eligible > 0
    assert len(matches) == 1
    patch, control = matches[0]
    assert np.linalg.norm(grid[patch.center]-lobe_center) <= 1
    assert control is not None

    distance = np.linalg.norm(grid-lobe_center, axis=1)
    lower_background = 4 + np.sum(grid**2, axis=1)/180
    lower_lobe = lower_background - 3*np.maximum(1-distance**2/36, 0)**2
    bounds = np.column_stack([lower_lobe, height])
    measured = measure_patch(bounds, patch)
    assert measured["underside"]["relief_mm"] > 1.5
    assert abs(measure_patch(bounds, control)["underside"]["relief_mm"]) < .1
    bounds[patch.core[:len(patch.core)//2]] = np.nan
    assert measure_patch(bounds, patch)["underside"]["relief_mm"] is None


def test_smooth_surface_does_not_trigger_detector():
    axis = np.arange(-20., 21.)
    grid = np.stack(np.meshgrid(axis, axis), axis=-1).reshape(-1, 2)
    depth = 20 - np.abs(grid).max(axis=1)
    matches, eligible = detect_and_match(grid, depth, 40 - np.sum(grid**2, axis=1)/140)
    assert eligible > 0
    assert matches == []
