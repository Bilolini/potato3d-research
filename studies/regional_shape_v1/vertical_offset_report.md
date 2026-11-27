# Development-only vertical offset diagnostic

**Ready for Astra to interpret.** The archived development baseline reproduced byte for byte. On the original seven measurable tubers, the best per-tuber constant shift reduced mean underside MAE from **5.5121 to 3.7382 mm**. Fitting the offset on alternating sectors and testing it on the other sectors gave **3.7523 mm**, a mean change of **−1.7598 mm**. All measurements came from the original development cohort. [Diagnostic protocol](replication_decision.md)

## Per-tuber results

The analysis retained 7 of 12 tubers, 10 of 24 bands, and 12,202 common scan and reference cells. A positive shift moves the body upward. A negative MAE change favors the shift. All results are in mm.

| Tuber | Passing bands | Scored cells | Fitted shift | Body MAE | Best achievable MAE | Held-out shifted MAE | Held-out change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2R1-10 | 1/2 | 1,699 | −7.6264 | 7.6704 | 2.9192 | 2.9523 | −4.7181 |
| 2R2-6 | 2/2 | 1,636 | −1.4062 | 2.3962 | 1.9451 | 1.9602 | −0.4359 |
| 2R3-10 | 0/2 | 0 | — | — | — | — | — |
| 3R2-10 | 2/2 | 2,937 | −5.1853 | 5.7538 | 2.9128 | 2.9195 | −2.8343 |
| 3R5-2 | 1/2 | 1,720 | −0.3557 | 4.7272 | 4.7212 | 4.7329 | +0.0057 |
| 5R1-4 | 1/2 | 892 | +5.4921 | 8.8633 | 5.3543 | 5.3846 | −3.4787 |
| 5R2-3 | 0/2 | 0 | — | — | — | — | — |
| 5R3-1 | 0/2 | 0 | — | — | — | — | — |
| R10-1 | 2/2 | 1,867 | +0.3381 | 5.5465 | 5.5430 | 5.5446 | −0.0019 |
| R12-7 | 1/2 | 1,451 | +2.8363 | 3.6273 | 2.7718 | 2.7722 | −0.8551 |
| R4-10 | 0/2 | 0 | — | — | — | — | — |
| R8-2 | 0/2 | 0 | — | — | — | — | — |
| **Equal-tuber mean** | **10/24** | **12,202** | | **5.5121** | **3.7382** | **3.7523** | **−1.7598** |

The five unscored tubers had no band meeting the archived coverage rule. Held-out performance was six wins, zero ties, and one loss, including a 0.0019 mm win for R10-1. Omitting each tuber in turn gave mean held-out changes from **−2.0540 to −1.2667 mm**. The endpoints came from omitting 3R5-2 and 2R1-10, respectively. The all-cell shift removed 1.7739 mm of mean error, about 32% of the body MAE.

## Method and verification

For each scored cell, the residual was the registered reference underside height minus the body's lower height. The weighted median gave each passing band equal weight, each sector equal weight within its band, and each cell equal weight within its sector. If an interval of shifts minimized MAE, the scorer used its midpoint. It added the fitted shift to the body's lower height. The best achievable column fits and scores the shift on the same cells.

For the transfer check, the scorer fitted the shift on the even-numbered sectors and compared it with the body on the identical odd-sector cells. It then reversed the split and averaged the two directions equally. The [results JSON](vertical_offset_results.json) gives each direction's shift, cell counts, and errors, plus per-tuber omission effects. Held-out transfer still uses reference heights from the same tuber. The fitted shifts alone cannot identify their physical cause.

Analytic checks recovered known positive and negative constant shifts, returned zero for symmetric residuals, and verified the weighting and parity splits. All 94 project and study tests passed.

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
MPLCONFIGDIR="$PWD/.cache/matplotlib" \
  .venv/bin/python -m studies.regional_shape_v1.vertical_offset \
  --source data/raw/3DPotatoTwin
```
