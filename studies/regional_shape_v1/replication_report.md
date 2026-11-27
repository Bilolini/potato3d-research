# Fixed quarter-strength regional reflection replication

**Ready for research review.** On the 28 evaluable tubers, fixed 0.25 reflection increased mean underside MAE from **5.3748 to 5.4338 mm**, a change of **+0.0590 mm**. The tuber and acquisition-group intervals both included zero. The replication did not meet the protocol's criterion for a mean accuracy gain. [Replication protocol](replication_protocol.md)

## Primary estimate and uncertainty

Negative changes favor aligned quarter-strength reflection. The median paired change was 0.0000 mm, with 11 wins, five ties, and 12 losses.

| Resampling unit | 95% percentile interval (mm) |
| --- | ---: |
| Tuber | −0.0156 to +0.1404 |
| Acquisition group | −0.0147 to +0.1498 |

Both intervals used 10,000 replicates and seed 5272101. The tuber bootstrap preserves the number of evaluable tubers per cultivar. The group bootstrap draws the observed number of evaluable groups per cultivar, retains all evaluable tubers in each drawn group, and divides the summed changes by the resulting tuber count in that replicate. The group count was sparse for Corolle, with three evaluable groups, and Sayaka contributed ten. Both cultivars were represented. The intervals describe measurable tubers in this acquisition setting.

Leaving out any single tuber with the weight fixed left a mean increase between +0.0353 and +0.0733 mm. Leaving out any one represented acquisition group left an increase between +0.0246 and +0.0762 mm. The lowest mean followed omission of the Sayaka group `20230914_field_okadasan_sarabetsu_04`.

## Coverage and failures

All 36 selected pairs were staged, passed the fresh RGB-D and released-registration overlap checks, and yielded body fits. All selected asset hashes passed the identity and duplicate checks. A band required at least 20 common scan and reference cells and at least 50% coverage in all eight sectors. The eight unevaluable tubers failed this rule in both bands. Across all 36 tubers, marker masking was the sole scan exclusion flag in the 69 sectors that failed coverage. The JSON records the individual sector counts and failed bands.

| Cultivar | Evaluable tubers | Passing bands | Scored cells |
| --- | ---: | ---: | ---: |
| Corolle | 11/12 | 14/24 | 14,222 |
| Sayaka | 17/24 | 18/48 | 20,367 |
| **Total** | 28/36 | 32/72 | 34,589 |

| Radial band | Nominal cells | Screened scan cells | Paired reference rays | Common before gate | Passing bands | Scored cells |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.25–0.50 | 23,847 | 19,548 | 23,847 | 19,548 | 5/36 | 4,261 |
| 0.50–0.75 | 39,756 | 37,876 | 39,694 | 37,862 | 27/36 | 30,328 |

## Per-tuber results

All errors and changes are in mm. The omission column gives the remaining mean paired change with the weight fixed. Rows with zero passing bands have no scores. Their failure column lists zero-based sector indices from the inner and outer bands.

