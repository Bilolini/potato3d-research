# Data provenance and acquisition

Raw datasets live in ignored `data/raw/`. No dataset was present initially.

The only downloaded dataset is the public
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

All five objects are smoke/development examples. There is no genuine held-out
split, no learned shape prior, and no approved full-dataset acquisition. Keep all
frames of an object in the same split if an expanded dataset is later obtained.
