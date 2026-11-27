# Spatial confidence confirmation — 2026-11-13

## Outcome

The selected spatial method passed **all five predefined confirmation criteria**
on twelve fresh synthetic families. It preserved clean input points and removed
isolated positive spikes without the fixed-quantile clean-apex bias. It also
failed badly on coherent bad-depth patches and was worse than q95 under Gaussian
jitter. This is a conditional robustness result within an analytic generator,
**not** general sensor reliability, real-potato validation or established novelty.

The implementation is in `src/potato3d/completion/confidence.py`; the mathematical
method and limits are in `docs/spatial_confidence_method.md`. Local robust
quadratic regression, IRLS and filtering are standard ingredients. The experiment
tests an observation-aware intervention, rather than asserting new mathematics.

## Frozen development and independent confirmation

The protocol/design were hashed before implementation. Six development families
and twelve confirmation families had disjoint generation and observation seeds,
IDs and shapes. Each family has two hidden profiles with identical top-view
observations. All corruptions and both hidden variants remain in the same split.

Development compared exactly two residual thresholds (3 and 5 mm), with 32
neighbors, three IRLS iterations and the other settings fixed. The predefined
scores tied exactly at **3.482078534**, so the preset tie-break selected **3 mm**.
The clean hidden mean was 1.6683 mm, isolated-outlier hidden mean 1.6669 mm and
outlier volume MAE 7.3423 mL for both options. These are selection data only;
six independent families do not support the confirmation claim.

`docs/spatial_confidence_selection_v1.json` freezes parameters, source files,
dependency lock, protocol/design and development evidence. Confirmation refused
changed source/config/evidence and used this sealed selection. No confirmation
case was generated for tuning. No parameter or implementation changed after the
development or confirmation results were read. Previous scored runs were retained.

| Split | Independent families | Shape objects | Condition instances | Predictions | Failures |
|---|---:|---:|---:|---:|---:|
| Development | 6 | 12 | 84 | 588 | 0 |
| Confirmation | 12 | 24 | 168 | 1,344 | 0 |

Confirmation includes five prior baselines, the full spatial method, height-only
and cap-only interventions. All eight methods and seven conditions are present
in the stored tables. The count of independent confirmation units is **12**,
not 24 hidden variants or 168 corruption instances.

## Predefined confirmation checks

Errors use unsquared distances in mm and absolute analytic-volume error in mL.
Differences are full spatial minus the specified baseline, with 2,000 paired
family-bootstrap replicates. The family average includes both hidden variants.

| Criterion | Mean difference | 95% interval | Required upper bound | Result |
|---|---:|---:|---:|---|
| Clean hidden Chamfer vs q95 | −0.1972 mm | [−0.2139, −0.1803] | <0 mm | pass |
| Isolated-spike hidden Chamfer vs mirror max | −4.6760 mm | [−5.3160, −4.0185] | <0 mm | pass |
| Isolated-spike hidden Chamfer vs q95 | −0.4088 mm | [−0.4367, −0.3802] | ≤0.10 mm | pass |
| Isolated-spike volume absolute error vs q95 | −1.1518 mL | [−1.3382, −0.9648] | ≤1 mL | pass |
| Clean uncorrupted-observation error vs mirror max | 0 mm | [0,0] | ≤0.05 mm | pass |

All required pairs and families are available. These are out-of-sample checks
**within the specified synthetic distribution**. They do not establish physical
sensor realism, external validity or calibrated confidence probabilities.

## Positive and negative conditions

Combined means weight families equally. Volume columns are **MAE**, not RMSE.

| Condition | Mirror max hidden (mm) | q95 hidden (mm) | Spatial hidden (mm) | q95 volume MAE (mL) | Spatial volume MAE (mL) |
|---|---:|---:|---:|---:|---:|
| Clean | 1.5978 | 1.7951 | 1.5978 | 7.4526 | 6.5867 |
| 2 mm Gaussian jitter | 2.2250 | 1.6312 | 1.9368 | 6.5867 | 8.2100 |
| 2% independent +10–20 mm spikes | 6.2748 | 2.0076 | 1.5988 | 7.7385 | 6.5867 |
| Missing patch | 1.5987 | 1.8999 | 1.5987 | 7.8532 | 6.5867 |
| Belt error +3 mm | 2.9587 | 3.2138 | 2.9587 | 16.6583 | 15.0164 |
| Belt error −3 mm | 1.6815 | 1.6105 | 1.6815 | 6.5867 | 6.5867 |
| Coherent 2% +15 mm patch | 8.2790 | 1.7190 | **8.2943** | 6.9660 | **35.4649** |

The full method flagged **no clean points** in confirmation and preserved their
geometry exactly relative to mirror max. For isolated spikes, its trusted-height
absolute error was 0.0033 mm, compared with 0.3698 mm for q95 and 18.6423 mm for
mirror max. The clean observed-error guardrail passed without any measured
degradation.

Detection diagnostics count each family scan once, avoiding duplicate hidden
variants. For independent spikes, **600/600** injected points were flagged, with
zero extra flags. For coherent patches, only **35/600** were flagged and **565/600
were missed**. This is generator-specific descriptive detection performance,
not a real-data sensitivity/specificity estimate. Gaussian noise has no binary
spike labels; its flagged fraction was about 1.83%.

