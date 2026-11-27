"""Check manually transcribed report values against frozen JSON evidence."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[2]
text = (ROOT/"course/REPORT.md").read_text()
real = json.loads((ROOT/"docs/bonn_real_v1_results.json").read_text())
names = {"Population ellipsoid": "population", "Fitted ellipsoid": "ellipsoid_0.15", "Training template": "template"}
count = 0
for line in text.splitlines():
    values = [x.strip() for x in line.strip().strip("|").split("|")]
    if len(values) == 5 and values[0] in {"Raw", "Depth component"} and values[1] in names:
        condition = "raw_valid" if values[0] == "Raw" else "depth_component"
        source = next(r for r in real["summary"] if r["condition"] == condition and r["method"] == names[values[1]])
        for value, key in zip(values[2:], ["mean_chamfer_l1_mm", "mean_fscore_5mm", "mean_raw_to_surface_mean_mm"]):
            if abs(float(value)-source[key]) > .00005:
                raise ValueError("Transcribed Bonn table value differs")
            count += 1
if count != 18:
    raise ValueError("Missing real-data table rows")
criteria = {}
for name in ["spatial", "multiscale"]:
    source = json.loads((ROOT/f"docs/{name}_confidence_results.json").read_text())
    checks = source["confirmation_criteria"]
    criteria[name] = {"checks": len(checks), "passed": sum(bool(c["passed"]) for c in checks)}
    for row in checks:
        for value in [row["mean"], *row["ci95"]]:
            if abs(value) < .00005:
                continue
            token = f"{value:.4f}"
            if token not in text:
                raise ValueError(f"Missing criterion value: {name} {token}")
for row in real["primary_checks"].values():
    for value in [row["mean_paired_delta"], *row["ci95_paired_delta"]]:
        if f"{value:.4f}" not in text:
            raise ValueError("Missing Bonn primary value")
record = {"bonn_table_values_checked": count, "synthetic_criterion_values_checked": True, "criteria": criteria,
          "bonn_primary_checks_passed": sum(c["pass"] for c in real["primary_checks"].values()),
          "bonn_full_hypothesis_passed": real["full_primary_hypothesis_passed"],
          "operation": "transcription check from frozen JSON, no metric computation"}
(ROOT/"course/evidence/report_number_checks.json").write_text(json.dumps(record, indent=2)+"\n")
print(json.dumps(record, indent=2))
