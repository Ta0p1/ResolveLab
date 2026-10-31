"""Copy the dialect study's evidence from .local/v05 into artifacts/v0.5 (reports, zipped
traces, training reports, data and both analyses).

Traces and data are zipped (they are repetitive JSON); every member keeps its original bytes,
so the SHA-256 values recorded in reports and the lock still apply. Refuses an incomplete
report, a missing analysis, or a test phase that ran without the lock.
"""

import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local/v05"
OUT = ROOT / "artifacts/v0.5"
# Report folders: the dev rehearsal, held-out dialects, the multi arms on the study contract.
POOLS = ("dev", "test", "study-contract")


def zip_dir(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.glob("*.json")):
            archive.write(path, path.name)


def main():
    lock = json.loads((OUT / "test-lock.json").read_text(encoding="utf-8"))
    for pool in POOLS:
        for report in sorted((LOCAL / "eval" / pool).glob("*.json")):
            data = json.loads(report.read_text(encoding="utf-8"))
            if data.get("status") != "completed":
                raise SystemExit(f"{report} incomplete")
            if pool != "dev" and data["source_sha256"] != lock["source_sha256"]:
                raise SystemExit(f"{report} ran on a source other than the locked one")
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
    for pool in ("dev", "test"):
        for suffix in (".json", ".md"):
            source = LOCAL / f"analysis-{pool}{suffix}"
            if not source.exists():
                raise SystemExit(f"{source} missing: run scripts/analyze_dialect_transfer.py {pool}")
            shutil.copy2(source, OUT / source.name)
    print(OUT)


if __name__ == "__main__":
    main()
