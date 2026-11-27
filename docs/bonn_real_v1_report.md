# Real-data checkpoint: Bonn laboratory fruit

The point-cloud-reference adapter and a reproducible classical completion study
are complete. **24/24 development and 72/72 holdout predictions succeeded**, with
valid closed meshes and no ellipsoid optimizer nonconvergence. The full primary
hypothesis **did not pass**: fitting improved mean Chamfer versus the population
prior, but the paired F5 interval crossed zero. Training templates had the best
descriptive mean scores. This is baseline evidence, not an established novel
method, official benchmark result, or potato/greenhouse generalization claim.

## Data and separation

The [official Bonn dataset](https://www.ipb.uni-bonn.de/data/shape_completion/index.html)
provides RGB-D inputs and laser point-cloud references. The adapter follows the
[official loader](https://github.com/PRBonn/shape_completion_toolkit/blob/master/dataloader.py):
metric depth, column-major intrinsics, supplied camera-to-fruit pose, then mm.
No reference-based alignment, normalization, filtering or belt frame is fitted.
The complete [protocol](bonn_real_v1_protocol.md),
[member manifest](../data/bonn_real_v1_manifest.json) and
[source seal](bonn_real_v1_seal.json) were fixed before new geometry access.

- Training: lab1, lab18, lab23, lab37, lab52, lab54, lab60, lab74, official train.
- Development: lab46, lab61, lab75, official validation.
- Local holdout: lab16, lab17, lab29, lab30, lab32, lab45, lab48, lab62, lab63,
  lab76, lab77, lab90, official validation. Prior audit val/lab15 is excluded.

There is one fixed first available frame per fruit, all frame 00001 here. No
frame was selected by reference quality. The eight training complete clouds alone
define canonical population medians and convex candidate templates. Population
center is [0.4912, 1.0151, -1.5122] mm; radii [44.2208, 42.4732, 52.4342] mm.
The methods use at most 2,500 deterministic input points each.

Only 98 pinned ZIP members were fetched: **55,004,299 compressed asset bytes**,
55,062,984 HTTP body bytes from selected ranges (including ZIP entry-header
budgets), 109,051,839 expanded
asset bytes. All passed ZIP size/CRC checks and content SHA verification;
[receipts](bonn_real_v1_download_receipt.json) record every member. The 8.37 GB
archive was not downloaded. Greenhouse fruit were deferred based on metadata
sizes before any geometry/score inspection; the preflight reservation is retained.
Separate dataset terms remain unverified. Raw assets stay ignored and excluded
from the source archive; no account, agreement or submission was initiated.

Observation loading has no reference dependency. All six prediction exports for
each holdout fruit preceded opening its reference geometry. The verified event
logs are in `outputs/bonn_holdout_v1/events.jsonl`. Training/development/holdout
IDs and source/parameter hashes are distinct and explicit. Holdout retrieval
required the frozen development selection.

## Development and selected setting

The only selected parameter was ellipsoid prior strength, with exactly two
registered options. Equal-object mean Chamfer averaged across raw and filtered
conditions was 4.7604 mm for lambda 0.15 and 4.9735 mm for 0.5. The rule selected
**0.15**. The [selection](bonn_real_v1_selection.json) freezes the source seal,
all training-prior artifact hashes and development-result hash. Templates use a
fixed strength 0.15 and 15 fitting iterations, selected only by observation fit
plus the prior penalty. No new candidate or parameter was tried on holdout.

## Holdout results

Equal means over twelve objects. Chamfer is unsquared, symmetric and in mm;
F5 is the harmonic precision/recall at inclusive 5 mm. All 31,473–47,717 native
reference points per fruit are scored against 10,000 area-uniform prediction
samples. Native reference density affects the metric. These definitions differ
from official competition scoring; do not compare against published leaderboards.

| Input | Method | Chamfer mm | F5 | Raw fidelity mm | Used fidelity mm |
|---|---|---:|---:|---:|---:|
| Raw | Population ellipsoid | 5.1798 | 0.5945 | 5.6524 | 5.6524 |
| Raw | Fitted ellipsoid, 0.15 | 4.6234 | 0.6298 | 2.5944 | 2.5944 |
| Raw | Training template | 4.3040 | 0.6742 | 2.4929 | 2.4929 |
| Depth component | Population ellipsoid | 5.1798 | 0.5945 | 5.6524 | 5.6033 |
| Depth component | Fitted ellipsoid, 0.15 | 4.6241 | 0.6294 | 2.6089 | 2.5555 |
| Depth component | Training template | 4.3029 | 0.6740 | 2.4920 | 2.4421 |

Fidelity is mean exact point-to-triangle distance on fixed subsets of at most
1,500 raw/used observations; it is not a hidden-region score. Point-cloud
references have no verified triangle topology or physical volume target, so
reference-volume errors remain null. Prediction volumes are descriptive only.

The two co-primary checks compare fitted minus population ellipsoid on filtered
inputs, paired over all twelve objects, 10,000 object-bootstrap replicates:

| Check | Mean delta | Paired 95% interval | Prespecified criterion | Pass |
|---|---:|---|---|---|
| Chamfer mm | -0.5557 | [-1.0149, -0.0647] | upper bound <0 | Yes |
| F5 | +0.0349 | [-0.0484, +0.1083] | lower bound >0 | No |

Both were required. The full hypothesis is not accepted. Template comparisons
remain descriptive; no extra superiority test was added after scoring.

## Failures and limits

The fitted ellipsoid is worse than the population prior on lab48: Chamfer
4.2296→5.4152 mm and F5 0.7744→0.4786. Template F5 also falls to 0.5876 there.
Lab30 remains difficult: population/fitted/template Chamfer 7.8781/6.4362/4.7675
mm. Training templates have the best mean but lose to population Chamfer on
lab17, lab29, lab48 and lab77. Every object remains in the table/plot and raw CSV.

The fixed depth-component filter retains 99.9623% of holdout points on average
(minimum 99.8477%); it changes aggregate geometry little here. This subset does
not establish that the filter solves significant contamination. It can discard
genuine disconnected structures and is not a verified observation-confidence
label. The small development split is a limited selection budget. Axis-aligned
ellipsoids miss irregular structure; convex templates cannot recreate concavity,
and one-sided matching leaves unseen geometry underdetermined. There are no
verified visible/hidden labels, no potato belt calibration, and no verified
independent cultivar/session split. Existing synthetic narrow-feature and
coherent-patch negative results remain relevant and unchanged.

## CPU cost and reproducibility

Python 3.12.14, Apple M2 Pro, CPU only, fixed dependency lock and one-thread
numerical environment. Development runner elapsed **5.58 seconds**; holdout
**19.94 seconds**, including metrics, PLY exports and offline HTML viewers.
Filtered-condition mean fit time per prediction: population 0.00042 s,
ellipsoid 0.02788 s, template 0.25172 s. These are one-machine measurements,
not cross-platform speed guarantees. The external `time -l` wrapper could not
read sandboxed `kern.clockrate`; it returned nonzero after the experiment had
completed. Peak memory was therefore not obtained and the holdout was not rerun.

**71 tests passed** before scoring. [Verification](bonn_real_v1_verification.json)
checks all 96 prediction artifacts, confirms prediction-before-reference order
for all fifteen evaluated fruit, and verifies **77 earlier output JSONs unchanged**.
Rebuilding the eight training priors was bitwise identical. All eight predictions
for development lab46 were reproduced bitwise without loading its reference or
recomputing a score. **No holdout predictions or scores were rerun.**

Run locations:

- `outputs/bonn_prior_v1/`: training priors and hashes.
- `outputs/bonn_development_v1/`, `outputs/bonn_holdout_v1/`: CSV/JSON, environment,
  parameters, PLY geometry and per-fruit offline `comparison.html` viewers.
- `outputs/bonn_figures_v1/object_metrics.png`: all-object raw/filtered plot.
- `outputs/bonn_verification_v1/`: training/development reproduction evidence.
- `outputs/bonn_reproduction_v1/`: source/protocol/compact-evidence archive with
  SHA manifest, raw data excluded. Restore this snapshot after later code changes.

Fresh-path reproduction commands are in the root README. To verify existing
evidence without rescoring holdout, run `scripts/check_bonn_reproducibility.py`
with a new `--out`. Do not retune on the recorded objects.

Next work should consolidate the final course report/showcase and related-work
positioning around the supported findings and failed hypotheses. Establishing a
new contribution, potato-specific transfer, certified calibration or field
performance needs new evidence and a new protocol.
