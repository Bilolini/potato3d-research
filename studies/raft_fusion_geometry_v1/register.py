"""Create the three point-cloud conditions before opening the reference meshes."""

from contextlib import ExitStack
from pathlib import Path
import csv
import time
from zipfile import BadZipFile, ZipFile

import numpy as np

import alignment as align
import prepare as prep


def camera():
    d = prep.read_json(prep.CAMERA)
    k = np.asarray(d["intrinsic_matrix"], dtype=float).reshape(3, 3, order="F")
    if ((d["width"], d["height"]) != (1280, 720) or not np.isfinite(k).all()
            or k[0, 0] <= 0 or k[1, 1] <= 0 or not np.array_equal(k[2], [0, 0, 1])):
        raise ValueError("Unexpected released pinhole matrix")
    return k


def registers(views, frames, method, metadata, matrix):
    poses, links = [], []
    for a, b in zip(frames[:-1], frames[1:], strict=True):
        source, target = a["suffix"], b["suffix"]
        first, second = views[source], views[target]
        row = {"source": source, "target": target, "failure": None, "transform": None}
        start = time.perf_counter()
        try:
            if first is None or second is None:
                raise ValueError("A required view failed the fixed depth-support check")
            if method == "icp":
                pose = align.estimate_icp(first, second, row)
            else:
                flow = metadata[source, target]
                row["raft_flow_wall_s"] = flow["wall_s"]
                if flow["error"]:
                    raise ValueError(flow["error"])
                path = prep.ASSETS / "flows" / flow["file"]
                if prep.digest(path) != flow["sha256"]:
                    raise ValueError("Saved dense RAFT flow changed")
                with np.load(path, allow_pickle=False) as array:
                    src, dst = align.flow_matches(first, second, array, matrix, row)
                pose = align.ransac(src, dst, row)
            if not prep.safe_rigid(pose):
                raise ValueError("Estimated link is not a proper rigid transform")
            row["transform"] = pose.tolist()
        except (ValueError, np.linalg.LinAlgError, KeyError, OSError) as error:
            row["failure"] = str(error)
            pose = None
        row["fit_wall_s"] = time.perf_counter() - start
        poses.append(pose)
        links.append(row)
    return poses, links


def fuse(views, suffixes, selected, poses, anchor):
    indexes = [suffixes.index(s) for s in selected]
    maps = align.to_center(poses, indexes[1])
    chosen = [maps[i] for i in indexes]
    cloud = np.concatenate([align.apply(views[s]["points"], anchor @ t)
                            for s, t in zip(selected, chosen, strict=True)])
    cloud = align.voxel(cloud, 1.)
    if not np.isfinite(cloud).all() or len(cloud) < 40:
        raise ValueError("Invalid fused voxel output")
    return cloud, {str(s): t.tolist() for s, t in zip(selected, chosen, strict=True)}


