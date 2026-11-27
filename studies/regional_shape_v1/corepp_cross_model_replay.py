"""Test unchanged-frame TripoSR inference and observation-only scale on one CPU frame."""

import argparse
import hashlib
import json
import platform
from pathlib import Path
import site
import sys
from time import perf_counter, process_time
from types import ModuleType
from unittest.mock import patch

import numpy as np
import open3d as o3d
from PIL import Image, ImageDraw
from skimage.measure import marching_cubes
import torch

HERE = Path(__file__).resolve().parent
SIZE = 512
GRID = 128
THRESHOLD = 25.0
MESH_AXIS_TO_CAMERA = np.array([[0., 1., 0.], [0., 0., -1.], [-1., 0., 0.]])
CHECKPOINT_SHA256 = "429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee"


def hash_file(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def hash_array(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def preserve_pin(rgba, box, folder, model, resize_foreground):
    cropped = np.asarray(resize_foreground(rgba, 0.85))
    alpha = cropped[..., 3:] / np.float32(255)
    native = cropped.astype(np.float32) / np.float32(255)
    prepared = Image.fromarray(((native[..., :3] * alpha + (1 - alpha) * 0.5) * 255).astype(np.uint8))
    condition = model.image_processor([prepared], SIZE)[0]
    rgb_display = Image.fromarray(np.rint(condition.numpy() * 255).astype(np.uint8))
    rgb_display.save(folder / "model_rgb.png")
    original = np.array(rgba)
    x, y, w, h = box
    # Trace only annotation support in a separate plane. Model RGB is untouched.
    support = np.zeros(original.shape, dtype=np.uint8)
    support[..., 3] = original[..., 3]
    support[y:y+h, x:x+w, :3] = 255
    transformed = np.asarray(resize_foreground(Image.fromarray(support), 0.85))
    mask = transformed[..., :1] * (transformed[..., 3:] == 255)
    probe = model.image_processor([np.repeat(mask, 3, axis=2)], SIZE)[0, ..., 0].numpy()
    ys, xs = np.nonzero(probe > 0.5)
    if not len(xs):
        raise ValueError("The pin annotation did not reach the model RGB tensor")
    marked = rgb_display.copy()
    ImageDraw.Draw(marked).rectangle((int(xs.min())-2, int(ys.min())-2, int(xs.max())+2, int(ys.max())+2),
                                    outline="#ffee00", width=2)
    marked.save(folder / "pin_overlay.png")
    return prepared, {
        "source_box_xywh": box, "source_box_pixels": w*h,
        "source_box_opaque_pixels": int(np.count_nonzero(original[y:y+h, x:x+w, 3] == 255)),
        "pre_resize_square_px": prepared.width, "model_square_px": SIZE,
        "model_pin_support_pixels_gt_half": len(xs),
        "model_box_xywh": [int(xs.min()), int(ys.min()), int(np.ptp(xs))+1, int(np.ptp(ys))+1],
        "model_rgb_sha256": hash_array(condition.numpy()),
    }


def cpu_marching_cubes(field, level):
    verts, faces, _, _ = marching_cubes(field.detach().numpy(), level=level, allow_degenerate=False)
    # torchmcubes returns Z,Y,X. The authors reverse this in their mesh helper.
    return torch.from_numpy(verts[:, ::-1].copy()), torch.from_numpy(faces.copy()).long()


def load_model(args):
    site.addsitedir(str(args.deps.resolve()))
    sys.path.insert(0, str(args.upstream.resolve()))
    adapter = ModuleType("torchmcubes")
    adapter.marching_cubes = cpu_marching_cubes
    # Substitute only the compiled isosurface binding. Model and density code stay upstream.
    original_binding = sys.modules.get("torchmcubes")
    sys.modules["torchmcubes"] = adapter
    try:
        from tsr.system import TSR
        from tsr.models.tokenizers import image as dino
        from tsr.utils import resize_foreground

        def local_dino_config(repo_id, filename):
            if (repo_id, filename) != ("facebook/dino-vitb16", "config.json"):
                raise ValueError(f"Unexpected DINO dependency {repo_id}/{filename}")
            return str((args.checkpoint / "dino_config.json").resolve())

        with patch.object(dino, "hf_hub_download", local_dino_config):
            model = TSR.from_pretrained(str(args.checkpoint), "config.yaml", "model.ckpt").cpu().eval()
    finally:
        if original_binding is None:
            del sys.modules["torchmcubes"]
        else:
            sys.modules["torchmcubes"] = original_binding
    model.renderer.set_chunk_size(8192)
    return model, resize_foreground


def predict(model, prepared):
    from trimesh import Trimesh

    begin, begin_cpu = perf_counter(), process_time()
    input_hashes = []

    def capture_rgb(_, args):
        rgb = args[0][0, 0].permute(1, 2, 0).numpy()
        input_hashes.append(hash_array(rgb))

    with torch.inference_mode(), model.image_tokenizer.register_forward_pre_hook(capture_rgb):
        scene = model([prepared], device="cpu")
        forward_seconds = perf_counter() - begin
        model.set_marching_cubes_resolution(GRID)
        helper = model.isosurface_helper
        radius = model.renderer.cfg.radius
        grid = helper.grid_vertices * (2 * radius) - radius
        density = model.renderer.query_triplane(model.decoder, grid, scene[0])["density_act"]
        verts, faces = helper(-(density - THRESHOLD))
    mesh = Trimesh(vertices=(verts * (2 * radius) - radius).numpy(), faces=faces.numpy())
    if mesh.volume < 0:
        mesh.invert()
    if not np.isfinite(mesh.vertices).all() or len(mesh.vertices) == 0:
        raise ValueError("Empty or non-finite reconstructed mesh")
    field = density.view(GRID, GRID, GRID).numpy()
    boundary = np.zeros(field.shape, bool)
    for axis in range(3):
        edge = np.moveaxis(boundary, axis, 0)
        edge[[0, -1]] = True
    stats = {
        "forward_seconds": forward_seconds, "forward_and_mesh_seconds": perf_counter() - begin,
        "forward_and_mesh_cpu_seconds": process_time() - begin_cpu,
        "tokenizer_input_sha256": input_hashes[0],
        "triplane_sha256": hash_array(scene.numpy()), "density_sha256": hash_array(density.numpy()),
        "vertex_sha256": hash_array(mesh.vertices), "faces_sha256": hash_array(mesh.faces),
        "vertices": len(mesh.vertices), "faces": len(mesh.faces), "watertight": bool(mesh.is_watertight),
        "solid_grid_nodes_on_boundary": int(np.count_nonzero((field >= THRESHOLD) & boundary)),
        "normalized_extents": mesh.extents.tolist(),
    }
    return mesh, stats


def cast(vertices, faces, rays):
    scene = o3d.t.geometry.RaycastingScene(nthreads=1)
    scene.add_triangles(o3d.core.Tensor(vertices.astype(np.float32)),
                        o3d.core.Tensor(faces.astype(np.uint32)))
    return scene.cast_rays(o3d.core.Tensor(rays.astype(np.float32)), nthreads=1)["t_hit"].numpy()


def spans(xyz):
    return np.quantile(xyz, [0.02, 0.98], axis=0)


def metric_scale(mesh, rgba, depth, intrinsic_path, output):
    intrinsic = json.loads(intrinsic_path.read_text())
    K = np.reshape(intrinsic["intrinsic_matrix"], (3, 3), order="F")
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    observed = np.asarray(rgba)[..., 3] == 255
    # The release alpha, filtered depth and intrinsics belong to this one input frame.
    valid = observed & (depth >= 290.0) & (depth <= 320.1000061035156)
    ys, xs = np.nonzero(valid)
    fit = (xs + ys) % 2 == 0
    z = depth[ys[fit], xs[fit]]
    points = np.column_stack(((xs[fit] - cx) * z / fx, (ys[fit] - cy) * z / fy, z))
    observed_span = spans(points)
    axes = np.asarray(mesh.vertices) @ MESH_AXIS_TO_CAMERA.T
    xy_min = axes[:, :2].min(axis=0)
    xy_max = axes[:, :2].max(axis=0)
    x, y = np.meshgrid(np.linspace(xy_min[0], xy_max[0], 256), np.linspace(xy_min[1], xy_max[1], 256))
    front = axes[:, 2].min() - 1
    ortho = np.stack((x, y, np.full_like(x, front), x*0, y*0, x*0+1), axis=-1)
    hit = cast(axes, mesh.faces, ortho)
    visible = np.isfinite(hit)
    predicted_span = spans(np.column_stack((x[visible], y[visible], front + hit[visible])))
    ratios = np.diff(observed_span[:, :2], axis=0)[0] / np.diff(predicted_span[:, :2], axis=0)[0]
    scale = float(np.sqrt(ratios[0] * ratios[1]))
    shift = observed_span.mean(axis=0) - scale * predicted_span.mean(axis=0)
    shift[2] = observed_span[0, 2] - scale * predicted_span[0, 2]
    vertices_mm = axes * scale + shift
    # Project within a crop that includes observed foreground and the entire mesh.
    proj = vertices_mm[:, :2] / vertices_mm[:, 2:] * [fx, fy] + [cx, cy]
    if np.any(vertices_mm[:, 2] <= 0) or not np.isfinite(proj).all():
        raise ValueError("Converted mesh is not in front of the camera")
    x0 = max(0, int(np.floor(min(proj[:, 0].min(), xs.min()))) - 4)
    x1 = min(depth.shape[1], int(np.ceil(max(proj[:, 0].max(), xs.max()))) + 5)
    y0 = max(0, int(np.floor(min(proj[:, 1].min(), ys.min()))) - 4)
    y1 = min(depth.shape[0], int(np.ceil(max(proj[:, 1].max(), ys.max()))) + 5)
    u, v = np.meshgrid(np.arange(x0, x1), np.arange(y0, y1))
    zero = np.zeros_like(u)
    rays = np.stack((zero, zero, zero, (u-cx)/fx, (v-cy)/fy, zero+1), axis=-1)
    projected = cast(vertices_mm, mesh.faces, rays)
    rendered = np.isfinite(projected)
    real = observed[y0:y1, x0:x1]
    iou = float((rendered & real).sum() / (rendered.sum() + observed.sum() - (rendered & real).sum()))
    holdout = valid[y0:y1, x0:x1] & ((u + v) % 2 == 1)
    matched = rendered & holdout
    if not matched.any():
        raise ValueError("Predicted surface misses all held-out depth pixels")
    residual = np.abs(projected[matched] - depth[y0:y1, x0:x1][matched])
    med, p90 = np.quantile(residual, [0.5, 0.9])
    masked_rgb = np.array(rgba)[y0:y1, x0:x1, :3].copy()
    masked_rgb[~real] = 48
    masked_rgb[rendered & ~real] = [240, 127, 52]
    masked_rgb[real & ~rendered] = [72, 179, 245]
    Image.fromarray(masked_rgb).save(output / "metric_overlay.png")
    gates = {"lateral_scale_ratio_at_most_1_25": float(ratios.max()/ratios.min()) <= 1.25,
             "perspective_silhouette_iou_at_least_0_75": iou >= 0.75,
             "visible_holdout_median_abs_depth_at_most_10_mm": float(med) <= 10}
    return vertices_mm, {
        "local_xy_mm_per_normalized_unit": ratios.tolist(), "uniform_mm_per_normalized_unit": scale,
        "camera_axis_rotation": MESH_AXIS_TO_CAMERA.tolist(), "camera_translation_mm": shift.tolist(),
        "perspective_silhouette_iou": iou, "held_out_depth_pixels": int(holdout.sum()),
        "covered_held_out_depth_pixels": int(matched.sum()),
        "held_out_median_abs_depth_mm": float(med), "held_out_p90_abs_depth_mm": float(p90),
        "calibration_fit_points": int(fit.sum()), "metric_bounds_mm": [vertices_mm.min(0).tolist(), vertices_mm.max(0).tolist()],
        "gates": gates, "passed": all(gates.values()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("upstream", "checkpoint", "deps", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    pilot = json.loads((HERE / "corepp_cpu_audit.json").read_text())
    original = Path("outputs/corepp_pin_pilot/inputs")
    files = {"rgb": original / "original_rgba.png", "depth": original / "depth.png",
             "release_intrinsics": Path("data/raw/3DPotatoTwin/1_rgbd/0_camera_intrinsics/realsense_d405_camera_intrinsic.json")}
    hashes = {key: hash_file(path) for key, path in files.items()}
    if any(pilot["input_sha256"][key] != sha for key, sha in hashes.items()):
        raise ValueError("Input bytes differ from the archived one-frame CoRe++ audit")
    weights = hash_file(args.checkpoint / "model.ckpt")
    if weights != CHECKPOINT_SHA256:
        raise ValueError(f"Checkpoint does not match the author release: {weights}")
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(133)
    start = perf_counter()
    model, resize = load_model(args)
    setup_seconds = perf_counter() - start
    print(f"Loaded official checkpoint on CPU in {setup_seconds:.2f}s", flush=True)
    rgba = Image.open(files["rgb"])
    depth = np.array(Image.open(files["depth"]))
    box = pilot["pin_trace"]["bbox_xywh_px"]
    start = perf_counter()
    prepared, pin = preserve_pin(rgba, box, args.out, model, resize)
    prep_seconds = perf_counter() - start
    predictions, meshes = [], []
    for i in range(2):
        mesh, record = predict(model, prepared)
        if record["tokenizer_input_sha256"] != pin["model_rgb_sha256"]:
            raise ValueError("The traced pin crop does not match the actual tokenizer input")
        meshes.append(mesh)
        predictions.append(record)
        mesh.export(args.out / f"pass_{i + 1}_normalized.ply")
        print(json.dumps({"pass": i + 1, **record}), flush=True)
    metric_vertices, scale = metric_scale(meshes[0], rgba, depth, files["release_intrinsics"], args.out)
    mesh_mm = meshes[0].copy()
    mesh_mm.vertices = metric_vertices
    mesh_mm.export(args.out / "pass_1_camera_mm.ply")
    delta = None if meshes[0].vertices.shape != meshes[1].vertices.shape else float(
        np.linalg.norm(meshes[0].vertices - meshes[1].vertices, axis=-1).max() * scale["uniform_mm_per_normalized_unit"])
    result = {
        "frame": "2R1-10/364", "input_sha256": hashes, "checkpoint_revision": "5b52193",
        "checkpoint_sha256": weights, "config_sha256": hash_file(args.checkpoint / "config.yaml"),
        "dino_config_sha256": hash_file(args.checkpoint / "dino_config.json"),
        "runner_sha256": hash_file(Path(__file__)),
        "upstream_source": json.loads((args.checkpoint / "source_revision.json").read_text())["sha"],
        "replay_protocol_sha256": hash_file(HERE / "corepp_cross_model/replay_protocol.md"),
        "platform": platform.platform(), "python": platform.python_version(), "torch": torch.__version__,
        "mesh_lattice": GRID, "density_threshold": THRESHOLD, "device": "cpu", "threads": args.threads,
        "model_setup_seconds": setup_seconds, "preprocess_seconds": prep_seconds,
        "pin_trace": pin, "metric": scale, "passes": predictions,
        "hashes_equal": {k: predictions[0][k] == predictions[1][k] for k in predictions[0] if k.endswith("sha256")},
        "max_corresponding_vertex_difference_mm": delta,
    }
    (args.out / "replay.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(scale), flush=True)


if __name__ == "__main__":
    main()
