# Height-estimation development protocol v1

Defined 2026-11-13 before running the new cases. This is a **development experiment**,
not a test-set claim or evidence of algorithmic novelty. Previous pilot/demo scores
are closed: no reruns, parameter search or threshold selection against them.

The immutable design is `configs/height_development_v1.yaml`; save its SHA256 and
exact content in the run. Use 12 fresh random geometric families, each with two
different undersides but **identical visible observations**, under six matched
conditions: clean, 2 mm Gaussian z jitter, 2% +10–20 mm z outliers, a missing patch,
and signed 3 mm belt-depth errors. This makes 24 shape objects / 12 independent
families / 144 condition instances. Use the original 2,500 observations, 10,000
surface samples and fixed numerical meshing settings. Seeds and dimensions differ
from the already scored pilot; no training or shape library is used.

Both undersides touch the same belt and have the same equator, top and footprint.
For unit-sphere vertical coordinate `w<0`, add
`c * k * w² * (1+w)` to the standard lower surface, with `k=0` or `1.8`.
This preserves the visible cap and belt contact but changes hidden curvature and
volume. The shape transform is monotonic in w for this range. The analytic volume
is `a*b*c * [2*I(1) - k*(I(2)-I(3))]`, where
`I(p)=2*pi/(p+2) * [(1-waist) + waist/(p+4)]`.
Rigid yaw and belt-coordinate offsets do not change volume. Under a signed belt
error delta, observations and reference both get z += delta while all methods
still assume belt z=0. This simulates a wrong calibration frame without aligning
predictions to the reference. Visibility partitions use the translated analytic
equator for evaluation only.

Compare the existing ellipsoid, belt-closed hull and mirror baselines with two
**standard robust-estimation ablations**, fixed before scoring:

- `symmetry_height95`: replace maximum height by the observed 95th percentile;
  retain the observed upper cap; clip any reflected lower vertices to belt z=0.
  This is a height/plane intervention with an explicit nonpenetration rule.
  It is not a pure estimator-only change when that floor constraint activates.
- `symmetry_robust95`: use the same 95th-percentile plane and clip observed cap
  z values down to that height before mirroring. Comparing these two variants
  isolates upper-cap clipping with the same height and floor convention. This
  clips genuine apex points too; clean-data bias must be reported.

Both variants use only partial points. Quantile 0.95 is fixed, not selected by
searching this experiment. No new confidence model, learned prior, uncertainty
calibration or concavity-refinement contribution is claimed.

Primary comparison: `symmetry_robust95 - symmetry` in the outlier condition, for
hidden-region unsquared Chamfer and **absolute** analytic-volume error. Require
both paired mean differences to be negative with family-bootstrap 95% intervals
below zero to call the specified hypothesis supported on this development set.
The clean observed-fidelity guardrail allows at most 0.5 mm mean degradation;
report its bootstrap interval and whether the mean passes that fixed bound.
All conditions, both underside profiles, all methods and all failures must appear.
Use the same complete paired cases for comparisons; report unavailable pairs,
never replace failed predictions with zero error. If any pairs are missing, the
complete-case differences are descriptive and do not establish hypothesis support.
Report differences before/after family averaging with 2,000 cluster-bootstrap
replicates: two hidden variants and all conditions from one family are correlated.

Record analytic clean-observation fidelity separately from fidelity to corrupted
input points: a method should not be rewarded merely for fitting known injected
outliers. Clean observations are **evaluation-only** and never enter fitting.
Also report predicted belt penetration and whether height estimation improved
under calibration errors. These are secondary diagnostics, not new primary endpoints.

Run serially on CPU; omit mass per-case visualization, but save a representative
clean/outlier comparison and a results-derived overview chart. Preserve all raw
per-case rows, generation parameters, input/prediction hashes, source hashes,
config, timing/memory boundaries and the predetermined analysis. Later adjustments
require a new protocol/version and fresh cases rather than tuning these scores.
