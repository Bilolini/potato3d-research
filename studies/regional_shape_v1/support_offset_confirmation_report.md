# Scan-only support-plane correction on the frozen confirmation cohort

**Confirmation remains unresolved.** On 24 of 36 selected tubers, the fixed correction reduced equal-tuber underside MAE from **5.0068 to 4.7451 mm**, a paired change of **−0.2617 mm**. Both cultivar-stratified 95% intervals include zero. The median paired change was **−0.2016 mm**, with 16 wins, zero ties, and eight losses. [Confirmation protocol](support_offset_confirmation_protocol.md)

| Resampling unit | 95% percentile interval (mm) |
| --- | ---: |
| Tuber | −0.8290 to +0.2984 |
| Whole acquisition group | −0.8467 to +0.2947 |

Both intervals used 10,000 replicates and seed 5272101. The tuber bootstrap retained the observed measurable tuber count within each cultivar. The group bootstrap drew the observed number of measurable acquisition groups within each cultivar, kept all measurable tubers in each sampled group, and computed the equal-tuber mean of the drawn sample. Both cultivars were represented. Corolle had three measurable acquisition groups and Sayaka had ten, so the Corolle group count is sparse. The intervals describe this measurable population and acquisition setting.

## Coverage and failures

All 36 fresh scan-only predictions were saved. Every footprint and background-plane fit succeeded, with zero fallbacks. All released RGB-D pairs passed frame and raster intake. One tuber, 5R1-3, had scan points below the nominal belt plane and failed the existing registered-geometry check. Eleven more had no band that met sector coverage. The selected denominator remained 36.

| Cultivar | Measurable tubers | Passing bands | Scored cells | Body MAE (mm) | Corrected MAE (mm) | Paired change (mm) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Corolle | 8/12 | 10/24 | 9,770 | 5.7606 | 5.9514 | +0.1908 |
| Sayaka | 16/24 | 21/48 | 26,287 | 4.6300 | 4.1420 | −0.4880 |
| **Total** | 24/36 | 31/72 | 36,057 | 5.0068 | 4.7451 | −0.2617 |

The inner band passed for 9 of 36 selected tubers and the outer band for 22 of 36. The JSON gives the per-sector denominators and failure flags.

## Within-acquisition-group control

The control covered **9 groups and 20 measurable tubers**. Correctly matched shifts scored **5.0284 mm** on this subset. The exact expected within-group reassignment MAE was **5.1553 mm**, a difference of **−0.1269 mm** in favor of correct matching. Every measurable tuber was scored with every shift from its own group, including its own. Group eligibility required two measurable tubers, and each contributing tuber had equal weight in the control means. This is a descriptive measure of frame matching within shared acquisition conditions.

| Cultivar | Group | Tubers | Matched MAE (mm) | Expected reassignment MAE (mm) | Difference (mm) |
| --- | --- | ---: | ---: | ---: | ---: |
| Corolle | 20230922_barn_okadasan_sarabetsu_01 | 2 | 5.6418 | 5.7884 | −0.1466 |
| Corolle | 20230922_barn_okadasan_sarabetsu_02 | 3 | 6.9821 | 6.2869 | +0.6952 |
| Corolle | 20230922_barn_okadasan_sarabetsu_03 | 3 | 5.1270 | 5.5466 | −0.4196 |
| Sayaka | 20230914_field_okadasan_sarabetsu_05 | 2 | 2.9612 | 4.4952 | −1.5340 |
| Sayaka | 20230921_field_okadasan_sarabetsu_04 | 2 | 4.8727 | 5.0406 | −0.1679 |
| Sayaka | 20230921_field_okadasan_sarabetsu_05 | 2 | 2.0918 | 2.2200 | −0.1282 |
| Sayaka | 20230921_field_okadasan_sarabetsu_06 | 2 | 4.3656 | 4.2524 | +0.1132 |
| Sayaka | 20230921_field_okadasan_sarabetsu_10 | 2 | 5.6140 | 5.4022 | +0.2119 |
| Sayaka | 20230921_field_okadasan_sarabetsu_11 | 2 | 6.5735 | 6.6041 | −0.0306 |

## Acquisition groups and omission effects

The point estimate remained negative after omitting any one measurable acquisition group, ranging from **−0.4565 to −0.0820 mm**. Omitting Sayaka group `20230921_field_okadasan_sarabetsu_04` moved the mean closest to zero. Its two tubers contributed about 71% of the net summed gain across the measurable cohort.

