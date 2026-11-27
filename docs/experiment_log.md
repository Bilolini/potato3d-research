# Experiment checkpoint — 2026-11-13 (Asia/Seoul)

## Completed scope

Milestones 0–1 are working; Milestone 2 has a small diagnostic pilot. The proposed
contribution, learned priors, neural baselines, calibrated uncertainty and final
course showcase have not been implemented. There is no full-data or held-out
research result.

The actual machine is an Apple M2 Pro running macOS 26.6.2 arm64, with Python
3.12.14 and the CPU dependencies recorded in `uv.lock`. Source checksums,
configuration, versions, inputs, transformations and metrics accompany each run.
The compact evidence copy is `docs/checkpoint_results.json`.

## Analytic correctness and repeatability

`python -m pytest -q`: **16 passed**. Checks cover analytic ellipsoid/waisted
volumes, units and transform inversion including meter translations, RNG
isolation and area-weighted sampling, exact distances/F-score directions,
null volume targets for open meshes, object-weighted aggregation and failures,
baseline determinism/closure, and quantized RGB-D scan rows.

Two fresh-process executions of the analytic demo produced byte-identical
partial/reference/three prediction PLYs and identical nontiming metrics. The
object-level demo summary also regenerated exactly from stored frame results.
`uv sync --locked --extra dev --offline` passed with the installed cache. These
are local reproducibility checks, not a claim of cross-platform identity.

## Real public demo: 5 potatoes / 5 registered frames

Run: `outputs/demo_baselines_v2`. Config: `configs/baseline.yaml`, seed 527,
10,000 surface samples, shared <=5,000-point fit subset, assumed belt depth
350 mm. **15/15 completions** passed closure/orientation/degeneracy checks.

| Baseline | Unsquared Chamfer (mm) | F-score at 5 mm | Observed-to-surface mean (mm) | RMSE vs CSV physical volume (mL) | RMSE vs CSV reported SfM volume (mL) |
|---|---:|---:|---:|---:|---:|
| Ellipsoid | 3.153 | 77.12% | 1.436 | 58.22 | 56.32 |
| Belt-closed convex hull | 2.408 | 87.23% | 0.818 | 83.51 | 81.99 |
| Mirror cap | 2.906 | 77.86% | 0.108 | 65.35 | 62.69 |

Means weight unique potatoes equally. These five selected demo potatoes are
**smoke examples**, not a test set or evidence of superiority over published
methods. All five reference meshes have boundary holes; direct mesh-volume
errors are unavailable. CSV volume values are separate targets of incompletely
verified provenance, and the `2R2-8` metadata inconsistency strongly compromises
volume interpretation. It remains in these descriptive results and is flagged
in the audit; no favorable subset was selected. Real visible/hidden partition
metrics remain unavailable.

Representative viewer: `outputs/demo_baselines_v2/4R3-4/registered_center/comparison.html`.
Every other object also has a PNG and a fully offline HTML viewer with shared
coordinate ranges. The PNG previews sample each complete surface; HTML shows
the actual triangles.

Full demo run total: **10.38 s**, including loading, checks, exports, metrics and
visualization; process peak RSS **415.91 MiB**, including imports. Mean fit times
were 10.37 ms ellipsoid, 4.30 ms hull and 40.62 ms symmetry. Demo, synthetic and
inspection jobs ran concurrently; these are descriptive timings, **not isolated
throughput benchmarks**. Startup/import/download time is excluded from run time.

## Synthetic development pilot: 2 objects × 4 conditions × 3 methods

Run: `outputs/synthetic_study_v2`. **24/24 completions** passed mesh checks. The
two analytic objects (ellipsoid and waisted) each have clean, noisy, outlier and
missing-patch inputs. Both are symmetric height fields, favoring the mirror
prior. These are two development objects, not eight independent samples.

