"""Audit the released CoRe++ CPU path on the registered 2R1-10 development frame."""
import argparse
import csv
import hashlib
import json
import math
import platform
import sys
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from zipfile import ZipFile

import cv2 as cv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import open3d as o3d
from PIL import Image
import torch

HERE = Path(__file__).resolve().parent
DEV = HERE.parent / "real_lobes_v1"
OBJECT = "2R1-10"
UPSTREAM_COMMIT = "0d6bae40b9215332efd566e6bca83bea171b99e9"
INPUT_INTRINSICS = "1_rgbd/0_camera_intrinsics/realsense_d405_camera_intrinsic.json"
PIN_LABELS = "1_rgbd/pin_regions.json"
MATRIX_ARCHIVE = "3_pair/tmatrix.zip"
CPU_SEED = 133
CHECKPOINT_SHA256 = {
    "_super3d_32_best_model.pt": "6d5555fad2fe2f5fc2ecbbdd0f2b2b0a9f42e09aa91460c88538970bc345cf9f",
    "500.pth": "72bdb43a710a4ea28b7332b816474147f2b824679d0241eccdcac6e2d0106132",
}
SOURCE_FILES = (
    "test.py", "data_preparation/organize_data.py", "data_preparation/pcd_from_sfm.py",
    "data/potato_example/realsense/intrinsic.json", "dataloaders/cameralaser_w_masks.py",
    "dataloaders/transforms.py", "networks/models.py", "networks/utils.py", "networks/blocks.py",
    "networks/resnet.py", "networks/rgb_depth_fusion.py",
    "deepsdf/networks/deep_sdf_decoder.py", "sdfrenderer/grid.py", "utils.py",
)


