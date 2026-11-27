"""Replicate the CoRe++ RGB patch swap on ten frozen development frames."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from pathlib import Path
from statistics import mean, median
from tempfile import TemporaryDirectory

import cv2 as cv
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import corepp_pin_accuracy as accuracy
from . import corepp_pin_confirmation as confirmation
from . import corepp_pin_grid_boundary as grid
from . import corepp_pin_multituber as multi
from . import corepp_pin_swap_pilot as swap
from .corepp_pin_multituber import audit, pilot

PROTOCOL = audit.HERE / "corepp_pin_swap_replication_protocol.md"
PATCHES = multi.EDIT_NAMES[1:]
LAYOUTS = ("native", *PATCHES)
NATIVE = ("original", *multi.EDIT_NAMES)
TOL = swap.SIGN_TOL_MM
EXPECTED_FAILURES = (ValueError, KeyError, RuntimeError, AssertionError, OSError, cv.error)


def code_hashes():
    return {p.name: audit.sha256(p) for p in (
        Path(__file__), PROTOCOL, Path(swap.__file__), Path(grid.__file__), Path(accuracy.__file__),
        Path(confirmation.__file__), Path(multi.__file__), Path(pilot.__file__), Path(audit.__file__),
    )}


def rgba_path(folder, layout, condition):
    return folder / f"{layout}_{condition}_rgba.png"


def save_panels(path, rgb, masks, obj, frame, outlines):
    # Use the same image bounds and zoom for all four layouts of a potato.
    xy = np.array(np.nonzero(np.logical_or.reduce(list(masks.values()))))
    y0, x0 = np.maximum(xy.min(axis=1) - 14, 0)
    y1, x1 = np.minimum(xy.max(axis=1) + 15, rgb["native"].shape[:2])
    w, h = int(x1-x0), int(y1-y0)
    zoom = min(2.6, 285/w, 234/h)
    size = (round(w * zoom), round(h * zoom))
    result = Image.new("RGB", (size[0]*4+50, size[1]+58), "white")
    draw = ImageDraw.Draw(result)
    title = ImageFont.load_default(size=16)
    label = ImageFont.load_default(size=13)
    draw.text((10, 5), f"{obj} / {frame}", fill="#182633", font=title)
    for i, layout in enumerate(LAYOUTS):
        offset = 10 + i * (size[0] + 10)
        draw.text((offset, 30), "Native" if layout == "native" else f"Swap with peel {i}",
                  fill="#182633", font=label)
        pixels = rgb[layout].copy()
        if outlines:
            for name, color in zip(("pin", *PATCHES), multi.COLORS, strict=True):
                if layout == "native" or name in ("pin", layout):
                    mask = masks[name]
                    pixels[mask & ~cv.erode(mask.astype(np.uint8), np.ones((3,3), np.uint8)).astype(bool)] = color
        image = Image.fromarray(pixels[y0:y1, x0:x1]).resize(size, Image.Resampling.NEAREST)
        result.paste(image, (offset, 49))
    result.save(path)


def prepare_one(runtime, frame, source, local, out):
    obj = frame["tuber"]
    original = swap.read_image(source / "original_rgba.png")
    original_rgb = swap.read_image(grid.ARCHIVE / obj / "original_rgb.png")
    masks = {name: swap.read_image(grid.ARCHIVE / obj / f"{name}_mask.png").astype(bool) for name in multi.EDIT_NAMES}
    delta = np.load(grid.ARCHIVE / obj / "realized_rgb_delta.npy", allow_pickle=False)
    if np.max(np.sum(list(masks.values()), axis=0)) != 1:
        raise ValueError("Archived masks overlap")
    model_positions = {name: np.nonzero(mask) for name, mask in masks.items()}
    pin_y, pin_x = model_positions["pin"]
    for name, spec in zip(PATCHES, frame["patches"]["patches"], strict=True):
        dx, dy = spec["offset_xy_px"]
        y, x = model_positions[name]
        np.testing.assert_array_equal(y, pin_y + dy)
        np.testing.assert_array_equal(x, pin_x + dx)
    trace = frame["crop_trace"]
    r, c = trace["crop_origin_yx_px"]
    left, top, _, _ = trace["pad_ltrb_px"]
    raw_positions = {name: (y+r-top, x+c-left) for name, (y,x) in model_positions.items()}
    depth = cv.imread(str(source / "depth.png"), cv.IMREAD_UNCHANGED)
    _, valid = multi.masks_for(frame["annotation"], trace, original, depth)[:2]
    if audit.array_sha256(valid) != frame["valid_mask_sha256"] or any(not valid[m].all() for m in masks.values()):
        raise ValueError("Mask does not match the archived valid crop")
    (local / "depth.png").write_bytes((source / "depth.png").read_bytes())
    runtime.bind(local, frame["annotation"])
    for name, mask in masks.items():
        edited = swap.read_image(grid.ARCHIVE / obj / f"{name}_rgb.png")
        np.testing.assert_array_equal(edited[mask].astype(np.int16) - original_rgb[mask], delta)
    base_previews, tensors, delta_checks, no_change = {}, {}, {}, {}
    roundtrip = {}
    for layout in LAYOUTS:
        places = (raw_positions["pin"], raw_positions["peel1" if layout == "native" else layout])
        exchanging = layout != "native"
        base = swap.exchange(original, places, exchanging)
        np.testing.assert_array_equal(swap.exchange(base, places, exchanging), original)
        roundtrip[layout] = {"identity_or_double_swap_exact": True}
        condition_names = NATIVE if layout == "native" else ("original", "pin", layout)
        tensors[layout], delta_checks[layout] = {}, {}
        for condition in condition_names:
            if condition == "original":
                rgba = base
            else:
                y, x = raw_positions[condition]
                candidate = base[y, x, :3].astype(np.int16) + delta
                if np.any((candidate < 0) | (candidate > 255)):
                    raise ValueError(f"RGB clipping on {layout}/{condition}")
                rgba = pilot.apply_delta(base, y, x, delta)
                changed = np.any(rgba != base, axis=2)
                if changed.sum() != changed[y, x].sum():
                    raise ValueError(f"Off-mask RGB change on {layout}/{condition}")
            path = rgba_path(local, layout, condition)
            Image.fromarray(rgba).save(path)
            np.testing.assert_array_equal(swap.read_image(path), rgba)
            np.testing.assert_array_equal(rgba[..., 3], original[..., 3])
            tensor, rgb, observed_trace = runtime.prepare(path, pilot.SEEDS[0])
            tensor_hash = audit.array_sha256(tensor.numpy())
            if observed_trace != trace or audit.array_sha256(tensor.numpy()[:,3]) != frame["depth_tensor_sha256"]:
                raise ValueError(f"Crop or depth changed on {layout}/{condition}")
            if layout == "native" and tensor_hash != frame["tensor_sha256"][condition]:
                raise ValueError(f"Native control changed on {condition}")
            if condition == "original":
                base_previews[layout] = rgb
                expected = original_rgb.copy()
                if exchanging:
                    expected[masks["pin"]] = original_rgb[masks[layout]]
                    expected[masks[layout]] = original_rgb[masks["pin"]]
                np.testing.assert_array_equal(expected, rgb)
                roundtrip[layout]["model_rgb_sha256"] = audit.array_sha256(rgb)
            else:
                mask = masks[condition]
                original_layout = base_previews[layout]
                np.testing.assert_array_equal(rgb[~mask], original_layout[~mask])
                np.testing.assert_array_equal(rgb[mask].astype(np.int16) - original_layout[mask], delta)
                delta_checks[layout][condition] = pilot.rgb_change(original_layout, rgb, mask) | {"clipped_channels": 0}
            tensors[layout][condition] = tensor_hash
            Image.fromarray(rgb).save(out / f"{layout}_{condition}_rgb.png")
    for name, (y, x) in raw_positions.items():
        no_change[name] = {k: float(f(depth[y,x])) for k,f in (("min",np.min),("mean",np.mean),("max",np.max))}
    save_panels(out / "layouts.png", base_previews, masks, obj, frame["frame"], False)
    save_panels(out / "overlays.png", base_previews, masks, obj, frame["frame"], True)
    return {"roundtrips": roundtrip, "tensor_sha256": tensors, "rgba_sha256": multi.hashes(local),
            "evidence_sha256": multi.hashes(out), "depth_mm_by_site": no_change, "delta_checks": delta_checks,
            "delta_sha256": audit.array_sha256(delta), "failure": None}


def prepare(args, runtime, frames, provenance):
    args.swap_input_dir.mkdir(parents=True, exist_ok=False)
    output = []
    for frame in frames:
        obj = frame["tuber"]
        local, out = args.swap_input_dir / obj, args.out_dir / obj
        local.mkdir()
        out.mkdir()
        row = {k: frame[k] for k in ("tuber","frame","annotation","registration_sha256")}
        try:
            row.update(prepare_one(runtime, frame, args.input_dir/obj, local, out))
        except EXPECTED_FAILURES as exc:
            row["failure"] = f"{type(exc).__name__}: {exc}"
        output.append(row)
        print(f"{obj}: {row['failure'] or 'three swaps and native controls verified'}", flush=True)
    pilot.put_json(args.out_dir/"intake.json", {"cpu_runtime_provenance": runtime.provenance_record,
                                              "archived_grid_provenance": provenance, "frames": output})


def verify(args, expected, provenance):
    data = audit.read_json(args.out_dir/"intake.json")
    if data["archived_grid_provenance"] != provenance:
        raise ValueError("The archived grid has changed")
    if [(r["tuber"],r["frame"]) for r in data["frames"]] != [(r["tuber"],r["frame"]) for r in expected]:
        raise ValueError("Intake differs from the archived development roster")
    for row in data["frames"]:
        if row["failure"]:
            continue
        for directory,key in ((args.swap_input_dir,"rgba_sha256"),(args.out_dir,"evidence_sha256")):
            if multi.hashes(directory/row["tuber"]) != row[key]:
                raise ValueError(f"Changed prepared file under {directory/row['tuber']}")
    return data


def seal(args, data):
    review = audit.read_json(args.review)
    expected = {r["tuber"]:r for r in data["frames"] if not r["failure"]}
    if set(review["frames"]) != set(expected):
        raise ValueError("Visual review must cover every prepared frame")
    for obj, entry in review["frames"].items():
        if set(entry["patches"]) != set(PATCHES) or entry["crop_sha256"] != expected[obj]["evidence_sha256"]["layouts.png"]:
            raise ValueError(f"Invalid crop review for {obj}")
    pilot.put_json(args.out_dir/"frozen_inputs.json", {
        "status":"frozen_before_inference", "intake_sha256":audit.sha256(args.out_dir/"intake.json"),
        "review_sha256":audit.sha256(args.review), "code_sha256":code_hashes(), "review":review,
        "tie_tolerance_mm":TOL, "seeds":list(pilot.SEEDS), **data,
    })


MODEL = None


def init_worker(args, provenance):
    global MODEL
    MODEL = confirmation.Model(args, provenance)


def replay_native(prediction, archive, inner, name):
    saved = archive["expanded_grid"][name]
    observed = prediction["hashes"]
    if (any(observed[k] != inner["hashes"][k] for k in ("tensor","latent")) or
            observed["interior_sdf"] != inner["hashes"]["sdf"] or
            observed["shell_sdf"] != saved["shell_sdf_sha256"] or
            observed["sdf"] != saved["expanded_sdf_sha256"] or
            prediction["mesh_failure"] is not None or abs(prediction["volume_ml"] - saved["volume_ml"]) > 1e-8):
        raise ValueError(f"Native archive replay differs at seed {archive['seed']} / {name}")


def seed_key(layout, seed):
    return f"{layout}_{seed}"


def no_op_frame(args, row, archived, interior):
    obj = row["tuber"]
    folder = args.swap_input_dir / obj
    MODEL.runtime.bind(folder,row["annotation"])
    checks, cache = [], {}
    with TemporaryDirectory(prefix="corepp-swap-replay-") as temp:
        for layout in LAYOUTS:
            base_path = rgba_path(folder,layout,"original")
            base = swap.read_image(base_path)
            y,x=np.nonzero(base[...,3]==255)
            noop_path=Path(temp)/"noop.png"
            Image.fromarray(pilot.apply_delta(base,y,x,np.zeros((len(x),3),dtype=np.int16))).save(noop_path)
            np.testing.assert_array_equal(swap.read_image(noop_path),base)
            h=row["tensor_sha256"][layout]["original"]
            a,b=(MODEL.tensor(p,h) for p in (base_path,noop_path))
            for seed, old, inside in zip(pilot.SEEDS,archived["pairs"],interior["seeds"],strict=True):
                main, replay=(MODEL.predict(t,seed) for t in (a,b))
                if layout=="native":
                    replay_native(main,old,inside["conditions"]["original"],"original")
                p,q=(r["mesh"] for r in (main,replay))
                surface=None if p is None or q is None else pilot.surface_pair(swap.canonical_mesh(p),swap.canonical_mesh(q))
                passed=(surface is not None and surface["identical_mesh_arrays"] and surface["max_mm"]<=pilot.SURFACE_TOL_MM
                        and main["hashes"]==replay["hashes"] and main["volume_ml"]==replay["volume_ml"])
                record={"layout":layout,"seed":seed,"passed":passed,"surface":surface,
                        "original_hashes":main["hashes"],"no_op_hashes":replay["hashes"],
                        "raw_mesh_arrays_equal":p is not None and q is not None and pilot.same_mesh(p,q),
                        "original_volume_ml":main["volume_ml"],"boundary":main["boundary"],
                        "mesh_failures":[main["mesh_failure"],replay["mesh_failure"]]}
                checks.append(record)
                if passed:
                    key=seed_key(layout,seed)
                    cache.update({f"{k}_{key}":v for k,v in (
                        ("latent",main["latent"]),("sdf",main["sdf"]),
                        ("vertices",np.array(p.vertices)),("triangles",np.array(p.triangles)))})
    if not all(x["passed"] for x in checks):
        return {"tuber":obj,"pairs":checks,"failure":"At least one exact no-op pair failed"}
    path=args.work_dir/"cache"/f"{obj}.npz"
    np.savez(path,**cache)
    return {"tuber":obj,"pairs":checks,"cache_sha256":audit.sha256(path),"failure":None}


def from_cache(cache, check):
    key = seed_key(check["layout"], check["seed"])
    # The existing cache reader validates the signed distances and latent, then reconstructs the exact mesh arrays.
    return confirmation.baseline_from_cache(cache, check | {"seed":key})


def sign(value):
    return (value > TOL) - (value < -TOL)


def classify(before, after):
    a,b = sign(before),sign(after)
    if a == 1 and b == -1:
        return "pilot_reversal"
    if a == -1 and b == 1:
        return "opposite_reversal"
    if a == 0 or b == 0:
        return "both_tied" if a == b else "native_tied" if a == 0 else "swapped_tied"
    change=sign(abs(after)-abs(before))
    movement={-1:"weakened",0:"unchanged",1:"strengthened"}[change]
    return ("pin_" if a>0 else "peel_") + movement


def score_frame(args, row, archived, interior, verified):
    obj=row["tuber"]
    local=args.swap_input_dir/obj
    MODEL.runtime.bind(local,row["annotation"])
    conditions={l:{n:MODEL.tensor(rgba_path(local,l,n),h) for n,h in v.items() if n!="original"}
                for l,v in row["tensor_sha256"].items()}
    checks={(x["layout"],x["seed"]):x for x in verified["pairs"]}
    path=args.work_dir/"cache"/f"{obj}.npz"
    if audit.sha256(path)!=verified["cache_sha256"] or len(checks)!=4*len(pilot.SEEDS):
        raise ValueError("Unchanged reference cache differs from the frozen no-op")
    seeds=[]
    with np.load(path,allow_pickle=False) as cache:
        for seed,old,inside in zip(pilot.SEEDS,archived["pairs"],interior["seeds"],strict=True):
            base={l:from_cache(cache,checks[l,seed]) for l in LAYOUTS}
            changes, detail = {}, {}
            for l in LAYOUTS:
                edits={}
                for name,tensor in conditions[l].items():
                    edit=MODEL.predict(tensor,seed)
                    if l=="native":
                        replay_native(edit,old,inside["conditions"][name],name)
                    edits[name]=swap.measure(base[l],edit) | {k:edit[k] for k in ("hashes","boundary","volume_ml","mesh_failure")}
                    if l=="native":
                        sampled=grid.surface_displacement(base[l],edit)
                        edits[name]["archived_displacement_abs_difference_mm"]=abs(
                            sampled-old["expanded_grid"][name]["displacement_mm"])
                changes[l]=edits
            for patch in PATCHES:
                n=changes["native"]
                s=changes[patch]
                values=[pred["surface_mm"] for pred in (n["pin"],n[patch],s["pin"],s[patch])]
                before, after, paired, category=None,None,None,None
                if values[0] is not None and values[1] is not None:
                    before=values[0]-values[1]
                if values[2] is not None and values[3] is not None:
                    after=values[2]-values[3]
                if before is not None and after is not None:
                    paired=before-after
                    category=classify(before,after)
                detail[patch]={"native_contrast_mm":before,"swapped_contrast_mm":after,"paired_shift_mm":paired,
                               "category":category,"unedited_swap":swap.measure(base["native"],base[patch])}
            shifts=[p["paired_shift_mm"] for p in detail.values()]
            seeds.append({"seed":seed,"patches":detail,"predictions":changes,
                          "mean_patch_shift_mm":mean(shifts) if all(v is not None for v in shifts) else None})
    result={"tuber":obj,"frame":row["frame"],"seeds":seeds,"patches":{}}
    for patch in PATCHES:
        entries=[s["patches"][patch] for s in seeds]
        medians={k:pilot.summarize([p[k] for p in entries if p[k] is not None]) for k in
                 ("native_contrast_mm","swapped_contrast_mm","paired_shift_mm")}
        summary=medians | {"unedited_swap_surface_mm":pilot.summarize([p["unedited_swap"]["surface_mm"] for p in entries
                                                                      if p["unedited_swap"]["surface_mm"] is not None]),
                           "seed_categories":dict(Counter(p["category"] or "incomplete" for p in entries))}
        if medians["paired_shift_mm"]["n"]==len(pilot.SEEDS):
            summary["category"]=classify(medians["native_contrast_mm"]["median"],medians["swapped_contrast_mm"]["median"])
        result["patches"][patch]=summary
    endpoint=pilot.summarize([s["mean_patch_shift_mm"] for s in seeds if s["mean_patch_shift_mm"] is not None])
    result["endpoint_mm"]=endpoint
    result["failure"]=None if endpoint["n"]==len(pilot.SEEDS) else "Incomplete set of paired predictions"
    return result


def worker(job):
    args,row,archive,inside,verified=job
    try:
        if args.phase=="noop":
            result=no_op_frame(args,row,archive,inside)
        else:
            result=score_frame(args,row,archive,inside,verified)
    except EXPECTED_FAILURES as exc:
        result={"tuber":row["tuber"],"frame":row["frame"],"failure":f"{type(exc).__name__}: {exc}"}
    pilot.put_json(args.work_dir/f"{args.phase}_rows"/f"{row['tuber']}.json",result)
    return result


def cohort(records):
    complete=[r for r in records if not r["failure"]]
    endpoints={r["tuber"]:r["endpoint_mm"]["median"] for r in complete}
    votes={}
    for row in complete:
        counts=Counter(p["category"] for p in row["patches"].values())
        votes[row["tuber"]]=dict(counts)
    return {"selected":len(records),"complete":len(complete),
            "endpoint_mean_mm":mean(endpoints.values()) if endpoints else None,
            "endpoint_median_mm":median(endpoints.values()) if endpoints else None,
            "endpoint_positive":sum(sign(x)>0 for x in endpoints.values()),
            "endpoint_tied":sum(sign(x)==0 for x in endpoints.values()),
            "endpoint_negative":sum(sign(x)<0 for x in endpoints.values()),
            "majority_pilot_direction":sum(v.get("pilot_reversal",0)>=2 for v in votes.values()),
            "majority_opposite_direction":sum(v.get("opposite_reversal",0)>=2 for v in votes.values()),
            "majority_either_direction":sum(v.get("pilot_reversal",0)+v.get("opposite_reversal",0)>=2 for v in votes.values()),
            "patch_classes":dict(Counter(p["category"] for r in records for p in r.get("patches",{}).values() if "category" in p)),
            "patch_votes_by_potato":votes,
            "leave_one_out_means_mm":{obj:mean(v for name,v in endpoints.items() if name!=obj) for obj in endpoints} if len(endpoints)>1 else {}}


def run(args, frozen, archived, interior):
    out, phase = args.out_dir, args.phase
    freeze_hash=audit.sha256(out/"frozen_inputs.json")
    if phase=="noop":
        (args.work_dir/"cache").mkdir(parents=True,exist_ok=False)
        prior={}
    else:
        no_op_path=out/"no_op_replay.json"
        replay=audit.read_json(no_op_path)
        if replay["frozen_inputs_sha256"]!=freeze_hash:
            raise ValueError("The no-op replay is for a different frozen input set")
        prior={r["tuber"]:r for r in replay["frames"]}
        pilot.put_json(out/"score_started.json",{"frozen_inputs_sha256":freeze_hash,"no_op_sha256":audit.sha256(no_op_path)})
    (args.work_dir/f"{phase}_rows").mkdir()
    jobs, result = [], {}
    for row,old,inside in zip(frozen["frames"],archived,interior,strict=True):
        obj=row["tuber"]
        previous=prior[obj] if phase=="score" else None
        blocked=row["failure"] or (previous and previous["failure"])
        if blocked:
            result[obj]={"tuber":obj,"frame":row["frame"],"failure":blocked}
        else:
            jobs.append((args,row,old,inside,previous))
    context=multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=context,initializer=init_worker,
                             initargs=(args,frozen["cpu_runtime_provenance"])) as pool:
        for row in pool.map(worker,jobs):
            result[row["tuber"]]=row
            print(f"{phase} {row['tuber']}: {row['failure'] or 'all seed pairs passed'}",flush=True)
    records=[result[r["tuber"]] for r in frozen["frames"]]
    summary={"frozen_inputs_sha256":freeze_hash,"frames":records}
    if phase=="score":
        summary.update(cohort=cohort(records),no_op_sha256=audit.sha256(no_op_path))
    pilot.put_json(out/("no_op_replay.json" if phase=="noop" else "results.json"),summary)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase",choices=("prepare","seal","noop","score"))
    for name in ("upstream","released","input-dir","swap-input-dir","work-dir","out-dir"):
        p.add_argument(f"--{name}",type=Path,required=True)
    p.add_argument("--review",type=Path)
    p.add_argument("--workers",type=int,default=5)
    args=p.parse_args()
    args.out_dir.mkdir(parents=True,exist_ok=True)
    runtime=multi.Runtime(argparse.Namespace(**(vars(args)|{"phase":"prepare"})))
    _,_,_,expanded,interior,provenance=accuracy.archive_context(args,runtime)
    frames=multi.audit.read_json(grid.ARCHIVE/"frozen_inputs.json")["frames"]
    if args.phase=="prepare":
        prepare(args,runtime,frames,provenance)
        return
    data=verify(args,frames,provenance)
    if args.phase=="seal":
        seal(args,data)
        return
    frozen=audit.read_json(args.out_dir/"frozen_inputs.json")
    if (frozen["intake_sha256"]!=audit.sha256(args.out_dir/"intake.json") or frozen["code_sha256"]!=code_hashes()
            or any(frozen[k]!=value for k,value in data.items())):
        raise ValueError("Inputs or code changed after freeze")
    run(args,frozen,expanded,interior)


if __name__=="__main__":
    main()
