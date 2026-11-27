# One peel click through SAM 2 and RAFT fusion

- **Completion.** SAM 2-mask RAFT fusion produced a cloud on **10/10 geometry** and **30/30 trait** development potatoes. Every center replay is accounted for below.
- **Surface.** Among **10/10** geometry pairs, SAM 2 fusion covered **41.14%** of the SfM surface within 2 mm versus **40.79%** with provided-mask fusion. The change was **+0.34 percentage points** (95% interval **+0.001 to +0.697**). At equal point count it was **+0.29 points** (**-0.02 to +0.62**). Far points changed by **+0.31 points** (**-0.17 to +0.77**).
- **Traits.** Weight, the primary comparison. Fusion MAE was 14.27 g versus 14.78 g at center on 30/30 paired potatoes, a change of -0.51 g (95% interval -1.52 to +0.37 g). The interval includes zero. Water-displacement volume. Fusion MAE was 15.14 mL versus 15.28 mL at center on 30/30 paired potatoes, a change of -0.14 mL (95% interval -1.10 to +0.71 mL). The interval includes zero.

[Per-potato geometry](geometry_per_potato.csv) · [Per-potato traits](traits_per_potato.csv) · [Full-precision results](results.json)

## Frozen inputs and end-to-end replay

The **40 previously studied development potatoes** used the exact coached repeat clicks and the same lower, center and upper frames as the two fusion studies. The ten geometry IDs were held separate from the remaining 30 trait IDs throughout. All 45 SAM 2 confirmation potatoes and reserved cohorts remained closed. [Roster and trait coefficients](frame_manifest.json) · [Frozen protocol](protocol.md) · [Coached repeat](../sam2_human_prompt_v1/repeat_01/report.md)

The extended-clip probe changed archived center masks by 7 pixels on R6-5 and by 2 pixels on 3R3-8. SAM 2 normalizes object-pointer time offsets using the declared clip length up to its pointer cap. We therefore kept the original length through center, then continued the same in-memory track over the later frames. That retained the same click, checkpoint, preprocessing and state. The final run reproduced **40/40** archived center masks pixel for pixel and returned tracks through upper on **40/40**, with **0** skips. The post-reconstruction audit found **40/40** correct upper masks by IoU ≥ 0.5, **0** tracks with empty frames, **0** target losses and **0** pin takeovers after first matching the potato. [Center replay](tracking_replay.csv) · [State transitions](tracking_audit.csv) · [Frame-by-frame audit](tracking_by_frame.csv)

The first reconstruction attempt stopped on the named entry-prompt array. The corrected reader preserved the frozen inputs and verified tracking outputs. [Reader correction receipt](mask_reader_correction.json)


The predicted-mask arm derived each histogram depth gate and RAFT crop from the propagated mask and recomputed all bidirectional flow and adjacent rigid fits. Its inputs were the propagated masks, original full-scene RGB and raw depth, released intrinsics, and measured tuber thickness (`x3_depth_mm`). Both mask arms retain the measured-thickness dependency. Provided masks, segmented PLYs and provided-mask poses were used for the separate baseline replay or audit. Only the three selected clouds contributed fused points. [Input ledger](predicted_input_ledger.json) · [Depth support](depth_support_by_frame.csv) · [Per-link RAFT results](registration_links.csv)

## Surface scoring on the ten geometry potatoes

The geometry comparison used the same released center-to-SfM pose in every arm, on the scoring side only, and the archived 1 mm scoring voxel grid, 50,000 area-uniform reference samples, 2 mm cutoff and ten equal-count repeats. The provided center and RAFT baselines replayed archived point clouds, full-count scores and original equal-count scores on **10/10**. The new equal-count comparison uses the smallest available cloud across these four conditions per potato. The SAM 2-fused arm scored against SfM on **10/10**. [Archived geometry study](../raft_fusion_geometry_v1/report.md) · [Geometry table](geometry_per_potato.csv)

| Arm | Coverage scored | Reference covered | Covered at equal count | Output points >2 mm |
|---|---:|---:|---:|---:|
| A | 10/10 | 36.31% | 36.31% | 3.99% |
| B | 10/10 | 36.63% | 36.62% | 4.31% |
| C | 10/10 | 40.79% | 40.32% | 5.54% |
| D | 10/10 | 41.14% | 40.61% | 5.85% |

| Geometry comparison | Metric | Pairs | Change (percentage points) | 95% interval |
|---|---|---:|---:|---:|
| D − B | Coverage | 10/10 | +4.50 | +3.71 to +5.33 |
| D − B | Far points | 10/10 | +1.54 | +0.92 to +2.23 |
| D − B | Equal-count coverage | 10/10 | +3.99 | +3.27 to +4.77 |
| D − C | Coverage | 10/10 | +0.34 | +0.001 to +0.697 |
| D − C | Far points | 10/10 | +0.31 | -0.17 to +0.77 |
| D − C | Equal-count coverage | 10/10 | +0.29 | -0.02 to +0.62 |
| B − A | Coverage | 10/10 | +0.33 | +0.04 to +0.58 |
| B − A | Far points | 10/10 | +0.31 | +0.08 to +0.61 |
| B − A | Equal-count coverage | 10/10 | +0.31 | +0.03 to +0.56 |

