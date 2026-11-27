# Depth-consistency filtering of three-view potato fusion

**The filter preserved the extra surface and barely changed the far-point rate.** Averaged over the ten development potatoes, it retained **99.988%** of the reference surface newly recovered by fusion. The far-point fraction fell from **5.8454%** to **5.8145%**. Count-matched random deletion left **5.8449%**, so the filter's mean advantage was **0.0304 percentage points** (paired 95% interval for filtered minus random **−0.0701 to +0.0001 points**). This fixed rule offered little cleanup on these potatoes. [Per-potato data](per_potato.csv) · [Results and intervals](results.json)

## Frozen rule and replay

The ten geometry potatoes reused the exact SAM 2 masks, lower, center and upper frames, depth support and RAFT poses. Before opening the SfM meshes, all ten center and fused point arrays replayed exactly. Every raw center point was retained. Each outer point was projected into both other selected views. A view could reject it only when all four surrounding depth pixels were supported and the point lay farther in front of the closest of those depths than the frozen tolerance. Behind-surface, missing and unsupported observations caused no rejection. [Frozen protocol](protocol.md) · [Input hashes and decisions](frozen_filter.json) · [Archived SAM 2 fusion](../sam2_raft_end_to_end_v1/report.md#surface-scoring-on-the-ten-geometry-potatoes)

The tolerance was twice the root sum of squares of both views' depth-scatter scales and the registration term. The depth scales came from robust local stencil residuals and reached the **0.5 mm** floor on all 30 frames. The registration term combined saved per-link 3D inlier RMSEs along the source-to-target chain by root sum of squares. The resulting **3.99–7.48 mm** tolerances used RGB-D and registration inputs only. This approximation can miss correlated drift. It also exceeds the scoring cutoff, so a point can exceed 2 mm reference error without a detectable foreground contradiction. **12,144 of 325,701 added points (3.73%)** had no usable stencil in either other view. The filter rejected **252 added points (0.077%)**. [Uncertainty and per-view counts](frozen_filter.json)

## Surface results

All arms used the archived center-to-SfM transform, 1 mm voxel centroids and the same 50,000 reference samples for each potato. The center and unfiltered fusion scores replayed on **10/10**. The random control averaged 20 frozen draws per potato, each deleting the same raw point count as the filter from each outer view. Mean post-voxel point counts were 11,165.5 for fusion, 11,158.5 for filtering and 11,164.0 for random deletion.

| Arm | Reference covered within 2 mm | Output points farther than 2 mm | Newly covered beyond center (mm²) | Same new surface retained (mm²) | Retained share |
| --- | ---: | ---: | ---: | ---: | ---: |
| Center | 36.6338% | 4.3075% | 0.00 | 0.00 | 0.000% |
| Archived fusion | 41.1370% | 5.8454% | 583.04 | 583.04 | 100.000% |
| Filtered | 41.1364% | 5.8145% | 582.99 | 582.99 | 99.988% |
| Count-matched random | 41.1368% | 5.8449% | 583.02 | 583.01 | 99.994% |

The retained share uses only the samples originally covered by unfiltered fusion and missed by center. Each row of the summary averages potatoes equally. Filtering changed total coverage by **−0.0006 percentage points** relative to fusion and **−0.0004 points** relative to random deletion. Only R9-2 lost any of the original newly covered samples under filtering. The filtered far-point fraction was still **1.51 points** above center. There were no input, replay or scoring failures. [All random draws](random_repeats.csv)

| Potato | Raw added points removed | Coverage % (center / fusion / filtered / random) | Far points % (same order) | Original new surface (mm²) | Retained % (filtered / random) |
| --- | ---: | --- | --- | ---: | --- |
| 4R4-8 | 19 | 32.986 / 40.050 / 40.050 / 40.050 | 5.350 / 7.766 / 7.772 / 7.765 | 708.26 | 100.000 / 99.999 |
| 3R7-10 | 0 | 40.874 / 43.942 / 43.942 / 43.942 | 5.289 / 5.035 / 5.035 / 5.035 | 223.06 | 100.000 / 100.000 |
| 2R1-9 | 62 | 42.868 / 48.586 / 48.586 / 48.585 | 3.085 / 4.770 / 4.765 / 4.768 | 622.72 | 100.000 / 99.986 |
| R1-3 | 10 | 32.694 / 36.448 / 36.448 / 36.448 | 4.362 / 5.960 / 5.932 / 5.959 | 527.71 | 100.000 / 100.000 |
| R9-2 | 16 | 42.432 / 47.520 / 47.514 / 47.519 | 5.993 / 7.410 / 7.425 / 7.408 | 482.98 | 99.882 / 99.982 |
| 4R4-10 | 1 | 34.174 / 39.100 / 39.100 / 39.100 | 6.566 / 10.470 / 10.471 / 10.470 | 414.63 | 100.000 / 100.000 |
| 4R6-7 | 15 | 31.520 / 33.946 / 33.946 / 33.946 | 2.939 / 4.232 / 4.214 / 4.232 | 730.67 | 100.000 / 100.000 |
| 4R8-8 | 70 | 36.470 / 40.960 / 40.960 / 40.960 | 2.615 / 3.091 / 2.983 / 3.091 | 837.24 | 100.000 / 99.989 |
| R11-5 | 6 | 31.652 / 34.920 / 34.920 / 34.920 | 1.211 / 2.705 / 2.705 / 2.705 | 733.88 | 100.000 / 100.000 |
| R10-10 | 53 | 40.668 / 45.898 / 45.898 / 45.898 | 5.665 / 7.016 / 6.842 / 7.015 | 549.29 | 100.000 / 99.987 |

## Reproduce

Run from the workspace root with the archived SAM 2 and RAFT files, the same RGB-D and SfM release, and the archived CPU environment. The freeze command writes the decisions before the score command reads reference meshes.

```sh
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
export DYLD_LIBRARY_PATH="$PWD/outputs/corepp_cpu_audit/runtime/libusb/1.0.30/lib"
filter_run=$(mktemp -d)
filter_python=outputs/corepp_cpu_audit/venv/bin/python
filter_script=studies/depth_consistency_fusion_v1/run.py
"$filter_python" "$filter_script" freeze --out "$filter_run" &&
"$filter_python" "$filter_script" score --out "$filter_run"
```

[Runner](run.py)
