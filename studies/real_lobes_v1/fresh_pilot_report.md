# Fresh 3DPotatoTwin development pilot

**Zero of 12 tubers provided a reference-corroborated lobe with an eligible within-tuber control.** This is a feasibility result for the current interior detector and matching rule. The pilot does not estimate the frequency of natural lobes or their association with underside relief.

## Intake and measurement

The selected cohort spans 12 acquisition groups and three cultivars. We extracted the 48 selected geometry and image files and their registration metadata into a temporary directory. Source metadata hashes matched the selection manifest. All 12 point clouds projected inside their RGB masks and agreed with the released depth pixels. All 12 released registrations met the development overlap rule on supported interior grid cells. The rule required 90% paired reference rays, median absolute observed-to-reference top difference at most 2 mm, and p95 at most 5 mm. Measured median differences ranged from 0.47 to 1.33 mm and p95 from 1.38 to 2.76 mm. These differences include both sensor and registration effects.

The detector, matching thresholds and RGB-D screen came from the demo. This run used the published marker rectangles instead of manual annotations. The runner encloses each rectangle in an ellipse and applies the existing two-pixel buffer. All 12 registered frames had a published annotation.

| Pilot count | Result |
|---|---:|
| Tubers that passed intake and registration overlap | 12/12 |
| Scan-only candidates before screening | 34 |
| Candidates after screening | 12 across 5 tubers |
| Screened candidates with eligible controls | 11 |
| Screened candidates with at least 1.5 mm reference-top relief | 1 |
| Tubers with a corroborated candidate and eligible control | 0/12 |

The only corroborated candidate was on **2R1-10**, frame 364. Its RGB-D top relief was 3.02 mm. The registered reference measured 2.79 mm of top relief and 0.19 mm of outward underside relief. The four lateral alignment probes gave 2.39–3.58 mm on top and 0.16–0.23 mm underneath. The inspection shows missing reference cells near the background-fitting annulus, although core coverage was 100% and nominal annulus coverage was 96%. The candidate had no eligible control under the existing matching rule. The individual measurement cannot establish an association.

The two unfinished raw photogrammetry image archives were unnecessary for this pilot. The two pilot runs produced byte-identical JSON, and all 80 project tests passed.

[Machine-readable results](fresh_pilot_results.json)

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python studies/real_lobes_v1/fresh_pilot.py \
  --source data/raw/3DPotatoTwin --out outputs/real_lobes_v1/fresh_pilot.json
```
