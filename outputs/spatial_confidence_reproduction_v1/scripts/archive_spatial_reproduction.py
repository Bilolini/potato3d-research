"""Save verified source/config/evidence so this frozen experiment can be restored."""
import argparse
import json
from pathlib import Path
import shutil

from potato3d.io import sha256, write_json
from potato3d.pipeline import environment
from potato3d.spatial_study import validate_selection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    validate_selection(args.selection)
    current = environment()
    for run in [args.development, args.confirmation]:
        saved = json.loads((run/"environment.json").read_text())
        if saved["source_sha256"] != current["source_sha256"] or saved["lock_sha256"] != current["lock_sha256"]:
            raise ValueError("Current source/lock does not match both frozen runs")
    args.out.mkdir(parents=True, exist_ok=False)
    sources = [Path(p) for p in ["pyproject.toml", "uv.lock", ".python-version", ".gitignore", "README.md"]]
    for folder, patterns in [("src", ["*.py"]), ("scripts", ["*.py"]), ("tests", ["*.py"]),
                             ("configs", ["*.yaml"]), ("docs", ["*.md", "*.json"]), ("data", ["README.md", "demo_manifest.json"])]:
        for pattern in patterns:
            sources.extend(Path(folder).rglob(pattern) if folder != "data" else Path(folder).glob(pattern))
    for source in sorted(set(sources)):
        target = args.out/source
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for label, run in [("development", args.development), ("confirmation", args.confirmation)]:
        target = args.out/"evidence"/label
        target.mkdir(parents=True)
        for source in run.glob("*.json"):
            shutil.copy2(source, target/source.name)
    (args.out/"REPRODUCE.md").write_text(
        "# Frozen spatial-confidence experiment\n\n"
        "This folder contains the verified implementation, dependency lock, protocols, tests, "
        "selection record and original JSON evidence. Raw demo data and generated meshes are excluded.\n\n"
        "Run from this folder with Python 3.12 and uv, using fresh output paths:\n\n"
        "```bash\nexport UV_CACHE_DIR=\"$PWD/.cache/uv\"\nexport MPLCONFIGDIR=\"$PWD/.cache/matplotlib\"\n"
        "export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1\n"
        "uv sync --locked --extra dev\n.venv/bin/python -m pytest -q\n"
        ".venv/bin/python scripts/run_spatial_study.py --split development --out outputs/reproduced_development\n"
        ".venv/bin/python scripts/select_spatial_candidate.py outputs/reproduced_development --out outputs/reproduced_selection.json\n"
        ".venv/bin/python scripts/run_spatial_study.py --split confirmation --selection outputs/reproduced_selection.json --out outputs/reproduced_confirmation\n"
        ".venv/bin/python scripts/analyze_spatial_study.py outputs/reproduced_confirmation --out outputs/reproduced_analysis\n```\n\n"
        "Reproduce to verify the frozen experiment; do not use its scores to retune. "
        "The recorded selection contains the original absolute evidence path; the commands above create "
        "a new equivalent selection with the reproduction's own evidence path. Cross-platform "
        "bit-for-bit numerical identity is not guaranteed. Artifact SHA256s are in MANIFEST.json.\n")
    files = {str(p.relative_to(args.out)): sha256(p) for p in sorted(args.out.rglob("*")) if p.is_file()}
    write_json(args.out/"MANIFEST.json", {"role": "verified restorable source and synthetic experiment evidence snapshot",
                                        "source_and_lock_verified_against_both_runs": True,
                                        "original_selection_sha256": sha256(args.selection), "files": files})
    print(f"Archived {len(files)} files in {args.out}")


if __name__ == "__main__":
    main()
