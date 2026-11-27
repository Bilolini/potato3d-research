# Can RGB-predicted height recover the weight benefit of camera depth?

On the **40 development potatoes**, substituting RGB-predicted height lowered weight MAE from **16.02 to 15.92 g** relative to the archived silhouette-only trait baseline. The paired reduction was **0.10 g**, about **5%** of the observed **1.83 g** camera-height advantage. The primary interval spans zero (RGB minus silhouette-only **−0.10 g**, 95% interval **−0.53 to +0.29 g**). Adding appearance to the height predictor changed weight MAE by **+0.02 g** relative to silhouette-predicted height (95% interval **−0.34 to +0.35 g**). The RGB-predicted-height estimate remained **1.74 g** behind the camera-height estimate (95% interval **+0.65 to +2.90 g**). [Per-potato results](per_potato.csv) · [Full-precision endpoints](results.json)

## Height prediction

Both height models used standardized ridge regression fitted on the same **118 training potatoes**. They retained original scale through projected silhouette area at the archived nominal 350 mm projection plane. The silhouette model used size, axis ratio and convex-hull fill. The RGB model added five foreground luma, chromaticity and core-to-rim contrast summaries. The image features came from the original center PNG at native resolution and the provided alpha. [Protocol and feature definitions](protocol.md) · [Frozen centers](frame_manifest.json)

Settings were chosen by leaving out one of the 14 training acquisition groups at a time. The selected penalties were **0.01 for silhouette** and **0.1 for RGB plus silhouette**, with training out-of-fold height MAEs of **4.51 mm** and **4.74 mm**, respectively. The 40 validation height predictions and the corresponding trait estimates were saved before opening the archived validation depth-derived heights or measured traits. [Training choices and coefficients](train_fit.json) · [Frozen RGB predictions](predictions_before_targets.json)

| Height model, 40/40 paired validation potatoes | Height MAE (mm) | Signed bias (mm) |
|---|---:|---:|
| Silhouette | 5.07 | +1.17 |
| RGB plus silhouette | 4.73 | +1.12 |

The target was the same camera-height proxy used in the earlier benchmark. Positive bias means the prediction is higher than that proxy. Appearance changed absolute height error by **−0.35 mm** (paired 95% interval **−0.79 to +0.11 mm**), with 25 potatoes improving and 15 worsening. [Height errors and coverage](results.json)

## Weight and water-displacement volume

For the middle two rows, the archived depth-assisted weight and volume regressions received the predicted height in their existing area × height term. The projected area, silhouette terms, coefficients and zero floor stayed fixed. The first and last rows replayed the archived silhouette-only and camera-height trait predictions. All four arms used the same **40/40 potatoes**, with zero failed images, height predictions or trait scores. [Earlier height benchmark](../rgb_only_height_value_v1/report.md) · [Per-potato estimates](per_potato.csv)

| Trait prediction | Weight MAE (g) | Volume MAE (mL) |
|---|---:|---:|
| Archived silhouette-only regression | 16.02 | 16.99 |
| Silhouette-predicted height | 15.91 | 16.90 |
| RGB-plus-silhouette-predicted height | 15.92 | 16.73 |
| Archived camera-estimated height | 14.18 | 15.12 |

| Paired comparison, 40/40 potatoes | Weight change (g) [95% interval] | Volume change (mL) [95% interval] |
|---|---:|---:|
| RGB-predicted height minus archived silhouette-only | −0.10 [−0.53, +0.29] | −0.26 [−0.60, +0.04] |
| RGB-predicted height minus silhouette-predicted height | +0.02 [−0.34, +0.35] | −0.17 [−0.46, +0.09] |
| RGB-predicted height minus camera height | +1.74 [+0.65, +2.90] | +1.62 [+0.77, +2.55] |
| Camera height minus archived silhouette-only | −1.83 [−3.16, −0.57] | −1.88 [−2.91, −0.95] |

Changes are differences in unrounded absolute errors. Negative favors the first arm. Intervals use 10,000 paired whole-potato resamples. The RGB predictor's smaller observed height error did not translate into an observed weight gain over the silhouette height predictor. The small observed volume gain from appearance has an interval that includes zero. [Paired results and win counts](results.json)

The height target depends on raw depth and the nominal 350 mm belt distance, so it is a camera-derived proxy for physical height. The findings apply to these compact RGB summaries and provided masks on previously studied development potatoes. Selection held out whole training acquisition groups, and the development cohort shared acquisition groups with training. The 45 SAM 2 confirmation potatoes and reserved cohorts remained closed. [Belt calibration audit](../regional_shape_v1/calibration_data_audit.md) · [Frozen evaluation protocol](protocol.md)

## Reproduce

Run from the workspace root with the archived camera-height benchmark and released image ZIPs available.

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
l2_run=$(mktemp -d)
.venv/bin/python -m studies.rgb_predicted_height_v1.run freeze --out "$l2_run" &&
.venv/bin/python -m studies.rgb_predicted_height_v1.run fit --out "$l2_run" &&
.venv/bin/python -m studies.rgb_predicted_height_v1.run predict --out "$l2_run" &&
.venv/bin/python -m studies.rgb_predicted_height_v1.run score --out "$l2_run"
```

[Runnable code](run.py)
