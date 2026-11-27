"""Plot two archived fused clouds with frozen intermediate-depth and SfM labels."""

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np


STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
DIAGNOSTIC = STUDY.parent / "depth_consistency_diagnostic_v1"
CLOUDS = ROOT / "outputs/sam2_raft_end_to_end_v1/predicted"
POTATOES = ("2R1-9", "R10-10")
DEPTH_STYLES = {
    "unobservable": ("No observation", "#677786", "o", 9),
    "consistent": ("Agreement", "#128073", "o", 12),
    "potentially_occluded": ("Possible occlusion", "#7956a2", "D", 20),
    "contradiction": ("Contradiction", "#ca541e", "^", 29),
}
SFM_STYLES = {
    False: ("Within 2 mm", "#226b8c", "o", 10),
    True: ("Over 2 mm", "#bf3e53", "o", 12),
}
INK = "#162736"


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def verified(path, sha):
    if digest(path) != sha:
        raise ValueError(f"Archived file changed: {path}")
    return path


def rows_by_tuber(record):
    return {row["tuber"]: row for row in record["rows"]}


def load_examples():
    result = read(STUDY / "results.json")
    frozen = read(verified(STUDY / "frozen_classifications.json", result["frozen_classifications_sha256"]))
    labels = read(verified(DIAGNOSTIC / "results.json", result["label_manifest_sha256"]))
    scores = read(verified(DIAGNOSTIC / "frozen_scores.json", labels["frozen_scores_sha256"]))
    rows = [rows_by_tuber(record) for record in (result, frozen, labels, scores)]
    examples = []
    for tuber in POTATOES:
        row, freeze, label, score = (table[tuber] for table in rows)
        if freeze["cloud_sha256"] != score["cloud_sha256"]:
            raise ValueError(f"Classification and label cloud archives disagree for {tuber}")
        with np.load(verified(STUDY / "classifications" / f"{tuber}.npz", freeze["classification_sha256"]),
                     allow_pickle=False) as file:
            index, codes = file["fused_index"], file["category"]
        with np.load(verified(DIAGNOSTIC / "scores" / f"{tuber}.npz", score["scores_sha256"]),
                     allow_pickle=False) as file:
            outer_index = file["fused_index"]
            np.testing.assert_array_equal(index, outer_index[file["usable_views"] == 0])
        with np.load(verified(DIAGNOSTIC / "labels" / f"{tuber}.npz", label["labels_sha256"]),
                     allow_pickle=False) as file:
            np.testing.assert_array_equal(outer_index, file["fused_index"])
            inaccurate = file["inaccurate"][np.searchsorted(outer_index, index)]
        with np.load(verified(CLOUDS / f"{tuber}.npz", freeze["cloud_sha256"]), allow_pickle=False) as file:
            cloud = file["D"]
        categories = np.array([frozen["category_codes"][str(code)] for code in codes])
        for category in DEPTH_STYLES:
            match = categories == category
            if match.sum() != row[f"{category}_count"] or inaccurate[match].sum() != row[f"{category}_errors"]:
                raise ValueError(f"Plotted points do not match the archived table for {tuber}")
        mask = np.ones(len(cloud), dtype=bool)
        mask[index] = False
        examples.append((row, cloud, mask, index, categories, inaccurate))
    return examples, result["ordering"]["higher"], result["paired_potatoes"]


def project(cloud):
    """Fixed orthographic projection of the archived center-camera coordinates."""
    yaw, pitch = np.deg2rad([15, 22])
    right = [np.cos(yaw), 0, -np.sin(yaw)]
    up = [np.sin(pitch)*np.sin(yaw), -np.cos(pitch), np.sin(pitch)*np.cos(yaw)]
    plane = cloud @ np.array([right, up]).T
    return plane - (plane.max(axis=0) + plane.min(axis=0)) / 2


def draw(ax, context, points, values, styles):
    ax.scatter(*context.T, s=1.25, c="#8b9da9", alpha=.15, linewidths=0)
    for group, (_, color, marker, size) in styles.items():
        ax.scatter(*points[values == group].T, s=size, c=color, marker=marker, linewidths=0)


def legend(ax, styles):
    handles = [Line2D([], [], linestyle="", marker=marker, markersize=6,
                      markerfacecolor=color, markeredgecolor="none", label=label)
               for label, color, marker, _ in styles.values()]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, -.03),
              ncols=2, fontsize=9, frameon=False)


def plot(output):
    examples, higher, paired = load_examples()
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 7.0))
    fig.subplots_adjust(left=.035, right=.965, bottom=.14, top=.78, hspace=.30, wspace=.16)
    fig.text(.055, .948, "Intermediate depth and SfM error", color=INK, fontsize=19, fontweight="bold")
    fig.text(.055, .904, "Contrasting development examples • faint points show the rest of the frozen fused cloud",
             color="#475969", fontsize=10)
    fig.text(.250, .845, "Intermediate depth observation", ha="center", color=INK, fontsize=12, fontweight="bold")
    fig.text(.750, .845, "SfM error of the same points", ha="center", color=INK, fontsize=12, fontweight="bold")

    # Each row uses identical projected coordinates, bounds and scale in both panels.
    planes = [project(example[1]) for example in examples]
    extent = np.maximum.reduce([np.abs(plane).max(axis=0) for plane in planes]) + [3., 5.]
    for (row, _, context, index, categories, inaccurate), coords, pair in zip(examples, planes, axes, strict=True):
        for ax in pair:
            ax.set(xlim=(-extent[0], extent[0]), ylim=(-extent[1], extent[1]), aspect="equal")
            ax.set_axis_off()
        point_xy = coords[index]
        draw(pair[0], coords[context], point_xy, categories, DEPTH_STYLES)
        draw(pair[1], coords[context], point_xy, inaccurate, SFM_STYLES)
        pair[0].set_title(f"{row['tuber']}   ·   {row['points']:,} previously uncheckable", color=INK, fontsize=10, pad=2)
        pair[1].set_title(f"{row['tuber']}   ·   {row['contradiction_errors']}/{row['contradiction_count']} contradictions over 2 mm",
                          color=INK, fontsize=10, pad=2)
    legend(axes[1, 0], DEPTH_STYLES)
    legend(axes[1, 1], SFM_STYLES)
    fig.text(.5, .028, f"Contradictions were more often inaccurate than agreements on {higher}/{paired} comparable potatoes.",
             color="#475969", fontsize=9, ha="center")
    fig.savefig(output, dpi=220, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=STUDY / "contrasting_examples.png")
    plot(parser.parse_args().output)
