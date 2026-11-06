from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from qwenpaw.app.sealed_agents.package import inspect_extracted_payload


TOOL = Path(__file__).parents[1] / "tools" / "restore_signed_release_file.py"


def _restore():
    spec = importlib.util.spec_from_file_location("restore_signed_release_file", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.restore_signed_file


def test_recovery_verifies_full_signed_digest_before_write(tmp_path):
    root = tmp_path / "release"
    target = root / "agent" / "__pycache__" / "workflow.pyc"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"signed")
    (root / "agent" / "runtime.py").write_bytes(b"source")
    expected, _ = inspect_extracted_payload(root)
    source = tmp_path / "original.pyc"
    source.write_bytes(b"signed")
    target.write_bytes(b"changed")
    restore = _restore()
    args = dict(
        release_root=root, relative_path="agent/__pycache__/workflow.pyc",
        source=source, expected_digest=expected,
        backup_dir=tmp_path / "backups",
    )
    assert restore(**args)["status"] == "verified_dry_run"
    assert target.read_bytes() == b"changed"
    assert restore(**args, commit=True)["status"] == "restored"
    assert inspect_extracted_payload(root)[0] == expected
    assert next((tmp_path / "backups").iterdir()).read_bytes() == b"changed"


def test_recovery_rejects_unverified_replacement(tmp_path):
    root = tmp_path / "release"
    root.mkdir()
    (root / "runtime.py").write_bytes(b"signed")
    expected, _ = inspect_extracted_payload(root)
    source = tmp_path / "replacement"
    source.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="does not restore"):
        _restore()(
            release_root=root, relative_path="runtime.py", source=source,
            expected_digest=expected, backup_dir=tmp_path / "backup", commit=True,
        )
    assert (root / "runtime.py").read_bytes() == b"signed"
