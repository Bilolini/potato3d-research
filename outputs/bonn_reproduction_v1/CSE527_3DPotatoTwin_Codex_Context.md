# CSE527 Project Context for Codex

> **Working project:** Reliable CPU-Based 3D Shape Completion from Partial RGB-D Potato Scans  
> **Status:** Research direction selected for a feasibility prototype; precise contribution is a **hypothesis**, not yet an established novel result.  
> **Last updated:** 2026-11-12  
> **Intended reader:** Codex, acting as an implementation and experimental research assistant.  
> **Immediate task:** Build a **small, reproducible CPU-only baseline and evaluation pipeline** before adding the proposed method.

---

## 0. Instructions for Codex — start here

You are joining a graduate Computer Vision (CSE527) final project. Read this document before editing files or choosing models. This is a **3D reconstruction research project**, not a potato classification project or a point-cloud-to-weight regression project.

**On your first pass:**

1. Inspect the current repository and environment. Determine whether this is a new/empty workspace, whether the PDFs are available, and whether any dataset is already present. Do not assume paths or files exist.
2. Read the `3DPotatoTwin`, `CoRe++`, and `PointRAFT` source papers if provided, prioritizing methods, figures, metrics, discussion, limitations, and future work. If they are not available, rely on the verified links below and **say what has not been checked**.
3. Produce a short **implementation plan and data-access report** in `docs/feasibility.md`, then implement a minimal runnable prototype rather than proposing an elaborate deep-learning architecture.
4. Create the project scaffold; implement robust data discovery/loading, unit/coordinate checks, at least two classical completion baselines, geometric evaluation, and a deterministic synthetic smoke test.
5. Prioritize a **working result on a small public demo**. Ask before downloading the full dataset or starting heavy training. Never claim a score unless it was actually measured on specified data.
6. After the baseline works, propose the smallest targeted experimental change likely to improve **observed-surface fidelity, hidden-surface reconstruction, uncertainty calibration, or robustness to depth errors**.

**Do not** silently switch to CoRe++/PointRAFT retraining, assume an NVIDIA GPU, use ground-truth meshes at test-time to construct predictions, or treat weight-regression performance as 3D geometry quality.

### Initial success condition (Milestone 1)

A documented command can read one genuine aligned partial/complete potato pair (or, until available, an analytic synthetic pair), generate two distinct completion meshes, compute meaningful geometry/volume metrics, and save a side-by-side 3D visualization and a machine-readable result. The pipeline must run on a **MacBook M2 Pro without NVIDIA CUDA**.

---

## 1. Academic context, motivation, and constraints

- Course: **CSE527 Graduate Computer Vision**. Professor emphasizes **3D reconstruction and geometric understanding**; the final project needs a research hypothesis, quantitative evaluation, a useful practical story, and a compelling demo.
- Motivation: Automated produce grading and yield measurement with **one inexpensive RGB-D camera** on a conveyor. The camera sees the exposed surface, not the underside; naive volume estimates are biased.
- Earlier greenhouse/plant dataset from Greece is **no longer available**. Do not assume any custom dataset, capture hardware, or privileged labels. Public data must suffice.
- Hardware: **Apple MacBook M2 Pro**. Baseline must run on CPU. Apple Metal/MPS may be used optionally after a CPU path works, but **CUDA is not available** and should not be required. No dependence on a dedicated NVIDIA GPU.
- Time: approximately **one-month student research scope**. Prefer NumPy/SciPy, Open3D (if macOS wheel works), Trimesh, scikit-image, and lightweight optimization. Avoid large network training, NeRF, diffusion, or 3DGS as core dependencies.
- Goal: A **defensible algorithmic contribution**. A paper replication, a benchmark-only study, or an attractive visualization without measurable improvement is insufficient.
- Priority order: (1) validity and data availability, (2) correctness and reproducibility, (3) a genuine 3D geometry question, (4) measurable improvement, (5) speed and demo polish.

### Working research question

> Can a CPU-efficient, observation-aware geometric method complete irregular potato shapes from noisy, partial RGB-D point clouds while preserving measured surfaces, quantifying ambiguity in hidden regions, and improving geometry/volume error over simple classical baselines?

### Important identifiability limit

