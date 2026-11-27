"""Score the registered clouds once against the fixed independent SfM meshes."""

from pathlib import Path
from zipfile import ZipFile, BadZipFile
import argparse
import csv
import io
import sys
import time

import numpy as np
from scipy.spatial import cKDTree

import prepare as prep

# Reuse the workspace's pure-Python Trimesh alongside its archived Open3D environment.
sys.path.extend([str(prep.ROOT/"outputs/corepp_cross_model/triposr/deps"), str(prep.ROOT/"src")])
import open3d as o3d
import trimesh
from potato3d.geometry import sample_surface

import alignment as align

METHODS = ("center", "icp", "raft")
THRESHOLD = 2.
SAMPLES = 50_000
REPEATS = 10


def mesh_scene(mesh):
    scene = o3d.t.geometry.RaycastingScene(nthreads=1)
    verts = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.uint32)
    scene.add_triangles(o3d.core.Tensor(verts), o3d.core.Tensor(faces))
    return scene


def mesh_distance(points, scene):
    query = o3d.core.Tensor(np.ascontiguousarray(points, dtype=np.float32))
    return scene.compute_distance(query, nthreads=1).numpy()


def metric_check():
    mesh = trimesh.Trimesh(vertices=[[0., 0., 0.], [10., 0., 0.], [0., 10., 0.]],
                           faces=[[0, 1, 2]], process=False)
    target = np.array([[1., 1., 1.], [1., 1., 2.], [1., 1., 3.]])
    distances = mesh_distance(target, mesh_scene(mesh))
    covered = cKDTree(np.array([[0., 0., 0.]])).query(np.array([[0., 0., 2.], [0., 0., 3.]]))[0] <= THRESHOLD
    if not np.array_equal(distances, [1., 2., 3.]) or not np.array_equal(covered, [True, False]):
        raise ValueError("Metric direction, distance scale or cutoff smoke check failed")
    return {"known_triangle_distances_mm": distances.tolist(), "known_coverage_at_2_3_mm": covered.tolist()}


def load_reference(archive, member):
    mesh = trimesh.load(io.BytesIO(prep.member_bytes(archive, member)),
                        file_type="obj", force="mesh", process=False, skip_materials=True)
    vertices = np.asarray(mesh.vertices, dtype=float) * 1000.
    if (len(vertices) < 4 or len(mesh.faces) < 4 or not np.isfinite(vertices).all()
            or not 10. <= np.ptp(vertices, axis=0).max() <= 300.):
        raise ValueError("Implausible released SfM model geometry or meter scale")
    return trimesh.Trimesh(vertices=vertices, faces=mesh.faces, process=False)


def score_cloud(cloud, samples, scene):
    nearest = cKDTree(cloud).query(samples)[0]
    distance = mesh_distance(cloud, scene)
    if not np.isfinite(distance).all():
        raise ValueError("Nonfinite point-to-SfM distances")
    covered = nearest <= THRESHOLD
    return {"coverage_fraction": float(covered.mean()), "far_fraction": float(np.mean(distance > THRESHOLD)),
            "points": len(cloud)}, covered


def equal_counts(clouds, samples):
    n = min(len(clouds[k]) for k in METHODS)
    rates = {}
    for key, points in clouds.items():
        if len(points) == n:
            rates[key] = float(np.mean(cKDTree(points).query(samples)[0] <= THRESHOLD))
        else:
            rng = np.random.default_rng(prep.SEED)
            outcomes = []
            for _ in range(REPEATS):
                indices = rng.choice(len(points), size=n, replace=False)
                outcomes.append(np.mean(cKDTree(points[indices]).query(samples)[0] <= THRESHOLD))
            rates[key] = float(np.mean(outcomes))
    return n, rates


