# Research decision after the reflection replication

Retain the smooth body as the reference method and close the fixed quarter-strength reflection experiment. The mean error rose by 0.0590 mm on the 28 measurable replication tubers. Both uncertainty intervals include zero. The direction persisted after omitting any one acquisition group. The result applies chiefly to the measured outer band. [Replication report](replication_report.md)

## Next development question

How much underside error would remain if the smooth body had the correct vertical position for each tuber? The regional correction was centered within each band and could not adjust that position. In the original development study, some measured underside heights fell below the assumed belt plane. This makes a vertical offset worth measuring, although its cause is unknown. [Development results](results.md)

1. Use only the original 12 development tubers. Reproduce the archived body MAE on the seven measurable tubers, ten bands and 12,202 common cells. Preserve the existing inputs, masks and weighting. Keep the 36 replication tubers closed.
2. For each measurable tuber, compute reference underside height minus body height on every scored cell. Estimate one constant vertical shift using the weighted median of those signed residuals. Give each passing band equal weight, each sector equal weight within a band, and each cell equal weight within a sector. Add the shift to the body and compute the remaining MAE. This uses reference heights to measure the maximum possible improvement from a constant shift on those cells.
3. Check whether the shift transfers across the same tuber. Estimate it on even-numbered sectors, score it on odd-numbered sectors, then reverse. Compare with the unshifted body on identical held-out cells and combine the two directions equally. Reference heights are still needed to estimate the shift.
4. Report each tuber's signed shift, original MAE, best achievable MAE, and held-out-sector change in mm. Give the equal-tuber means, win/tie/loss counts for the held-out comparison, and the range of mean changes when each tuber is omitted. Verify on a known constant shift and a zero-offset example. Save a reproducible command and a machine-readable result.

If a substantial part of the error is removable and the offset consistently transfers across sectors, investigate whether belt-plane or thickness measurements available at inference can predict it. If substantial error remains even with the best shift, inspect the spatial pattern of that residual before choosing a new shape prior. A fitted offset alone cannot identify its physical cause.
