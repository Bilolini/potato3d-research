# Calibration and metadata follow-up — 2026-11-13

## What was established

The five named registered PLYs reproject to **integer source pixels exactly** with
the released camera intrinsics (column-major matrix storage). Their XYZ coordinates
reconstructed from the PNG depth match within roughly 0.00002 mm numerical error,
and every projected point lies within its object's alpha mask. The depth values
are millimeters. This checks our loading convention against another released
modality; it is not an independent physical scale calibration.

Depth PNGs contain background values outside the target object's mask. The RGB
image also contains neighboring potatoes, rods and gaps; the alpha mask labels
only the target. A new audit fits a near-horizontal **background plane proxy**
using only image/depth/intrinsic data, with no reference mesh or physical dimensions.
It excludes the target mask plus 15 pixels, limits image ROI/depth explicitly,
uses fixed-seed RANSAC, and reserves 20% of sampled candidate pixels for diagnostics.

| Object | Camera-axis plane intercept (mm) | Tilt (degrees) | Held-out support within 1.5 mm |
|---|---:|---:|---:|
| 2R2-8 | 348.361 | 1.76 | 35.8% |
| 4R3-4 | 350.644 | 1.04 | 43.4% |
| 5R3-2 | 348.676 | 1.75 | 29.9% |
| R13-8 | 350.341 | 1.02 | 45.5% |
| R7-7 | 350.450 | 1.15 | 49.4% |

All sampled inlier positions and representative RGB overlays are saved in
`outputs/demo_calibration_audit_v1/`. The matrix for each proxy is a proper rigid
camera-mm to plane-height-mm transform, but it is **not applied to predictions**.
The saved compact audit and source hashes are `docs/calibration_followup_evidence.json`.

The intercepts are consistent with the approximate 0.35 m camera placement in
[PointRAFT section 2.2.1](https://arxiv.org/html/2512.24193v2). They do not establish
the true support envelope: a dominant fit can cut through round conveyor rods;
neighboring potatoes remain unlabeled; held-out pixels test fit support rather
than physical correctness. A single exact flat belt plane is itself an
approximation for a rod conveyor. Further refinement needs a known empty-belt
region/capture or verified roller-envelope geometry, with uncertainty recorded.
No already-scored real experiment was rerun or calibrated from reference bounds.

## What remains unresolved

`2R2-8` still has a larger mutually consistent RGB-D/PLY/SfM geometry than its
listed physical dimensions and reported volume suggest. The successful PNG/PLY
check rules out our PLY loader or camera projection as the immediate cause.
It does not prove the upstream ID, camera calibration or SfM scale are correct.
No released object-specific corrected measurement record was located.

The upstream
[PotatoScan README](https://github.com/UTokyo-FieldPhenomics-Lab/PotatoScan/blob/04c2ed46737533630ff8665646bef402e9225f35/README.md)
documents two 2023 scale-bar systems. Its
[reference notebook](https://github.com/UTokyo-FieldPhenomics-Lab/PotatoScan/blob/04c2ed46737533630ff8665646bef402e9225f35/02_metashape_scripts/00_reference_list.ipynb)
notes that the second system starts at `2R1-10`. This is relevant provenance,
**not proof that this caused the 2R2-8 issue**. A mesh-only scale correction would
also break the currently close RGB-D/SfM overlap.

The
[2023 volume-export notebook](https://github.com/UTokyo-FieldPhenomics-Lab/PotatoScan/blob/04c2ed46737533630ff8665646bef402e9225f35/02_metashape_scripts/06_export_area_volume_2023.ipynb)
uses `Metashape chunk.model.volume()` and converts cubic meters to cubic centimeters;
it does not contain a `2R2-8` correction. The code repository file listings were
checked at CoRe++ commit `0d6bae40b9215332efd566e6bca83bea171b99e9` and PotatoScan
commit `04c2ed46737533630ff8665646bef402e9225f35`. Small downloaded source files and
their hashes are recorded; notebooks were read as source and **not executed**.

Status: usable real geometry smoke pairs remain available, but no corrected
physical-volume benchmark or certified belt calibration has been established.
Keep the inconsistency visible and continue method development on the freshly
sealed synthetic protocol. Strong real-data conclusions still require validated
measurements and a larger object-level split; no access agreement, large dataset
download or external message was initiated.

## Reproduce the audit

```bash
MPLCONFIGDIR="$PWD/.cache/matplotlib" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python scripts/audit_demo_calibration.py \
  --out outputs/my_calibration_audit
```

The output directory must be new. This command reads existing demo files only.
