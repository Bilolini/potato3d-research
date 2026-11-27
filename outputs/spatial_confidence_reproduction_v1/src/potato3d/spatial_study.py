"""Reserved family splits and a source-locked development/confirmation gate."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import yaml

from .completion import METHODS
from .completion.confidence import complete as spatial
from .development import DevelopmentShape
from .io import sha256, write_json
from .pipeline import Sample, environment, load_config


PROTOCOL_PATH = Path("configs/spatial_confidence_v1.yaml")
SEAL_PATH = Path("docs/spatial_confidence_v1_seal.json")
DESIGN_PATH = Path("docs/spatial_confidence_protocol.md")


def load_spatial_protocol(path=PROTOCOL_PATH):
    path = Path(path)
    protocol = yaml.safe_load(path.read_text())
    seal = json.loads(SEAL_PATH.read_text())
    if sha256(path) != seal["protocol_sha256"] or sha256(DESIGN_PATH) != seal["design_sha256"]:
        raise ValueError("Spatial protocol/design differs from its pre-implementation seal")
    if sha256(Path(protocol["baseline_config"])) != seal["baseline_config_sha256"]:
        raise ValueError("Baseline configuration changed after protocol reservation")
    splits = protocol["splits"]
    for key in ["shape_seed", "observation_seed", "evaluation_seed"]:
        if splits["development"][key] == splits["confirmation"][key]:
            raise ValueError("Development and confirmation seeds overlap")
    return protocol


def candidate_method(index):
    return f"symmetry_spatial_option_{index}"


def candidate_parameters(option):
    return {k: v for k, v in option.items() if k != "name"}


def study_config(protocol, split, selection=None):
    config = load_config(Path(protocol["baseline_config"]))
    config.update(seed=protocol["splits"][split]["evaluation_seed"], split=split,
                  spatial_protocol=protocol, protocol_sha256=sha256(PROTOCOL_PATH),
                  design_sha256=sha256(DESIGN_PATH), bootstrap_replicates=protocol["bootstrap_replicates"])
    if split == "development":
        methods = list(protocol["baseline_methods"])
        options = {}
        for index, option in enumerate(protocol["candidate_options"]):
            method = candidate_method(index)
            METHODS[method] = spatial
            methods.append(method)
            options[method] = candidate_parameters(option)
        config.update(methods=methods, method_options=options)
    elif split == "confirmation":
        if selection is None:
            raise ValueError("Confirmation requires a validated selection seal")
        config.update(methods=protocol["confirmation_methods"], selected_candidate=selection["selected_option"],
                      selection_evidence=selection,
                      method_options={method: selection["selected_parameters"] for method in
                                      ["symmetry_spatial", "symmetry_spatial_height", "symmetry_spatial_surface"]})
    else:
        raise ValueError("Unknown study split")
    return config


def spatial_samples(protocol, config, confirmation_authorized=False):
    split = config["split"]
    if split == "confirmation" and not confirmation_authorized:
        raise ValueError("Confirmation generation is closed until selection validation")
    settings = protocol["splits"][split]
    generator = np.random.default_rng(settings["shape_seed"])
    for family in range(settings["families"]):
        axes = tuple(generator.uniform(lo, hi) for lo, hi in protocol["axes_ranges_mm"])
        waist = generator.uniform(*protocol["waist_range"])
        yaw = generator.uniform(*protocol["yaw_range_rad"])
        seed = settings["observation_seed"]+family
        for warp in protocol["underside_warps"]:
            family_id = f"spatial_{split}_family_{family:02d}"
            pid = f"{family_id}_warp_{warp:g}"
            for condition in protocol["conditions"]:
                offset = 3. if condition == "belt_plus3mm" else -3. if condition == "belt_minus3mm" else 0.
                shape = DevelopmentShape(axes=axes, waist=waist, yaw=yaw,
                                         underside_warp=warp, belt_offset_mm=offset)
                corruption = ({"noise_mm": 2.} if condition == "depth_jitter_2mm" else
                              {"outlier_fraction": .02} if condition == "outliers_2percent" else
                              {"gap": True} if condition == "depth_gap" else {})
                points = shape.partial(config["synthetic_points"], seed, **corruption)
                clean = shape.partial(config["synthetic_points"], seed, gap=condition == "depth_gap")
                if condition == "correlated_outlier_patch":
                    center = np.array([.25*axes[0], .20*axes[1], 0.])@shape.rotation.T
                    distance = np.linalg.norm(points[:, :2]-center[:2], axis=1)
                    indices = np.argsort(distance, kind="stable")[:int(.02*len(points))]
                    points[indices, 2] += 15.
                    corruption = {"coherent_xy_fraction": .02, "z_shift_mm": 15., "center_normalized_xy": [.25, .20]}
                injected = np.flatnonzero(points[:, 2]-clean[:, 2] > 9.).tolist() if condition in ("outliers_2percent", "correlated_outlier_patch") else []
                metadata = {"split": f"synthetic_{split}_only", "protocol_id": protocol["protocol_id"],
                            "family_id": family_id, "underside_warp": warp, "axes_mm": axes,
                            "waist": waist, "yaw_rad": yaw, "observation_seed": seed, "corruption": corruption,
                            "true_belt_in_input_frame_mm": offset, "true_object_height_mm": 2*axes[2],
                            "injected_spike_indices_eval_only": injected,
                            "clean_observations_role": "evaluation only; not supplied to completion",
                            "visibility": "orthographic top root; identical within each hidden-profile pair"}
                yield Sample(pid, "000", condition, points, shape.mesh(), metadata, shape, clean)


def selection_scores(rows, inputs, protocol):
    meta = {(m["object_id"], m["condition"]): m for m in inputs}
    def mean(method, condition, metric):
        families = {}
        for row in rows:
            if row["method"] == method and row["condition"] == condition:
                families.setdefault(meta[(row["object_id"], condition)]["family_id"], []).append(row[metric])
        if len(families) != protocol["splits"]["development"]["families"]:
            raise ValueError("Missing development families")
        return float(np.mean([np.mean(v) for v in families.values()]))
    scores = []
    for index, option in enumerate(protocol["candidate_options"]):
        method = candidate_method(index)
        clean = mean(method, "clean", "hidden_chamfer_l1_mm")
        outlier = mean(method, "outliers_2percent", "hidden_chamfer_l1_mm")
        volume = mean(method, "outliers_2percent", "volume_absolute_error_analytic_ml")
        scores.append({"option_index": index, "option_name": option["name"],
                       "clean_hidden_mm": clean, "outlier_hidden_mm": outlier,
                       "outlier_volume_mae_ml": volume, "selection_score": clean+outlier+.02*volume})
    return scores


def select_candidate(development_path, output):
    path, output = Path(development_path), Path(output)
    if output.exists():
        raise FileExistsError("Selection seal already exists")
    protocol = load_spatial_protocol()
    config = json.loads((path/"config.json").read_text())
    if config.get("split") != "development" or config["protocol_sha256"] != sha256(PROTOCOL_PATH):
        raise ValueError("Selection requires the matching development run")
    finished = json.loads((path/"run.json").read_text())
    expected = protocol["splits"]["development"]["families"]*len(protocol["underside_warps"])*len(protocol["conditions"])*len(config["methods"])
    rows = json.loads((path/"results.json").read_text())
    inputs = json.loads((path/"inputs.json").read_text())
    if len(rows) != expected or finished["failed_predictions"] != 0 or any(r["status"] != "ok" for r in rows):
        raise ValueError("Development predictions incomplete or failed; confirmation remains closed")
    saved_environment = json.loads((path/"environment.json").read_text())
    current = environment()
    if saved_environment["source_sha256"] != current["source_sha256"] or saved_environment["lock_sha256"] != current["lock_sha256"]:
        raise ValueError("Code/lock changed after development scoring; reserve another protocol")
    scores = selection_scores(rows, inputs, protocol)
    selected = min(scores, key=lambda s: (s["selection_score"], s["option_index"]))
    option = protocol["candidate_options"][selected["option_index"]]
    seal = {"protocol_id": protocol["protocol_id"], "role": "selected on development only; frozen before confirmation generation",
            "protocol_sha256": sha256(PROTOCOL_PATH), "design_sha256": sha256(DESIGN_PATH),
            "baseline_config_sha256": sha256(Path(protocol["baseline_config"])),
            "development_path": str(path.resolve()), "development_evidence_sha256":
                {name: sha256(path/name) for name in ["results.json", "inputs.json", "config.json", "run.json", "environment.json"]},
            "source_sha256": current["source_sha256"], "lock_sha256": current["lock_sha256"],
            "selected_option": option["name"], "selected_parameters": candidate_parameters(option),
            "selection_scores": scores}
    write_json(output, seal)
    return seal


def validate_selection(selection_path):
    protocol = load_spatial_protocol()
    selection = json.loads(Path(selection_path).read_text())
    if selection["protocol_sha256"] != sha256(PROTOCOL_PATH) or selection["design_sha256"] != sha256(DESIGN_PATH):
        raise ValueError("Selection belongs to a different protocol/design")
    current = environment()
    if selection["source_sha256"] != current["source_sha256"] or selection["lock_sha256"] != current["lock_sha256"]:
        raise ValueError("Source/lock differs from the frozen selection; confirmation denied")
    for name, digest in selection["development_evidence_sha256"].items():
        if sha256(Path(selection["development_path"])/name) != digest:
            raise ValueError("Development evidence changed after selection")
    option = next((o for o in protocol["candidate_options"] if o["name"] == selection["selected_option"]), None)
    if option is None or candidate_parameters(option) != selection["selected_parameters"]:
        raise ValueError("Selected parameters are outside the fixed candidate budget")
    path = Path(selection["development_path"])
    scores = selection_scores(json.loads((path/"results.json").read_text()), json.loads((path/"inputs.json").read_text()), protocol)
    winner = min(scores, key=lambda s: (s["selection_score"], s["option_index"]))
    if scores != selection["selection_scores"] or winner["option_name"] != selection["selected_option"]:
        raise ValueError("Selection does not match the fixed development selection rule")
    return selection