| Condition | Baseline | Full Chamfer (mm) | Hidden Chamfer (mm) | Volume RMSE vs analytic formula (mL) |
|---|---|---:|---:|---:|
| Clean | Ellipsoid | 0.893 | 0.895 | 0.71 |
| Clean | Belt-closed convex hull | 2.384 | 3.733 | 21.11 |
| Clean | Mirror cap | 0.529 | 0.529 | 0.50 |
| 2 mm depth jitter | Ellipsoid | 2.582 | 2.617 | 12.84 |
| 2 mm depth jitter | Belt-closed convex hull | 3.151 | 3.764 | 32.77 |
| 2 mm depth jitter | Mirror cap | 1.882 | 2.918 | 14.77 |
| 2% positive depth outliers | Ellipsoid | 5.682 | 5.439 | 19.42 |
| 2% positive depth outliers | Belt-closed convex hull | 4.732 | 3.744 | 58.32 |
| 2% positive depth outliers | Mirror cap | 3.811 | 7.310 | 47.23 |
| Missing patch | Ellipsoid | 0.887 | 0.890 | 1.44 |
| Missing patch | Belt-closed convex hull | 2.379 | 3.718 | 20.70 |
| Missing patch | Mirror cap | 0.557 | 0.556 | 0.93 |

The chart `outputs/synthetic_study_v2/failure_modes.png` is generated directly
from its `summary.json` by `scripts/plot_results.py`. No confidence intervals are
reported for two/five unique objects. The run took 6.38 s and process peak RSS
was 533.66 MiB, with the same timing/concurrency caveats as above.

## Observed failures and next bounded experiment

The flat-belt hull overfills the rounded underside even for clean ellipsoids.
Mirror completion gives low observed-point error yet can give a bad underside:
2% positive depth outliers raised its mean hidden error from **0.529 to 7.310 mm**
while its observed-point error was only **0.230 mm**. Its plane uses maximum
height, so sparse positive outliers shift the hidden-surface prior. On real
objects, preserving observations alone also does not minimize global geometry
or establish correct volume. This is a measured motivation, not evidence of a
new remedy or its novelty.

Next, resolve `2R2-8` measurement identity/scale and obtain independent belt
plane/tilt calibration before using these data for research conclusions. Then
predefine a **fresh** synthetic development protocol with new object parameters
and seeds, including asymmetric undersides, and compare maximum-height against
a robust height/plane estimate. Predefine hidden-region Chamfer and analytic
volume error as primary checks, with observed fidelity as a guardrail; isolate
height estimation from surface smoothing. This would be the smallest useful
ablation before confidence-weighted refinement. Do not tune on these scored
pilot cases or call a standard robust estimator a novel contribution.

## Implementation issue retained for traceability

The first real run `outputs/demo_baselines_v1` recorded **2 symmetry failures**
(5R3-2, R7-7). Quantized rows produced near-collinear projected Delaunay triangles.
Deleting them after closing the cap created holes. The correction deletes them
before computing closure boundaries; a synthetic quantized-row regression check
was added. `v2` is the corrected implementation and uses the same baseline
settings; no geometry hyperparameter was selected for better reference scores.
Earlier outputs are retained. The first hand-written nonconvex-shape test also
overstated the expected convex-hull volume gap (5% versus the actual ~3%); the
assertion now checks a 2% gap, independently of baseline scores.

## Follow-up — sealed height development v1

See `docs/calibration_followup.md` for the completed source/depth audit and
`docs/height_development_report.md` for the new predetermined experiment. Previous
outputs above are retained. The fresh run completed 720/720 predictions with no
mesh failures, and 31 tests passed before scoring. Fixed q95 height/cap ablations
improved the predefined outlier endpoints (hidden error 5.949→2.045 mm; analytic
volume MAE 38.726→7.760 mL), but worsened clean/missing-patch geometry. The
two undersides per family have identical inputs and predictions, explicitly
demonstrating the remaining ambiguity. No proposed novelty or real-potato
generalization is established. Current summaries additionally record independent
family-cluster counts; historical summary JSONs remain unchanged.

## Follow-up — spatial confidence v1

`docs/spatial_confidence_report.md` records a separately sealed development and
confirmation study. Local robust quadratic height confidence preserves trusted
points and selectively repairs positive spikes. The complete two-option budget
tied on development; threshold 3 mm won by the preset tie-break. Six development
families (588 predictions) and twelve independent confirmation families (1,344
predictions) had no mesh failures; 47 tests passed before scoring.

