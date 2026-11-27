# Bonn real-data v1: bounded laboratory-fruit experiment

Status: specified before new geometry was downloaded or scored. The source,
configuration, tests, scripts, this document, lockfile and member manifest are
hashed in `bonn_real_v1_seal.json` before training/development. Any change to those
files invalidates the run guard. Reports may be added after scoring.

## Population and reservation

`data/bonn_real_v1_manifest.json` fixes eight official-training laboratory fruit
IDs, three development IDs and twelve local holdout IDs from official public
validation. IDs are disjoint, partition seed 527151101. Previously audited val
lab15 is excluded; previously audited train lab1 is training only. No holdout
geometry or method scores have been inspected when reserving IDs. First
lexicographic available mask frame is fixed for each fruit, without quality or
reference inspection. There is one frame per object. Train references are the
only source of population shape priors and candidate templates.

An earlier metadata-only reservation included greenhouse fruit. Archive sizes
showed those dense references would raise the subset to about 596 MB. Before
geometry access, the reservation was replaced by this lab-only protocol (55 MB
of compressed members). `bonn_preflight_reservation.json` retains that decision.
This is not the official hidden test and cannot establish greenhouse, potato,
cross-species or broad deployment generalization. Official training/validation
labels do not guarantee cultivar/session independence. No data license is inferred
from the toolkit's software license. Raw data stays ignored and is not redistributed;
no account, agreement, benchmark submission or large archive download is made.

## Adapter and input conditions

Use source depth in meters, column-major intrinsic matrix and the supplied
camera-to-canonical-fruit pose, following the official loader. Transform camera
XYZ in meters, then multiply all coordinates by 1000 for scoring in mm. Do not
fit a belt plane, pose, alignment, rotation or scale using an evaluation reference.
No complete test fruit can become a template. RGB is retrieved for provenance
and inspection; the classical methods do not use appearance.

Both prespecified conditions are scored and reported:

- `raw_valid`: positive mask, finite depth, strictly 0 < depth < 1 meter.
- `depth_component`: largest 4-neighbor component among valid pixels, retaining
  an edge only when the absolute depth jump is <=10 mm. Ties favor the component
  whose first pixel occurs first in row-major order. Require >=100 pixels.

The filter may delete genuine disconnected parts. It is a fixed segmentation
heuristic, not a sensor-error ground truth. Report retention and fidelity to both
raw and used observations. A loading failure remains in the planned denominator.

## Training prior and classical methods

For each training reference, compute canonical axis-aligned bounding-box center
and half extents. Their coordinatewise medians define population center c0 and
radii r0. No PCA or evaluation-time reference normalization is used. Training
convex hulls are closed candidate meshes; sample 5,000 surface points each with
fixed local seeds. Serialize every template, sampled cloud, training ID and hash.

Every input/method receives the same deterministic subset of <=2,500 fit points
for that fruit and condition. The population ellipsoid ignores observations.

1. **Population ellipsoid:** fixed c0/r0, icosphere subdivision 3.
2. **Regularized partial ellipsoid:** optimize three center coordinates and three
   log radius ratios to r0. Surface residual is `(norm((p-c)/r)-1)*min(r)`.
   Data loss is mean pseudo-Huber square with delta 2 mm. Prior penalty is
   lambda^2 * mean(r0)^2 * [mean(((c-c0)/r0)^2) + mean(log(r/r0)^2)].
   Center bounds c0 +/- r0; radius bounds 0.5*r0 to 2*r0. L-BFGS-B, <=150
   iterations, ftol 1e-10. Record convergence; valid finite bound-constrained
   meshes remain scored even if the solver reports nonconvergence.
3. **Training-template completion:** compare all eight training convex hulls,
   identity rotation, isotropic scale [0.5,2] and translation c0 +/- r0.
   Fifteen iterations of observation-to-template nearest-neighbor fitting use
   IRLS weights `1/sqrt(1+(distance/2mm)^2)`. A fixed lambda 0.15 penalizes scale
   and translation: lambda^2*[mean(r0)^2*(s-1)^2 + sum((c-c0)^2)]. The linear
   update uses this ridge penalty times the number of input points, with clipping
   after the solve. Select by the final mean pseudo-Huber data loss plus this
   penalty; exact ties favor lexical training ID. No reference is available to
   candidate retrieval. Templates are convex and cannot recover concavities.

Only ellipsoid lambda is selected: **0.15 or 0.5**, exactly two options. Score all
four methods on all three development objects in both conditions (24 planned
predictions). Choose minimum equal-object mean unsquared Chamfer, equally
averaging both conditions; exact ties favor 0.5. Selection requires complete
development rows with valid metrics. Freeze source seal, prior hashes, selection
rule, scores and development-result hash before retrieving holdout assets.

Holdout has population, selected ellipsoid, template in both conditions:
**12 objects x 3 methods x 2 conditions = 72 planned predictions**. No retuning,
new filtering, additional view selection or extra candidates on these objects.
Prediction exports for each fruit finish before its reference geometry is loaded;
the event log records this order. Test reference hashes are checked only on load.

## Metrics and decision

All native reference laser points are used, without triangulation, reference
resampling or filling. Predictions have 10,000 area-uniform surface samples with
an object seed shared across methods/conditions. Report native-density-weighted,
unsquared symmetric Chamfer `0.5*(mean(pred->ref)+mean(ref->pred))` in mm;
precision, recall and harmonic F-score at inclusive 2, 5, 10 mm thresholds; and
symmetric p95. Native density is a limitation and these are not a replica of the
official benchmark metrics or directly comparable published scores.

Raw/used observation fidelity is exact point-to-triangle mean/p95 on fixed subsets
of <=1,500 each. Subset selection is common across methods for that input. Report
counts. Geometry validity, fit seconds, optimizer status, template ID and filter
retention are mandatory. Prediction volume is descriptive only: reference/physical
volume targets and errors are null. No visible/hidden region claim is available.

Two co-primary paired checks compare selected ellipsoid minus population on
`depth_component`, using all twelve objects. For mean Chamfer, the paired 95%
percentile object-bootstrap upper bound must be <0. For F5 the lower bound must
be >0. Use 10,000 bootstrap replicates, seed config seed+101. Both must pass to
accept the full primary hypothesis. This is an exploratory local transfer study,
not a powered clinical-style claim. Failures/incomplete objects make primary
inference fail rather than silently reducing the cohort. Other methods/conditions
and outliers are descriptive, retained regardless of sign. No frame bootstrap.

## Reproduction and limits

CPU only. Exact settings in `configs/bonn_real_v1.json`, dependencies in `uv.lock`.
Download only pinned ranges with exact Content-Range, ZIP CRC/size and SHA receipts;
200 MB hard cap, no complete archive fallback. Holdout retrieval and execution
require the sealed development selection. New output directories only.

Tests use generated fixtures for transforms/units, input-only loading, point-cloud
metrics, filtering, leakage guards and reference-load ordering. Restore a source
snapshot and run those tests after the study. Recompute training/development
geometry for reproducibility without retuning or rerunning holdout evaluations.
Verify earlier output JSON hashes unchanged. Archive source/protocol/compact
evidence, excluding raw data, and retain rejected synthetic hypotheses.
