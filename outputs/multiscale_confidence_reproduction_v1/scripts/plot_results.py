"""Plot measured synthetic failure modes from an existing summary.json."""
import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path.cwd()/".cache"/"matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists")
    rows = json.loads(args.summary.read_text())
    conditions = ["clean", "depth_jitter_2mm", "outliers_2percent", "depth_gap"]
    labels = ["Clean", "Depth jitter\n2 mm SD", "Depth outliers\n2% at +10–20 mm", "Missing patch"]
    methods = ["ellipsoid", "convex", "symmetry"]
    colors = ["#34679d", "#cb8b25", "#2c8c7f"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), layout="constrained")
    for method, color, offset in zip(methods, colors, [-.23, 0, .23]):
        selected = {r["condition"]: r for r in rows if r["method"] == method}
        for ax, metric in zip(axes, ["mean_chamfer_l1_mm", "volume_rmse_analytic_ml"]):
            values = [selected[c][metric] for c in conditions]
            ax.bar(np.arange(len(conditions))+offset, values, width=.22, label=method, color=color)
    for ax, title, ylabel in zip(axes, ["Full-surface geometry", "Volume vs analytic truth"],
                                  ["Unsquared Chamfer (mm; mean over objects)", "Volume RMSE (mL)"]):
        ax.set(title=title, ylabel=ylabel, xticks=range(4), xticklabels=labels)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=.2)
        ax.set_axisbelow(True)
    axes[0].legend(frameon=False)
    fig.suptitle("Synthetic development pilot: 2 objects × 4 matched conditions; descriptive only", fontsize=12)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
