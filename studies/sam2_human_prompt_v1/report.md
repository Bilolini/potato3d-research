# One-click human-operator development results

**1/40** center masks matched the potato at IoU ≥ 0.5. The prior peel-click rule matched **34/40**. There were 0 gains and 33 losses.

**39/40** weights were scorable. Human-click masks had **148.44 g MAE**, and provided masks had **16.34 g MAE** on the same IDs. The paired mean change was **+132.11 g**.

In the post-scoring placement audit, **35** clicks landed on or inside the pin outline, **2** landed outside the intended potato, and **3** landed on the potato outside the pin. Of those last clicks, **1** produced a potato match. This session primarily reflects pin clicks, so it provides little evidence about reliably placed peel clicks. Click regions were assigned from frozen coordinates and the released entry annotations. They were used only to describe the submitted responses. [Click regions and per-potato results](per_potato.csv)

Gains among prior failures were none. Losses among prior matches were 4R4-4, 3R3-8, 4R6-1, 4R4-8, R9-4, R1-2, R4-4, 3R1-7, R5-7, 3R6-3, R8-1, 2R1-9, R3-2, 2R2-1, R1-3, R4-2, 4R8-5, R4-7, R9-2, 4R1-2, 4R4-10, 3R1-8, 4R6-7, 4R8-2, 3R1-1, 4R8-8, R11-5, R5-9, 2R1-1, 3R6-2, 3R1-9, 3R4-10, R5-1.

One operator used annotated coarse location cues. The weight pipeline used measured thickness, as in the archived study. Test and reserved cohorts stayed closed. [Frozen click receipt](click_freeze.json) · [Per-potato results](per_potato.csv) · [Per-frame states](per_frame.csv) · [Full-precision results](results.json)

## Failures

Among the 39 center-mask failures, **36** selected the pin at entry and **0** acquired the potato and later lost it. 3 had another entry mask and never reached the potato IoU threshold.

| Trial | Potato | Mask failure | Entry mask | Center IoU | Weight status | Detail |
|---:|---|---|---|---:|---|---|
| 1 | 4R4-4 | never tracked potato | other | 0.000 | scorable | — |
| 2 | R6-5 | never tracked potato | other | 0.000 | empty center | — |
| 3 | 3R3-8 | pin at entry | pin | 0.032 | scorable | — |
| 4 | 4R6-1 | pin at entry | pin | 0.023 | scorable | — |
| 5 | 4R4-8 | pin at entry | pin | 0.053 | scorable | — |
| 6 | R9-4 | pin at entry | pin | 0.024 | scorable | — |
| 7 | 4R3-1 | pin at entry | pin | 0.031 | scorable | — |
| 8 | R1-2 | pin at entry | pin | 0.022 | scorable | — |
| 9 | 3R7-10 | never tracked potato | other | 0.094 | scorable | — |
| 10 | R4-4 | pin at entry | pin | 0.076 | scorable | — |
| 11 | 3R1-7 | pin at entry | pin | 0.020 | scorable | — |
| 12 | R5-8 | pin at entry | pin | 0.034 | scorable | — |
| 13 | R5-7 | pin at entry | pin | 0.042 | scorable | — |
| 14 | 3R6-3 | pin at entry | pin | 0.032 | scorable | — |
| 15 | R8-1 | pin at entry | pin | 0.025 | scorable | — |
| 16 | 2R1-9 | pin at entry | pin | 0.040 | scorable | — |
| 17 | R3-2 | pin at entry | pin | 0.053 | scorable | — |
| 18 | 2R2-1 | pin at entry | pin | 0.035 | scorable | — |
| 19 | R1-3 | pin at entry | pin | 0.039 | scorable | — |
| 20 | R4-2 | pin at entry | pin | 0.019 | scorable | — |
| 21 | 4R8-5 | pin at entry | pin | 0.044 | scorable | — |
| 22 | R4-7 | pin at entry | pin | 0.036 | scorable | — |
| 24 | R9-2 | pin at entry | pin | 0.043 | scorable | — |
| 25 | 4R1-2 | pin at entry | pin | 0.040 | scorable | — |
| 26 | 4R4-10 | pin at entry | pin | 0.056 | scorable | — |
| 27 | 3R1-8 | pin at entry | pin | 0.034 | scorable | — |
| 28 | 4R6-7 | pin at entry | pin | 0.015 | scorable | — |
| 29 | 4R8-2 | pin at entry | pin | 0.034 | scorable | — |
| 30 | 3R1-1 | pin at entry | pin | 0.028 | scorable | — |
| 31 | 4R8-8 | pin at entry | pin | 0.027 | scorable | — |
| 32 | R11-5 | pin at entry | pin | 0.020 | scorable | — |
| 33 | R5-9 | pin at entry | pin | 0.035 | scorable | — |
| 34 | 2R1-1 | pin at entry | pin | 0.014 | scorable | — |
| 35 | 3R6-2 | pin at entry | pin | 0.021 | scorable | — |
| 36 | 3R1-9 | pin at entry | pin | 0.022 | scorable | — |
| 37 | R10-10 | pin at entry | pin | 0.047 | scorable | — |
| 38 | 3R4-10 | pin at entry | pin | 0.038 | scorable | — |
| 39 | 4R8-3 | pin at entry | pin | 0.037 | scorable | — |
| 40 | R5-1 | pin at entry | pin | 0.029 | scorable | — |

Separate flags in the per-potato table show whether a failure selected the pin at entry and whether it acquired a potato mask and later lost it. Both flags can apply. The failure table gives priority to the entry pin when both occur.
