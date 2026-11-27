# Fresh-potato CoRe++ pin-color result

On 29/29 fresh potatoes, the mean pin-minus-mean-peel displacement was **+0.4941 mm**. The acquisition-group 95% interval was **+0.3089 to +0.6271 mm**. The effect persisted against the strongest fixed peel, with a mean of **+0.3976 mm** and a 95% group interval of **+0.2267 to +0.4956 mm**. Both intervals lie above zero. The prespecified rule classifies these results as **descriptive** because five acquisition groups contributed and six were required for a confirmatory decision. [Frozen protocol](../corepp_pin_confirmation_protocol.md) · [Machine-readable results](results.json)

The cohort includes every eligible unstudied object assigned to the model-test split by the authors' published full-data split generator. The 29 selected frames cover 21 Sayaka, seven Kitahime and one Corolle. This verifies freshness to our study and identifies held-out status from published rules. The checkpoint bundle supplies no separate tuber list. [Availability by cultivar, group and split](availability.md) · [Frozen roster](roster.json)

| Paired contrast | Potatoes | Mean (mm) | Median (mm) | Positive / tied / negative | 95% group interval (mm) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pin − mean peel | 29/29 | +0.4941 | +0.4472 | 25 / 1 / 3 | +0.3089 to +0.6271 |
| Pin − strongest fixed peel | 29/29 | +0.3976 | +0.3924 | 24 / 2 / 3 | +0.2267 to +0.4956 |

The paired effect for a potato is the median over 16 seeds. The primary uses the mean of the three peel displacements within each seed. The strongest control selects one fixed patch by its median across the same seeds. Seed repetitions quantify within-potato variation. Group intervals used 20,000 whole-group draws retaining every evaluable potato from each drawn group with equal potato weights. With five selected groups and one Corolle potato, the descriptive interval has limited coverage across acquisition settings. The outcome is **sensitivity of the predicted surface** to the color intervention.

## Acquisition groups

All means are in mm. Omitting one group at a time gave primary means of **+0.3873 to +0.5389 mm** and strongest-peel means of **+0.3260 to +0.4408 mm**.

| Group | Evaluable / selected | Primary in group | Primary if omitted | Strongest if omitted | Potatoes if omitted |
| --- | ---: | ---: | ---: | ---: | ---: |
| `20230914_field_okadasan_sarabetsu_05` | 10/10 | +0.6972 | +0.3873 | +0.3260 | 19 |
| `20230915_barn_okadasan_sarabetsu_03` | 7/7 | +0.4891 | +0.4958 | +0.3751 | 22 |
| `20230921_field_okadasan_sarabetsu_03` | 5/5 | +0.4001 | +0.5137 | +0.4171 | 24 |
| `20230921_field_okadasan_sarabetsu_11` | 6/6 | +0.3224 | +0.5389 | +0.4408 | 23 |
| `20230922_barn_okadasan_sarabetsu_02` | 1/1 | 0.0000 | +0.5118 | +0.4118 | 28 |

## Per-potato results

The four edit columns show median symmetric displacement from the unchanged prediction in mm. Both contrasts use seed pairing. RGB L2 is the mean realized 8-bit RGB change per retained mask pixel and is matched across all four interventions for that potato. Contact counts cover the unchanged and four edited predictions per seed. Per-potato input and registration hashes, realized and proposed RGB changes, and all failure reasons are available in the frozen or scored records. [Per-potato data](per_potato.csv) · [Frozen inputs](frozen_inputs.json) · [Visual flags](visual_review.json)

