"""Fresh protrusion-control protocol and source-locked selection."""
import json
from pathlib import Path

import numpy as np
import yaml

from .completion import METHODS
from .completion.multiscale import complete as multiscale
from .io import sha256, write_json
from .pipeline import Sample, environment, load_config
from .protrusions import ProtrusionShape


PROTOCOL_PATH = Path("configs/multiscale_confidence_v1.yaml")
DESIGN_PATH = Path("docs/multiscale_confidence_protocol.md")
SEAL_PATH = Path("docs/multiscale_confidence_v1_seal.json")


def load_protocol():
    protocol = yaml.safe_load(PROTOCOL_PATH.read_text())
    seal = json.loads(SEAL_PATH.read_text())
    for path, key in [(PROTOCOL_PATH, "protocol_sha256"), (DESIGN_PATH, "design_sha256"),
                      (Path(protocol["baseline_config"]), "baseline_config_sha256")]:
        if sha256(path) != seal[key]:
            raise ValueError("Multiscale protocol/design/baseline differs from reservation")
    for key in ["shape_seed", "observation_seed", "evaluation_seed"]:
        if protocol["splits"]["development"][key] == protocol["splits"]["confirmation"][key]:
            raise ValueError("Split seeds overlap")
    return protocol


def option_parameters(protocol, option):
    return {**protocol["fixed_candidate_parameters"], **{k: v for k, v in option.items() if k != "name"}}


def option_method(index):
    return f"symmetry_multiscale_option_{index}"


def make_config(protocol, split, selection=None):
    config = load_config(Path(protocol["baseline_config"]))
    config.update(seed=protocol["splits"][split]["evaluation_seed"], split=split,
                  multiscale_protocol=protocol, protocol_sha256=sha256(PROTOCOL_PATH),
                  design_sha256=sha256(DESIGN_PATH), reference_subdivisions=protocol["reference_subdivisions"],
                  bootstrap_replicates=protocol["bootstrap_replicates"])
    options = {"symmetry_spatial": protocol["single_scale_parameters"]}
    if split == "development":
        methods = list(protocol["baseline_methods"])
        for index, option in enumerate(protocol["candidate_options"]):
            name = option_method(index)
            METHODS[name] = multiscale
            methods.append(name)
            options[name] = option_parameters(protocol, option)
    elif split == "confirmation":
        if selection is None:
            raise ValueError("Confirmation requires a validated frozen selection")
        methods = protocol["confirmation_methods"]
        options.update({m: selection["selected_parameters"] for m in ["symmetry_annular", "symmetry_multiscale"]})
        config["selection_evidence"] = selection
    else:
        raise ValueError("Unknown protocol split")
    config.update(methods=methods, method_options=options)
    return config


def samples(protocol, config, confirmation_authorized=False):
    split = config["split"]
    if split == "confirmation" and not confirmation_authorized:
        raise ValueError("Confirmation generation remains closed")
    settings = protocol["splits"][split]
    rng = np.random.default_rng(settings["shape_seed"])
    for family in range(settings["families"]):
        axes = tuple(rng.uniform(lo, hi) for lo, hi in protocol["axes_ranges_mm"])
        waist = rng.uniform(*protocol["waist_range"])
        yaw = rng.uniform(*protocol["yaw_range_rad"])
        warp = 0. if family % 2 == 0 else 1.8
        observation_seed = settings["observation_seed"]+family
        family_id = f"multiscale_{split}_family_{family:02d}"
        for condition in protocol["conditions"]:
            profile = "wide" if condition == "genuine_wide_protrusion" else "narrow" if condition == "genuine_narrow_protrusion" else "smooth"
            amplitude = protocol["protrusion_amplitude_mm"] if profile != "smooth" else 0.
            radius = protocol["protrusion_narrow_radius_unit"] if profile == "narrow" else protocol["protrusion_wide_radius_unit"]
            offset = 3. if condition == "belt_plus3mm" else -3. if condition == "belt_minus3mm" else 0.
            shape = ProtrusionShape(axes=axes, waist=waist, yaw=yaw, underside_warp=warp, belt_offset_mm=offset,
                                    bump_amplitude_mm=amplitude, bump_radius_unit=radius,
                                    bump_center_unit=tuple(protocol["protrusion_center_unit_xy"]))
            corruption = ({"noise_mm": 2.} if condition == "depth_jitter_2mm" else
                          {"outlier_fraction": .02} if condition == "outliers_2percent" else
                          {"gap": True} if condition == "depth_gap" else {})
            points = shape.partial(config["synthetic_points"], observation_seed, **corruption)
            clean = shape.partial(config["synthetic_points"], observation_seed, gap=condition == "depth_gap")
            if condition == "correlated_outlier_patch":
                center = np.array([.25*axes[0], .20*axes[1], 0.])@shape.rotation.T
                ids = np.argsort(np.linalg.norm(points[:, :2]-center[:2], axis=1), kind="stable")[:int(.02*len(points))]
                points[ids, 2] += 15
                corruption = {"coherent_xy_fraction": .02, "z_shift_mm": 15.}
            injected = np.flatnonzero(points[:, 2]-clean[:, 2] > 9.).tolist() if condition in ("outliers_2percent", "correlated_outlier_patch") else []
            feature_ids = shape.feature_indices(clean, protocol["protrusion_core_fraction_of_amplitude"]).tolist()
            metadata = {"split": f"synthetic_{split}_only", "protocol_id": protocol["protocol_id"],
                        "family_id": family_id, "geometry_profile": profile, "underside_warp": warp,
                        "axes_mm": axes, "waist": waist, "yaw_rad": yaw, "observation_seed": observation_seed,
                        "corruption": corruption, "injected_spike_indices_eval_only": injected,
                        "feature_observation_indices_eval_only": feature_ids,
                        "feature_labels_role": "evaluation only; never supplied to confidence/completion",
                        "bump_amplitude_mm": amplitude, "bump_radius_unit": radius,
                        "bump_center_unit": shape.bump_center_unit, "bump_added_volume_ml": shape.added_volume_ml,
                        "true_belt_in_input_frame_mm": offset, "true_object_height_mm": shape.true_height_mm,
                        "clean_observations_role": "evaluation only", "visibility": "orthographic positive root"}
            pid = f"{family_id}_{profile}_warp_{warp:g}"
            yield Sample(pid, "000", condition, points, shape.mesh(protocol["reference_subdivisions"]), metadata, shape, clean)


