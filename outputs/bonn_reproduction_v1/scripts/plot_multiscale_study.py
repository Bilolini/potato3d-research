"""Show sensor-error gains and genuine-feature costs from saved confirmation."""
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    report = json.loads(args.analysis.read_text())
    config = json.loads((args.run/"config.json").read_text())
    protocol = config["multiscale_protocol"]
    methods = ["symmetry", "symmetry_robust95", "symmetry_spatial", "symmetry_annular", "symmetry_multiscale"]
    names = ["Mirror max", "Fixed q95", "Local 32", "Annular (no gate)", "Boundary-gated multiscale"]
    colors = ["#727c8a", "#bc8a34", "#557aaa", "#aa628f", "#218c82"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), layout="constrained")
    for index, (method, name, color) in enumerate(zip(methods, names, colors)):
        for ax, conditions, metric in [(axes[0], ["outliers_2percent", "correlated_outlier_patch"], "hidden_chamfer_l1_mm"),
                                       (axes[1], ["genuine_wide_protrusion", "genuine_narrow_protrusion"], "feature_observed_to_surface_mean_mm")]:
            rows = [next(r for r in report["group_summary"] if r["condition"] == c and r["method"] == method and r["profile"] == "combined") for c in conditions]
            means = np.array([r[metric]["mean"] for r in rows])
            ci = np.array([r[metric]["ci95"] for r in rows])
            errors = np.maximum(np.vstack([means-ci[:, 0], ci[:, 1]-means]), 0)
            ax.errorbar(np.arange(2)+(index-2)*.13, means, yerr=errors, fmt="o", color=color, capsize=3, label=name)
    axes[0].set(title="Injected sensor errors", ylabel="Hidden unsquared Chamfer (mm)", xticks=[0, 1], xticklabels=["2% isolated spikes", "2% coherent patch"])
    axes[1].axhline(.5, color="#b75359", linestyle="--", linewidth=1, label="Preservation guardrail: 0.5 mm")
    axes[1].set(title="Genuine clean features", ylabel="Core point-to-surface error (mm)", xticks=[0, 1], xticklabels=["Wide protrusion", "Narrow protrusion"])
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=.2)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=3, frameon=False)
    fig.suptitle("Fresh synthetic confirmation: 12 independent families; 95% family-bootstrap intervals")
    fig.savefig(args.out/"tradeoffs.png", dpi=170)
    plt.close(fig)
    inputs = json.loads((args.run/"inputs.json").read_text())
    family = f"multiscale_confirmation_family_{protocol['visualize_family']:02d}"
    chosen = [i for i in inputs if i["family_id"] == family and i["condition"] in
              ["correlated_outlier_patch", "genuine_wide_protrusion", "genuine_narrow_protrusion"]]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.6), layout="constrained")
    for ax, case in zip(axes, chosen):
        folder = args.run/case["object_id"]/case["condition"]
        points = np.asarray(trimesh.load(folder/"partial.ply", process=False).vertices)
        reference = trimesh.load(folder/"reference.ply", force="mesh", process=False)
        predictions = {label: trimesh.load(folder/f"{method}.ply", force="mesh", process=False) for label, method in
                       [("local 32", "symmetry_spatial"), ("annular (no gate)", "symmetry_annular"), ("boundary-gated", "symmetry_multiscale")]}
        comparison(points, predictions, reference, args.out/case["condition"],
                   f"Fixed family 0 | {case['condition']} | synthetic confirmation", config["seed"])
        fitted = json.loads((folder/"symmetry_multiscale_parameters.json").read_text())
        flagged = np.array(fitted["suspect_point_indices"], dtype=int)
        control = np.array(case["feature_observation_indices_eval_only"] or case["injected_spike_indices_eval_only"], dtype=int)
        ax.scatter(*points[:, :2].T, color="#c4cfd7", s=4)
        if len(control):
            ax.scatter(*points[control, :2].T, facecolors="none", edgecolors="#c28a32", s=26, linewidths=.7)
        if len(flagged):
            ax.scatter(*points[flagged, :2].T, color="#b54b62", s=9)
        overlap = len(set(control) & set(flagged))
        ax.set(title=f"{case['condition']}\n{overlap}/{len(control)} labeled core/spike points flagged", xlabel="x (mm)", ylabel="y (mm)")
        ax.set_aspect("equal")
    fig.suptitle("Fixed confirmation family 0: gold = evaluation-only feature/spike labels; red = repaired points")
    fig.savefig(args.out/"fixed_family_controls.png", dpi=170)
    plt.close(fig)
