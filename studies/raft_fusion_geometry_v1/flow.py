"""Produce frozen bidirectional RAFT pixel flow for consecutive selected sequences."""

from contextlib import ExitStack
from pathlib import Path
import time

import numpy as np
import torch
import torchvision
from torchvision.models.optical_flow import Raft_Small_Weights, raft_small

import prepare as prep


def model():
    weights = Raft_Small_Weights.C_T_V2
    if prep.digest(prep.CHECKPOINT) != prep.CHECKPOINT_HASH:
        raise ValueError("RAFT-small checkpoint hash differs")
    torch.set_num_threads(6)
    torch.set_num_interop_threads(1)
    torch.manual_seed(133)
    tracker = raft_small(weights=None, progress=False)
    tracker.load_state_dict(torch.load(prep.CHECKPOINT, map_location="cpu", weights_only=True))
    return tracker.eval(), weights.transforms(), weights.url


def crop_bounds(first, second):
    ys, xs = np.nonzero((first[:, :, 3] > 0) | (second[:, :, 3] > 0))
    if not len(xs):
        raise ValueError("Empty provided masks")
    h, w = first.shape[:2]
    limits = []
    for scan, size in ((xs, w), (ys, h)):
        low, high = max(0, int(scan.min()) - 24), min(size, int(scan.max()) + 25)
        if high - low < 128:
            low = max(0, min((low + high - 128) // 2, size - 128))
            high = low + 128
        limits.append((low, high))
    (x0, x1), (y0, y1) = limits
    return x0, y0, x1, y1


def predict(first_rgb, second_rgb, tracker, normalize):
    h, w = first_rgb.shape[:2]
    source = torch.from_numpy(np.ascontiguousarray(first_rgb)).permute(2, 0, 1)[None, ...]
    target = torch.from_numpy(np.ascontiguousarray(second_rgb)).permute(2, 0, 1)[None, ...]
    first, second = normalize(source, target)
    pad = (0, (-w) % 8, 0, (-h) % 8)
    first = torch.nn.functional.pad(first, pad, mode="replicate")
    second = torch.nn.functional.pad(second, pad, mode="replicate")
    flow = tracker(first, second, num_flow_updates=12)[-1][0, :, :h, :w]
    output = flow.permute(1, 2, 0).contiguous().numpy()
    if not np.isfinite(output).all():
        raise ValueError("Nonfinite dense RAFT prediction")
    return output


def synthetic_check(tracker, normalize):
    from scipy.ndimage import gaussian_filter, shift

    rng = np.random.default_rng(prep.SEED)
    texture = gaussian_filter(rng.random((160, 192, 3)), sigma=(1.2, 1.2, 0))
    rgb = np.clip((texture - texture.min()) / (texture.max() - texture.min()) * 255, 0, 255).astype(np.uint8)
    expected = np.array([8., -6.])
    shifted = shift(rgb, (-6, 8, 0), order=0, mode="constant", cval=0)
    fv = predict(rgb, shifted, tracker, normalize)[35:-35, 35:-35]
    median = np.median(fv.reshape(-1, 2), axis=0)
    if np.linalg.norm(median - expected) > 2.:
        raise ValueError(f"RAFT synthetic pixel direction/scale replay failed: {median}")
    return {"expected_dx_dy_px": expected.tolist(), "median_dx_dy_px": median.tolist()}


def run():
    manifest = prep.load_manifest()
    output = prep.ASSETS / "flows"
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    tracker, normalize, url = model()
    setup_seconds = time.perf_counter()-started
    links = []
    with ExitStack() as stack, torch.inference_mode():
        check = synthetic_check(tracker, normalize)
        print("RAFT synthetic translation check:", check, flush=True)
        archives = prep.open_images(stack, (f["rgb"]["archive"] for r in manifest["roster"] for f in r["frames"]))
        for i, row in enumerate(manifest["roster"], 1):
            tuber = row["tuber"]
            frames = row["frames"]
            previous = None
            for source, target in zip(frames[:-1], frames[1:], strict=True):
                n0, n1 = source["suffix"], target["suffix"]
                path = output / f"{tuber}_{n0}_{n1}.npz"
                record = {"tuber": tuber, "source": n0, "target": n1, "file": None, "error": None}
                start = time.perf_counter()
                try:
                    if previous is None:
                        member = source["rgb"]
                        previous = prep.read_rgba(archives[member["archive"]], member)
                    member = target["rgb"]
                    next_image = prep.read_rgba(archives[member["archive"]], member)
                    x0, y0, x1, y1 = crop_bounds(previous, next_image)
                    first = previous[y0:y1, x0:x1, :3]
                    second = next_image[y0:y1, x0:x1, :3]
                    forward = predict(first, second, tracker, normalize)
                    reverse = predict(second, first, tracker, normalize)
                    temp = path.with_suffix(".tmp")
                    with temp.open("wb") as f:
                        np.savez_compressed(f, origin=[x0, y0], forward=forward, reverse=reverse)
                    temp.replace(path)
                    previous = next_image
                    record.update({"file": path.name, "sha256": prep.digest(path),
                                   "crop_xyxy": [x0, y0, x1, y1]})
                except (KeyError, ValueError, RuntimeError, OSError) as error:
                    previous = None
                    record["error"] = f"{type(error).__name__}: {error}"
                record["wall_s"] = time.perf_counter() - start
                links.append(record)
            print(f"RAFT flow {i}/{len(manifest['roster'])}: {tuber}", flush=True)
    summary = {"flow_code_sha256": prep.digest(Path(__file__)), "manifest_sha256": prep.digest(prep.STUDY/"frame_manifest.json"),
               "checkpoint_sha256": prep.CHECKPOINT_HASH, "checkpoint_url": url,
               "torch": torch.__version__, "torchvision": torchvision.__version__,
               "cpu_setup_s": setup_seconds, "synthetic": check, "links": links}
    prep.write_json(prep.ASSETS / "flow_run.json", summary)


if __name__ == "__main__":
    run()
