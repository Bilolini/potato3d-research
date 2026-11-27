# Spatial confidence protocol v1

Reserved 2026-11-13 before implementation, generation or scoring. Prior demo,
pilot and height-development scores are closed. This is a synthetic development
stage followed by a fresh **confirmation split**, not real-potato validation or
a novelty claim. No external dataset acquisition or training is needed.

## Fixed design

`configs/spatial_confidence_v1.yaml` defines disjoint seeds and family IDs for
six development and twelve confirmation families. Each family has two different
undersides with identical visible observations, as in the prior analytic
generator. No family, observation seed, candidate output or reference is shared
between splits or previous studies. Keep all hidden variants and corruptions of
a family together. Analytic volume, visibility and clean points are evaluation
only; they never enter the confidence function or completion.

Seven matched conditions: clean, 2 mm z jitter, 2% independent +10–20 mm positive
outliers, the existing missing patch, signed 3 mm belt-depth errors, and a
coherent 2% bad-depth patch. For that last diagnostic, choose the 2% nearest XY
observations to a fixed normalized location (0.25*a, 0.20*b), rotate that location
by object yaw, and add 15 mm z to the patch. The coherent patch is a secondary
stress test, not a new primary endpoint or a selection target.

Retain baseline settings: 2,500 input points, <=5,000 common fit points, 10,000
area samples, unsquared millimeter distances, separate analytic-volume errors.
Development has 84 cases × 7 methods = 588 predictions (five existing baselines
plus two candidate options). Confirmation has 168 cases × 8 methods = 1,344
predictions. Methods run serially on the CPU; large batches omit visualization.

## Candidate and bounded development budget

For each observation, query 32 nearest other XY points. Fit a local quadratic
height field in centered/radius-normalized XY with a small numerical ridge and
three robust IRLS steps. Exclude the query point from its own fit. Estimate
neighbor residual scale by MAD, with a fixed 0.5 mm floor. Flag a point only if
its **positive** residual exceeds `max(threshold_mm, 3*local_scale)`; this
one-sided decision avoids treating a measured depression as a positive spike.
Preserve trusted XYZ observations exactly. This is a robust local regression
control, not a learned probability or a calibrated uncertainty estimate.

Two development options only: threshold 3 or 5 mm, all other settings fixed.
The full candidate takes height from the maximum trusted z and replaces flagged
cap z values by local predictions, limited above by trusted height and below by
the assumed belt. It mirrors the corrected cap with the same lower nonpenetration
constraint as q95. Unsupported neighborhoods fall back explicitly to a local
median and are counted. Fail explicitly if too few trusted points remain.

Select the option minimizing: clean mean hidden Chamfer + independent-outlier
mean hidden Chamfer + 0.02 × independent-outlier mean analytic-volume MAE.
The volume coefficient has units mm/mL. Average paired hidden variants within
families first. Reject any option with a development prediction failure. Break
exact ties by option order. No other option search is allowed under v1.

## Frozen confirmation and ablations

Before generating confirmation cases, save a selection seal containing the
development results/input/config hashes, selected parameters, protocol/design
hashes, exact source file hashes and lock checksum. The confirmation command
must reject changed code/config/development evidence and reserve its output
path **before** accessing confirmation references. Do not inspect confirmation
objects while selecting parameters. If all development options fail, report that
outcome without opening confirmation data. No repair/tuning after confirmation
scores under the same protocol; reserve a new protocol if needed.

Compare all five prior baselines with the selected full spatial method and:

- `symmetry_spatial_height`: trusted height, original cap, reflected lower-floor
  constraint. Isolates height/floor intervention without upper-cap repair.
- `symmetry_spatial_surface`: repaired cap, original maximum-height plane,
  reflected lower-floor constraint. Isolates cap repair while retaining the
  original potentially wrong plane. This diagnostic can float above the belt.

The full candidate uses both trusted height and repaired cap. Report threshold,
flagged counts, fallback counts, confidence residual diagnostics, clipping and
runtime per case, along with all baseline results and failures.

Confirmation succeeds only if **all five** predefined paired criteria pass,
with 2,000 family-bootstrap replicates over twelve independent families:

1. Clean hidden Chamfer improves over `symmetry_robust95` (95% upper difference <0).
2. Independent-outlier hidden Chamfer improves over original symmetry (upper <0).
3. Independent-outlier hidden Chamfer is no more than 0.10 mm worse than q95
   (upper difference <=0.10 mm).
4. Independent-outlier analytic-volume absolute error is no more than 1 mL worse
   than q95 (upper difference <=1 mL).
5. Clean uncorrupted-observation fidelity is no more than 0.05 mm worse than
   original symmetry (upper difference <=0.05 mm).

Differences are candidate minus baseline; all endpoints are errors. No missing
shape pairs/families may establish success. All conditions, methods, both hidden
profiles, per-family paired differences and failures must be reported, including
coherent-patch and calibration failures. Per-profile summaries must accompany
combined volume errors because hidden ambiguity can flatten the combined MAE.
Keep observed-noisy fidelity separate from clean-observation fidelity.

Confirmation is out of sample **within this fixed analytic distribution**.
Bootstraps do not establish physical sensor realism or external validity. Original
real-data calibration/measurement blockers remain. Check identical input and
prediction pairs across hidden variants; this candidate cannot identify an
underside from information absent in its observations.

## Reproducibility

Seal this YAML, this design and baseline config before implementation. Snapshot
checksums of previous run records and verify they are unchanged at completion.
Unit tests use separate fixtures, with local depth corruption/clean-apex checks,
rigid XY equivariance, finite and degenerate-neighborhood handling, floor/mesh
validity, split separation and confirmation gating. A fresh-process validation
fixture checks deterministic geometry/parameters/metrics without rerunning scored
development or confirmation cases. Save fixed-family clean/outlier/coherent-patch
views and results-derived scientific plots only after scoring.