| Cultivar | Acquisition group | Measurable tubers | Passing bands | Scored cells | Mean change (mm) | Mean if group omitted (mm) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Corolle | 20230922_barn_okadasan_sarabetsu_01 | 2/4 | 2/8 | 1,977 | +1.8806 | −0.4565 |
| Corolle | 20230922_barn_okadasan_sarabetsu_02 | 3/4 | 4/8 | 3,604 | +0.5323 | −0.3751 |
| Corolle | 20230922_barn_okadasan_sarabetsu_03 | 3/4 | 4/8 | 4,189 | −1.2772 | −0.1166 |
| Sayaka | 20230914_field_okadasan_sarabetsu_02 | 1/2 | 2/4 | 2,356 | −0.7522 | −0.2404 |
| Sayaka | 20230914_field_okadasan_sarabetsu_03 | 1/2 | 1/4 | 562 | −0.3093 | −0.2596 |
| Sayaka | 20230914_field_okadasan_sarabetsu_04 | 1/2 | 2/4 | 2,908 | −0.0416 | −0.2713 |
| Sayaka | 20230914_field_okadasan_sarabetsu_05 | 2/2 | 3/4 | 2,010 | −1.1624 | −0.1798 |
| Sayaka | 20230921_field_okadasan_sarabetsu_03 | 0/2 | 0/4 | 0 | — | −0.2617 |
| Sayaka | 20230921_field_okadasan_sarabetsu_04 | 2/2 | 2/4 | 3,311 | −2.2386 | −0.0820 |
| Sayaka | 20230921_field_okadasan_sarabetsu_05 | 2/2 | 2/4 | 3,005 | −0.0725 | −0.2789 |
| Sayaka | 20230921_field_okadasan_sarabetsu_06 | 2/2 | 3/4 | 5,120 | −0.0204 | −0.2837 |
| Sayaka | 20230921_field_okadasan_sarabetsu_08 | 1/2 | 1/4 | 568 | −0.3665 | −0.2572 |
| Sayaka | 20230921_field_okadasan_sarabetsu_09 | 0/2 | 0/4 | 0 | — | −0.2617 |
| Sayaka | 20230921_field_okadasan_sarabetsu_10 | 2/2 | 3/4 | 3,987 | +0.4168 | −0.3234 |
| Sayaka | 20230921_field_okadasan_sarabetsu_11 | 2/2 | 2/4 | 2,460 | −0.0919 | −0.2771 |

## Per-tuber comparison

All heights and changes are in mm. Positive shifts move the lower prediction upward. Negative paired changes mean the correction lowered MAE.

