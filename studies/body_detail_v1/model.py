"""Synthetic top-view study. Prediction functions take observed XYZ only."""
from dataclasses import dataclass
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull, Delaunay, cKDTree
from matplotlib.tri import LinearTriInterpolator, Triangulation
import trimesh

from potato3d.completion.robust import robust95
from potato3d.completion.symmetry import complete as mirror


@dataclass
class Family:
    axes: np.ndarray
    exponent: float
    warp: np.ndarray
    rotation: np.ndarray
    amplitude: float
    radius: float
    direction: np.ndarray
    uv: np.ndarray
    noise: np.ndarray

    @classmethod
    def draw(cls, seed):
        rng = np.random.default_rng(seed)
        axes = rng.uniform([34, 23, 19], [53, 32, 31])
        exponent = rng.uniform(1.65, 2.55)
        warp = rng.uniform(-0.20, 0.20, 4)
        yaw, angle = rng.uniform(0, 2*np.pi, 2)
        rotation = np.array([[np.cos(yaw), -np.sin(yaw)], [np.sin(yaw), np.cos(yaw)]])
        amplitude, width = rng.uniform(5, 8), rng.uniform(.15, .195)
        az = rng.uniform(0, 2*np.pi, 2600)
        radius = .995*np.sqrt(rng.random(len(az)))
        rim = np.arange(128)*2*np.pi/128
        uv = np.vstack([radius[:, None]*np.column_stack([np.cos(az), np.sin(az)]),
                        np.column_stack([np.cos(rim), np.sin(rim)])])
        return cls(axes, exponent, warp, rotation, amplitude, width,
                   np.array([np.cos(angle), np.sin(angle)]), uv, rng.normal(0, .18, len(uv)))

    def xy(self, uv):
        return (uv*self.axes[:2]) @ self.rotation.T

    def surfaces(self, uv):
        r = np.linalg.norm(uv, axis=1).clip(0, 1)
        c = self.axes[2]
        half = c*np.maximum(0, 1-r**self.exponent)**(1/self.exponent)
        u, v = uv.T
        # Smooth different upper/lower profiles. Both center bottom and rim are unchanged.
        top = c+half*(1+(self.warp[0]*u+self.warp[1]*v)*(1-r*r))
        lower = (c-half)*(1+(self.warp[2]*u+self.warp[3]*v)*(1-r*r))
        return top, lower

    def feature(self, uv, center, sign):
        squared = np.sum((uv-center)**2, axis=1)/self.radius**2
        return sign*self.amplitude*np.maximum(0, 1-squared)**3


def stitched_mesh(xy, upper, lower, tri):
    n = len(xy)
    if np.any(upper <= lower):
        raise ValueError("Upper and lower surfaces intersect")
    faces = tri.simplices
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    _, inverse, counts = np.unique(np.sort(edges, axis=1), axis=0, return_inverse=True, return_counts=True)
    a, b = edges[counts[inverse] == 1].T
    all_faces = np.vstack([faces, faces[:, ::-1]+n, np.column_stack([b, a, a+n]),
                           np.column_stack([b, a+n, b+n])])
    return trimesh.Trimesh(vertices=np.vstack([np.column_stack([xy, upper]), np.column_stack([xy, lower])]),
                           faces=all_faces, process=False)


def fit_body(points):
    """Fit the smooth, belt-tangent body to the observed points."""
    xy, z = points[:, :2], points[:, 2]
    rim = xy[ConvexHull(xy).vertices]
    center = rim.mean(axis=0)
    eig, basis = np.linalg.eigh(2*np.cov((rim-center).T, bias=True))
    radii = np.sqrt(eig)*1.002
    radius = np.linalg.norm(((xy-center) @ basis)/radii, axis=1)
    radius = np.minimum(radius, .99999)

    def half_height(params):
        c, exponent = params
        return c*np.maximum(0, 1-radius**exponent)**(1/exponent)

    def residual(params):
        return params[0]+half_height(params)-z

    fit = least_squares(residual, [np.median(z)*.6, 2], bounds=([5, 1.25], [65, 4]),
                        loss="soft_l1", f_scale=.65)
    if not fit.success:
        raise ValueError(fit.message)
    c, exponent = fit.x
    return {"center_xy_mm": center.tolist(), "radii_xy_mm": radii.tolist(),
            "rotation_basis": basis.tolist(), "vertical_radius_mm": c, "exponent": exponent}


def body_surfaces(xy, pars):
    local = ((xy - pars["center_xy_mm"]) @ pars["rotation_basis"]) / pars["radii_xy_mm"]
    radius = np.minimum(np.linalg.norm(local, axis=1), .99999)
    c, exponent = pars["vertical_radius_mm"], pars["exponent"]
    half = c*np.maximum(0, 1-radius**exponent)**(1/exponent)
    return c+half, c-half, half


def body_models(points):
    xy, z = points[:, :2], points[:, 2]
    pars = fit_body(points)
    top, bottom, half = body_surfaces(xy, pars)
    neighbors = cKDTree(xy).query(xy, k=7)[1]
    detail = np.median((z-top)[neighbors], axis=1).clip(-.90*half, .90*half)
    tri = Delaunay(xy)
    for name, upper, lower in [
        ("body", top, bottom), ("visible_detail", top+detail, bottom),
        ("reflected_detail", top+detail, np.maximum(0, bottom-detail))]:
        yield name, stitched_mesh(xy, upper, lower, tri), pars


def predictions(points, original_scan_max):
    yield "mirror", *mirror(points)
    yield "fixed_height_diagnostic", *mirror(points, height_mm=original_scan_max)
    yield "clipped_q95", *robust95(points)
    yield from body_models(points)


def ray_heights(mesh, xy):
    """Barycentric intersections on projected upper/lower mesh faces. Ignore vertical walls."""
    if not mesh.is_watertight or not mesh.is_winding_consistent or not mesh.is_volume:
        raise ValueError("Invalid predicted solid")
    hits = []
    for side in (1, -1):
        selected = mesh.faces[side*mesh.face_normals[:, 2] > 1e-10]
        if side == -1:
            selected = selected[:, ::-1]
        used, mapped = np.unique(selected, return_inverse=True)
        vertices = mesh.vertices[used]
        tri = Triangulation(*vertices[:, :2].T, triangles=mapped.reshape(-1, 3))
        hits.append(LinearTriInterpolator(tri, vertices[:, 2])(*xy.T).filled(np.nan))
    if not np.array_equal(np.isfinite(hits[0]), np.isfinite(hits[1])):
        raise ValueError("Unpaired upper/lower ray coverage")
    return hits
