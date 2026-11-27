# Potato3D

CPU-based shape completion, RGB-D fusion, and weight and volume estimation for
conveyor potato scans. The repository collects the study code, frozen
protocols, result tables, figures, and course deliverables.

## Research results

- [Integrated multi-frame report](studies/potato_multiframe_final_report.md) covers
  three-view fusion, one-click SAM 2 tracking, and the matched center-frame
  depth benchmark. The fusion closeout documents why points with uncertain
  depth evidence can contribute useful surface.
- [Registration-pin findings](studies/regional_shape_v1/corepp_pin_findings.md)
  and the [CSE527 results section](course/PIN_RECOLORING_RESULTS.md) summarize
  the matched recoloring test, patch swaps, and paired comparison with TripoSR.
- [Results notebook](potato3d_results.ipynb) and [HTML summary](research_summary.html)
  provide walkthroughs of the archived experiments.

Study-specific replay commands are in the reports. Full replays can require the
original datasets, released checkpoints, or local caches listed in those commands.
The compact run records and the two derived clouds used for the fusion closeout
figure are included at their original paths under `outputs/`.

## Course deliverables

The [nine-page report](output/pdf/CSE527_CPU_Shape_Completion_Report.pdf),
[offline six-case 3D showcase](course/showcase/index.html),
[focused primary-source review](course/related_work.md), and
[submission ZIP](dist/CSE527_CPU_Shape_Completion.zip) are available.
The ZIP has five top-level files and a nested reproduction archive with three
verified source checkpoints, editable report source and compact evidence. Raw
real datasets and reference geometry are excluded. A fresh extracted installation
passes 71 tests and an unscored three-method analytic fixture without network
access. The report preserves the positive and negative results and their
experimental scope.

Build instructions and presentation-only provenance are in [course/README.md](course/README.md).

The original CSE527 geometry baselines run on an Apple M2 Pro CPU and cover
analytic validation, real demo discovery, ellipsoid, belt-closed convex hull,
and mirror completion. Spatial confidence reduced errors from isolated spikes.
Broader annular support improved coherent patches and failed the narrow-feature
preservation criterion.

## Install

Python 3.12 is recommended; the checked environment used Python 3.12.14 on macOS
26.6.2 arm64. No CUDA, PyTorch, Open3D or GPU is required. Exact dependencies are
recorded in `uv.lock`.

```bash
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

There are now **71 passing tests**. The initial checked runs are `outputs/demo_baselines_v2` (15/15
successful predictions) and `outputs/synthetic_study_v2` (24/24). See
[checkpoint results](docs/experiment_log.md), [metric definitions](docs/methodology.md),
and [dataset provenance](data/README.md). The compact
[checkpoint record](docs/checkpoint_results.json) and
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

## Multiscale support and genuine-feature controls

The [multiscale report](docs/multiscale_confidence_report.md) records **432 development
and 864 confirmation predictions**, all valid, on fresh reserved families. Annular
support detected 599/600 coherent patch points and preserved wide protrusions,
but damaged narrow genuine features. Two of seven predefined criteria failed;
the candidate was not accepted as a general replacement.

The [external-data audit](docs/external_data_access.md) also established two small
CRC-verified real fruit pairs from the Bonn archive using only 5.2 MB of selected
compressed assets. Source data stays ignored. These are alignment/data-access
smoke checks, not model benchmark scores. The separate lab-fruit study below
adds an explicit adapter and evaluation protocol for those reference types.

## Real fruit: point-cloud references and object holdout

The [sealed protocol](docs/bonn_real_v1_protocol.md) uses eight official-training
laboratory fruit references, three development fruit and twelve reserved local
holdout fruit from public validation. It is not the official hidden test or a
potato generalization claim. The bounded subset is 55 MB of compressed members;
no full Bonn archive or gated potato dataset is downloaded.

The adapter uses supplied camera intrinsics, metric depth, mask and pose. Raw
input and a fixed depth-component filter are both reported. Classical methods
are a training population ellipsoid, a regularized partial ellipsoid, and
training-template completion. Geometry scoring accepts reference point clouds
without constructing a mesh or inventing a reference volume. No belt plane is
assumed. Predictions are exported before each evaluation reference is loaded.

Read [the real-data report](docs/bonn_real_v1_report.md) for the scored results,
failure cases, CPU cost, reproduction evidence and limitations. Every fruit has
an offline `comparison.html` viewer and exported PLY predictions.

For reproduction from the frozen source snapshot, use fresh output paths:

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
.venv/bin/python scripts/fetch_bonn_real.py --roles train development --out data/raw/my_bonn
.venv/bin/python scripts/run_bonn_real.py train --data data/raw/my_bonn --out outputs/my_bonn_prior
.venv/bin/python scripts/run_bonn_real.py development --data data/raw/my_bonn \
  --prior outputs/my_bonn_prior --out outputs/my_bonn_development
.venv/bin/python scripts/run_bonn_real.py select --input outputs/my_bonn_development --out outputs/my_bonn_selection.json
.venv/bin/python scripts/fetch_bonn_real.py --roles holdout \
  --selection outputs/my_bonn_selection.json --out data/raw/my_bonn
.venv/bin/python scripts/run_bonn_real.py holdout --data data/raw/my_bonn \
  --prior outputs/my_bonn_prior --selection outputs/my_bonn_selection.json --out outputs/my_bonn_holdout
.venv/bin/python scripts/run_bonn_real.py analyze --input outputs/my_bonn_holdout --out outputs/my_bonn_analysis.json
.venv/bin/python scripts/plot_bonn_real.py outputs/my_bonn_holdout --out outputs/my_bonn_figures
```

Reproduction verifies the fixed study; existing holdout objects stay closed to
tuning. The course report/showcase and focused related-work review are now
prepared. Stronger method, potato-transfer or calibration claims require new
external evidence and a new protocol. Hidden-shape ambiguity and the narrow-feature
failure remain explicit limitations.