def sha256(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def array_sha256(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def stage_frame(source, root):
    """Take one released RGB-D frame and its SfM OBJ from the archived development roster."""
    selection_path = DEV / "fresh_selection.json"
    selection = read_json(selection_path)
    pair, = [p for p in selection["pairs"] if p["object_id"] == OBJECT]
    archive = read_json(HERE / "results.json")
    prior, = [p for p in archive["intake"]["pairs"] if p["object_id"] == OBJECT]
    with (DEV / "fresh_download_members.tsv").open(newline="") as handle:
        members = {(r["tuber_id"], r["member_basename"]): r for r in csv.DictReader(handle, delimiter="\t")}
    input_hashes = {"development_selection": sha256(selection_path), "archived_development_results": sha256(HERE/"results.json")}
    paths = {}
    for role in ("rgb", "depth", "reference"):
        filename = Path(pair[role]).name
        member = members[OBJECT, filename]
        path = root / filename
        with ZipFile(source / member["archive"]) as z:
            info = z.getinfo(member["member_path"])
            if info.file_size != int(member["uncompressed_bytes"]):
                raise ValueError(f"Unexpected archived size for {filename}")
            path.write_bytes(z.read(info))
        paths[role] = path
        input_hashes[role] = sha256(path)
        if input_hashes[role] != prior["files"][role]["sha256"]:
            raise ValueError(f"The released {role} differs from the archived development input")
    with ZipFile(source / MATRIX_ARCHIVE) as z:
        registration = z.read(pair["registration_member"])
    input_hashes["registered_pair_json"] = hashlib.sha256(registration).hexdigest()
    meta = json.loads(registration)
    frame = pair["frame"]
    if (input_hashes["registered_pair_json"] != prior["files"]["registration"]["sha256"]
            or meta["rgbd_pcd_file"] != pair["partial"] or meta["sfm_mesh_file"] != pair["reference"]
            or pair["rgb"] != f"{OBJECT}_rgb_{frame}.png" or pair["depth"] != f"{OBJECT}_depth_{frame}.png"):
        raise ValueError("Frame identity differs from the released registration")
    for key, paths_in_release in (("pin_annotation", PIN_LABELS), ("release_intrinsics", INPUT_INTRINSICS)):
        path = source / paths_in_release
        input_hashes[key] = sha256(path)
        if input_hashes[key] != selection["metadata_sha256"][path.name]:
            raise ValueError(f"Unexpected release hash for {path.name}")
    labels = read_json(source / PIN_LABELS)
    image, = [im for im in labels["images"] if im["file_name"] == f"{OBJECT}/{pair['rgb']}"]
    pin, = [a for a in labels["annotations"] if a["image_id"] == image["id"]]
    return paths, input_hashes, frame, pin


def prepare_tensor(paths, pin, camera_file, cfg, prepare_images, histogram, pad_cls, get_padding):
    start = perf_counter()
    # organize_data.py writes the RGB and alpha separately. A lossless PNG round trip
    # leaves these pixel values intact; __getitem__ then converts BGR to RGB.
    rgba = cv.imread(str(paths["rgb"]), cv.IMREAD_UNCHANGED)
    rgb = cv.cvtColor(rgba[:, :, :3], cv.COLOR_BGR2RGB)
    alpha = rgba[:, :, 3] // 255
    depth = cv.imread(str(paths["depth"]), cv.IMREAD_UNCHANGED).astype(np.float32)
    min_depth, max_depth = histogram(depth, alpha, 50, 0.05)
    masked_rgb, masked_depth, mask, origin, _, _, _ = prepare_images(
        rgb, depth, alpha, str(camera_file), cfg["detection_input"])
    h, w = masked_depth.shape
    row, col = map(int, origin)
    crop = np.s_[row:row+h, col:col+w]
    valid_source = (alpha > 0) & (depth != 0) & (depth >= min_depth) & (depth <= max_depth)
    np.testing.assert_array_equal(mask.astype(bool), valid_source[crop])
    pad = pad_cls(size=cfg["input_size"])
    normal = (masked_depth - cfg["depth_min"]) / (cfg["depth_max"] - cfg["depth_min"])
    normal[masked_depth == 0] = 0
    padded_rgb = np.array(pad(masked_rgb))
    padded_depth = np.array(pad(normal))
    tensor = torch.cat((torch.from_numpy(padded_rgb).permute(2, 0, 1).float()/255,
                        torch.from_numpy(padded_depth).unsqueeze(0).float()), dim=0).unsqueeze(0)
    if tensor.shape != (1, 4, cfg["input_size"], cfg["input_size"]) or not torch.isfinite(tensor).all():
        raise ValueError(f"Unexpected encoder input shape or values: {tensor.shape}")
    left, top, right, bottom = get_padding(Image.fromarray(masked_rgb), cfg["input_size"])
    if min(left, top, right, bottom) < 0:
        raise ValueError("This frame exceeds the released padding size")
    x, y, bw, bh = pin["bbox"]
    bbox = np.zeros(alpha.shape, dtype=bool)
    bbox[math.floor(y):math.ceil(y+bh), math.floor(x):math.ceil(x+bw)] = True
    yy, xx = np.nonzero(bbox & valid_source)
    inside = (yy >= row) & (yy < row+h) & (xx >= col) & (xx < col+w)
    yy, xx = yy[inside], xx[inside]
    np.testing.assert_array_equal(padded_rgb[yy-row+top, xx-col+left], rgb[yy, xx])
    np.testing.assert_array_equal(padded_depth[yy-row+top, xx-col+left], normal[yy-row, xx-col])
    trace = {
        "coco_annotation_id": pin["id"], "bbox_xywh_px": pin["bbox"],
        "bbox_area_px": int(bbox.sum()), "box_pixels_with_target_alpha": int((bbox & (alpha > 0)).sum()),
        "box_pixels_passing_alpha_and_depth": int((bbox & valid_source).sum()),
        "box_pixels_retained_after_crop_and_pad": len(xx),
        "retained_rgb_pixels_equal_to_source": True,
        "histogram_depth_range_mm": [float(min_depth), float(max_depth)],
        "crop_origin_yx_px": [row, col], "crop_height_width_px": [h, w], "pad_ltrb_px": [left, top, right, bottom],
        "bbox_in_model_xywh_px": [x-col+left, y-row+top, bw, bh], "input_shape_nchw": list(tensor.shape),
    }
    return tensor, padded_rgb, trace, perf_counter()-start


def draw_pin(rgb, trace, path):
    x, y, w, h = trace["bbox_in_model_xywh_px"]
    zoom = 14
    fig, axes = plt.subplots(1, 2, figsize=(7.7, 4.2), layout="constrained")
    axes[0].imshow(rgb, interpolation="nearest")
    axes[0].set_title("CoRe++ RGB input · 304 × 304")
    axes[1].imshow(rgb, interpolation="nearest")
    axes[1].set(xlim=(x-zoom, x+w+zoom), ylim=(y+h+zoom, y-zoom))
    axes[1].add_patch(Rectangle((x-.5, y-.5), w, h, fill=False, ec="#4dd3ec", lw=1.4, linestyle="--"))
    axes[1].set_title("Pin annotation · magnified")
    for ax in axes:
        ax.set_axis_off()
    fig.suptitle("Registered development frame 2R1-10 / 364", fontsize=13, fontweight="bold")
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def surface_distances_mm(source, target):
    """Area-weighted, seeded points from one mesh to triangles of the other."""
    vertices = np.asarray(source.vertices)
    triangles = vertices[np.asarray(source.triangles)]
    area = np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), axis=1)
    rng = np.random.default_rng(CPU_SEED)
    indices = rng.choice(len(triangles), size=20000, p=area/area.sum())
    triangle = triangles[indices]
    u, v = rng.random((2, len(indices)))
    root = np.sqrt(u)
    points = (1-root[:, None])*triangle[:, 0] + (root*(1-v))[:, None]*triangle[:, 1] + (root*v)[:, None]*triangle[:, 2]
    scene = o3d.t.geometry.RaycastingScene(nthreads=1)
    scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(target))
    distance = scene.compute_distance(o3d.core.Tensor(points, dtype=o3d.core.Dtype.Float32), nthreads=1)
    return distance.numpy()*1e3