The intervals resample whole potatoes within each comparable pair set, using unrounded errors and coverage. Relative to its own center, SAM 2 fusion newly covered 583.04 mm² and lost 2.64 mm² on average. With provided masks, fusion newly covered 606.34 mm² and lost 3.15 mm² relative to its corresponding center. [Per-potato new and lost area](geometry_per_potato.csv)

## Weight and volume on the 30 trait potatoes

A and B used the frozen center coefficients, and C and D used the frozen RAFT coefficients from the 117 common training potatoes. There was no refit. Center features used raw accepted points and fused features used 1 mm voxel centroids in the center camera. Both used XY hull area times the belt-relative height proxy. Archived provided-mask weight and volume predictions replayed within 1e-7 of their stored values before outcomes were joined. Measured weight includes the tack. [Earlier trait comparison](../raft_fusion_traits_v1/report.md) · [Predictions before outcome join](predictions_before_targets.json)

| Arm | Weight scored and MAE | Volume scored and MAE |
|---|---:|---:|
| A · Provided center | 30/30 · 15.41 g | 30/30 · 15.63 mL |
| B · SAM 2 center | 30/30 · 14.78 g | 30/30 · 15.28 mL |
| C · Provided RAFT fusion | 30/30 · 15.17 g | 30/30 · 15.44 mL |
| D · SAM 2 RAFT fusion | 30/30 · 14.27 g | 30/30 · 15.14 mL |

| Trait | Comparison | Pairs | First MAE | Baseline MAE | Paired change | 95% interval | Wins / ties / losses |
|---|---|---:|---:|---:|---:|---:|---:|
| Weight | D − B | 30/30 | 14.27 g | 14.78 g | -0.51 g | -1.52 to +0.37 g | 20 / 0 / 10 |
| Weight | D − C | 30/30 | 14.27 g | 15.17 g | -0.90 g | -1.59 to -0.20 g | 19 / 0 / 11 |
| Weight | B − A | 30/30 | 14.78 g | 15.41 g | -0.63 g | -1.70 to +0.53 g | 19 / 0 / 11 |
| Volume | D − B | 30/30 | 15.14 mL | 15.28 mL | -0.14 mL | -1.10 to +0.71 mL | 16 / 0 / 14 |
| Volume | D − C | 30/30 | 15.14 mL | 15.44 mL | -0.30 mL | -1.11 to +0.49 mL | 15 / 0 / 15 |
| Volume | B − A | 30/30 | 15.28 mL | 15.63 mL | -0.35 mL | -1.45 to +0.79 mL | 18 / 0 / 12 |

Paired estimates use only the indicated complete pairs, with the cohort denominator shown separately. Negative change is lower absolute error. Both suites use the frozen 10,000-draw tuber bootstrap. No center fallback was used. Available fusion predictions constitute the primary D result.

Replacing the provided masks throughout fusion reduced observed weight MAE by 0.90 g on these 30 potatoes (SAM 2 minus provided, 95% interval -1.59 to -0.20 g). The corresponding volume change was -0.30 mL (-1.11 to +0.49 mL). These comparisons isolate the mask source within fusion. The weight and volume intervals for fusion versus center from the same click both include zero.

## Failures and incremental CPU runtime

No mask-depth support, registration or scoring failures occurred.

The table sums timed local CPU-process wall components across potatoes. Tracking used two concurrent processes. The time through center includes initial loading of the full RGB clip, so the post-center increment excludes extra clip loading already counted there. It includes additional support reconstruction, RAFT and fused feature work. Model setup, scoring and file writes are reported separately in the result ledgers. The archived provided-mask RAFT increment over its center baseline on 30 trait potatoes was 110.37 s, with its original runtime accounting. [Per-potato runtime](runtime_by_potato.csv) · [Failures](failures.csv) · [Archived trait runtime](../raft_fusion_traits_v1/report.md#incremental-cpu-time)

| Cohort | Tracking through center (s) | Extra tracking through upper (s) | Additional depth, RGB, RAFT and fused feature (s) | Total increment D over B (s) |
|---|---:|---:|---:|---:|
| Geometry (10) | 257.69 | 131.40 | 32.15 | 163.54 |
| Traits (30) | 784.15 | 409.48 | 103.79 | 513.26 |
| All (40) | 1041.85 | 540.87 | 135.93 | 676.81 |

This development comparison measures replacement of the mask source throughout a frozen RGB-D fusion pipeline on the coached repeat's clicks. Performance with another operator, other acquisition groups, or a thickness-free filter remains unmeasured.

## Reproduce

From the workspace root, use a fresh copy with this study's scripts and protocol, plus the archived local RGB-D, geometry, checkpoints, calibration and CPU environment.

```bash
sh studies/sam2_raft_end_to_end_v1/reproduce.sh
```
