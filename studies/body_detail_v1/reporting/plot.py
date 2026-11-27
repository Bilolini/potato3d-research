"""Plot recorded confirmation rows without generating any inputs or predictions."""
import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("rows", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
with args.rows.open() as handle:
    rows = list(csv.DictReader(handle))
methods = ["mirror", "fixed_height_diagnostic", "clipped_q95", "body", "visible_detail", "reflected_detail"]
labels = ["Maximum-height mirror", "Mirror with clean height¹", "Clipped 95th-percentile mirror",
          "Fitted body", "Body + visible detail", "Body + reflected detail"]
colors = ["#687687", "#687687", "#687687", "#347160", "#0c7567", "#347160"]
panels = [("artifact", "remote_mm", ("apex",), "Remote underside motion\nRaised artifact at apex"),
          ("unilateral", "top_core_mm", ("flank", "edge"), "Upper feature error\nGenuine one-sided lobe"),
          ("bilateral", "lower_core_mm", ("flank", "edge"), "Underneath feature error\nGenuine bilateral lobe")]
fig, axes = plt.subplots(1, 3, figsize=(11.3, 3.65), sharey=True)
for axis, (condition, metric, sites, title) in zip(axes, panels):
    for y, method in enumerate(methods):
        subset = [r for r in rows if r["method"] == method and r["case"] == condition
                  and r["site"] in sites and r["sign"] == "1"]
        values = [np.mean([float(r[metric]) for r in subset if r["family"] == family])
                  for family in sorted({r["family"] for r in subset})]
        if len(values) < 2:
            raise ValueError("Expected a multi-family results file")
        axis.scatter(values, y+np.linspace(-.13, .13, len(values)), s=10, color=colors[y], alpha=.27)
        axis.scatter(np.mean(values), y, marker="D", s=38, color=colors[y])
    axis.set(title=title, xlabel="mm  (lower is better)", xlim=(-.2, None))
    axis.grid(axis="x", alpha=.18)
    axis.spines[["right","top","left"]].set_visible(False)
    axis.tick_params(axis="y",length=0)
axes[0].set_yticks(range(len(labels)), labels)
axes[0].invert_yaxis()
fig.subplots_adjust(left=.205, bottom=.26, top=.78, right=.985, wspace=.25)
fig.suptitle("How a local depth change affects the reconstructed potato", fontsize=16, y=.985)
fig.text(.02,.065,"Dots show individual confirmation families. Diamonds show means. Feature panels average raised flank and near-silhouette cases.",fontsize=9)
fig.text(.02,.014,"¹ Mechanism diagnostic with access to the paired unperturbed scan height.",fontsize=9)
fig.savefig(args.output, dpi=175, facecolor="white")
