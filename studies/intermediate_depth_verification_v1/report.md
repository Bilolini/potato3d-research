# Can an intermediate depth view check previously unobservable fusion points?

**The intermediate views recovered usable depth for 7,816 of 12,144 points (64.36%).** A total of **7,619 (62.74%)** could be classified as agreement or contradiction, with **197** potentially occluded. Giving each potato equal weight, the corresponding rates were **62.08%** with usable depth and **60.63%** with agreement or contradiction. All ten potatoes contributed. [Per-potato table](per_potato.csv) · [Detailed results](results.json)

**Contradiction was more error-prone on average, with reversals across potatoes.** On the nine potatoes with both categories, the equal-potato error rate was **39.44%** for contradiction and **17.32%** for agreement, a paired difference of **+22.13 percentage points**. Contradiction had a higher rate on **6/9**, a lower rate on **3/9**, and tied on none. 3R7-10 supplied no contradictions. Of all 567 contradictions, 333 still lay within 2 mm of SfM. The average separation warrants attention, but the per-potato reversals and the number of accurate contradictions favor retaining the uncertainty flag over selective removal on this evidence. [Category and paired counts](results.json)

## Frame choices and freeze

For each outer source we selected the adjacent archived capture toward the center. All twenty selected intermediate frames lie strictly between source and center and contributed no points to the archived fusion. Their SAM 2 masks and depth support replayed, as did the original score arrays and the exact fused indices of all 12,144 previously uncheckable raw points. We used one adjacent RAFT link for each comparison, including its inverse for the upper source, and replayed that relative pose by composition through center. [Frozen frame choices](frozen_frames.json) · [Archived capture order](../sam2_raft_end_to_end_v1/frame_manifest.json)

The original formula, combining both depth-scatter scales and the adjacent link's inlier RMSE, gave tolerances of **2.03–2.56 mm**. A valid comparison required all four surrounding depths. Points clearly in front of all four depths were contradictions. Points clearly behind all four could be occluded. Other valid projections were consistent with the measured depth envelope. We froze those classifications and checked their hashes before joining the archived SfM labels by raw fused-point index. The intermediates participated in pose estimation and supply additional depth evidence. SfM supplies the independent accuracy check at the archived alignment. All rates below use **raw outer-view points** and the strict **greater-than-2 mm** label. Fused-voxel metrics were not recomputed. The depth support retains the archived measured-thickness dependency. [Protocol](protocol.md) · [Classification freeze](frozen_classifications.json) · [Archived raw-label diagnostic](../depth_consistency_diagnostic_v1/report.md)

## Error rates by category

| Category | Raw points | Inaccurate points | Pooled error rate | Equal-potato error rate | Potatoes with category |
| --- | ---: | ---: | ---: | ---: | ---: |
| Consistent | 7,052 | 1,131 | 16.04% | 18.20% | 10 |
| Contradiction | 567 | 234 | 41.27% | 39.44% | 9 |
| Potentially occluded | 197 | 11 | 5.58% | 12.35% | 9 |
| Still unobservable | 4,328 | 1,291 | 29.83% | 28.72% | 10 |

In the table below, category cells show **point count (SfM error rate)**. Empty categories have no rate. The observed column includes potentially occluded points. Fused point membership and labels joined successfully for all ten potatoes.

| Potato | Lower source → intermediate | Upper source → intermediate | Usable depth / total | Consistent | Contradiction | Potentially occluded | Still unobservable |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 4R4-8 | 196 → 218 | 495 → 473 | 879/1,317 (66.7%) | 778 (16.8%) | 11 (81.8%) | 90 (11.1%) | 438 (58.9%) |
| 3R7-10 | 214 → 230 | 521 → 504 | 264/471 (56.1%) | 264 (26.1%) | 0 (—) | 0 (—) | 207 (21.3%) |
| 2R1-9 | 231 → 252 | 501 → 480 | 316/935 (33.8%) | 275 (31.6%) | 39 (0.0%) | 2 (0.0%) | 619 (25.0%) |
| R1-3 | 231 → 252 | 505 → 484 | 906/1,375 (65.9%) | 865 (15.5%) | 32 (3.1%) | 9 (0.0%) | 469 (35.8%) |
| R9-2 | 220 → 238 | 503 → 482 | 362/687 (52.7%) | 324 (1.2%) | 33 (30.3%) | 5 (0.0%) | 325 (19.1%) |
| 4R4-10 | 216 → 235 | 495 → 474 | 666/956 (69.7%) | 495 (41.2%) | 170 (21.2%) | 1 (100.0%) | 290 (54.5%) |
| 4R6-7 | 237 → 261 | 465 → 443 | 1,104/1,826 (60.5%) | 1,047 (15.4%) | 8 (50.0%) | 49 (0.0%) | 722 (31.3%) |
| 4R8-8 | 220 → 240 | 479 → 460 | 933/1,176 (79.3%) | 889 (0.4%) | 13 (7.7%) | 31 (0.0%) | 243 (2.5%) |
| R11-5 | 245 → 266 | 507 → 486 | 1,686/2,272 (74.2%) | 1,457 (14.5%) | 225 (60.9%) | 4 (0.0%) | 586 (30.2%) |
| R10-10 | 222 → 241 | 497 → 478 | 700/1,129 (62.0%) | 658 (19.1%) | 36 (100.0%) | 6 (0.0%) | 429 (8.6%) |

On **2R1-9**, none of the **39** contradictions were inaccurate, versus **87/275** points that agreed. On **R10-10**, all **36** contradictions were inaccurate, versus **126/658** points that agreed. These differences show why the pooled category rates are insufficient for a removal decision.

## Reproduce

Run from the workspace root with the frozen depth, mask, RAFT and diagnostic artifacts. The first phase seals the classifications. The second reads the archived error labels.

```sh
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
export DYLD_LIBRARY_PATH="$PWD/outputs/corepp_cpu_audit/runtime/libusb/1.0.30/lib"
intermediate_out=$(mktemp -d)
intermediate_python=outputs/corepp_cpu_audit/venv/bin/python
intermediate_script=studies/intermediate_depth_verification_v1/run.py
"$intermediate_python" "$intermediate_script" freeze --out "$intermediate_out" &&
"$intermediate_python" "$intermediate_script" evaluate --out "$intermediate_out"
```

[Runner](run.py)