| Tuber | Cultivar | Bands | Cells | Body | Aligned 0.25 | Change | Clipped q95 | Mean if omitted | Coverage failure, inner / outer |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 5R1-5 | Corolle | 2/2 | 3,517 | 6.2342 | 6.2247 | −0.0095 | 7.1012 | +0.0615 |  |
| 5R2-5 | Corolle | 1/2 | 1,298 | 4.7292 | 5.2915 | +0.5622 | 7.8496 | +0.0403 |  |
| 5R3-8 | Corolle | 1/2 | 873 | 5.9257 | 5.9255 | −0.0002 | 3.9818 | +0.0612 |  |
| 5R1-1 | Corolle | 1/2 | 1,088 | 3.3463 | 3.3146 | −0.0317 | 3.6594 | +0.0623 |  |
| 5R2-2 | Corolle | 1/2 | 956 | 0.9706 | 0.9212 | −0.0494 | 2.5026 | +0.0630 |  |
| 5R3-5 | Corolle | 1/2 | 733 | 1.3408 | 1.4192 | +0.0784 | 1.7877 | +0.0582 |  |
| 5R1-6 | Corolle | 1/2 | 593 | 3.1375 | 3.1375 | +0.0000 | 5.2232 | +0.0611 |  |
| 5R2-6 | Corolle | 1/2 | 747 | 2.5285 | 2.4114 | −0.1171 | 5.5555 | +0.0655 |  |
| 5R3-10 | Corolle | 2/2 | 1,835 | 6.3192 | 6.3872 | +0.0681 | 7.0225 | +0.0586 |  |
| 5R1-2 | Corolle | 2/2 | 1,904 | 10.0960 | 10.0960 | +0.0000 | 6.6520 | +0.0611 |  |
| 5R2-10 | Corolle | 0/2 | 0 | — | — | — | — | — | s5 / s5 |
| 5R3-7 | Corolle | 1/2 | 678 | 9.2658 | 9.2658 | +0.0000 | 7.7384 | +0.0611 |  |
| R3-6 | Sayaka | 0/2 | 0 | — | — | — | — | — | s2 / s2 |
| 4R2-4 | Sayaka | 1/2 | 1,693 | 12.8334 | 12.8334 | +0.0000 | 8.4049 | +0.0611 |  |
| R9-1 | Sayaka | 0/2 | 0 | — | — | — | — | — | s1, s2 / s1 |
| R10-3 | Sayaka | 1/2 | 993 | 8.9380 | 9.6358 | +0.6978 | 11.6814 | +0.0353 |  |
| 4R9-5 | Sayaka | 1/2 | 764 | 1.5486 | 2.0613 | +0.5127 | 4.2877 | +0.0422 |  |
| R13-7 | Sayaka | 1/2 | 1,295 | 3.7787 | 3.9284 | +0.1497 | 4.6299 | +0.0556 |  |
| 3R2-8 | Sayaka | 1/2 | 946 | 3.5281 | 3.5281 | +0.0000 | 4.7950 | +0.0611 |  |
| 4R6-8 | Sayaka | 1/2 | 1,416 | 2.1360 | 2.1690 | +0.0330 | 3.4783 | +0.0599 |  |
| 3R6-8 | Sayaka | 1/2 | 1,903 | 4.2788 | 4.0463 | −0.2325 | 3.9854 | +0.0698 |  |
| 4R3-3 | Sayaka | 0/2 | 0 | — | — | — | — | — | s1, s2 / s1 |
| 3R4-9 | Sayaka | 1/2 | 536 | 5.2435 | 4.9153 | −0.3282 | 3.7926 | +0.0733 |  |
| 3R7-4 | Sayaka | 0/2 | 0 | — | — | — | — | — | s1 / s1 |
| R3-4 | Sayaka | 1/2 | 1,436 | 2.7406 | 2.8467 | +0.1061 | 3.4865 | +0.0572 |  |
| 4R2-10 | Sayaka | 0/2 | 0 | — | — | — | — | — | s1 / s1 |
| R6-6 | Sayaka | 0/2 | 0 | — | — | — | — | — | s1, s2 / s1 |
| R10-5 | Sayaka | 2/2 | 2,268 | 2.1873 | 2.5007 | +0.3134 | 3.7217 | +0.0495 |  |
| 4R9-10 | Sayaka | 1/2 | 819 | 6.5375 | 6.5149 | −0.0227 | 5.6251 | +0.0620 |  |
| R12-1 | Sayaka | 1/2 | 803 | 4.9714 | 4.8695 | −0.1020 | 4.4268 | +0.0649 |  |
| 3R2-2 | Sayaka | 1/2 | 1,693 | 7.8656 | 7.8259 | −0.0397 | 8.3154 | +0.0626 |  |
| 4R6-3 | Sayaka | 1/2 | 460 | 11.1224 | 11.1224 | +0.0000 | 9.1277 | +0.0611 |  |
| 3R6-1 | Sayaka | 1/2 | 910 | 7.5726 | 7.5879 | +0.0154 | 7.5034 | +0.0606 |  |
| 4R3-9 | Sayaka | 0/2 | 0 | — | — | — | — | — | s7 / s7 |
| 3R4-4 | Sayaka | 1/2 | 1,503 | 5.9137 | 5.9130 | −0.0007 | 4.3444 | +0.0612 |  |
| 3R7-8 | Sayaka | 1/2 | 929 | 5.4041 | 5.4522 | +0.0481 | 5.1513 | +0.0594 |  |

## Acquisition groups

Group counts use the frozen selected denominator. Group means and omission diagnostics use the same fixed quarter weight.

