# Does spaced-view fusion improve measured potato weight or volume?

**The extra surface did not establish an improvement in either physical measurement.** On the 30 evaluation potatoes, RAFT fusion lowered mean absolute weight error from **15.41 g to 15.17 g** relative to center alone. The paired change was **−0.24 g** (95% tuber-bootstrap interval **−1.33 to +0.70 g**). Drainage-volume MAE went from **15.63 to 15.44 mL**, with a paired change of **−0.19 mL** (95% interval **−1.23 to +0.72 mL**). All six paired intervals span zero. Averaging the three independent predictions gave the lowest observed volume MAE. [Frozen protocol](protocol.md) · [Full results](results.json)

## Frozen comparison

We enrolled the 118 archived training potatoes and the 30 development potatoes left after removing the ten geometry-pilot IDs. The evaluation potatoes were new to fusion and had already appeared in weight development. The 45 SAM 2 confirmation potatoes and the reserves stayed closed. The lower, center and upper frames came from the archived spaced triplets. The pilot’s frozen ICP and RAFT settings used 2,029 adjacent links to estimate motion. Only the three selected clouds contributed points to each fusion. [Frame manifest](frame_manifest.json) · [Geometry-pilot protocol](../raft_fusion_geometry_v1/protocol.md)

Fusion used RGB-D only and kept the points in the center-camera coordinate frame. Both fused outputs used the same 1 mm voxel grid. The single-view conditions used the archived unvoxelized clouds. All regressions used camera-XY hull area times the robust height proxy. A separate intercept and slope were fitted for each method and trait, using equal total weight per training potato. B assigned weight 1/3 to each training frame and averaged the three predictions at evaluation. The reference fields were `weight_g_inctack` in grams and drainage `volume_ml` in mL. The released depth support was constructed with measured thickness (`x3_depth_mm`), so these results apply with that dependency. Archive-verified single-frame proxy values were reused for 118 training centers and all 90 selected evaluation views. [Train-only fits](train_fit.json) · [Weight measurement](../multiframe_weight_v1/report.md) · [Drainage measurement](../regional_shape_v1/corepp_two_frame_volume/report.md)

## Error and coverage

All four methods were scorable on the same 30 potatoes for both traits. The table gives MAE on that common cohort.

| Method | Scorable per trait | Weight MAE (g) | Drainage-volume MAE (mL) |
|---|---:|---:|---:|
| A · Center alone | 30/30 | 15.41 | 15.63 |
| B · Average three predictions | 30/30 | 15.49 | 15.00 |
| C · ICP fusion | 30/30 | 15.33 | 15.01 |
| D · RAFT fusion | 30/30 | 15.17 | 15.44 |

Changes use unrounded paired absolute errors, with negative values favoring RAFT. Each interval uses 10,000 whole-potato bootstrap draws. [Per-potato results](per_potato.csv) · [Full-precision paired MAEs and IDs](results.json)

| Trait | Comparison | Pairs | Mean change | 95% interval | RAFT wins / ties / losses |
|---|---|---:|---:|---:|---:|
| Weight (g) | D − A, primary | 30/30 | −0.24 | −1.33 to +0.70 | 14 / 0 / 16 |
| Weight (g) | D − B | 30/30 | −0.32 | −1.15 to +0.52 | 19 / 0 / 11 |
| Weight (g) | D − C | 30/30 | −0.16 | −1.08 to +0.70 | 14 / 0 / 16 |
| Volume (mL) | D − A | 30/30 | −0.19 | −1.23 to +0.72 | 16 / 0 / 14 |
| Volume (mL) | D − B | 30/30 | +0.43 | −0.32 to +1.19 | 14 / 0 / 16 |
| Volume (mL) | D − C | 30/30 | +0.43 | −0.27 to +1.12 | 13 / 0 / 17 |

One training potato, `4R5-9`, had fewer than 40 valid RAFT RGB-D matches across its required 189-to-363 link. It was excluded from the common training pool, leaving **117/118 training potatoes** for every fit. There were no evaluation registration or scoring failures. [Failure log](failures.csv) · [Saved evaluation predictions before target join](predictions_before_targets.json)

## Incremental CPU time

These are sums of the relevant measured component times on the local CPU. They include the support checks and feature extraction for each method and exclude conveyor acquisition and process idle time. Model fitting took less than 0.01 s. The RAFT total includes dense flow, rigid fitting and fusion. [Timing components](results.json)

| Method | Training compute (s), 118 attempted | Evaluation compute (s), 30 attempted | Evaluation increase over A (s) |
|---|---:|---:|---:|
| A | 3.72 | 0.99 | — |
| B | 11.27 | 2.93 | 1.95 |
| C | 276.50 | 73.67 | 72.68 |
| D | 411.77 | 111.36 | 110.37 |

On this development comparison, the geometry pilot’s additional reference coverage did not translate into a clear accuracy gain from the fused area-height feature. [Geometry-pilot results](../raft_fusion_geometry_v1/report.md)

## Reproduce

From the workspace root with the released RGB-D archives and archived CPU environment, use a fresh study output for a clean run. The feature stage can resume verified per-potato records in `outputs/raft_fusion_traits_v1/features/`.

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
study=studies/raft_fusion_traits_v1
.venv/bin/python "$study/roster.py" &&
.venv/bin/python "$study/score.py" freeze &&
outputs/corepp_cpu_audit/venv/bin/python "$study/features.py" &&
.venv/bin/python "$study/score.py" fit &&
.venv/bin/python "$study/score.py" score
```
