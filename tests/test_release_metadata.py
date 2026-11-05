"""A release writes its version in four places, and they have to agree."""

import re
import tomllib
from pathlib import Path

import resolvelab

ROOT = Path(__file__).resolve().parents[1]


def test_version_records_agree():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    assert resolvelab.__version__ == version

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entry = re.search(rf"^## {re.escape(version)} — (\d{{4}}-\d{{2}}-\d{{2}})$", changelog, re.MULTILINE)
    assert entry, f"CHANGELOG.md has no dated entry for {version}"

    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert f"\nversion: {version}\n" in citation
    assert f"\ndate-released: {entry[1]}\n" in citation