def calculate_row(plan, registration, ref_archive):
    tuber = plan["tuber"]
    path = prep.ASSETS/"clouds"/f"{tuber}.npz"
    if prep.digest(path) != registration["cloud_sha256"]:
        raise ValueError(f"Registered output cloud changed: {tuber}")
    with np.load(path, allow_pickle=False) as file:
        clouds = {key: file[key] for key in METHODS if key in file}
    start = time.perf_counter()
    row = {
        "tuber": tuber, "lower": plan["selected_suffixes"][0], "center": plan["selected_suffixes"][1],
        "upper": plan["selected_suffixes"][2], "links": len(plan["frames"])-1,
        "reference_failure": "", "sfm_area_mm2": None, "equal_points": None,
    }
    for method in METHODS:
        times = registration["methods"][method]
        row[f"{method}_failure"] = times["failure"] or ""
        row[f"{method}_geometry_wall_s"] = times["geometry_wall_s"]
        row[f"{method}_flow_wall_s"] = times.get("flow_wall_s", 0.)
        row[f"{method}_measurement_failure"] = ""
        for field in ("coverage_fraction", "far_fraction", "points", "equal_coverage_fraction",
                      "new_fraction", "lost_fraction", "new_area_mm2", "lost_area_mm2"):
            row[f"{method}_{field}"] = None
    result_viz = None
    try:
        reference = load_reference(ref_archive, plan["reference"])
        samples, _ = sample_surface(reference, SAMPLES, prep.SEED)
        scene = mesh_scene(reference)
        row["sfm_area_mm2"] = float(reference.area)
        covered = {}
        for method, cloud in clouds.items():
            try:
                values, coverage = score_cloud(cloud, samples, scene)
            except (ValueError, RuntimeError) as error:
                row[f"{method}_measurement_failure"] = str(error)
                continue
            covered[method] = coverage
            for key, value in values.items():
                row[f"{method}_{key}"] = value
        if "center" in covered:
            for method, coverage in covered.items():
                new = float(np.mean(coverage & ~covered["center"]))
                lost = float(np.mean(covered["center"] & ~coverage))
                for kind, value in (("new", new), ("lost", lost)):
                    row[f"{method}_{kind}_fraction"] = value
                    row[f"{method}_{kind}_area_mm2"] = value * reference.area
        if set(covered) == set(METHODS):
            row["equal_points"], matched = equal_counts(clouds, samples)
            for method, rate in matched.items():
                row[f"{method}_equal_coverage_fraction"] = rate
        result_viz = samples, covered
    except (OSError, ValueError, RuntimeError, KeyError, BadZipFile) as error:
        row["reference_failure"] = str(error)

    for baseline in ("center", "icp"):
        for metric in ("coverage_fraction", "far_fraction", "equal_coverage_fraction"):
            a, b = row[f"raft_{metric}"], row[f"{baseline}_{metric}"]
            row[f"raft_minus_{baseline}_{metric}"] = a-b if a is not None and b is not None else None
    row["measurement_wall_s"] = time.perf_counter()-start
    return row, result_viz


def stats(values):
    return {"n": len(values), "mean": float(np.mean(values)) if len(values) else None,
            "median": float(np.median(values)) if len(values) else None,
            "positive": int(sum(v > 1e-12 for v in values)), "negative": int(sum(v < -1e-12 for v in values)),
            "ties": int(sum(abs(v) <= 1e-12 for v in values))}


def sum_if_present(rows, key):
    return stats([r[key] for r in rows if r[key] is not None])


def summarize(rows):
    fields = ("coverage_fraction", "far_fraction", "equal_coverage_fraction",
              "new_fraction", "lost_fraction", "new_area_mm2", "lost_area_mm2", "points")
    pairs = ("coverage_fraction", "far_fraction", "equal_coverage_fraction")
    full_pairs = {}
    for target in ("center", "icp"):
        full_pairs[f"raft_vs_{target}"] = {
            name: sum_if_present(rows, f"raft_minus_{target}_{name}") for name in pairs
        }
    return {
        "n": len(rows), "reference_samples_per_tuber": SAMPLES, "distance_threshold_mm": THRESHOLD,
        "equal_density_repeats": REPEATS, "output_voxel_mm": 1.,
        "methods": {m: {key: sum_if_present(rows, f"{m}_{key}") for key in fields} for m in METHODS},
        "paired_raft_comparison": full_pairs,
        "runtime_s": {f"{m}_{kind}": sum(r[f"{m}_{kind}_wall_s"] for r in rows)
                      for m in METHODS for kind in ("geometry", "flow")},
        "reference_coverage_failures": [
            {k: r[k] for k in ("tuber","reference_failure",*(f"{m}_measurement_failure" for m in METHODS))}
            for r in rows if r["reference_failure"] or any(r[f"{m}_measurement_failure"] for m in METHODS)
        ],
        "measurement_wall_s": sum(r["measurement_wall_s"] for r in rows),
    }


def select_examples(rows):
    pairs = [r for r in rows if r["raft_minus_center_coverage_fraction"] is not None
             and r["raft_far_fraction"] is not None]
    if not pairs:
        return {}
    worst = min(pairs, key=lambda r: (-r["raft_far_fraction"], r["tuber"]))
    candidates = [r for r in pairs if r["tuber"] != worst["tuber"]]
    examples = {"worst_alignment": worst["tuber"]}
    if candidates:
        median = float(np.median([r["raft_minus_center_coverage_fraction"] for r in candidates]))
        typ = min(candidates, key=lambda r: (abs(r["raft_minus_center_coverage_fraction"]-median), r["tuber"]))
        examples["typical_coverage"] = typ["tuber"]
    return examples