All five predefined confirmation checks passed. Full spatial hidden error was
1.5978 mm clean and 1.5988 mm for isolated spikes, versus q95's 1.7951 / 2.0076 mm.
The coherent-patch condition failed badly: 565/600 known patch points were missed,
and hidden error was 8.2943 mm versus q95's 1.7190 mm. Gaussian jitter was also
worse than q95. These negative cases remain in every complete report; parameters
were not adjusted after confirmation. Identical paired observations/predictions
retain hidden-shape ambiguity. Original demo, pilot and height-development run
records were checked unchanged. The source/config/evidence snapshot supports
restoring this implementation after future changes.

## Follow-up — multiscale confidence v1 and real-data access

See `docs/multiscale_confidence_report.md`. The full hypothesis was **rejected**:
five of seven frozen confirmation checks passed, while patch noninferiority to
q95 and narrow genuine-feature preservation failed. Six development families
(432 predictions) and twelve confirmation families (864 predictions) had no mesh
failures; 60 tests passed before scoring. Coherent-patch hidden error improved
from single-scale's 8.1623 to 1.9534 mm, but narrow-feature core error was 1.3070 mm
against a 0.5 mm bound. Wide features were preserved. Parameters were not revised
after confirmation; negative cases and prior run records were retained.

`docs/external_data_access.md` records HTTP-range/CRC retrieval of train/lab1 and
val/lab15 frame 00001 from the public Bonn benchmark (5.2 MB compressed assets).
Provided-pose raw median overlap was 1.640 / 3.152 mm, with no ICP or method
evaluation. Point-cloud references, large partial outliers and non-conveyor frames
need explicit treatment before a real completion benchmark.

## Follow-up — Bonn real-data v1

`docs/bonn_real_v1_report.md` records the completed point-cloud-reference adapter
and a lab-only real-data experiment: eight training priors, three development
objects and twelve reserved local holdout objects from public validation. Only
55 MB of pinned compressed members were retrieved, all CRC/size/SHA verified.
No complete archive or gated potato dataset was downloaded.

71 tests passed before scoring. All 24 development and 72 holdout predictions
were valid; no ellipsoid solver reported nonconvergence. The two-option rule
selected ellipsoid regularization 0.15 before holdout retrieval. Source, prior,
selection and object IDs were frozen. Predictions were exported before reference
geometry was opened. Both raw input and a fixed depth-component filter were
reported; reference mesh/physical volume errors are unavailable.

Filtered holdout Chamfer/F5 were population 5.1798 mm/0.5945, fitted ellipsoid
4.6241/0.6294, training template 4.3029/0.6740. The full primary hypothesis did
not pass: Chamfer paired CI improved, while F5 CI crossed zero. Lab48 is a clear
regression, retained. Template superiority is descriptive. Filtering changed
little on these lab fruit, and no greenhouse/potato claim is established.

Holdout elapsed 19.94 CPU-machine wall seconds including evaluation/export.
77 earlier output JSONs were verified unchanged. Training priors and eight
development predictions reproduced bitwise; holdout was not rerun. Source and
compact evidence are archived for restoration. The next bounded milestone is
the final report/showcase and related-work positioning, with the earlier
synthetic negative results and real-data limitations explicit.

## Course report and local submission package

Presentation-only work consolidates the frozen evidence in `course/REPORT.md`
and the visually reviewed eight-page PDF under `output/pdf/`. The focused
primary-source review (`course/related_work.md`) distinguishes established
symmetry, implicit priors, robust local fitting, template deformation and weight
regression from the project's conditional intervention/failure-analysis claim.
It does not establish algorithmic novelty or potato generalization.

The self-contained offline showcase contains six fixed-family synthetic cases
with synchronized input/reference and prediction views. Its surface-error colors
are explicitly post-hoc display distances; numeric scores remain original saved
rows. All eighteen case/method views, reset and mobile layout were checked in an
isolated browser, with no page JavaScript errors or page network requests.

`dist/CSE527_CPU_Shape_Completion.zip` contains five top-level files: report,
showcase, README, manifest and nested reproduction ZIP. Three frozen source
snapshots are verified; raw real geometry and datasets are excluded. A fresh
extracted installation, using the cache without network access, passed all
71 tests and produced three valid completions on a new unscored analytic fixture
(seed 527131399). All 92 historical top-level output JSONs are unchanged. No
research holdout prediction or score was rerun. Checks/provenance are in
`course/evidence/`. No official rubric/template was supplied and no submission
or external upload has been made; course format and author details require
checking before submission. Stronger research claims still require new evidence.
