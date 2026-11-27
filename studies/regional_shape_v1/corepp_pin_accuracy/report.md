# Development accuracy of CoRe++ pin recoloring

The mean SfM surface error decreased by **0.1277 mm** after the pin edit on **10/10** development potatoes. Relative to the mean of the three matched peel edits, the mean signed error change was **-0.1266 mm**. [Frozen protocol](../corepp_pin_accuracy_protocol.md) · [Machine-readable results](results.json)

| Contrast | Potatoes | Mean (mm) | Median (mm) | Improved / worsened / tied |
| --- | ---: | ---: | ---: | ---: |
| Pin error − unchanged error | 10/10 | -0.1277 | -0.0235 | 6 / 3 / 1 |
| Pin error change − mean peel error change | 10/10 | -0.1266 | -0.0162 | 7 / 3 / 0 |

Positive values mean increased reconstruction error. In the second row, an improvement means the pin edit had a better accuracy change than the mean peel edit. The first row gives the direction relative to the unchanged prediction. A median within 0.0001 mm of zero counts as tied.

## Per-potato results

All distance columns are in mm. The five error columns show condition medians against the same fixed SfM reference. Each contrast instead takes the median after subtracting errors within seeds. The displacement columns come from the archived 30³ sensitivity study and measure movement away from the unchanged prediction. [Per-potato data](per_potato.csv) · [Archived displacement study](../corepp_pin_grid_boundary/report.md)

| Potato / frame | Seeds | Unchanged error | Pin error | Peel 1 error | Peel 2 error | Peel 3 error | Pin displacement | Pin − mean peel displacement | Pin error change | Pin − mean peel error change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5R1-4 / 362 | 16/16 | 4.7386 | 4.6767 | 4.6891 | 4.8032 | 4.7390 | 0.0758 | -0.1484 | -0.0189 | -0.0136 |
| 5R3-1 / 360 | 16/16 | 3.6165 | 3.6975 | 3.5965 | 3.6091 | 3.5965 | 0.0881 | +0.0828 | +0.0307 | +0.0430 |
| 2R2-6 / 358 | 16/16 | 3.6812 | 3.2454 | 3.6905 | 3.6905 | 3.6812 | 0.8014 | +0.7922 | -0.4486 | -0.4623 |
| 2R3-10 / 363 | 16/16 | 3.8137 | 3.0399 | 3.8602 | 3.8166 | 3.8531 | 1.2134 | +1.1408 | -0.7113 | -0.7287 |
| R4-10 / 352 | 16/16 | 2.0935 | 2.0936 | 2.0946 | 2.0946 | 2.1123 | 0.0197 | +0.0027 | 0.0000 | -0.0048 |
| R8-2 / 350 | 16/16 | 1.8248 | 2.0652 | 1.8376 | 1.8129 | 1.8145 | 1.8399 | +1.7639 | +0.2153 | +0.2061 |
| R10-1 / 362 | 16/16 | 2.5020 | 2.5021 | 2.5085 | 2.5020 | 2.5020 | 0.3266 | +0.2764 | -0.1342 | -0.1238 |
| R12-7 / 353 | 16/16 | 2.7003 | 2.6328 | 2.6867 | 2.6933 | 2.6429 | 0.1258 | +0.0966 | -0.0281 | -0.0188 |
| 3R2-10 / 367 | 16/16 | 2.7397 | 3.0672 | 2.7556 | 2.7377 | 2.7322 | 0.6470 | +0.5071 | +0.2530 | +0.2713 |
| 3R5-2 / 359 | 16/16 | 2.5149 | 2.0726 | 2.5308 | 2.4880 | 2.5155 | 2.0193 | +1.9621 | -0.4348 | -0.4341 |

## Mapping and replay

The 5R1-4 coordinate gate matched the recreated float32 loader target bit for bit, reproduced the archived unchanged mesh, and used the release registration to check both pin landmarks and the visible scan against the centered target. The pin landmarks were 2.328 mm apart and the registered scan-to-SfM distances had a 0.708 mm median and a 2.527 mm p95. The coordinate overlay uses the SfM axes and fixed pose. We reconstructed the released target centering rule with Open3D seed 133. The original per-tuber target samples used by the authors were unavailable. [Coordinate trace and visual verification](coordinate_mapping.md) · [Frozen reference hashes](frozen_protocol.json)

Accuracy uses symmetric mean point-to-triangle distance with 20,000 deterministic area-weighted samples in each direction at seed 133. Identical planar geometry gave 0.00000174 mm and a known 4 mm normal shift gave 4.000000 mm. The metric was invariant to changes in triangle order and winding in the synthetic check. Pose and scale were fixed across all conditions. Every scored prediction reproduced its archived original-grid SDF and labels, shell SDF and expanded SDF. Across **800/800** scored meshes, the maximum replay volume difference was **0 mL** and the maximum difference from the archived order-dependent sampled displacement was **0 mm**. Both earlier 36-object cohorts and the 29 fresh test potatoes stayed closed.

The initial run encountered one replay discrepancy in the historical displacement measure. Same-geometry meshes gave slightly different sampled distances when Open3D enumerated the triangles differently. Before inspecting any accuracy values, I preserved the initial run, froze a canonical vertex and triangle order, and rescored all ten potatoes. Reference axes, positions, endpoint formulas and sampling count stayed fixed. [Mesh-order diagnostic](mesh_order_diagnostic.json)

There were zero reference, replay or scoring failures.

## Interpretation

The pin edit moved the predicted surface more than the mean peel control on nine of ten potatoes in the archived sensitivity study. Its effect on accuracy went in both directions. On **3R5-2**, a **2.0193 mm** displacement reduced error by **0.4348 mm**. On **R8-2**, a **1.8399 mm** displacement increased error by **0.2153 mm**. The average error fell on this development cohort, with three potatoes showing a loss of accuracy. [Archived displacement results](../corepp_pin_grid_boundary/report.md)

## Reproduction

Run from the repository root with the archived development input hashes and original-grid latents and SDF cache. If that cache is unavailable, reproduce the interior replay using the command in the [30³ grid report](../corepp_pin_grid_boundary/report.md). Use fresh output and reference directories. Inspect the audit overlay before freezing. The saved visual signoff applies to matching audit and overlay hashes.

```sh
export DYLD_LIBRARY_PATH="$PWD/outputs/corepp_cpu_audit/runtime/libusb/1.0.30/lib"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
for phase in audit freeze score
do
  outputs/corepp_cpu_audit/venv/bin/python -m studies.regional_shape_v1.corepp_pin_accuracy "$phase" \
    --source data/raw/3DPotatoTwin \
    --upstream outputs/corepp_cpu_audit/upstream/corepp-0d6bae40b9215332efd566e6bca83bea171b99e9 \
    --released outputs/corepp_cpu_audit/released \
    --input-dir outputs/corepp_pin_multituber/inputs \
    --cache-dir outputs/corepp_pin_grid_boundary/interior \
    --out-dir outputs/corepp_pin_accuracy/reproduction_evidence \
    --work-dir outputs/corepp_pin_accuracy/reproduction_work \
    --review studies/regional_shape_v1/corepp_pin_accuracy/coordinate_review.json --workers 4 || break
done
```