| Cultivar | Acquisition group | Evaluable tubers | Passing bands | Scored cells | Mean change (mm) | Mean if omitted (mm) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Corolle | 20230922_barn_okadasan_sarabetsu_01 | 4/4 | 6/8 | 7,102 | −0.0103 | +0.0705 |
| Corolle | 20230922_barn_okadasan_sarabetsu_02 | 3/4 | 3/8 | 3,001 | +0.1319 | +0.0502 |
| Corolle | 20230922_barn_okadasan_sarabetsu_03 | 4/4 | 5/8 | 4,119 | +0.0366 | +0.0627 |
| Sayaka | 20230914_field_okadasan_sarabetsu_02 | 1/2 | 1/4 | 1,436 | +0.1061 | +0.0572 |
| Sayaka | 20230914_field_okadasan_sarabetsu_03 | 0/2 | 0/4 | 0 | — | — |
| Sayaka | 20230914_field_okadasan_sarabetsu_04 | 2/2 | 3/4 | 3,261 | +0.5056 | +0.0246 |
| Sayaka | 20230914_field_okadasan_sarabetsu_05 | 2/2 | 2/4 | 2,098 | +0.0239 | +0.0617 |
| Sayaka | 20230921_field_okadasan_sarabetsu_03 | 2/2 | 2/4 | 2,639 | −0.0199 | +0.0650 |
| Sayaka | 20230921_field_okadasan_sarabetsu_04 | 2/2 | 2/4 | 2,039 | −0.1644 | +0.0762 |
| Sayaka | 20230921_field_okadasan_sarabetsu_05 | 2/2 | 2/4 | 2,813 | −0.1086 | +0.0719 |
| Sayaka | 20230921_field_okadasan_sarabetsu_06 | 1/2 | 1/4 | 929 | +0.0481 | +0.0594 |
| Sayaka | 20230921_field_okadasan_sarabetsu_08 | 1/2 | 1/4 | 1,693 | +0.0000 | +0.0611 |
| Sayaka | 20230921_field_okadasan_sarabetsu_09 | 0/2 | 0/4 | 0 | — | — |
| Sayaka | 20230921_field_okadasan_sarabetsu_10 | 2/2 | 2/4 | 1,876 | +0.0165 | +0.0622 |
| Sayaka | 20230921_field_okadasan_sarabetsu_11 | 2/2 | 2/4 | 1,583 | +0.2450 | +0.0447 |

## Secondary controls and registration checks

The original clipped q95 mirror covered every scored cell. The seven shifted predictions used the same quarter weight as aligned reflection. The mean shifted error averages the seven MAEs. The neighboring shifts remain diagnostic.

| Prediction | Equal-tuber MAE (mm) |
| --- | ---: |
| Smooth body | 5.3748 |
| Aligned 0.25 | 5.4338 |
| Mean of seven shifts | 5.3992 |
| +1 sector shift | 5.4544 |
| −1 sector shift | 5.4210 |
| Clipped q95 mirror | 5.5654 |

The released nominal transforms gave paired reference rays on 100% of tested overlap cells for all 36 pairs. Per-tuber median absolute top disagreement ranged from 0.388 to 1.000 mm, with p95 from 1.259 to 3.063 mm. The eight probes used the original released lateral RMSE offsets and ±1° rotations around the scan centroid, with the nominal belt depth and scan masks fixed. All probes retained the same 28 tubers and 32 bands. The nominal and perturbed errors in each row use the same intersected support. Quarter-strength reflection increased MAE versus the body on each probe's aggregate.

| Probe | Scored cells | Lost cells | Aligned − body (mm) | Perturbed aligned − shifted mean (mm) | Perturbed +1 MAE (mm) | Perturbed −1 MAE (mm) | Perturbed clip MAE (mm) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Ray x − RMSE | 34,589 | 0 | +0.0590 → +0.0603 | +0.0359 | 5.4731 | 5.4460 | 5.6035 |
| Ray x + RMSE | 34,577 | 12 | +0.0590 → +0.0576 | +0.0335 | 5.4432 | 5.4009 | 5.5335 |
| Ray y − RMSE | 34,588 | 1 | +0.0590 → +0.0625 | +0.0361 | 5.4753 | 5.4361 | 5.5872 |
| Ray y + RMSE | 34,576 | 13 | +0.0590 → +0.0554 | +0.0322 | 5.4420 | 5.4138 | 5.5486 |
| Rotate x −1° | 34,586 | 3 | +0.0590 → +0.0624 | +0.0388 | 5.4445 | 5.4060 | 5.5532 |
| Rotate x +1° | 34,589 | 0 | +0.0590 → +0.0545 | +0.0301 | 5.4691 | 5.4397 | 5.5800 |
| Rotate y −1° | 34,589 | 0 | +0.0590 → +0.0601 | +0.0348 | 5.4201 | 5.3873 | 5.5399 |
| Rotate y +1° | 34,585 | 4 | +0.0590 → +0.0575 | +0.0338 | 5.4891 | 5.4543 | 5.5917 |

## Verification and provenance

Before opening replication outcomes, the development replay matched the archived result byte for byte. The adapter reproduced the zero- and full-weight endpoints, the saved quarter-weight error for each of the seven evaluable development tubers, and 112 matched probe/reference cases to within 10⁻¹² mm. The fixed cohort was independently rebuilt from release metadata and matched the protocol hash. The preflight file was written before replication scoring and records SHA-256 hashes for the protocol, cohort, source archives and selected members, scorer, and environment. The scorer then verified the staged hashes at intake. The original cohort and development artifacts were preserved. [Preflight and input hashes](replication_preflight.json)

The results file contains all 36 selected rows, per-band coverage and failure details, primary and secondary scores, bootstrap intervals, omission diagnostics, and per-tuber matched-support probe scores. [Results JSON](replication_results.json)

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
MPLCONFIGDIR="$PWD/.cache/matplotlib" \
  .venv/bin/python -m studies.regional_shape_v1.replication \
  --source data/raw/3DPotatoTwin
```
