import numpy as np
import pytest

from potato3d.completion import METHODS
from potato3d.development import DevelopmentShape, load_protocol
from potato3d.geometry import mesh_quality
from potato3d.pipeline import summarize


@pytest.mark.parametrize("waist,warp", [(0., 1.8), (.4, 1.8), (.2, 0.)])
def test_hidden_warp_analytic_volume_matches_independent_mesh(waist, warp):
    shape = DevelopmentShape(axes=(36., 24., 19.), waist=waist, underside_warp=warp, belt_offset_mm=3.)
    mesh = shape.mesh()
    quality = mesh_quality(mesh)
    assert quality["volume_valid"]
    assert quality["volume_ml"] == pytest.approx(shape.volume_ml, rel=.005)
    assert mesh.bounds[0, 2] == pytest.approx(3., abs=1e-8)


def test_ambiguous_undersides_have_identical_observations_and_different_volumes():
    a = DevelopmentShape(axes=(36., 24., 19.), waist=.3, underside_warp=0.)
    b = DevelopmentShape(axes=a.axes, waist=a.waist, underside_warp=1.8)
    for regime in [{}, {"noise_mm": 2.}, {"outlier_fraction": .02}, {"gap": True}]:
        assert np.array_equal(a.partial(1200, 91, **regime), b.partial(1200, 91, **regime))
    assert abs(a.volume_ml-b.volume_ml) > 5
    assert np.array_equal(a.mesh().vertices[a.mesh().vertices[:, 2] >= 19],
                          b.mesh().vertices[b.mesh().vertices[:, 2] >= 19])


@pytest.mark.parametrize("method", ["symmetry_height95", "symmetry_robust95"])
def test_robust_variants_use_only_points_and_respect_assumed_belt(method):
    p = DevelopmentShape(axes=(36., 24., 19.)).partial(1200, 92, outlier_fraction=.02)
    original = p.copy()
    mesh, parameters = METHODS[method](p)
    assert np.array_equal(p, original)
    assert parameters["height_mm"] == pytest.approx(np.quantile(p[:, 2], .95))
    assert mesh_quality(mesh)["volume_valid"]
    assert mesh_quality(mesh)["degenerate_faces"] == 0
    assert mesh.bounds[0, 2] >= -1e-8


def test_default_symmetry_is_identical_to_explicit_max_height():
    p = DevelopmentShape(axes=(36., 24., 19.)).partial(1200, 93)
    default, _ = METHODS["symmetry"](p)
    explicit, _ = METHODS["symmetry"](p, height_mm=p[:, 2].max())
    assert np.array_equal(default.vertices, explicit.vertices)
    assert np.array_equal(default.faces, explicit.faces)


def test_twins_are_one_analysis_cluster_not_independent_objects():
    rows = [{"object_id": f"o{i}", "analysis_cluster_id": "family", "method": "m", "condition": "c",
             "status": "ok", "chamfer_l1_mm": 2.} for i in range(12)]
    summary = summarize(rows)[0]
    assert summary["objects_with_chamfer_l1_mm"] == 12
    assert summary["independent_clusters_with_chamfer_l1_mm"] == 1
    assert summary["ci95_chamfer_l1_mm"] is None


def test_sealed_development_protocol_loads():
    from pathlib import Path
    protocol, config = load_protocol(Path("configs/height_development_v1.yaml"))
    assert protocol["families"] == 12
    assert len(config["methods"]) == 5


def test_paired_analysis_resamples_families_and_marks_missing_pairs():
    from potato3d.study_analysis import paired_difference
    rows, metadata = [], []
    for family in range(12):
        for twin in range(2):
            pid = f"f{family}_t{twin}"
            metadata.append({"object_id": pid, "condition": "c", "family_id": f"f{family}", "underside_warp": twin})
            for method, error in [("baseline", 5.), ("candidate", 3.)]:
                rows.append({"object_id": pid, "condition": "c", "method": method, "status": "ok", "metric": error})
    protocol = {"bootstrap_replicates": 100, "bootstrap_seed": 98}
    result = paired_difference(rows, metadata, "candidate", "baseline", "c", "metric", protocol)
    assert result["mean"] == -2
    assert result["ci95"] == [-2, -2]
    assert result["available_shape_pairs"] == 24
    assert result["independent_families"] == 12
    rows[-1]["status"] = "failed"
    result = paired_difference(rows, metadata, "candidate", "baseline", "c", "metric", protocol)
    assert result["complete_case_only"]
    assert result["available_shape_pairs"] == 23
