"""Source-lock and rebuild paired center-camera point samples from cached RAFT poses."""

import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
from pathlib import Path
import sys
import time
from zipfile import BadZipFile, ZipFile

import numpy as np
from scipy.spatial import ConvexHull, QhullError, cKDTree

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
PILOT = STUDY.parent / "raft_fusion_geometry_v1"
TRAIT_STUDY = STUDY.parent / "raft_fusion_traits_v1"
TRAIT_CACHE = ROOT / "outputs/raft_fusion_traits_v1"
OUTPUT = ROOT / "outputs/raft_pointcloud_weight_v1"
sys.path.insert(0,str(PILOT))
sys.path.append(str(ROOT/"outputs/corepp_cross_model/triposr/deps"))
import prepare as pilot
import alignment as align
import register

TRAITS = pilot.RELEASE / "3_pair/ground_truth.csv"
SAMPLE_COUNT = 1024
ARMS = ("center","fused")
INNER_PREFIX = "raft-pointcloud-inner-v1/133/"


def hashed(text):
    return hashlib.sha256(text.encode()).hexdigest()


def source_hashes():
    paths = (STUDY/"protocol.md",Path(__file__),PILOT/"prepare.py",PILOT/"alignment.py",PILOT/"register.py",
             pilot.CAMERA,TRAIT_STUDY/"frame_manifest.json",TRAIT_STUDY/"train_fit.json",
             TRAIT_STUDY/"features.py",TRAIT_CACHE/"feature_run.json",TRAITS,pilot.HELD_OUT,
             *(ROOT/name for name,_,_ in pilot.RESERVES))
    return {str(p.relative_to(ROOT)):pilot.digest(p) for p in paths}


def freeze():
    old = pilot.read_json(TRAIT_STUDY/"frame_manifest.json")
    if (old["archived_ply_bytes"]!=pilot.CLOUDS.stat().st_size
            or any(pilot.digest(ROOT/k)!=v for k,v in old["sources_sha256"].items())):
        raise ValueError("Frozen trait-study inputs changed")
    if pilot.digest(pilot.CHECKPOINT)!=old["checkpoint_sha256"]:
        raise ValueError("Frozen RAFT checkpoint hash differs")
    feature_index = pilot.read_json(TRAIT_CACHE/"feature_run.json")
    train_fit = pilot.read_json(TRAIT_STUDY/"train_fit.json")
    if (train_fit["feature_run_sha256"]!=pilot.digest(TRAIT_CACHE/"feature_run.json")
            or feature_index["recipe"]["frame_manifest_sha256"]!=pilot.digest(TRAIT_STUDY/"frame_manifest.json")
            or feature_index["recipe"]["checkpoint_sha256"]!=pilot.CHECKPOINT_HASH):
        raise ValueError("Frozen trait study and cached registration provenance disagree")
    train = set(train_fit["training_ids"]["weight"])
    val = {r["tuber"] for r in old["roster"] if r["split"]=="val"}
    keep = train | val
    reserved = {r["tuber"] for r in pilot.read_json(pilot.HELD_OUT)["roster"]}
    for path,section,key in pilot.RESERVES:
        group = pilot.read_json(ROOT/path)
        reserved.update(r[key] for r in (group[section] if section else group))
    if len(train)!=117 or len(val)!=30 or train & val or keep & (reserved | set(old["pilot_ids_excluded"])):
        raise ValueError("Unexpected train/evaluation cohort or holdout overlap")
    fixed = {r["tuber"]:r for r in feature_index["records"]}
    inner = sorted(train,key=lambda tuber:hashed(INNER_PREFIX+tuber))
    roster = []
    for r in old["roster"]:
        t = r["tuber"]
        if t not in keep:
            continue
        if r["split"]!=("train" if t in train else "val"):
            raise ValueError("Archived training fit included an invalid split")
        roster.append({
            "tuber":t,"split":r["split"],"selected":r["selected"],
            "frames":[x for x in r["frames"] if x["suffix"] in r["selected"]],
            "registration_cache":fixed[t],
        })
    freeze = {"sources_sha256":source_hashes(),"raft_checkpoint_sha256":pilot.CHECKPOINT_HASH,
              "registration_fingerprint":feature_index["fingerprint"],"roster":roster,
              "inner_validation":inner[:24],"inner_fit":inner[24:],"smoke_ids":inner[24:32],
              "excluded_geometry_pilot":old["pilot_ids_excluded"],"points":SAMPLE_COUNT}
    pilot.freeze_check(STUDY/"frame_manifest.json",freeze)
    print("Frozen 117 common training and 30 evaluation IDs, with a 93/24 inner split.")


