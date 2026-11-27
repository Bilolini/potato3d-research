# Does pin recoloring move the CoRe++ surface across potatoes?

The one-frame pilot found a median 0.7665 mm greater surface displacement for the pin edit than the peel edit. This development experiment tests whether the result repeats across tubers and across several peel locations on the same tuber. [Pilot](corepp_pin_pilot/report.md)

## Cohort and inputs

Use the registered frame for each object in the [12-object development roster](../real_lobes_v1/fresh_selection.json), excluding the pilot object 2R1-10 and its hue donor 5R2-3. All ten remaining named frames have one release annotation with segmentation. Keep all ten in the intake denominator. The earlier underside-coverage gate measures a different endpoint and does not apply to this within-frame prediction comparison. Keep both 36-object cohorts closed.

Use the released CPU checkpoints, preprocessing, module modes, mesh extraction and surface-distance implementation from the pilot. Use its saved 94.839 mm grid cube (exact saved coordinates or bounding-box values) for every frame and condition. Report grid-boundary contacts, invalid meshes and failures. The grid was defined on the pilot; no evaluated object's reference geometry is needed.

## Freeze edits before edited inference

1. Rasterize each published pin contour on the valid crop. Use two fixed donor colors from the pilot inputs: the archived red donor and the median RGB of the pilot's original colored pin pixels. Assign the donor farther from the current pin's median HSV hue by circular hue distance, breaking ties toward red. Use the selected donor hue and saturation and preserve pixelwise HSV value as in the pilot. Record the preprocessed mask, number of retained pixels, donor and signed RGB changes.
2. For each frame select three disjoint peel patches using the translated pin mask, entirely on valid potato pixels and outside the pin. Search integer translations and select greedily by fewest clipped channel values for the proposed edit, then closest mean distance to the silhouette, then smallest difference in mean original luminance, then row and column. Require disjoint patches at each selection. Save overlays and flag visibly contaminated patches before inference. Record eligibility and each failure without substituting tubers.
3. Enforce exact RGB-delta matching. On each corresponding pixel/channel, cap the proposed delta to the common feasible integer range across the pin and all three peel locations. Apply that same realized delta map in each condition. Verify equal changed-pixel counts and deltas at the model input, unchanged depth and crop, and zero off-mask changes. Report attenuation relative to the proposed edit and mark zero-strength edits unevaluable. Save and hash the entire input manifest before running any edited predictions.

## Score and interpret

Reuse paired seeds 133–148, checkpoint/buffer resets and the pilot's exact no-op replay checks. For each seed compute mean symmetric surface displacement relative to that seed's original prediction for each edit. Subtract the mean displacement of the three peel edits from the pin displacement, then take the median across seeds for **one primary contrast per tuber**. Require a complete set of paired conditions and seeds for the primary estimate and report all incomplete cases.

Report the equal-tuber mean and median, positive/zero/negative counts, range of leave-one-tuber-out means, and the pin and each peel result per tuber. Also report the comparison against the most responsive peel patch, realized edit magnitude, latent and continuous SDF changes, and signed volume change. Seed repeats measure decoder variability within an object. Show the denominators and stop after this development analysis.

Consider an independent confirmation design if the primary median is positive, every single-tuber omission leaves a positive mean, and a majority of all ten selected tubers have positive primary contrasts. Review the strongest-peel control and grid-boundary flags before choosing a confirmation protocol. This measures prediction sensitivity under controlled edits; reconstruction accuracy and physical pin removal are separate questions.
