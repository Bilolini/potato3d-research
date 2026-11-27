"""Triangulate an upper height field and mirror it about half observed height."""
import numpy as np
from scipy.spatial import Delaunay
import trimesh

from ..geometry import validate_points


def complete(points, height_mm=None, cap_height_mm=None, clip_lower_to_belt=False, **_):
    p = validate_points(points)
    height = float(p[:, 2].max() if height_mm is None else height_mm)
    if not np.isfinite(height):
        raise ValueError("Height must be finite")
    cap_clipped = 0
    if cap_height_mm is not None:
        if not np.isfinite(cap_height_mm) or cap_height_mm <= 0:
            raise ValueError("Cap ceiling must be positive and finite")
        cap_clipped = int(np.sum(p[:, 2] > cap_height_mm))
        p = p.copy()
        p[:, 2] = np.minimum(p[:, 2], cap_height_mm)
    plane = height/2
    if plane <= 0.5:
        raise ValueError("Object height above the belt must exceed 1 mm")
    # Only an upper height field is represented. At duplicate XY take the top point.
    upper = p[p[:, 2] > plane + 1e-6]
    order = np.argsort(-upper[:, 2], kind="stable")
    upper = upper[order]
    _, keep = np.unique(upper[:, :2], axis=0, return_index=True)
    upper = upper[np.sort(keep)]
    if len(upper) < 4:
        raise ValueError("Too few upper-surface observations")
    tri = Delaunay(upper[:, :2]).simplices.copy()
    normals = np.cross(upper[tri[:, 1]]-upper[tri[:, 0]], upper[tri[:, 2]]-upper[tri[:, 0]])
    # Quantized RGB-D rows can yield numerically collinear XY triangles. Drop
    # them BEFORE computing the boundary, so the side closure follows the
    # actual cap instead of leaving holes after a post-hoc face deletion.
    valid = np.abs(normals[:, 2]) > 1e-8  # twice projected area in mm^2
    removed = int(np.sum(~valid))
    tri, normals = tri[valid], normals[valid]
    flip = normals[:, 2] < 0
    tri[flip] = tri[flip, ::-1]
    n = len(upper)
    lower = upper.copy()
    lower[:, 2] = 2*plane - lower[:, 2]
    floor_clipped = int(np.sum(lower[:, 2] < 0)) if clip_lower_to_belt else 0
    if clip_lower_to_belt:
        lower[:, 2] = np.maximum(lower[:, 2], 0)
    edges = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    _, inv, counts = np.unique(np.sort(edges, axis=1), axis=0, return_inverse=True, return_counts=True)
    boundary = edges[counts[inv] == 1]
    a, b = boundary[:, 0], boundary[:, 1]
    sides = np.concatenate([np.column_stack([b, a, a+n]), np.column_stack([b, a+n, b+n])])
    mesh = trimesh.Trimesh(vertices=np.vstack([upper, lower]),
                           faces=np.vstack([tri, tri[:, ::-1]+n, sides]), process=True)
    # Remove any numerical degeneracies after welding; validate closure in the runner.
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals()
    return mesh, {"mirror_plane_z_mm": plane, "upper_points": n,
                  "height_mm": height, "upper_cap_clipped_points": cap_clipped,
                  "lower_floor_clipped_points": floor_clipped,
                  "removed_projected_degenerate_triangles": removed,
                  "discarded_below_plane": int(np.sum(p[:, 2] <= plane + 1e-6)),
                  "assumption": "upper 2.5D Delaunay cap; mirror at supplied height/2 (default max(z)/2); close boundary walls; gaps bridged"}
