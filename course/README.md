# Course report and showcase

This directory contains presentation-only work over frozen experiment artifacts.
No method, threshold, split or scored prediction is changed. The related-work
review is `related_work.md`; the editable report is `REPORT.md`; the printable
report is `../output/pdf/CSE527_CPU_Shape_Completion_Report.pdf`.

Open `showcase/index.html` locally in a browser. It is self-contained, includes
Plotly, and needs no server or internet connection. It uses synthetic reference,
input and saved completion geometry only. Display errors are one-way exact
sample-to-reference-triangle distances, clipped to an 8 mm color range. They are
post-hoc visualization, not new aggregate endpoints or parameter-selection data.
The numeric scores shown beside each case are the original frozen result rows.

The six cases cover clean input, isolated spikes, a locally self-supporting error
patch, broader support on that patch, a true narrow protrusion, and an asymmetric
hidden twin. Family 0 is fixed for illustration, matching the earlier figure
protocol. Curated views are not representative-performance estimates. Global
plots and full negative results are retained in the report/evidence.

Build presentation artifacts from the workspace root:

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
.venv/bin/python course/tools/build_showcase.py
python course/tools/plot_pin_recoloring_directions.py
python course/tools/build_pdf.py
.venv/bin/python course/tools/package_submission.py
```

The showcase builder needs the ignored original run meshes; the frozen result
JSONs alone cannot rebuild geometry. The authoring pins in
`report-requirements.txt` cover the PDF builder and Figure 4 plotter. Figure 4
uses the bundled paired-direction CSV. Figure and showcase provenance hashes
are recorded under `evidence/`. All three historical source snapshots are
preserved in the reproduction package because their source gates differ.

The submission ZIP contains a PDF, self-contained showcase, README, integrity
manifest and a nested reproduction archive. Raw real datasets and real reference
geometry are excluded. No official assignment PDF/template was supplied; course
format and author metadata requirements still require checking against the
rubric. No course submission or external upload is performed.
