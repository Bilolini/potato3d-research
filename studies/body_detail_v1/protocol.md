# Body detail propagation study v1

Prospective plan, 20 November 2026. This CPU experiment uses new synthetic families. It tests whether a local change in top-view depth propagates to an otherwise unchanged underside and whether withholding detail from the underside sacrifices true bilateral shape. Prior scored objects are closed.

## Design

Reserve six development families (seeds 527201100–105) and 24 confirmation families (527202100–123). Family is the independent unit. Use a debugging seed outside both sets. Each family has one smooth convex-footprint body with randomized metric axes, yaw, vertical profile and smooth departures from the fitted primitive. An orthographic top view and a fully sampled silhouette are supplied. The support plane is known. All cases in a family share the same sampled XY and weak depth noise.

For each of apex, flank and near silhouette, apply a compact smooth deviation with a peak magnitude of 5–8 mm and a randomized radius. Cross raised and depressed features with three interpretations: observation error on a smooth reference, genuine feature confined to the upper surface, and corresponding upper and lower features. Add one smooth control per family. This yields 19 cases per family. Keep the hidden reference above the belt when a reflected feature would go through it. Use outward flank/near-silhouette cases to examine bilateral recovery with clearance; report actual reference displacement. The three interpretations at each site and sign must have exactly the same input. Feature labels, clean geometry and clean fit height are evaluation data. Only the explicitly identified diagnostic mirror may use the last of these.

## Predictors and comparisons

Use the existing maximum-height mirror and the existing 95th-percentile mirror with cap clipping and lower floor. For diagnosis run the same maximum mirror with the height fixed to the paired original scan maximum. Fit a belt-tangent body with an elliptical footprint obtained from input XY and a robust vertical-profile fit. Give the three body variants identical fitted parameters and residual filtering: body alone, detail restored only on top (candidate), and detail restored on top and reflected below. Use a seven-neighbor median of vertical residuals. This is a constrained superquadric fit with robust loss. No settings are selected on confirmation. These baselines target the mechanism; direct implementations of feature-preserving MLS and learned models are outside this first comparison.

## Endpoints and decision

Evaluate exported-mesh geometry along fixed vertical rays through an independent uniform-area disk grid; exclude the outermost 1% of radius to avoid tangent rays. All distances below are absolute vertical differences in mm. Define the feature core where deviation reaches at least 25% of its peak. Remote rays lie at least two feature radii from its center. Score missed reference rays with 15 mm, report coverage, and report paired coverage flips. For remote motion score 15 mm on rays intersecting exactly one prediction, zero when neither intersects, and absolute lower-surface motion otherwise. Always pair motion with absolute hidden error. Report approximate reference quadrature volume and absolute mesh volume error separately.

Candidate success requires all five checks at the family level. Use 10,000 paired percentile bootstrap replicates with seed 527203100, resampling whole families. Each family averages relevant sites and signs equally. These are chosen experimental margins, without agronomic calibration.

1. Artifact remote motion versus maximum mirror: upper 95% interval below −0.5 mm.
2. Artifact hidden error versus clipped q95: upper interval below zero.
3. Unilateral upper-core error: upper interval at most 0.75 mm.
4. Bilateral hidden-core error versus detail reflected: upper interval at most 0.75 mm on outward flank and near-silhouette cases.
5. Mean ray coverage across cases: lower interval at least 0.95.

Report positive-apex fixed-height vs ordinary mirror separately, stratify by sign and location and retain failures. Require valid predictions and finite metrics for every planned case. Summarize expected limitations from the synthetic body, silhouette and the identical-input ambiguity. Development verifies behavior and gives preliminary numbers. Freeze protocol, dependencies, code and development evidence before generating confirmation. Keep one immutable confirmation run; report any failed criterion.