**An unseen underside cannot be uniquely recovered from a single top-view scan.** Any method must use shape priors/assumptions and should communicate uncertainty. Multiple conveyor frames generally show a translating potato from nearly the same view; merging them can improve denoising, but **does not automatically reveal the bottom**.

---

## 2. Source papers — what they actually establish

### A. 3DPotatoTwin (dataset paper, 2025)

- Paper: *3DPotatoTwin*, Plant Phenomics **7 (2025), article 100123**.
- DOI: https://doi.org/10.1016/j.plaphe.2025.100123
- Data: https://huggingface.co/datasets/UTokyo-FieldPhenomics-Lab/3DPotatoTwin
- Data-preparation/registration code: https://github.com/UTokyo-FieldPhenomics-Lab/PotatoScan
- Relevant local attachment, if supplied: `3dpotatotwin.pdf`.

**What it does:** Curates **339 unique potato tubers** with about **20-30 conveyor RGB-D frames per tuber**, along with separately captured near-complete multiview SfM reconstructions and registrations linking partial and complete representations. Three cultivars. Uses a RealSense D405 above the conveyor and a separate photogrammetry setup to create reference geometry.

**Important limitations to inspect in the paper:** Semi-automatic registration relies on marker-based initialization and human verification; near-symmetric shapes create ambiguous orientations; the dataset contains imperfect registrations; images/geometry have acquisition artifacts; data variety is limited. The released complete mesh is a **high-quality reference**, not necessarily exact physical truth; verify physical-volume measurements and calibration before using them as targets.

**Availability caution:** The full dataset is large (approximately **111 GB** in the previous dataset audit), with access conditions. Do not fetch the full dataset automatically. Confirm current distribution, license/access, per-file download options, and whether the needed partial/full mesh pairs are really included.

### B. CoRe++ (completion model and principal baseline, 2025)

- Title: *High-throughput 3D shape completion of potato tubers on a harvester*.
- Paper: https://arxiv.org/abs/2407.21341
- Code: https://github.com/UTokyo-FieldPhenomics-Lab/corepp
- Small public demo asset: https://github.com/UTokyo-FieldPhenomics-Lab/corepp/releases/tag/demo_dataset
- Demo archive: `3DPotatoTwinDemo.zip` (~**279 MB**, as checked from the release listing).
- Relevant local attachment: `core++.pdf`.

**Pipeline:** masked/cropped **304 × 304 RGB-D** image -> CNN encoder (7 convolutional blocks, ~6.42M encoder parameters in paper Table 1) -> latent vector -> pre-trained **DeepSDF** decoder -> predicted signed distances -> closed mesh/post-processing -> volume. Decoder is trained first on complete shapes; encoder is trained afterwards. The best reported latent size is **32**. The author's mesh post-processing includes **convex hull extraction** over selected points and smoothing/watertightness procedures.

**Reported test results (not independently reproduced):** 51 held-out potatoes, 1,425 test RGB-D frames; Chamfer-type geometric error **2.8 mm**, F-score **85.0%** at **5 mm**, volume RMSE **22.6 mL**, and approximately **9.9-10 ms** reported shape-completion time. Reported center-image volume RMSE **18.2 mL**. Original CoRe (latent size 32) gives approximately **36.9 mL** volume RMSE; optimized DeepSDF can be more accurate but requires about **33 seconds** per shape due to per-instance optimization.

**Critical ablations (CoRe++ paper Table 6, volume RMSE):**

| Configuration | Volume RMSE |
|---|---:|
| Full CoRe++ | 22.6 mL |
| Without depth normalization | 34.3 mL |
| Without depth filtering | 41.1 mL |
| Without augmentation | 32.4 mL |
| Depth-only (no RGB) | 40.5 mL |
| Bounding-box crop instead of foreground mask | 33.0 mL |
| Earlier validation/post-processing strategy | 50.2 mL |

**Conclusions relevant to our work:** High sensitivity to depth noise and foreground masks; poorer performance on unusually large, concave, irregular potatoes; latent-size capacity trade-offs; frame-position sensitivity; full neural pipeline is **CUDA/GPU-oriented**, so reproducing its published performance is *not* required for initial CPU research. Convexification may erase concavities, but **do not assume that replacing convex hull with marching cubes must help**: an alternative marching-cubes configuration was among the author's ablations and performed worse under their settings. Geometry extraction and decoder errors must be disentangled.

