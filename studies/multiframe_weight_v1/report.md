# Three conveyor frames for potato weight estimation

**Wider spacing did not establish a weight-error reduction.** On 40 development potatoes, three spaced predictions averaged **16.63 g MAE** versus **16.82 g** for three adjacent predictions and **16.15 g** for center alone. The primary paired change was **−0.20 g** for spaced minus adjacent (95% tuber bootstrap interval **−0.91 to +0.41 g**). Center alone had the lowest observed MAE.

## Cohort and measurement

The reference was `weight_g_inctack` from the release's measured traits CSV. The field denotes grams including the tack. The dataset paper's §2.3 and Table 1 describe the physical weight measurement and report grams. PointRAFT names this exact column in its training code and describes a digital scale in the acquisition methods. We used the field as released, with no tack adjustment. [Dataset card](https://huggingface.co/datasets/UTokyo-FieldPhenomics-Lab/3DPotatoTwin#3_pair) · [Dataset paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC13109331/) · [PointRAFT training code](https://github.com/pieterblok/pointraft/blob/main/train.py) · [PointRAFT §2.2.2](https://arxiv.org/html/2512.24193v2#S2.SS2.SSS2)

| PointRAFT public split and eligibility | Train | Validation |
|---|---:|---:|
| Assigned IDs | 195 | 71 |
| Release non-perfect exclusions | 11 | 2 |
| Reserved reflection replication | 17 | 9 |
| Reserved support-offset confirmation | 25 | 8 |
| Reserved CoRe++ sensitivity | 15 | 7 |
| Earlier local development and demo | 9 | 5 |
| Missing or duplicate weight, invalid weight or frame layout | 0 | 0 |
| **Eligible and used** | **118** | **40** |

No exclusion reasons overlapped among the train and validation IDs. As in the earlier release audit, the ambiguous warning `2R306` also excludes `2R3-6`. Every eligible ID had one valid exact weight join. All 3,368 training frames and 200 selected validation frames processed successfully. The 73 PointRAFT test IDs were counted from the split file and stayed closed. The same 40 validation potatoes contribute to all results. They include 37 Sayaka and three Kitahime from 13 acquisition groups, all represented in training. [Frozen frame and exclusion manifest](frame_manifest.json) · [Protocol](protocol.md)

## Frozen positions and estimator

The suffix is the reversed vertical coordinate of the annotated bounding-box center, `image_height − y`, along the direction of travel. The center is the saved position nearest **360 px** in the 720 px image. Adjacent uses its previous and next saved positions. Spaced uses the same center and the saved positions nearest the 25% and 75% points of the potato's observed travel span. Each triple had distinct positions, and the spaced frames were farther out on both sides for every validation potato. The center's absolute offset from 360 was 5 px at the median and at most 11 px. This is spacing in image position, with capture timing and physical angle unverified. [Release naming convention](https://huggingface.co/datasets/UTokyo-FieldPhenomics-Lab/3DPotatoTwin#1_image) · [PointRAFT image-position convention](https://arxiv.org/html/2512.24193v2#S2.SS4.SSS1)

| Actual validation spacing | Lower to center, median (range) | Center to upper, median (range) | Outer span, median (range) |
|---|---:|---:|---:|
| Adjacent | 20 px (16–24) | 20.5 px (17–24) | 41 px (35–46) |
| Spaced | 137 px (109–163) | 141.5 px (106–163) | 275.5 px (228–307) |

We used a **train-only weighted linear regression** on the visible XY hull area times robust height. The released optional PointRAFT checkpoint has no verified training-ID list tied to these validation potatoes, and the documented CUDA environment and `torch-cluster` dependency were unavailable on this Apple CPU setup. The public split still defines eligibility. [PointRAFT public split and pretrained-weight instructions](https://github.com/pieterblok/pointraft#training-and-testing) · [PointRAFT installation](https://github.com/pieterblok/pointraft/blob/main/INSTALL.md)

We used the supplied segmented PLY clouds and converted camera XYZ from meters to millimeters. Validation medians for camera depth ranged from 278 to 318 mm, consistent with the release's camera distances. The area is the convex hull of the visible XY projection in mm². The height proxy is the nonnegative difference between the nominal 350 mm camera-to-belt depth and the fifth percentile of the observed camera depth. It ranged from 37 to 81 mm on validation frames. The area-height product divided by 1,000 is in cm³. Each training tuber contributed total weight one across its frames. The frozen intercept was **12.25 g** and the slope was **0.7672 g/cm³**. The same coefficients produced all 200 per-frame validation estimates, saved before joining the validation targets for scoring. [Released cloud construction](https://pmc.ncbi.nlm.nih.gov/articles/PMC13109331/) · [Nominal belt convention](../regional_shape_v1/calibration_data_audit.md) · [Train fit](train_fit.json) · [Frame predictions](per_frame_predictions.csv)

## Paired results

Changes are differences in absolute error, in grams. Negative values favor the first condition. The 95% intervals resample whole potatoes with all three predictions kept together.

| Comparison | Mean paired change (g) | Median paired change (g) | 95% interval (g) | Wins / ties / losses |
|---|---:|---:|---:|---:|
| **Spaced minus adjacent** | **−0.197** | −0.133 | **−0.910 to +0.412** | **21 / 0 / 19** |
| Spaced minus center | +0.478 | +0.380 | −0.528 to +1.373 | 13 / 0 / 27 |
| Adjacent minus center | +0.676 | +0.344 | −0.003 to +1.426 | 16 / 0 / 24 |

| Potato and measured weight | Center frame and prediction | Adjacent frames and predictions | Spaced frames and predictions | Adjacent → spaced absolute error |
|---|---|---|---|---:|
| **2R1-1, 346 g** · largest improvement | 358 → 361.73 g | 337/358/381 → 359.16/361.73/357.25 g | 229/358/490 → 338.08/361.73/350.64 g | 13.38 → 4.15 g (**−9.23**) |
| **4R6-7, 470 g** · largest worsening | 359 → 370.05 g | 341/359/382 → 365.17/370.05/363.69 g | 237/359/465 → 355.89/370.05/361.64 g | 103.70 → 107.47 g (**+3.78**) |

For 2R1-1, the lower-position spaced frame underestimated weight and partially canceled the other two overestimates. For 4R6-7 every prediction underestimated weight, and the spaced outer frames underestimated it more strongly. [All per-potato estimates and errors](per_potato_predictions.csv) · [Full-precision summary](results.json)

This development result applies to the simple visible-geometry estimator and these mostly Sayaka potatoes from shared acquisition groups. Image-position separation does not establish angular diversity, and the nominal belt depth is an approximation. The earlier two-frame experiment measured volume and served only as context. [Earlier volume pilot](../regional_shape_v1/corepp_two_frame_volume/report.md)

## Reproduce

Run from the repository root with the local Python environment and release inputs.

```bash
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
weight_run_dir=$(mktemp -d)
.venv/bin/python -m studies.multiframe_weight_v1.run freeze --out "$weight_run_dir" &&
.venv/bin/python -m studies.multiframe_weight_v1.run score --out "$weight_run_dir"
```

[Runner](run.py)
