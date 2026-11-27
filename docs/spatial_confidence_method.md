# Selective local depth repair

The candidate addresses one measured failure: a global quantile suppresses noisy
height peaks but also lowers a reliable clean apex. It replaces that global
decision with local geometric support. This is an observation-aware candidate
built from standard robust regression and filtering; novelty is **not established**.

## Input-only confidence

For each measured point `(x_i,y_i,z_i)`, select the nearest 32 **other** points in
XY. The input coordinates are the same millimeter belt frame as the baselines.
Remove self explicitly, including distance ties from duplicate XY coordinates.
Center the neighborhood at the query XY, normalize by its maximum radius, and
construct the quadratic basis `[1,x,y,x²,xy,y²]`.

Fit neighbor heights relative to their median. Three Cauchy IRLS iterations solve
weighted least squares; a ridge of 1e-6 on non-intercept coefficients stabilizes
the numerical solve. Estimate scale using `max(1.4826*MAD(residual),0.5 mm)` and
update weights as `1/(1+(residual/(2.5*scale))²)`. Degenerate neighborhoods fall
back to the neighbor median, using the neighbor height spread for scale. Counts
of such unsupported fits are saved.

The predicted height at the query is the fitted intercept plus the median
neighbor height. Define residual `r_i=z_i-predicted_i` and threshold
`t_i=max(selected_threshold_mm,3*local_scale_i)`. A point is trusted when
`r_i<=t_i`. Only positive height spikes can be flagged; this deliberately retains
negative depressions. The score is 1 for trusted points and
`1/(1+(r_i/t_i)²)` for flagged points. It is a **heuristic support score**, not a
probability of correctness and not calibrated uncertainty.

Two absolute thresholds, 3 and 5 mm, are the complete development budget. Their
selection rule and independent confirmation split are fixed in
`docs/spatial_confidence_protocol.md`. No reference geometry, clean observations,
injected-noise labels, object height or hidden profile enters the confidence fit.

## Completion and separable interventions

The trusted maximum supplies height H. For flagged points only, replace cap z by
the local prediction clipped into `[0,H]`. All trusted XYZ points are retained
exactly. Use the existing Delaunay/mirror cap construction, horizontal plane H/2,
and lower-floor constraint. The representation retains the same height-field,
symmetry and convex-projected-domain limitations as the classical mirror baseline.

The three interventions are:

| Method | Plane height | Upper cap |
|---|---|---|
| `symmetry_spatial_height` | trusted maximum | original observations |
| `symmetry_spatial_surface` | original maximum | selective local repair |
| `symmetry_spatial` | trusted maximum | selective local repair |

The height-only intervention still requires clipping reflected vertices at the
assumed belt. The surface-only intervention deliberately keeps a potentially
wrong plane and may float above the belt; it is a diagnostic ablation. The full
method repairs only flagged heights and uses the trusted plane.

Per-case parameter JSONs retain thresholds, IRLS/ridge settings, trusted/original
height, flagged point indices, residuals, heuristic scores, repaired heights,
fallback counts and mesh parameters. Indices refer to the common fit-point
array. In this protocol 2,500 points fit under the 5,000-point cap, so their order
is also the exported partial-point order.

## What confidence does not establish

Local agreement does not prove a depth measurement is correct. A coherent error
patch can be supported by its own neighbors and remain trusted. Conversely, a
real isolated protrusion can resemble a sensor spike. This positive-only rule
does not mitigate negative depth failures. Large gaps, density changes, steep
slopes and unmodeled surface curvature can degrade local fits. Belt miscalibration
and hidden-surface ambiguity are separate problems. A successful confirmation
on smooth analytic caps therefore does not establish real-potato reliability.

Observed-fidelity evaluation includes both noisy input and uncorrupted analytic
observations. Binary detection precision/recall is descriptive only for known
injected spikes; Gaussian noise has no binary spike labels. Hidden geometry,
analytic volume and family-paired differences remain the specified confirmation
endpoints, rather than declaring the support scores to be uncertainty estimates.