def render(path, name, row, plan, figure_data):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.lines import Line2D

    points, masks = figure_data
    pose = align.in_mm(plan["center_to_sfm_m"])
    coords = align.apply(points, np.linalg.inv(pose))
    coords -= (coords.max(axis=0) + coords.min(axis=0)) / 2.
    span = np.ptp(coords, axis=0).max()/2. + 2.
    idx = np.random.default_rng(prep.SEED).choice(len(coords), size=9_000, replace=False)
    base = masks["center"][idx]
    c = coords[idx]
    fig = plt.figure(figsize=(11.2, 7.7), layout="constrained")
    for i, elev in enumerate((-57, 57)):
        for j, method in enumerate(METHODS):
            ax = fig.add_subplot(2, 3, i * 3 + j + 1, projection="3d")
            if method in masks:
                coverage = masks[method][idx]
                colors = np.full(len(idx), "#d4d8dd", dtype="U7")
                colors[coverage & base] = "#374d65"
                colors[coverage & ~base] = "#148166"
                colors[~coverage & base] = "#d55739"
                ax.scatter(*c.T, c=colors, s=3.1, depthshade=False, linewidths=0, rasterized=True)
                ax.set_title(f"{method.upper()}  ·  {row[f'{method}_coverage_fraction']:.1%} covered", fontsize=12)
            else:
                ax.text2D(.18, .5, "Registration unavailable", transform=ax.transAxes)
                ax.set_title(method.upper(), fontsize=12)
            ax.set(xlim=(-span,span), ylim=(-span,span), zlim=(-span,span), box_aspect=(1,1,1))
            ax.view_init(elev=elev, azim=-67, roll=0)
            ax.set_proj_type("ortho")
            ax.set_axis_off()
    roles = ("Center-facing view", "Opposite view")
    fig.text(.012,.71,roles[0],rotation=90,va="center",fontsize=10)
    fig.text(.012,.28,roles[1],rotation=90,va="center",fontsize=10)
    fig.suptitle(f"{row['tuber']}   ·   {name}   ·   SfM surface coverage within 2 mm", fontsize=15)
    keys = (("Covered by center and shown method","#374d65"),("Newly covered","#148166"),
            ("Coverage lost","#d55739"),("Still uncovered","#d4d8dd"))
    fig.legend(handles=[Line2D([], [], linestyle="", marker="o", markersize=6, color=color, label=label)
                        for label,color in keys], loc="outside lower center", ncols=4, frameon=False)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def run(output):
    if (output/"results.json").exists():
        raise FileExistsError("This frozen comparison was already scored")
    manifest = prep.load_manifest()
    reg_file = prep.STUDY/"registration.json"
    registration = prep.read_json(reg_file)
    if (registration["recipe"]["manifest_sha256"] != prep.digest(prep.STUDY/"frame_manifest.json")
            or registration["recipe"] != prep.read_json(prep.STUDY/"alignment_freeze.json")):
        raise ValueError("Registration does not match the frozen cohort")
    plans = manifest["roster"]
    if [p["tuber"] for p in plans] != [r["tuber"] for r in registration["potatoes"]]:
        raise ValueError("Registration roster differs from the freeze")
    recipe = {
        "protocol_sha256": prep.digest(prep.STUDY/"protocol.md"), "registration_sha256": prep.digest(reg_file),
        "score_code_sha256": prep.digest(Path(__file__)), "open3d": o3d.__version__, "trimesh": trimesh.__version__,
        "known_geometry": registration["recipe"]["geometry_check"], "known_distances": metric_check(),
    }
    prep.freeze_check(output/"score_freeze.json", recipe)
    rows, figures = [], {}
    with ZipFile(prep.MESHES) as reference:
        for plan, fixed in zip(plans, registration["potatoes"], strict=True):
            row, figure = calculate_row(plan, fixed, reference)
            rows.append(row)
            figures[plan["tuber"]] = figure
            print(f"Scored {len(rows)}/{len(plans)} {plan['tuber']}", flush=True)
    summary = summarize(rows)
    names = select_examples(rows)
    summary["figures"] = names
    summary["shared_support_loading_s"] = sum(r["load_and_support_wall_s"] for r in registration["potatoes"])
    summary["raft_model_setup_s"] = prep.read_json(prep.ASSETS/"flow_run.json")["cpu_setup_s"]
    summary["score_freeze_sha256"] = prep.digest(output/"score_freeze.json")
    for filename, tuber in names.items():
        row = next(r for r in rows if r["tuber"] == tuber)
        plan = next(r for r in plans if r["tuber"] == tuber)
        label = "highest RAFT outlier fraction" if filename == "worst_alignment" else "near-median RAFT coverage change"
        render(output/f"{filename}.png", label, row, plan, figures[tuber])
    with (output/"per_potato.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    prep.write_json(output/"results.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=prep.STUDY)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    run(args.out)
