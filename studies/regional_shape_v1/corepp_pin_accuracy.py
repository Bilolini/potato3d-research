"""Score fixed-pose accuracy for the archived CoRe++ development edits."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import json
import multiprocessing
from pathlib import Path
from statistics import mean, median
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import matplotlib.pyplot as plt
import numpy as np
import open3d as o3d
from scipy.spatial import ConvexHull
import torch

from . import corepp_pin_grid_boundary as grid
from . import corepp_pin_multituber as multi
from .corepp_pin_multituber import audit, pilot

GRID_DIR = audit.HERE / "corepp_pin_grid_boundary"
PROTOCOL = audit.HERE / "corepp_pin_accuracy_protocol.md"
DEVELOPMENT = audit.HERE / "results.json"
FOCUS = "5R1-4"
TOL_MM = 1e-4
MESH_DECIMALS_M = 13
SOURCE_FILES = ("data_preparation/pcd_from_sfm.py", "dataloaders/cameralaser_w_masks.py", "test.py",
                "metrics_3d/chamfer_distance.py", "metrics_3d/metric.py")


def archive_context(args, runtime):
    archived_frames, hashes = grid.load_archive(args, runtime)
    opts = argparse.Namespace(**(vars(args) | {"out_dir": GRID_DIR}))
    points, inside, manifest = grid.check_grid(opts, runtime, hashes)
    paths = {name: GRID_DIR / name for name in (grid.FREEZE, grid.REPLAY, grid.RESULTS, grid.GRID_FILE)}
    provenance = {name: audit.sha256(path) for name, path in paths.items()}
    saved, replay = (audit.read_json(paths[name]) for name in (grid.RESULTS, grid.REPLAY))
    if (saved["frozen_grid_sha256"] != provenance[grid.FREEZE] or
            replay["frozen_grid_sha256"] != provenance[grid.FREEZE] or
            saved["interior_replay_sha256"] != provenance[grid.REPLAY] or replay["verified_predictions"] != 800):
        raise ValueError("Expanded-grid archives failed the provenance check")
    expected = [(r["tuber"], r["frame"]) for r, _, _ in archived_frames]
    for record in (saved, replay):
        if [(r["tuber"], r["frame"]) for r in record["frames"]] != expected:
            raise ValueError("Expanded archives do not cover the frozen development roster")
    return points, inside, manifest, saved["frames"], replay["frames"], provenance


def get_member(source, obj, recorded, members, destination):
    row = members[obj, Path(recorded["path"]).name]
    with ZipFile(source / row["archive"]) as z:
        data = z.read(row["member_path"])
    if len(data) != int(row["uncompressed_bytes"]) or hashlib.sha256(data).hexdigest() != recorded["sha256"]:
        raise ValueError(f"Development asset failed archive check: {recorded['path']}")
    destination.write_bytes(data)
    return destination


def development_metadata():
    with (audit.DEV / "fresh_download_members.tsv").open(newline="") as f:
        members = {(r["tuber_id"], r["member_basename"]): r for r in csv.DictReader(f, delimiter="\t")}
    dev = {p["object_id"]: p for p in audit.read_json(DEVELOPMENT)["intake"]["pairs"]}
    geometry = {p["object_id"]: p for p in audit.read_json(audit.DEV / "fresh_selection.json")["pairs"]}
    return dev, geometry, members


def ref_mesh(args, obj, tmp, dev, members):
    recorded = dev[obj]
    if recorded["unit"] != "m":
        raise ValueError(f"Unexpected reference units for {obj}")
    obj_path = get_member(args.source, obj, recorded["files"]["reference"], members, tmp / f"{obj}.obj")
    mesh = o3d.io.read_triangle_mesh(str(obj_path), enable_post_processing=True)
    vertices = np.asarray(mesh.vertices).copy()
    if not len(mesh.triangles) or not np.isfinite(vertices).all() or not .02 <= np.ptp(vertices, axis=0).max() <= .25:
        raise ValueError(f"Invalid or implausibly scaled reference mesh for {obj}")
    pilot.set_rng(audit.CPU_SEED)
    points = mesh.sample_points_uniformly(number_of_points=20000)
    center = points.get_center()
    if len(points.points) != 20000 or not np.isfinite(center).all():
        raise ValueError(f"Invalid target samples for {obj}")
    mesh.translate(-center)
    points.translate(-center)
    np.testing.assert_allclose(np.asarray(mesh.vertices), vertices - center, rtol=0, atol=1e-15)
    return mesh, points, center, obj_path, vertices


class MeshReplay:
    def __init__(self, args, runtime, context):
        self.args = args
        self.runtime = runtime
        points, self.inside, manifest, _, _, _ = context
        self.shell = torch.from_numpy(points[~self.inside])
        self.seed_map = manifest["shell_seed_by_interior_seed"]
        self.geometry = argparse.Namespace(grid=torch.from_numpy(points), mesh_builder=runtime.mesh_builder)

    def load_cache(self, obj, verified):
        path = self.args.cache_dir / f"{obj}.npz"
        if audit.sha256(path) != verified["cache_sha256"]:
            raise ValueError(f"Changed cache for {obj}")
        with np.load(path, allow_pickle=False) as cache:
            return cache["latent"], cache["sdf"]

    @torch.no_grad()
    def predict(self, seed, shell_seed, latent, sdf, hashes, archived):
        if shell_seed != self.seed_map[str(seed)]:
            raise ValueError(f"Unexpected archived shell seed at {seed}")
        if audit.array_sha256(latent) != hashes["latent"] or audit.array_sha256(sdf) != hashes["sdf"]:
            raise ValueError(f"Interior replay mismatch at seed {seed}")
        if audit.array_sha256(sdf.ravel() < 0) != hashes["inside_labels_sha256"]:
            raise ValueError(f"Interior label mismatch at seed {seed}")
        decoder = self.runtime.decoder
        decoder.load_state_dict(self.runtime.states[1], strict=True)
        decoder.train(self.runtime.modes[1])
        outer = grid.decode(decoder, torch.from_numpy(latent), self.shell, shell_seed).numpy()
        assembly = np.empty((len(self.inside), 1), dtype=np.float32)
        assembly[self.inside], assembly[~self.inside] = sdf, outer
        outer_hash, full_hash = audit.array_sha256(outer), audit.array_sha256(assembly)
        if outer_hash != archived["shell_sdf_sha256"] or full_hash != archived["expanded_sdf_sha256"]:
            raise ValueError(f"Outer or assembled SDF replay mismatch at seed {seed}")
        predicted = grid.mesh_prediction(self.geometry, assembly, seed)
        if predicted["mesh_failure"] or abs(predicted["volume_ml"] - archived["volume_ml"]) > 1e-8:
            raise ValueError(f"Mesh or volume replay mismatch at seed {seed}: {predicted['mesh_failure']}")
        predicted["replay"] = {"shell_sdf_sha256": outer_hash, "expanded_sdf_sha256": full_hash,
                               "volume_replay_abs_difference_ml": abs(predicted["volume_ml"] - archived["volume_ml"])}
        return predicted


def transform(values, matrix):
    return values @ matrix[:3, :3].T + matrix[:3, 3]


def scenes(points, mesh):
    ray = o3d.t.geometry.RaycastingScene(nthreads=1)
    ray.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(mesh))
    return ray.compute_distance(o3d.core.Tensor(points, dtype=o3d.core.Dtype.Float32), nthreads=1).numpy() * 1000


def surface_error(reference, prediction):
    return (float(audit.surface_distances_mm(reference, prediction).mean(dtype=np.float64)) +
            float(audit.surface_distances_mm(prediction, reference).mean(dtype=np.float64))) / 2


def ordered_surface(mesh):
    """Stabilize the sample order across equivalent Open3D triangle enumerations."""
    vertices = np.round(np.asarray(mesh.vertices), MESH_DECIMALS_M)
    triangles = np.asarray(mesh.triangles)
    order = np.lexsort(vertices.T[::-1])
    inverse = np.argsort(order)
    triangles = np.sort(inverse[triangles], axis=1)
    face_order = np.lexsort(triangles.T[::-1])
    return o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(vertices[order]),
                                    o3d.utility.Vector3iVector(triangles[face_order]))


def metric_checks():
    v = np.array([[0., 0., 0.], [.05, 0., 0.], [.05, .04, 0.], [0., .04, 0.]])
    faces = np.array([[0, 1, 2], [0, 2, 3]])
    a = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(v), o3d.utility.Vector3iVector(faces))
    shifted = o3d.geometry.TriangleMesh(a).translate([0., 0., .004])
    permutation = np.array([2, 0, 3, 1])
    permuted = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(v[permutation]),
                                      o3d.utility.Vector3iVector(np.argsort(permutation)[faces[::-1, ::-1]]))
    a, shifted, permuted = (ordered_surface(mesh) for mesh in (a, shifted, permuted))
    same, known = surface_error(a, a), surface_error(a, shifted)
    invariant = surface_error(permuted, shifted) == known and pilot.same_mesh(a, permuted)
    if same > TOL_MM or abs(known - 4) > TOL_MM or not invariant:
        raise ValueError("Symmetric surface metric failed synthetic checks")
    return {"identity_mm": same, "known_shift_mm": 4., "observed_shift_mm": known,
            "mesh_order_invariant": invariant, "tolerance_mm": TOL_MM}


def overlay(path, points, scan, mesh, pins):
    target = np.asarray(points.points) * 1000
    verts = np.asarray(mesh.vertices) * 1000
    fig, axes = plt.subplots(1, 3, figsize=(11.4, 4.05), layout="constrained")
    for ax, (i, j) in zip(axes, ((0, 1), (0, 2), (1, 2)), strict=True):
        ax.scatter(target[::4, i], target[::4, j], s=1.2, color="#62737f", alpha=.28, label="Centered SfM target")
        ax.scatter(scan[::4, i]*1000, scan[::4, j]*1000, s=1.8, color="#008477", alpha=.35, label="Registered RGB-D scan")
        hull = ConvexHull(verts[:, [i, j]]).vertices
        outline = verts[np.r_[hull, hull[0]]]
        ax.plot(outline[:, i], outline[:, j], color="#be3b2d", lw=1.35, label="Unchanged mesh outline")
        for k, (mark, color, name) in enumerate((("+", "#d48300", "SfM pin center"), ("x", "#542f82", "Registered RGB-D pin center"))):
            ax.scatter(pins[k][i]*1000, pins[k][j]*1000, marker=mark, color=color, s=42, label=name)
        ax.scatter([0], [0], s=12, color="black", zorder=6)
        ax.set(xlabel=f"SfM {'XYZ'[i]} (mm)", ylabel=f"SfM {'XYZ'[j]} (mm)", aspect="equal")
    axes[0].legend(loc="upper left", fontsize=7, frameon=True)
    fig.suptitle("5R1-4 / 362 · unchanged prediction at seed 133")
    fig.savefig(path, dpi=155)
    plt.close(fig)


def audit_mapping(args, runtime, context):
    from data_preparation.pcd_from_sfm import main as released_prepare

    _, _, _, archived, replays, provenance = context
    row, = [r for r in archived if r["tuber"] == FOCUS]
    verified, = [r for r in replays if r["tuber"] == FOCUS]
    dev, selected, members = development_metadata()
    builder = MeshReplay(args, runtime, context)
    latents, sdfs = builder.load_cache(FOCUS, verified)
    baseline = builder.predict(133, row["pairs"][0]["shell_seed"], latents[0, 0], sdfs[0, 0],
                               verified["seeds"][0]["conditions"]["original"]["hashes"] |
                               {"inside_labels_sha256": verified["seeds"][0]["conditions"]["original"]["inside_labels_sha256"]},
                               row["pairs"][0]["expanded_grid"]["original"])
    with TemporaryDirectory(prefix="corepp-accuracy-frame-") as folder:
        temp = Path(folder)
        raw = temp / "raw"
        raw.mkdir()
        target, samples, center, _, raw_vertices = ref_mesh(args, FOCUS, raw, dev, members)
        pilot.set_rng(audit.CPU_SEED)
        released_prepare(str(raw), str(temp / "prepared"))
        ply = temp / "prepared" / FOCUS / "laser/fruit.ply"
        direct = np.array(o3d.io.read_point_cloud(str(ply)).points, dtype=np.float32)
        expected_target = np.asarray(samples.points).astype(np.float32)
        np.testing.assert_array_equal(direct, expected_target)

        identity = dev[FOCUS]
        with ZipFile(args.source / audit.MATRIX_ARCHIVE) as z:
            reg_bytes = z.read(selected[FOCUS]["registration_member"])
        if hashlib.sha256(reg_bytes).hexdigest() != identity["files"]["registration"]["sha256"]:
            raise ValueError("Coordinate-audit registration hash does not match")
        reg = json.loads(reg_bytes)
        if (reg["sfm_mesh_file"] != identity["files"]["reference"]["path"] or
                reg["rgbd_pcd_file"] != identity["files"]["partial"]["path"]):
            raise ValueError("RGB-D and SfM frame IDs do not match")
        path = get_member(args.source, FOCUS, identity["files"]["partial"], members, temp / "scan.ply")
        camera = np.asarray(o3d.io.read_point_cloud(str(path)).points)
        T = np.asarray(reg["T"])
        np.testing.assert_allclose(T[:3, :3].T @ T[:3, :3], np.eye(3), atol=1e-8, rtol=0)
        np.testing.assert_allclose(np.linalg.det(T[:3, :3]), 1., atol=1e-8, rtol=0)
        np.testing.assert_array_equal(T[3], [0., 0., 0., 1.])
        scan = transform(camera, T) - center
        roundtrip = transform(scan + center, np.linalg.inv(T))
        np.testing.assert_allclose(roundtrip, camera, atol=1e-12, rtol=0)
        pin = reg["meta"]["pin_segment"]
        pins = np.array([np.asarray(pin["sfm"]["center"]), transform(np.asarray(pin["rgbd"]["center"]), T)]) - center
        pin_error = float(np.linalg.norm(pins[0] - pins[1])*1000)
        dist = scenes(scan, target)
        scan_median, scan_p95 = np.quantile(dist, [.5, .95]).tolist()
        if pin_error > 10 or scan_median > 2 or scan_p95 > 5:
            raise ValueError(f"Release registration failed gate: pin {pin_error:.3f}, median {scan_median:.3f}, p95 {scan_p95:.3f} mm")
        report_landmarks = {}
        for i, axis in enumerate("xyz"):
            where = int(np.argmax(raw_vertices[:, i]))
            report_landmarks[axis+"maximum_vertex"] = {"vertex_index": where, "raw_xyz_m": raw_vertices[where].tolist(),
                                                      "centered_xyz_m": np.asarray(target.vertices)[where].tolist()}
        vertices = np.asarray(baseline["mesh"].vertices)
        overlay(args.out_dir / "coordinate_overlay.png", samples, scan, baseline["mesh"], pins)
        pilot.put_json(args.out_dir / "coordinate_audit.json", {
            "status": "numeric_mapping_passed", "tuber": FOCUS, "frame": row["frame"], "seed": 133,
            "source_sha256": {name: audit.sha256(args.upstream/name) for name in SOURCE_FILES},
            "archived_grid_provenance": provenance, "geometry_input_hashes": identity["files"],
            "sample_center_sfm_m": center.tolist(), "loader_target_sha256": audit.array_sha256(direct),
            "loader_float32_target_bitwise_equal": True, "loader_target_mean_mm": (direct.mean(axis=0)*1000).tolist(),
            "reference_extent_xyz_mm": (np.ptp(raw_vertices, axis=0)*1000).tolist(),
            "decoded_extent_xyz_mm": (np.ptp(vertices, axis=0)*1000).tolist(),
            "landmarks": report_landmarks, "rgbd_to_sfm": T.tolist(),
            "registered_and_sfm_pin_centres_centered_mm": (pins*1000).tolist(),
            "pin_center_distance_mm": pin_error, "registered_scan_to_sfm_mm": {"median": scan_median, "p95": scan_p95},
            "camera_roundtrip_max_mm": float(np.max(np.abs(roundtrip-camera))*1000),
            "synthetic_surface_checks": metric_checks(),
        })


def save_refs(args, context):
    _, _, _, rows, _, provenance = context
    if args.review is None:
        raise ValueError("The coordinate overlay review is required")
    checked = audit.read_json(args.out_dir / "coordinate_audit.json")
    visual = audit.read_json(args.review)
    if (checked["status"] != "numeric_mapping_passed" or checked["archived_grid_provenance"] != provenance or
            visual["status"] != "passed" or visual["coordinate_audit_sha256"] != audit.sha256(args.out_dir / "coordinate_audit.json") or
            visual["coordinate_overlay_sha256"] != audit.sha256(args.out_dir / "coordinate_overlay.png")):
        raise ValueError("The coordinate audit and visual review must both pass before freezing references")
    refs = args.work_dir / "refs"
    refs.mkdir(parents=True, exist_ok=False)
    dev, _, members = development_metadata()
    records = []
    for row in rows:
        obj = row["tuber"]
        item = {"tuber": obj, "frame": row["frame"], "reference_obj_sha256": dev[obj]["files"]["reference"]["sha256"]}
        try:
            with TemporaryDirectory(prefix="corepp-accuracy-reference-") as folder:
                mesh, samples, center, _, _ = ref_mesh(args, obj, Path(folder), dev, members)
                target_hash = audit.array_sha256(np.asarray(samples.points).astype(np.float32))
                if obj == FOCUS and target_hash != checked["loader_target_sha256"]:
                    raise ValueError("Frozen target does not reproduce the verified loader target")
                path = refs / f"{obj}.npz"
                np.savez(path, vertices=np.asarray(mesh.vertices), triangles=np.asarray(mesh.triangles))
                vertices = np.asarray(mesh.vertices)
                item.update(center_sfm_m=center.tolist(), centered_extent_mm=(np.ptp(vertices, axis=0)*1000).tolist(),
                            loader_sample_sha256=target_hash, frozen_mesh_sha256=audit.sha256(path), failure=None)
        except (ValueError, RuntimeError, OSError, KeyError) as exc:
            item["failure"] = f"{type(exc).__name__}: {exc}"
        records.append(item)
    pilot.put_json(args.out_dir / "frozen_protocol.json", {
        "stage": "fixed_pose_and_endpoints_frozen_before_accuracy_scoring", "protocol_sha256": audit.sha256(PROTOCOL),
        "script_sha256": audit.sha256(Path(__file__)), "upstream_files_sha256": checked["source_sha256"],
        "coordinate_audit_sha256": audit.sha256(args.out_dir / "coordinate_audit.json"),
        "visual_review_sha256": audit.sha256(args.review), "archived_grid_provenance": provenance,
        "surface_sample_count_per_direction": 20000, "surface_sample_seed": audit.CPU_SEED,
        "mesh_vertex_order_rounding_decimals_m": MESH_DECIMALS_M,
        "tie_tolerance_mm": TOL_MM, "references": records,
    })


REPLAY = None


def initialize(args):
    global REPLAY
    runtime = multi.Runtime(argparse.Namespace(**(vars(args) | {"phase": "score"})))
    REPLAY = MeshReplay(args, runtime, archive_context(args, runtime))


def aggregate(rows, field):
    values = [r[field]["median"] for r in rows if not r["failure"]]
    return {"n": len(values), "mean_mm": mean(values) if values else None,
            "median_mm": median(values) if values else None,
            "improved": sum(v < -TOL_MM for v in values), "worsened": sum(v > TOL_MM for v in values),
            "tied": sum(abs(v) <= TOL_MM for v in values)}


def score_one(job):
    row, verified, ref = job
    obj = row["tuber"]
    records = []
    item = {"tuber": obj, "frame": row["frame"], "surface_displacement_mm": row["expanded"]["edit_medians_mm"],
            "pin_minus_mean_peel_displacement_mm": row["expanded"]["primary"]["median"]}
    if ref["failure"]:
        return item | {"failure": ref["failure"], "seeds": []}
    try:
        path = REPLAY.args.work_dir / "refs" / f"{obj}.npz"
        if audit.sha256(path) != ref["frozen_mesh_sha256"]:
            raise ValueError("Centered reference changed")
        with np.load(path, allow_pickle=False) as data:
            target = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(data["vertices"]),
                                               o3d.utility.Vector3iVector(data["triangles"]))
        target = ordered_surface(target)
        latents, sdfs = REPLAY.load_cache(obj, verified)
        for i, (pair, replay) in enumerate(zip(row["pairs"], verified["seeds"], strict=True)):
            seed = pair["seed"]
            if replay["seed"] != seed:
                raise ValueError("Seed order differs from replay archive")
            decoded_meshes, replay_checks = {}, {}
            for j, name in enumerate(multi.CONDITIONS):
                archived = pair["expanded_grid"][name]
                expected = replay["conditions"][name]
                decoded = REPLAY.predict(seed, pair["shell_seed"], latents[i, j], sdfs[i, j],
                                         expected["hashes"] | {"inside_labels_sha256": expected["inside_labels_sha256"]}, archived)
                if name == "original":
                    baseline = decoded
                else:
                    displacement = grid.surface_displacement(baseline, decoded)
                    decoded["replay"]["displacement_replay_abs_difference_mm"] = abs(displacement - archived["displacement_mm"])
                decoded_meshes[name] = ordered_surface(decoded["mesh"])
                replay_checks[name] = decoded["replay"]
            errors = {name: surface_error(target, mesh) for name, mesh in decoded_meshes.items()}
            pin_change = errors["pin"] - errors["original"]
            peel_changes = [errors[name] - errors["original"] for name in multi.EDIT_NAMES[1:]]
            records.append({"seed": seed, "errors_mm": errors, "replay_checks": replay_checks, "pin_change_mm": pin_change,
                            "pin_minus_mean_peel_change_mm": pin_change - mean(peel_changes)})
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        return item | {"failure": f"{type(exc).__name__}: {exc}", "seeds": records}
    return item | {"failure": None, "seeds": records,
                   "error_medians_mm": {name: median(p["errors_mm"][name] for p in records) for name in multi.CONDITIONS},
                   "pin_change_mm": pilot.summarize([p["pin_change_mm"] for p in records]),
                   "pin_minus_mean_peel_change_mm": pilot.summarize([p["pin_minus_mean_peel_change_mm"] for p in records])}


def score(args, context):
    _, _, _, rows, replay, provenance = context
    manifest = audit.read_json(args.out_dir / "frozen_protocol.json")
    if (manifest["protocol_sha256"] != audit.sha256(PROTOCOL) or manifest["script_sha256"] != audit.sha256(Path(__file__)) or
            manifest["archived_grid_provenance"] != provenance or
            any(audit.sha256(args.upstream / name) != h for name, h in manifest["upstream_files_sha256"].items())):
        raise ValueError("Frozen protocol or geometry provenance changed")
    refs = manifest["references"]
    if [(r["tuber"], r["frame"]) for r in refs] != [(r["tuber"], r["frame"]) for r in rows]:
        raise ValueError("Frozen references do not match the scored cohort")
    path = args.out_dir / "results.json"
    if path.exists():
        raise FileExistsError(path)
    result = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn"),
                             initializer=initialize, initargs=(args,)) as pool:
        for item in pool.map(score_one, zip(rows, replay, refs, strict=True)):
            result.append(item)
            print(f"{item['tuber']}: {item['failure'] or '16 paired seed sets scored'}", flush=True)
    pilot.put_json(path, {"frozen_protocol_sha256": audit.sha256(args.out_dir/"frozen_protocol.json"),
                          "selected": len(rows), "results": result, "cohort": {
                              name: aggregate(result, name) for name in ("pin_change_mm", "pin_minus_mean_peel_change_mm")
                          }})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=("audit", "freeze", "score"))
    for name in ("source", "upstream", "released", "out-dir", "input-dir", "cache-dir", "work-dir"):
        p.add_argument(f"--{name}", type=Path, required=True)
    p.add_argument("--review", type=Path)
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    runtime = multi.Runtime(argparse.Namespace(**(vars(args) | {"phase": "score" if args.phase == "audit" else "freeze"})))
    context = archive_context(args, runtime)
    if args.phase == "audit":
        audit_mapping(args, runtime, context)
    elif args.phase == "freeze":
        save_refs(args, context)
    else:
        score(args, context)


if __name__ == "__main__":
    main()
