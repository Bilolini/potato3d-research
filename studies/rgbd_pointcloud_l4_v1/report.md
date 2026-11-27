# L4 full RGB-D point clouds versus L3 camera height

**Use L3 on this setup.** On all 40 paired development potatoes, the L4 three-seed point-cloud estimator had **35.46 g weight MAE** and **35.92 mL water-displacement volume MAE**. Relative to L3, the paired increases were **+21.28 g** (95% tuber-bootstrap interval **+7.78 to +36.49 g**) and **+20.80 mL** (**+10.43 to +31.51 mL**). This comparison changes both the input representation and estimator architecture. [Per-potato results](per_potato.csv) · [Full-precision results](results.json)

| Estimator, same 40 development potatoes | Weight scored | Weight MAE (g) | Volume scored | Volume MAE (mL) |
|---|---:|---:|---:|---:|
| L0 · Silhouette alone | 40/40 | 16.02 | 40/40 | 16.99 |
| L1 · Frozen monocular height | 40/40 | 23.71 | 40/40 | 22.75 |
| L2 · Learned RGB height | 40/40 | 15.92 | 40/40 | 16.73 |
| L3 · Silhouette plus camera-estimated height | 40/40 | 14.18 | 40/40 | 15.12 |
| L4 · Center RGB-D point cloud plus the same height | 40/40 | 35.46 | 40/40 | 35.92 |

There were zero input, fitting or scoring failures. L4 improved on L3 for nine potatoes and worsened weight error for 31. For volume, the counts were seven and 33, with zero ties for both traits. The effect and interval use unrounded paired errors with 10,000 whole-potato bootstrap draws. [Coverage and paired counts](results.json) · [L0–L3 archive](../rgb_monocular_height_v1/report.md)

## Inputs and fitting

The study matched all **118 training and 40 development IDs** and exact center-frame archive members in the L3 manifest. The 45 held-out SAM 2 potatoes and reserved cohorts stayed closed. L4 used original provided alpha, 16-bit depth in mm, and RGB from the same pixels. It retained the L3 mask and depth gate of 150 mm inclusive to 400 mm exclusive, at least 100 accepted pixels and at least half the silhouette. The 350 mm nominal belt depth minus the fifth percentile of all accepted axial depths reproduced the archived L3 scalar exactly on all 158 cases before sampling. The construction used only raw center RGB-D, provided alpha and fixed camera calibration. Measured thickness, released segmented PLYs, SfM and fused views played no role. The height is a camera-derived proxy based on nominal belt depth. [Input manifest and replay](inputs_manifest.json) · [L3 protocol](../rgb_only_height_value_v1/protocol.md) · [Calibration audit](../regional_shape_v1/calibration_data_audit.md)

The fixed sample selected 1,024 accepted pixels per potato. All clouds had enough distinct points. Back-projecting and projecting back to the image yielded a maximum discrepancy of 2.27 × 10⁻¹³ px. The sampled XYZ coordinates were mean-centered and divided by 100 mm so metric size remained available. RGB was scaled to [0,1]. The first point MLP took six channels, relative XYZ and RGB, and the separate height branch received the same L3 height scaled by 100 mm. The remainder of the compact CPU architecture came from the earlier PointRAFT-style study, including the neighborhood construction, pooling, feature widths and dropout. [Frozen protocol](protocol.md) · [Runnable code](run.py) · [Prior CPU architecture](../raft_pointcloud_weight_v1/report.md)

For each trait and seed, we selected the earliest minimum-MAE epoch using only a fixed 94-potato training subset and 24 other training potatoes for selection. We then fitted from scratch on all 118 training potatoes through that epoch. Predictions were averaged across all three seeds before scoring. Both traits used measurements from the archived benchmark, weight in grams including the tack and volume in mL by water displacement. All 40 development predictions were frozen before joining those values. [Model and checkpoint receipts](train_fit.json) · [Frozen predictions](predictions_before_targets.json) · [Archived weight and volume provenance](../rgb_only_height_value_v1/report.md)

## Seed variation and CPU time

| Seed | Weight refit epochs | Weight MAE (g) | Volume refit epochs | Volume MAE (mL) |
|---|---:|---:|---:|---:|
| 133 | 78 | 39.96 | 52 | 39.80 |
| 527 | 74 | 36.99 | 67 | 35.52 |
| 2401 | 73 | 38.96 | 35 | 36.69 |

The sample standard deviations across seed MAEs were **1.51 g** for weight and **2.21 mL** for volume. All three individual seeds had higher MAE than L3 for both traits. The reported L4 ensemble averages predictions, so its MAE can differ from the mean of seed MAEs. [Per-seed predictions and contrasts](results.json)

Extracting and verifying all 158 clouds took **5.51 s**. Across the three seeds, CPU training and epoch selection took **40.29 s for weight** and **35.83 s for volume** on the local arm64 CPU with four PyTorch threads. Finishing the forward passes for all 40 potatoes and all three seeds took **0.035 s for weight** and **0.045 s for volume**, measured separately from cloud preparation, model fitting and serialization. [Input runtime](inputs_manifest.json) · [Training and prediction runtime](train_fit.json)

The recommendation is for these estimators and these previously studied potatoes. L3 had the lowest observed error for both traits using the same masks, camera scale and camera-height proxy as L4. The result leaves open how other point-cloud architectures or training setups would perform. [Frozen protocol](protocol.md)

## Reproduce

Run from the workspace root with the archived CPU environment and source studies. Use a fresh output directory.

```bash
export PYTHONPATH="$PWD/src:$PWD/outputs/corepp_cross_model/triposr/deps"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
l4_run=$(mktemp -d)
cpu_python=outputs/corepp_cpu_audit/venv/bin/python
"$cpu_python" -m studies.rgbd_pointcloud_l4_v1.run freeze --out "$l4_run" &&
"$cpu_python" -m studies.rgbd_pointcloud_l4_v1.run extract --out "$l4_run" &&
"$cpu_python" -m studies.rgbd_pointcloud_l4_v1.run fit --out "$l4_run" &&
"$cpu_python" -m studies.rgbd_pointcloud_l4_v1.run score --out "$l4_run"
```
