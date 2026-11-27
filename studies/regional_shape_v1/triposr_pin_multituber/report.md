# Do CoRe++ and TripoSR favor the same recoloring sites?

Both models favored the pin on **3/10 potatoes** against the mean of three peel edits and **2/10** against the strongest peel patch. **10/10** development potatoes had both TripoSR comparisons. R8-2 and R12-7 favored the pin in both models under both controls. R4-10 agreed under the mean-peel comparison and tied in CoRe++ under the strongest-peel comparison. [Per-potato table](per_potato.csv) · [Detailed results](results.json)

## Paired comparisons

A positive contrast means recoloring the pin moved the surface farther from the unchanged prediction. TripoSR used one deterministic prediction per edit. CoRe++ values are the archived expanded-grid medians of paired seed contrasts. The strongest patch was selected within each model. For CoRe++, this was the fixed patch with the highest median displacement across seeds. The CSV gives all four TripoSR displacements and both strongest-patch identities. Values stay in each model’s own units. [Archived CoRe++ results](../corepp_pin_grid_boundary/results.json) · [Frozen protocol](protocol.md)

| Potato / frame | TripoSR vs mean peel (native) | CoRe++ vs mean peel (mm) | TripoSR vs strongest peel (native) | CoRe++ vs strongest peel (mm) | Grid / mesh contacts |
| --- | ---: | ---: | ---: | ---: | ---: |
| [5R1-4](5R1-4/overlay.png) / 362 | -0.00233012 (peel) | -0.1484 (peel) | -0.00321178 (peel) | -0.2592 (peel) | 0 / 0 (6 predictions) |
| [5R3-1](5R3-1/overlay.png) / 360 | -0.01158273 (peel) | +0.0828 (pin) | -0.01486456 (peel) | +0.0623 (pin) | 0 / 0 (6 predictions) |
| [2R2-6](2R2-6/overlay.png) / 358 | -0.00607917 (peel) | +0.7922 (pin) | -0.00651679 (peel) | +0.7803 (pin) | 0 / 0 (6 predictions) |
| [2R3-10](2R3-10/overlay.png) / 363 | -0.00810505 (peel) | +1.1408 (pin) | -0.00921849 (peel) | +1.1219 (pin) | 0 / 0 (6 predictions) |
| [R4-10](R4-10/overlay.png) / 352 | +0.01094929 (pin) | +0.0027 (pin) | +0.01016367 (pin) | +0.0000 (tie) | 0 / 0 (6 predictions) |
| [R8-2](R8-2/overlay.png) / 350 | +0.00247480 (pin) | +1.7639 (pin) | +0.00069124 (pin) | +1.6851 (pin) | 0 / 0 (6 predictions) |
| [R10-1](R10-1/overlay.png) / 362 | -0.00745820 (peel) | +0.2764 (pin) | -0.01352872 (peel) | +0.2281 (pin) | 0 / 0 (6 predictions) |
| [R12-7](R12-7/overlay.png) / 353 | +0.00266594 (pin) | +0.0966 (pin) | +0.00239017 (pin) | +0.0777 (pin) | 0 / 0 (6 predictions) |
| [3R2-10](3R2-10/overlay.png) / 367 | -0.01176646 (peel) | +0.5071 (pin) | -0.01682115 (peel) | +0.4288 (pin) | 0 / 0 (6 predictions) |
| [3R5-2](3R5-2/overlay.png) / 359 | -0.00244442 (peel) | +1.9621 (pin) | -0.00912892 (peel) | +1.9810 (pin) | 0 / 0 (6 predictions) |

| Paired direction | Mean peel | Strongest peel |
| --- | ---: | ---: |
| Both pin | 3 | 2 |
| Both peel | 1 | 1 |
| CoRe++ pin, TripoSR peel | 6 | 6 |
| CoRe++ peel, TripoSR pin | 0 | 0 |
| At least one tie | 0 | 1 |
| Unavailable | 0 | 0 |

CoRe++ pin / tied / peel / unavailable counts were **9 / 0 / 1 / 0** against mean peel and **8 / 1 / 1 / 0** against strongest peel. TripoSR counts were **3 / 0 / 7 / 0** and **3 / 0 / 7 / 0**. The TripoSR tie tolerance was 1e-6 native units. CoRe++ retained its archived exact sign convention.

## Input matching and replay

All ten enrolled frames came from the archived registered development roster. The separate 2R1-10 / 364 pilot and fresh cohorts stayed closed. The archived four locations were mapped through the TripoSR crop and 512-pixel resize. Each potato’s four sites shared one mask shape and the same realized per-pixel RGB delta after joint capping. Matching passed for **10/10** potatoes. Each edit changed **1,153–6,179 pixels**, with zero off-mask changes and mean RGB L2 strength of **4.17–155.90** on a 0–255-equivalent scale. The transported support was partial on 2R2-6 and R12-7, as the crops show. The model’s tokenizer received the exact frozen tensors. [Input hashes and edit checks](frozen_inputs.json) · [All overlays](overlay_sheet.png)

Exact unchanged/no-op replay passed for **10/10** potatoes at the tokenizer, triplane, density, vertex and face arrays. The largest mean numerical self-distance was **4.51e-09 native units** and the largest individual closest-triangle self-distance was **8.62e-06**. The first launcher stopped before edited inference after applying an extra gate to the latter value. The corrected runner used the protocol’s exact replay gate and preserved every input, overlay and the contrast tie rule. [Replay checks](no_op_replay.json) · [Correction and hash check](replay_gate_correction.json)

## Meshes, failures and runtime

**60/60** recorded meshes met the validity criteria. **0/60** predictions had solid lattice-face nodes and **0/60** had mesh vertices within the face tolerance. The CPU harness reused official checkpoint revision `5b52193`, a fixed 128³ extraction lattice and density threshold 25. The successful run took **6.23 min** wall time including setup and distance scoring. Forward and mesh extraction accounted for **6.03 min** elapsed and **15.79 CPU-min** on four threads. [CPU harness](../corepp_cross_model/report.md) · [Per-condition records](results.json)

There were no matching, replay, inference or mesh failures.

These comparisons measure response to recoloring at matched locations within each model. TripoSR receives RGB alone and CoRe++ receives RGB-D. Resize, RGB capping and coordinate units also differ between models. The result concerns prediction sensitivity on these ten development frames. Reconstruction accuracy and physical marker removal remain open.

## Reproduction

Run from the repository root with the archived development RGBA inputs and the local TripoSR assets described in the [CPU harness report](../corepp_cross_model/report.md#reproduce). The two phases write to a fresh directory. All replay gates are recorded before edited prediction begins.

```sh
export DYLD_LIBRARY_PATH="$PWD/outputs/corepp_cpu_audit/runtime/libusb/1.0.30/lib"
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
triposr_replication=$(mktemp -d)
triposr_python=outputs/corepp_cpu_audit/venv/bin/python
"$triposr_python" -m studies.regional_shape_v1.triposr_pin_multituber freeze --out "$triposr_replication" &&
"$triposr_python" -m studies.regional_shape_v1.triposr_pin_multituber score --out "$triposr_replication"
```

[Runner](../triposr_pin_multituber.py)
