import json

import numpy as np
import pytest

from potato3d.completion import METHODS
from potato3d.completion.confidence import local_depth_confidence
from potato3d.geometry import mesh_quality
from potato3d.spatial_analysis import criterion_passes
from potato3d.spatial_study import (load_spatial_protocol, selection_scores, spatial_samples,
                                    study_config, validate_selection)


def quadratic_fixture():
    rng = np.random.default_rng(7101)
    xy = rng.uniform(-20, 20, (900, 2))
    xy = np.vstack([xy, [0., 0.]])
    z = 44-.012*xy[:, 0]**2-.018*xy[:, 1]**2
    return np.column_stack([xy, z])


def test_clean_quadratic_preserves_all_points_including_apex():
    points = quadratic_fixture()
    confidence = local_depth_confidence(points)
    assert confidence.trusted.all()
    assert confidence.predicted_height[-1] == pytest.approx(44, abs=1e-4)
    assert np.array_equal(confidence.score, np.ones(len(points)))


def test_isolated_positive_spikes_do_not_determine_their_own_prediction():
    points = quadratic_fixture()
    spikes = np.array([5, 29, 83, 138, 254, 378, 491, 632, 725, 845, 900])
    corrupted = points.copy()
    corrupted[spikes, 2] += 15
    confidence = local_depth_confidence(corrupted)
    assert np.mean(~confidence.trusted[spikes]) > .9
    assert np.mean(~confidence.trusted[np.setdiff1d(np.arange(len(points)), spikes)]) < .02
    assert confidence.predicted_height[-1] == pytest.approx(44, abs=.3)


def test_negative_depression_is_not_rejected_by_positive_residual_gate():
    points = quadratic_fixture()
    points[-1, 2] -= 8
    confidence = local_depth_confidence(points)
    assert confidence.residual[-1] < -7
    assert confidence.trusted[-1]


def test_confidence_is_xy_rigid_equivariant_and_height_translation_invariant():
    points = quadratic_fixture()
    points[20, 2] += 15
    c, s = np.cos(.73), np.sin(.73)
    transformed = points.copy()
    transformed[:, :2] = points[:, :2]@np.array([[c, s], [-s, c]])+[13, -8]
    transformed[:, 2] += 7
    before, after = local_depth_confidence(points), local_depth_confidence(transformed)
    assert np.array_equal(before.trusted, after.trusted)
    assert after.predicted_height == pytest.approx(before.predicted_height+7, abs=1e-4)


def test_duplicate_xy_neighborhoods_use_finite_explicit_fallback():
    points = np.column_stack([np.zeros(24), np.zeros(24), np.arange(24.)])
    points = np.vstack([points, [[20, 0, 10], [0, 20, 12], [20, 20, 13]]])
    confidence = local_depth_confidence(points, neighbors=8)
    assert confidence.fallback.any()
    assert np.isfinite(confidence.predicted_height).all()
    assert np.isfinite(confidence.threshold).all()


@pytest.mark.parametrize("method", ["symmetry_spatial", "symmetry_spatial_height", "symmetry_spatial_surface"])
def test_spatial_interventions_make_closed_meshes_without_mutating_inputs(method):
    from potato3d.development import DevelopmentShape
    shape = DevelopmentShape(axes=(38., 28., 22.), waist=.21, yaw=.41, underside_warp=1.1)
    points = shape.partial(1300, 7102, outlier_fraction=.02)
    before = points.copy()
    mesh, parameters = METHODS[method](points)
    assert np.array_equal(before, points)
    quality = mesh_quality(mesh)
    assert quality["volume_valid"]
    assert quality["degenerate_faces"] == 0
    assert mesh.bounds[0, 2] >= -1e-8
    assert parameters["flagged_points"] > 0
    assert parameters["confidence_is_calibrated_probability"] is False


def test_invalid_confidence_settings_fail():
    with pytest.raises(ValueError, match="six"):
        local_depth_confidence(quadratic_fixture(), neighbors=3)
    with pytest.raises(ValueError, match="Positive finite"):
        local_depth_confidence(quadratic_fixture(), threshold_mm=np.nan)


def test_confirmation_generator_is_closed_without_validated_selection():
    with pytest.raises(ValueError, match="closed"):
        next(spatial_samples({}, {"split": "confirmation"}))
    protocol = load_spatial_protocol()
    with pytest.raises(ValueError, match="selection"):
        study_config(protocol, "confirmation")
    for key in ["shape_seed", "observation_seed", "evaluation_seed"]:
        assert protocol["splits"]["development"][key] != protocol["splits"]["confirmation"][key]


def test_confirmation_selection_rejects_changed_source(tmp_path, monkeypatch):
    import potato3d.spatial_study as study
    from potato3d.io import sha256
    path = tmp_path/"selection.json"
    path.write_text(json.dumps({"protocol_sha256": sha256(study.PROTOCOL_PATH),
                                "design_sha256": sha256(study.DESIGN_PATH),
                                "source_sha256": {"old.py": "old"}, "lock_sha256": "x"}))
    monkeypatch.setattr(study, "environment", lambda: {"source_sha256": {"changed.py": "new"}, "lock_sha256": "x"})
    with pytest.raises(ValueError, match="Source/lock"):
        validate_selection(path)


def test_selection_uses_only_development_score_and_fixed_option_order():
    protocol = {"splits": {"development": {"families": 1}}, "candidate_options": [{"name": "a"}, {"name": "b"}]}
    rows, metadata = [], []
    for condition in ["clean", "outliers_2percent"]:
        for twin in range(2):
            metadata.append({"object_id": str(twin), "condition": condition, "family_id": "one"})
            for option, error in [(0, 2.), (1, 1.)]:
                rows.append({"object_id": str(twin), "condition": condition,
                             "method": f"symmetry_spatial_option_{option}", "hidden_chamfer_l1_mm": error,
                             "volume_absolute_error_analytic_ml": 10.})
    scores = selection_scores(rows, metadata, protocol)
    assert scores[0]["selection_score"] == pytest.approx(4.2)
    assert scores[1]["selection_score"] == pytest.approx(2.2)


def test_confirmation_noninferiority_is_strict_where_predefined():
    result = {"missing_shape_pairs": [], "ci95": [-.1, 0.], "independent_families": 12}
    assert not criterion_passes(result, {"upper_difference_limit": 0., "strict": True}, 12)
    assert criterion_passes(result, {"upper_difference_limit": .1, "strict": False}, 12)
    result["missing_shape_pairs"] = ["missing"]
    assert not criterion_passes(result, {"upper_difference_limit": .1, "strict": False}, 12)