def selection_scores(rows, inputs, protocol):
    meta = {(i["object_id"], i["condition"]): i for i in inputs}
    def mean(method, condition, metric):
        family_values = {}
        for row in rows:
            if row["method"] == method and row["condition"] == condition:
                if row.get(metric) is None:
                    raise ValueError("Missing required development endpoint")
                family_values.setdefault(meta[(row["object_id"], condition)]["family_id"], []).append(row[metric])
        if len(family_values) != protocol["splits"]["development"]["families"]:
            raise ValueError("Missing development families")
        return float(np.mean([np.mean(v) for v in family_values.values()]))
    scores = []
    for index, option in enumerate(protocol["candidate_options"]):
        method = option_method(index)
        terms = {"clean_hidden_mm": mean(method, "clean", "hidden_chamfer_l1_mm"),
                 "patch_hidden_mm": mean(method, "correlated_outlier_patch", "hidden_chamfer_l1_mm"),
                 "patch_volume_mae_ml": mean(method, "correlated_outlier_patch", "volume_absolute_error_analytic_ml"),
                 "wide_core_error_mm": mean(method, "genuine_wide_protrusion", "feature_observed_to_surface_mean_mm"),
                 "narrow_core_error_mm": mean(method, "genuine_narrow_protrusion", "feature_observed_to_surface_mean_mm")}
        score = terms["clean_hidden_mm"]+terms["patch_hidden_mm"]+.02*terms["patch_volume_mae_ml"]+2*(terms["wide_core_error_mm"]+terms["narrow_core_error_mm"])
        scores.append({"option_index": index, "option_name": option["name"], **terms, "selection_score": score})
    return scores


def select_candidate(path, output):
    path, output = Path(path), Path(output)
    if output.exists():
        raise FileExistsError("Selection already exists")
    protocol = load_protocol()
    config = json.loads((path/"config.json").read_text())
    rows = json.loads((path/"results.json").read_text())
    inputs = json.loads((path/"inputs.json").read_text())
    finished = json.loads((path/"run.json").read_text())
    expected = protocol["splits"]["development"]["families"]*len(protocol["conditions"])*len(config["methods"])
    if config["split"] != "development" or config["protocol_sha256"] != sha256(PROTOCOL_PATH):
        raise ValueError("Development evidence belongs to another protocol")
    if len(rows) != expected or finished["failed_predictions"] or any(r["status"] != "ok" for r in rows):
        raise ValueError("Development failed/incomplete; confirmation remains closed")
    current = environment()
    old = json.loads((path/"environment.json").read_text())
    if current["source_sha256"] != old["source_sha256"] or current["lock_sha256"] != old["lock_sha256"]:
        raise ValueError("Code/lock changed after development; reserve a new protocol")
    scores = selection_scores(rows, inputs, protocol)
    winner = min(scores, key=lambda r: (r["selection_score"], r["option_index"]))
    option = protocol["candidate_options"][winner["option_index"]]
    selection = {"protocol_id": protocol["protocol_id"], "role": "development selection frozen before confirmation",
                 "protocol_sha256": sha256(PROTOCOL_PATH), "design_sha256": sha256(DESIGN_PATH),
                 "baseline_config_sha256": sha256(Path(protocol["baseline_config"])),
                 "development_path": str(path.resolve()), "development_evidence_sha256":
                     {name: sha256(path/name) for name in ["results.json", "inputs.json", "config.json", "run.json", "environment.json"]},
                 "source_sha256": current["source_sha256"], "lock_sha256": current["lock_sha256"],
                 "selected_option": option["name"], "selected_parameters": option_parameters(protocol, option),
                 "selection_scores": scores}
    write_json(output, selection)
    return selection


def validate_selection(path):
    protocol = load_protocol()
    selection = json.loads(Path(path).read_text())
    if selection["protocol_sha256"] != sha256(PROTOCOL_PATH) or selection["design_sha256"] != sha256(DESIGN_PATH):
        raise ValueError("Selection protocol/design mismatch")
    current = environment()
    if current["source_sha256"] != selection["source_sha256"] or current["lock_sha256"] != selection["lock_sha256"]:
        raise ValueError("Frozen source/lock changed; confirmation denied")
    for name, digest in selection["development_evidence_sha256"].items():
        if sha256(Path(selection["development_path"])/name) != digest:
            raise ValueError("Development evidence changed")
    path = Path(selection["development_path"])
    scores = selection_scores(json.loads((path/"results.json").read_text()), json.loads((path/"inputs.json").read_text()), protocol)
    winner = min(scores, key=lambda r: (r["selection_score"], r["option_index"]))
    option = protocol["candidate_options"][winner["option_index"]]
    if scores != selection["selection_scores"] or option["name"] != selection["selected_option"] or option_parameters(protocol, option) != selection["selected_parameters"]:
        raise ValueError("Selection differs from the fixed development rule")
    return selection
