# Do visible lobes predict underside features on real potatoes?

The synthetic study found that mirroring detail helped when a real underside lobe was present, while restoring it only on the observed surface reduced errors from depth artifacts. Registered scans can estimate where the first case occurs in practice. The primary question is whether the underside has more outward relief at visible lobe locations than at comparable locations on the same tuber. [Synthetic results](../body_detail_v1/results.md)

## Development geometry audit

We used the five CoRe++ demo pairs and their released transforms. The grid has 1 mm spacing and sits at least 2 mm inside the projected convex hull of the RGB-D points. A reference ray is usable when it has exactly two distinct crossings with the expected outward orientation. Shared triangle edges count once. This supports measurements on portions of open meshes without filling holes. It tests reference coverage, while scan support and feature-specific coverage will require separate checks.

| Demo tuber | Usable rays | All interior rays | Largest of four underside shift p95 values (mm) |
|---|---:|---:|---:|
| 2R2-8 | 4,635 | 4,661 | 0.95 |
| 4R3-4 | 3,311 | 3,311 | 0.67 |
| 5R3-2 | 2,401 | 2,402 | 1.02 |
| R13-8 | 7,139 | 7,139 | 1.28 |
| R7-7 | 1,145 | 1,149 | 1.05 |

Across the five objects, 18,631 of 18,662 rays had usable pairs. Four missed the mesh and 27 had more than two crossings. All references are open. The sensitivity probe shifts the ray positions in each lateral direction by the published registration RMSE for that pair and measures absolute lower-surface movement on the intersection of usable rays. That RMSE sets the scale of an illustrative perturbation. The p95 values do not bound registration error or capture rotations, depth offsets or registration failures. [Machine-readable audit](demo_geometry.json)

## Draft confirmation design

1. Obtain fresh tubers with a named RGB-D point cloud, SfM mesh, and released rigid transform. Record acquisition group, cultivar, file hashes, available calibration and any registration warning. Keep all frames of each tuber in one split and reserve confirmation object IDs before inspecting feature or underside measurements. The five demo tubers remain development examples.
2. Identify candidate outward lobes from the RGB-D observation alone. Use local positive height residuals relative to a smooth observed-only body, require spatial coherence and image support, and define the patch core and surrounding annulus in physical units. Match control patches within tuber on distance to the silhouette, surface slope, and valid observation support. Set scales, matching tolerances, and abstention rules on development data.
3. At the frozen patch locations, use the registered SfM reference to measure upward relief on the top and downward relief on the underside. For each side, fit a local background from valid annulus rays and summarize signed core height relative to it. Record core and annulus support, mask documented pin and fixture regions, and keep unmatched or unmeasurable patches in the denominators. Report the measured underside relief over matched controls both across all detected patches and across patches whose visible features are corroborated by the reference. Recompute under small rigid perturbations of the released transform and report the resulting spread.
4. Compare clipped 95th-percentile mirroring, visible-detail restoration and reflected-detail restoration at the same locations. Report paired error and coverage in the feature core and on the rest of the underside. Aggregate by tuber, use tuber-level intervals, and stratify by location only where the cohort supports it. Freeze the detector, thresholds, endpoints and evaluation code before scoring confirmation.

The statistical decision rule is pending development. Submillimeter comparisons deserve particular care given the shifts measured on the demo. The full 3DPotatoTwin release is gated. A bounded subset needs the point clouds named in the pair JSON files, the matching OBJ meshes, the transforms and the registration warnings. Raw photo and photogrammetry project archives are unnecessary for this first study. [Dataset card](https://huggingface.co/datasets/UTokyo-FieldPhenomics-Lab/3DPotatoTwin)

## Visible-lobe detector pilot

The pilot uses a 1 mm scan grid and the median height of the five nearest observations within 1.5 mm. At each center at least 9 mm inside the convex hull, it fits a robust quadratic background on a 6–9 mm annulus. A candidate needs median relief of at least 1.5 mm in its 3 mm core, and at least 80% of supported core cells must show at least 0.75 mm of relief. Both core and annulus need at least 80% data coverage. Candidate centers are selected in descending relief order and kept at least 9 mm apart. Controls use absolute relief of at most 0.5 mm and are matched on hull distance, local slope, and observed coverage. The detector uses RGB-D geometry. Image and pin checks are still pending.

| Demo tuber | Eligible centers | Candidates | Matched controls |
|---|---:|---:|---:|
| 2R2-8 | 3,088 | 4 | 3 |
| 4R3-4 | 1,985 | 3 | 3 |
| 5R3-2 | 1,245 | 4 | 3 |
| R13-8 | 5,078 | 6 | 6 |
| R7-7 | 437 | 0 | 0 |

All 17 candidate footprints supported both reference measurements under the nominal transform and each of the four lateral probes. One candidate reached the descriptive 1.5 mm threshold on the reference top. On 2R2-8 at (100, 20) mm, the nominal top relief was 3.19 mm and the underside relief was −0.14 mm, where positive means outward. Across the lateral probes it retained top relief of 2.96–3.69 mm and underside relief of −0.15 to −0.12 mm. It had no eligible matched control. Other candidates' nominal reference top relief ranged from −0.32 to 0.56 mm.

These are development observations. The disagreement could reflect the depth scan, the SfM reconstruction, registration, or acquisition artifacts. The pilot does not estimate lobe prevalence. Visual inspection found that the sole candidate with reference-top relief above 1.5 mm lies next to a local mask and mesh boundary. [Machine-readable pilot](demo_pilot.json) · [RGB-D and reference inspection](inspection.md)

## Reproduce the geometry audit

From the project root with the existing environment and demo data:

```sh
.venv/bin/python studies/real_lobes_v1/audit.py --out outputs/real_lobes_v1/demo_geometry.json
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python studies/real_lobes_v1/pilot.py --out outputs/real_lobes_v1/demo_pilot.json
.venv/bin/python -m pytest -q studies/real_lobes_v1
```
