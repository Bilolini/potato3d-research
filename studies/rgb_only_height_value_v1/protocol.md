# Center-frame development benchmark for the value of camera height

## Frozen cohort and inputs

Reuse the exact 118 PointRAFT training and 40 validation potatoes from the archived three-frame weight study, including its exclusions. Reuse the archived center suffix for each validation potato and the already frozen center of the training triplet from the follow-up. Verify the exact IDs and the nearest-360-px frame rule with ties resolved toward the lower suffix. Cross-check the 45 SAM 2 confirmation IDs and reserved rosters by metadata. Only the enrolled RGB-alpha and matching raw-depth members are opened. The 40 validation potatoes have already been studied. No measured axes or released PLY clouds are used as inputs, and no cohort is reopened.

## Features fixed before fitting

Treat nonzero alpha in the original 1280 × 720 PNG as foreground. The released D405 focal lengths are in pixels. At the fixed nominal belt distance of 350 mm for this 2023 setup, each pixel represents `350² / (fx × fy)` mm² in a plane parallel to the image. Multiply this by foreground pixel count to define area `A` in mm². Compute the silhouette axis ratio from the square roots of the larger and smaller eigenvalues of the scaled foreground-pixel covariance after centering. This measures shape independent of orientation in the projection plane.

- **Mask-only.** Use an intercept, `A^(3/2) / 1000` in cm³ and the natural log of the silhouette axis ratio. Per-potato depth, measured dimensions, released segmented clouds and volume are excluded from these features.
- **Depth-assisted.** Use the same three terms and add exactly one predictor, `A × h / 1000` in cm³. The area and aspect ratio are identical to those of the mask-only model. Height `h` in mm is the nominal 350 mm belt depth minus the fifth percentile of accepted camera axial depth within that same alpha mask. Use the archived fifth-percentile convention to reduce sensitivity to isolated unusually close pixels and a fixed 150 mm inclusive to 400 mm exclusive depth gate to exclude zeros and implausible readings. Require at least 100 accepted pixels and at least half of the silhouette pixels, plus a positive height. Apply these predetermined checks to training first and retain the exact rule for validation. A failed depth check leaves the silhouette prediction available. The gate has no measured-thickness input. Nominal belt depth is approximate and lacks an independent support-height measurement at each potato's position.

A degenerate or missing silhouette stays recorded as unscorable in both methods. No substitute frame, image crop, measured thickness, per-potato metric scale or reference geometry is used.

## Fit and score

For each outcome, use one row per training potato and ordinary least squares with an intercept. Both models for that outcome use the identical rows with valid shared inputs, height and target. Record any exclusions. Floor predicted weight and volume at zero in both models. The primary target is release `weight_g_inctack`, measured in grams including the tack. The secondary target is water-displacement `volume_ml` in mL, with entirely separate coefficients and the same feature definitions. Save the frozen training features, both sets of coefficients, validation features and validation predictions before joining validation targets by exact ID. Missing or invalid targets remain visible.

For each trait, report both MAEs on complete paired predictions and the change in absolute error (depth-assisted minus mask-only), computed from unrounded values. Use 10,000 paired whole-potato bootstrap draws with seed 5272401 for a percentile 95% interval. Report wins, ties within 1e-9 outcome units and losses, and the full-cohort usable-height and scored counts. Also report each model's available-case MAE, including mask-only on all eligible validation potatoes if depth fails. Stop after this frozen development comparison.
