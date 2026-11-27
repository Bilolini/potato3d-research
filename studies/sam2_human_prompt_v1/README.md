# Human-operator click collection

Run from the potato workspace root on the operator's computer.

```bash
.venv/bin/python studies/sam2_human_prompt_v1/collector.py --open
```

The collector opens at http://127.0.0.1:8765/. Use a maximized desktop browser so the peel and pin are visible. The page provides the task instruction. Each response is saved before the next trial appears. To resume after closing the page or terminal, run the same command. The session is complete when the page says all 40 responses are saved.

The ledger starts at [clicks.csv](clicks.csv). After the 40th response the server writes `frozen_clicks.csv` and `click_freeze.json` automatically. The browser shows collection progress only.

## Verification and analysis

The 40 entry scenes and order are fixed. We checked cue placement on a private review sheet and verified that their graphics stay outside the target and pin. The collector serves the original RGB without alpha and keeps the cue in a separate layer. [Protocol and cue method](protocol.md)

The dummy-image browser test checks native and scaled coordinates, resistance to repeated and stale responses, resume after restart and reload, preserving an explicit skip, and byte equality of the completed snapshot and ledger. It uses a separate temporary directory.

```bash
node studies/sam2_human_prompt_v1/verify_collector.mjs
```

After the real session is complete, run the frozen analysis from the workspace root. It verifies the click receipt before launching the archived tracker. It saves `results.json`, `per_potato.csv`, `per_frame.csv`, and `report.md` in this directory.

```bash
export OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
outputs/corepp_cpu_audit/venv/bin/python studies/sam2_human_prompt_v1/score.py
```
