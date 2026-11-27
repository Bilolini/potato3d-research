# Scan-only support-plane offset on the development cohort

**Ready for Astra to interpret.** The correctly matched scan-only shifts reduced mean underside MAE from **5.5121 to 4.1069 mm**, a gain of **1.4052 mm**. The mean shuffled assignment scored **6.0959 mm**. The gain over the body survived every single-tuber omission, so the proxy met the protocol's development criterion for considering a fresh-cohort test. [Protocol](support_offset_protocol.md)

## Per-tuber comparison

Seven of the original 12 tubers, 10 bands, and 12,202 common cells were evaluable. The original baseline replay matched the archived file byte for byte. The 36 replication tubers stayed closed.

All measurements below are in mm. Positive shifts move the underside prediction upward. Negative changes favor the scan-only shift. The best shift comes from the earlier reference-based diagnostic. The last column gives the mean paired change when the row's tuber is omitted.

| Tuber | Bands | Scored cells | Scan-only shift | Archived best shift | Body MAE | Shifted MAE | Paired change | Mean if omitted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2R1-10 | 1/2 | 1,699 | −4.6236 | −7.6264 | 7.6704 | 3.6013 | −4.0691 | −0.9612 |
| 2R2-6 | 2/2 | 1,636 | +0.9071 | −1.4062 | 2.3962 | 3.0298 | +0.6337 | −1.7450 |
| 2R3-10 | 0/2 | 0 | +4.0660 | — | — | — | — | — |
| 3R2-10 | 2/2 | 2,937 | −5.1050 | −5.1853 | 5.7538 | 2.9136 | −2.8402 | −1.1660 |
| 3R5-2 | 1/2 | 1,720 | −3.4217 | −0.3557 | 4.7272 | 5.1483 | +0.4211 | −1.7096 |
| 5R1-4 | 1/2 | 892 | +5.1378 | +5.4921 | 8.8633 | 5.3655 | −3.4978 | −1.0564 |
| 5R2-3 | 0/2 | 0 | −1.4827 | — | — | — | — | — |
| 5R3-1 | 0/2 | 0 | +7.8301 | — | — | — | — | — |
| R10-1 | 2/2 | 1,867 | −0.0129 | +0.3381 | 5.5465 | 5.5469 | +0.0003 | −1.6395 |
| R12-7 | 1/2 | 1,451 | +1.1015 | +2.8363 | 3.6273 | 3.1429 | −0.4844 | −1.5587 |
| R4-10 | 0/2 | 0 | −0.5317 | — | — | — | — | — |
| R8-2 | 0/2 | 0 | +1.3899 | — | — | — | — | — |
| **Equal-tuber mean** | **10/24** | **12,202** | | | **5.5121** | **4.1069** | **−1.4052** | |

Four of seven tubers improved. The smallest worsening was 0.0003 mm on R10-1. The omission means ranged from **−1.7450 to −0.9612 mm**. The 2R2-6 proxy shift had the opposite sign to its reference-fitted shift. The 3R5-2 proxy shifted downward by about 3.07 mm more than its reference-fitted shift.

## Shuffled control

All **5,040** one-to-one assignments of the seven saved shifts were evaluated, including the correct assignment. Each assignment used the original support and equal-tuber weighting. The correctly matched mean was **1.9890 mm lower** than the average assignment.

| Assignment statistic | Result |
| --- | ---: |
| Correctly matched MAE | 4.1069 mm |
| Mean of all assignments | 6.0959 mm |
| Minimum / median / maximum | 3.9527 / 6.1036 / 7.8310 mm |
| Rank from lowest error | 25 of 5,040 |
| Better / tied / worse than correct matching | 24 / 1 / 5,015 |

About **0.50%** of assignments scored at or below correct matching. The rank is descriptive because acquisition groups can share imaging conditions.

## Prediction provenance and replay

The prediction phase staged the 12 registered PLYs and their named RGB and depth images. It read registration metadata to verify frame identity. Every PLY point fell inside the corresponding target alpha mask, and the largest discrepancy with a released depth pixel was 0.000015 mm. This checks the loading units and frame correspondence.

The unchanged background-plane estimator fitted all 12 frames with its original defaults. There were **zero** zero-shift fallbacks. Tilt ranged from **1.13° to 2.19°** and held-out candidate support within 1.5 mm ranged from **21.7% to 46.5%**. This pixel-level check measures fit support. The fitted plane remains a proxy for the physical surface supporting the tuber. [Calibration audit](../../docs/calibration_followup.md)

The footprint center came from the original body fit on the visible scan. The conversion negated belt Y to obtain camera Y, then computed 350 mm minus local plane depth. Analytic checks gave 0 mm for a plane at 350 mm and −3 mm at 353 mm, and verified the Y sign on a tilted plane. The prediction phase saved the named input hashes, plane fit support and shifts before any reference scoring. The scoring phase linked the saved file by SHA-256 and used the original masks and weighting. Only the lower heights received the translation. [Frozen predictions](support_offset_predictions.json) · [Per-tuber and shuffled results](support_offset_results.json)

All 99 tests passed.

```sh
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
.venv/bin/python -m studies.regional_shape_v1.support_offset predict \
  --source data/raw/3DPotatoTwin
.venv/bin/python -m studies.regional_shape_v1.support_offset score \
  --source data/raw/3DPotatoTwin
```
