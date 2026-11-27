import json

import numpy as np
import pytest
from scipy.integrate import dblquad

from potato3d.completion import METHODS
from potato3d.completion.multiscale import annular_depth_confidence, supported_components
from potato3d.completion.confidence import DepthConfidence
from potato3d.geometry import mesh_quality
from potato3d.multiscale_study import load_protocol, make_config, samples, validate_selection
from potato3d.protrusions import ProtrusionShape


@pytest.mark.parametrize("radius", [.10, .22])
def test_protrusion_volume_against_independent_integration_and_mesh(radius):
    shape = ProtrusionShape(axes=(39., 26., 21.), waist=.28, yaw=.63, underside_warp=1.8,
                            bump_amplitude_mm=8., bump_radius_unit=radius)
    u0, v0 = shape.bump_center_unit
    def integrand(v, u):
        jacobian = shape.axes[0]*shape.axes[1]*(1-shape.waist+shape.waist*u*u)
        return jacobian*shape.bump_height_unit(u, v)
    integral, _ = dblquad(integrand, u0-radius, u0+radius,
                         lambda u: v0-np.sqrt(max(0, radius*radius-(u-u0)**2)),
                         lambda u: v0+np.sqrt(max(0, radius*radius-(u-u0)**2)), epsabs=1e-8)
    assert shape.added_volume_ml == pytest.approx(integral/1000, rel=1e-7)
    mesh = shape.mesh(5)
    assert mesh_quality(mesh)["volume_valid"]
    assert mesh.volume/1000 == pytest.approx(shape.volume_ml, rel=.003)
    assert shape.true_height_mm > 2*shape.axes[2]
    assert shape.true_height_mm <= 2*shape.axes[2]+8+1e-6


def test_feature_masks_are_localized_and_evaluation_only():
    shape = ProtrusionShape(axes=(39., 26., 21.), waist=.28, bump_amplitude_mm=8.)
    points = shape.partial(1600, 8101)
    feature = shape.feature_indices(points)
    assert 0 < len(feature) < len(points)*.1
    unfeatured = ProtrusionShape(axes=shape.axes, waist=shape.waist)
    assert not len(unfeatured.feature_indices(unfeatured.partial(1600, 8101)))


def grid_fixture():
    x, y = np.meshgrid(np.linspace(-20, 20, 31), np.linspace(-20, 20, 31))
    return np.column_stack([x.ravel(), y.ravel(), (44-.01*x*x-.015*y*y).ravel()])


def test_annular_fit_preserves_quadratic_and_excludes_inner_patch():
    points = grid_fixture()
    clean = annular_depth_confidence(points, inner_neighbors=32, outer_neighbors=160)
    assert clean.trusted.all()
    center = np.argmin(np.linalg.norm(points[:, :2], axis=1))
    corrupted = points.copy()
    mask = np.linalg.norm(points[:, :2], axis=1) <= 3
    corrupted[mask, 2] += 15
    result = annular_depth_confidence(corrupted, inner_neighbors=32, outer_neighbors=160)
    assert not result.trusted[center]
    assert result.predicted_height[center] == pytest.approx(points[center, 2], abs=.2)


def test_component_gate_accepts_abrupt_patch_but_not_smooth_bump():
    points = grid_fixture()
    radius = np.linalg.norm(points[:, :2], axis=1)
    for residual, expected in [(np.where(radius <= 3, 15., 0.), True),
                                (8*np.maximum(0, 1-(radius/7)**2)**3, False)]:
        broad = DepthConfidence(residual <= 3, points[:, 2], residual,
                                np.full(len(points), 3.), np.ones(len(points)), np.zeros(len(points), dtype=bool))
        accepted, info = supported_components(points, broad)
        assert accepted.any() == expected
        assert info["accepted_components"] > 0 if expected else info["accepted_components"] == 0


@pytest.mark.parametrize("method", ["symmetry_annular", "symmetry_multiscale"])
def test_multiscale_methods_make_closed_meshes_and_leave_input_unchanged(method):
    shape = ProtrusionShape(axes=(39., 26., 21.), waist=.28, bump_amplitude_mm=8.)
    points = shape.partial(1300, 8102, outlier_fraction=.02)
    before = points.copy()
    mesh, parameters = METHODS[method](points)
    assert np.array_equal(points, before)
    quality = mesh_quality(mesh)
    assert quality["volume_valid"]
    assert quality["degenerate_faces"] == 0
    assert mesh.bounds[0, 2] >= -1e-8
    assert parameters["confidence_is_calibrated_probability"] is False
    flagged = set(parameters["suspect_point_indices"])
    assert all(0 <= i < len(points) for i in flagged)


def test_multiscale_confirmation_is_closed_and_seeds_disjoint():
    with pytest.raises(ValueError, match="closed"):
        next(samples({}, {"split": "confirmation"}))
    protocol = load_protocol()
    with pytest.raises(ValueError, match="selection"):
        make_config(protocol, "confirmation")
    for name in ["shape_seed", "observation_seed", "evaluation_seed"]:
        assert protocol["splits"]["development"][name] != protocol["splits"]["confirmation"][name]


def test_multiscale_selection_rejects_source_changes(tmp_path, monkeypatch):
    import potato3d.multiscale_study as study
    from potato3d.io import sha256
    path = tmp_path/"selection.json"
    path.write_text(json.dumps({"protocol_sha256": sha256(study.PROTOCOL_PATH),
                                "design_sha256": sha256(study.DESIGN_PATH),
                                "source_sha256": {"old": "old"}, "lock_sha256": "x"}))
    monkeypatch.setattr(study, "environment", lambda: {"source_sha256": {"changed": "new"}, "lock_sha256": "x"})
    with pytest.raises(ValueError, match="Frozen source"):
        validate_selection(path)


def test_single_scale_leaf_matches_its_previously_frozen_implementation():
    from pathlib import Path
    from potato3d.io import sha256
    previous = json.loads(Path("docs/spatial_confidence_selection_v1.json").read_text())
    assert sha256(Path("src/potato3d/completion/confidence.py")) == previous["source_sha256"]["completion/confidence.py"]


def test_invalid_annular_settings_fail_explicitly():
    with pytest.raises(ValueError, match="six"):
        annular_depth_confidence(grid_fixture(), inner_neighbors=32, outer_neighbors=34)
    with pytest.raises(ValueError, match="inside"):
        ProtrusionShape(bump_radius_unit=.9)
