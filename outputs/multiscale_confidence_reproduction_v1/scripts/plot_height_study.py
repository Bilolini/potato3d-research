"""Render the predetermined height study from saved analysis and mesh artifacts."""
import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path.cwd()/".cache"/"matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import trimesh

from potato3d.visualize import comparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    report = json.loads(args.analysis.read_text())
    config = json.loads((args.run/"config.json").read_text())
    protocol = config["development_protocol"]
    conditions = protocol["conditions"]
    labels = ["Clean", "Depth jitter\n2 mm SD", "2% positive\noutliers", "Missing\npatch", "Belt error\n+3 mm", "Belt error\n−3 mm"]
    methods = protocol["methods"]
    colors = ["#3f68a0", "#d29a2c", "#657080", "#a85b9a", "#209182"]
    names = ["Ellipsoid", "Belt-closed hull", "Mirror max", "Mirror q95 + floor", "Mirror q95 + cap clip"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.7), layout="constrained")
    for index, (method, color, name) in enumerate(zip(methods, colors, names)):
        selected = {r["condition"]: r for r in report["group_summary"] if r["method"] == method and r["profile"] == "combined"}
        for ax, metric in zip(axes, ["hidden_chamfer_l1_mm", "volume_absolute_error_analytic_ml"]):
            means = np.array([selected[c][metric]["mean"] for c in conditions], dtype=float)
            intervals = [selected[c][metric]["ci95"] for c in conditions]
            errors = (np.array([[m-ci[0], ci[1]-m] for m, ci in zip(means, intervals)]).T
                      if all(ci is not None for ci in intervals) else None)
            ax.errorbar(np.arange(len(conditions))+(index-2)*.13, means, yerr=errors,
                        fmt="o", markersize=4, capsize=2.5, color=color, label=name, linewidth=1)
    for ax, title, ylabel in zip(axes, ["Hidden-surface geometry", "Absolute volume error"],
                                  ["Unsquared Chamfer (mm)", "Error vs analytic volume (mL)"]):
        ax.set(title=title, ylabel=ylabel, xticks=range(len(conditions)), xticklabels=labels)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=.2)
        ax.set_axisbelow(True)
    handles, legend_labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="outside lower center", ncol=3, frameon=False)
    fig.suptitle("Fresh synthetic development: 12 families × 2 ambiguous undersides; family-bootstrap 95% intervals")
    fig.savefig(args.out/"performance.png", dpi=170)
    plt.close(fig)
    # Fixed family specified in the sealed protocol, never selected by score.
    for pid in [protocol["visualize_object_id"], "family_00_warp_1.8"]:
        for condition in ["clean", protocol["primary_condition"]]:
            folder = args.run/pid/condition
            points = np.asarray(trimesh.load(folder/"partial.ply", process=False).vertices)
            reference = trimesh.load(folder/"reference.ply", force="mesh", process=False)
            predictions = {label: trimesh.load(folder/f"{method}.ply", force="mesh", process=False)
                           for label, method in [("mirror max", "symmetry"), ("q95 + floor", "symmetry_height95"),
                                                 ("q95 + cap clip", "symmetry_robust95")]}
            comparison(points, predictions, reference, args.out/pid/condition,
                       f"{pid} | {condition} | synthetic development only", config["seed"])


if __name__ == "__main__":
    main()
