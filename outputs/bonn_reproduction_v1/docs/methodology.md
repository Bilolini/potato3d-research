# Baseline protocol

## Units, frames and leakage boundaries

All internal coordinates and distances are **mm**, volume is **mL = mm³/1000**.
The demo PLY/OBJ coordinates and registration translations are in meters: their
depths are approximately 0.28–0.33 m; registration metadata explicitly names
meter-valued radii. Scale is declared rather than inferred by a loader. Nonfinite,
degenerate, implausibly scaled input and nonrigid transforms fail explicitly.

The released JSON convention is `p_sfm_m = T_rgbd_to_sfm @ p_camera_m` (homogeneous
column vectors), verified in bundled `3_pair/transform.py`. Invert this fixed
transform to put the reference in the named source frame. Scale translations to
mm along with vertices. Canonical coordinates are `(x, -y, belt_depth-z)` from
camera-mm XYZ; the rotation has determinant +1. Save both matrices in `inputs.json`.
The belt plane is z=0. For this 2023 demo, 350 mm comes from the approximate
camera placement reported in the papers, **not GT bounds**. Several reference
vertices end up below this approximate plane; that is recorded, not corrected.

Predictions see only the common partial-point subset and fixed baseline settings.
No reference-driven scale, center, shape fitting, template retrieval, ICP or test
alignment occurs. Use exactly the source frame named by each registration JSON;
other RGB-D frames do not automatically share that transform. This first dataset
has only a `demo_smoke_only` role. There is no training/validation/test claim and
no learned prior. Any future splits must assign **whole potato IDs**, and all
frames/corruptions of an ID must remain in that split. Shape priors may use only
training meshes and hyperparameters only training/validation data.

## Three explicit completion rules

All methods receive the same deterministic sample of at most 5,000 observed
points. Seed 527 and sorted sampled indices are fixed. Raw observations are kept
and used in the observed-fidelity metric, including points omitted during fitting.

1. **Ellipsoid.** Estimate horizontal yaw, xy center and two horizontal radii by
   bounded, ordinary least squares on scaled radial residuals. Its vertical
   radius and center both equal half of the highest supplied point, imposing
   belt tangency. PCA supplies yaw initialization only; it does not use a
   partial cloud's 3D covariance as a full-shape estimate. Export a subdivision-4
   icosphere transformed into the fitted ellipsoid. This is a standard parametric
   baseline, with no confidence weighting or novel objective.
2. **Convex.** Take the convex hull of the observed points **and their vertical
   projections to the belt**. This defines a full volume, but adds a flat base
   and vertical sides and can overfill rounded undersides and grooves. A hull of
   the visible cap alone would be a different, unsuitable completion rule.
3. **Symmetry.** Set the horizontal mirror plane to half the highest supplied
   point's z. Keep the upper half, retain the highest z at duplicate xy locations,
   triangulate xy with Delaunay, mirror the cap, and join its boundary edges.
   Remove projected near-collinear triangles *before* identifying boundary edges
   (twice XY area <=1e-8 mm² is numerical degeneracy, not a fitted parameter).
   Depth gaps and concave silhouettes are bridged by the cap's convex projected
   domain. This model assumes a single upper height field and symmetry; it can
   preserve observed grooves while hallucinating a wrong underside.

Mesh checks report finite coordinates, orientation, boundary/nonmanifold edges,
degenerate faces and watertightness. The runner records a failure instead of
scoring an invalid completion. Edge watertightness is not a proof of freedom
from all self-intersections. Reference meshes are never filled or repaired.

## Distances and volumes

Sample 10,000 points uniformly by triangle area on each predicted and reference
mesh with independent fixed RNG streams. The reference sample is reused across
methods. Local NumPy generators leave global RNG state unchanged. Let `P`, `R`
be these point sets; `d(x,Y)` is the nearest Euclidean point distance.

`chamfer_l1_mm = 0.5 * (mean_p d(p,R) + mean_r d(r,P))`.

This is **unsquared**, includes a factor 1/2, and has unit mm. It is a sampled
surface metric with a nonzero sampling floor even for identical surfaces. It
is not a verbatim replication of CoRe++'s Chamfer convention, whose printed
equation and unit description are inconsistent. Never directly rank our demo
scores against its published test scores.

