# Potato3D — CPU shape-completion baselines

A reproducible CSE527 geometry prototype for partial potato scans. Milestones 0
and 1 run on an Apple M2 Pro CPU: analytic validation, real demo discovery,
ellipsoid / belt-closed convex hull / mirror completion, geometry and volume
evaluation, mesh exports, PNG comparisons and offline interactive 3D viewers.
The proposed contribution is **not yet established**. A spatial confidence
candidate now passes predefined independent synthetic confirmation checks for
clean geometry and isolated spikes, but fails coherent bad-depth patches. The
reports preserve these limits; no real-generalization or novelty claim is made.

## Install

Python 3.12 is recommended; the checked environment used Python 3.12.14 on macOS
26.6.2 arm64. No CUDA, PyTorch, Open3D or GPU is required. Exact dependencies are
recorded in `uv.lock`.

```bash
cd /Users/meliboevbilol/Desktop/potato
export UV_CACHE_DIR="$PWD/.cache/uv"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
uv sync --locked --extra dev
.venv/bin/python -m pytest -q
```

## One-command analytic demo

```bash
.venv/bin/potato3d synthetic --out outputs/my_synthetic_run
```

Output directories must be new; earlier experiments are never overwritten.
Inspect `results.csv`, `results.json`, `summary.json`, `inputs.json`, `config.json`,
`environment.json` and `run.json`. Each object/condition folder contains input,
reference and three prediction `.ply` files, fit parameters, `comparison.png`
and `comparison.html`. Open HTML locally for rotating full triangular meshes;
PNG is an area-sampled surface preview. HTML includes Plotly and works offline.

## Real public demo

The pinned archive is **279 MB compressed / 368 MB expanded**, contains five
objects and is already downloaded in this workspace. For a fresh checkout:

```bash
.venv/bin/python scripts/download_demo.py
.venv/bin/potato3d inspect --data data/raw/3DPotatoTwinDemo \
  --belt-depth-mm 350 --out outputs/my_demo_audit.json
.venv/bin/potato3d demo --data data/raw/3DPotatoTwinDemo \
  --belt-depth-mm 350 --out outputs/my_demo_run
```

Only the **five explicitly registered frames** are evaluated, out of 138 available
partial frames. The camera-to-belt depth of 350 mm is an approximate paper value,
not a recovered or independently calibrated measurement. Registration matrices
are fixed release metadata. Predictions never use reference meshes or ICP.

**All five raw references are open meshes.** Direct mesh-volume error is null;
errors against CSV physical volume and reported Metashape volume are separate.
`2R2-8` has inconsistent geometry and listed dimensions/volume and stays visibly
flagged. All demo results are **smoke tests**, with no held-out performance claim.
See [the data audit](docs/feasibility.md) before interpreting numbers.

## Matched failure-mode pilot and reproducibility

```bash
.venv/bin/potato3d synthetic --study --out outputs/my_study
.venv/bin/python scripts/plot_results.py outputs/my_study/summary.json \
  --out outputs/my_study/failure_modes.png
.venv/bin/python scripts/check_reproducibility.py --out outputs/my_repeat_check.json
.venv/bin/python scripts/evaluate_results.py outputs/my_demo_run/results.json \
  --out outputs/my_recomputed_summary.json
```

The study uses two analytic objects, each with clean input, 2 mm depth jitter,
2% positive depth outliers, and one missing-depth patch. These are development
examples, not eight independent test objects. Change settings in a copied
`configs/baseline.yaml` and pass `--config`; retain scored outputs.

## Checked results

There are now **47 passing tests**. The initial checked runs are `outputs/demo_baselines_v2` (15/15
successful predictions) and `outputs/synthetic_study_v2` (24/24). See
[checkpoint results](docs/experiment_log.md), [metric definitions](docs/methodology.md),
and [dataset provenance](data/README.md). Generated data and outputs are ignored;
the compact [checkpoint record](docs/checkpoint_results.json) and
[input manifest](data/demo_manifest.json) preserve the reported evidence.

The follow-up [calibration audit](docs/calibration_followup.md) verifies PNG/PLY
consistency and estimates background-plane proxies; physical belt calibration
and the `2R2-8` measurement mismatch remain unresolved.

## Fresh robustness study

The [sealed development protocol](docs/height_development_protocol.md) uses 12
families, each with two ambiguous undersides and six matched conditions. The
run `outputs/height_development_v1` completed **720/720 valid predictions** on CPU.
Results and negative cases are in [the report](docs/height_development_report.md),
with a compact [machine-readable checkpoint](docs/height_development_results.json).

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
.venv/bin/python scripts/run_height_study.py --out outputs/my_height_run
.venv/bin/python scripts/analyze_height_study.py outputs/my_height_run \
  --out outputs/my_height_analysis
.venv/bin/python scripts/plot_height_study.py outputs/my_height_run \
  --analysis outputs/my_height_analysis/analysis.json --out outputs/my_height_figures
```

Quantile 0.95 is fixed. Independent clean observations enter evaluation only.
Family-bootstrap intervals avoid treating two identical visible scans as
independent cases. Existing scored outputs are preserved. Future tuning requires
fresh reserved cases rather than using the recorded scores repeatedly.

## Spatial confidence: development and confirmation

The [sealed spatial protocol](docs/spatial_confidence_protocol.md) reserved six
development families and twelve independent confirmation families before coding.
A fixed two-option development budget selected a local residual threshold of
3 mm by the preset tie-break. Source/parameters/evidence were frozen before
confirmation. **588 development + 1,344 confirmation predictions** all produced
valid meshes. All five confirmation criteria passed within this analytic
distribution; coherent patches and Gaussian jitter expose material limitations.

Read [the confirmation report](docs/spatial_confidence_report.md),
[the method](docs/spatial_confidence_method.md) and
[machine-readable results](docs/spatial_confidence_results.json).

```bash
.venv/bin/python scripts/run_spatial_study.py --split development --out outputs/my_spatial_development
.venv/bin/python scripts/select_spatial_candidate.py outputs/my_spatial_development --out outputs/my_spatial_selection.json
.venv/bin/python scripts/run_spatial_study.py --split confirmation \
  --selection outputs/my_spatial_selection.json --out outputs/my_spatial_confirmation
.venv/bin/python scripts/analyze_spatial_study.py outputs/my_spatial_confirmation --out outputs/my_spatial_analysis
```

Full reproduction commands and a restorable verified source snapshot are
documented in the report. Previous scored outputs are unchanged.

Next: address coherent-patch self-support with broader spatial checks and real
protrusion controls under fresh reservations. Hidden-surface ambiguity, exact
belt calibration, inconsistent real metadata and validated real-data evaluation
remain separate issues.
