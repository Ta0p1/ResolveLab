"""Write a study's ``artifacts/locked-source`` snapshot from the commit it locked, and check it."""

import argparse
import json
import subprocess
import zipfile

from locked_source import ROOT, read_snapshot
from verify_http_study import V03_SOURCE

# The v0.3 lock names no commit or file list, and the commit in the v0.4 lock was rewritten without
# changing its tree (artifacts/v0.4/RESULTS.md). The hash decides either way.
REVISIONS = {"v0.3": "v0.3.0", "v0.4": "7ace095", "v0.5": "d092177"}


def locked_files(study):
    if study == "v0.3":
        return V03_SOURCE
    lock = json.loads((ROOT / f"artifacts/{study}/test-lock.json").read_text(encoding="utf-8"))
    return lock["source_files"]


def write_snapshot(study):
    path = ROOT / f"artifacts/locked-source/{study}.zip"
    path.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(locked_files(study)):
            spec = f"{REVISIONS[study]}:src/resolvelab/{name}"
            data = subprocess.run(
                ["git", "show", spec], cwd=ROOT, capture_output=True, check=True
            ).stdout
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return read_snapshot(study)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("studies", nargs="+", choices=sorted(REVISIONS))
    for study in parser.parse_args().studies:
        print(f"{study}: {len(write_snapshot(study))} files reproduce the lock's source hash.")
