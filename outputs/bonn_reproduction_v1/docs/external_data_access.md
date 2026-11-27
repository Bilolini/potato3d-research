# External real-data access audit — 2026-11-13

## Potato data

The current [3DPotatoTwin card](https://huggingface.co/datasets/UTokyo-FieldPhenomics-Lab/3DPotatoTwin)
still requires login and agreement to share account information. Its displayed
total is **111 GB**, with 150 GB free space recommended. No agreement was accepted
and no large download was started. The card describes physical volume as measured
by drainage and names `non-perfect.txt` for imperfect registrations. These are
useful provenance claims, not verification of the particular demo measurements
or an independently inspected exclusion list.

The five released demo pairs remain useful geometry smoke cases. This audit does
not resolve `2R2-8` identity/scale, certify belt geometry or make the open SfM
references valid direct-volume targets.

## Bonn fruit benchmark: archive availability verified

The [official dataset page](https://www.ipb.uni-bonn.de/data/shape_completion/index.html)
links an unrestricted archive URL. HTTP HEAD measured **8,369,655,798 compressed
bytes** and advertised byte-range support. The initial audit fetched only the
last 65,536 bytes, 4,106,913-byte ZIP directory and small official loader source.
The later bounded member audit below retrieved two small pairs; the full archive
was not downloaded. Directory metadata
reports 29,050 entries and 32,493,628,119 expanded bytes.

| Released split | Fruit IDs | RGB-D/mask/pose frames | Reference point clouds |
|---|---:|---:|---:|
| Train | 66 | 4,580 | 66 |
| Validation | 25 | 1,387 | 25 |
| Test | 38 | 980 | 0 |

These counts were measured from the remote ZIP directory and agree with
[the source paper's table](https://arxiv.org/html/2407.13304v2). Reference paths are
`<split>/<fruit>/gt/pcd/fruit.ply`; input folders contain `intrinsic.json`, color,
depth `.npy`, masks and per-frame pose files. A bounded train/validation subset
can in principle be retrieved with member-level byte ranges, rather than the
whole 8.37 GB archive. Actual member CRC/unit/alignment checks remain to be done.

The [official loader](https://github.com/PRBonn/shape_completion_toolkit/blob/master/dataloader.py)
uses a column-major intrinsic matrix, metric-depth configuration (`depth_scale=1`),
provided poses, and point-cloud references. This is source inspection, not an
independent numerical validation of the file values. The paper describes
fruit-specific canonical frames and lab/greenhouse views, not the potato
conveyor setup. Its published metric conventions differ from our current
unsquared fixed-threshold metrics and must not be silently mixed.

The code toolkit is labeled MIT. No separate README/license/terms file was found
in the ZIP directory; a separate data license was not verified. The currently
linked competition endpoint returned unrelated content through the reader, and
the former CodaLab page did not expose usable current participation terms in
this check. No account, agreement, application or submission was initiated.
Record these access uncertainties before selecting a redistribution or benchmark
submission workflow; a software license alone is not a verified dataset license.

## Concrete integration work still needed

1. Verify a deliberately small train/validation member subset, provenance,
   access terms, CRCs, point units, poses and visible-surface overlap.
2. Add a point-cloud reference evaluation path. There is no measured physical
   volume target in this audit, so no volume comparison should be invented.
3. Define camera-frame filtering and canonical-frame scoring explicitly. Do not
   rotate/translate using the complete test shape to manufacture a belt plane.
4. Use a completion prior appropriate to fruit observations without assuming
   belt tangency; any learned geometry/extent prior must use training IDs only.
5. Keep development/validation IDs fixed and do not use the hidden test set for
   tuning. The public test reference geometry is absent; direct local test
   benchmark scores are not currently available.

## Bounded member audit completed

Two cases were selected before any geometric scoring: training `lab1` and
validation `lab15`, both frame `00001`. A pinned manifest retrieved only their
reference cloud, RGB, depth, mask, intrinsic and pose members: **5,212,041 compressed
asset bytes**, using exact HTTP ranges. All 12 members passed CRC and size checks;
SHA256s are recorded. Raw data stays ignored and is not redistributed in the
source snapshot. No account or access terms were accepted; the separate data
license remains unverified.

The official pose direction was applied directly, with no ICP, transform search,
reference-driven scaling or filtering:

| Case | Partial points | Reference points | Median raw visible overlap (mm) | p95 (mm) |
|---|---:|---:|---:|---:|
| Train lab1 / 00001 | 41,632 | 25,326 | 1.640 | 5.740 |
| Validation lab15 / 00001 | 26,927 | 43,667 | 3.152 | 7.782 |

Both masks use values 0/1, depth is 720×1280, and source metric depth plus pose
translations produce fruit-scale canonical reference extents. Both PLY references
contain **points without triangle faces**. No mesh or physical-volume score is
available from these files. Canonical partial/reference clouds in mm were
exported for inspection. The training partial cloud spans about 304×333 mm in
XY versus a 77×81 mm reference, indicating substantial extreme points requiring
inspection; nothing was silently removed. The overlap residuals mix registration,
measurement and segmentation effects, so they are not completion-method scores
or binary sensor-error ground truth.

These checks establish accessible aligned data smoke pairs, not a completed
external reconstruction benchmark. The next step is a point-cloud-reference
adapter and a separate real-data protocol, including a completion prior suitable
for fruit frames without assuming belt tangency.

```bash
.venv/bin/python scripts/fetch_bonn_minipairs.py --out data/raw/my_bonn_minipairs
.venv/bin/python scripts/audit_bonn_minipairs.py --data data/raw/my_bonn_minipairs \
  --out outputs/my_bonn_audit
```

Downloader sizes/ranges/CRC checks are pinned by `data/bonn_minipairs_manifest.json`.
Current raw subset: `data/raw/bonn_minipairs_v1/`; measurements and exported
canonical clouds: `outputs/bonn_minipairs_audit_v1/`.

Local metadata: `data/raw/external_access_audit/` (ignored). Compact counts,
source hashes and byte-range checksums: `docs/external_data_access_evidence.json`.

## Subsequent implementation checkpoint

The adapter and bounded real-data protocol have now been implemented and scored;
the earlier "work still needed" list above records the audit-stage state.
`docs/bonn_real_v1_report.md` contains the new evidence: eight training, three
development and twelve disjoint local holdout laboratory fruit, 55 MB of pinned
compressed members, 96/96 valid classical predictions, fixed raw/filtered input
conditions, point-cloud-reference metrics and null volume targets. The co-primary
ellipsoid hypothesis did not fully pass. Greenhouse and potato transfer are not
established. Dataset license, potato calibration and metadata questions remain
unresolved; no full archive or gated dataset was acquired.
