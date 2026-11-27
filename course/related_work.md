# Related work and claim boundary

Reviewed 13 November 2026. This is a focused positioning review, not an exhaustive
systematic search. Primary author/publisher/venue sources are used below. No
neural baseline was retrained, and no published number is treated as comparable
to our different splits, distance conventions or hardware.

| Work | Verified scope | Relationship to this project |
|---|---|---|
| [Ge, Xiong and From, 2020](https://www.sciencedirect.com/science/article/pii/S1537511020301963) | Symmetry-based partial-fruit completion for localization; publisher abstract/highlights checked. | Symmetry completion predates this project. Our belt-constrained height-field reflection is a simple baseline, not a replication of their optimized plane. |
| [Park et al., DeepSDF, CVPR 2019](https://openaccess.thecvf.com/content_CVPR_2019/html/Park_DeepSDF_Learning_Continuous_Signed_Distance_Functions_for_Shape_Representation_CVPR_2019_paper.html) | A learned continuous signed-distance representation; venue abstract checked. | Learned shape priors and implicit completion are established; this CPU pipeline does not train a neural decoder. |
| [Magistri et al., CoRe, RA-L 2022](https://www.ipb.uni-bonn.de/wp-content/papercite-data/pdf/magistri2022ral-iros.pdf) | Author PDF: learned latent fruit shapes, SDF decoding and RGB-D encoding. | Complete training shapes supplying a completion prior is established. Our real-data prior uses only eight training clouds and classical fitting. |
| [Magistri et al., transformer completion, ICRA 2024](https://www.ipb.uni-bonn.de/wp-content/papercite-data/pdf/magistri2024icra.pdf) | Author-hosted abstract/indexed first page: sparse point features, transformer decoding and iterative template deformation. Full PDF reader failed on the 21 MB file. | Template-based learned completion already exists. Our fixed-rotation convex-hull retrieval is a different, intentionally limited classical baseline. No superiority claim is supported. |
| [Blok et al., CoRe++, 2025](https://arxiv.org/html/2407.21341v3) | Full primary HTML inspected, including discussion; RGB-D-to-implicit potato completion. | The application and shape-completion task already exist. We investigate CPU baseline validity and controlled repair failures, without claiming a matched neural comparison. |
| [Wang et al., 3DPotatoTwin, 2025](https://doi.org/10.1016/j.plaphe.2025.100123) | Publisher-indexed abstract: 339 paired tubers, RGB-D/SfM and registration. Full publisher page was inaccessible in this check. [Dataset card](https://huggingface.co/datasets/UTokyo-FieldPhenomics-Lab/3DPotatoTwin) inspected separately. | Dataset registration/volume claims do not certify every demo item. Our actual five-pair audit finds open references and an unresolved metadata mismatch. |
| [Magistri et al., Bonn benchmark, arXiv v2, 2024](https://arxiv.org/html/2407.13304v2) | Full primary HTML: laboratory/greenhouse sweet peppers, RGB-D inputs and laser references. | This supplies the external lab-fruit experiment. Our local public-validation holdout, metrics and bounded subset differ from the official hidden benchmark. |
| [Blok et al., PointRAFT, arXiv v2, 4 Nov 2026](https://arxiv.org/html/2512.24193v2) | Primary HTML: direct potato weight regression from partial points with a height embedding. | Weight regression does not evaluate completed surface geometry; its weight errors cannot validate this project's meshes. |
| [Fleishman, Cohen-Or and Silva, SIGGRAPH 2005](https://sci.utah.edu/~csilva/papers/sig2005.pdf) | Author PDF: robust moving least-squares reconstruction with sharp-feature handling. | Local robust fitting and the ambiguity between noise and features are established. Our one-sided quadratic residual gate is not their forward-search method or new robust statistics. |

## Claim that the evidence supports

A CPU implementation combining standard geometric completion and selective
positive-depth repair was evaluated with sealed development/confirmation
protocols. Local support improves isolated injected spikes on a specified
synthetic distribution. Coherent errors can support one another, and broader
support can erase true narrow protrusions. The real pepper study establishes a
working classical baseline and reproduces its development geometry; it does not
validate the synthetic repair rule on potatoes.

The experimental contribution is the matched intervention/ablation study,
genuine-feature controls, explicit hidden-twin ambiguity, and traceable positive
and negative evidence. Algorithmic novelty, general robustness, calibrated
uncertainty and held-out potato performance remain unestablished. The original
ambition of a validated novel potato-completion algorithm has not been met by
the current evidence. No amount of presentation polish changes that boundary.

## Appropriate future validation

Any revised method needs fresh reserved objects, realistic segmentation/depth
errors, genuine irregular features and a new sealed protocol. A matched
comparison with robust MLS/feature-preserving reconstruction would be needed
before a stronger methodological claim. A matched neural comparison needs
compatible data, splits and metrics. Existing confirmation/holdout objects are
closed to tuning. New potato data and independently verified scale/support
calibration are needed for potato transfer; no additional dataset was acquired
for this report.
