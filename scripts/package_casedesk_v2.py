"""Copy v2 evidence from .local/v04 into artifacts/v0.4 (reports, zipped traces and data).

Traces and imitation data are zipped per arm/file (they are repetitive JSON); every member
keeps its original bytes, so the SHA-256 values recorded in reports and the lock still apply.
"""

import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local/v04"
OUT = ROOT / "artifacts/v0.4"


def zip_dir(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.glob("*.json")):
            archive.write(path, path.name)


def main():
    for pool in ("dev", "test"):
        for report in sorted((LOCAL / "eval" / pool).glob("*.json")):
            if json.loads(report.read_text(encoding="utf-8")).get("status") != "completed":
                raise SystemExit(f"{report} incomplete")
            (OUT / pool).mkdir(parents=True, exist_ok=True)
            shutil.copy2(report, OUT / pool / report.name)
            zip_dir(report.with_suffix(""), OUT / "traces" / pool / f"{report.stem}.zip")
    for run in sorted((LOCAL / "runs").glob("*")):
        (OUT / "training").mkdir(parents=True, exist_ok=True)
        shutil.copy2(run / "training.json", OUT / "training" / f"{run.name}.json")
    with zipfile.ZipFile(OUT / "data.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted((LOCAL / "data").rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(LOCAL / "data").as_posix())
    diagnostics = LOCAL / "diag-position"
    if diagnostics.exists():
        target = OUT / "diagnostics" / "position"
        target.mkdir(parents=True, exist_ok=True)
        for report in sorted(diagnostics.glob("*.json")):
            shutil.copy2(report, target / report.name)
            zip_dir(report.with_suffix(""), target / f"{report.stem}-traces.zip")
    print(OUT)


if __name__ == "__main__":
    main()
