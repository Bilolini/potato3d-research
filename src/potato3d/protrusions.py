"""Analytic genuine top features with independent volumes and evaluation masks."""
from dataclasses import dataclass
from functools import cached_property

import numpy as np
from scipy.optimize import minimize

from .development import DevelopmentShape


@dataclass(frozen=True)
class ProtrusionShape(DevelopmentShape):
    bump_amplitude_mm: float = 0.
    bump_radius_unit: float = .22
    bump_center_unit: tuple[float, float] = (.25, .20)

    def __post_init__(self):
        super().__post_init__()
        if not np.isfinite([self.bump_amplitude_mm, self.bump_radius_unit, *self.bump_center_unit]).all():
            raise ValueError("Finite bump parameters required")
        if self.bump_amplitude_mm < 0 or self.bump_radius_unit <= 0:
            raise ValueError("Nonnegative amplitude and positive bump radius required")
        if np.linalg.norm(self.bump_center_unit)+self.bump_radius_unit >= 1:
            raise ValueError("Analytic bump support must lie inside the projected disk")

    def bump_height_unit(self, u, v):
        radius2 = ((np.asarray(u)-self.bump_center_unit[0])**2+(np.asarray(v)-self.bump_center_unit[1])**2)/self.bump_radius_unit**2
        return self.bump_amplitude_mm*np.maximum(0., 1-radius2)**3

    def deform(self, unit):
        unit = np.asarray(unit)
        p = super().deform(unit)
        p[:, 2] += np.where(unit[:, 2] >= 0, self.bump_height_unit(unit[:, 0], unit[:, 1]), 0.)
        return p

    @property
    def added_volume_ml(self):
        a, b, _ = self.axes
        radius, u0 = self.bump_radius_unit, self.bump_center_unit[0]
        weight = 1-self.waist+self.waist*(u0*u0+radius*radius/10)
        return a*b*self.bump_amplitude_mm*np.pi*radius*radius/4*weight/1000

    @property
    def volume_ml(self):
        return super().volume_ml+self.added_volume_ml

    @cached_property
    def true_height_mm(self):
        if not self.bump_amplitude_mm:
            return 2*self.axes[2]
        def negative_height(uv):
            norm = np.dot(uv, uv)
            return -(self.axes[2]*(1+np.sqrt(max(0., 1-norm)))+self.bump_height_unit(*uv))
        results = [minimize(negative_height, initial, method="SLSQP", bounds=[(-1, 1), (-1, 1)],
                            constraints=[{"type": "ineq", "fun": lambda uv: 1-np.dot(uv, uv)}],
                            options={"ftol": 1e-10, "maxiter": 150}) for initial in [self.bump_center_unit, (0., 0.)]]
        if not any(r.success for r in results):
            raise ValueError("Analytic height optimization failed")
        return float(max(-r.fun for r in results if r.success))

    def feature_indices(self, points, minimum_fraction=.25):
        if self.bump_amplitude_mm == 0:
            return np.array([], dtype=int)
        local = np.asarray(points)@self.rotation
        u = local[:, 0]/self.axes[0]
        v = local[:, 1]/(self.axes[1]*(1-self.waist*(1-u*u)))
        return np.flatnonzero(self.bump_height_unit(u, v) >= minimum_fraction*self.bump_amplitude_mm)
