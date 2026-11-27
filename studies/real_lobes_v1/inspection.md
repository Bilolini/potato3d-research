# Inspection of the 17 demo detections

All 92,793 points in the five registered partial clouds projected inside their corresponding RGB masks. Each projected pixel agreed with the raw depth PNG to within 0.00002 mm in camera coordinates, consistent with the precision of the stored cloud. This verifies the PLY-to-image mapping. The SfM surface still uses the independently supplied registration. [Projection audit](projection_audit.json)

## Visual review

The montage numbers follow descending scan relief within each tuber. “Marker in view” means a visible pin-like head in the 49 × 49 pixel crop. Some heads are at the patch center and others are nearby. This is a visual flag and does not attribute the geometry to the pin. “Unresolved” means the crop provided no clear explanation for the RGB-D and SfM disagreement.

| Tuber | Marker in view | Boundary-sensitive | Unresolved |
|---|---|---|---|
| 2R2-8 | 1, 4 | 3 | 2 |
| 4R3-4 | 1, 2 | | 3 |
| 5R3-2 | 1, 2, 3 | | 4 |
| R13-8 | 1, 4, 6 | | 2, 3, 5 |
| R7-7 | No detections | | |

The strongest RGB-D candidate, 2R2-8 patch 1, lies over a colored marker head and shows 3.62 mm of scan relief versus 0.15 mm in the SfM top. 5R3-2 patch 1 similarly lies on the edge of a blue marker head and shows 2.71 mm in the scan versus −0.31 mm in the reference. Ten candidate crops contain a pin-like head. I did not assign any crop a definite fixture label.

2R2-8 patch 3 was the only detection above 1.5 mm on both observed and reference top surfaces. Its center is five pixels inside the actual RGB mask despite being 10.3 mm inside the scan's projected convex hull. The mesh has rejected rays in and around the core, and the top surface shows a steep transition through the measurement neighborhood. Nominal core and annulus coverage were 93% and 96%, so the pilot's coverage rule alone would accept it. Its reference top and underside relief were +3.19 mm and −0.14 mm, respectively. Treat this patch as boundary-sensitive and retain it in the audit. It provides no unambiguous example of a natural, interior top lobe.

## Implications for development

Convex-hull distance alone misses local silhouette concavities. The follow-up development run implements the same RGB-D eligibility for candidate and control centers before selection and matching. [Screening results](screening.md)

## Reproduce the inspection

Run from the project root. The script verifies the camera projection and produces one four-column montage per tuber with candidates, plus a numerical audit for all five tubers. It shows RGB, RGB-D height, SfM upper height, and outward SfM underside relief. The maps display residuals from a local quadratic fitted to the annulus. Captions report the previously computed robust pilot scores. Blank cells in the geometry maps have unsupported or rejected measurements. Generated crops stay in the local outputs directory.

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 MPLCONFIGDIR=.cache/matplotlib \
  .venv/bin/python studies/real_lobes_v1/inspect_patches.py --out outputs/real_lobes_v1/inspection
```
