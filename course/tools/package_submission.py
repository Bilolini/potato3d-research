"""Assemble a compact local submission; verify snapshots and exclude real raw data."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT/"dist"
SNAPSHOTS = {"bonn": "bonn_reproduction_v1", "spatial": "spatial_confidence_reproduction_v1",
             "multiscale": "multiscale_confidence_reproduction_v1"}
PIN_EVIDENCE = (
    "corepp_pin_confirmation_protocol.md",
    "corepp_pin_confirmation/per_potato.csv",
    "corepp_pin_confirmation/report.md",
    "corepp_pin_swap_replication/per_potato.csv",
    "corepp_pin_swap_replication/report.md",
    "corepp_pin_accuracy/per_potato.csv",
    "corepp_pin_accuracy/report.md",
    "corepp_pin_findings.png",
    "triposr_pin_multituber/per_potato.csv",
    "triposr_pin_multituber/report.md",
)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


VERIFY = '''"""Standard-library integrity check; no data acquisition or experiment execution."""
from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parent
manifest=json.loads((root/"MANIFEST.json").read_text())
for name,expected in manifest.items():
    path=(root/name).resolve()
    if not path.is_relative_to(root) or not path.is_file(): raise ValueError(name)
    with path.open("rb") as f: actual=hashlib.file_digest(f,"sha256").hexdigest()
    if actual!=expected: raise ValueError("Changed file: "+name)
print("Verified",len(manifest),"files; no experiments rerun")
'''


README = '''# CSE527: CPU shape completion

## Start here

1. Read `report.pdf`.
2. Open `showcase.html` in a browser. It is fully offline and uses six saved
   synthetic cases. Select cases/methods and drag to compare geometry.
3. Extract `reproduction.zip` for editable report source, figures, provenance,
   compact evidence and three version-specific source checkpoints.

The report covers isolated-spike repair, coherent-error failure, genuine-feature
loss, laboratory-pepper baselines and a real-potato pin-color study. The
29-potato CoRe++ result is descriptive. The paired CoRe++ and TripoSR comparison
uses ten separate development potatoes. A focused primary-source review and its
access limits are included.
No official assignment PDF/template was provided, so check required author,
length and submission-format details against the course rubric before uploading.

## Verify and run a fresh installation

From the extracted reproduction folder, with Python 3.12 and uv installed:

```bash
python3 VERIFY.py
cd source/bonn
export UV_CACHE_DIR="$PWD/.cache/uv"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
uv sync --locked --extra dev
.venv/bin/python -m pytest -q
.venv/bin/potato3d synthetic --out outputs/new_installation_smoke
```

That smoke command uses an analytic installation fixture, not a research holdout.
The source README describes dataset reacquisition and frozen-study reproduction
using new output paths. Real runs require public pinned member retrieval; no raw
real data or real reference point clouds/meshes are included. Do not accept data
agreements or start a large download as part of verification.

## Checkpoints and closed evaluations

- `source/bonn`: latest CPU adapter/fruit baselines; 71 tests at scoring checkpoint.
- `source/spatial`: exact earlier local-repair implementation and evidence.
- `source/multiscale`: exact annular/feature-control implementation and evidence.

Each checkpoint includes its original SHA manifest and protocol. Its source gates
must use the matching checkpoint, not a mixture of versions. Each has a dependency
lock. Original report evidence includes positive and negative outcomes; these are
not pooled as independent frames. Source archives exclude regenerated mesh caches.
The current holdout/confirmation objects are closed to method tuning. Reproduce
only to verify frozen computations, not select another method on their scores.

## Edit or regenerate the report

`course/REPORT.md` and `course/related_work.md` are editable. Figure provenance and
browser/PDF checks are in `course/evidence`. Install the pins in
`course/report-requirements.txt` in a separate authoring environment. Run these
commands from the extracted reproduction root.

```bash
python course/tools/plot_pin_recoloring_directions.py --output reproduced_pin_figure.png
python course/tools/build_pdf.py
```

The Figure 4 script reads
`studies/regional_shape_v1/triposr_pin_multituber/per_potato.csv`. It needs no
model weights, raw scans or new predictions. The PDF appears in `output/pdf/`.
Rebuilding the showcase requires the original saved synthetic meshes or their
frozen regeneration. The supplied HTML already embeds display data.

The outer `MANIFEST.json` checks the four supplied files. `VERIFY.py` checks all
files inside the reproduction archive after extraction. Plotly is distributed
with its embedded license. All real raw assets remain excluded. This is a local
prepared package; no course submission or external upload has been made.
'''


def build():
    DIST.mkdir(exist_ok=True)
    snapshot_files = []
    for label, folder in SNAPSHOTS.items():
        root = ROOT/"outputs"/folder
        manifest = json.loads((root/"MANIFEST.json").read_text())
        files = manifest.get("files", manifest)
        for name, expected in files.items():
            source = (root/name).resolve()
            if not source.is_relative_to(root.resolve()) or digest(source) != expected:
                raise ValueError(f"Source snapshot changed: {label}/{name}")
            snapshot_files.append((source, f"source/{label}/{name}"))
        snapshot_files.append((root/"MANIFEST.json", f"source/{label}/MANIFEST.json"))
    extras = []
    for path in sorted((ROOT/"course").rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".png" and "evidence" in path.parts:
            continue
        if "showcase" in path.parts or path.name in {"package_verification.json", "package_manifest.json"}:
            continue
        extras.append((path, str(path.relative_to(ROOT))))
    for name in ["bonn_real_v1_archive_verification.json", "pre_course_checksums.json"]:
        path = ROOT/"docs"/name; extras.append((path, "course/evidence/"+name))
    pin_root = ROOT/"studies/regional_shape_v1"
    extras.extend((pin_root/name, f"studies/regional_shape_v1/{name}") for name in PIN_EVIDENCE)
    source_zip = DIST/"reproduction.zip"
    inner_manifest = {name: digest(path) for path, name in snapshot_files+extras}
    inner_manifest["README.md"] = hashlib.sha256(README.encode()).hexdigest()
    inner_manifest["VERIFY.py"] = hashlib.sha256(VERIFY.encode()).hexdigest()
    with zipfile.ZipFile(source_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, name in snapshot_files+extras:
            archive.write(path, name)
        archive.writestr("README.md", README)
        archive.writestr("VERIFY.py", VERIFY)
        archive.writestr("MANIFEST.json", json.dumps(inner_manifest, indent=2)+"\n")
    files = {"report.pdf": ROOT/"output/pdf/CSE527_CPU_Shape_Completion_Report.pdf",
             "showcase.html": ROOT/"course/showcase/index.html", "reproduction.zip": source_zip}
    manifest = {name: digest(path) for name, path in files.items()}
    manifest["README.md"] = hashlib.sha256(README.encode()).hexdigest()
    output = DIST/"CSE527_CPU_Shape_Completion.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in files.items():
            archive.write(path, "CSE527_CPU_Shape_Completion/"+name)
        archive.writestr("CSE527_CPU_Shape_Completion/README.md", README)
        archive.writestr("CSE527_CPU_Shape_Completion/MANIFEST.json", json.dumps(manifest, indent=2)+"\n")
    record = {"output": str(output.relative_to(ROOT)), "bytes": output.stat().st_size, "sha256": digest(output),
              "outer_files": 5, "reproduction_files": len(inner_manifest)+1,
              "frozen_snapshots_verified": list(SNAPSHOTS), "raw_real_assets_included": False,
              "report": manifest["report.pdf"], "showcase": manifest["showcase.html"]}
    (ROOT/"course/evidence/package_manifest.json").write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    build()
