"""Classical priors only: no reference mesh enters any prediction function."""
from .ellipsoid import complete as ellipsoid
from .convex import complete as convex
from .symmetry import complete as symmetry
from .robust import height95, robust95
from .confidence import complete as spatial, height_only as spatial_height, surface_only as spatial_surface
from .multiscale import complete as multiscale, annular_only

METHODS = {"ellipsoid": ellipsoid, "convex": convex, "symmetry": symmetry,
           "symmetry_height95": height95, "symmetry_robust95": robust95,
           "symmetry_spatial": spatial, "symmetry_spatial_height": spatial_height,
           "symmetry_spatial_surface": spatial_surface,
           "symmetry_annular": annular_only, "symmetry_multiscale": multiscale}