**Specific open questions from Discussion:** cultivar and shape generalization, rare/extreme sizes, mask sensitivity, hardware/software integration, potentially rotating fruits to reveal the underside. The authors already did shape completion: a new basic completion network is not by itself a novelty claim.

### C. PointRAFT (direct regression alternative, updated 2026)

- Title: *PointRAFT: 3D deep learning for high-throughput prediction of potato tuber weight from partial point clouds*.
- Paper: https://arxiv.org/abs/2512.24193
- Code: https://github.com/pieterblok/pointraft
- Relevant local attachment: `pointraft.pdf` (the uploaded **arXiv v2 dated 2026-11-04**).

**Goal:** Predict weight **directly from partial 3D point clouds**, without completing a mesh. Uses PointNet++-style hierarchical backbone, **1,024 sampled XYZ points**, and a **height embedding** (MLP **1 -> 8 -> 8**) derived from camera-to-conveyor distance and observed highest point. Concatenated shape + height features feed a regression MLP (**1032 -> 512 -> 256 -> 1**). Uses Smooth L1 loss.

**Different dataset:** **859 unique potatoes**, four cultivars, three growing seasons, **26,688** point clouds. Published test set **172 potatoes / 5,254 scans**. A **different public subset** described in its README contains **2,053 point clouds from 73 test potatoes**; do **not** compare its scores with the larger published test set uncritically.

**Reported results:** weight MAE **11.7 g**, RMSE **17.1 g**, R² about **0.98**. Approximately **6.3 ms** reported point-cloud preprocessing + model inference on a GPU laptop. Versus PointNet++ without the height embedding, weight MAE reduced by **25.9%**. DGCNN is a strong competing regression backbone.

**Important full-pipeline runtime caveat:** The **6.3 ms** excludes RGB-D image loading, initial point-cloud creation, and expensive DBSCAN filtering. On one reported laptop, total processing time was **166.9 ms** per sample, with DBSCAN alone about **135.1 ms** (instance segmentation excluded). The paper recommends faster depth-image-connected-component or geometric filters.

**Ablations/future work:** performance deteriorates without augmentation, on rare very heavy tubers, under stacking and potentially tilt; predictions vary over multiple frames; authors suggest frame-consistency losses, MC-dropout uncertainty, adding orientation context, balancing rare sizes, faster filters, testing segmentation errors. **Most importantly: PointRAFT does not evaluate complete 3D shape recovery** and its weight MAE is **not comparable to CoRe++ volume RMSE or Chamfer distance**.

### D. Additional relevant prior art (do not claim these are new ideas)

- Symmetry-based fruit completion: https://doi.org/10.1016/j.biosystemseng.2020.07.003
- Original CoRe (2022), DeepSDF-based: linked from CoRe++ README and paper.
- Transformer-based fruit completion / T-CoRe (ICRA 2024): discussed in CoRe++.
- Bonn fruit completion benchmark (ICRA 2025): https://www.ipb.uni-bonn.de/data/shape_completion/index.html
- Statistical/parametric geometric fitting and template retrieval **already exist**. Their novelty, if any, must be a *specific justified variant* backed by matched experiments.

### Related handoff materials from prior analysis (if mounted)

- `3DPotatoTwin_Literature_Review_Research_Proposals.html`
- `CSE527_CoRePP_PointRAFT_Detailed_Analysis.html`

Use the PDFs and original papers as authoritative for claims; the HTML reports are prior synthesis only. Do not quote their estimated potential/feasibility scores as published scientific metrics.

---

## 3. Narrow project scope — initial decision

**Primary proposed method:** **Observation-aware, concavity-preserving classical completion**, with *uncertainty calibration* as an optional second contribution.

Try to improve one precise failure mode, not all of them at once:

1. Preserve measured visible surfaces (avoid replacing good observations with an overly smooth average shape).
2. Produce plausible hidden surfaces using explicit, modest geometric priors (symmetry, parametric fit, shape-library retrieval, or a blend).
3. Respect non-convexity where supported; quantify when a convex hull artificially inflates volume.
4. Prefer robust estimation under mask/depth outliers; distinguish sensor noise from true shape concavity.
5. Communicate uncertainty when the underside is poorly constrained.

