# Research decision after conveyor-offset confirmation

Keep the smooth body as the baseline. The fixed scan-only correction reduced average underside error on the measurable confirmation tubers, but the prespecified criterion for a reproducible gain was unmet. The confirmation run is closed. [Decision rule](support_offset_confirmation_protocol.md)

| Question | Measurable tubers | Mean underside MAE, body → corrected | Interpretation |
| --- | ---: | ---: | --- |
| Does a shift estimated from known underside heights transfer across sectors of the same tuber? | 7/12 development | 5.5121 → 3.7523 mm | Part of the developmental error is shared across sectors. The diagnostic requires underside measurements. |
| Can the observed conveyor predict that shift on development objects? | Same 7/12 | 5.5121 → 4.1069 mm | The depth-frame proxy passed its development criterion. |
| Does the fixed proxy improve accuracy on fresh objects? | 24/36 confirmation | 5.0068 → 4.7451 mm | The estimated gain shrank to 0.2617 mm. Both uncertainty intervals span zero. |

Sources for the three comparisons are the [vertical-offset diagnostic](vertical_offset_report.md), [development comparison](support_offset_report.md), and [confirmation report](support_offset_confirmation_report.md).

Sixteen of 24 fresh measurable tubers improved. Removing any one acquisition group preserved the direction of the mean change, but two tubers in one Sayaka group contributed about 71% of the net summed gain. The tuber-level 95% interval for corrected minus body MAE was −0.8290 to +0.2984 mm. The acquisition-group interval was −0.8467 to +0.2947 mm. Correct frame matching improved MAE by 0.1269 mm over within-group reassignment on the eligible subset of 20 tubers in nine groups. This descriptive control gives limited evidence about the value of measuring each frame individually. Eleven coverage failures and one nominal-plane exclusion limit the primary result to the measurable subset.

## Calibration follow-up

Can the conveyor surface that actually supports a tuber be located independently of the potato reconstruction? Before testing another prediction rule, audit acquisition records for a known empty-belt capture, measured roller geometry and camera pose, or another independent support-height reference linked to these acquisitions. Record the units, coordinate system, group correspondence and measurement uncertainty for any candidate. A background plane fitted to the same depth pixels cannot independently validate itself. If the records supply no usable reference, document that limitation and report the completed measurement study with the calibration explanation still open. [Earlier calibration audit](../../docs/calibration_followup.md)

**Final disposition.** The audit covered the 18 acquisition groups represented across these studies. The reviewed release materials and acquisition records provided no independent, frame-linked roller support height. Published camera standoffs and a season-level depth constant cannot establish the contact height at a particular potato. Close the conveyor-correction branch with the smooth body as baseline and the physical cause of the vertical error unresolved. The confirmation result above is the final estimate for the fixed correction. [Completed calibration audit](calibration_data_audit.md)
