"""Render the verified frozen results as the study report."""

import common as c


def number(x, unit="", signed=False):
    return "—" if x is None else f"{x:+.2f}{unit}" if signed else f"{x:.2f}{unit}"


def ci(pair, unit="", decimals=2):
    if pair["interval_95"] is None:
        return "—"
    return " to ".join(f"{x:+.{decimals}f}" for x in pair["interval_95"]) + unit


def paired_table(traits):
    lines = [
        "| Trait | Comparison | Pairs | First MAE | Baseline MAE | Paired change | 95% interval | Wins / ties / losses |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, info in traits.items():
        unit = " g" if name == "weight" else " mL"
        for key, pair in info["paired"].items():
            line = [
                name.capitalize(), key.replace("-", " − "), f"{pair['n']}/30",
                number(pair["first_mean"], unit), number(pair["baseline_mean"], unit),
                number(pair["change"], unit, True), ci(pair, unit),
                f"{pair['wins']} / {pair['ties']} / {pair['losses']}",
            ]
            lines.append("| " + " | ".join(line) + " |")
    return "\n".join(lines)


def trait_table(traits):
    label = {"A": "Provided center", "B": "SAM 2 center", "C": "Provided RAFT fusion", "D": "SAM 2 RAFT fusion"}
    lines = ["| Arm | Weight scored and MAE | Volume scored and MAE |", "|---|---:|---:|"]
    for key, text in label.items():
        w, v = (traits[name]["methods"][key] for name in ("weight", "volume"))
        lines.append(f"| {key} · {text} | {w['n']}/30 · {number(w['mae'], ' g')} | {v['n']}/30 · {number(v['mae'], ' mL')} |")
    return "\n".join(lines)


def geometry_tables(geometry):
    lines = [
        "| Arm | Coverage scored | Reference covered | Covered at equal count | Output points >2 mm |",
        "|---|---:|---:|---:|---:|",
    ]
    for method, info in geometry["methods"].items():
        fields = [number(100*x["mean"] if x["mean"] is not None else None, "%")
                  for x in (info["coverage_fraction"], info["equal_coverage_fraction"], info["far_fraction"])]
        lines.append(f"| {method} | {info['coverage_fraction']['n']}/10 | " + " | ".join(fields) + " |")
    lines.extend([
        "",
        "| Geometry comparison | Metric | Pairs | Change (percentage points) | 95% interval |",
        "|---|---|---:|---:|---:|",
    ])
    labels = {"coverage_fraction":"Coverage", "equal_coverage_fraction":"Equal-count coverage", "far_fraction":"Far points"}
    for key, records in geometry["paired_percentage_points"].items():
        for metric, pair in records.items():
            digits = 3 if key == "D-C" and metric == "coverage_fraction" else 2
            lines.append(f"| {key.replace('-', ' − ')} | {labels[metric]} | {pair['n']}/10 | "
                         f"{number(pair['change'], signed=True)} | {ci(pair, decimals=digits)} |")
    return "\n".join(lines)


def read_outcome(pair, unit):
    low, high = pair["interval_95"] or (None, None)
    if not pair["n"]:
        return "There were no comparable predictions for this endpoint."
    conclusion = "The interval includes zero." if low <= 0 <= high else (
        "The paired interval favors fusion." if high < 0 else "The paired interval favors the baseline."
    )
    return (f"Fusion MAE was {number(pair['first_mean'], unit)} versus {number(pair['baseline_mean'], unit)} at center "
            f"on {pair['n']}/30 paired potatoes, a change of {number(pair['change'], unit, True)} "
            f"(95% interval {ci(pair, unit)}). {conclusion}")


def failures_text():
    failures = c.csv_rows(c.STUDY / "failures.csv")
    if not failures:
        return "No mask-depth support, registration or scoring failures occurred."
    grouped = {}
    for row in failures:
        key = (row["tuber"], row["analysis"])
        reason = f"{row['stage']}: {row['reason']}"
        if row["source"]:
            reason = f"{row['source']} → {row['target']} {reason}" if row["target"] else f"frame {row['source']} {reason}"
        grouped.setdefault(key, []).append(reason)
    lines = ["| Potato | Cohort | Failure detail |", "|---|---|---|"]
    lines.extend(f"| {tuber} | {cohort} | {' · '.join(reasons)} |"
                 for (tuber, cohort), reasons in grouped.items())
    return "\n".join(lines)


def write_report():
    result = c.prep.read_json(c.STUDY / "results.json")
    traits, geometry = result["traits"], result["geometry"]
    groups = result["coverage_tracking_and_runtime"]
    for tag, filename in (("geometry_scores_sha256", "geometry_per_potato.csv"), ("trait_scores_sha256", "traits_per_potato.csv")):
        if result[tag] != c.prep.digest(c.STUDY / filename):
            raise ValueError(f"Results and table hash differ: {filename}")
    full_geo, full_traits = groups["geometry"]["usable_geometry"]["D"], groups["traits"]["usable_geometry"]["D"]
    coverage = geometry["paired_percentage_points"]["D-C"]["coverage_fraction"]
    coverage_equal = geometry["paired_percentage_points"]["D-C"]["equal_coverage_fraction"]
    far = geometry["paired_percentage_points"]["D-C"]["far_fraction"]
    entry = groups["all"]
    gscore = geometry["methods"]["D"]["coverage_fraction"]["n"]
    weight, volume = (traits[name]["paired"]["D-B"] for name in ("weight", "volume"))
    weight_mask = traits["weight"]["paired"]["D-C"]
    volume_mask = traits["volume"]["paired"]["D-C"]
    area = geometry["methods"]
    original = c.prep.read_json(c.TRAIT_STUDY / "results.json")["runtime"]["val"]["incremental_s_vs_A"]["D"]
    runtime_lines = [
        "| Cohort | Tracking through center (s) | Extra tracking through upper (s) | Additional depth, RGB, RAFT and fused feature (s) | Total increment D over B (s) |",
        "|---|---:|---:|---:|---:|",
    ]
    for key in ("geometry", "traits", "all"):
        data = groups[key]
        total, ext = data["incremental_D_minus_B_wall_s"], data["timed_components"]["tracked_extension_s"]
        center = data["timed_components"]["tracking_through_center_s"]
        runtime_lines.append(f"| {key.capitalize()} ({data['n']}) | {center:.2f} | {ext:.2f} | {total-ext:.2f} | {total:.2f} |")
    fallback = result["fallback_ids"]
    fallback_lines = []
    if fallback:
        fallback_lines.append("The operational policy used D when available and B on " + ", ".join(fallback) + ".")
        for name, trait in traits.items():
            p = trait["fallback_vs_B"]
            unit = " g" if name == "weight" else " mL"
            fallback_lines.append(f"For {name}, this fallback policy had {number(p['first_mean'], unit)} MAE versus "
                                  f"{number(p['baseline_mean'], unit)} for B on {p['n']}/30 pairs, with a change of "
                                  f"{number(p['change'], unit, True)} (95% interval {ci(p, unit)}).")
    else:
        fallback_lines.append("No center fallback was used. Available fusion predictions constitute the primary D result.")
    runtime_table = "\n".join(runtime_lines)
    fallback_text = " ".join(fallback_lines)
    reader_fix = ""
    if (c.STUDY / "mask_reader_correction.json").is_file():
        reader_fix = ("\nThe first reconstruction attempt stopped on the named entry-prompt array. "
                      "The corrected reader preserved the frozen inputs and verified tracking outputs. "
                      "[Reader correction receipt](mask_reader_correction.json)\n")
    text = f"""# One peel click through SAM 2 and RAFT fusion

- **Completion.** SAM 2-mask RAFT fusion produced a cloud on **{full_geo}/10 geometry** and **{full_traits}/30 trait** development potatoes. Every center replay is accounted for below.
- **Surface.** Among **{coverage['n']}/10** geometry pairs, SAM 2 fusion covered **{number(coverage['first_mean'], '%')}** of the SfM surface within 2 mm versus **{number(coverage['baseline_mean'], '%')}** with provided-mask fusion. The change was **{number(coverage['change'], signed=True)} percentage points** (95% interval **{ci(coverage, decimals=3)}**). At equal point count it was **{number(coverage_equal['change'], signed=True)} points** (**{ci(coverage_equal)}**). Far points changed by **{number(far['change'], signed=True)} points** (**{ci(far)}**).
- **Traits.** Weight, the primary comparison. {read_outcome(weight, ' g')} Water-displacement volume. {read_outcome(volume, ' mL')}

[Per-potato geometry](geometry_per_potato.csv) · [Per-potato traits](traits_per_potato.csv) · [Full-precision results](results.json)

## Frozen inputs and end-to-end replay

The **40 previously studied development potatoes** used the exact coached repeat clicks and the same lower, center and upper frames as the two fusion studies. The ten geometry IDs were held separate from the remaining 30 trait IDs throughout. All 45 SAM 2 confirmation potatoes and reserved cohorts remained closed. [Roster and trait coefficients](frame_manifest.json) · [Frozen protocol](protocol.md) · [Coached repeat](../sam2_human_prompt_v1/repeat_01/report.md)

The extended-clip probe changed archived center masks by 7 pixels on R6-5 and by 2 pixels on 3R3-8. SAM 2 normalizes object-pointer time offsets using the declared clip length up to its pointer cap. We therefore kept the original length through center, then continued the same in-memory track over the later frames. That retained the same click, checkpoint, preprocessing and state. The final run reproduced **{entry['center_exact_replays']}/40** archived center masks pixel for pixel and returned tracks through upper on **{entry['tracking_returned_through_upper']}/40**, with **{entry['skips']}** skips. The post-reconstruction audit found **{entry['upper_potato_matches']}/40** correct upper masks by IoU ≥ 0.5, **{len(entry['tracks_with_empty_frames'])}** tracks with empty frames, **{len(entry['tracks_with_loss'])}** target losses and **{len(entry['tracks_with_pin_takeover'])}** pin takeovers after first matching the potato. [Center replay](tracking_replay.csv) · [State transitions](tracking_audit.csv) · [Frame-by-frame audit](tracking_by_frame.csv)
{reader_fix}

The predicted-mask arm derived each histogram depth gate and RAFT crop from the propagated mask and recomputed all bidirectional flow and adjacent rigid fits. Its inputs were the propagated masks, original full-scene RGB and raw depth, released intrinsics, and measured tuber thickness (`x3_depth_mm`). Both mask arms retain the measured-thickness dependency. Provided masks, segmented PLYs and provided-mask poses were used for the separate baseline replay or audit. Only the three selected clouds contributed fused points. [Input ledger](predicted_input_ledger.json) · [Depth support](depth_support_by_frame.csv) · [Per-link RAFT results](registration_links.csv)

## Surface scoring on the ten geometry potatoes

The geometry comparison used the same released center-to-SfM pose in every arm, on the scoring side only, and the archived 1 mm scoring voxel grid, 50,000 area-uniform reference samples, 2 mm cutoff and ten equal-count repeats. The provided center and RAFT baselines replayed archived point clouds, full-count scores and original equal-count scores on **{geometry['provided_geometry_replay_n']}/10**. The new equal-count comparison uses the smallest available cloud across these four conditions per potato. The SAM 2-fused arm scored against SfM on **{gscore}/10**. [Archived geometry study](../raft_fusion_geometry_v1/report.md) · [Geometry table](geometry_per_potato.csv)

{geometry_tables(geometry)}

The intervals resample whole potatoes within each comparable pair set, using unrounded errors and coverage. Relative to its own center, SAM 2 fusion newly covered {number(area['D']['new_area_mm2']['mean'], ' mm²')} and lost {number(area['D']['lost_area_mm2']['mean'], ' mm²')} on average. With provided masks, fusion newly covered {number(area['C']['new_area_mm2']['mean'], ' mm²')} and lost {number(area['C']['lost_area_mm2']['mean'], ' mm²')} relative to its corresponding center. [Per-potato new and lost area](geometry_per_potato.csv)

## Weight and volume on the 30 trait potatoes

A and B used the frozen center coefficients, and C and D used the frozen RAFT coefficients from the 117 common training potatoes. There was no refit. Center features used raw accepted points and fused features used 1 mm voxel centroids in the center camera. Both used XY hull area times the belt-relative height proxy. Archived provided-mask weight and volume predictions replayed within 1e-7 of their stored values before outcomes were joined. Measured weight includes the tack. [Earlier trait comparison](../raft_fusion_traits_v1/report.md) · [Predictions before outcome join](predictions_before_targets.json)

{trait_table(traits)}

{paired_table(traits)}

Paired estimates use only the indicated complete pairs, with the cohort denominator shown separately. Negative change is lower absolute error. Both suites use the frozen 10,000-draw tuber bootstrap. {fallback_text}

Replacing the provided masks throughout fusion reduced observed weight MAE by {number(-weight_mask['change'], ' g')} on these {weight_mask['n']} potatoes (SAM 2 minus provided, 95% interval {ci(weight_mask, ' g')}). The corresponding volume change was {number(volume_mask['change'], ' mL', True)} ({ci(volume_mask, ' mL')}). These comparisons isolate the mask source within fusion. The weight and volume intervals for fusion versus center from the same click both include zero.

## Failures and incremental CPU runtime

{failures_text()}

The table sums timed local CPU-process wall components across potatoes. Tracking used two concurrent processes. The time through center includes initial loading of the full RGB clip, so the post-center increment excludes extra clip loading already counted there. It includes additional support reconstruction, RAFT and fused feature work. Model setup, scoring and file writes are reported separately in the result ledgers. The archived provided-mask RAFT increment over its center baseline on 30 trait potatoes was {original:.2f} s, with its original runtime accounting. [Per-potato runtime](runtime_by_potato.csv) · [Failures](failures.csv) · [Archived trait runtime](../raft_fusion_traits_v1/report.md#incremental-cpu-time)

{runtime_table}

This development comparison measures replacement of the mask source throughout a frozen RGB-D fusion pipeline on the coached repeat's clicks. Performance with another operator, other acquisition groups, or a thickness-free filter remains unmeasured.

## Reproduce

From the workspace root, use a fresh copy with this study's scripts and protocol, plus the archived local RGB-D, geometry, checkpoints, calibration and CPU environment.

```bash
sh studies/sam2_raft_end_to_end_v1/reproduce.sh
```
"""
    (c.STUDY / "report.md").write_text(text)
    print("Integrated development report saved.", flush=True)


if __name__ == "__main__":
    write_report()
