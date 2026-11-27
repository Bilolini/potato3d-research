# Data provenance and acquisition

Raw datasets live in ignored `data/raw/`. No dataset was present initially.

The initial downloaded dataset was the public
[CoRe++ demo release](https://github.com/UTokyo-FieldPhenomics-Lab/corepp/releases/tag/demo_dataset).
The archive is pinned in `demo_manifest.json`: 278,967,884 bytes, SHA256
`c89fd95fba3284559d5b79a5679bf4bc5a9da96cb0fbc0bc9eeb6c7d8fb33fa2`.
It contains 483 ZIP entries and 367,705,315 expanded file bytes. Reacquire with
`.venv/bin/python scripts/download_demo.py` after installation. The script has
size/hash/path checks and never downloads the full dataset. If extraction already
exists it is retained; the archive is verified but existing extracted files are
not overwritten. Compare their pair hashes with `demo_manifest.json` if edited.

Actual root: `data/raw/3DPotatoTwinDemo`.

| Object ID | Partial frames | Exact registered source frame |
|---|---:|---|
| 2R2-8 | 25 | `1_rgbd/2_pcd/2R2-8/2R2-8_pcd_356.ply` |
| 4R3-4 | 28 | `1_rgbd/2_pcd/4R3-4/4R3-4_pcd_367.ply` |
| 5R3-2 | 31 | `1_rgbd/2_pcd/5R3-2/5R3-2_pcd_356.ply` |
| R13-8 | 22 | `1_rgbd/2_pcd/R13-8/R13-8_pcd_357.ply` |
| R7-7 | 32 | `1_rgbd/2_pcd/R7-7/R7-7_pcd_357.ply` |

Each complete reference is `2_sfm/1_mesh/<ID>/<ID>.obj`. The object JSON at
`3_pair/tmatrix/<ID>.json` names that mesh and one RGB-D frame, contains the
camera-to-SfM rigid transform, and reports registration diagnostics. The archive
also contains RGB (alpha-mask) and depth PNGs, camera intrinsics/settings, sampled
SfM PLYs and `ground_truth.csv` (cultivar, dimensions, weight, physical volume,
reported Metashape volume). Availability of those fields does not validate their
measurement accuracy. The current pipeline uses provided PLYs; it does not yet
reconstruct PLYs from depth PNGs or reproduce authors' depth filtering.

The public [full dataset card](https://huggingface.co/datasets/UTokyo-FieldPhenomics-Lab/3DPotatoTwin)
states MIT and requires access conditions/account-information sharing; it
recommends 150 GB free space. Access was not accepted and no full data downloaded.
The demo archive itself contains no separate data license file; record this
distinction and confirm redistribution terms before redistributing raw assets.
The source code repository's MIT label alone is not a separate demo-data license.

All five potato demo objects are smoke/development examples. That demo has no held-out
split or learned shape prior, and no full-dataset acquisition was approved. Keep all
frames of an object in the same split if an expanded dataset is later obtained.

## Bounded Bonn laboratory-fruit subset

The [official Bonn dataset page](https://www.ipb.uni-bonn.de/data/shape_completion/index.html)
links a public ZIP of 8,369,655,798 bytes. Only pinned members are retrieved by HTTP
range; the complete archive is not downloaded. `bonn_minipairs_manifest.json`
records the earlier two-pair access audit. `bonn_real_v1_manifest.json` separately
reserves eight training references and one RGB/depth/mask/intrinsic/pose/reference
pair each for three development and twelve holdout objects: **55,004,299 compressed
member bytes**, 98 members. Holdout uses public validation, not hidden-test data.
All are laboratory fruit. The prior val/lab15 audit is excluded from this study.

Source root: `data/raw/bonn_real_v1/`. `download_manifest.json` records per-member
ZIP CRC, size and content SHA256. The fetcher enforces exact HTTP ranges, safe
paths and a 200 MB subset cap; it cannot fall back to a full ZIP download. Holdout
fetching requires the frozen development selection. The prior uses only complete
official-training references. No holdout reference supplies a pose fit, center,
scale, filter, template or parameter choice. Units and source pose are explicit.

References are laser point clouds; they provide no direct mesh/physical volume
target. No data license is inferred from the toolkit's MIT software license;
separate data terms remain unverified. Raw assets stay ignored and are excluded
from source archives. No agreement or benchmark submission was made. See
`docs/bonn_real_v1_protocol.md` and `docs/bonn_real_v1_report.md` for definitions,
evidence and commands. This fruit study does not validate potato generalization.