The coherent error supports its own local neighborhood and corrupts the trusted
height. Local agreement therefore cannot be interpreted as correctness. Under
jitter, the spatial maximum retains height bias (4.417 mm) and does not match
q95's denoising behavior. The method also leaves belt miscalibration unresolved.

## Ablation on isolated spikes

| Method | Full Chamfer (mm) | Hidden Chamfer (mm) | Analytic-volume MAE (mL) |
|---|---:|---:|---:|
| Mirror max | 3.7180 | 6.2748 | 45.1004 |
| Fixed q95 + cap clipping | 1.3667 | 2.0076 | 7.7385 |
| Spatial height only + floor | 1.5476 | 1.8947 | 7.1408 |
| Spatial cap only, original plane | 5.5942 | 13.5419 | 48.4429 |
| Spatial height + cap | **1.0520** | **1.5988** | **6.5867** |

Correcting the cap while retaining the corrupted plane can make hidden geometry
much worse. Height and upper-surface handling must be evaluated together. The
height-only intervention improves most of the error, while selective upper-cap
repair supplies the remaining gain. The cap-only diagnostic may float above the
belt; it is not a deployable completion rule.

## Hidden-shape ambiguity remains

All **84/84** paired inputs and **672/672** paired predictions are byte-identical
across the two hidden alternatives, with no missing pairs. Reliable visible
observations cannot identify which underside was used. For the full spatial
method on clean inputs:

| Hidden profile | Hidden Chamfer (mm) | Analytic-volume MAE (mL) |
|---|---:|---:|
| Symmetric underside | 0.5390 | 0.7761 |
| Asymmetric underside | 2.6567 | 12.3974 |

Per-profile tables remain essential: several combined volume-MAE entries are
flat because two different hidden volumes share one prediction, as explained
in the prior ambiguity diagnostic. No uncertainty interval is calibrated here.
Real isolated protrusions can also resemble positive sensor spikes; they are
not represented by this generator's smooth top caps.

## CPU cost, tests and reproducibility

Apple M2 Pro CPU, Python 3.12.14, locked dependencies; OpenBLAS/OMP/VECLIB thread
limits 1. **47 tests passed before scoring.** Development took **146.08 s** with
465.64 MiB process peak RSS; confirmation took **375.85 s** with 530.09 MiB peak
RSS. Main run totals include generation, preprocessing, checks, exports and
metrics, exclude process startup/imports/installation, and exclude later analysis
and figures. These are recorded execution costs, not guaranteed throughput.

On confirmation's isolated-spike condition, mean completion time was 65.7 ms for
the full spatial method versus 18.7 ms for q95, excluding shared preparation,
evaluation and exports. Spatial support has a measurable CPU cost.

A separate validation fixture, not a scored split, was run in two fresh
processes: seven geometry files, parameters and metrics were identical. The
analysis was regenerated from saved rows, source/lock/protocol/selection hashes
were verified, and previous JSON run records were checked unchanged. A verified
restorable source/config/evidence snapshot is saved at
`outputs/spatial_confidence_reproduction_v1/`; `REPRODUCE.md` and `MANIFEST.json`
describe restoration and integrity checks. It excludes downloaded real data and
regenerable prediction meshes.

## Commands and artifacts

Use new output paths from the project root:

```bash
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
.venv/bin/python -m pytest -q
.venv/bin/python scripts/run_spatial_study.py --split development --out outputs/my_spatial_development
.venv/bin/python scripts/select_spatial_candidate.py outputs/my_spatial_development --out outputs/my_spatial_selection.json
.venv/bin/python scripts/run_spatial_study.py --split confirmation \
  --selection outputs/my_spatial_selection.json --out outputs/my_spatial_confirmation
.venv/bin/python scripts/analyze_spatial_study.py outputs/my_spatial_confirmation --out outputs/my_spatial_analysis
.venv/bin/python scripts/plot_spatial_study.py outputs/my_spatial_confirmation \
  --analysis outputs/my_spatial_analysis/analysis.json --out outputs/my_spatial_figures
.venv/bin/python scripts/check_spatial_reproducibility.py \
  --selection outputs/my_spatial_selection.json --out outputs/my_spatial_repeat.json
```

Current runs: `outputs/spatial_confidence_development_v1/` and
`outputs/spatial_confidence_confirmation_v1/`. Each has inputs, environment/config,
per-case metrics, meshes, confidence indices/residuals and fit parameters.
Analyses live in the corresponding `_analysis/` folders, with full grouped CSVs,
paired differences and confidence detection tables. Fixed confirmation-family-0
clean/spike/patch PNG/offline HTML comparisons and the scientific overview charts
are in `outputs/spatial_confidence_confirmation_v1_figures/`.
Compact checkpoint: `docs/spatial_confidence_results.json`.

## Next bounded experiment

The next design issue is **coherent-patch self-support**, not another threshold
search on these cases. Reserve fresh development/confirmation families and
compare single-scale support with broader/multiple spatial scales. Include real
positive protrusions as clean controls so a detector is not rewarded for simply
removing every locally unusual surface. Keep Gaussian jitter, calibration error,
runtime and observed-surface preservation as explicit guardrails. Confidence
needs calibration before probabilistic claims; hidden-shape priors and validated
real paired scans remain separate requirements.