| Potato / frame | Seeds | Pin | Peel 1 | Peel 2 | Peel 3 | Primary | Strongest patch | Pin − strongest | Edited px | RGB L2 | Grid / mesh contacts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| [R12-4](R12-4/overlay.png) / 369 | 16/16 | 0.1279 | 0.1380 | 0.0808 | 0.0755 | +0.0221 | peel1 | +0.0019 | 404 | 18.71 | 0 / 0 |
| [4R9-3](4R9-3/overlay.png) / 360 | 16/16 | 0.0000 | 0.6350 | 0.8507 | 1.4098 | -0.9575 | peel3 | -1.4098 | 429 | 75.96 | 0 / 0 |
| [3R2-3](3R2-3/overlay.png) / 366 | 16/16 | 0.6365 | 1.4503 | 1.8930 | 1.4876 | -1.0348 | peel2 | -1.3632 | 500 | 140.32 | 0 / 0 |
| [2R3-9](2R3-9/overlay.png) / 354 | 16/16 | 1.2983 | 0.0000 | 0.0814 | 0.0137 | +1.2326 | peel2 | +1.2288 | 500 | 156.59 | 0 / 0 |
| [5R2-7](5R2-7/overlay.png) / 354 | 16/16 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | peel1 | 0.0000 | 414 | 3.96 | 0 / 0 |
| [R12-5](R12-5/overlay.png) / 364 | 16/16 | 1.2801 | 0.2015 | 0.0925 | 0.1799 | +1.0870 | peel1 | +1.0407 | 473 | 149.20 | 0 / 0 |
| [4R9-8](4R9-8/overlay.png) / 363 | 16/16 | 0.0911 | 0.0725 | 0.0520 | 0.0599 | +0.0375 | peel1 | +0.0262 | 521 | 15.20 | 0 / 0 |
| [3R2-6](3R2-6/overlay.png) / 364 | 16/16 | 0.3364 | 0.0559 | 0.1430 | 0.0435 | +0.2413 | peel2 | +0.1850 | 404 | 155.98 | 0 / 0 |
| [2R3-2](2R3-2/overlay.png) / 357 | 16/16 | 1.1331 | 0.0221 | 0.0855 | 0.0473 | +1.0752 | peel2 | +1.0623 | 415 | 129.85 | 0 / 0 |
| [R12-6](R12-6/overlay.png) / 361 | 16/16 | 1.1413 | 0.0934 | 0.0543 | 0.1723 | +1.0130 | peel3 | +0.9334 | 449 | 155.71 | 0 / 0 |
| [4R9-1](4R9-1/overlay.png) / 369 | 16/16 | 2.1465 | 0.0335 | 0.0311 | 0.0398 | +2.1044 | peel3 | +2.0688 | 440 | 95.85 | 0 / 0 |
| [3R2-9](3R2-9/overlay.png) / 364 | 16/16 | 1.1051 | 0.0623 | 0.0791 | 0.0000 | +1.0763 | peel2 | +1.0355 | 444 | 163.40 | 0 / 0 |
| [2R3-7](2R3-7/overlay.png) / 351 | 16/16 | 0.0750 | 0.0000 | 0.0232 | 0.0000 | +0.0713 | peel2 | +0.0645 | 466 | 5.42 | 0 / 0 |
| [R12-10](R12-10/overlay.png) / 351 | 16/16 | 0.8115 | 0.0000 | 0.0000 | 0.3206 | +0.6350 | peel3 | +0.3924 | 447 | 125.43 | 0 / 0 |
| [4R9-6](4R9-6/overlay.png) / 370 | 16/16 | 0.6887 | 0.0362 | 0.0329 | 0.0000 | +0.6783 | peel1 | +0.6639 | 419 | 157.24 | 0 / 0 |
| [3R2-1](3R2-1/overlay.png) / 365 | 16/16 | 1.6922 | 0.0405 | 0.0017 | 0.0120 | +1.6649 | peel1 | +1.6395 | 400 | 74.45 | 0 / 0 |
| [2R3-4](2R3-4/overlay.png) / 369 | 16/16 | 0.1583 | 0.0897 | 0.0337 | 0.1405 | +0.0731 | peel3 | +0.0051 | 479 | 17.30 | 0 / 0 |
| [R12-2](R12-2/overlay.png) / 351 | 16/16 | 0.9090 | 0.0089 | 0.0245 | 0.1489 | +0.8934 | peel3 | +0.7827 | 435 | 112.17 | 0 / 0 |
| [4R9-4](4R9-4/overlay.png) / 363 | 16/16 | 0.0363 | 0.0177 | 0.0192 | 0.0192 | +0.0031 | peel2 | 0.0000 | 423 | 12.88 | 0 / 0 |
| [3R2-4](3R2-4/overlay.png) / 367 | 16/16 | 0.1436 | 0.1527 | 0.0460 | 0.1305 | +0.0527 | peel1 | +0.0245 | 345 | 21.40 | 0 / 0 |
| [2R3-8](2R3-8/overlay.png) / 362 | 16/16 | 0.5013 | 0.3433 | 0.3546 | 0.2224 | +0.1418 | peel2 | +0.1650 | 472 | 27.61 | 0 / 0 |
| [R12-3](R12-3/overlay.png) / 365 | 16/16 | 0.3600 | 1.1604 | 3.0832 | 2.9558 | -2.0109 | peel2 | -2.7136 | 460 | 187.13 | 0 / 0 |
| [4R9-7](4R9-7/overlay.png) / 370 | 16/16 | 0.1497 | 0.0919 | 0.0040 | 0.0750 | +0.0687 | peel1 | +0.0437 | 544 | 5.13 | 0 / 0 |
| [2R3-5](2R3-5/overlay.png) / 348 | 16/16 | 0.6244 | 0.1935 | 0.0361 | 0.1616 | +0.4747 | peel1 | +0.4216 | 507 | 160.27 | 0 / 0 |
| [R12-8](R12-8/overlay.png) / 350 | 16/16 | 1.0073 | 0.1410 | 0.1142 | 0.3700 | +0.7852 | peel3 | +0.5759 | 535 | 53.16 | 0 / 0 |
| [2R3-1](2R3-1/overlay.png) / 358 | 16/16 | 0.3751 | 0.0216 | 0.0000 | 0.0040 | +0.3548 | peel1 | +0.3326 | 421 | 69.83 | 0 / 0 |
| [R12-9](R12-9/overlay.png) / 362 | 16/16 | 1.6456 | 0.0207 | 0.0033 | 0.0252 | +1.6051 | peel3 | +1.5990 | 339 | 149.64 | 0 / 0 |
| [R13-10](R13-10/overlay.png) / 359 | 16/16 | 0.5234 | 0.1264 | 0.0374 | 0.0493 | +0.4472 | peel1 | +0.4264 | 557 | 155.88 | 0 / 0 |
| [R13-9](R13-9/overlay.png) / 365 | 16/16 | 2.5944 | 0.2400 | 0.0000 | 0.0235 | +2.4945 | peel1 | +2.2990 | 414 | 146.11 | 0 / 0 |

