"""After reconstruction, label propagation states using the released annotations."""

from contextlib import ExitStack

import common as c
from studies.sam2_pin_prompt_v1 import run as pin


def audit():
    freeze, _ = c.tracking_bundle()
    if not (c.STUDY / "predictions_before_targets.json").is_file():
        raise ValueError("Freeze model predictions before opening annotations for this audit")
    cases = freeze["roster"]
    polygons = pin.load_polygons(freeze)
    frames, rows = [], []
    with ExitStack() as stack:
        archives = c.prep.open_images(stack, (r["archive"] for r in cases))
        for case in cases:
            tuber = case["tuber"]
            record = c.prep.read_json(c.track_path(tuber))
            masks = c.packed_masks(tuber, record) if record["mask_sha256"] else {}
            center, upper = case["selected"][1:]
            states, transitions = {}, []
            prompt_state = None
            for index, frame in enumerate(case["frames"]):
                _, alpha, pin_mask = pin.annotation_masks(archives[case["archive"]], frame, polygons)
                suffix = frame["suffix_px"]
                if index == 0 and "prompt" in masks:
                    metrics = pin.metrics(c.unpack(masks["prompt"]), alpha, pin_mask)
                    prompt_state = metrics["state"]
                    frames.append({"tuber": tuber, "phase": "prompt", "suffix": suffix, **metrics})
                if suffix in masks:
                    metrics = pin.metrics(c.unpack(masks[suffix]), alpha, pin_mask)
                    states[suffix] = metrics["state"]
                    frames.append({"tuber": tuber, "phase": "propagation", "suffix": suffix, **metrics})
                else:
                    states[suffix] = "missing"
                    frames.append({"tuber": tuber, "phase": "propagation", "suffix": suffix,
                                   "state": "missing"})
            last, first_match = prompt_state, None
            for suffix, state in states.items():
                if state != last:
                    transitions.append({"suffix": suffix, "old": last, "new": state})
                if state == "potato" and first_match is None:
                    first_match = suffix
                last = state
            losses = [r["suffix"] for r in transitions if r["old"] == "potato" and r["new"] != "potato"]
            rows.append({
                "tuber": tuber, "analysis": case["analysis"], "response": case["response"],
                "click_x": case["click_xy"][0], "click_y": case["click_xy"][1], "prompt_state": prompt_state,
                "center_state": states[center], "upper_state": states[upper],
                "below_threshold_suffixes": [s for s, state in states.items() if state != "potato"],
                "empty_suffixes": record["empty_suffixes"], "first_potato_suffix": first_match,
                "loss_suffixes": losses,
                "pin_takeover_suffixes": [s for s, state in states.items()
                                          if state == "pin" and first_match is not None and s > first_match],
                "recovery_suffixes": [r["suffix"] for r in transitions if losses and r["suffix"] > losses[0]
                                      and r["new"] == "potato"],
                "transitions": transitions,
            })
    c.write_csv(c.STUDY / "tracking_by_frame.csv", frames)
    c.write_csv(c.STUDY / "tracking_audit.csv", rows)
    c.prep.write_json(c.STUDY / "tracking_audit.json", {"rows": rows, "frames": len(frames)})
    print(f"Audited {len(rows)} tracks and {len(frames)} masks with annotations after reconstruction", flush=True)


if __name__ == "__main__":
    audit()
