"""Run from the repository root with the project venv. See protocol.md."""
import argparse
import csv
import hashlib
import json
import os
import platform
from collections import defaultdict
from importlib.metadata import version
from pathlib import Path
import time

import numpy as np
from model import Family, predictions, ray_heights
from potato3d.io import sha256, write_json
from potato3d.study_analysis import cluster_estimate

HERE = Path(__file__).resolve().parent
DEFAULT = Path("outputs/body_detail_v1")
SEAL = HERE/"confirmation_seal.json"
PROTOCOL_HASH = "53af7678aa245029e679ede779668558bff9068059db1078ce7c37e23d609e98"
METHODS = ("mirror", "fixed_height_diagnostic", "clipped_q95", "body", "visible_detail", "reflected_detail")
SPLITS = {"development": (527201100, 6), "confirmation": (527202100, 24), "fixture": (527209999, 1)}


def source_fingerprint():
    paths = [*HERE.glob("*.py"), HERE/"protocol.md", Path("uv.lock"), Path("pyproject.toml"),
             *Path("src/potato3d").rglob("*.py")]
    return {str(p.resolve().relative_to(Path.cwd())): sha256(p) for p in sorted(paths)}


def array_hash(*items):
    h = hashlib.sha256()
    for a in items:
        h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()


def evaluate_family(split, seed, directory, export):
    f = Family.draw(seed)
    grid = (np.arange(111)+.5)*2/111-1
    gx, gy = np.meshgrid(grid, grid)
    disk = gx*gx+gy*gy < 1
    uv = np.column_stack([gx[disk], gy[disk]])
    domain = np.linalg.norm(uv, axis=1) < .99
    xy = f.xy(uv)
    observed_xy = f.xy(f.uv)
    base_top_obs, _ = f.surfaces(f.uv)
    base_top, base_low = f.surfaces(uv)
    observed_z = base_top_obs+f.noise
    max_clean = float(observed_z.max())
    cell_ml_per_mm = (2/111)**2*np.prod(f.axes[:2])/1000
    rows = []
    original_lower = {}
    observed_hashes = set()
    family_id = f"{split}-{seed}"
    for site, location in [("clean", 0), ("apex", .04), ("flank", .57), ("edge", .79)]:
        center = location*f.direction
        for sign in ([0] if site == "clean" else [-1, 1]):
            bump = f.feature(uv, center, sign)
            delta = f.feature(f.uv, center, sign)
            obs = np.column_stack([observed_xy, observed_z+delta])
            obs_digest = array_hash(obs)
            if obs_digest in observed_hashes:
                raise ValueError("Distinct interventions must produce distinct scans")
            observed_hashes.add(obs_digest)
            core = domain & (abs(bump) >= .25*f.amplitude)
            remote = domain & (np.linalg.norm(uv-center, axis=1) >= 2*f.radius)
            if sign and (core.sum() < 5 or not np.any(remote)):
                raise ValueError("Insufficient evaluation support")
            cases = ["smooth"] if not sign else ["artifact", "unilateral", "bilateral"]
            for method, mesh, pars in predictions(obs, max_clean):
                upper, lower = ray_heights(mesh, xy)
                hits = np.isfinite(lower)
                geom_hash = array_hash(mesh.vertices, mesh.faces)
                if export:
                    folder = directory/"examples"/family_id
                    folder.mkdir(parents=True, exist_ok=True)
                    mesh.export(folder/f"{site}_{sign}_{method}.ply")
                if not sign:
                    original_lower[method] = lower
                old = original_lower[method]
                before = np.isfinite(old)
                flip = hits ^ before
                motion = np.full(len(uv), 0.)
                motion[flip] = 15
                shared = hits & before
                motion[shared] = abs(lower[shared]-old[shared])
                for case in cases:
                    target_top = base_top+bump if case in ("unilateral", "bilateral") else base_top
                    target_low = np.maximum(0, base_low-bump) if case == "bilateral" else base_low
                    if np.any(target_top < target_low-1e-8):
                        raise ValueError("Invalid reference geometry")
                    err_top = np.where(hits, abs(upper-target_top), 15)
                    err_low = np.where(hits, abs(lower-target_low), 15)
                    true_volume = float((target_top-target_low).sum()*cell_ml_per_mm)
                    rows.append(dict(family=family_id, site=site, sign=sign, case=case,
                        method=method, input_sha256=obs_digest, mesh_sha256=geom_hash,
                        reference_sha256=array_hash(target_top, target_low),
                        parameters=json.dumps(pars, sort_keys=True),
                        amplitude_mm=f.amplitude, radius_unit_disk=f.radius, core_rays=int(core.sum()),
                        coverage=hits[domain].mean(), hidden_mm=err_low[domain].mean(),
                        top_core_mm=err_top[core].mean() if sign else None,
                        lower_core_mm=err_low[core].mean() if sign else None,
                        reference_core_motion_mm=abs(target_low-base_low)[core].mean() if sign else None,
                        remote_mm=motion[remote].mean(), remote_flip=flip[remote].mean(),
                        remote_shared_motion_mm=motion[remote & shared].mean(),
                        fitted_height_shift_mm=pars["height_mm"]-max_clean if "height_mm" in pars else None,
                        volume_ml=mesh.volume, reference_volume_ml=true_volume,
                        volume_absolute_error_ml=abs(mesh.volume-true_volume)))
    if len(rows) != 19*len(METHODS) or len(observed_hashes) != 7:
        raise ValueError("Incomplete family")
    return rows


