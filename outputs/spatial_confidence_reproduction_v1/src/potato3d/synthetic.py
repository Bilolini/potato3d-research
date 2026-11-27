"""Analytic top-view surfaces, independent of the generated reference mesh."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import trimesh


@dataclass(frozen=True)
class AnalyticShape:
    axes: tuple[float, float, float] = (40., 27., 23.)
    waist: float = 0.
    yaw: float = 0.35

    @property
    def rotation(self) -> np.ndarray:
        c, s = np.cos(self.yaw), np.sin(self.yaw)
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])

    @property
    def volume_ml(self) -> float:
        # Shape: x=a*u; y=b*v*(1-waist*(1-u^2)); z=c*(1+w), u^2+v^2+w^2=1.
        # Integrate ellipse cross sections along x analytically.
        a, b, c = self.axes
        return 4 * np.pi * a * b * c / 3 * (1 - 4 * self.waist / 5) / 1000

    def deform(self, unit: np.ndarray) -> np.ndarray:
        p = np.asarray(unit).copy()
        p[:, 1] *= 1 - self.waist * (1 - p[:, 0] ** 2)
        p *= self.axes
        p[:, 2] += self.axes[2]
        return p @ self.rotation.T

    def mesh(self, subdivisions: int = 4) -> trimesh.Trimesh:
        m = trimesh.creation.icosphere(subdivisions=subdivisions)
        m.vertices = self.deform(m.vertices)
        return m

    def partial(self, count: int, seed: int, noise_mm: float = 0.,
                gap: bool = False, outlier_fraction: float = 0.) -> np.ndarray:
        # Uniform projected unit-disk sampling, followed by the known shape warp.
        # Only the positive (top-visible) root is used: no underside information.
        rng = np.random.default_rng(seed)
        radius = np.sqrt(rng.uniform(0, 0.995 ** 2, count))
        phi = rng.uniform(0, 2 * np.pi, count)
        u, v = radius * np.cos(phi), radius * np.sin(phi)
        w = np.sqrt(np.maximum(0, 1 - u*u - v*v))
        p = self.deform(np.column_stack([u, v, w]))
        if gap:
            local = p @ self.rotation
            p = p[~((local[:, 0] > -8) & (local[:, 0] < 8) & (local[:, 1] > 0))]
        p[:, 2] += rng.normal(0, noise_mm, len(p))
        n = int(len(p) * outlier_fraction)
        if n:
            indices = rng.choice(len(p), n, replace=False)
            p[indices, 2] += rng.uniform(10, 20, n)
        return p

    def visible(self, points: np.ndarray) -> np.ndarray:
        # Exact for these vertically symmetric height fields under a +z orthographic camera.
        return points[:, 2] >= self.axes[2]
