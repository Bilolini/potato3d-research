# Feasibility checkpoint — 2026-11-13

The initial workspace contained only `CSE527_3DPotatoTwin_Codex_Context.md`.
No PDFs, dataset, implementation or project-local Git repository was present.
Git resolves to an ancestor repository; this project does not stage or alter it.

## Implementation sequence

1. Verify public demo files, units, alignment metadata and IDs; keep an analytic fallback.
2. Establish millimeter coordinates, explicit belt-plane assumptions, three CPU baselines,
   deterministic geometry metrics and independent analytic checks.
3. Save immutable input manifests, mesh exports, per-frame metrics, object-level summaries,
   environment/configuration records and side-by-side visualizations.
4. Run a small failure-mode study before designing a contribution. Do not fit priors
   or tune parameters against demo reference shapes.

## Source and access checks

- [Demo release](https://github.com/UTokyo-FieldPhenomics-Lab/corepp/releases/tag/demo_dataset)
  is publicly reachable. GitHub API release ID 167985504; asset ID 182924227;
  published 2024-07-31; archive size 278,967,884 bytes. It advertises five objects.
  Archive contents and actual alignment were audited below.
- [Full dataset](https://huggingface.co/datasets/UTokyo-FieldPhenomics-Lab/3DPotatoTwin)
  is gated: login and agreement to share account information are required. The
  public card labels the license MIT and recommends at least 150 GB free space.
  No access agreement is accepted and no full download is attempted. The older
  ~111 GB estimate is unverified; card content is not proof of accessible files.
- [CoRe++ paper, v3](https://arxiv.org/html/2407.21341v3) was available as HTML.
  Its complete-mesh postprocessing uses a convex hull; the Chamfer equation is
  squared while surrounding text calls the unit mm. We explicitly use unsquared
  mean bidirectional distance in mm and do not compare scores directly.
- [PointRAFT paper, v2](https://arxiv.org/html/2512.24193v2) was available as HTML.
  Direct weight regression and stage-specific GPU times do not establish shape
  completion quality or CPU end-to-end speed.
- [3DPotatoTwin paper](https://doi.org/10.1016/j.plaphe.2025.100123): DOI and publisher
  full-text fetch failed (403); the author-hosted PDF returned 404 and PMC required
  browser verification. Its abstract/bibliographic record was checked through
  [PubMed](https://pubmed.ncbi.nlm.nih.gov/42041015/), but the full methods, figures
  and physical-volume calibration **were not independently read**. No local attachment exists.

## Verified environment

Actual CPU: **Apple M2 Pro** (`sysctl -n machdep.cpu.brand_string`); macOS 26.6.2,
arm64. Default system Python was 3.13.1; a project-local Python **3.12.14** virtual
environment was created using uv and an already-installed Homebrew interpreter.
CPU wheels installed successfully for NumPy 2.5.4, SciPy 1.18.1, Trimesh 4.12.2,
Rtree 1.4.1, Matplotlib 3.11.2, Plotly 6.9.0, PyYAML 6.0.3 and pytest 9.2.0.
`uv.lock` records exact transitive versions and artifacts; locked offline sync
is checked. Open3D was not installed or probed because SciPy/Trimesh/Rtree cover
the required CPU functionality. Its macOS compatibility remains unverified.

## Verified demo inventory and alignment

Archive SHA256: `c89fd95fba3284559d5b79a5679bf4bc5a9da96cb0fbc0bc9eeb6c7d8fb33fa2`.
The extracted dataset has **5 unique objects, 138 partial PLY frames, and only 5
explicitly registered source/reference pairs**. Exact paths, IDs and checksums
are in `data/demo_manifest.json`; RGB/depth counts are also recorded there.
Other frames are not scored with the center frame's matrix.

The bundled `3_pair/transform.py` applies JSON `T` to RGB-D points to overlay SfM.
The implementation equivalently maps SfM into the named camera frame with `T^-1`,
then converts both to canonical mm with z above an assumed 350 mm belt depth.
`T` is rigid and proper for every pair. No reference-driven adjustment occurs.
Approximate physical camera-to-belt depth is supported by PointRAFT section 2.2.1
for the 2023 setup; exact belt plane/tilt are absent from demo metadata and are
not independently calibrated. Units are corroborated by meter-labeled registration
metadata, camera depths, physical scale and visible-surface overlap.

Fixed-seed 1,500-point alignment checks measure raw partial-to-reference triangle
distance, with no ICP or fitting:

| ID | Partial points | Mean / p95 overlap error (mm) | Reference faces | Boundary edges |
|---|---:|---:|---:|---:|
| 2R2-8 | 22,085 | 0.576 / 1.556 | 41,138 | 874 |
| 4R3-4 | 15,847 | 0.491 / 1.272 | 31,386 | 728 |
| 5R3-2 | 10,955 | 0.698 / 1.773 | 21,966 | 418 |
| R13-8 | 38,302 | 0.721 / 1.767 | 47,542 | 774 |
| R7-7 | 5,604 | 0.532 / 1.423 | 10,910 | 454 |

All raw references have consistent winding but are **not watertight** and contain
12–18 degenerate triangles. They remain unchanged; direct mesh volumes are
ineligible. Volume targets from the CSV are stored separately, not inferred from
open-mesh signed integrals. No independent displacement-measurement protocol was
verified. Released registration residuals and measured overlap are not a proof
of correct hidden-surface registration.

`2R2-8` requires special review: transformed reference extent is approximately
88×81×67 mm while listed physical dimensions are 51×55×49 mm and reported SfM
volume is 86 mL. The raw open mesh's origin-dependent signed integral is roughly
243 mL, **not a valid volume measurement**. Its partial cloud overlaps the larger
reference closely, so changing scale using the CSV would corrupt that alignment.
It is retained and flagged; the inconsistency is not resolved or silently excluded.

## Milestone status

- **Milestone 0:** done for a public smoke test; full-data access and measurement
  validation remain outstanding for a research benchmark.
- **Milestone 1:** done. Three CPU baselines, 16 tests, analytic volume controls,
  five aligned demo pairs, saved closed predictions and PNG/offline HTML viewers,
  per-frame geometry/volume/runtime records and reproducibility checks.
- **Milestone 2:** initial synthetic pilot only: two objects × four conditions.
  Evidence and limits are in `docs/experiment_log.md`.
- **Milestones 3–4:** contribution and final course showcase remain future work.

## Follow-up checkpoint

The next stage is recorded in `docs/calibration_followup.md` and
`docs/height_development_report.md`. Depth PNGs retain usable background, enabling
a reference-free plane-proxy audit; this does not yet certify a physical support
plane or correct `2R2-8` metadata. The fresh sealed synthetic study completed
720 predictions over 12 families, 24 ambiguous hidden shapes and 6 conditions.
There are 31 passing tests and fixed robust-height/cap ablations with family-level
paired statistics. The predefined outlier hypothesis is supported on this
development generator, with unfavorable clean/missing-patch cases reported.
No larger download, training, real-data retuning or novelty claim was introduced.

The subsequent spatial confidence stage (`docs/spatial_confidence_report.md`)
completed 588 development and 1,344 independent-confirmation predictions with
47 passing tests and no mesh failures. It meets its predefined clean/isolated-spike
criteria but fails coherent patches and does not solve calibration or hidden-shape
ambiguity. Real measurement/scale/calibration blockers above remain unresolved;
the new results are synthetic confirmation only.

## Boundaries

Use the public demo only as a smoke/development check, never a held-out benchmark.
Do not learn templates from its reference meshes, align predictions to references,
train a neural model, download the full dataset, or implement the proposed contribution
before inspecting measured baseline failures.