def run(args):
    sys.path.insert(0, str(args.upstream.resolve()))
    from data_preparation.pcd_from_sfm import main as prepare_sfm
    from dataloaders.cameralaser_w_masks import MaskedCameraLaserData, histogram_filtering
    from dataloaders.transforms import Pad, get_padding
    from deepsdf.networks.deep_sdf_decoder import Decoder
    from networks.models import EncoderBigPooled
    from networks.utils import load_without_parallel, set_require_grad
    from sdfrenderer.grid import Grid3D
    from utils import sdf2mesh_cuda

    cfg_path = args.released/"super3d_32.json"
    specs_path = args.released/"specs.json"
    cfg, specs = read_json(cfg_path), read_json(specs_path)
    if (cfg["encoder"], cfg["detection_input"], cfg["input_size"], cfg["normalize_depth"], specs["NetworkArch"]) != (
            "pool", "mask", 304, True, "deep_sdf_decoder"):
        raise ValueError("Unexpected released CoRe++ model configuration")
    checkpoint_paths = {name: args.released/name for name in CHECKPOINT_SHA256}
    actual_hashes = {name: sha256(path) for name, path in checkpoint_paths.items()}
    if actual_hashes != CHECKPOINT_SHA256 or cfg["checkpoint_file"] not in checkpoint_paths:
        raise ValueError("Official checkpoint hashes or configuration differ from the recorded files")
    checkpoint = torch.load(checkpoint_paths[cfg["checkpoint_file"]], map_location="cpu", weights_only=True)
    pretrain = torch.load(checkpoint_paths["500.pth"], map_location="cpu", weights_only=True)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    cv.setNumThreads(1)
    decoder = Decoder(specs["CodeLength"], **specs["NetworkSpecs"]).cpu()
    decoder.load_state_dict(load_without_parallel(pretrain), strict=True)
    set_require_grad(decoder, False)
    torch.manual_seed(CPU_SEED)
    np.random.seed(CPU_SEED)
    encoder = EncoderBigPooled(4, specs["CodeLength"], cfg["input_size"]).cpu()
    encoder.load_state_dict(checkpoint["encoder_state_dict"], strict=True)
    decoder.load_state_dict(checkpoint["decoder_state_dict"], strict=True)

    camera = args.upstream/"data/potato_example/realsense/intrinsic.json"
    actual_camera, camera_template = read_json(args.source/INPUT_INTRINSICS), read_json(camera)
    if any(actual_camera[k] != camera_template[k] for k in ("width", "height", "intrinsic_matrix")):
        raise ValueError("Upstream camera example differs from the development release intrinsics")

    with TemporaryDirectory(prefix="potato-corepp-frame-") as temp:
        root = Path(temp)
        paths, input_hashes, frame, pin = stage_frame(args.source, root)
        # The released test uses the largest SfM point-cloud extent of its input
        # split. Run the identical bbox helper on a split containing just this tuber.
        o3d.utility.random.seed(CPU_SEED)
        prepared = root/"prepared"
        prepare_sfm(str(root), str(prepared))
        fixture = MaskedCameraLaserData.__new__(MaskedCameraLaserData)
        fixture.split_ids = [OBJECT]
        fixture.data_source = str(prepared)
        box = fixture.find_global_bbox()
        frames = [
            prepare_tensor(paths, pin, camera, cfg, MaskedCameraLaserData.preprocess_images,
                           histogram_filtering, Pad, get_padding)
            for _ in range(2)
        ]
        input_hashes["prepared_sfm_point_cloud_for_grid"] = sha256(prepared/OBJECT/"laser/fruit.ply")
    input_hashes["upstream_intrinsics_with_depth_scale"] = sha256(camera)
    if not torch.equal(frames[0][0], frames[1][0]):
        raise ValueError("Two preprocess passes on the unchanged frame produced different tensors")

    args.run_dir.mkdir(parents=True, exist_ok=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.run_dir.joinpath("model_rgb_304.png").write_bytes(
        cv.imencode(".png", cv.cvtColor(frames[0][1], cv.COLOR_RGB2BGR))[1].tobytes())
    draw_pin(frames[0][1], frames[0][2], args.out_dir/"corepp_pin_input.png")
    prepared_items = [(item[0][0], idx) for idx, item in enumerate(frames)]
    # The stock test seeds once and leaves the modules in training mode during
    # no_grad. Keep that behavior, including the decoder's programmed dropout.
    loader = torch.utils.data.DataLoader(prepared_items, batch_size=1, shuffle=False)
    entries, meshes, latents, sdfs = [], [], [], []
    with torch.no_grad():
        for tensor, idx in loader:
            index = int(idx.item())
            start = perf_counter()
            latent = encoder(tensor)
            grid = Grid3D(cfg["grid_density"], "cpu", torch.float32, bbox=box).points
            sdf = decoder(torch.cat((latent.expand(len(grid), -1), grid), dim=1))
            mesh = sdf2mesh_cuda(sdf, grid, t=0.0)
            if not mesh.is_watertight():
                raise ValueError("Released postprocessing did not produce a watertight mesh")
            volume = mesh.get_volume()*1e6
            seconds = perf_counter()-start
            vertices, faces = np.asarray(mesh.vertices), np.asarray(mesh.triangles)
            path = args.run_dir/f"run_{index+1}_mesh.ply"
            if not o3d.io.write_triangle_mesh(str(path), mesh):
                raise ValueError(f"Could not save {path}")
            meshes.append(mesh)
            latents.append(latent.numpy())
            sdfs.append(sdf.numpy())
            entries.append({
                "run_number": index+1, "preprocessing_seconds": frames[index][3],
                "forward_and_mesh_seconds": seconds, "volume_ml": volume, "watertight": True,
                "vertices": len(vertices), "faces": len(faces), "grid_points": len(grid),
                "negative_sdf_grid_points": torch.count_nonzero(sdf < 0).item(),
                "input_tensor_sha256": array_sha256(tensor.numpy()),
                "latent_sha256": array_sha256(latent.numpy()), "sdf_sha256": array_sha256(sdf.numpy()),
                "mesh_file_sha256": sha256(path), "mesh_file": path.name,
            })

    distances = np.concatenate((surface_distances_mm(meshes[0], meshes[1]), surface_distances_mm(meshes[1], meshes[0])))
    out = {
        "stage": "released_corepp_unchanged_frame_cpu_audit", "upstream_commit": UPSTREAM_COMMIT,
        "object_id": OBJECT, "frame_id": frame,
        "upstream_file_sha256": {f: sha256(args.upstream/f) for f in SOURCE_FILES},
        "checkpoint_sha256": actual_hashes, "checkpoint_epoch_fields": {
            "joint": checkpoint["epoch"], "pretrain": pretrain["epoch"]},
        "released_config_sha256": {cfg_path.name: sha256(cfg_path), specs_path.name: sha256(specs_path)},
        "input_sha256": input_hashes, "pin_trace": frames[0][2],
        "environment": {"machine": platform.machine(), "platform": platform.platform(), "python": sys.version,
                        "dependencies": {k: version(k) for k in ("torch", "torchvision", "numpy", "open3d", "opencv-python", "Pillow")}},
        "cpu_threads": torch.get_num_threads(), "seed_once_per_process": CPU_SEED,
        "encoder_training_mode": encoder.training, "decoder_training_mode": decoder.training,
        "decoder_dropout_prob": specs["NetworkSpecs"]["dropout_prob"],
        "grid_bbox_m_single_tuber_split": box, "runs": entries,
        "differences": {
            "input_tensor_bitwise_equal": True, "latent_max_abs_difference": float(np.max(np.abs(latents[0]-latents[1]))),
            "sdf_max_abs_difference": float(np.max(np.abs(sdfs[0]-sdfs[1]))),
            "sdf_inside_label_changes": int(np.count_nonzero((sdfs[0]<0) != (sdfs[1]<0))),
            "symmetric_surface_distance_sample_count": len(distances),
            "symmetric_surface_distance_mean_mm": float(np.mean(distances)),
            "symmetric_surface_distance_p95_mm": float(np.percentile(distances, 95)),
            "symmetric_surface_distance_max_mm": float(np.max(distances)),
            "absolute_volume_difference_ml": abs(entries[0]["volume_ml"]-entries[1]["volume_ml"]),
        },
    }
    (args.out_dir/"corepp_cpu_audit.json").write_text(json.dumps(out, indent=2, allow_nan=False)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "upstream", "released", "run-dir", "out-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
