"""Replay A and C in isolation from the predicted-mask reconstruction."""

from contextlib import ExitStack
from pathlib import Path
import time
from zipfile import ZipFile

import numpy as np

import common as c
import alignment as align
from build import bulk, merged_cloud, save_clouds
from register import camera


def archive_inputs():
    geometry = c.prep.read_json(c.PILOT / "registration.json")
    pilot_manifest = c.PILOT / "frame_manifest.json"
    if geometry["recipe"]["manifest_sha256"] != c.prep.digest(pilot_manifest):
        raise ValueError("Archived geometry registration refers to a different manifest")
    geo_plans = c.by_tuber(c.prep.read_json(pilot_manifest)["roster"])
    geo_links = c.by_tuber(geometry["potatoes"])
    trait_manifest = c.TRAIT_STUDY / "frame_manifest.json"
    trait_plans = c.by_tuber([r for r in c.prep.read_json(trait_manifest)["roster"] if r["split"] == "val"])
    features_path = c.OLD_TRAIT_ASSETS / "feature_run.json"
    features = c.prep.read_json(features_path)
    fits = c.prep.read_json(c.TRAIT_STUDY / "train_fit.json")
    if (fits["feature_run_sha256"] != c.prep.digest(features_path)
            or features["recipe"]["frame_manifest_sha256"] != c.prep.digest(trait_manifest)
            or features["recipe"]["checkpoint_sha256"] != c.prep.CHECKPOINT_HASH):
        raise ValueError("Archived trait cache provenance differs from the frozen recipe")
    records = c.by_tuber(features["records"])
    return geo_plans, geo_links, trait_plans, records, features["fingerprint"]


def archived_links(case, pilot_plans, pilot_fits, trait_plans, records, fingerprint):
    tuber = case["tuber"]
    if case["analysis"] == "geometry":
        plan = pilot_plans[tuber]
        old = pilot_fits[tuber]["methods"]["raft"]
        links = old["links"]
        if old["failure"] or any(link["failure"] for link in links):
            raise ValueError(f"Archived geometry pilot had an unusable RAFT chain: {tuber}")
        return plan["frames"], links, old["to_center"], None
    plan, cache = trait_plans[tuber], records[tuber]
    path = c.OLD_TRAIT_ASSETS / "features" / cache["cache_file"]
    if c.prep.digest(path) != cache["cache_sha256"]:
        raise ValueError(f"Archived supplied-mask feature file changed: {tuber}")
    archived = c.prep.read_json(path)
    if (archived["feature_fingerprint"] != fingerprint or archived["selected"] != case["selected"]
            or archived["tuber"] != tuber):
        raise ValueError(f"Archived provided-mask feature cache does not match this potato: {tuber}")
    old = archived["registration"]["D"]
    if old["failure"] or any(record["error"] for record in old["links"]):
        raise ValueError(f"Archived trait evaluation had an unusable RAFT chain: {tuber}")
    return plan["frames"], old["links"], old["to_center"], archived


def replay():
    freeze = c.frame_manifest()
    plans = archive_inputs()
    output = c.OUTPUT / "provided"
    output.mkdir(parents=True, exist_ok=True)
    matrix = camera()
    records = []
    start = time.perf_counter()
    names = {f[key]["archive"] for r in freeze["roster"] for f in r["links_rgbd"] for key in ("rgb", "depth")}
    with ExitStack() as stack:
        ply_archive = stack.enter_context(ZipFile(c.prep.CLOUDS))
        archives = c.prep.open_images(stack, names)
        for case in freeze["roster"]:
            tuber = case["tuber"]
            started = time.perf_counter()
            frames, links, maps, original = archived_links(case, *plans)
            suffixes = [f["suffix"] for f in frames]
            if (suffixes != [f["suffix"] for f in case["links_rgbd"]]
                    or [(link["source"], link["target"]) for link in links] != list(zip(suffixes[:-1], suffixes[1:], strict=True))):
                raise ValueError(f"Provided-mask archived link order changed: {tuber}")
            poses = [np.asarray(link["transform"], dtype=float) for link in links]
            if not all(c.prep.safe_rigid(pose) for pose in poses):
                raise ValueError(f"Provided-mask archived non-rigid transform: {tuber}")
            views = {f["suffix"]: align.read_view(f, ply_archive, archives, matrix)
                     for f in frames if f["suffix"] in case["selected"]}
            points = views[case["selected"][1]]["points"]
            raw_fused, replay_maps = merged_cloud(views, suffixes, case["selected"], poses)
            if any(not np.allclose(replay_maps[k], maps[k], atol=1e-11, rtol=0) for k in replay_maps):
                raise ValueError(f"Cached provided-mask transform composition did not replay: {tuber}")
            conditions = {"A": bulk(points), "C": bulk(align.voxel(raw_fused, 1.))}
            deltas = {}
            if original is not None:
                old_center = original["single_views"]["center"]
                old_fused = original["registration"]["D"]["fused"]
                for method, old in (("A", old_center), ("C", old_fused)):
                    fit = conditions[method]
                    deltas[method] = {k: fit[k] - old[k] for k in ("area_mm2", "height_mm", "proxy_cm3")}
                    if not all(abs(v) <= 1e-7 for v in deltas[method].values()) or fit["point_count"] != old["points"]:
                        raise ValueError(f"Archived {method} feature replay differed: {tuber}, {deltas[method]}")
            row = {"tuber": tuber, "analysis": case["analysis"], "features": conditions, "cloud_sha256": None,
                   "trait_feature_replay_delta": deltas, "selected": case["selected"], "fused_to_center": replay_maps}
            destination = output / f"{tuber}.json"
            if case["analysis"] == "geometry":
                row["cloud_sha256"] = save_clouds(destination.with_suffix(".npz"), {"A": points, "C": raw_fused})
            row["wall_s"] = time.perf_counter() - started
            c.prep.write_json(destination, row)
            records.append({"tuber": tuber, "sha256": c.prep.digest(destination)})
    c.prep.write_json(c.STUDY / "provided_replay.json", {
        "frame_manifest_sha256": c.prep.digest(c.STUDY / "frame_manifest.json"), "records": records,
        "wall_s": time.perf_counter() - start, "code_sha256": c.prep.digest(Path(__file__)),
    })
    print(f"Rebuilt all {len(records)} provided-mask centers and fusions; 30 trait features verified.", flush=True)


if __name__ == "__main__":
    replay()
