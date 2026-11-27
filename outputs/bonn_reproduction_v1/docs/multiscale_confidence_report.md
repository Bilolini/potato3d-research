# Multiscale confidence experiment — 2026-11-13

## Decision: full hypothesis rejected

The wider annular fit substantially improved coherent-patch reconstruction and
the boundary gate preserved wide genuine protrusions. However, the method failed
the **narrow genuine-feature preservation** criterion and did not establish the
required coherent-patch noninferiority bound against q95. **Five of seven**
predefined checks passed. The full candidate is not accepted as a generally
reliable replacement. Neither parameters nor criteria were changed afterward.

This is a synthetic hypothesis test with a retained negative result. It does not
establish novelty or physical sensor reliability. Earlier experiments remain
unchanged, including the previously successful but narrower isolated-spike study.

## Implementation and independent controls

`completion/multiscale.py` adds an annular robust quadratic height fit around each
query, excluding its nearest neighbors. It complements the unchanged 32-neighbor
local fit. Broad positive-residual components are repaired only when supported
by abrupt boundary residual jumps. The ungated annular ablation removes that
boundary requirement. Trusted points remain exact, and both use the previous
mirror/floor completion with trusted-maximum height.

`ProtrusionShape` adds a genuine smooth 8 mm bump to the upper surface, with wide
or narrow support. Its added volume is analytically known and was checked by
independent numerical integration; tessellated total volumes were also tested.
These are different clean geometries, not injected depth errors. Feature-core
points carry at least 25% of bump amplitude and are used only in evaluation.
This localized metric prevents a global mean from hiding feature erasure.

All new references use subdivision 5 and the same 10,000 area samples across
methods. There are 2,500 input points per full scan. Each geometric family has
one alternating hidden profile, with all feature variants and corruptions kept
together. The hidden-twin identifiability experiment was already established;
it was not repeated or counted as new independent evidence here.

| Split | Independent families | Shape objects | Cases | Predictions | Failures |
|---|---:|---:|---:|---:|---:|
| Development | 6 | 18 | 54 | 432 | 0 |
| Confirmation | 12 | 36 | 108 | 864 | 0 |

Six of the twelve confirmation families have each hidden profile. Per-profile
means are descriptive; confidence intervals are withheld below ten families.
Overall confirmation intervals resample the twelve independent families.

## Frozen development choice

The complete budget was inner/outer neighbor counts **32/160 or 64/256**. The
fixed score includes clean and patch hidden Chamfer, patch absolute analytic
volume error, and both localized feature errors. The 64/256 option won:

| Option | Clean hidden (mm) | Patch hidden (mm) | Patch volume MAE (mL) | Wide core (mm) | Narrow core (mm) | Selection score |
|---|---:|---:|---:|---:|---:|---:|
| 32/160 | 1.6430 | 7.3618 | 33.6781 | 0 | 2.0226 | 13.7236 |
| 64/256 | 1.6430 | 1.6521 | 6.7799 | 0 | 2.0426 | 7.5159 |

The development data already showed a narrow-feature problem. The predefined
selection rule still selected the smaller score; it did not permit changing
thresholds or removing that control. The selected parameters, source, lock,
protocol/design and development evidence were sealed before confirmation.

## Seven confirmation criteria

Differences are full gated multiscale minus baseline. Distances are unsquared mm;
volume error is **MAE against the analytic formula**, not RMSE. All pairs and
families are present. Intervals use 2,000 paired family-bootstrap replicates.

| Criterion | Mean difference | 95% interval | Required upper bound | Result |
|---|---:|---:|---:|---|
| Patch hidden vs single-scale | −6.2089 mm | [−8.0581, −4.4659] | <0 | pass |
| Patch volume absolute error vs single-scale | −27.3304 mL | [−37.2325, −18.3802] | <0 | pass |
| Patch hidden vs q95 | +0.1894 mm | [−0.1538, +0.8177] | ≤0.20 mm | **fail** |
| Isolated-spike hidden vs single-scale | +0.0006 mm | [−0.0015, +0.0029] | ≤0.10 mm | pass |
| Clean hidden vs mirror max | 0 mm | [0,0] | ≤0.05 mm | pass |
| Wide-feature core vs mirror max | 0 mm | [0,0] | ≤0.5 mm | pass |
| Narrow-feature core vs mirror max | +1.3070 mm | [+0.7570, +1.7817] | ≤0.5 mm | **fail** |

Although the patch difference's mean is within the specified margin, its upper
confidence bound is not. The noninferiority requirement is therefore not met.
The feature failure is likewise not softened by a favorable global mean.

## Gains and feature costs on the same confirmation cases

| Method | Patch hidden Chamfer (mm) | Patch volume MAE (mL) | Wide genuine core error (mm) | Narrow genuine core error (mm) |
|---|---:|---:|---:|---:|
| Mirror max | 8.2025 | 35.5923 | 0 | 0 |
| Fixed q95 | 1.7640 | 7.2848 | 3.5315 | 3.8382 |
| Single-scale local | 8.1623 | 35.4498 | 0 | 0.7810 |
| Annular, no boundary gate | 1.9534 | 8.1194 | 1.9283 | 2.4028 |
| Boundary-gated multiscale | 1.9534 | 8.1194 | **0** | **1.3070** |