def load_freeze():
    manifest = pilot.read_json(STUDY/"frame_manifest.json")
    if manifest["sources_sha256"]!=source_hashes():
        raise ValueError("Frozen point-cloud inputs changed")
    return manifest


def fixed_poses(plan, fingerprint):
    cache = plan["registration_cache"]
    path = TRAIT_CACHE/"features"/cache["cache_file"]
    if pilot.digest(path)!=cache["cache_sha256"]:
        raise ValueError("Saved trait-study transform changed")
    row = pilot.read_json(path)
    if (row["tuber"]!=plan["tuber"] or row["selected"]!=plan["selected"]
            or row["feature_fingerprint"]!=fingerprint):
        raise ValueError("Cached registration does not identify this frozen sequence")
    ra = row["registration"]["D"]
    if ra["failure"] or any(x["error"] for x in ra["links"]):
        raise ValueError("Frozen RAFT chain is unavailable")
    links = ra["links"]
    seq = [links[0]["source"]]+[x["target"] for x in links]
    poses = [np.asarray(x["transform"]) for x in links]
    if any(not pilot.safe_rigid(t) for t in poses):
        raise ValueError("A saved RAFT link is nonrigid")
    if any(x["source"]!=seq[i] for i,x in enumerate(links)):
        raise ValueError("Nonconsecutive cached RAFT links")
    composed = align.to_center(poses,seq.index(plan["selected"][1]))
    chosen = [composed[seq.index(s)] for s in plan["selected"]]
    if any(not np.allclose(t,ra["to_center"][str(s)],atol=1e-11,rtol=0)
           for t,s in zip(chosen,plan["selected"],strict=True)):
        raise ValueError("Cached RAFT poses fail source-to-center replay")
    if not np.array_equal(chosen[1],np.eye(4)):
        raise ValueError("Center-camera pose is not identity")
    return chosen,ra["fused"]


def geometry(points):
    area = float(ConvexHull(points[:,:2]).volume)
    height = max(0.,350.-float(np.quantile(points[:,2],.05)))
    return area,height


def matched_clouds(plan, fingerprint, archive, rgb, k):
    computed, original = fixed_poses(plan,fingerprint)
    selected = []
    for record in plan["frames"]:
        if record["problems"]:
            raise ValueError("Frozen frame has incomplete RGB-D support")
        selected.append(align.read_view(record,archive,rgb,k)["points"])
    fused = align.voxel(np.concatenate([align.apply(p,t) for p,t in zip(selected,computed,strict=True)]),1.)
    area, height = geometry(fused)
    if len(fused)!=original["points"] or abs(area-original["area_mm2"])>1e-7 or abs(height-original["height_mm"])>1e-8:
        raise ValueError("Fused cloud does not replay the archived RGB-D-only trait feature")
    return {"center":align.voxel(selected[1],1.),"fused":fused}


def fps(points, count):
    choice = int(np.argmax(np.einsum("ij,ij->i",points,points)))
    distance = np.full(len(points),np.inf)
    chosen = []
    for _ in range(count):
        chosen.append(choice)
        offset = points-points[choice]
        distance = np.minimum(distance,np.einsum("ij,ij->i",offset,offset))
        distance[choice] = -1.
        choice = int(np.argmax(distance))
    return np.array(chosen,dtype=np.int64)


