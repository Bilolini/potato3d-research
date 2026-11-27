"""Post-hoc two-underside volume ambiguity diagnostic; not a primary endpoint."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

import numpy as np

from potato3d.io import sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists")
    rows = json.loads((args.run/"results.json").read_text())
    inputs = json.loads((args.run/"inputs.json").read_text())
    meta = {(i["object_id"], i["condition"]): i for i in inputs}
    groups = defaultdict(list)
    for row in rows:
        if row["status"] == "ok":
            groups[(meta[(row["object_id"], row["condition"])]["family_id"], row["condition"], row["method"])].append(row)
    bounds, excess = {}, defaultdict(list)
    for (family, condition, method), pair in groups.items():
        if len(pair) != 2 or abs(pair[0]["prediction_volume_ml"]-pair[1]["prediction_volume_ml"]) > 1e-9:
            raise ValueError("Requires complete twin pairs with identical volume predictions")
        bound = abs(pair[0]["analytic_target_volume_ml"]-pair[1]["analytic_target_volume_ml"])/2
        bounds[family] = bound
        mae = np.mean([r["volume_absolute_error_analytic_ml"] for r in pair])
        if mae < bound-1e-9:
            raise ValueError("Observed error violates the two-target lower bound")
        excess[(condition, method)].append(float(mae-bound))
    write_json(args.out, {"scope": "post-hoc explanatory diagnostic; not a new primary endpoint or calibrated uncertainty interval",
                         "results_sha256": sha256(args.run/"results.json"), "script_sha256": sha256(Path(__file__)),
                         "bound_definition": "For identical observed inputs and a shared deterministic volume prediction, mean absolute error across two equiprobable hidden volumes is at least half their absolute difference.",
                         "mean_two_profile_volume_mae_lower_bound_ml": float(np.mean(list(bounds.values()))),
                         "family_lower_bounds_ml": bounds,
                         "excess_mae_over_two_profile_bound": [{"condition": c, "method": m, "mean_excess_ml": float(np.mean(v))}
                                                               for (c, m), v in sorted(excess.items())]})


if __name__ == "__main__":
    main()
