"""Plot CoRe++ pin recoloring results from the two archived potato-level tables."""

import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import numpy as np


HERE = Path(__file__).resolve().parent


def read_table(path, expected_rows):
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len({row["potato"] for row in rows}) != len(rows) or len(rows) != expected_rows:
        raise ValueError(f"Unexpected potato roster in {path}")
    if any(row["failure"] for row in rows):
        raise ValueError(f"Expected a complete score for each potato in {path}")
    return rows


def style_axis(ax, title):
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", pad=9)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#6b7480")
    ax.tick_params(length=3.5, width=0.7, pad=3)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.set_axisbelow(True)
    ax.grid(axis="y", color="#e5e8ec", linewidth=0.6)
    ax.axhline(0, color="#68717c", linewidth=1, linestyle=(0, (4, 3)), zorder=2)


def plot(fresh, development, output):
    matplotlib.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 8.5, "text.color": "#182431",
        "axes.labelcolor": "#182431", "xtick.color": "#182431", "ytick.color": "#182431",
        "axes.linewidth": 0.7,
    })
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.65, 3.28), layout="constrained",
                               gridspec_kw={"wspace": 0.12})

    effects = sorted(float(row["primary_mm"]) for row in fresh)
    a.scatter(range(1, len(effects) + 1), effects, s=24, c="#176580", edgecolors="white", linewidths=0.45, zorder=3)
    a.set(xlim=(0, 30), xticks=[1, 5, 10, 15, 20, 25, 29], xlabel="Potato rank by displacement contrast",
          ylabel="Pin − mean peel displacement (mm)")
    style_axis(a, f"A   Fresh potatoes (n = {len(fresh)})")

    positions = {row["potato"]: (float(row["pin_displacement_median_mm"]), float(row["pin_change_mm"]))
                 for row in development}
    labels = {"3R5-2": ("#176580", (-10, -14), "right"), "R8-2": ("#a33b36", (-10, 12), "right")}
    others = np.array([xy for potato, xy in positions.items() if potato not in labels])
    b.scatter(others[:, 0], others[:, 1], s=24, c="#626c76", edgecolors="white", linewidths=0.45, zorder=3)
    for potato, (color, offset, align) in labels.items():
        x, y = positions[potato]
        b.scatter(x, y, s=34, c=color, edgecolors="white", linewidths=0.5, zorder=4)
        b.annotate(potato, (x, y), xytext=offset, textcoords="offset points", ha=align, va="center",
                   color=color, fontweight="bold", fontsize=8.5,
                   arrowprops={"arrowstyle": "-", "color": color, "lw": 0.7, "shrinkA": 2, "shrinkB": 5})
    b.set(xlim=(-0.071, 2.18), ylim=(-0.83, 0.40), xlabel="Pin-induced surface displacement (mm)",
          ylabel="Change in SfM reference error (mm)")
    b.text(0.045, 0.045, "Negative = improvement", transform=b.transAxes, fontsize=7.5, color="#4e5a67")
    style_axis(b, f"B   Development potatoes (n = {len(development)})")

    fig.savefig(output, dpi=400, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "corepp_pin_findings.png")
    args = parser.parse_args()
    plot(
        read_table(HERE / "corepp_pin_confirmation/per_potato.csv", 29),
        read_table(HERE / "corepp_pin_accuracy/per_potato.csv", 10),
        args.output,
    )
