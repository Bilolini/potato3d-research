"""Checks for equal-tuber within-group expectations and the exclusive attempt marker."""
import json

import numpy as np
import pytest

from studies.regional_shape_v1.support_offset_confirmation import publish_new, within_group_control


def test_within_group_expected_mae_uses_all_own_group_shifts_and_equal_tubers():
    rows, supports = [], {}
    for group, members in [("a", [0., 2.]), ("b", [0., 3., 6.]), ("singleton", [4.])]:
        for shift in members:
            key = f"{group}-{shift}"
            rows.append({"label": key, "cultivar": "Corolle", "ros_bag_name": group,
                         "predicted_shift_mm": shift, "scores_mm": {"shifted": 0.}})
            supports[key] = np.array([shift]), [[np.array([True])]]
    control = within_group_control(rows, supports)
    assert control["contributing_groups"] == 2
    assert control["contributing_tubers"] == 5
    assert control["correctly_matched_mae_mm"] == 0
    assert control["expected_within_group_reassignment_mae_mm"] == pytest.approx(2.)


def test_attempt_record_cannot_be_replaced(tmp_path):
    attempt = tmp_path/"attempt.json"
    publish_new(attempt, {"first": True})
    with pytest.raises(FileExistsError):
        publish_new(attempt, {"second": True})
    assert json.loads(attempt.read_text()) == {"first": True}
