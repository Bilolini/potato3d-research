# CoRe++ pin recoloring across ten development potatoes

The median within-tuber contrast between the pin and the mean of three matched peel edits was **+0.3590 mm** across 10/10 complete tubers. The equal-tuber mean was **+0.6140 mm**. The primary contrast was positive for **9/10 selected tubers** and negative for one, with no ties. Leave-one-tuber-out means ranged from **+0.4862 to +0.6972 mm** over 10 omissions. [Development protocol](../corepp_pin_multituber_protocol.md) · [Per-seed results](results.json)

With one strongest peel patch fixed per tuber by its median displacement across seeds, the paired contrast had a median of **+0.2885 mm** and was positive in **8/10** selected tubers. Using the largest peel response separately within each seed gave **+0.2873 mm** and **8/10** positive tubers. Both controls use the median of paired seed differences. Ties in selection of the fixed strongest patch follow peel order.

## Surface displacement by potato

Pin and individual peel columns are median symmetric surface displacements from the unchanged prediction for the same seed, in mm. The primary column takes the median across seeds after subtracting the mean of the three peel displacements within each seed. The two strongest-peel columns use the same pairing. One complete row represents one potato. Seed repetitions quantify variation within it.

| Potato / frame | Complete seeds | Pin | Peel 1 | Peel 2 | Peel 3 | Pin − mean peel | Strongest patch | Pin − fixed strongest | Pin − seedwise max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| [5R1-4](5R1-4/overlay.png) / 362 | 16/16 | 0.0750 | 0.2210 | 0.3205 | 0.1314 | -0.1344 | Peel 2 | -0.2155 | -0.2376 |
| [5R3-1](5R3-1/overlay.png) / 360 | 16/16 | 0.0881 | 0.0144 | 0.0000 | 0.0303 | +0.0828 | Peel 3 | +0.0623 | +0.0623 |
| [2R2-6](2R2-6/overlay.png) / 358 | 16/16 | 0.8014 | 0.0293 | 0.0000 | 0.0117 | +0.7922 | Peel 1 | +0.7803 | +0.7667 |
| [2R3-10](2R3-10/overlay.png) / 363 | 16/16 | 1.2134 | 0.1261 | 0.1035 | 0.0593 | +1.1408 | Peel 1 | +1.1219 | +1.1219 |
| [R4-10](R4-10/overlay.png) / 352 | 16/16 | 0.0197 | 0.0000 | 0.0000 | 0.0319 | +0.0027 | Peel 3 | +0.0000 | +0.0000 |
| [R8-2](R8-2/overlay.png) / 350 | 16/16 | 1.8399 | 0.1275 | 0.0248 | 0.0114 | +1.7639 | Peel 1 | +1.6851 | +1.6851 |
| [R10-1](R10-1/overlay.png) / 362 | 16/16 | 0.3266 | 0.0849 | 0.0000 | 0.0000 | +0.2764 | Peel 1 | +0.2281 | +0.2281 |
| [R12-7](R12-7/overlay.png) / 353 | 16/16 | 0.1212 | 0.0059 | 0.0000 | 0.0282 | +0.0972 | Peel 3 | +0.0796 | +0.0796 |
| [3R2-10](3R2-10/overlay.png) / 367 | 16/16 | 0.5939 | 0.2100 | 0.0533 | 0.0940 | +0.4417 | Peel 1 | +0.3488 | +0.3465 |
| [3R5-2](3R5-2/overlay.png) / 359 | 16/16 | 1.7454 | 0.0420 | 0.0604 | 0.0704 | +1.6768 | Peel 3 | +1.6587 | +1.6430 |

## Frozen interventions and replay

The ten registered development RGB-D pairs were verified against the archived member and registration hashes. The pilot and its red donor were excluded from inference. The donor choices were red RGB `[251, 134, 138]` (HSV hue 357.95°, saturation 0.4661) and the pilot pin median RGB `[251, 253, 254]` (hue 200.00°, saturation 0.0118). The farther hue was selected by circular distance from the current pin's median RGB expressed in HSV. Each proposed recoloring took the selected donor saturation and retained per-pixel HSV value. The shared integer RGB cap could attenuate the edit.

Peel selection ranked all feasible integer translations by proposed clipped channel count, then mean silhouette-distance difference, then difference in mean BT.709 luma on RGB code values, then row and column. It selected three disjoint patches greedily. Visual review flagged R12-7 peel 1 and peel 3 near the central masked depth hole. Their intervention pixels all passed the valid-depth and alpha checks, and the original locations stayed in the comparison. The preprocessed pin contours of 2R2-6 and R12-7 lost 104 and 241 source pixels, respectively. [Patch review 1](patch_review_1.png) · [Patch review 2](patch_review_2.png) · [Visual flags](visual_review.json)

