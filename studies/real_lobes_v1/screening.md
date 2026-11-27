# Foreground, depth, and marker screening

This development run applied the same screen to candidate and control centers before ranking and matching. It evaluates the entire projected 9 mm neighborhood, including the core and the background-fitting annulus. For supported grid cells it also checks the actual point pixels used to estimate height. A center is flagged if any checked pixel:

- Is within the 3-pixel guard around the outside of the RGB foreground mask or around a missing-depth region.
- Is on or within one pixel of an adjacent valid pixel pair with a depth step of at least 4 mm.
- Intersects one of the manually annotated visible marker heads. The annotations use ellipses with a 2-pixel allowance on each semi-axis.

The rules and manual annotations were chosen during development after the visual review. They can reject true features near a discontinuity as well as artifacts. The numerical output retains all flags for each original detection and its original control, plus counts by reason over all evaluated centers. Reasons can overlap. [Marker annotations](demo_markers.json)

| Demo tuber | Centers before | Centers after | Candidates before | Candidates after | Matched controls after |
|---|---:|---:|---:|---:|---:|
| 2R2-8 | 3,088 | 1,710 | 4 | 1 | 1 |
| 4R3-4 | 1,985 | 871 | 3 | 0 | 0 |
| 5R3-2 | 1,245 | 348 | 4 | 1 | 1 |
| R13-8 | 5,078 | 3,449 | 6 | 3 | 3 |
| R7-7 | 437 | 56 | 0 | 0 | 0 |
| Total | 11,833 | 6,434 | 17 | 5 | 5 |

Ten of the original candidates overlapped marker neighborhoods. Two hit the foreground or missing-depth guard, including the boundary-sensitive patch that had previously crossed the nominal reference-top relief threshold. No original candidate triggered the depth-step rule. Among all original matched controls, five overlapped a marker neighborhood and one hit the foreground or missing-depth guard.

After rematching, all five remaining candidates had eligible controls. The candidate RGB-D relief ranged from 1.53 to 2.27 mm. Reference-top relief ranged from −0.19 to +0.38 mm under the nominal registration, and its maximum across the four lateral probes was +0.41 mm. Zero candidates reached the pilot's 1.5 mm descriptive reference-top threshold. The screened demo therefore supplies no corroborated positive patch for estimating the association between visible and underside relief. The retained scan-to-reference disagreements remain unresolved. [Full screening record](demo_screen.json)

The next data requirement is a fresh registered development subset. The intake plan specifies how to select and validate it, then count corroborated and matchable lobes per tuber before sizing confirmation. [Fresh intake plan](fresh_intake.md)

## Reproduce

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python studies/real_lobes_v1/screen.py --out outputs/real_lobes_v1/demo_screen.json
```
