# -*- coding: utf-8 -*-
"""Regression tests for workspace markdown template copying."""

from __future__ import annotations


def test_copy_workspace_md_files_does_not_install_bootstrap_by_default(
    tmp_path,
):
    """New workspaces should not start by asking who the agent/user is."""
    from qwenpaw.agents.utils.setup_utils import copy_workspace_md_files

    copied = copy_workspace_md_files("zh", tmp_path)

    assert "AGENTS.md" in copied
    assert "PROFILE.md" in copied
    assert "BOOTSTRAP.md" not in copied
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "PROFILE.md").exists()
    assert not (tmp_path / "BOOTSTRAP.md").exists()