All 10/10 eligible frames had identical realized per-pixel RGB deltas in the pin and three peel conditions, with zero off-mask RGB changes and identical alpha, depth tensor, and crop. The input manifest was frozen before edited inference. It records donor assignments, candidate rankings for the selected patches, signed and absolute RGB changes, SHA-256 hashes, and crop checks. Annotated overlays, the model-input RGB crops, the four masks and both delta maps are stored per potato. Full source PNG inputs and their edits are saved locally under `outputs/corepp_pin_multituber/inputs/`. [Frozen input manifest](frozen_inputs.json)

Paired no-op replay passed **160/160** attempted pairs out of 160 planned. For passing pairs the tensor, latent, SDF, grid labels, mesh arrays and volume agreed exactly. The largest self-distance residual was 3.24e-05 mm. Each run restored initial checkpoint parameters and buffers and seeded each corresponding operation on one CPU thread. The decoder retained the released active dropout, and surface distance used 20,000 fixed-seed area-weighted samples each way. [Replay evidence](no_op_replay.json) · [One-frame CPU audit](../corepp_cpu_audit.md)

## Edit strength and changes before surface extraction

RGB strength is mean RGB L2 per retained mask pixel in 8-bit code values. The latent, SDF and signed volume columns show condition medians in pin / peel 1 / peel 2 / peel 3 order. They are paired against the original at the same seed. Volumes are edited minus original.

| Potato | Donor | Pin pixels retained | RGB pixels changed per edit | Proposed RGB L2 | Realized RGB L2 | Attenuation | Latent L2 | Mean absolute SDF change (mm) | Signed volume change (mL) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5R1-4 | Pilot pin | 433/433 | 433 | 41.14 | 41.14 | 0.00% | 0.01681 / 0.03652 / 0.04508 / 0.02293 | 0.07579 / 0.15218 / 0.15325 / 0.09741 | 0.13486 / 0.94264 / 1.70176 / -0.60333 |
| 5R3-1 | Red | 318/318 | 318 | 49.33 | 49.33 | 0.00% | 0.02400 / 0.00258 / 0.00355 / 0.00494 | 0.06017 / 0.01008 / 0.01252 / 0.01763 | 0.44076 / 0.00000 / 0.00000 / 0.00000 |
| 2R2-6 | Red | 384/488 | 384 | 159.06 | 159.06 | 0.00% | 0.48031 / 0.00769 / 0.00917 / 0.01048 | 0.76071 / 0.03265 / 0.02306 / 0.02292 | 0.67767 / -0.14667 / 0.00000 / 0.00000 |
| 2R3-10 | Red | 426/426 | 426 | 157.10 | 157.02 | 0.05% | 0.31061 / 0.02067 / 0.01496 / 0.01386 | 1.26986 / 0.11731 / 0.07924 / 0.04905 | -5.72142 / -1.02853 / -0.93844 / -0.13009 |
| R4-10 | Pilot pin | 432/432 | 432 | 4.77 | 4.77 | 0.00% | 0.00520 / 0.00328 / 0.00231 / 0.00526 | 0.02442 / 0.00819 / 0.00537 / 0.01610 | -0.03211 / 0.00000 / 0.00000 / 0.00000 |
| R8-2 | Red | 371/371 | 371 | 219.28 | 123.46 | 43.70% | 0.46808 / 0.01573 / 0.01843 / 0.00793 | 1.79152 / 0.10473 / 0.04827 / 0.02899 | -14.96738 / 0.78332 / 0.11879 / 0.00000 |
| R10-1 | Red | 368/368 | 368 | 62.11 | 62.11 | 0.00% | 0.07791 / 0.01718 / 0.00472 / 0.00333 | 0.26774 / 0.06378 / 0.01315 / 0.01151 | 2.66135 / 0.02078 / 0.00000 / 0.00000 |
| R12-7 | Pilot pin | 265/506 | 265 | 7.02 | 7.02 | 0.00% | 0.01690 / 0.00262 / 0.00158 / 0.00457 | 0.08872 / 0.01673 / 0.01207 / 0.02042 | -1.86068 / -0.02609 / 0.00000 / -0.29419 |
| 3R2-10 | Red | 532/532 | 532 | 156.83 | 156.83 | 0.00% | 0.14440 / 0.02722 / 0.01625 / 0.00979 | 0.44383 / 0.16652 / 0.02962 / 0.05309 | 7.89629 / -3.20838 / -0.35293 / -1.27621 |
| 3R5-2 | Red | 523/523 | 523 | 230.32 | 132.82 | 42.33% | 0.63959 / 0.01283 / 0.01701 / 0.01282 | 1.70527 / 0.03348 / 0.05853 / 0.05357 | 37.78456 / -0.64487 / 0.54247 / -0.81831 |

