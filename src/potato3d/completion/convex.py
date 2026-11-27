"""Convex envelope with an explicit flat-belt closure, not a visible-cap hull."""
import numpy as np
import trimesh

from ..geometry import validate_points


def complete(points, **_):
    p = validate_points(points)
    if np.min(p[:, 2]) < 0:
        raise ValueError("Observed points below the assumed belt")
    floor = p.copy()
    floor[:, 2] = 0
    mesh = trimesh.convex.convex_hull(np.vstack([p, floor]))
    return mesh, {"assumption": "hull(observed points + their projections onto z=0); flat base and vertical sides"}
