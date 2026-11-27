"""Belt-tangent ellipsoid fitted to partial points by bounded least squares."""
import numpy as np
from scipy.optimize import least_squares
import trimesh

from ..geometry import validate_points


def complete(points, subdivisions=4, **_):
    p = validate_points(points)
    height = float(p[:, 2].max())
    if height <= 1:
        raise ValueError("Object height above the assumed belt must exceed 1 mm")
    center = (p[:, :2].min(axis=0) + p[:, :2].max(axis=0)) / 2
    _, vectors = np.linalg.eigh(np.cov(p[:, :2].T))
    direction = vectors[:, -1]
    yaw = np.arctan2(direction[1], direction[0])

    def rotate(theta):
        c, s = np.cos(theta), np.sin(theta)
        return np.array([[c, -s], [s, c]])

    local = (p[:, :2] - center) @ rotate(yaw)
    ab = np.maximum(np.ptp(local, axis=0) / 2, 2.)
    # z center and z radius both height/2: belt tangency is an explicit prior.
    def residual(x):
        xy = (p[:, :2] - x[:2]) @ rotate(x[4])
        radius = np.sqrt(np.sum((xy / x[2:4])**2, axis=1) + ((p[:, 2]-height/2)/(height/2))**2)
        return (radius - 1) * min(x[2], x[3], height/2)

    initial = [*center, *ab, yaw]
    bounds = ([*(center - 2*ab.max()), 1., 1., yaw-np.pi],
              [*(center + 2*ab.max()), 4*ab.max(), 4*ab.max(), yaw+np.pi])
    fit = least_squares(residual, initial, bounds=bounds, loss="linear", max_nfev=300)
    if not fit.success:
        raise ValueError(f"Ellipsoid fit failed: {fit.message}")
    cx, cy, a, b, theta = fit.x
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions)
    mesh.vertices *= [a, b, height/2]
    mesh.vertices[:, :2] = mesh.vertices[:, :2] @ rotate(theta).T
    mesh.vertices += [cx, cy, height/2]
    return mesh, {"center_mm": [cx, cy, height/2], "axes_mm": [a, b, height/2],
                  "yaw_rad": theta, "fit_cost": fit.cost, "fit_evaluations": fit.nfev,
                  "assumption": "belt z=0; vertical extent=max observed z; horizontal ellipsoid"}
