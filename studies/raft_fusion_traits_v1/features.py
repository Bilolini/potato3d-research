"""Build reference-free center, individual and fused geometry features."""

from contextlib import ExitStack
from pathlib import Path
import csv
import sys
import time
from zipfile import BadZipFile, ZipFile

import numpy as np

import roster as prep

# Same archived Torch environment as the pilot, with its cached pure-Python Trimesh.
sys.path.append(str(prep.ROOT/"outputs/corepp_cross_model/triposr/deps"))
import alignment as align
import flow as raft
import register as registration
from scipy.spatial import ConvexHull, QhullError
import torch

CONDITIONS = ("A", "B", "C", "D")
GEOMETRY_ERRORS = (ValueError, np.linalg.LinAlgError, QhullError, OSError, KeyError, BadZipFile)
CPU_ENV = ("2.7.1", "0.22.1")


def bulk(points):
    area = float(ConvexHull(points[:, :2]).volume)
    height = max(0., 350. - float(np.quantile(points[:, 2], .05)))
    if not np.isfinite(area) or area <= 0. or not np.isfinite(height):
        raise ValueError("Invalid projected hull or height")
    return {"area_mm2": area, "height_mm": height, "proxy_cm3": area * height / 1000.}


def archived_single_views():
    centers = prep.indexed_rows(prep.CORRECTION/"scan_features.csv")
    archived = {}
    for tuber,row in centers.items():
        archived[tuber,int(row["center_suffix_px"])] = {
            "area_mm2": float(row["center_area_mm2"]),
            "height_mm": float(row["center_height_mm"]),
            "proxy_cm3": float(row["center_proxy_cm3"]),
        }
    with (prep.ORIGINAL/"per_frame_predictions.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            archived[row["tuber"],int(row["suffix_px"])] = {
                "area_mm2": float(row["area_mm2"]),
                "height_mm": float(row["height_mm"]),
                "proxy_cm3": float(row["bulk_proxy_cm3"]),
            }
    return archived


def load_views(plan, cloud_archive, images, k):
    loaded, diagnostics, elapsed = {}, [], {}
    for item in plan["frames"]:
        suffix = item["suffix"]
        started = time.perf_counter()
        try:
            if item["problems"]:
                raise ValueError(" | ".join(item["problems"]))
            loaded[suffix] = align.read_view(item, cloud_archive, images, k)
            diagnostics.append({"suffix": suffix, "error": None, **loaded[suffix]["calibration"]})
        except GEOMETRY_ERRORS as error:
            loaded[suffix] = None
            diagnostics.append({"suffix": suffix, "error": str(error)})
        elapsed[suffix] = time.perf_counter() - started
    return loaded, diagnostics, elapsed


def make_flow(first, second, tracker, normalize):
    x0, y0, x1, y1 = raft.crop_bounds(first, second)
    a, b = first[y0:y1,x0:x1,:3], second[y0:y1,x0:x1,:3]
    return {"origin": np.array([x0,y0]),
            "forward": raft.predict(a,b,tracker,normalize),
            "reverse": raft.predict(b,a,tracker,normalize)}


def get_rgba(frame, images, cache):
    suffix = frame["suffix"]
    if suffix not in cache:
        member = frame["rgb"]
        cache[suffix] = prep.pilot.read_rgba(images[member["archive"]],member)
    return cache[suffix]


