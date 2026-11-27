# Does three-view area change improve a center-frame weight estimate?

**The area-change feature did not improve this development comparison.** Model A, the matched center-only regression, had **16.227 g MAE**. Model B, which added the area-change feature, had **16.230 g MAE**. The paired B-minus-A change was **+0.0025 g** (95% tuber-bootstrap interval **−0.2810 to +0.3028 g**), with **17 wins, 0 ties and 23 losses** for B. The earlier center MAE was **16.149 g**, or **16.15 g** at the previous reporting precision. That fit used all training frames and serves as context. [Earlier weight experiment](../multiframe_weight_v1/report.md)

## What was held fixed

Both models were fitted by ordinary least squares with an intercept, using one row for each of the same **118 training potatoes**, then evaluated once on the same **40 validation potatoes**. We kept the original exclusions and used the released segmented clouds. Test and reserved cohorts stayed closed. There were no extraction or scoring failures. Model A used center XY hull area times center height. Model B added the difference between the mean outer XY hull area and the center area, multiplied by the same center height. Each product was converted from mm³ to cm³. Height used the prior 350 mm nominal camera-to-belt depth minus the fifth-percentile center depth, floored at zero. Both models predicted measured grams including the tack. [Frozen protocol](protocol.md) · [Train-only coefficients](train_fit.json)

The three frozen image positions were distinct and correctly ordered on all **158 potatoes**. Every validation triplet and its archived scan features replayed exactly. Training potato 4R5-9 had a lower quarter pick that also happened to be its previous saved frame. Its ordered picks, **189 / 363 / 520 px**, follow the same nearest-position rules. The extra feature varied in both splits. In training it ranged from **−14.67 to +7.50 cm³** (SD **3.99 cm³**), with 70 negative and 48 positive values. In validation it ranged from **−19.09 to +8.58 cm³** (SD **4.90 cm³**), with 24 negative and 16 positive values. [Frame manifest and feature checks](frame_manifest.json) · [Scan features](scan_features.csv)

## Interpretation

The mean change was essentially zero and the interval covers small effects in either direction. The median paired change was **+0.099 g**. This is exploratory because the same validation cohort informed the question. [Per-potato predictions](predictions.csv) · [Full-precision results](results.json)

## Reproduce

Run from the repository root using the local Python environment and existing release inputs.

```bash
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
weight_correction_dir=$(mktemp -d)
.venv/bin/python -m studies.multiframe_weight_correction_v1.run freeze --out "$weight_correction_dir" &&
.venv/bin/python -m studies.multiframe_weight_correction_v1.run score --out "$weight_correction_dir"
```

[Runnable script](run.py)