**Potential algorithmic hypothesis:** A confidence-weighted fit with a smoothness/shape prior and explicit preservation of high-confidence observed regions outperforms global convex/ellipsoidal fitting, especially on concave or irregular tubers. This is **to be tested**, not assumed.

**Suggested formulation (design sketch, subject to refinement):**

For surface/shape parameters `S`, minimize an objective resembling

```text
E(S) = λ_obs  * Σ_i w_i * robust_distance(p_i, surface(S))
     + λ_prior * shape_prior_penalty(S)
     + λ_smooth * regularization(S)
     + λ_phys  * physical_feasibility_penalty(S)
```

where `w_i` decreases near unreliable depth boundaries/outliers, and shape priors are estimated **only from the training set**. This is *not* a required exact solver or claim of new mathematics. Investigate tractable representations before implementation.

**Phase-1 simplification:** If an explicitly non-convex shape model is too costly, establish a carefully evaluated convex/ellipsoidal baseline, a symmetry baseline, and a template-based method. Then identify error modes to choose the best targeted improvement. Do not start by building a full latent generative model.

---

## 4. Data acquisition and validation requirements

### Data priority

1. **First:** check existing files already present in the working directory.
2. **Next:** inspect the public **CoRe++ ~279 MB demo release** for one or more genuine aligned RGB-D / complete mesh pairs.
3. **Then:** verify access to a reasonable subset of the full 3DPotatoTwin dataset; require user approval for a large download or access application.
4. **Fallback:** if no aligned potato pairs are available, develop/evaluate the pipeline on **synthetic analytic ellipsoids/superellipsoids with simulated top-view visibility**. This validates code but does **not** constitute real-data research evidence. Bonn fruit benchmark may be a later external check if licensing/access permit.

The CoRe++ README suggests a demo tree with paths similar to `3DPotatoTwinDemo/1_rgbd/1_image` and `3DPotatoTwinDemo/2_sfm/1_mesh`. **Inspect the archive; do not rely on these exact paths blindly.**

### Data checks required before claiming an experiment

- Number of **unique potatoes** and number of scans per potato; identify potato IDs.
- Which data types exist: RGB, depth, intrinsics, partial `.ply` clouds, complete `.ply`/`.obj` meshes, registration transforms, physical volume, cultivar, scan positions.
- Coordinate systems, units (meters vs millimeters), handedness, axis directions, whether camera and GT are already aligned. Record transforms explicitly.
- Do NOT align the predicted completed shape to the ground-truth mesh at evaluation time unless the protocol specifically permits it. If a dataset provides a fixed preregistration transform, apply it consistently. Evaluation-time GT alignment can overstate performance.
- Whether the GT mesh is watertight, has holes/filled areas, and whether its physical volume agrees with any independently measured volume.
- Identify datasets with known imperfect alignments; log and report exclusions instead of silently deleting difficult samples.
- Respect license and access conditions, and record exact archive/version/checksums where practical.

### Split/leakage policy (mandatory)

- Split by **unique potato**, not individual image/point cloud; multiple views of the same potato must not cross train/validation/test partitions.
- All statistical shape templates, PCA/priors, hyperparameters and thresholds must be fit on training/validation only. **Never** use a test object's complete mesh to retrieve or generate its completion.
- If only a tiny demo sample exists, provide qualitative results and explicitly mark the result as **smoke test only**. No inflated statistical conclusions.
- Report test-set counts in **unique objects** and in frames, and use potato-level confidence intervals (e.g., bootstrap resampling unique IDs) if sample size permits.

---

## 5. Baselines and possible contribution

Implement progressively (do not try every method before generating results):

