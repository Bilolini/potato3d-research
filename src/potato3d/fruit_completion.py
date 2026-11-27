"""Training-only, canonical fruit priors and classical CPU completion baselines."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.spatial import cKDTree
import trimesh

from .bonn import load_reference, verified_member
from .geometry import mesh_quality, sample_surface, validate_points
from .io import sha256, write_json


def build_prior(root, records, output, seed=527151102, template_samples=5000):
    if not records or any(o["role"] != "train" or o["source_split"] != "train" for o in records):
        raise ValueError("Fruit priors may use official training objects only")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    centers, radii, templates = [], [], []
    for i, record in enumerate(records):
        points = load_reference(root, record)
        center = (points.min(axis=0)+points.max(axis=0))/2
        radius = np.ptp(points, axis=0)/2
        hull = trimesh.points.PointCloud(points).convex_hull
        if not mesh_quality(hull)["volume_valid"]:
            raise ValueError("Invalid training convex hull")
        name = record["object_id"]+".ply"
        hull.export(output/name)
        sampled, _ = sample_surface(hull, template_samples, seed+i)
        samples_name = record["object_id"]+"_samples.npy"
        np.save(output/samples_name, sampled-center)
        centers.append(center); radii.append(radius)
        templates.append({"object_id": record["object_id"], "center_mm": center,
                          "mesh": name, "mesh_sha256": sha256(output/name),
                          "samples": samples_name, "samples_sha256": sha256(output/samples_name),
                          "reference_sha256": sha256(verified_member(root, record, "reference"))})
    prior = {"training_ids": [o["object_id"] for o in records], "templates": templates,
             "center_mm": np.median(centers, axis=0), "radii_mm": np.median(radii, axis=0),
             "training_centers_mm": centers, "training_radii_mm": radii,
             "seed": seed, "template_samples": template_samples,
             "policy": "canonical axis-aligned medians and convex training hulls; no evaluation fruit geometry"}
    write_json(output/"prior.json", prior)
    return prior


def load_prior(folder):
    folder = Path(folder)
    prior = json.loads((folder/"prior.json").read_text())
    for template in prior["templates"]:
        for key in ["mesh", "samples"]:
            if sha256(folder/template[key]) != template[key+"_sha256"]:
                raise ValueError("Training template changed")
    return prior


def ellipsoid_mesh(center, radii, subdivisions=3):
    if np.any(np.asarray(radii) <= 0):
        raise ValueError("Ellipsoid radii must be positive")
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions, radius=1.)
    mesh.vertices = mesh.vertices*np.asarray(radii)+np.asarray(center)
    return mesh


def robust_square(residual, delta=2.):
    return 2*delta**2*(np.sqrt(1+(np.asarray(residual)/delta)**2)-1)


def fit_ellipsoid(points, prior, strength, subdivisions=3):
    points = validate_points(points)
    center0, radii0 = np.array(prior["center_mm"]), np.array(prior["radii_mm"])
    radius = float(np.mean(radii0))
    def objective(x):
        center, radii = x[:3], radii0*np.exp(x[3:])
        residual = (np.linalg.norm((points-center)/radii, axis=1)-1)*radii.min()
        regularizer = np.mean(((center-center0)/radii0)**2)+np.mean(x[3:]**2)
        return float(np.mean(robust_square(residual))+strength**2*radius**2*regularizer)
    bounds = list(zip(center0-radii0, center0+radii0))+[(np.log(.5), np.log(2.))]*3
    result = minimize(objective, np.r_[center0, np.zeros(3)], method="L-BFGS-B", bounds=bounds,
                      options={"maxiter": 150, "ftol": 1e-10})
    center, radii = result.x[:3], radii0*np.exp(result.x[3:])
    return ellipsoid_mesh(center, radii, subdivisions), {
        "center_mm": center, "radii_mm": radii, "prior_strength": strength,
        "objective": float(result.fun), "optimizer_success": bool(result.success),
        "optimizer_message": str(result.message), "iterations": int(result.nit)}


class TemplateCompleter:
    """Retrieve a training convex hull with fixed rotation, robust scale/translation ICP.

    ICP is observation-to-training-template fitting, never test-reference alignment.
    """
    def __init__(self, folder, prior):
        self.prior = prior
        self.templates = []
        for item in prior["templates"]:
            points = np.load(Path(folder)/item["samples"], allow_pickle=False)
            self.templates.append((item, points, cKDTree(points), Path(folder)/item["mesh"]))

    def complete(self, points, strength=.15, iterations=15):
        points = validate_points(points)
        c0, r0 = np.asarray(self.prior["center_mm"]), np.asarray(self.prior["radii_mm"])
        radius = float(r0.mean())
        candidates = []
        for item, sample, tree, mesh_path in self.templates:
            scale, center = 1., c0.copy()
            for _ in range(iterations):
                distance, index = tree.query((points-center)/scale, workers=1)
                q = sample[index]
                weight = 1/np.sqrt(1+(distance*scale/2.)**2)
                # Weighted normal equations for [scale, tx, ty, tz].
                a = np.empty((4, 4)); b = np.empty(4)
                a[0, 0] = np.sum(weight*np.sum(q*q, axis=1))
                a[0, 1:] = np.sum(weight[:, None]*q, axis=0)
                a[1:, 0] = a[0, 1:]; a[1:, 1:] = np.eye(3)*weight.sum()
                b[0] = np.sum(weight*np.sum(q*points, axis=1))
                b[1:] = np.sum(weight[:, None]*points, axis=0)
                penalty = len(points)*strength**2*np.r_[radius**2, np.ones(3)]
                x = np.linalg.solve(a+np.diag(penalty), b+penalty*np.r_[1., c0])
                scale, center = np.clip(x[0], .5, 2.), np.clip(x[1:], c0-r0, c0+r0)
            residual = tree.query((points-center)/scale, workers=1)[0]*scale
            loss = float(np.mean(robust_square(residual))+strength**2*(radius**2*(scale-1)**2+np.sum((center-c0)**2)))
            candidates.append((loss, item["object_id"], scale, center, item, mesh_path))
        loss, pid, scale, center, item, mesh_path = min(candidates, key=lambda x: (x[0], x[1]))
        mesh = trimesh.load(mesh_path, force="mesh", process=False)
        mesh.vertices = (mesh.vertices-np.array(item["center_mm"]))*scale+center
        return mesh, {"training_template_id": pid, "isotropic_scale": float(scale), "center_mm": center,
                      "objective": loss, "prior_strength": strength, "iterations_per_template": iterations,
                      "rotation_policy": "identity in provided canonical fruit frame",
                      "candidate_objectives": {c[1]: c[0] for c in candidates}}
