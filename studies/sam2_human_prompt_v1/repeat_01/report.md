# One-click human-operator development results

**40/40** center masks matched the potato at IoU ≥ 0.5. The prior peel-click rule matched **34/40**. There were 6 gains and 0 losses.

The first human session matched **1/40**. This was a coached repeat with clarified instructions on the same scenes.

**40/40** weights were scorable. Human-click masks had **15.57 g MAE**, and provided masks had **16.23 g MAE** on the same IDs. The paired mean change was **-0.66 g**.

In the post-scoring placement audit, **0** clicks landed on or inside the pin outline, **0** landed outside the intended potato, and **40** landed on the potato outside the pin. Of those last clicks, **40** produced a potato match. Click regions were assigned from frozen coordinates and the released entry annotations. They were used only to describe the submitted responses. [Click regions and per-potato results](per_potato.csv)

Gains among prior failures were R6-5, 4R3-1, 3R7-10, R5-8, R10-10, 4R8-3. Losses among prior matches were none.

One operator used annotated coarse location cues. The weight pipeline used measured thickness, as in the archived study. Test and reserved cohorts stayed closed. [Frozen click receipt](click_freeze.json) · [Per-potato results](per_potato.csv) · [Per-frame states](per_frame.csv) · [Full-precision results](results.json)

## Failures

Among the 0 center-mask failures, **0** selected the pin at entry and **0** acquired the potato and later lost it. 0 had another entry mask and never reached the potato IoU threshold.

| Trial | Potato | Mask failure | Entry mask | Center IoU | Weight status | Detail |
|---:|---|---|---|---:|---|---|
| — | — | None | — | — | — | — |

Separate flags in the per-potato table show whether a failure selected the pin at entry and whether it acquired a potato mask and later lost it. Both flags can apply. The failure table gives priority to the entry pin when both occur.
