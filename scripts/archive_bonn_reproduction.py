"""Archive verified source, protocol and compact evidence; raw data excluded."""
import argparse
import json
from pathlib import Path
import shutil
from potato3d.fruit_study import fingerprint, verify_seal
from potato3d.io import sha256, write_json

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--development", type=Path, default=Path("outputs/bonn_development_v1"))
    parser.add_argument("--holdout", type=Path, default=Path("outputs/bonn_holdout_v1"))
    args = parser.parse_args()
    verify_seal()
    args.out.mkdir(parents=True, exist_ok=False)
    files = set(fingerprint()) | {"README.md", "data/README.md", ".python-version", ".gitignore", "CSE527_3DPotatoTwin_Codex_Context.md"}
    for directory, patterns in [("docs", ["*.md", "*.json"]), ("configs", ["*.yaml", "*.json"]), ("data", ["*.json"])]:
        for pattern in patterns:
            files.update(str(p) for p in Path(directory).glob(pattern))
    for name in sorted(files):
        path = Path(name)
        if path.is_file():
            destination = args.out/path; destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    for split, run in [("development", args.development), ("holdout", args.holdout)]:
        for path in [*run.glob("*.json"), *run.glob("*.jsonl"), *run.glob("*.csv")]:
            destination = args.out/"evidence"/split/path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    manifest = {str(p.relative_to(args.out)): sha256(p) for p in sorted(args.out.rglob("*")) if p.is_file()}
    write_json(args.out/"MANIFEST.json", manifest)
    print("Archived", len(manifest), "verified files; no raw fruit data")