def groups(points, indices, radius):
    distance, neighbors = cKDTree(points).query(points[indices],k=16)
    return np.where(distance<=radius,neighbors,indices[:,None]).astype(np.int64)


def sample_data(points, tuber):
    if len(points)<SAMPLE_COUNT:
        raise ValueError(f"Only {len(points)} occupied voxels remain")
    seed = int.from_bytes(hashlib.sha256(f"raft-pointcloud-sample-v1/{tuber}".encode()).digest()[:8],"big")
    choice = np.sort(np.random.default_rng(seed).choice(len(points),SAMPLE_COUNT,replace=False))
    measured = points[choice]
    area,height = geometry(measured)
    centered = (measured-measured.mean(axis=0))/100.
    sa1 = fps(centered,64)
    anchors = centered[sa1]
    sa2 = fps(anchors-anchors.mean(axis=0),16)
    stats = {"area_mm2":area,"height_mm":height,"proxy_cm3":area*height/1000.,"voxels":len(points)}
    return {
        "xyz":centered.astype(np.float32),"height":np.float32(height/100.),
        "anchors1":sa1,"knn1":groups(centered,sa1,2.),
        "anchors2":sa2,"knn2":groups(anchors,sa2,4.),
    },stats


def extract():
    manifest = load_freeze()
    started = time.perf_counter()
    entries = []
    stacked = {}
    used = set()
    k = register.camera()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with ExitStack() as stack:
        cloud = stack.enter_context(ZipFile(pilot.CLOUDS))
        names = {f[x]["archive"] for r in manifest["roster"] for f in r["frames"] for x in ("rgb","depth") if x in f}
        images = pilot.open_images(stack,names)
        used = {str(pilot.CLOUDS.relative_to(ROOT)),*(str((pilot.RGBD/n).relative_to(ROOT)) for n in names)}
        for i,plan in enumerate(manifest["roster"],1):
            start = time.perf_counter()
            row={"tuber":plan["tuber"],"split":plan["split"],"error":None,"input_index":None,"arms":{}}
            try:
                clouds = matched_clouds(plan,manifest["registration_fingerprint"],cloud,images,k)
                shapes,metadata = {},{}
                for arm in ARMS:
                    shapes[arm],metadata[arm]=sample_data(clouds[arm],plan["tuber"])
                row.update({"input_index":len(stacked.get("center_xyz",[])),"arms":metadata})
                for arm,shape in shapes.items():
                    for key,value in shape.items():
                        stacked.setdefault(f"{arm}_{key}",[]).append(value)
            except (KeyError,ValueError,BadZipFile,QhullError,OSError,np.linalg.LinAlgError) as error:
                row["error"]=f"{type(error).__name__}: {str(error).splitlines()[0]}"
            row["wall_s"]=time.perf_counter()-start
            entries.append(row)
            if i%20==0 or i==len(manifest["roster"]):
                print(f"Replayed matched input {i}/{len(manifest['roster'])}",flush=True)
    path=OUTPUT/"point_inputs.npz"
    with path.with_suffix(".tmp").open("wb") as f:
        np.savez_compressed(f,**{name:np.stack(values) for name,values in stacked.items()})
    path.with_suffix(".tmp").replace(path)
    pilot.write_json(STUDY/"inputs_manifest.json",{
        "frame_manifest_sha256":pilot.digest(STUDY/"frame_manifest.json"),"dataset_sha256":pilot.digest(path),
        "raw_payload_archives":sorted(used),"poses":"cached RGB-D relative-to-center, composed and replayed",
        "elapsed_s":time.perf_counter()-started,"entries":entries,
        "complete_by_split":dict(Counter(row["split"] for row in entries if row["error"] is None)),
    })


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=("freeze","extract"))
    choice=parser.parse_args()
    {"freeze":freeze,"extract":extract}[choice.stage]()
