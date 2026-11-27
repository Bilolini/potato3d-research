# Confirmation collection and scoring

From the potato workspace root, launch the collector for the first-time operator.

```bash
.venv/bin/python studies/sam2_human_prompt_v1/collector.py --directory studies/sam2_human_prompt_confirmation_v1 --port 8767 --open
```

Give the operator the collector page at http://127.0.0.1:8767/. They should have seen none of the scenes, earlier results, or failure overlays. Share only the page and let its written instruction guide the session. The collector saves the first response to each trial and resumes at the next unanswered trial. The 45th response seals the click snapshot and receipt.

After all responses are frozen, use the archived CPU environment.

```bash
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
outputs/corepp_cpu_audit/venv/bin/python studies/sam2_human_prompt_confirmation_v1/score.py
```

An interrupted run resumes saved tracks under the same click receipt. A completed run is closed. The report and machine-readable results are written in this directory. [Protocol](protocol.md) · [Current report](report.md)
