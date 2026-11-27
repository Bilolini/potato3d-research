"""Fixed-quantile classical ablations, not a novelty claim or learned confidence model."""
import numpy as np

from ..geometry import validate_points
from .symmetry import complete as mirror


HEIGHT_QUANTILE = .95


def height95(points, **_):
    p = validate_points(points)
    height = float(np.quantile(p[:, 2], HEIGHT_QUANTILE, method="linear"))
    mesh, parameters = mirror(p, height_mm=height, clip_lower_to_belt=True)
    return mesh, {**parameters, "height_estimator": "fixed quantile", "quantile": HEIGHT_QUANTILE,
                  "upper_cap_policy": "retain observations", "floor_policy": "clip reflected vertices to z=0"}


def robust95(points, **_):
    p = validate_points(points)
    height = float(np.quantile(p[:, 2], HEIGHT_QUANTILE, method="linear"))
    mesh, parameters = mirror(p, height_mm=height, cap_height_mm=height, clip_lower_to_belt=True)
    return mesh, {**parameters, "height_estimator": "fixed quantile", "quantile": HEIGHT_QUANTILE,
                  "upper_cap_policy": "clip z at estimated height", "floor_policy": "clip reflected vertices to z=0"}