| Order | Method | Purpose | Practical notes |
|---|---|---|---|
| 1 | **Ellipsoid fit** to visible points / bounding constraints | Simple low-dimensional volume/shape baseline | A top-view-only surface underconstrains vertical extent; make belt-plane assumptions explicit. |
| 2 | **Convex hull** of visible points with an explicitly stated completion rule | Measures convexification failure | A hull over only visible top points is **not automatically a full-volume estimate**. Must define how the underside is closed. |
| 3 | **Symmetry/mirror completion** around an estimated plane | Classical fruit completion baseline | Document plane choice, possible asymmetry and bad fits. |
| 4 | **Superellipsoid or low-order parametric surface** (optional) | More flexible compact shape baseline | Add only if enough time; regularization needed to avoid overfit. |
| 5 | **Shape-template prior** from training potato meshes (optional) | Tests whether cross-instance shape statistics help | Train-only templates, avoid test leakage; requires meaningful number of complete shapes. |
| 6 | **Proposed confidence-weighted refinement** | Targeted novel candidate | Should have clearly separable ablations (confidence, prior, regularizer). |
| 7 | **Ensemble/uncertainty** (stretch goal) | Quantify hidden-region ambiguity | Calibration/coverage matters more than pretty heatmaps. |

### Evaluation metrics

**Primary geometry:**

- Symmetric Chamfer distance between surface-sampled predicted and reference meshes, with **units and squared/unsquared convention explicitly stated**. Many papers define Chamfer differently; do not silently quote incomparable values.
- Precision, recall, and F-score at **5 mm** (matching the CoRe++ protocol where appropriate; optionally report thresholds 2/5/10 mm).
- **Observed-region fidelity:** distance from measured high-confidence visible points to predicted surface; a complete shape should not corrupt observed geometry.
- **Hidden-region quality:** evaluate separately if the known visibility mask and alignment permit an honest observed/hidden partition. Avoid oracle usage in fitting.

**Secondary:**

- Volume absolute and relative error versus SfM mesh; **separately** versus physical displacement volume if actually available.
- Watertightness, nonmanifold geometry, normal orientation and degenerate surface failures.
- Runtime and peak memory on **Mac M2 Pro CPU**, no CUDA, including required data preparation stages; label benchmark boundaries clearly.
- Group errors by size, cultivar, elongation, concavity, percentage observed, and noise severity *only if annotations/data permit*.
- If uncertainty is added: expected-vs-actual coverage for chosen volume/shape-error intervals, calibration reliability, association between predicted uncertainty and actual error.

**Fair comparison requirements:** same input observations, reference frames, surface sample counts, metric code, evaluation splits and CPU hardware; identify parameter tuning budget. Reproducible seeds and stored per-object results.

### Planned ablations

- Standard vs confidence-weighted observation fit.
- With/without hidden-surface prior.
- With/without adaptive regularization.
- Clean vs controlled noise/outliers/erosion/dilation/depth gaps.
- Performance on *irregular/concave* cases versus near-ellipsoidal cases.
- Runtime versus point-cloud density and mesh resolution.

---

## 6. Scope of the robustness experiment

The papers motivate **segmentation and depth failures**, but a benchmark with random artificial noise alone is not a new reconstruction method. If this becomes the chosen experimental direction, implement a mitigation and demonstrate it helps.

Consider controlled, documented corruptions such as:

- Depth jitter (millimeter-scale with explicit units), isolated outliers, missing-depth patches, edge discontinuities.
- Foreground mask erosion/dilation or boundary misplacement **only if masks are available**.
- Subsampling/occlusion ratios that mimic partial scans without unrealistically exposing underside information.
- Simulated camera-plane/belt calibration error as a separate evaluation condition.

Do not mix corruption regimes into training/evaluation without recording them. The original RGB-D capture and reference mesh may already contain noise and alignment errors.

---

## 7. Suggested repository structure

Create/adapt to existing repository conventions; do not overwrite existing work.

