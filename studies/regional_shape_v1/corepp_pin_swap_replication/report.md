# Development replication of the CoRe++ pin-pixel swap

Sensitivity shifted toward the transplanted RGB pixels on **9/10 potatoes**. The more responsive site switched in the pilot direction on at least two of three patches for **8/10 potatoes**. Counting both directions, **9/10** met the two-patch threshold. The additional potato, **5R1-4**, favored peel before swapping and reversed in the opposite direction on all three patches. [Frozen protocol](../corepp_pin_swap_replication_protocol.md) · [Machine-readable results](results.json)

The equal-potato mean shift was **+1.1187 mm** and the median was **+0.5220 mm**. Signs were **9 positive, 0 tied and 1 negative**. Leave-one-potato-out means ranged from **+0.7671 to +1.2672 mm**.

## Potato-level results

For each seed, the two site displacements are measured relative to that layout's unchanged prediction. The contrast is original pin site minus original peel site. The shift is native contrast minus swapped contrast. The potato endpoint takes the median across the 16 seeds of the within-seed mean of the three patch shifts. A positive shift indicates movement toward the transplanted appearance. A **+ → −** reversal means the original pin site was more responsive before the swap and the original peel site was more responsive after it. Contrasts within 0.0001 mm of zero count as tied. [Per-potato data](per_potato.csv)

| Potato / frame | Peel 1 | Peel 2 | Peel 3 | Pilot reversals | Opposite reversals | Shift (mm) | Mean if omitted (mm) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| [5R1-4 / 362](5R1-4/layouts.png) · [overlay](5R1-4/overlays.png) | − → + | − → + | − → + | 0 | 3 | -0.2174 | +1.2672 |
| [5R3-1 / 360](5R3-1/layouts.png) · [overlay](5R3-1/overlays.png) | + → − | + → − | + → − | 3 | 0 | +0.1437 | +1.2271 |
| [2R2-6 / 358](2R2-6/layouts.png) · [overlay](2R2-6/overlays.png) | + → − | + → − | + → − | 3 | 0 | +1.2170 | +1.1078 |
| [2R3-10 / 363](2R3-10/layouts.png) · [overlay](2R3-10/overlays.png) | + → − | + → − | + → − | 3 | 0 | +1.8712 | +1.0351 |
| [R4-10 / 352](R4-10/layouts.png) · [overlay](R4-10/overlays.png) | + → − | Swapped tie | Native tie | 1 | 0 | +0.0319 | +1.2395 |
| [R8-2 / 350](R8-2/layouts.png) · [overlay](R8-2/overlays.png) | + → − | + → − | + → − | 3 | 0 | +2.6908 | +0.9440 |
| [R10-1 / 362](R10-1/layouts.png) · [overlay](R10-1/overlays.png) | + → − | + → − | + → − | 3 | 0 | +0.5296 | +1.1842 |
| [R12-7 / 353](R12-7/layouts.png) · [overlay](R12-7/overlays.png) | + → − | + → − | + → − | 3 | 0 | +0.1229 | +1.2294 |
| [3R2-10 / 367](3R2-10/layouts.png) · [overlay](3R2-10/overlays.png) | + → − | + → − | Pin advantage weakened | 2 | 0 | +0.5144 | +1.1859 |
| [3R5-2 / 359](3R5-2/layouts.png) · [overlay](3R5-2/overlays.png) | + → − | + → − | + → − | 3 | 0 | +4.2831 | +0.7671 |

## Patch-level results

Each patch classification compares its median native and swapped seed contrasts. An advantage can weaken or strengthen while favoring the same site. The seed-level counts classify the individual paired contrasts. The unedited swaps moved the predicted surface by **0.0458 to 2.3449 mm** across the patch-level medians. [All 30 patch medians](per_patch.csv) · [All paired seed contrasts and base-swap displacements](per_patch_seed.csv)

| Pair outcome | Patch medians | Patch × seed pairs |
| --- | ---: | ---: |
| + → − | 24 | 348 |
| − → + | 3 | 29 |
| Pin advantage weakened | 1 | 26 |
| Peel advantage weakened | 0 | 16 |
| Pin advantage strengthened | 0 | 5 |
| Peel advantage strengthened | 0 | 7 |
| Pin advantage unchanged | 0 | 0 |
| Peel advantage unchanged | 0 | 0 |
| Native tie | 1 | 13 |
| Swapped tie | 1 | 25 |
| Both tied | 0 | 11 |

## Frozen inputs and replay

The 30 swaps each reused the archived translated masks and the exact realized RGB delta map. Every double swap restored the original RGBA pixel bytes. All single-site edits matched the archived map at model input, with zero clipping and zero RGB changes outside the edit masks. Surface measurement used the 30³ grid, paired interior and added-point dropout, and the pilot's canonical mesh ordering. [Frozen inputs](frozen_inputs.json)

All 30 swapped crops showed visible composite seams. At the old pin site, 18 exhibited a distinct residual rim and 9 a faint remnant. The three R12-7 swaps had indeterminate rims and visibly fragmented patches around the fixed depth holes. The RGB patches moved while the original depth and surrounding pixels remained at their sites. In the overlays, cyan is the original pin mask and amber, magenta and green mark peel patches 1–3. [Visual review](visual_review.json)

All **640/640** no-op pairs passed. The maximum mesh self-distance was 9.72e-05 mm. One pair, 3R5-2 with peel 3 at seed 137, differed in raw mesh order and matched exactly after canonical ordering. **800/800** native condition-and-seed predictions reproduced the archived SDF hashes and mesh volumes. The maximum difference in the legacy order-dependent displacement sampler was 6.34e-06 mm. Across **2,240** unique scored predictions, none had negative SDF on an outer lattice layer or an extracted mesh that touched a face. All **1,600** edited meshes were valid. [No-op evidence](no_op_replay.json) · [Expanded-grid archive](../corepp_pin_grid_boundary/report.md)

All ten potatoes completed all paired conditions.

The shift and reversal counts describe RGB appearance in synthetic swaps. The fixed depth, original-site context and residual rims remain part of the composite. Marker recognition and the outcome of physical pin removal remain open. The 29 fresh model-test potatoes and both earlier 36-object cohorts stayed closed.

## Reproduction

Run from the repository root with fresh output, swap-input and work directories. Inspect the crops after preparation. The saved visual review applies to the exact regenerated crops.

```sh
export DYLD_LIBRARY_PATH="$PWD/outputs/corepp_cpu_audit/runtime/libusb/1.0.30/lib"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
for phase in prepare seal noop score
do
  outputs/corepp_cpu_audit/venv/bin/python -m studies.regional_shape_v1.corepp_pin_swap_replication "$phase" \
    --upstream outputs/corepp_cpu_audit/upstream/corepp-0d6bae40b9215332efd566e6bca83bea171b99e9 \
    --released outputs/corepp_cpu_audit/released \
    --input-dir outputs/corepp_pin_multituber/inputs \
    --swap-input-dir outputs/corepp_pin_swap_replication/reproduce/inputs \
    --work-dir outputs/corepp_pin_swap_replication/reproduce/work \
    --out-dir outputs/corepp_pin_swap_replication/reproduce/evidence \
    --review studies/regional_shape_v1/corepp_pin_swap_replication/visual_review.json --workers 5 || break
done
```
