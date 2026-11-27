"""Object-level real-data comparison; no pooling frames as independent samples."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    rows = json.loads((args.run/"results.json").read_text())
    ids = sorted({r["object_id"] for r in rows}); methods = sorted({r["method"] for r in rows})
    figure, axes = plt.subplots(2, 2, figsize=(13, 7), sharex=True)
    for col, condition in enumerate(["raw_valid", "depth_component"]):
        for row, metric in enumerate(["chamfer_l1_mm", "fscore_5mm"]):
            axis = axes[row, col]
            for method in methods:
                lookup = {r["object_id"]: r[metric] for r in rows if r["status"] == "ok" and r["method"] == method and r["condition"] == condition}
                axis.plot(np.arange(len(ids)), [lookup.get(pid, np.nan) for pid in ids], ".-", label=method)
            axis.set_title(condition); axis.set_ylabel("Unsquared Chamfer (mm)" if row == 0 else "F-score at 5 mm")
            axis.grid(alpha=.2)
    for axis in axes[-1]:
        axis.set_xticks(np.arange(len(ids)), ids, rotation=45)
    axes[0, 0].legend(fontsize=8)
    figure.suptitle("Bonn laboratory fruit: one fixed view per object, supplied pose, no reference alignment")
    figure.tight_layout(); figure.savefig(args.out/"object_metrics.png", dpi=180); plt.close(figure)