```text
.
├── README.md
├── pyproject.toml                # or requirements.txt; choose compatible versions
├── .gitignore                    # ignore data, generated plots, cache, large meshes
├── docs/
│   ├── feasibility.md            # data-access and feasibility report
│   ├── methodology.md            # hypotheses, assumptions, baselines, metrics
│   └── experiment_log.md         # dated observations, failures and decisions
├── data/
│   ├── raw/                      # ignored; user-provided/downloaded data
│   ├── interim/                  # ignored
│   └── README.md                 # exact provenance/expected structure
├── src/potato3d/
│   ├── __init__.py
│   ├── io.py                     # discover/read point clouds, meshes, metadata
│   ├── geometry.py               # unit checks, sampling, coordinate transforms
│   ├── completion/
│   │   ├── ellipsoid.py
│   │   ├── convex.py
│   │   ├── symmetry.py
│   │   └── confidence.py         # only after baselines work
│   ├── metrics.py                # Chamfer/F-score/volume/observed fidelity
│   ├── visualize.py              # interactive/exported comparisons
│   └── cli.py                    # reproducible command entry point
├── configs/
│   └── baseline.yaml
├── tests/
│   ├── test_geometry.py
│   ├── test_metrics.py
│   └── test_synthetic_completion.py
├── scripts/
│   ├── inspect_dataset.py
│   ├── run_baselines.py
│   └── evaluate_results.py
└── outputs/                      # ignored; figures, 3D meshes, CSV/JSON results
```

**Package constraints:** Prefer Python 3.11 or 3.12 with current macOS arm64-compatible wheels; verify availability of Open3D and other native dependencies in the actual environment before pinning versions. Avoid installing CUDA wheels. If Open3D installation is problematic, keep I/O and geometry abstractions modular and use SciPy + Trimesh where possible.

---

## 8. Execution plan (one-month scale)

### Milestone 0 — Source and dataset verification

- Confirm attachments and public links; inspect demo archive contents before large downloads.
- Confirm at least one genuine partial/complete pair, scale, alignment, and ID.
- Save `docs/feasibility.md` with concrete verified/unverified items.

**Exit condition:** At least one usable aligned real pair, or explicit blocked status with a working synthetic fallback.

### Milestone 1 — Reproducible classical baseline

- Synthetic shapes with analytically known surfaces and volumes to validate metrics.
- Load real partial scan and reference mesh if available.
- Implement ellipsoid, symmetry and one carefully defined hull/closing baseline.
- Render side-by-side partial / completed / reference; export CSV/JSON metrics.

**Exit condition:** One-command CPU demo and passing unit tests.

### Milestone 2 — Failure-mode study

- Evaluate which methods fail on irregular shapes, missing depth, outliers and concavities.
- Separate observed and unobserved regions in metrics where possible.
- Choose **one primary failure mode** using measured evidence.

**Exit condition:** Small error analysis table and initial plots; no novelty claims without a proposed remedy.

### Milestone 3 — Targeted method

- Implement one observation-confidence / shape-prior / surface-refinement modification.
- Compare with all baselines under the same input and evaluation protocol.
- Run ablations; report failures, not only best examples.

**Exit condition:** Clear quantitative hypothesis test and per-potato results.

### Milestone 4 — Course showcase

- Interactive 3D viewer or saved rotating visualization of input, predicted surface, reference, and error field.
- Research-style short report with background, related work, mathematical method, dataset, protocol, results, ablations, failure cases and limitations.
- Measured CPU cost; all figures traceable to results files.

---

## 9. Acceptance criteria / definition of done

### First working prototype

- [ ] Mac CPU execution works without NVIDIA/CUDA.
- [ ] Synthetic mesh evaluation matches known geometry and volume within numerical tolerance.
- [ ] Real demo inspection identifies exact files, units and transforms, or explains why data is blocked.
- [ ] At least **two distinct** full-shape baseline predictions for the same partial input.
- [ ] Saved `.ply`/`.obj` meshes and side-by-side 3D figures.
- [ ] Measured Chamfer, F-score, observed-region error, volume error and runtime (when reference is present).
- [ ] No test-data leakage; no unverified performance/novelty claims.
- [ ] `README.md` contains installation and minimal reproducible execution instructions.

### Research-quality final deliverable

- [ ] Primary method improves at least one *predefined* metric on held-out potatoes, or reports rigorously that it does not.
- [ ] Comparable metrics for classical baselines and the proposed method.
- [ ] Separate effects of geometric concavity, observation noise, and visibility.
- [ ] Confidence intervals with grouping by potato ID when sample count permits.
- [ ] Detailed ablations and representative success/failure visualizations.
- [ ] Clearly differentiated from CoRe++, CoRe, PointRAFT, standard symmetry/ellipsoid fitting and published uncertainty methods.
- [ ] Reproducibility: code, fixed seeds, dataset manifests, configs, results tables.

