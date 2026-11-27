# Single-scan rescan screen on ten development potatoes

**No. Exact random selection left a lower mean error at the 20% rescan budget, so the exposure candidate is closed.** Appearance sensitivity lowered the accepted error by **0.1039 mm** compared with depth rejection and raised it by **0.0756 mm** compared with the exact random expectation. These are mean unedited reference errors for the eight accepted potatoes. [Frozen protocol](../corepp_rescan_screen_protocol.md) · [Machine-readable results](results.json)

| Rule | Flagged potatoes and their unedited errors | Mean accepted error (mm) |
| --- | ---: | ---: |
| Sensitivity | R12-7 (2.7003 mm), 3R2-10 (2.7397 mm) | 3.0981 |
| Depth rejection | R4-10 (2.0935 mm), 3R5-2 (2.5149 mm) | 3.2021 |
| Uniform random | Each of the 45 pairs has probability 1/45 | 3.0225 |

Both deterministic rules accepted 5R1-4, the highest-error potato at **4.7386 mm**. Each rule also accepted all four potatoes with errors above the cohort mean. Across the 45 random pairs, accepted error ranged from **2.7091 to 3.2883 mm**. Flagging 2R3-10 and 5R1-4 gave the lowest random-pair mean, and flagging R4-10 and R8-2 gave the highest. Of the 45 pairs, **30** beat the sensitivity rule and **1** tied it. [All 45 pairs and flagged errors](random_pairs.csv)

## Per-potato results

| Potato / frame | Unedited error (mm) | Sensitivity (mm) | Depth rejected | Sensitivity rule | Depth rule | CPU seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| R12-7 / 353 | 2.7003 | 0.4573 | 12.587% | Flagged | Accepted | 48.5 |
| 3R2-10 / 367 | 2.7397 | 0.4187 | 12.926% | Flagged | Accepted | 48.1 |
| R10-1 / 362 | 2.5020 | 0.2942 | 6.845% | Accepted | Accepted | 47.9 |
| 5R1-4 / 362 | 4.7386 | 0.2877 | 6.952% | Accepted | Accepted | 48.0 |
| 2R2-6 / 358 | 3.6812 | 0.2355 | 10.410% | Accepted | Accepted | 48.9 |
| 3R5-2 / 359 | 2.5149 | 0.2066 | 13.807% | Accepted | Flagged | 48.2 |
| 2R3-10 / 363 | 3.8137 | 0.2023 | 10.008% | Accepted | Accepted | 47.7 |
| R8-2 / 350 | 1.8248 | 0.1959 | 8.840% | Accepted | Accepted | 49.2 |
| R4-10 / 352 | 2.0935 | 0.1776 | 14.204% | Accepted | Flagged | 47.3 |
| 5R3-1 / 360 | 3.6165 | 0.1244 | 11.197% | Accepted | Accepted | 48.4 |

## Verification and scope

The two rankings and flagged IDs were saved before they were joined to the archived unedited errors. Each sensitivity score is the median of 16 paired seed averages of the 0.9 and 1.1 exposure displacements, in mm. The depth comparator is the fraction of the foreground removed by the native depth filter, including zero depths. The computation used the fixed 30³ grid, RGB-D images and foreground masks. Reference geometry and marker annotations played no role in scoring. [Scan-only scores and ranking seal](scan_only_scores.json) · [Per-potato CSV](per_potato.csv)

All **160** gain-1.0 replays matched exactly on the tensor, latent, SDF, grid labels, canonical mesh and volume. All unchanged predictions matched the expanded-grid archive. The largest numerical self-distance was **9.72e-05 mm**. Among **480** unchanged and perturbed predictions, **0** had outer-grid negative SDF and **0** meshes touched an outer face. There were no mesh failures. Scan scoring consumed **482.3 CPU seconds** in total, including the no-op checks and excluding model startup. Scoring wall time was **100.9 s** across 5 workers.

The comparison measures selection on previously analyzed development objects. The benefit of a second view remains unmeasured. All previously scored fresh cohorts stayed closed.

## Reproduction

Run from the repository root with a new output directory. Phase `score` uses scan data and archives of unchanged predictions. Phase `evaluate` joins the score to the frozen reference-error table.

```sh
export DYLD_LIBRARY_PATH="$PWD/outputs/corepp_cpu_audit/runtime/libusb/1.0.30/lib"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
for phase in freeze score evaluate
do
  outputs/corepp_cpu_audit/venv/bin/python -m studies.regional_shape_v1.corepp_rescan_screen "$phase" \
    --upstream outputs/corepp_cpu_audit/upstream/corepp-0d6bae40b9215332efd566e6bca83bea171b99e9 \
    --released outputs/corepp_cpu_audit/released \
    --input-dir outputs/corepp_pin_multituber/inputs \
    --out-dir outputs/corepp_rescan_screen/replay --workers 5 || break
done
```