def fused_features(plan, views, method, images, k, tracker, normalize, runtime):
    sequence = plan["frames"]
    rgba = {}
    poses, diagnostics = [], []
    for source,target in zip(sequence[:-1],sequence[1:],strict=True):
        a,b = source["suffix"],target["suffix"]
        detail = {"source": a, "target": b, "error": None, "transform": None}
        pose = None
        try:
            if views[a] is None or views[b] is None:
                raise ValueError("Required view failed the pilot depth support check")
            if method == "D":
                started = time.perf_counter()
                try:
                    first = get_rgba(source,images,rgba)
                    second = get_rgba(target,images,rgba)
                    flows = make_flow(first,second,tracker,normalize)
                finally:
                    runtime["D_flow_s"] += time.perf_counter()-started
                    rgba.pop(a,None)
            started = time.perf_counter()
            try:
                if method == "C":
                    pose = align.estimate_icp(views[a],views[b],detail)
                else:
                    src,dst = align.flow_matches(views[a],views[b],flows,k,detail)
                    pose = align.ransac(src,dst,detail)
                if not prep.pilot.safe_rigid(pose):
                    raise ValueError("Estimated link is not a proper rigid transform")
            finally:
                runtime[f"{method}_fit_fuse_feature_s"] += time.perf_counter()-started
        except (*GEOMETRY_ERRORS, RuntimeError) as error:
            detail["error"] = str(error)
            pose = None
        if pose is not None:
            detail["transform"] = pose.tolist()
        poses.append(pose)
        diagnostics.append(detail)
    if any(t is None for t in poses):
        return None,diagnostics,None,"one or more required adjacent links failed"
    started = time.perf_counter()
    try:
        # Identity means the output and voxel origin remain in the center camera frame.
        points,maps = registration.fuse(views,[v["suffix"] for v in sequence],plan["selected"],poses,np.eye(4))
        result = {**bulk(points),"points":len(points)}
        return result,diagnostics,maps,None
    except GEOMETRY_ERRORS as error:
        return None,diagnostics,None,str(error)
    finally:
        runtime[f"{method}_fit_fuse_feature_s"] += time.perf_counter()-started


def single_feature(tuber, suffix, view, cached):
    current = bulk(view["points"])
    archived = cached.get((tuber,suffix))
    if archived is None:
        return {**current,"points":len(view["points"]),"archive_reused":False}
    if any(abs(current[key]-archived[key])>1e-8 for key in archived):
        raise ValueError(f"Archived single-frame geometry does not replay: {tuber} {suffix}")
    return {**archived,"points":len(view["points"]),"archive_reused":True}


def build(plan, cloud_archive, images, k, tracker, normalize, cached, fingerprint):
    views,checks,loads = load_views(plan,cloud_archive,images,k)
    lower,center,upper = plan["selected"]
    runtime = {"center_support_s":loads[center],"outer_support_s":loads[lower]+loads[upper],
               "intermediate_support_s":sum(v for s,v in loads.items() if s not in plan["selected"]),
               "center_feature_s":0.,"outer_feature_s":0.,"C_fit_fuse_feature_s":0.,
               "D_fit_fuse_feature_s":0.,"D_flow_s":0.}
    singles = {}
    problems = []
    for position,item in zip(("lower","center","upper"),plan["selected"],strict=True):
        started = time.perf_counter()
        singles[position] = None
        if views[item] is not None:
            try:
                singles[position] = single_feature(plan["tuber"],item,views[item],cached)
            except GEOMETRY_ERRORS as error:
                problems.append({"method": "A/B", "source": item, "target": "", "error": str(error)})
        runtime["center_feature_s" if position=="center" else "outer_feature_s"] += time.perf_counter()-started
    row = {
        "tuber":plan["tuber"],"split":plan["split"],"selected":plan["selected"],
        "feature_fingerprint":fingerprint,"single_views":singles,
        "features":{"A":singles["center"]["proxy_cm3"] if singles["center"] else None,
                    "B":[v["proxy_cm3"] for v in singles.values()] if all(singles.values()) else None},
        "support_checks":checks,"registration":{},"runtime_s":runtime,"extra_failures":problems,
    }
    for method in ("C","D"):
        fused,links,maps,error = fused_features(plan,views,method,images,k,tracker,normalize,runtime)
        row["registration"][method] = {"failure":error,"links":links,"to_center":maps,"fused":fused}
        row["features"][method] = fused["proxy_cm3"] if fused is not None else None
    return row


