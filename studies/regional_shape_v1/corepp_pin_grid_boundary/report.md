# CoRe++ development grid-boundary check

The pin-location effect **persisted** on the expanded grid. The pin-minus-mean-peel contrast was positive on **9/10** potatoes, compared with **9/10** on the original grid. The equal-potato mean moved from **+0.6140 to +0.6476 mm** (change **+0.0336 mm**), and the median moved from **+0.3590 to +0.3917 mm** (change **+0.0327 mm**). The median paired per-potato change was 0.0000 mm. [Archived development report](../corepp_pin_multituber/report.md) · [Expanded per-seed results](results.json)

## Paired contrasts

Effects are in millimetres. Each potato contributes a median across 16 paired seeds. Each seed compares pin displacement with the mean of the three peel displacements, the strongest fixed peel, or the largest peel displacement for that seed. The strongest fixed peel is the patch with the highest median displacement on that grid. The anchored control holds the original-grid strongest patch fixed on both grids. Counts use exact signs and show positive / tied / negative.

| Contrast | Mean 20³ | Mean 30³ | Mean change | Median 20³ | Median 30³ | Median change | Counts 20³ | Counts 30³ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pin − mean peel | +0.6140 | +0.6476 | +0.0336 | +0.3590 | +0.3917 | +0.0327 | 9 / 0 / 1 | 9 / 0 / 1 |
| Pin − strongest fixed peel | +0.5749 | +0.6106 | +0.0356 | +0.2885 | +0.3285 | +0.0400 | 8 / 1 / 1 | 8 / 1 / 1 |
| Pin − seedwise max peel | +0.5696 | +0.6035 | +0.0339 | +0.2873 | +0.3285 | +0.0411 | 8 / 1 / 1 | 8 / 1 / 1 |
| Pin − archived strongest patch | +0.5749 | +0.6106 | +0.0356 | +0.2885 | +0.3285 | +0.0400 | 8 / 1 / 1 | 8 / 1 / 1 |

Every potato kept its original sign for all three contrasts, and the strongest fixed patch stayed the same. The largest primary shift was **+0.2854 mm** for 3R5-2. Expanded-grid leave-one-potato-out primary means ranged from **+0.5016 to +0.7361 mm**. A dash in a sign column means the sign stayed the same. Grid and mesh columns count boundary contacts before and after, out of 80 predictions per potato.

| Potato / frame | Primary 20³ | Primary 30³ | Sign | Strongest 20³ | Strongest 30³ | Sign | Seedwise max 20³ | Seedwise max 30³ | Sign | Grid contacts | Mesh contacts | Seeds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5R1-4 / 362 | -0.1344 | -0.1484 | — | -0.2155 | -0.2592 | — | -0.2376 | -0.2687 | — | 80 → 0 | 80 → 0 | 16/16 |
| 5R3-1 / 360 | +0.0828 | +0.0828 | — | +0.0623 | +0.0623 | — | +0.0623 | +0.0623 | — | 80 → 0 | 10 → 0 | 16/16 |
| 2R2-6 / 358 | +0.7922 | +0.7922 | — | +0.7803 | +0.7803 | — | +0.7667 | +0.7667 | — | 5 → 0 | 0 → 0 | 16/16 |
| 2R3-10 / 363 | +1.1408 | +1.1408 | — | +1.1219 | +1.1219 | — | +1.1219 | +1.1219 | — | 18 → 0 | 0 → 0 | 16/16 |
| R4-10 / 352 | +0.0027 | +0.0027 | — | 0.0000 | 0.0000 | — | 0.0000 | 0.0000 | — | 0 → 0 | 0 → 0 | 16/16 |
| R8-2 / 350 | +1.7639 | +1.7639 | — | +1.6851 | +1.6851 | — | +1.6851 | +1.6851 | — | 0 → 0 | 0 → 0 | 16/16 |
| R10-1 / 362 | +0.2764 | +0.2764 | — | +0.2281 | +0.2281 | — | +0.2281 | +0.2281 | — | 52 → 0 | 0 → 0 | 16/16 |
| R12-7 / 353 | +0.0972 | +0.0966 | — | +0.0796 | +0.0777 | — | +0.0796 | +0.0776 | — | 80 → 0 | 75 → 0 | 16/16 |
| 3R2-10 / 367 | +0.4417 | +0.5071 | — | +0.3488 | +0.4288 | — | +0.3465 | +0.4288 | — | 80 → 0 | 80 → 0 | 16/16 |
| 3R5-2 / 359 | +1.6768 | +1.9621 | — | +1.6587 | +1.9810 | — | +1.6430 | +1.9330 | — | 80 → 0 | 76 → 0 | 16/16 |

## Verification and remaining boundary contacts

The released grid staggers alternate z-planes by **2.3710 mm** in x and y. The frozen grid continued the same stagger and **4.9915 mm** within-axis spacing for five extra indices per side, extending its nominal bounds by **24.9576 mm** per side. The 8,000 interior coordinates were bitwise identical. All **800/800** original-grid tensor, latent and SDF hashes reproduced. The identical SDFs preserved the labels, and the number of changed labels for each edit also matched its archived count. [Frozen grid manifest](frozen_grid.json) · [Interior replay](interior_replay.json)

In the single packed 27,000-point probe on 5R1-4 seed 133, **7,799** interior SDFs and **512** labels differed from the archived batch. All reported predictions therefore used the verified original 8,000-point batch at seeds 133–148 and one separate 19,000-point batch per condition at the corresponding shell seed 10133–10148. Shell draws were paired across the five conditions. The result is conditional on this shell stream and the fixed grid.

Negative SDF at a coordinate-extreme face dropped from **475/800** to **0/800** under the archived contact definition. Checking all outer index layers of the staggered lattice gave the same counts. Mesh face contacts changed from **321/800** to **0/800**. The check stopped at the prescribed 30³ size.

Coverage was **10/10** potatoes and **800/800** valid expanded meshes. Every expanded mesh was watertight with positive finite volume. Both confirmation cohorts stayed closed.

## Reproduction

Run from the repository root with the archived development inputs, the verified CPU runtime and fresh cache and output directories. The scorer verifies the cached latents and interior signed distances before evaluating the added points.

```sh
export DYLD_LIBRARY_PATH="$PWD/outputs/corepp_cpu_audit/runtime/libusb/1.0.30/lib"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
for phase in freeze replay score
do
  outputs/corepp_cpu_audit/venv/bin/python -m studies.regional_shape_v1.corepp_pin_grid_boundary "$phase" \
    --upstream outputs/corepp_cpu_audit/upstream/corepp-0d6bae40b9215332efd566e6bca83bea171b99e9 \
    --released outputs/corepp_cpu_audit/released \
    --input-dir outputs/corepp_pin_multituber/inputs \
    --cache-dir outputs/corepp_pin_grid_boundary/reproduction_cache \
    --out-dir outputs/corepp_pin_grid_boundary/reproduction || break
done
```
