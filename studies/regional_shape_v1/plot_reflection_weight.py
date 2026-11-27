"""Plot absolute cohort error and paired per-tuber changes over reflection weights."""
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


def plot_reflection_weight(result, path):
    weights = result["candidate_weights"]
    pooled = result["pooled_nominal_mae_curve_mm"]
    selected = result["out_of_fold_scores_mm"]["aligned"]
    folds = [r for r in result["pairs"] if r["fold"] is not None]
    fig, (cohort, tubers) = plt.subplots(1, 2, figsize=(10.8, 4.45), layout="constrained")

    cohort.plot(weights, pooled, color="#175b76", marker="o", label="Pooled weight curve")
    cohort.axhline(selected, color="#a64127", linestyle="--", label=f"Out-of-fold mean ({selected:.3f} mm)")
    cohort.set_title("Equal-tuber mean")
    cohort.set_ylabel("Underside MAE (mm)")
    cohort.legend(loc="upper left", frameon=False, fontsize=9)

    colors = plt.get_cmap("tab10").colors
    for row, color in zip(folds, colors, strict=False):
        fold = row["fold"]
        curve = np.asarray(fold["all_weight_mae_curve_mm"])
        delta = curve - curve[0]
        tubers.plot(weights, delta, color=color, linewidth=1.3, alpha=.85, label=row["object_id"])
        tubers.scatter(fold["selected_weight"], fold["scores_mm"]["aligned_minus_body"],
                       color=color, edgecolor="white", linewidth=.6, zorder=3, s=43)
    tubers.axhline(0, linestyle=":", color="#444444", linewidth=1)
    tubers.set_title("Paired change by tuber")
    tubers.set_ylabel("MAE change from body (mm)")
    tubers.legend(loc="upper left", frameon=False, ncols=2, fontsize=8)

    for ax in (cohort, tubers):
        ax.set_xlabel("Reflection weight")
        ax.set_xticks(weights, ["0", "0.25", "0.5", "0.75", "1"])
        ax.grid(axis="y", alpha=.22)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Reflection strength on seven development tubers", fontweight="bold")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
