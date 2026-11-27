# Multiscale confidence protocol v1

Reserved 2026-11-13 before implementation, generation or scoring. Previous real
demo, pilot, height and spatial runs are closed. This experiment tests whether
broader support can repair coherent sensor patches **while preserving true
protrusions**. It is synthetic confirmation only; no novelty or physical sensor
validity claim is implied.

## Families and geometric controls

Reserve six development and twelve confirmation families, with disjoint seeds
and IDs in `configs/multiscale_confidence_v1.yaml`. To avoid repeating the already
established hidden-twin experiment, each family has one hidden profile: 0 for
even family indices, 1.8 for odd ones. All feature variants and corruptions of a
family stay together. Each split is balanced by hidden profile. Confirmation has
12 independent families; each hidden-profile subgroup has six families and is
descriptive rather than a separate large-sample inference.

Each base geometry has seven smooth-cap conditions from the previous protocol
(clean, jitter, independent spikes, missing patch, signed belt errors, coherent
2% +15 mm patch), plus two **different clean geometries**, wide and narrow real
protrusions. The latter receive distinct shape-object IDs, not sensor-noise labels.
Development: 18 shape objects / 54 cases / 432 predictions. Confirmation: 36 shape
objects / 108 cases / 864 predictions. Reference meshes use subdivision 5 for all
cases; surface-sample count, observed-point count and other baseline settings stay
at 10,000 / 2,500 / the frozen baseline defaults.

For a true protrusion on the visible cap, add
`A * max(0,1-r²)^3` to height, where the unit-disk center is (0.25,0.20), A=8 mm,
and circular radius is 0.22 (wide) or 0.10 (narrow). The support is entirely inside
the projected disk and has a smooth C2 boundary. XY retains the known waist warp.
With projected area Jacobian `a*b*(1-waist+waist*u²)`, added volume is exactly
`a*b*A*pi*radius²/4 * [1-waist+waist*(u0²+radius²/10)]` in mm³.
The base hidden warp and belt contact are unchanged. True overall height is
computed from the analytic upper surface for auxiliary evaluation only.

Feature-preservation endpoints use only evaluation points whose true bump height
is at least 25% of its amplitude. Global mean error would dilute erasure of a
small protrusion; this **feature-core** distance is required. Feature masks, clean
observations, analytic volumes and true heights never enter prediction.

## Candidate and budget

Retain the previous 32-neighbor local confidence function unchanged. Add a robust
quadratic fit on an annulus, excluding the nearest inner neighbors. Two options
only: inner/outer neighbor counts 32/160 or 64/256. Other IRLS/MAD/ridge settings
match the single-scale method. This lets an exterior neighborhood test whether
an apparently consistent inner patch agrees with broader surface geometry.

Build XY-connected components of positive annular residuals above the adaptive
3 mm / 3*MAD threshold. Connectivity radius is three times the median third-other
neighbor XY distance. A component is accepted for repair only if at least two
distinct component points have an edge to an outside neighbor with a residual
drop of at least 6 mm; examine eight nearest other points, within that radius.
This tests abrupt boundaries. Ordinary local positive spikes remain repairable.
Use annular predictions for accepted broad components and local predictions for
local-only suspects. Keep trusted XYZ exactly, estimate height from their
maximum, clip repaired heights into [0,trusted height], and use the existing
mirror/floor construction. Unsupported fits are explicit and counted.

Confirmation compares all five initial baselines, the frozen single-scale
spatial method, annular rejection **without** the boundary gate, and the full
gated method. The ungated ablation tests whether broader fitting wins by deleting
genuine features. It is not an extra tuned candidate. No global q95 fallback or
geometry-dependent threshold search is allowed under this protocol.

Development selects the smaller family-mean score:
`clean hidden + patch hidden + .02*patch volume MAE + 2*wide core error + 2*narrow core error`.
Distance terms are in mm; the volume coefficient is mm/mL. Reject any prediction
failure and break ties by option order. Source/lock/protocol/design and all
development evidence must be sealed before accessing confirmation cases. There
is no tuning, repair or selection against confirmation results under this version.

## Confirmation decision

Use 2,000 paired family-bootstrap replicates. Differences are full gated method
minus baseline; all seven required upper confidence bounds are in YAML:

1. Coherent-patch hidden Chamfer improves over single-scale (<0 mm).
2. Coherent-patch absolute analytic-volume error improves over single-scale (<0 mL).
3. Coherent-patch hidden Chamfer is within 0.20 mm of q95.
4. Independent-spike hidden Chamfer is within 0.10 mm of single-scale.
5. Clean hidden Chamfer is within 0.05 mm of original symmetry.
6. Wide genuine-protrusion core fidelity is within 0.5 mm of original symmetry.
7. Narrow genuine-protrusion core fidelity is within 0.5 mm of original symmetry.

All conditions, hidden profiles, methods, ablations and failures are reported.
All pairs and families must be present to establish success. Gaussian jitter,
calibration errors, core-point flagging, runtime and volume are explicit secondary
diagnostics. A failed genuine-feature guardrail means the full hypothesis fails,
even if sensor-patch errors improve. Per-profile summaries remain necessary
because paired hidden-volume errors can hide geometry changes.

## Validity and reproducibility boundaries

Sharp observed discontinuities versus smooth bumps are a modeled distinction,
not proof of correct semantics. A real sharp protrusion can resemble a depth
artifact, and a smooth sensor bias can resemble a genuine bump. No observation-only
rule can resolve cases with identical observations and different causes. The
model still has a mirror prior, and preserving a one-sided true bump may itself
expose a hidden-symmetry error. Report these limits rather than editing references.

Unit fixtures are separate from reserved families. Check the protrusion volume
formula against an independent integration and tessellated volume, control-mask
support, trusted-point preservation, component gating, split separation and
confirmation refusal after code/evidence changes. Use fresh-process verification
and a restorable source snapshot. Snapshot prior result checksums before coding.
Only fixed-family examples are rendered; no best-case selection. Existing raw
real data, registrations, measurements and historical results stay unchanged.
