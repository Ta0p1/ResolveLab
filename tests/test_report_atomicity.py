import json
from pathlib import Path

import pytest

from resolvelab.evaluation import write_report


def test_transient_windows_rename_denial_preserves_complete_report(tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    path.write_text('{"version": 1}', encoding="utf-8")
    original, attempts = Path.replace, []

    def replace(source, target):
        attempts.append(1)
        assert json.loads(path.read_text()) == {"version": 1}
        if len(attempts) < 3:
            raise PermissionError("briefly open on Windows")
        return original(source, target)

    monkeypatch.setattr(Path, "replace", replace)
    write_report(path, {"version": 2})
    assert json.loads(path.read_text()) == {"version": 2}
    assert len(attempts) == 3
    assert not list(tmp_path.glob("*.tmp"))


def test_permanent_rename_denial_does_not_destroy_previous_report(tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    path.write_text('{"version": 1}', encoding="utf-8")

    def fail(*args):
        raise PermissionError("permanent")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(PermissionError):
        write_report(path, {"version": 2})
    assert json.loads(path.read_text()) == {"version": 1}
    assert not list(tmp_path.glob("*.tmp"))
