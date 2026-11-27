# Two-rescan policy for CoRe++ volume estimation

**Ellipsoid disagreement lost to all three baselines.** With two rescans, it raised the mean absolute volume error across the ten development potatoes to **31.99 mL**. That is **2.07 mL worse than center alone**, **2.36 mL worse than random selection**, and **2.13 mL worse than selecting by size**.

| Policy | Rescan pair | Mean absolute error (mL) | Change vs center (mL) |
|---|---|---:|---:|
| Center alone | None | 29.92 | 0.00 |
| Ellipsoid disagreement | 5R3-1, 3R2-10 | 31.99 | +2.07 |
| Uniform random | Exact average over 45 pairs | 29.63 | −0.29 |
| Largest center estimates | 3R2-10, 3R5-2 | 29.86 | −0.06 |
| Hindsight oracle | 3R5-2, R10-1 | 26.32 | −3.61 |

The oracle shows that the best pair available among these archived frames could have lowered the cohort mean error by **3.61 mL**. It uses the observed drainage errors to pick the pair. [All 45 pairs](rescan_pairs.csv) · [Machine-readable summary](results.json)

## Per-potato results

Positive rescan gain means the archived average of both frame estimates was closer to the drainage measurement than center alone. All volumes, disagreements, errors and gains are in mL.

| Potato | Center frame | Ellipsoid volume | Center volume | Disagreement | Rank | Flagged | Center error | Two-frame error | Rescan gain |
|---|---:|---:|---:|---:|---:|:---:|---:|---:|---:|
| 5R3-1 | 360 | 267.30 | 90.68 | 176.62 | 1 | Yes | 30.68 | 26.28 | +4.40 |
| 3R2-10 | 367 | 258.77 | 356.01 | 97.24 | 2 | Yes | 46.01 | 71.11 | −25.10 |
| R12-7 | 353 | 217.61 | 266.77 | 49.15 | 3 | No | 16.77 | 23.87 | −7.11 |
| 2R2-6 | 358 | 117.88 | 144.93 | 27.05 | 4 | No | 39.93 | 37.61 | +2.32 |
| R4-10 | 352 | 68.56 | 91.12 | 22.56 | 5 | No | 1.12 | 1.96 | −0.84 |
| 2R3-10 | 363 | 129.74 | 151.30 | 21.56 | 6 | No | 68.70 | 66.76 | +1.95 |
| R10-1 | 362 | 183.73 | 162.40 | 21.33 | 7 | No | 37.60 | 27.27 | +10.32 |
| R8-2 | 350 | 60.35 | 73.23 | 12.88 | 8 | No | 18.23 | 17.33 | +0.89 |
| 5R1-4 | 362 | 195.27 | 185.57 | 9.69 | 9 | No | 14.43 | 12.55 | +1.88 |
| 3R5-2 | 359 | 297.74 | 294.23 | 3.51 | 10 | No | 25.77 | 0.04 | +25.73 |

Averaging helped the highest-ranked potato, 5R3-1, by 4.40 mL, but hurt the other flagged potato, 3R2-10, by 25.10 mL. The smallest disagreement belonged to 3R5-2, which had the largest rescan gain. 2R3-10 had the largest center-only error, 68.70 mL, and the rescan reduced it by just 1.95 mL. First-frame disagreement, first-frame error and rescan gain led to different decisions on these potatoes. [Full-precision per-potato table](per_potato.csv)

## Frozen method and verification

This is exploratory because the ten outcomes were previously studied. The first stage verified the released partial PLY for each registered center frame, loaded the coordinates in millimeters and set belt height to zero at a nominal camera depth of 350 mm. The full point cloud went through the existing CPU ellipsoid with default settings. The score was the absolute difference between its mesh volume and the archived center-frame CoRe++ volume. Failed fits had first priority, and ties used ascending object ID. All ten fits succeeded. The ranking and both deterministic pairs were saved before the second-frame and drainage values were joined. [Protocol](../corepp_volume_rescan_protocol.md) · [Frozen first-frame scores and input hashes](frozen_selection.json) · [Archived two-frame study](../corepp_two_frame_volume/report.md)

Each two-rescan policy used the archived two-frame average for its selected pair and center alone for the other eight. The two stages reproduced byte-for-byte from a new output directory. The random expectation was also checked using each potato's 2-in-10 inclusion probability. This comparison used the archived neural predictions, kept the fresh cohorts closed and ended with the frozen rule.

## Reproduce

From the repository root, with the project's Python environment and local release archives in place, run:

```bash
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
rescan_output=$(mktemp -d)
.venv/bin/python -m studies.regional_shape_v1.corepp_volume_rescan select --out "$rescan_output" &&
.venv/bin/python -m studies.regional_shape_v1.corepp_volume_rescan evaluate --out "$rescan_output"
```
