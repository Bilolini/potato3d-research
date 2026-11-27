import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest
import trimesh

from potato3d.bonn import depth_component, load_observations, validate_manifest, verified_member
from potato3d.fruit_completion import build_prior, ellipsoid_mesh, fit_ellipsoid, load_prior, TemplateCompleter
from potato3d.geometry import mesh_quality, sample_surface
from potato3d.io import sha256, write_json
from potato3d import fruit_study as study


def test_component_four_neighbor_jump_and_tie():
    valid = np.array([[1, 1, 0, 1], [0, 0, 1, 1]], dtype=bool)
    depth = np.array([[.3, .305, .3, .3], [.3, .3, .4, .3]])
    kept, audit = depth_component(valid, depth, 10, minimum=2)
    # Two size-two components tie; diagonal contact does not join them.
    np.testing.assert_array_equal(kept, [[1, 1, 0, 0], [0, 0, 0, 0]])
    assert audit["components"] == 3 and audit["retained_fraction"] == .4
    with pytest.raises(ValueError, match="below fixed minimum"):
        depth_component(valid, depth, 10, minimum=3)


def receipt(root, names):
    write_json(root/"download_manifest.json", {"members": [
        {"name": n, "bytes": (root/n).stat().st_size, "sha256": sha256(root/n), "crc32_verified": True} for n in names]})


def test_observation_pose_units_and_no_reference_access(tmp_path):
    k = np.array([[100., 0, 2], [0, 100., 2], [0, 0, 1]])
    write_json(tmp_path/"k.json", {"intrinsic_matrix": k.reshape(-1, order="F"), "width": 5, "height": 5})
    depth = np.full((5, 5), .3); depth[1:4, 1:4] = .305
    depth[0, 0] = np.nan; depth[0, 1] = 0; depth[0, 2] = 1
    np.save(tmp_path/"depth.npy", depth)
    Image.fromarray(np.ones((5, 5), dtype=np.uint8)).save(tmp_path/"mask.png")
    t = np.eye(4); t[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]; t[:3, 3] = [.01, -.02, -.25]
    np.savetxt(tmp_path/"pose.txt", t)
    names = ["k.json", "depth.npy", "mask.png", "pose.txt"]; receipt(tmp_path, names)
    record = dict(zip(["intrinsic", "depth", "mask", "pose"], names), reference="DOES_NOT_EXIST.ply", object_id="fixture", frame_id="0")
    clouds, audit = load_observations(tmp_path, record, minimum=4)
    assert len(clouds["raw_valid"]) == 22
    yy, xx = np.nonzero(np.isfinite(depth) & (depth > 0) & (depth < 1))
    camera = np.column_stack([(xx-2)/100, (yy-2)/100, np.ones(len(xx))])*depth[yy, xx, None]
    np.testing.assert_allclose(clouds["raw_valid"], (camera@t[:3, :3].T+t[:3, 3])*1000)
    assert audit["alignment"].endswith("no reference geometry accessed")
    (tmp_path/"k.json").write_text("tampered")
    with pytest.raises(ValueError, match="modified"):
        verified_member(tmp_path, record, "intrinsic")


def test_training_role_guard(tmp_path):
    with pytest.raises(ValueError, match="training objects only"):
        build_prior(tmp_path, [{"role": "holdout", "source_split": "val"}], tmp_path/"forbidden")
    assert not (tmp_path/"forbidden").exists()


def test_manifest_disjointness_and_hidden_test_guard():
    manifest = json.loads(Path("data/bonn_real_v1_manifest.json").read_text())
    validate_manifest(manifest)
    manifest["roles"]["holdout"].append(manifest["roles"]["train"][0])
    with pytest.raises(ValueError, match="cross roles"):
        validate_manifest(manifest)
    manifest = json.loads(Path("data/bonn_real_v1_manifest.json").read_text())
    manifest["objects"][-1]["source_split"] = "test"
    with pytest.raises(ValueError, match="hidden test"):
        validate_manifest(manifest)


def test_ellipsoid_fit_uses_partial_geometry_and_bounds():
    truth = ellipsoid_mesh([2, -3, 1], [33, 25, 41])
    points, _ = sample_surface(truth, 1500, 3)
    points = points[points[:, 2] > 8]
    prior = {"center_mm": [0, 0, 0], "radii_mm": [30, 30, 38]}
    mesh, parameters = fit_ellipsoid(points, prior, .15)
    assert mesh_quality(mesh)["volume_valid"]
    assert np.all(np.abs(np.array(parameters["center_mm"])) <= prior["radii_mm"])
    radii = np.array(parameters["radii_mm"])
    assert np.all(radii >= np.array(prior["radii_mm"])*.5)
    assert np.all(radii <= np.array(prior["radii_mm"])*2)
    # Independent analytic radial residual on the visible hemisphere improves.
    c = np.asarray(parameters["center_mm"])
    before = abs(np.linalg.norm(points/np.array(prior["radii_mm"]), axis=1)-1).mean()
    after = abs(np.linalg.norm((points-c)/radii, axis=1)-1).mean()
    assert after < before*.5


def make_prior(tmp_path):
    data = tmp_path/"data"; data.mkdir()
    mesh = ellipsoid_mesh([0, 0, 0], [30, 25, 40], subdivisions=2)
    points, _ = sample_surface(mesh, 1000, 9)
    trimesh.points.PointCloud(points/1000).export(data/"reference.ply")
    receipt(data, ["reference.ply"])
    record = {"role": "train", "source_split": "train", "reference": "reference.ply", "object_id": "train_fixture"}
    folder = tmp_path/"prior"
    build_prior(data, [record], folder, template_samples=500)
    return folder, mesh, points