---

## 10. Risks, decision points, and boundaries

| Risk | Implication | Mitigation / fallback |
|---|---|---|
| Full 3DPotatoTwin access is gated or too large | Cannot establish strong results on real held-out potatoes | Start with ~279 MB CoRe++ demo; request a subset; evaluate Bonn fruit data if needed |
| Demo has too few unique potatoes | Cannot support robust inference or shape-prior learning | Use as a smoke test only; do not report confident generalization |
| Partial and complete pairs are misaligned | Chamfer/volume analysis becomes meaningless | Verify transforms, units, visible overlap and registration quality first |
| Shape prior leaks test meshes | Artificially optimistic completion | Build priors/templates from training IDs only |
| Nearly symmetric potato has ambiguous orientation | Exact orientation cannot be uniquely recovered | Evaluate equivalence under symmetry or report ambiguity; no false certainty |
| Convex hull gives seemingly good volume but misses grooves | Incorrect geometry hidden by one volume metric | Report surface error, per-region metrics and visual overlays |
| Geometry method performs worse than CoRe++ | Research claim may still be valuable for CPU speed/reliability | Compare accurately; do not claim superiority or conflate GPU/CPU latency |
| Neural references are difficult on macOS | Can't directly rerun published neural models | Use published results as context, not head-to-head unless identical test set and metrics |
| Project becomes weight regression rather than reconstruction | Misaligned with CSE527 | Keep complete-surface output as the main task; volume/weight are downstream checks |

### Stop/go decision

If, after Milestone 1, no usable aligned real pairs or representative complete reference shapes can be obtained, **do not keep coding speculative potato-specific algorithms**. Report the blocker and recommend switching to the accessible **Bonn Fruit Shape Completion benchmark** or another public geometric dataset. Reuse the metric and completion pipeline.

---

## 11. What to report back to the user at the first checkpoint

Respond with:

1. Exact environment and whether CPU dependencies installed.
2. Exact discovered dataset files and number of unique objects; missing fields and access blockers.
3. Implemented modules/tests and how to run them.
4. One image or interactive visualization of the partial scan and candidate complete shapes.
5. A small metrics table **only for actually evaluated samples**, clearly labeled synthetic/demo/held-out.
6. Recommended next experiment based on **observed** failure modes, plus what remains unverified.

Do not ask for information already in this document. Only request user action for a genuinely blocked prerequisite, such as gated data access or approval for a large download.

---

## 12. Suggested initial Codex instruction

> Read `CSE527_3DPotatoTwin_Codex_Context.md` and inspect the workspace. We are building a CPU-only, reproducible 3D potato-shape completion research prototype for CSE527 on an M2 Pro Mac. First establish the dataset/demo availability and environment, then scaffold the project, implement synthetic geometry tests, real-data loader, ellipsoid and symmetry baselines, geometry/volume metrics, and a saved 3D comparison. Write a short `docs/feasibility.md` and report evidence of what runs. Do not start GPU training, download the full 111 GB dataset, or claim novel performance. Once the baselines run, identify a measurable failure mode that motivates confidence-weighted or concavity-preserving refinement.

---

## 13. Source links at a glance

| Resource | Link |
|---|---|
| 3DPotatoTwin paper | https://doi.org/10.1016/j.plaphe.2025.100123 |
| 3DPotatoTwin data | https://huggingface.co/datasets/UTokyo-FieldPhenomics-Lab/3DPotatoTwin |
| PotatoScan registration code | https://github.com/UTokyo-FieldPhenomics-Lab/PotatoScan |
| CoRe++ paper | https://arxiv.org/abs/2407.21341 |
| CoRe++ code | https://github.com/UTokyo-FieldPhenomics-Lab/corepp |
| CoRe++ demo dataset release | https://github.com/UTokyo-FieldPhenomics-Lab/corepp/releases/tag/demo_dataset |
| PointRAFT paper | https://arxiv.org/abs/2512.24193 |
| PointRAFT code | https://github.com/pieterblok/pointraft |
| Bonn fruit completion benchmark | https://www.ipb.uni-bonn.de/data/shape_completion/index.html |

**End of handoff context.**