Precision at threshold t is `mean_p [d(p,R)<=t]`; recall is
`mean_r [d(r,P)<=t]`. F-score is the harmonic mean, 0 when both are zero.
Report 2/5/10 mm thresholds as fractions in [0,1], and percentages in prose.

Observed-region fidelity is the **exact point-to-triangle** distance from all
supplied points to the prediction, summarized by mean and p95. This is different
from Chamfer's sampled nearest-point distance. There are no confidence labels
in this prototype; the metric includes sensor noise and outliers. Query-only
triangle views omit faces of area <=1e-10 mm² to avoid undefined projections;
the original mesh topology audit and volume eligibility remain unchanged.

Hidden/visible metrics are available **only for analytic height fields**. The
top-visible root is known by construction; the analytic equatorial z partitions
sampled predicted and reference surfaces at evaluation time only. Each region
gets its own bidirectional distance/F-score. Real camera visibility is perspective
and has holes: no invented per-region scores are emitted for it.

Only finite, watertight, consistently oriented meshes with positive signed volume
get a direct volume target. All released demo references fail this requirement,
so `reference_mesh_volume_ml` and direct mesh-volume errors are null. Keep four
different target types separate: direct closed-mesh volume, analytic formula,
CSV physical volume, and CSV `volume_metashape` (reported SfM volume; not recomputed
from the open mesh). Store signed, absolute and relative errors for each available
target. Physical measurement provenance must be checked further before treating
CSV values as exact displacement truth.

## Synthetic controls

One analytic object has axes (40,27,23) mm and yaw 0.35 rad. A second waisted
object uses the same axes and a 0.55 waist factor. Map a unit-sphere point `(u,v,w)`
to `(a*u, b*v*(1-k*(1-u²)), c*(1+w))`, then rotate around z. The analytic volume
is `4*pi*a*b*c/3 * (1-4*k/5)`; tests compare this independently integrated value
with triangle mesh volume. The waisted shape has a genuinely nonconvex waist.

Input points are sampled from an undeformed projected disk, warped into the
footprint, and assigned the **positive** square-root surface. Their distribution
is uniform in the undeformed disk, not uniform on the final waisted surface or
a full perspective sensor model. No reference mesh is used to generate input.
The reference is a separately tessellated analytic surface. Both shapes are
vertically symmetric: good mirror scores are expected and are not a discovery.

The pilot uses 2,500 points and matched seeds across clean, Gaussian z jitter
(SD=2 mm), 2% z outliers (+10–20 mm), and a local missing patch. No mask-corruption
claim is made; no RGB-D segmentation model is implemented. Conditions are neither
independent objects nor a held-out benchmark. No severity was tuned to improve
a proposed method.

## Aggregation, timing and reproducibility

Average frames within each potato first, then weight potatoes equally within
each condition/method. Volume RMSE averages squared errors within each potato,
then across potatoes before the square root. Failed predictions and metric-specific
counts remain in summaries. Do not compare methods over different successful
subsets without reporting missing cases. Object bootstrap intervals require at
least 10 unique IDs in the current code; five demo objects/two analytic objects
receive descriptive means and no confidence intervals.

`fit_seconds` includes completion and mesh construction. Shared loading,
subsampling, mesh validity checks, disk export, metrics and rendering are outside
that number. `evaluation_seconds` covers metric calculation. `run.json` total
includes loading/generation, preprocessing, checks, exports and visualization,
but excludes process startup/imports, installation and downloads. Peak RSS is a
process-lifetime high-water mark including imports/viewer creation, not a
per-method memory measurement. The first checkpoint ran demo and synthetic smoke
jobs concurrently, so timings are descriptive execution records, not an isolated
throughput benchmark. Use serial repeated runs before making speed claims.

`uv.lock` freezes CPU wheel versions. Each run stores config, package/platform
versions, source file SHA256s, lock checksum, transformations, input checksums,
per-frame results, aggregation and CPU memory/timing boundaries. Outputs are
immutable by default. `check_reproducibility.py` launches two fresh processes and
requires byte-identical input/prediction/reference PLY exports and identical
nontiming metrics. Cross-platform bit-for-bit numerical identity is not promised.
