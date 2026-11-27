"""Plot saved confirmation outcomes and fixed-family confidence examples."""
import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path.cwd()/".cache/matplotlib"))
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
    protocol = config["spatial_protocol"]
    conditions = protocol["conditions"]
    labels = ["Clean", "2 mm\njitter", "2% isolated\nspikes", "Missing\npatch", "Belt error\n+3 mm", "Belt error\n−3 mm", "2% coherent\nbad patch"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), layout="constrained")
    for ax, metric, title, unit in zip(axes, ["hidden_chamfer_l1_mm", "volume_absolute_error_analytic_ml"],
                                      ["Hidden-surface error difference", "Absolute-volume error difference"], ["mm", "mL"]):
        selected = {r["condition"]: r for r in report["paired_comparisons"] if
                    r["candidate"] == "symmetry_spatial" and r["baseline"] == "symmetry_robust95" and
                    r["metric"] == metric and r["profile"] == "combined"}
        means = np.array([selected[c]["mean"] for c in conditions], dtype=float)
        intervals = [selected[c]["ci95"] for c in conditions]
        errors = np.array([[m-ci[0], ci[1]-m] for m, ci in zip(means, intervals)]).T
        ax.axhline(0, color="#6a7480", linewidth=1, linestyle="--")
        ax.errorbar(np.arange(len(conditions)), means, yerr=errors, color="#287f91", fmt="o", capsize=4)
        ax.set(title=title, ylabel=f"Spatial − q95 ({unit}); negative favors spatial", xticks=range(len(conditions)), xticklabels=labels)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=.2)
    fig.suptitle("Independent synthetic confirmation: paired differences with 95% family-bootstrap intervals")
    fig.savefig(args.out/"paired_differences.png", dpi=170)
    plt.close(fig)
    family = protocol["visualize_family"]
    for warp in protocol["underside_warps"]:
        pid = f"spatial_confirmation_family_{family:02d}_warp_{warp:g}"
        for condition in ["clean", "outliers_2percent", "correlated_outlier_patch"]:
            folder = args.run/pid/condition
            points = np.asarray(trimesh.load(folder/"partial.ply", process=False).vertices)
            reference = trimesh.load(folder/"reference.ply", force="mesh", process=False)
            predictions = {label: trimesh.load(folder/f"{method}.ply", force="mesh", process=False)
                           for label, method in [("mirror max", "symmetry"), ("fixed q95", "symmetry_robust95"),
                                                 ("spatial confidence", "symmetry_spatial")]}
            comparison(points, predictions, reference, args.out/pid/condition,
                       f"{pid} | {condition} | independent synthetic confirmation", config["seed"])
    pid = f"spatial_confirmation_family_{family:02d}_warp_0"
    inputs = json.loads((args.run/"inputs.json").read_text())
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.5), layout="constrained")
    for ax, condition in zip(axes, ["clean", "outliers_2percent", "correlated_outlier_patch"]):
        folder = args.run/pid/condition
        points = np.asarray(trimesh.load(folder/"partial.ply", process=False).vertices)
        parameters = json.loads((folder/"symmetry_spatial_parameters.json").read_text())
        meta = next(i for i in inputs if i["object_id"] == pid and i["condition"] == condition)
        suspect = np.array(parameters["suspect_point_indices"], dtype=int)
        spikes = np.array(meta["injected_spike_indices_eval_only"], dtype=int)
        ax.scatter(*points[:, :2].T, c="#c6d2d9", s=3, label="observations")
        if len(spikes):
            ax.scatter(*points[spikes, :2].T, facecolors="none", edgecolors="#da9131", s=22, linewidths=.6, label="injected spikes (eval only)")
        if len(suspect):
            ax.scatter(*points[suspect, :2].T, c="#c15161", s=9, label="flagged by spatial method")
        ax.set(title=f"{condition}\n{len(suspect)} flagged; {len(set(spikes)-set(suspect))} spikes missed",
               xlabel="x (mm)", ylabel="y (mm)")
        ax.set_aspect("equal")
    handles, names = axes[-1].get_legend_handles_labels()
    fig.legend(handles, names, loc="outside lower center", ncol=3, frameon=False)
    fig.suptitle("Fixed confirmation family 0: observation confidence and known injected spikes")
    fig.savefig(args.out/"confidence_examples.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    main()
