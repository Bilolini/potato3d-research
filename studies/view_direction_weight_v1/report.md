# Does centroid-ray viewing direction improve per-frame potato weight estimates?

Adding viewing direction moved the primary MAE from **17.02 g to 16.94 g** on the 40 development potatoes. The paired change was **−0.08 g**, with a 95% tuber-bootstrap interval of **−2.39 to +2.07 g**. This endpoint scores each frame individually and then averages its absolute error within each potato. The interval spans zero. [Frozen protocol](protocol.md) · [Full-precision results](results.json)

After averaging each model’s three predictions into one weight per potato, MAE was **16.63 g for Model A** and **16.67 g for Model B**. The paired change was **+0.05 g** (95% interval **−2.32 to +2.29 g**). The small frame-level improvement did not carry through to averaged predictions. Both differences use unrounded per-potato errors. [Per-potato results](per_potato.csv)

## Frozen inputs and baseline replay

Both weighted least-squares fits used the identical 3,368 frames from 118 training potatoes. Each potato had total weight one. The 40 validation potatoes each contributed the three archived spaced frames, for 120 frames and full coverage. The 45 SAM 2 confirmation potatoes and prior reserves were outside this run. The target was the released measured weight in grams including the tack. The baseline used the original camera-XY hull area times the height proxy based on the nominal 350 mm belt depth and fifth-percentile camera depth. Model B added `rx`, `ry`, and their interactions with the bulk proxy. Model A exactly reproduced both archived coefficients and all 120 selected-frame predictions. [Frame manifest](frame_manifest.json) · [Train-only coefficients](train_fit.json) · [Archived three-frame study](../multiframe_weight_v1/report.md)

## How much the viewing ray varied

The centroid came from the nonzero alpha pixels of the uncropped 1280 × 720 image. Using the released D405 intrinsics, `rx = (u − cx)/fx` and `ry = (v − cy)/fy` give dimensionless camera-ray coordinates `X/Z` and `Y/Z`. Image right and down are positive. Landmarks one-quarter focal length right and below the principal point gave the expected +0.25 in each axis. Every ray projected back to its original centroid. [Frozen protocol](protocol.md) · [Frame features](per_frame.csv)

| Ray coordinate | Training range | Validation range | Median within-potato span across the three views (range) |
|---|---:|---:|---:|
| `rx` | −0.782 to +0.658 | −0.690 to +0.654 | 0.00894 (0.00039–0.01397) |
| `ry` | −0.490 to +0.462 | −0.262 to +0.242 | 0.42211 (0.35298–0.47442) |

Within the validation triplets, `ry` decreased from lower through upper suffix on all 40 potatoes. Its median was +0.201 at the lower position, −0.005 at center and −0.222 at the upper position. The frames mainly varied in vertical image position within a potato. [Ray ranges by position](results.json)

## Position errors and largest changes

Signed bias is prediction minus measured weight. Each position has 40 potatoes.

| Position | A MAE (g) | B MAE (g) | A signed bias (g) | B signed bias (g) |
|---|---:|---:|---:|---:|
| Lower suffix | 16.80 | 16.41 | −4.96 | −2.74 |
| Center | 16.15 | 16.00 | −3.80 | −3.10 |
| Upper suffix | 18.10 | 18.41 | −3.73 | −4.65 |

Across potatoes, Model B reduced the primary error on 18 and increased it on 22. The largest gain was **4R6-7**, where mean frame error fell from 107.47 g to 80.65 g (**−26.82 g**). The largest loss was **R11-5**, where it rose from 37.47 g to 56.10 g (**+18.62 g**). The per-frame predictions show that all three positions moved in the same direction for each of these potatoes. [Per-frame results](per_frame.csv) · [Per-potato results](per_potato.csv)

These 40 potatoes had already informed development decisions. This comparison tests a centroid ray with one geometry-based estimator. The ray encodes camera-relative image position, so conclusions apply to that measurement and the sampled conveyor views. [Frozen protocol](protocol.md)

## Reproduce

From the workspace root, run the three stages into a fresh output directory.

```bash
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
view_run=$(mktemp -d)
view_code=studies/view_direction_weight_v1/run.py
.venv/bin/python "$view_code" freeze --out "$view_run" &&
.venv/bin/python "$view_code" fit --out "$view_run" &&
.venv/bin/python "$view_code" score --out "$view_run"
```

[Runnable script](run.py)
