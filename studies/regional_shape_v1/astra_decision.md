# Research decision after regional reflection v1

Keep the current result as development evidence. On the seven evaluable tubers, full reflection beat the mean of seven shifted controls by 0.731 mm but increased underside MAE by 0.217 mm versus the smooth body. One neighboring shift also beat aligned reflection. The angular position affected error on this cohort. Exact same-location symmetry and a practical accuracy benefit remain unestablished. Mask-related exclusions limit the result to the evaluable interior regions. [Development report](results.md)

## One remaining question about reflection strength

Does downweighting the observed regional deviation improve underside MAE over the smooth body on a tuber excluded from choosing that weight?

Use the same development inputs, predictions, masks, sectors, common cells, and averaging order. Preserve the original artifacts. Reconstruct underside height as body lower height minus a single weight times the existing signed regional correction. Use candidate weights 0, 0.25, 0.5, 0.75 and 1. A weight of zero reproduces the body and one reproduces full reflection. This is a new development analysis motivated by the first result.

1. Reproduce both endpoint errors from the saved study on identical support. Compute MAE on individual cells before the existing sector, band and tuber averages. Interpolating endpoint MAEs does not recover intermediate errors.
2. For each of the seven evaluable tubers, choose the weight with lowest equal-tuber mean error on the other six. Break ties toward zero. Score the excluded tuber once at that weight and report the paired difference from its body prediction. Record the chosen weights, per-tuber results and the influence of each tuber on the aggregate. Keep the denominator of 12 selected tubers visible.
3. Evaluate the seven cyclic shifts using each fold's already-chosen weight. Report their mean and the two neighboring shifts individually. Apply the existing registration probes with the nominal fold weights fixed and compare on common support. Retain the existing clipped mirror as a practical comparator.
4. Provide an error-versus-weight plot and per-tuber table. A gain confined to the pooled fitted curve does not justify confirmation. If out-of-fold errors fail to improve on the body, close this reflection-strength direction on the current protocol. If an improvement persists across tubers and probes, return to Astra to judge its size, coverage, and whether independent confirmation is worth the data. The seven folds reuse development objects and cannot establish generalization.

Only the existing development cohort is needed. The neighboring shift that looked favorable in v1 stays a diagnostic. Selection of a rotation, changes to the coverage rule, and scoring additional tubers are separate research decisions.