| Tuber | Frame | Cultivar | Bands | Cells | Saved shift | Body MAE | Corrected MAE | Paired change | Exclusion |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 5R1-8 | 366 | Corolle | 1/2 | 1,021 | +5.0039 | 3.7467 | 7.8806 | +4.1339 |  |
| 5R2-8 | 364 | Corolle | 1/2 | 568 | −2.5134 | 8.3408 | 9.6690 | +1.3282 |  |
| 5R3-6 | 357 | Corolle | 1/2 | 835 | +1.7832 | 2.8958 | 4.0321 | +1.1363 |  |
| 5R1-7 | 351 | Corolle | 1/2 | 956 | −0.8691 | 3.7756 | 3.4030 | −0.3726 |  |
| 5R2-9 | 349 | Corolle | 1/2 | 1,236 | −1.3157 | 5.7299 | 4.8602 | −0.8697 |  |
| 5R3-4 | 368 | Corolle | 2/2 | 1,900 | −2.7477 | 11.3286 | 8.7078 | −2.6208 |  |
| 5R1-9 | 355 | Corolle | 0/2 | 0 | −3.0002 | — | — | — | Sector coverage |
| 5R2-1 | 355 | Corolle | 2/2 | 1,800 | +1.3532 | 5.2789 | 6.4172 | +1.1383 |  |
| 5R3-3 | 353 | Corolle | 1/2 | 1,454 | −5.0988 | 4.9882 | 2.6411 | −2.3471 |  |
| 5R1-3 | 350 | Corolle | 0/2 | 0 | +0.6490 | — | — | — | Below nominal belt plane |
| 5R2-4 | 363 | Corolle | 0/2 | 0 | +0.5849 | — | — | — | Sector coverage |
| 5R3-9 | 371 | Corolle | 0/2 | 0 | +4.8641 | — | — | — | Sector coverage |
| R2-8 | 369 | Sayaka | 0/2 | 0 | +2.1821 | — | — | — | Sector coverage |
| 4R1-10 | 361 | Sayaka | 0/2 | 0 | +2.4286 | — | — | — | Sector coverage |
| R5-6 | 357 | Sayaka | 1/2 | 562 | −1.0551 | 3.8392 | 3.5299 | −0.3093 |  |
| R10-2 | 360 | Sayaka | 2/2 | 2,908 | +0.3659 | 1.4636 | 1.4221 | −0.0416 |  |
| 4R9-2 | 356 | Sayaka | 1/2 | 1,063 | −0.0583 | 6.4255 | 6.4361 | +0.0106 |  |
| R13-6 | 370 | Sayaka | 1/2 | 624 | −1.7425 | 5.0200 | 3.4643 | −1.5557 |  |
| 3R1-6 | 368 | Sayaka | 0/2 | 0 | −3.4732 | — | — | — | Sector coverage |
| 4R5-2 | 357 | Sayaka | 1/2 | 1,396 | +0.8953 | 7.7737 | 8.6690 | +0.8953 |  |
| 3R6-4 | 359 | Sayaka | 1/2 | 1,172 | −1.2451 | 2.0023 | 1.8237 | −0.1786 |  |
| 4R4-6 | 358 | Sayaka | 0/2 | 0 | +0.9065 | — | — | — | Sector coverage |
| 3R5-5 | 355 | Sayaka | 1/2 | 1,654 | −3.7289 | 8.3788 | 5.0744 | −3.3045 |  |
| 3R7-3 | 365 | Sayaka | 2/2 | 2,970 | −0.8670 | 5.1101 | 4.9014 | −0.2087 |  |
| R2-6 | 358 | Sayaka | 2/2 | 2,356 | +1.2095 | 6.6091 | 5.8569 | −0.7522 |  |
| 4R2-8 | 364 | Sayaka | 1/2 | 568 | +1.9527 | 2.8720 | 2.5055 | −0.3665 |  |
| R9-8 | 357 | Sayaka | 0/2 | 0 | +0.5557 | — | — | — | Sector coverage |
| R11-8 | 367 | Sayaka | 0/2 | 0 | −0.4151 | — | — | — | Sector coverage |
| 4R8-1 | 353 | Sayaka | 1/2 | 1,397 | +0.5267 | 6.9054 | 6.7110 | −0.1944 |  |
| R13-1 | 358 | Sayaka | 2/2 | 1,386 | +2.5639 | 3.2270 | 2.4580 | −0.7690 |  |
| 3R2-5 | 353 | Sayaka | 0/2 | 0 | −4.1852 | — | — | — | Sector coverage |
| 4R5-10 | 356 | Sayaka | 2/2 | 2,591 | −0.3482 | 2.6207 | 2.5590 | −0.0617 |  |
| 3R6-7 | 350 | Sayaka | 1/2 | 1,833 | +0.4180 | 2.3262 | 2.3598 | +0.0336 |  |
| 4R3-7 | 367 | Sayaka | 0/2 | 0 | +2.0804 | — | — | — | Sector coverage |
| 3R4-2 | 352 | Sayaka | 1/2 | 1,657 | −2.0787 | 5.8438 | 4.6710 | −1.1728 |  |
| 3R7-1 | 358 | Sayaka | 1/2 | 2,150 | −2.8265 | 3.6620 | 3.8299 | +0.1679 |  |

## Replay and provenance

Development scan predictions and scoring replayed byte for byte against both archived files. The confirmation scoring adapter also reproduced every development tuber's archived coverage and both MAEs. The 36-object confirmation roster reproduced from release metadata, and input hashes matched the frozen inventory. Duplicate-content checks used the demo, development, and previous replication inventories.

The prediction phase saved all per-frame shifts, plane fits, failures, and scan, code, environment, and protocol hashes before accessing fresh SfM geometry. The exclusive attempt record was written before the reference archive opened. The result records the fresh reference archive and selected mesh hashes and links the prediction and attempt files by SHA-256. All 101 tests passed. [Frozen predictions](support_offset_confirmation_predictions.json) · [Single scoring attempt](support_offset_confirmation_attempt.json) · [Results JSON](support_offset_confirmation_results.json)

The run used these commands in order.

```sh
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
.venv/bin/python -m studies.regional_shape_v1.support_offset_confirmation predict --source data/raw/3DPotatoTwin
.venv/bin/python -m studies.regional_shape_v1.support_offset_confirmation score --source data/raw/3DPotatoTwin
```
