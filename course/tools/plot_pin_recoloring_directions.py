"""Plot paired directions from the archived CoRe++ and TripoSR potato table."""

import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


COURSE = Path(__file__).resolve().parents[1]
TABLE = COURSE.parent / "studies/regional_shape_v1/triposr_pin_multituber/per_potato.csv"
MODELS = (("corepp", "CoRe++"), ("triposr", "TripoSR"))
CONTROLS = (("mean", "Mean of three peel patches"), ("strongest", "Strongest peel patch"))
STYLES = {
    "pin": ("#dcefe9", "#125548", "Pin"),
    "peel": ("#f8e8d7", "#773a12", "Peel"),
    "tie": ("#eceef2", "#394759", "Tie"),
}


def plot(output):
    with TABLE.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    if len(rows) != 10 or len({r["tuber"] for r in rows}) != 10 or any(r["failure"] for r in rows):
        raise ValueError("Expected ten complete paired results")

    fig, ax = plt.subplots(figsize=(7.25, 4.15))
    fig.subplots_adjust(left=.045, right=.97, bottom=.055, top=.84)
    ax.set(xlim=(0, 6.6), ylim=(-.35, 10.8))
    ax.set_axis_off()
    ink = "#182431"
    fig.text(.045, .94, "Which edit moved the predicted surface farther?",
             color=ink, fontsize=15, fontweight="bold")
    fig.text(.045, .885, "Both models scored the same ten development frames.",
             color="#4e5a67", fontsize=9.5)

    ax.text(0, 9.82, "Potato", color=ink, fontweight="bold", fontsize=9, va="center")
    for (control, heading), start in zip(CONTROLS, (1.25, 4.05), strict=True):
        width = 1.12
        spacing = .14
        midpoint = start + width + spacing / 2
        ax.text(midpoint, 10.55, heading, color=ink, fontweight="bold", fontsize=10,
                ha="center", va="center")
        ax.hlines(10.2, start, start + 2 * width + spacing, linewidth=.6, colors="#a5adb8")
        for i, (model, label) in enumerate(MODELS):
            left = start + i * (width + spacing)
            ax.text(left + width / 2, 9.82, label, color=ink, fontweight="bold",
                    fontsize=9, ha="center", va="center")
            for index, row in enumerate(rows):
                y = 9.0 - index * .98
                if control == "mean" and i == 0:
                    ax.text(0, y, row["tuber"], color=ink, fontsize=9, va="center")
                fill, text, name = STYLES[row[f"{model}_{control}_direction"]]
                ax.add_patch(Rectangle((left, y - .36), width, .72, facecolor=fill, linewidth=0))
                ax.text(left + width / 2, y, name, ha="center", va="center",
                        color=text, fontsize=9, fontweight="medium")
    fig.savefig(output, dpi=350, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=COURSE / "figures/pin_recoloring_directions.png")
    plot(parser.parse_args().output)