def run():
    manifest = prep.load_manifest()
    manifest_hash = prep.digest(prep.STUDY/"frame_manifest.json")
    flow_path = prep.ASSETS/"flow_run.json"
    flow_run = prep.read_json(flow_path)
    if (flow_run["manifest_sha256"] != manifest_hash
            or flow_run["checkpoint_sha256"] != prep.CHECKPOINT_HASH
            or flow_run["flow_code_sha256"] != prep.digest(prep.STUDY/"flow.py")):
        raise ValueError("Dense-flow provenance differs from the frozen study")
    output = prep.ASSETS / "clouds"
    output.mkdir(exist_ok=True)
    registration_path = prep.STUDY / "registration.json"
    if registration_path.exists():
        raise FileExistsError("Registration is already saved")
    matrix = camera()
    check = align.geometry_check(matrix)
    print("Synthetic geometry direction, composition and scale:", check, flush=True)

    recipe = {"manifest_sha256": manifest_hash, "flow_run_sha256": prep.digest(flow_path),
              "register_code_sha256": prep.digest(Path(__file__)),
              "alignment_code_sha256": prep.digest(prep.STUDY/"alignment.py"),
              "geometry_check": check}
    prep.freeze_check(prep.STUDY/"alignment_freeze.json", recipe)
    metadata = {(x["tuber"], x["source"], x["target"]): x for x in flow_run["links"]}
    expected = {(r["tuber"], a["suffix"], b["suffix"]) for r in manifest["roster"]
                for a, b in zip(r["frames"][:-1], r["frames"][1:], strict=True)}
    if len(metadata) != len(flow_run["links"]) or set(metadata) != expected:
        raise ValueError("Dense flows do not match the frozen adjacent frame sequence")
    rows = []
    with ExitStack() as stack:
        ply = stack.enter_context(ZipFile(prep.CLOUDS))
        image_files = prep.open_images(stack, (f[k]["archive"] for r in manifest["roster"]
                                              for f in r["frames"] for k in ("rgb", "depth")))
        for index, plan in enumerate(manifest["roster"], 1):
            tuber, selected, sequence = plan["tuber"], plan["selected_suffixes"], plan["frames"]
            suffixes = [r["suffix"] for r in sequence]
            anchor = align.in_mm(plan["center_to_sfm_m"])
            views, support_rows = {}, []
            start = time.perf_counter()
            for frame in sequence:
                suffix = frame["suffix"]
                try:
                    view = align.read_view(frame, ply, image_files, matrix)
                    support_rows.append({"suffix": suffix, "failure": None, **view["calibration"]})
                except (ValueError, np.linalg.LinAlgError, KeyError, OSError, BadZipFile) as error:
                    view = None
                    support_rows.append({"suffix": suffix, "failure": str(error)})
                views[suffix] = view
            row = {"tuber": tuber, "support_checks": support_rows,
                   "load_and_support_wall_s": time.perf_counter()-start, "methods": {}}
            clouds = {}
            start = time.perf_counter()
            base = views[selected[1]]
            row["methods"]["center"] = {"failure": None if base else "Center cloud failed support check"}
            if base:
                clouds["center"] = align.voxel(align.apply(base["points"], anchor), 1.)
            row["methods"]["center"]["geometry_wall_s"] = time.perf_counter()-start

            local_meta = {(x, y): v for (name, x, y), v in metadata.items() if name == tuber}
            for method in ("icp", "raft"):
                start = time.perf_counter()
                links, details = registers(views, sequence, method, local_meta, matrix)
                method_row = {"links": details, "failure": None, "to_center": None}
                if any(link is None for link in links):
                    method_row["failure"] = "At least one required adjacent registration failed"
                else:
                    try:
                        clouds[method], method_row["to_center"] = fuse(views, suffixes, selected, links, anchor)
                    except (ValueError, np.linalg.LinAlgError) as error:
                        method_row["failure"] = str(error)
                method_row["geometry_wall_s"] = time.perf_counter()-start
                if method == "raft":
                    method_row["flow_wall_s"] = sum(value["wall_s"] for value in local_meta.values())
                row["methods"][method] = method_row
            for method, cloud in clouds.items():
                row["methods"][method]["point_count"] = len(cloud)
            path = output/f"{tuber}.npz"
            with path.open("wb") as f:
                np.savez_compressed(f, **clouds)
            row["cloud_sha256"] = prep.digest(path)
            rows.append(row)
            states = {m: v["failure"] or "OK" for m, v in row["methods"].items()}
            print(f"Registered {index}/{len(manifest['roster'])} {tuber}: {states}", flush=True)

    prep.write_json(registration_path, {"recipe": recipe, "potatoes": rows})
    failures = []
    for r in rows:
        for f in r["support_checks"]:
            if f["failure"]:
                failures.append({"tuber": r["tuber"], "method": "shared_support",
                                 "source_suffix": f["suffix"], "target_suffix": "", "reason": f["failure"]})
        for method, data in r["methods"].items():
            bad = [link for link in data.get("links", []) if link["failure"]]
            for link in bad:
                failures.append({"tuber": r["tuber"], "method": method, "source_suffix": link["source"],
                                 "target_suffix": link["target"], "reason": link["failure"]})
            if data["failure"] and not bad:
                failures.append({"tuber": r["tuber"], "method": method, "source_suffix": "",
                                 "target_suffix": "", "reason": data["failure"]})
    with (prep.STUDY/"registration_failures.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["tuber", "method", "source_suffix", "target_suffix", "reason"])
        writer.writeheader()
        writer.writerows(failures)


if __name__ == "__main__":
    run()
