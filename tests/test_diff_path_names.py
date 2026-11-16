# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_diff_path_names.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The names of the files of a diff are read the way `git apply` reads them, and what the apply really changed goes through the barriers again."""
from __future__ import annotations

from pathlib import Path

import pytest
from _approvals import APPROVERS
from test_signed_approvals import PASS, approved, make_live, pending

from hydra_umc_ops_agent.canary_deploy import ProtectedPathsError, deploy_canary
from hydra_umc_ops_agent.change_proposal import ProtectedPathError
from hydra_umc_ops_agent.diff_policy import protected_paths_in, touched_paths


def test_the_names_of_a_rename_or_a_copy_are_read_as_git_apply_reads_them():
    rename = "diff --git a/README.md b/README.md\nsimilarity index 100%\nrename from src/x.sh\nrename to build-test.sh\n"
    assert touched_paths(rename) == ["README.md", "src/x.sh", "build-test.sh"]
    assert protected_paths_in(rename) == ["build-test.sh"]
    copy = "diff --git a/README.md b/README.md\nsimilarity index 100%\ncopy from src/x.sh\ncopy to scripts/run.sh\n"
    assert protected_paths_in(copy) == ["scripts/run.sh"]
    with pytest.raises(ProtectedPathError):
        pending(rename)


def test_a_name_in_quotes_is_decoded_like_git_apply_decodes_it():
    quoted = '--- "a/b\\165ild-test.sh"\n+++ "b/b\\165ild-test.sh"\n@@ -1 +1 @@\n-a\n+b\n'
    assert touched_paths(quoted) == ["build-test.sh"]
    assert protected_paths_in(quoted) == ["build-test.sh"]
    escapes = '--- "a/dir\\\\x\\"y\\n.txt"\n+++ "b/dir\\\\x\\"y\\n.txt"\n'
    assert touched_paths(escapes) == ['dir\\x"y\n.txt']


def test_what_the_apply_really_changed_goes_through_the_barriers_again(tmp_path: Path, monkeypatch):
    # a gap in the text check (here: it sees no protected path at all) must not let the deploy change a protected file
    diff = "--- a/build-test.sh\n+++ b/build-test.sh\n@@ -1 +1 @@\n-bash check.sh\n+exit 0\n"
    monkeypatch.setattr("hydra_umc_ops_agent.change_proposal.protected_paths_in", lambda text: [])
    proposal = approved(diff)
    monkeypatch.setattr("hydra_umc_ops_agent.canary_deploy.protected_paths_in", lambda text: [])
    live = make_live(tmp_path, {"build-test.sh": "bash check.sh\n"})
    with pytest.raises(ProtectedPathsError):
        deploy_canary(proposal, live_root=live, approvers=APPROVERS, build_test_command=PASS)
    assert "bash check.sh" in (live / "build-test.sh").read_text(encoding="utf-8")


