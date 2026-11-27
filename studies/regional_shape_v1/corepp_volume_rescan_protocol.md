# Exploratory two-rescan volume policy

Use exactly the ten registered development center frames from the archived CoRe++ two-frame volume experiment. Keep fresh cohorts closed. The ten outcomes are already studied. Run only the existing CPU ellipsoid and use the archived neural predictions.

## Freeze before outcome join

For each center frame, load the released registered partial PLY in metres with the project's millimetre loader. Apply the existing nominal belt transform at 350 mm camera depth, giving `z = 350 − z_camera_mm` and belt `z = 0`. Pass all points to the existing fitted ellipsoid with its default settings. Use the project's watertight mesh volume in mm³ divided by 1,000 for mL. The belt is a nominal convention. Keep the input frame and the belt assumption fixed.

Read just the object ID, center frame ID and center volume columns for selection. Rank invalid or failed ellipsoid fits first, followed by successful fits in descending absolute difference between ellipsoid volume and archived center CoRe++ volume. Break ties by ascending case-sensitive object ID, including ties among failures. Flag the first two. The size baseline flags the two highest archived center volumes with the same tie break. Save the rankings, first-frame scores, input provenance and flags before joining the archived second-frame or drainage values.

## Evaluate once

For each policy, use the archived mean-of-two estimate for the two flagged potatoes and the center estimate for the other eight. Score mean absolute volume error against physical drainage in mL across all ten. Compare disagreement with center for everyone, the exact mean over all 45 distinct uniformly sampled pairs, and the size rule. Compute the oracle as the smallest error over the 45 pairs, resolving exact ties by ascending ordered IDs. The oracle is a hindsight benchmark.

Record each potato's center-only and mean-of-two errors, decision, and the difference between those errors. Positive improvement means the rescan reduced absolute error. Report whether disagreement strictly improves on all three baselines. Stop after this comparison.
