"""Plot the first evaluable tuber's first band on the scored 1 mm cells."""
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


def plot_example(example, path):
    xy = example["xy"]
    nominal = example["band_cells"]
    scored = example["scored"]
    x, y = xy[nominal].astype(int).T
    x0, x1, y0, y1 = x.min(), x.max(), y.min(), y.max()
    cols, rows = (xy[scored] - [x0, y0]).astype(int).T

    def raster(values):
        table = np.full((y1-y0+1, x1-x0+1), np.nan)
        table[rows, cols] = values[scored]
        return table

    fig, axes = plt.subplots(2, 3, figsize=(11.6, 6.8), layout="constrained",
                             sharex=True, sharey=True)
    extent = (x0-.5, x1+.5, y0-.5, y1+.5)

    def draw(ax, title, values, cmap, lo, hi):
        ax.scatter(x, y, color="#dedede", s=2, marker="s", linewidths=0, zorder=0)
        image = ax.imshow(raster(values), origin="lower", interpolation="nearest",
                          extent=extent, cmap=cmap, vmin=lo, vmax=hi, zorder=1)
        ax.set_title(title, fontsize=11, loc="left")
        ax.set(xlim=extent[:2], ylim=extent[2:], aspect="equal")
        return image

    scan, sfm_top = example["scan_correction"], example["sfm_top"]
    body, aligned, sfm = (example[k] for k in ("lower_body", "lower_aligned", "lower_sfm"))
    limit = max(.1, np.max(np.abs(np.r_[scan[scored], sfm_top[scored]])))
    top = draw(axes[0, 0], "RGB-D top correction", scan, "RdBu_r", -limit, limit)
    draw(axes[0, 1], "SfM top relief", sfm_top, "RdBu_r", -limit, limit)
    fig.colorbar(top, ax=axes[0, :2], location="bottom", shrink=.72, label="Centered top height (mm)")

    change = np.abs(aligned-sfm) - np.abs(body-sfm)
    limit = max(.1, np.max(np.abs(change[scored])))
    delta = draw(axes[0, 2], "Change in absolute error", change, "PuOr_r", -limit, limit)
    fig.colorbar(delta, ax=axes[0, 2], location="bottom", shrink=.95, label="Aligned minus body (mm)")

    lower = np.r_[body[scored], aligned[scored], sfm[scored]]
    for axis, title, height in zip(axes[1], ("Smooth body", "Aligned reflection", "Measured SfM underside"),
                                   (body, aligned, sfm)):
        image = draw(axis, title, height, "viridis", lower.min(), lower.max())
        axis.set_xlabel("Belt x (mm)")
    fig.colorbar(image, ax=axes[1], location="bottom", shrink=.75, label="Underside height above belt (mm)")
    for axis in axes[:, 0]:
        axis.set_ylabel("Belt y (mm)")
    fig.suptitle(f"{example['object_id']} · frame {example['frame_id']} · normalized radius {example['radial_band']}",
                 fontsize=14, weight="bold")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
