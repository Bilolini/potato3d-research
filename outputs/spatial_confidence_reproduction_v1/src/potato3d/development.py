"""Fresh, predetermined development cases with paired ambiguous undersides."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

import numpy as np
import yaml

from .completion.robust import HEIGHT_QUANTILE
from .io import sha256
from .pipeline import Sample, load_config
from .synthetic import AnalyticShape


@dataclass(frozen=True)
class DevelopmentShape(AnalyticShape):
    underside_warp: float = 0.
    belt_offset_mm: float = 0.

    def __post_init__(self):
        if not all(np.isfinite(self.axes)) or min(self.axes) <= 0:
            raise ValueError("Positive finite axes required")
        if not 0 <= self.waist < 1 or not -.9 <= self.underside_warp <= 2.5:
            raise ValueError("Shape warp outside monotonic analytic range")

    def deform(self, unit):
        result = super().deform(unit)
        w = np.minimum(np.asarray(unit)[:, 2], 0)
        result[:, 2] += self.axes[2]*self.underside_warp*w*w*(1+w) + self.belt_offset_mm
        return result

    @property
    def volume_ml(self):
        def integral(power):
            return 2*np.pi/(power+2)*((1-self.waist)+self.waist/(power+4))
        return float(np.prod(self.axes)*(2*integral(1)-self.underside_warp*(integral(2)-integral(3)))/1000)

    def visible(self, points):
        return points[:, 2] >= self.axes[2]+self.belt_offset_mm


def load_protocol(path: Path):
    path = Path(path)
    protocol = yaml.safe_load(path.read_text())
    # Reject accidental changes to the sealed v1 design before accessing scores.
    seal = json.loads(Path("docs/height_development_v1_seal.json").read_text())
    if protocol["protocol_id"] != "height_development_v1" or sha256(path) != seal["protocol_sha256"]:
        raise ValueError("Protocol differs from the sealed v1 design; reserve a new version before changing it")
    if protocol["height_quantile"] != HEIGHT_QUANTILE:
        raise ValueError("Implementation quantile differs from the fixed protocol")
    baseline = load_config(Path(protocol["baseline_config"]))
    config = {**baseline, "seed": protocol["evaluation_seed"], "methods": protocol["methods"],
              "bootstrap_replicates": protocol["bootstrap_replicates"],
              "development_protocol": protocol, "protocol_sha256": sha256(path),
              "protocol_design_sha256": seal["design_sha256"]}
    return protocol, config


def development_samples(protocol, config):
    generator = np.random.default_rng(protocol["shape_seed"])
    for family in range(protocol["families"]):
        axes = tuple(generator.uniform(lo, hi) for lo, hi in protocol["axes_ranges_mm"])
        waist = generator.uniform(*protocol["waist_range"])
        yaw = generator.uniform(*protocol["yaw_range_rad"])
        seed = protocol["observation_seed"]+family
        for warp in protocol["underside_warps"]:
            pid = f"family_{family:02d}_warp_{warp:g}"
            for condition in protocol["conditions"]:
                offset = 3. if condition == "belt_plus3mm" else -3. if condition == "belt_minus3mm" else 0.
                shape = DevelopmentShape(axes=axes, waist=waist, yaw=yaw,
                                         underside_warp=warp, belt_offset_mm=offset)
                corruption = ({"noise_mm": 2.} if condition == "depth_jitter_2mm" else
                              {"outlier_fraction": .02} if condition == "outliers_2percent" else
                              {"gap": True} if condition == "depth_gap" else {})
                points = shape.partial(config["synthetic_points"], seed, **corruption)
                clean = shape.partial(config["synthetic_points"], seed, gap=condition == "depth_gap")
                metadata = {"split": "synthetic_development_only", "protocol_id": protocol["protocol_id"],
                            "family_id": f"family_{family:02d}", "underside_warp": warp,
                            "axes_mm": axes, "waist": waist, "yaw_rad": yaw,
                            "observation_seed": seed, "corruption": corruption,
                            "true_belt_in_input_frame_mm": offset, "true_object_height_mm": 2*axes[2],
                            "clean_observations_role": "evaluation only; not supplied to completion",
                            "visibility": "orthographic top root; identical cap within each family"}
                yield Sample(pid, "000", condition, points, shape.mesh(), metadata, shape, clean)
