# Height robustness development results — 2026-11-13

## Outcome and scope

The predefined **synthetic development** hypothesis passed: fixed 95th-percentile
height estimation plus cap clipping reduced both outlier-condition hidden geometry
error and absolute analytic-volume error against maximum-height symmetry, while
remaining inside the specified clean observed-fidelity guardrail. This supports
a targeted robustness finding on this generator, **not** novelty, real-potato
generalization, calibration accuracy, or recovery of an unobservable underside.

No quantile, threshold, mesh setting or case was selected after reading scores.
The prior demo and two-object pilot were not rerun or retuned. The sealed protocol
and design are `configs/height_development_v1.yaml`,
`docs/height_development_protocol.md` and `docs/height_development_v1_seal.json`.

## Implementation and execution

- Added `calibration.py` and a standalone depth/PLY/background-plane audit.
- Added `DevelopmentShape`: analytic, nonconvex, vertically asymmetric lower
  surfaces with independently known volumes. Fresh axes, waist, yaw and seeds.
- Added two classical ablations: `symmetry_height95` (q95 plane + lower-floor
  constraint) and `symmetry_robust95` (same plane + upper-cap clipping). The latter
  clips genuine apex points as well as outliers; no learned confidence is claimed.
- Added family-cluster aggregation, paired bootstrap comparisons, clean-observation
  evaluation, calibration-error diagnostics, per-profile tables and deterministic
  report/visualization scripts. Baseline defaults retain their prediction behavior.
- **31 tests passed** before scoring. Tests include asymmetric analytic volume,
  identical-visible/different-hidden shapes, camera projection, robust plane fitting,
  proper transforms, robust mesh validity and family-paired statistics.

The run `outputs/height_development_v1` completed **720/720 valid predictions**:
12 independent geometric families × 2 hidden profiles × 6 conditions × 5 methods.
This means **24 shape objects, 144 condition instances, 12 independent families**,
not 144 independent test objects. Every condition and method was retained.

Apple M2 Pro CPU, Python 3.12.14, frozen dependencies; serial inference/evaluation
with OpenBLAS/OMP/VECLIB thread limits set to 1. Main run time was **168.09 s**;
process-lifetime peak RSS **425.58 MiB**. That time includes loading/generation,
mesh checks/exports and metrics, excludes imports/installation/downloads, and
excludes figures/analysis generated afterward. No model training or GPU was used.

## Primary outlier-condition comparison

2% of input z values receive +10–20 mm outliers. Distances are unsquared mm;
volume error here is **MAE against the analytic formula**, not the earlier pilot's
RMSE. Average the two hidden variants within each family, then families equally.

| Method | Hidden Chamfer (mm) | Analytic-volume MAE (mL) | Height absolute error (mm) |
|---|---:|---:|---:|
| Ellipsoid | 4.345 | 14.891 | — |
| Belt-closed hull | 4.987 | 67.641 | — |
| Mirror maximum | 5.949 | 38.726 | 17.662 |
| Mirror q95 + lower floor | 2.058 | 8.160 | 0.431 |
| Mirror q95 + cap clipping | 2.045 | 7.760 | 0.431 |

Predefined full-variant minus maximum-height paired differences, with 2,000
family-bootstrap replicates over **12** independent families:

| Primary metric | Mean difference | 95% family-bootstrap interval |
|---|---:|---:|
| Hidden Chamfer | −3.904 mm | [−4.289, −3.534] mm |
| Absolute analytic-volume error | −30.965 mL | [−33.507, −28.302] mL |

Both intervals are below zero and all 24 shape pairs are present. The clean
observed-to-surface guardrail degraded by **0.0159 mm**, interval
[0.0144, 0.0175] mm, below the predefined **0.5 mm mean** bound. These intervals
describe variation over the specified synthetic parameter distribution. They
do not quantify uncertainty over unknown real potato populations.

Height/floor correction explains most hidden-error improvement (5.949→2.058 mm).
Additional cap clipping changes it only to 2.045 mm, while full-surface Chamfer
improves from 1.587 to 1.383 mm. These are separable ablations, although the
height-only variant includes an explicit floor constraint when needed.

## Failures, bias and limits

The full robust variant is not uniformly better. The same fixed quantile biases
the height low by about 0.638 mm on clean input. Complete summary tables and
per-profile differences are saved, including unfavorable conditions:

| Condition | Mirror max: hidden Chamfer (mm) | Full q95 variant: hidden Chamfer (mm) | Mirror max: volume MAE (mL) | Full q95 variant: volume MAE (mL) |
|---|---:|---:|---:|---:|
| Clean | 1.629 | 1.828 | 6.529 | 7.477 |
| 2 mm depth jitter | 2.016 | 1.679 | 8.578 | 6.529 |
| 2% positive outliers | 5.949 | 2.045 | 38.726 | 7.760 |
| Missing patch | 1.625 | 1.929 | 6.529 | 7.898 |
| Belt error +3 mm | 2.840 | 3.093 | 14.025 | 15.673 |
| Belt error −3 mm | 1.649 | 1.592 | 6.529 | 6.529 |

Thus this intervention addresses sparse depth outliers, not general belt
miscalibration or all missing-data cases. Measurements of fidelity to injected
noise/outliers can also reward the wrong surface, so evaluation includes the
independent clean observation set, which never enters prediction.

## Explicit hidden-surface ambiguity

Within each family, the two references have identical top cap, footprint, height,
and belt contact but different lower curvature/volume. All **72/72 input pairs**
and **360/360 prediction pairs** were byte-identical across the hidden variants.
There is no reference information leaking into predictions.

For clean inputs, maximum-height symmetry has mean hidden Chamfer **0.538 mm**
on symmetric undersides but **2.720 mm** on asymmetric undersides. The robust
variant gives **0.658 / 2.998 mm** respectively. Low visible-surface error does
not establish hidden-surface correctness.

A separately labeled **post-hoc explanatory diagnostic** finds a two-profile
volume-MAE lower bound of **6.529 mL** averaged over these families: a shared
deterministic estimate cannot have lower average absolute error against two
equally weighted hidden volumes than half their difference. This explains why
several combined volume-MAE entries are identical even when geometry errors
change. It is not a new primary endpoint, a universal lower bound for arbitrary
potatoes, or a calibrated uncertainty interval. Always inspect per-profile results.

## Calibration and real-data status

The independent follow-up in `docs/calibration_followup.md` verifies depth/PLY
consistency and saves background-plane proxies. It does **not** certify a true
support plane or resolve `2R2-8`'s measurement mismatch. No real-reference volume
was repaired, no GT-driven scale correction occurred, and the candidates were
not scored on the closed real demo. Real evaluation still requires validated
measurement IDs/scale/calibration and an object-level development/test split.

## Reproduction and artifacts

From the project root, use new output paths:

```bash
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
.venv/bin/python -m pytest -q
.venv/bin/python scripts/run_height_study.py --out outputs/my_height_run
.venv/bin/python scripts/analyze_height_study.py outputs/my_height_run \
  --out outputs/my_height_analysis
.venv/bin/python scripts/plot_height_study.py outputs/my_height_run \
  --analysis outputs/my_height_analysis/analysis.json --out outputs/my_height_figures
.venv/bin/python scripts/analyze_ambiguity_bound.py outputs/my_height_run \
  --out outputs/my_height_analysis/ambiguity_bound.json
.venv/bin/python scripts/check_height_reproducibility.py \
  --out outputs/my_height_repeat_check.json
```

Reproduction of a frozen run is for verifying the recorded implementation, not
selecting new parameters on its scores. Future method development needs a new
protocol/case reservation. The reproducibility check itself uses a separate
validation fixture, not the scored study objects: two fresh processes produced
byte-identical geometry, fit parameters and metrics for all three mirror variants.

Raw run artifacts: `outputs/height_development_v1/`. Predetermined analysis:
`outputs/height_development_v1_analysis/analysis.json`, `group_summary.csv` and
`paired_comparisons.csv`. Fixed-family clean/outlier PNG/offline HTML comparisons
and the results-derived chart: `outputs/height_development_v1_figures/`.
Compact evidence: `docs/height_development_results.json`. All outputs are retained;
the protocol/design seals and current source hashes match the scored run.

## Next bounded milestone

The next candidate should address the **observed clean-data bias**: derive
spatial depth confidence from partial neighborhoods, so reliable apex points
are preserved while isolated depth failures have less influence on height.
Reserve fresh geometric families and separate family-level development and
confirmation sets before implementation/tuning. Compare against these fixed
q95 ablations, with clean geometry and missing-patch/calibration failures as
guardrails. A trained shape prior or uncertainty model remains a separate step;
no method should pretend these ambiguous undersides became identifiable.