## Replay, contacts and failures

Matched RGB deltas, alpha and depth checks passed for **29/29** input sets. Realized RGB L2 ranged from **3.96 to 187.13**. The visual review flagged 10/87 retained peel patches near a silhouette or pin highlight before scoring. Preprocessing removed 6, 10 and 26 pin pixels on 5R2-7, 2R3-7 and 4R9-6, respectively. [Review 1](review_1.png) · [Review 2](review_2.png) · [Review 3](review_3.png) · [Review 4](review_4.png) · [Review 5](review_5.png)

**464/464** attempted exact no-op pairs passed, out of 464 planned. The largest mesh self-distance residual among passing pairs was 2.46e-05 mm. These checks replayed the input, latent, original-grid signed distances, added-point signed distances, labels, mesh arrays and volume on the 30³ grid. The original-point batch used seeds 133–148 and the added points used the existing paired shell seeds 10133–10148. [No-op checks](no_op_replay.json) · [Archived fixed grid](../corepp_pin_grid_boundary/frozen_grid.json)

**464/464** complete edited seed sets contributed, yielding **1,856/1,856** valid edited meshes. None of the **2,320** original and edited predictions had negative SDF at an outer index layer or coordinate-extreme face, and no meshes touched a face. The two earlier 36-object cohorts stayed closed.

The study recorded zero intake, no-op, or scoring failures. [Artifact checksums](checksums.sha256)

## Reproduction

Run from the repository root with fresh output, input and cache directories. Inspect all overlays after preparation and before sealing. The command below uses the saved flags for this exact roster. The scorer writes an exclusive one-score marker for each run directory.

```sh
export DYLD_LIBRARY_PATH="$PWD/outputs/corepp_cpu_audit/runtime/libusb/1.0.30/lib"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
source_root=data/raw/3DPotatoTwin
upstream=outputs/corepp_cpu_audit/upstream/corepp-0d6bae40b9215332efd566e6bca83bea171b99e9
study=outputs/corepp_pin_confirmation/reproduction
runtime=outputs/corepp_cpu_audit/venv/bin/python
"$runtime" -m studies.regional_shape_v1.corepp_pin_confirmation_inventory \
  --source "$source_root" --upstream "$upstream" --out-dir "$study/evidence" &&
for phase in prepare seal noop score
do
  "$runtime" -m studies.regional_shape_v1.corepp_pin_confirmation "$phase" \
    --source "$source_root" --upstream "$upstream" --released outputs/corepp_cpu_audit/released \
    --out-dir "$study/evidence" --input-dir "$study/inputs" --cache-dir "$study/noop_cache" \
    --review studies/regional_shape_v1/corepp_pin_confirmation/visual_review.json --workers 5 || break
done
```
