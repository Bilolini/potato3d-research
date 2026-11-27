"""Verify old evidence, prediction order and training/dev reproduction without holdout rescoring."""
import argparse
import hashlib
import json
from pathlib import Path

from potato3d.bonn import load_observations
from potato3d.fruit_completion import TemplateCompleter, ellipsoid_mesh, fit_ellipsoid, load_prior
from potato3d.fruit_study import CONFIG, MANIFEST, prior_hashes, train, verify_seal
from potato3d.geometry import subset
from potato3d.io import sha256, write_json

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/raw/bonn_real_v1"))
    parser.add_argument("--prior", type=Path, default=Path("outputs/bonn_prior_v1"))
    parser.add_argument("--development", type=Path, default=Path("outputs/bonn_development_v1"))
    parser.add_argument("--holdout", type=Path, default=Path("outputs/bonn_holdout_v1"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    verify_seal()
    args.out.mkdir(parents=True, exist_ok=False)
    old = json.loads(Path("docs/pre_bonn_run_checksums.json").read_text())
    changed = [name for name, digest in old.items() if not Path(name).exists() or sha256(name) != digest]
    if changed:
        raise ValueError(f"Historical output changed: {changed}")
    artifacts, ordering = {}, {}
    for split, folder in [("development", args.development), ("holdout", args.holdout)]:
        rows = json.loads((folder/"results.json").read_text())
        for row in rows:
            if "prediction_sha256" in row:
                path = folder/row["object_id"]/row["condition"]/(row["method"]+".ply")
                if sha256(path) != row["prediction_sha256"]:
                    raise ValueError("Prediction artifact changed")
        events = [json.loads(line) for line in (folder/"events.jsonl").read_text().splitlines()]
        ids = sorted({r["object_id"] for r in rows})
        for pid in ids:
            reference = [i for i, e in enumerate(events) if e["object_id"] == pid and e["event"] == "reference_loading"]
            attempts = [i for i, e in enumerate(events) if e["object_id"] == pid and e["event"] in {"prediction_exported", "prediction_failed"}]
            expected = sum(r["object_id"] == pid for r in rows)
            if len(reference) != 1 or len(attempts) != expected or max(attempts) >= reference[0]:
                raise ValueError("Prediction/reference ordering not verified")
        artifacts[split] = len(rows); ordering[split] = len(ids)
    train(args.data, args.out/"prior_repeat")
    prior_equal = prior_hashes(args.prior) == prior_hashes(args.out/"prior_repeat")
    if not prior_equal:
        raise ValueError("Training-prior reproduction is not bitwise identical")
    config = json.loads(CONFIG.read_text()); manifest = json.loads(MANIFEST.read_text())
    record = next(o for o in manifest["objects"] if o["role"] == "development")
    pid = record["object_id"]
    seed = config["seed"]+int(hashlib.sha256(pid.encode()).hexdigest()[:7], 16)
    observations, _ = load_observations(args.data, record, config["component_jump_mm"], config["component_minimum_points"])
    prior = load_prior(args.prior); completer = TemplateCompleter(args.prior, prior)
    rows = json.loads((args.development/"results.json").read_text())
    repeated = []
    for row in [r for r in rows if r["object_id"] == pid]:
        fit = subset(observations[row["condition"]], config["max_fit_points"], seed+3)
        method = row["method"]
        if method == "population":
            mesh = ellipsoid_mesh(prior["center_mm"], prior["radii_mm"], config["ellipsoid_subdivisions"])
        elif method == "template":
            mesh, _ = completer.complete(fit, config["template_strength"], config["template_iterations"])
        else:
            mesh, _ = fit_ellipsoid(fit, prior, float(method.split("_")[1]), config["ellipsoid_subdivisions"])
        digest = hashlib.sha256(mesh.export(file_type="ply")).hexdigest()
        if digest != row["prediction_sha256"]:
            raise ValueError(f"Development prediction reproduction differs: {pid} {row['condition']} {method}")
        repeated.append({"condition": row["condition"], "method": method, "sha256": digest})
    write_json(args.out/"verification.json", {"historical_jsons_unchanged": len(old), "artifact_hashes_verified": artifacts,
                                            "prediction_before_reference_objects": ordering, "prior_bitwise_identical": prior_equal,
                                            "development_object_repeated": pid, "development_predictions_bitwise_identical": repeated,
                                            "holdout_prediction_or_score_reruns": 0, "seal_verified": True})
    print("Verified", artifacts, "and exact training/development reproduction; holdout not rerun")
