# Single-frame conveyor correction on fresh tubers

Does the fixed, scan-only conveyor correction reduce mean absolute underside error on previously unscored 3DPotatoTwin objects? Development error fell from 5.5121 to 4.1069 mm on seven measurable tubers. Four improved. The correctly matched prediction ranked 25th of 5,040 assignments. [Development report](support_offset_report.md)

## Cohort and prediction

The [reserved cohort](support_offset_confirmation_cohort.json) has SHA-256 `8e1f11ecf292eefb167a4b3a8d6fe8af6dbeeeb933fcf45cf4b26fb0b76d2188`. It contains 24 Sayaka and 12 Corolle from 15 acquisition groups. This is a fixed CPU experiment budget. To reproduce selection, apply the previous replication's metadata filters, exclusions, hash ordering and round-robin selector, additionally excluding every ID on its 36-object roster. The objects are fresh. The collection and some acquisition groups are shared. Preserve all 36 rows, including failures.

1. Verify the cohort hash, input identities and duplicate-content checks against all earlier cohorts. Replay the development prediction and scoring on the original data. Record input, code, environment and protocol hashes. Keep old outputs intact.
2. Run the development predictor unchanged. Estimate local background-plane depth at the footprint center in camera coordinates, then add 350 mm minus that depth to the smooth body's lower surface. Retain the zero-shift fallback on plane-fit failure. Save all scan-only shifts, failures and hashes before reading fresh reference geometry or scoring. Use registration metadata for frame selection only at prediction time.
3. Score once with the same registration checks, masks, bands, sector coverage and nested equal weighting. Primary endpoint is corrected minus unshifted underside MAE, averaged equally across measurable tubers. Report errors in mm, per-tuber changes, wins, median, selected and measurable counts, and group and cultivar summaries. Report counts of plane-fit failures even when their fallback scored successfully.

## Interpretation

Use the previous replication's two cultivar-stratified 95% bootstrap intervals (10,000 draws, seed 5272101), resampling tubers and whole acquisition groups respectively. Report both and the effect after omitting each group. Call a mean gain confirmed for this measurable population if both intervals are wholly below zero and both cultivars are represented. An interval crossing zero leaves confirmation unresolved. Report any concentration of gains in a single group.

For the secondary control, compare correctly matched MAE with the expected MAE from randomly reassigning shifts **within the same acquisition group**. Compute the exact expectation by scoring every eligible shift from that group on each measurable tuber, including its own, then averaging with the primary weights. Report both control means on groups with at least two measurable tubers and give the number of groups and tubers contributing. A group-wide camera offset can improve prediction even when individual frame matching adds little. Treat that distinction as descriptive.

Keep the formula fixed throughout. Return the report and machine-readable results to the research chat for interpretation.