def summarize(rows):
    lookup = {(r["family"],r["site"],r["sign"],r["case"],r["method"]): r for r in rows}
    def calc(metric, method, case=None, compare=None, sites=None, sign=None):
        groups = defaultdict(list)
        for key, r in lookup.items():
            family, site, s, kind, name = key
            if name != method or (case and case != kind) or (sites and site not in sites) or (sign and s != sign):
                continue
            value = r[metric]
            if compare:
                value -= lookup[(family,site,s,kind,compare)][metric]
            groups[family].append(value)
        return cluster_estimate(groups, 10000, 527203100)

    checks = {}
    def check(label, est, margin, lower=False, strict=False):
        ci = est["ci95"]
        ok = None
        if ci is not None:
            ok = ci[0] >= margin if lower else (ci[1] < margin if strict else ci[1] <= margin)
        checks[label] = dict(**est, margin=margin, passed=ok)

    candidate = "visible_detail"
    check("artifact_remote_minus_mirror",calc("remote_mm",candidate,"artifact","mirror"),-.5,strict=True)
    check("artifact_hidden_minus_q95",calc("hidden_mm",candidate,"artifact","clipped_q95"),0,strict=True)
    check("unilateral_upper_core",calc("top_core_mm",candidate,"unilateral"),.75)
    check("bilateral_lower_core_minus_reflected",calc("lower_core_mm",candidate,"bilateral","reflected_detail",
          sites=("flank","edge"),sign=1),.75)
    check("coverage",calc("coverage",candidate),.95,lower=True)
    table = {}
    for m in METHODS:
        table[m] = {label: calc(metric,m,case,sites=sites,sign=s)["mean"]
            for label,metric,case,sites,s in [
            ("artifact_remote","remote_mm","artifact",None,None),("artifact_hidden","hidden_mm","artifact",None,None),
            ("unilateral_core","top_core_mm","unilateral",None,None),
            ("bilateral_hidden_core","lower_core_mm","bilateral",("flank","edge"),1),
            ("positive_apex_remote","remote_mm","artifact",("apex",),1),
            ("positive_apex_shared_motion","remote_shared_motion_mm","artifact",("apex",),1),
            ("positive_apex_flip","remote_flip","artifact",("apex",),1),("coverage","coverage",None,None,None)]}
    strata = defaultdict(list)
    for r in rows:
        strata[(r["site"], r["sign"], r["case"], r["method"])].append(r)
    summaries = []
    for (site, sign, case, method), grouped in sorted(strata.items()):
        summary = dict(site=site, sign=sign, case=case, method=method, families=len(grouped))
        for field in ("remote_mm", "remote_flip", "remote_shared_motion_mm", "hidden_mm",
                      "top_core_mm", "lower_core_mm", "reference_core_motion_mm", "coverage",
                      "volume_absolute_error_ml"):
            values = [r[field] for r in grouped if r[field] is not None]
            summary[field] = float(np.mean(values)) if values else None
        summaries.append(summary)
    return {"checks": checks, "means": table, "strata": summaries,
            "positive_apex_fixed_minus_mirror":calc("remote_mm","fixed_height_diagnostic","artifact","mirror",
                  sites=("apex",),sign=1)}


def write_rows(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage",choices=[*SPLITS,"freeze"])
    parser.add_argument("--out",type=Path,default=DEFAULT)
    args = parser.parse_args()
    if sha256(HERE/"protocol.md") != PROTOCOL_HASH:
        raise ValueError("Protocol changed")
    hashes = source_fingerprint()
    dev = args.out/"development"
    if args.stage in ("freeze","confirmation"):
        meta = json.loads((dev/"run.json").read_text())
        if meta["source"] != hashes or sha256(dev/"rows.csv") != meta["rows_sha256"] or sha256(dev/"summary.json") != meta["summary_sha256"]:
            raise ValueError("Development state differs from its completed run")
        evidence = {"source": hashes,
                    "development_rows_sha256":meta["rows_sha256"],"development_summary_sha256":meta["summary_sha256"]}
        if args.stage == "freeze":
            with SEAL.open("x") as handle:
                json.dump(evidence,handle,sort_keys=True,indent=2)
            return
        if json.loads(SEAL.read_text()) != evidence:
            raise ValueError("Confirmation seal mismatch")
    directory = args.out/args.stage
    directory.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    seed, count = SPLITS[args.stage]
    rows = []
    for i in range(count):
        rows.extend(evaluate_family(args.stage,seed+i,directory,export=i==0))
        if (i+1)%6==0: print(f"{args.stage} {i+1}/{count}", flush=True)
    write_rows(directory/"rows.csv", rows)
    write_json(directory/"summary.json",summarize(rows))
    write_json(directory/"run.json",{"source":hashes,"split":args.stage,"seed_range":[seed,seed+count-1],
          "families":count, "scored_cases":19*count, "scored_predictions":len(rows),
          "unique_scans":7*count,"method_outputs_on_distinct_scans":7*len(METHODS)*count,
          "platform":platform.platform(),"python":platform.python_version(),
          "versions":{k:version(k) for k in ["numpy","scipy","matplotlib","trimesh"]},
          "threads":{k:os.environ.get(k) for k in ["OPENBLAS_NUM_THREADS","VECLIB_MAXIMUM_THREADS","OMP_NUM_THREADS"]},
          "elapsed_seconds":time.monotonic()-start,"rows_sha256":sha256(directory/"rows.csv"),
          "summary_sha256":sha256(directory/"summary.json")})

if __name__=="__main__":
    main()