def save_failures(rows):
    failures = []
    for row in rows:
        common = {"tuber":row["tuber"],"split":row["split"]}
        for check in row["support_checks"]:
            if check["error"]:
                failures.append({**common,"method":"support","source":check["suffix"],"target":"","error":check["error"]})
        failures.extend({**common,**f} for f in row["extra_failures"])
        for method,saved in row["registration"].items():
            bad = [v for v in saved["links"] if v["error"]]
            failures.extend({**common,"method":method,"source":v["source"],"target":v["target"],"error":v["error"]}
                            for v in bad)
            if saved["failure"] and not bad:
                failures.append({**common,"method":method,"source":"","target":"","error":saved["failure"]})
    with (prep.STUDY/"failures.csv").open("w",newline="") as f:
        writer = csv.DictWriter(f,fieldnames=("tuber","split","method","source","target","error"))
        writer.writeheader()
        writer.writerows(failures)
    return len(failures)


def run():
    frozen = prep.read_freeze()
    old_flow = prep.pilot.read_json(prep.pilot.ASSETS/"flow_run.json")
    if (torch.__version__,raft.torchvision.__version__) != (old_flow["torch"],old_flow["torchvision"]):
        raise ValueError("Use the archived pilot Torch and Torchvision versions")
    if old_flow["flow_code_sha256"] != prep.pilot.digest(prep.PILOT/"flow.py"):
        raise ValueError("Pilot flow code changed")
    manifest_hash = prep.pilot.digest(prep.STUDY/"frame_manifest.json")
    output = prep.OUTPUTS/"features"
    output.mkdir(parents=True,exist_ok=True)
    recipe = {"frame_manifest_sha256":manifest_hash,"checkpoint_sha256":frozen["checkpoint_sha256"],
              "torch":torch.__version__,"torchvision":raft.torchvision.__version__,
              "code_sha256":prep.pilot.digest(Path(__file__))}
    prep.pilot.freeze_check(prep.OUTPUTS/"feature_recipe.json",recipe)
    fingerprint = prep.pilot.digest(prep.OUTPUTS/"feature_recipe.json")

    started = time.perf_counter()
    tracker,normalize,_ = raft.model()
    setup = time.perf_counter()-started
    k = registration.camera()
    cached = archived_single_views()
    rows = []
    with ExitStack() as stack,torch.inference_mode():
        known = align.geometry_check(k)
        known_flow = raft.synthetic_check(tracker,normalize)
        print("Frozen geometry and flow checks passed.",flush=True)
        cloud = stack.enter_context(ZipFile(prep.pilot.CLOUDS))
        names = [f[k]["archive"] for r in frozen["roster"] for f in r["frames"]
                 for k in ("rgb","depth") if k in f]
        images = prep.pilot.open_images(stack,names)
        for index,plan in enumerate(frozen["roster"],1):
            path = output/f"{plan['tuber']}.json"
            if path.exists():
                data = prep.pilot.read_json(path)
                if data["feature_fingerprint"] != fingerprint or data["tuber"] != plan["tuber"]:
                    raise ValueError("Cached features do not match this frozen job")
            else:
                data = build(plan,cloud,images,k,tracker,normalize,cached,fingerprint)
                prep.pilot.write_json(path,data)
            rows.append({"tuber":plan["tuber"],"split":plan["split"],"cache_file":path.name,
                         "cache_sha256":prep.pilot.digest(path)})
            print(f"Features {index}/{len(frozen['roster'])} {plan['tuber']} "
                  f"{[m for m,v in data['features'].items() if v is not None]}",flush=True)
    failure_count = save_failures([prep.pilot.read_json(output/r["cache_file"]) for r in rows])
    prep.pilot.write_json(prep.OUTPUTS/"feature_run.json", {
        "recipe":recipe,"fingerprint":fingerprint,"records":rows,"geometry_check":known,
        "flow_check":known_flow,"failure_count":failure_count,"model_setup_s":setup,
    })


if __name__ == "__main__":
    run()
