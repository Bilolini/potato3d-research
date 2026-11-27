# Does RAFT fusion help a learned potato weight estimator?

On 30 previously scored development potatoes, fusing three spaced RGB-D views lowered the three-seed learned estimator’s weight MAE from **26.95 to 25.26 g**. The paired change was **−1.69 g** (95% tuber-bootstrap interval **−4.03 to +0.86 g**). Only one of three individual seeds improved with fusion. For the matched area × height control, MAE went from **15.43 to 14.94 g**, a paired change of **−0.49 g** (95% interval **−1.67 to +0.63 g**). Fusion’s benefit is uncertain for both estimators. The simple control had lower MAE on both input types. [Machine-readable results](results.json) · [Per-potato predictions and errors](per_potato.csv)

## Paired results

All 117 training potatoes and all 30 evaluation potatoes had complete inputs and measured weights. All six neural fits completed. The intervals resample the 30 evaluation potatoes 10,000 times, keeping the center and fused errors paired. Negative changes favor fusion. Seed-specific intervals describe potato-level variation conditional on each seed.

| Estimator | Scored | Center MAE (g) | RAFT-fused MAE (g) | Fused − center (g) | 95% interval (g) | Fusion wins / ties / losses |
|---|---:|---:|---:|---:|---:|---:|
| Learned, mean prediction of 3 seeds | 30/30 | 26.95 | 25.26 | −1.69 | −4.03 to +0.86 | 18 / 0 / 12 |
| Matched area × height regression | 30/30 | 15.43 | 14.94 | −0.49 | −1.67 to +0.63 | 18 / 0 / 12 |

| Seed | Shared refit epochs | Center MAE (g) | RAFT-fused MAE (g) | Fused − center (g) | 95% interval (g) |
|---|---:|---:|---:|---:|---:|
| 133 | 97 | 22.98 | 23.74 | +0.76 | −2.12 to +3.93 |
| 527 | 100 | 33.05 | 34.81 | +1.76 | −0.58 to +4.22 |
| 2401 | 97 | 36.00 | 24.25 | −11.75 | −16.82 to −6.44 |

Across individual seeds, the sample standard deviation was 6.83 g for center MAE, 6.25 g for fused MAE and 7.53 g for the paired change. The fusion result depended strongly on initialization and training stochasticity. The primary comparison kept all three seeds. It applies to this small CPU adaptation trained on 117 potatoes and evaluated on 30 previously studied potatoes. [Seed and primary endpoints](results.json)

## Matched inputs and fitting

The study used weight in grams including the tack (`weight_g_inctack`). We reused the fusion-traits study’s exact 117 common training potatoes and 30 evaluation potatoes, plus the frozen lower, center and upper frames. These 30 potatoes had already been scored in development. The 45 SAM 2 confirmation potatoes, the ten geometry-pilot potatoes and the reserved cohorts stayed closed. [Fusion-traits study](../raft_fusion_traits_v1/report.md) · [Frozen protocol](protocol.md) · [Frame manifest](frame_manifest.json)

The center input used the registered center frame’s released segmented cloud in its own camera coordinates. Fusion moved the same three selected clouds into that camera frame with the archived RAFT-Small RGB-D transforms. The saved link composition, fused voxel counts, hull areas and heights replayed on all 147 potatoes. Each selected PLY had to project one-to-one into the provided mask and valid raw depth within 0.1 px and 0.1 mm. Feature extraction accessed RGB, depth and segmented PLYs, with no SfM geometry or SfM alignment. The released PLY depth filter uses measured tuber thickness (`x3_depth_mm`), so both input conditions retain that dependency. [Input replay ledger](inputs_manifest.json) · [Frozen RAFT settings and checkpoint](../raft_fusion_traits_v1/protocol.md) · [Released depth support](../raft_fusion_geometry_v1/protocol.md)