def test_template_training_provenance_and_integrity(tmp_path):
    folder, _, points = make_prior(tmp_path)
    prior = load_prior(folder)
    completer = TemplateCompleter(folder, prior)
    result, parameters = completer.complete(points[points[:, 2] > 10][:200])
    assert mesh_quality(result)["volume_valid"]
    assert parameters["training_template_id"] == "train_fixture"
    assert .5 <= parameters["isotropic_scale"] <= 2
    with (folder/prior["templates"][0]["samples"]).open("ab") as f:
        f.write(b"corrupt")
    with pytest.raises(ValueError, match="template changed"):
        load_prior(folder)


def test_point_cloud_reference_metrics_have_no_volume_target(tmp_path):
    _, mesh, reference = make_prior(tmp_path)
    cfg = {"surface_samples": 1000, "max_fidelity_points": 40, "thresholds_mm": [2., 5., 10.]}
    result = study.evaluate_cloud(mesh, reference, reference[:100], reference[:70], cfg, 7)
    assert result["chamfer_l1_mm"] < 2 and result["fscore_5mm"] > .99
    assert result["reference_mesh_volume_ml"] is None
    assert result["physical_target_volume_ml"] is None
    assert result["raw_metric_points"] == result["used_metric_points"] == 40


def test_seal_rejects_source_mutation(tmp_path, monkeypatch):
    seal = tmp_path/"seal.json"
    write_json(seal, {"fingerprint": {"source": "original"}})
    monkeypatch.setattr(study, "SEAL", seal)
    monkeypatch.setattr(study, "fingerprint", lambda: {"source": "changed"})
    with pytest.raises(ValueError, match="Sealed source"):
        study.verify_seal()


def test_runner_exports_all_predictions_before_reference_and_never_uses_reference_for_fit(tmp_path, monkeypatch):
    folder, _, points = make_prior(tmp_path)
    manifest = json.loads(Path("data/bonn_real_v1_manifest.json").read_text())
    dev = next(o for o in manifest["objects"] if o["role"] == "development")
    train_record = manifest["objects"][0].copy(); train_record["object_id"] = "train_fixture"
    prefix = "shape_completion_challenge/train/train_fixture/"
    train_record["reference"] = prefix+"gt/pcd/fruit.ply"
    train_record["members"] = [{"name": train_record["reference"]}]
    holdout = next(o for o in manifest["objects"] if o["role"] == "holdout")
    manifest["objects"] = [train_record, dev, holdout]
    manifest["roles"] = {"train": ["train_fixture"], "development": [dev["object_id"]], "holdout": [holdout["object_id"]]}
    cfg = json.loads(Path("configs/bonn_real_v1.json").read_text())
    cfg.update(surface_samples=300, max_fidelity_points=20, max_fit_points=200, template_iterations=2)
    config_path, manifest_path = tmp_path/"config.json", tmp_path/"manifest.json"
    write_json(config_path, cfg); write_json(manifest_path, manifest)
    monkeypatch.setattr(study, "CONFIG", config_path); monkeypatch.setattr(study, "MANIFEST", manifest_path)
    monkeypatch.setattr(study, "verify_seal", lambda: "fixture")
    monkeypatch.setattr(study, "viewer", lambda *args: None)
    visible = points[points[:, 2] > 5]
    monkeypatch.setattr(study, "load_observations", lambda *args: ({"raw_valid": visible, "depth_component": visible}, {}))
    hashes = []
    for index, offset in enumerate([0, 100.]):
        out = tmp_path/f"run{index}"
        def reference_loader(*args):
            events = [json.loads(line) for line in (out/"events.jsonl").read_text().splitlines()]
            assert sum(e["event"] == "prediction_exported" for e in events) == 8
            return points+offset
        monkeypatch.setattr(study, "load_reference", reference_loader)
        rows = study.run(tmp_path/"unused", folder, "development", out)
        assert len(rows) == 8 and all(r["status"] == "ok" for r in rows)
        hashes.append([r["prediction_sha256"] for r in rows])
    assert hashes[0] == hashes[1]


def test_selection_prior_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "verify_seal", lambda: "fixture-seal")
    path = tmp_path/"selection.json"
    write_json(path, {"seal_sha256": "fixture-seal", "prior_hashes": {"prior.json": "wrong"}})
    prior = tmp_path/"prior"; prior.mkdir(); (prior/"prior.json").write_text("{}")
    with pytest.raises(ValueError, match="differs from development"):
        study.verify_selection(path, prior)


def test_incomplete_holdout_cannot_pass_on_successful_subset(tmp_path):
    run = tmp_path/"run"; run.mkdir()
    write_json(run/"results.json", [{"object_id": "missing", "method": m, "condition": "depth_component", "status": "failed"}
                                    for m in ["population", "ellipsoid_0.5"]])
    write_json(run/"run.json", {"split": "holdout", "complete": False, "object_ids": ["missing"]})
    write_json(run/"config.json", {"seed": 1, "bootstrap_replicates": 10})
    result = study.analyze(run, tmp_path/"analysis.json")
    assert result["full_primary_hypothesis_passed"] is False
    assert all(not c["pass"] for c in result["primary_checks"].values())