The gate prevents the broad fit from erasing the wide genuine feature. It does
not reliably preserve narrow features: 46 of 108 evaluated narrow-core points
were selected for repair, versus 24/108 by the original local rule and 79/108 by
ungated annular repair. Wide-core repair counts were 0/534 gated, 0/534 local,
and 338/534 ungated. These are descriptive counts on the generator, not real-data
classification accuracy estimates.

For coherent noise, gated repair selected **599/600** injected patch points,
compared with **36/600** by single-scale confidence. The remaining point was in
confirmation family 11 and still shifted the trusted-maximum height by **11.91 mm**.
That family's hidden error was 6.5155 mm, illustrating the tail sensitivity of
a maximum even when most bad points are detected. This is a post-hoc failure
diagnosis; it did not change the registered endpoints or parameters.

All three spatial variants selected the 600 independent spikes. Clean smooth
scans had zero observed-error degradation. Both successful noise repair and
genuine-feature erasure must therefore remain visible in the conclusion.

## Other conditions and the hidden prior

| Condition | q95 hidden (mm) | Single-scale hidden (mm) | Gated multiscale hidden (mm) |
|---|---:|---:|---:|
| Clean smooth | 1.8356 | 1.6328 | 1.6328 |
| 2 mm Gaussian jitter | 1.6543 | 2.0793 | 2.0831 |
| Isolated spikes | 2.0515 | 1.6333 | 1.6339 |
| Missing patch | 1.9201 | 1.6258 | 1.6258 |
| Belt error +3 mm | 3.2474 | 2.9813 | 2.9813 |
| Belt error −3 mm | 1.6853 | 1.7485 | 1.7485 |

Gaussian denoising and calibration remain unresolved. Preserving a one-sided
genuine bump can also increase hidden error under the mirror prior, whereas
clipping it may make hidden metrics look better while destroying real visible
geometry. The localized core criterion prevents rewarding that behavior.

## Tests, runtime and reproduction

**60 tests passed before scoring.** They cover independent bump-volume integration,
mesh volumes, true-feature masks, annular quadratic recovery, abrupt-versus-smooth
component gating, valid meshes, split separation and confirmation refusal after
source changes. The single-scale confidence source file still matches its
previously frozen implementation.

Apple M2 Pro CPU, Python 3.12.14, locked dependencies, OpenBLAS/OMP/VECLIB limits 1.
Development took **131.07 s**, peak process RSS **680.09 MiB**; confirmation took
**286.66 s**, peak RSS **725.17 MiB**. Main totals include generation, checks,
exports and metrics; they exclude imports, later figures/analysis and network
downloads. The full gated fit averaged about **302 ms** per patch case, versus
63 ms single-scale and 18 ms q95, excluding common loading/evaluation/export.

Two fresh processes on separate patch/feature fixtures produced identical ten
geometry files, fitted parameters and metrics. Current source/lock/protocol and
frozen evidence match; prior run records are retained. A restorable source and
evidence snapshot is `outputs/multiscale_confidence_reproduction_v1/`.

```bash
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
.venv/bin/python -m pytest -q
.venv/bin/python scripts/run_multiscale_study.py --split development --out outputs/my_ms_development
.venv/bin/python scripts/select_multiscale_candidate.py outputs/my_ms_development --out outputs/my_ms_selection.json
.venv/bin/python scripts/run_multiscale_study.py --split confirmation \
  --selection outputs/my_ms_selection.json --out outputs/my_ms_confirmation
.venv/bin/python scripts/analyze_multiscale_study.py outputs/my_ms_confirmation --out outputs/my_ms_analysis
.venv/bin/python scripts/plot_multiscale_study.py outputs/my_ms_confirmation \
  --analysis outputs/my_ms_analysis/analysis.json --out outputs/my_ms_figures
```

Actual run folders use `multiscale_confidence_development_v1` and
`multiscale_confidence_confirmation_v1`. Corresponding `_analysis` folders contain
full grouped/per-profile CSVs, paired differences and detection diagnostics;
`multiscale_confidence_confirmation_v1_figures` contains the tradeoff chart and
fixed-family examples. Compact evidence is `docs/multiscale_confidence_results.json`.
No previous scored families were rerun or used for parameter selection.

## Real-data progress and next decision

The parallel access audit established two new public real-data smoke pairs from
the Bonn fruit benchmark without downloading its full archive. CRC-verified data,
provided-pose alignment and metric-unit checks are recorded in
`docs/external_data_access.md`; these are not completion-method scores. They have
point-cloud references and no conveyor plane or physical-volume target in the
inspected files, so the current completion assumptions cannot be silently reused.

The next priority is a point-cloud-reference adapter and a fixed real-data
validation protocol. The narrow-feature and surviving-maximum failures argue
against claiming a generic repair rule from further synthetic threshold search.
Preserve measured geometry in ambiguous regions and test any revised body-height
prior or abstention/uncertainty rule on fresh cases with explicit feature controls.
Real-data calibration, novelty and the final course report remain incomplete.
