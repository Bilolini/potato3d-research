# Repeat collection

Open the repeat collector at http://127.0.0.1:8766/. To launch or resume it, run this command from the potato workspace root.

```bash
.venv/bin/python studies/sam2_human_prompt_v1/collector.py --directory studies/sam2_human_prompt_v1/repeat_01 --port 8766 --open
```

The arrow identifies the potato. Click a clear patch of its skin and leave a gap from the small colored circle and the potato edge. The collector saves a separate response ledger here and freezes it after 40 responses. [Repeat protocol](protocol.md)

After collection is complete, use the archived SAM 2 CPU environment.

```bash
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 \
outputs/corepp_cpu_audit/venv/bin/python studies/sam2_human_prompt_v1/score.py --directory studies/sam2_human_prompt_v1/repeat_01
```
