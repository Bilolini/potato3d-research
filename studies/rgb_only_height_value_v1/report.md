# How much does camera height add beyond the potato silhouette?

On the **40 development potatoes**, adding one camera-height feature lowered weight mean absolute error (MAE) from **16.02 g to 14.18 g**. The paired change was **−1.83 g** (95% tuber-bootstrap interval **−3.16 to −0.57 g**). Height was usable on **40/40 validation** and **118/118 training** potatoes. The volume comparison also favored the depth-assisted fit. [Per-potato estimates](per_potato.csv) · [Full-precision results](results.json)

| Outcome | Scored pairs | Mask-only MAE | Depth-assisted MAE | Paired change, depth minus mask | 95% interval | Wins / ties / losses |
|---|---:|---:|---:|---:|---:|---:|
| Weight, primary (g) | 40/40 | 16.02 | 14.18 | −1.83 | −3.16 to −0.57 | 28 / 0 / 12 |
| Water-displacement volume (mL) | 40/40 | 16.99 | 15.12 | −1.88 | −2.91 to −0.95 | 28 / 0 / 12 |

Both arms scored all 40 potatoes for each trait, with zero failures. The mask-only MAEs in the table therefore also describe all eligible validation potatoes. Differences and percentile intervals use unrounded absolute errors and 10,000 bootstrap draws of whole potatoes. Weight was measured in grams including the tack (`weight_g_inctack`), and reference volume was measured by water displacement (`volume_ml`). [Results and coverage](results.json) · [Archived weight provenance](../multiframe_weight_v1/report.md) · [Archived drainage provenance](../regional_shape_v1/corepp_two_frame_volume/report.md#reference-and-procedure)

## What the models saw

Both fits used the same original full-resolution alpha mask at the frozen center of each potato. We used every nonzero alpha pixel, the released D405 focal lengths and a fixed 350 mm projection plane. At that plane one pixel covers **0.28734 mm²**. The mask-only regression used an intercept, projected area raised to the 3/2 power in cm³, and the log of the silhouette's major-to-minor axis ratio. The ratio came from the second moments of foreground positions in the fixed projection plane. The depth-assisted fit retained those predictors and added **that same area × estimated height**, also in cm³. Both regressions used one row per potato and the exact same 118 training IDs for each trait. Weight and volume were fitted separately. [Frozen protocol](protocol.md) · [Exact frame manifest](frame_manifest.json) · [Coefficients](train_fit.json)

Accepted pixels were inside the shared alpha mask and had camera axial depths from 150 mm inclusive to 400 mm exclusive. The frozen rule required at least 100 accepted pixels and at least half of the silhouette. Height was **350 mm minus the fifth percentile of accepted depth**, with nonpositive results marked unavailable. The rule was checked on training inputs first. Validation heights ranged from **37 to 80 mm**, and accepted pixels accounted for **93.39% to 99.92%** of each validation silhouette. The mask-only predictors use alpha and fixed camera scale. The added predictor uses raw depth, with neither measured tuber thickness nor released segmented clouds in the feature pipeline. [Training checks](train_fit.json) · [Validation features](validation_features.csv)

## Scope

The nominal belt depth defines both the common area scale and the height reference. An error in the assumed local belt depth shifts the height estimate, and the project calibration audit found no independent support-height measurement at each potato's position. The result measures the added predictive value of this camera-height proxy on 40 previously studied potatoes with provided masks. The 45 SAM 2 confirmation potatoes and reserved cohorts stayed closed. [Calibration audit](../regional_shape_v1/calibration_data_audit.md) · [Predictions frozen before the validation target join](predictions_before_targets.json)

## Reproduce

Run from the repository root with the release image ZIPs and local Python environment. A fresh directory leaves the recorded validation result intact.

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
height_run=$(mktemp -d)
.venv/bin/python -m studies.rgb_only_height_value_v1.run freeze --out "$height_run" &&
.venv/bin/python -m studies.rgb_only_height_value_v1.run fit --out "$height_run" &&
.venv/bin/python -m studies.rgb_only_height_value_v1.run predict --out "$height_run" &&
.venv/bin/python -m studies.rgb_only_height_value_v1.run score --out "$height_run"
```

[Runnable code](run.py)