## Grid contacts and failures

The same 94.839 mm cube from the pilot was used in every condition. A grid-boundary contact means one or more negative-SDF points on a face of that cube. An extracted mesh touch means a vertex within 0.0001 mm of a face. These checks flagged **475/800** scored predictions on the grid and **321/800** on the extracted mesh. Per-condition entries show contacting seeds / scored seeds, maximum unique negative boundary points at any seed, and seeds with a mesh touch. Per-face and per-seed counts are in the results.

| Potato | Original | Pin | Peel 1 | Peel 2 | Peel 3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 5R1-4 | 16/16; 41; 16 | 16/16; 41; 16 | 16/16; 45; 16 | 16/16; 46; 16 | 16/16; 43; 16 |
| 5R3-1 | 16/16; 6; 2 | 16/16; 6; 2 | 16/16; 6; 2 | 16/16; 6; 2 | 16/16; 6; 2 |
| 2R2-6 | 1/16; 1; 0 | 1/16; 1; 0 | 1/16; 1; 0 | 1/16; 1; 0 | 1/16; 1; 0 |
| 2R3-10 | 4/16; 2; 0 | 2/16; 2; 0 | 4/16; 2; 0 | 4/16; 2; 0 | 4/16; 2; 0 |
| R4-10 | 0/16; 0; 0 | 0/16; 0; 0 | 0/16; 0; 0 | 0/16; 0; 0 | 0/16; 0; 0 |
| R8-2 | 0/16; 0; 0 | 0/16; 0; 0 | 0/16; 0; 0 | 0/16; 0; 0 | 0/16; 0; 0 |
| R10-1 | 10/16; 3; 0 | 12/16; 4; 0 | 10/16; 3; 0 | 10/16; 3; 0 | 10/16; 3; 0 |
| R12-7 | 16/16; 37; 15 | 16/16; 37; 15 | 16/16; 37; 15 | 16/16; 37; 15 | 16/16; 37; 15 |
| 3R2-10 | 16/16; 134; 16 | 16/16; 130; 16 | 16/16; 134; 16 | 16/16; 134; 16 | 16/16; 134; 16 |
| 3R5-2 | 16/16; 84; 15 | 16/16; 114; 16 | 16/16; 84; 15 | 16/16; 85; 15 | 16/16; 84; 15 |

Coverage was **10/10** at intake, **10/10** after edit eligibility and **10/10** for the primary endpoint, with **160/160** fully scored seed sets. There were **0 invalid scored meshes** and **0 other scored prediction failures**. Every scored mesh was watertight and had positive finite volume.
An initial replay stopped before producing predictions because the shared inference code expected two model attributes that the multi-frame wrapper had omitted. After adding those bindings, the regenerated frame artifacts matched the reviewed inputs byte for byte. The corrected run used the verified freeze for replay and scoring.

## Development decision

The protocol's three checks were all met. The primary median was positive, leave-one-tuber-out means were all positive, and a majority of the ten selected tubers had positive contrasts. The strongest-peel controls and fixed-grid contacts qualify the development result. The intervention measures model sensitivity to image edits with different starting appearance and position. Reconstruction accuracy and the physical effect of removing a pin remain open. Both 36-object confirmation cohorts stayed closed.

## Reproduction

Run from the repository root using the environment and verified model artifacts in the one-frame CPU audit. Use fresh output and input directories. Inspect the generated overlays before sealing. The command below uses the saved visual review of these exact masks.

```sh
export DYLD_LIBRARY_PATH="$PWD/outputs/corepp_cpu_audit/runtime/libusb/1.0.30/lib"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
for phase in prepare seal noop score
do
  outputs/corepp_cpu_audit/venv/bin/python -m studies.regional_shape_v1.corepp_pin_multituber "$phase" \
    --source data/raw/3DPotatoTwin \
    --upstream outputs/corepp_cpu_audit/upstream/corepp-0d6bae40b9215332efd566e6bca83bea171b99e9 \
    --released outputs/corepp_cpu_audit/released \
    --out-dir outputs/corepp_pin_multituber/replay \
    --input-dir outputs/corepp_pin_multituber/replay_inputs \
    --review studies/regional_shape_v1/corepp_pin_multituber/visual_review.json || break
done
```
