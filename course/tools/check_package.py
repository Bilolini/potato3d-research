"""Verify the packaged report, figure reproduction and optional installation fixture."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract(source, destination):
    with zipfile.ZipFile(source) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive CRC mismatch")
        for name in archive.namelist():
            path = (destination/name).resolve()
            if not path.is_relative_to(destination.resolve()):
                raise ValueError("Unsafe archive path")
            if "raw" in Path(name).parts or Path(name).suffix in {".ply", ".obj", ".npy"}:
                raise ValueError("Unexpected raw/geometry asset in reproduction archive")
        archive.extractall(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--online", action="store_true", help="Allow the dependency installer to access registries")
    parser.add_argument("--presentation-only", action="store_true",
                        help="Verify the archive and reproduce Figure 4 without any experiment execution")
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    bundle = ROOT/"dist/CSE527_CPU_Shape_Completion.zip"
    extract(bundle, out)
    package = out/"CSE527_CPU_Shape_Completion"
    manifest = json.loads((package/"MANIFEST.json").read_text())
    for name, digest in manifest.items():
        if sha(package/name) != digest:
            raise ValueError("Outer manifest mismatch")
    reproduction = out/"reproduction"; extract(package/"reproduction.zip", reproduction)
    env = dict(os.environ, UV_CACHE_DIR=str(ROOT/".cache/uv"), MPLCONFIGDIR=str(out/"matplotlib"),
               OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1", PYTHONPATH="")
    def execute(label, command, cwd):
        result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)
        (out/(label+".log")).write_text(result.stdout+result.stderr)
        if result.returncode:
            print((result.stdout+result.stderr)[-5000:])
            raise RuntimeError(f"{label} failed; inspect log")
        return result.stdout.strip()
    integrity = execute("integrity", [sys.executable, "VERIFY.py"], reproduction)
    report = ROOT/"output/pdf/CSE527_CPU_Shape_Completion_Report.pdf"
    if sha(package/"report.pdf") != sha(report):
        raise ValueError("Packaged report differs from the reviewed printable PDF")
    rebuilt = out/"reproduced_pin_figure.png"
    plot = reproduction/"course/tools/plot_pin_recoloring_directions.py"
    execute("pin_figure_reproduction", [sys.executable, str(plot), "--output", str(rebuilt)], reproduction)
    expected = reproduction/"course/figures/pin_recoloring_directions.png"
    if sha(rebuilt) != sha(expected):
        raise ValueError("Rebuilt Figure 4 differs from the archived PNG. Use the pinned Matplotlib runtime.")
    old = json.loads((ROOT/"docs/pre_course_checksums.json").read_text())["files"]
    if any(sha(ROOT/name) != digest for name, digest in old.items()):
        raise ValueError("Historical result JSON changed")
    record = {
        "package_sha256": sha(bundle),
        "outer_manifest_files_verified": len(manifest),
        "nested_integrity": integrity,
        "packaged_report_sha256": sha(report),
        "reproduced_pin_figure_sha256": sha(rebuilt),
        "pin_figure_table_sha256": sha(reproduction/"studies/regional_shape_v1/triposr_pin_multituber/per_potato.csv"),
        "presentation_only": args.presentation_only,
        "research_holdout_predictions_or_scores_rerun": 0,
        "historical_jsons_unchanged": len(old),
        "real_raw_geometry_included": False,
    }
    verification = ROOT/"course/evidence/package_verification.json"
    if args.presentation_only:
        verification.write_text(json.dumps(record, indent=2)+"\n")
        print(json.dumps(record, indent=2))
        return
    source = reproduction/"source/bonn"
    command = ["uv", "sync", "--locked", "--extra", "dev", "--python", str(ROOT/".venv/bin/python"), "--no-progress"]
    if not args.online:
        command.append("--offline")
    execute("fresh_install", command, source)
    python = source/".venv/bin/python"
    source_proof = execute("source_proof", [str(python), "-c", "import sys,potato3d.bonn; from potato3d.fruit_study import verify_seal; print(sys.prefix); print(potato3d.bonn.__file__); print(verify_seal())"], source)
    if str(source) not in source_proof:
        raise ValueError("Fresh environment imported the original workspace")
    tests = execute("tests", [str(python), "-m", "pytest", "-q"], source)
    import yaml
    config = yaml.safe_load((source/"configs/baseline.yaml").read_text())
    config.update(seed=527131399, synthetic_points=400, surface_samples=2000, max_fit_points=1000)
    fixture_config = out/"fresh_fixture.yaml"; fixture_config.write_text(yaml.safe_dump(config))
    fixture = out/"unscored_installation_fixture"
    execute("installation_fixture", [str(source/".venv/bin/potato3d"), "synthetic", "--config", str(fixture_config), "--out", str(fixture)], source)
    rows = json.loads((fixture/"results.json").read_text())
    if len(rows) != 3 or any(r["status"] != "ok" for r in rows):
        raise ValueError("Fresh installation fixture failed")
    record.update(fresh_install_offline=not args.online, fresh_source_proof=source_proof.splitlines(),
                  tests=tests, installation_fixture_seed=config["seed"], unscored_fixture_valid_predictions=len(rows))
    verification.write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