Both inputs used the same 1 mm centroid voxelization and the same deterministic rule to sample 1,024 points. The linear control used XY hull area times robust height on those sampled points, with a separate intercept and slope per input condition. The learned estimator used mean-centered XYZ divided by a fixed 100 mm to preserve metric size, plus the same height scalar divided by 100 mm. Height was the nominal 350 mm belt depth minus the fifth-percentile axial depth, floored at zero. Converting stored points back to millimeters reproduced sample hull areas within 0.00015 mm² and stored heights within 0.000003 mm across both inputs. [Input code](inputs.py) · [Control coefficients](control_fit.json)

The authors’ runner requires `torch-cluster`, which was unavailable in the local CPU environment. We trained a 52,409-parameter CPU adaptation from scratch. It retains two point-neighborhood aggregation stages, global pooling and a separate height branch. It uses fewer anchors and neighbors, precomputed neighborhoods, narrower layers, LayerNorm and SiLU. On eight training-only potatoes, the prespecified smoke check reduced training MAE from 52.28 to 23.47 g for center and from 52.40 to 12.13 g for fusion. Those fits were discarded. [Authors’ model](https://github.com/pieterblok/pointraft/blob/main/models/pointraft.py) · [Authors’ installation requirements](https://github.com/pieterblok/pointraft/blob/main/INSTALL.md) · [CPU model code](run.py) · [Smoke check](smoke_fit.json)

Both arms had the same potato-level inner split (93 fit, 24 selection), architecture, optimizer, budget and three seeds. For each seed we chose one common epoch from the two inner-validation MAE curves, then refit each arm through that epoch on all 117 training potatoes. The learned endpoint takes the mean of the three seed predictions per potato before computing absolute error. All evaluation predictions were saved before joining the 30 evaluation weights. [Frozen analysis](analysis_freeze.json) · [Train-only selection and checkpoint hashes](train_fit.json) · [Frozen evaluation predictions](predictions_before_targets.json)

## Runtime and failures

On the local arm64 macOS CPU with four PyTorch threads, archive replay, calibration checks and input construction took 19.13 s for 147 paired inputs. The small-fit check took 3.89 s. Training and model selection took 48.19 s for center and 48.36 s for fusion across all three seeds. The three saved fits together took 0.028 s for center predictions and 0.027 s for fused predictions across all 30 potatoes, with checkpoint loading and geometry preparation timed separately from forward inference. Fitting the two simple control regressions and generating their predictions took under 0.01 s. The runtime here reuses verified transforms. The archived trait run reported 111.36 s for the RAFT condition over the 30 evaluation potatoes, including optical flow, alignment and feature extraction. [Runtime components](results.json) · [Original RAFT timing](../raft_fusion_traits_v1/report.md)

There were no new registration, input, fitting or scoring failures within the enrolled cohort. The earlier trait run excluded `4R5-9` from the common training set after a required RAFT link had too few valid correspondences. It remains outside this study. The six refit checkpoints, epoch traces and failure status are saved, and the reported MAEs, changes, intervals and counts were recomputed from the per-potato table. [Archived failure log](../raft_fusion_traits_v1/failures.csv) · [Saved fits](fits/) · [Fit records and hashes](train_fit.json)

## Reproduce

Run from the workspace root in a fresh copy of the study without generated outputs, retaining the released data, archived trait caches, and both study scripts and protocol. The comparison uses the archived CPU virtual environment (Python 3.13.1, PyTorch 2.7.1, NumPy 2.2.6 and SciPy 1.16.0). Input regeneration replays the cached RAFT links. The final stage writes the evaluation results once.

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
python=outputs/corepp_cpu_audit/venv/bin/python
study=studies/raft_pointcloud_weight_v1
"$python" "$study/inputs.py" freeze &&
"$python" "$study/inputs.py" extract &&
"$python" "$study/run.py" freeze &&
"$python" "$study/run.py" control &&
"$python" "$study/run.py" smoke &&
"$python" "$study/run.py" train &&
"$python" "$study/run.py" predict &&
"$python" "$study/run.py" score
```
