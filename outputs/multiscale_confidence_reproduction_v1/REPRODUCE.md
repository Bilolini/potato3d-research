# Frozen multiscale-confidence experiment

This folder contains the verified implementation, dependency lock, protocols, tests, selection record and original JSON evidence. Raw demo data and generated meshes are excluded.

Run from this folder with Python 3.12 and uv, using fresh output paths:

```bash
export UV_CACHE_DIR="$PWD/.cache/uv"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
uv sync --locked --extra dev
.venv/bin/python -m pytest -q
.venv/bin/python scripts/run_multiscale_study.py --split development --out outputs/reproduced_development
.venv/bin/python scripts/select_multiscale_candidate.py outputs/reproduced_development --out outputs/reproduced_selection.json
.venv/bin/python scripts/run_multiscale_study.py --split confirmation --selection outputs/reproduced_selection.json --out outputs/reproduced_confirmation
.venv/bin/python scripts/analyze_multiscale_study.py outputs/reproduced_confirmation --out outputs/reproduced_analysis
```

Reproduce to verify the frozen experiment; do not use its scores to retune. The recorded selection contains the original absolute evidence path; the commands above create a new equivalent selection with the reproduction's own evidence path. Cross-platform bit-for-bit numerical identity is not guaranteed. Artifact SHA256s are in MANIFEST.json.
