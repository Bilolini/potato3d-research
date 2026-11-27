import numpy as np
import pytest
import trimesh

from potato3d.metrics import evaluate, point_cloud_metrics, surface_distances
from potato3d.pipeline import summarize


def test_known_unsquared_chamfer_and_threshold_convention():
    a = np.array([[0., 0., 0.], [10., 0., 0.]])
    b = a + [0, 3, 0]
    m = point_cloud_metrics(a, b, [2, 3, 5])
    assert m["chamfer_l1_mm"] == 3
    assert m["fscore_2mm"] == 0
    assert m["fscore_3mm"] == 1  # inclusive boundary
    assert point_cloud_metrics(a, a)["chamfer_l1_mm"] == 0


def test_precision_recall_directions_and_zero_denominator():
    a = np.array([[0., 0., 0.]])
    b = np.array([[0., 0., 0.], [100., 0., 0.]])
    m = point_cloud_metrics(a, b)
    assert m["precision_5mm"] == 1
    assert m["recall_5mm"] == .5
    assert m["fscore_5mm"] == pytest.approx(2/3)
    assert point_cloud_metrics(a, a+100)["fscore_5mm"] == 0


def test_exact_observed_triangle_distance():
    box = trimesh.creation.box(extents=[2, 2, 2])
    assert surface_distances([[0, 0, 4], [1, 0, 0], [0, 0, 0]], box) == pytest.approx([3, 0, 1])


def test_volume_targets_remain_separate_and_null_for_open_reference():
    m = trimesh.creation.box(extents=[10, 10, 10])
    r = m.copy()
    r.update_faces(np.arange(len(r.faces)-1))
    config = {"seed": 1, "surface_samples": 100, "thresholds_mm": [5]}
    result = evaluate(m, r, [[0,0,5]], config, physical_volume_ml=2, reported_sfm_volume_ml=3)
    assert result["reference_mesh_volume_ml"] is None
    assert result["volume_absolute_error_mesh_ml"] is None
    assert result["volume_absolute_error_physical_ml"] == 1
    assert result["volume_absolute_error_reported_sfm_ml"] == 2


def test_aggregation_weights_objects_and_reports_failures():
    rows = [{"object_id": "a", "method": "x", "condition": "clean", "status": "ok", "chamfer_l1_mm": 2},
            {"object_id": "a", "method": "x", "condition": "clean", "status": "ok", "chamfer_l1_mm": 4},
            {"object_id": "b", "method": "x", "condition": "clean", "status": "ok", "chamfer_l1_mm": 10},
            {"object_id": "c", "method": "x", "condition": "clean", "status": "failed"}]
    summary = summarize(rows)[0]
    assert summary["mean_chamfer_l1_mm"] == 6.5
    assert summary["attempted_frames"] == 4
    assert summary["failed_frames"] == 1
    assert summary["successful_objects"] == 2
    assert summary["ci95_chamfer_l1_mm"] is None
