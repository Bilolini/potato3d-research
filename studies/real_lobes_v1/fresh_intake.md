# Fresh 3DPotatoTwin development intake

The five CoRe++ demo tubers are the only registered potato pairs in the workspace. The public dataset card still requires a signed-in Hugging Face user to agree to share account information before accessing files. CoRe++ lists the same full release alongside its five-object demo. A local intake command is ready. The remote archive layout and selective download sizes remain unverified. [3DPotatoTwin dataset card](https://huggingface.co/datasets/UTokyo-FieldPhenomics-Lab/3DPotatoTwin) · [CoRe++ release instructions](https://github.com/UTokyo-FieldPhenomics-Lab/corepp#dataset)

## First batch

Use up to **12 fresh tubers** for a development feasibility batch. This is an operational starting size. Confirmation size will depend on the number of independent tubers with corroborated, measurable lobes.

1. After access is granted, inventory the file layout, sizes, registration JSONs and warning list before selecting assets. Pin the release revision and record the catalog used to choose the batch. If the files are available only inside archives, check selective member access and its byte cost first.
2. Select across available cultivar and acquisition groups using metadata alone. Within each group, order object IDs by the SHA-256 of `real-lobes-dev-v1/<ID>`, then take one per group in sorted group order until the batch is filled. If acquisition metadata are absent, use cultivar alone and record the limitation. Select one frame per tuber using its released pairing JSON. Exclude the demo IDs up front and record any later ingestion failures.
3. Stage the five assets for each selected tuber: named PLY, matching SfM OBJ, pairing JSON, matching RGB PNG and matching depth PNG. Include the shared camera intrinsics, trait metadata and registration warnings. The rest of the RGB-D sequence, raw SfM photographs and Metashape projects are unnecessary for this batch. Use the same extracted directory structure as the demo, with the shared trait table at the root. Record any normalization from the file layout.
4. Run intake. It rejects reused demo IDs or exact geometry hashes, validates the published pair transform via the existing loader, checks frame projection against the RGB and raw depth rasters, and records paths and SHA-256 hashes. Review the release's registration warnings and inspect overlays before scoring. The projection check establishes PLY-to-RGB-D consistency. The mesh-to-camera transform still needs its own review.
5. Annotate marker footprints from RGB, then run the existing screen unchanged for the first pass. Report tuber counts at intake and after registration review, tubers with candidates, tubers with corroborated and matched candidates, and missing or unmatched cases. Use counts by tuber to decide whether the interior-lobe endpoint is feasible before reserving a separate confirmation cohort.

## Local validation

```sh
.venv/bin/python studies/real_lobes_v1/intake.py \
  --root data/raw/3DPotatoTwinFreshDev \
  --out outputs/real_lobes_v1/fresh_intake.json
```

The new intake path was smoke-tested on all five existing demo pairs with `--demo-check`. Repeating it produced byte-identical manifests, and fresh mode rejected the demo. No fresh registered tubers were available to ingest or score.
