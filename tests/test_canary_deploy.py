# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_canary_deploy.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real tests against a real, throwaway local git repository - never a
mock of `subprocess`/`git`. Every scenario proves a real, observable
filesystem outcome: the live checkout's own file content, whether a
`.backup-*` sibling exists, whether the staging clone was cleaned up."""
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace as _replace
from unittest import mock
from pathlib import Path

from hydra_umc_ops_agent.canary_deploy import (
    ApprovalInvalidError,
    CanaryDeployError,
    ChangeNotApprovedError,
    DiffApplyError,
    TargetProjectMismatchError,
    deploy_canary,
)
from hydra_umc_ops_agent.change_proposal import approve_change, propose_change

_GOOD_DIFF = (
    "--- a/config.json\n"
    "+++ b/config.json\n"
    "@@ -1,3 +1,3 @@\n"
    " {\n"
    '-  "retries": 0\n'
    '+  "retries": 3\n'
    " }\n"
)

_STILL_FAILING_DIFF = (
    "--- a/config.json\n"
    "+++ b/config.json\n"
    "@@ -1,3 +1,3 @@\n"
    " {\n"
    '-  "retries": 0\n'
    '+  "retries": 1\n'
    " }\n"
)

_NON_APPLYING_DIFF = (
    "--- a/config.json\n"
    "+++ b/config.json\n"
    "@@ -1,3 +1,3 @@\n"
    " {\n"
    '-  "retries": 999\n'
    '+  "retries": 3\n'
    " }\n"
)

_CHECK_SCRIPT = (
    "import json, sys\n"
    "data = json.loads(open('config.json', encoding='utf-8').read())\n"
    "sys.exit(0 if data.get('retries', 0) >= 3 else 1)\n"
)


def _run(args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True)


def _make_live_repo(tmp_path: Path) -> Path:
    live_root = tmp_path / "live-project"
    live_root.mkdir()
    (live_root / "config.json").write_text('{\n  "retries": 0\n}\n', encoding="utf-8")
    (live_root / "check.py").write_text(_CHECK_SCRIPT, encoding="utf-8")
    _run(["git", "init", "-q"], live_root)
    _run(["git", "config", "user.email", "test@example.com"], live_root)
    _run(["git", "config", "user.name", "Test"], live_root)
    _run(["git", "add", "."], live_root)
    _run(["git", "commit", "-q", "-m", "initial"], live_root)
    return live_root


def _make_live_repo_with_real_upstream(tmp_path: Path) -> tuple[Path, Path]:
    """Same real checkout as _make_live_repo(), but cloned from a real
    bare remote first - so `live_root`'s own `origin` is the real
    canonical upstream, the way every real deployed checkout in this
    ecosystem already has it (HYDRA-UMC-UPDATER's own install.py is what
    sets it up that way in the first place). Returns (live_root, remote)."""
    remote = tmp_path / "remote.git"
    _run(["git", "init", "-q", "--bare", str(remote)], tmp_path)
    seed = tmp_path / "seed"
    _run(["git", "clone", "-q", str(remote), str(seed)], tmp_path)
    (seed / "config.json").write_text('{\n  "retries": 0\n}\n', encoding="utf-8")
    (seed / "check.py").write_text(_CHECK_SCRIPT, encoding="utf-8")
    _run(["git", "config", "user.email", "test@example.com"], seed)
    _run(["git", "config", "user.name", "Test"], seed)
    _run(["git", "add", "."], seed)
    _run(["git", "commit", "-q", "-m", "initial"], seed)
    _run(["git", "push", "-q", "origin", "HEAD"], seed)
    live_root = tmp_path / "live-project"
    _run(["git", "clone", "-q", str(remote), str(live_root)], tmp_path)
    return live_root, remote


def _make_approved_proposal(diff_text: str):
    proposal = propose_change(
        incident_id="inc-1", correlation_id="corr-1", project_name="test-project",
        description="Raise retries to 3", diff=diff_text, rationale="fixes the flaky check",
    )
    return approve_change(proposal, approved_by="Test Approver")


class DeployCanaryHappyPathTests(unittest.TestCase):
    def test_a_real_successful_canary_promotes_the_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            live_root = _make_live_repo(tmp_path)
            proposal = _make_approved_proposal(_GOOD_DIFF)

            result = deploy_canary(proposal, live_root=live_root, build_test_command=[sys.executable, "check.py"])

            self.assertTrue(result.promoted)
            self.assertEqual(result.stage_reached, "promoted")
            # The live path now holds the PATCHED content - the swap really happened.
            self.assertIn('"retries": 3', (live_root / "config.json").read_text(encoding="utf-8"))
            # The previous checkout was kept, not deleted.
            backups = list(tmp_path.glob("live-project.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertIn('"retries": 0', (backups[0] / "config.json").read_text(encoding="utf-8"))
            # No leftover staging directory.
            self.assertEqual(list(tmp_path.glob("ops-agent-canary-*")), [])


class DeployCanaryDataPreservationTests(unittest.TestCase):
    """V07-002 (P1): this
    module's own docstring claims it uses "the same atomic-by-
    verification pattern HYDRA-UMC-UPDATER's own install.py already
    uses" - but never actually carried over real local data, never
    reset the staging clone's own remote, and never refused a real
    tracked-dirty edit, reproducing the exact same real gaps
    HYDRA-UMC-UPDATER's own REV-001/REV-002/V07-001 fixes already
    closed there."""

    def test_canary_carries_over_real_untracked_local_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            live_root = _make_live_repo(tmp_path)
            # A real, genuinely untracked file - never added/committed -
            # the exact shape a real project's own local operational
            # data (private-local.json in the review's own reproduction)
            # takes inside a live checkout.
            (live_root / "private-local.json").write_text('{"real": "local state"}', encoding="utf-8")
            proposal = _make_approved_proposal(_GOOD_DIFF)

            result = deploy_canary(proposal, live_root=live_root, build_test_command=[sys.executable, "check.py"])

            self.assertTrue(result.promoted, result.detail)
            self.assertEqual(
                (live_root / "private-local.json").read_text(encoding="utf-8"),
                '{"real": "local state"}',
                "real untracked local data must survive a promoted canary deploy, not be left behind in .backup-*",
            )

    def test_canary_restores_the_real_upstream_remote_on_the_promoted_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            live_root, remote = _make_live_repo_with_real_upstream(tmp_path)
            proposal = _make_approved_proposal(_GOOD_DIFF)

            result = deploy_canary(proposal, live_root=live_root, build_test_command=[sys.executable, "check.py"])

            self.assertTrue(result.promoted, result.detail)
            restored_origin = subprocess.run(
                ["git", "remote", "get-url", "origin"], cwd=str(live_root), check=True, capture_output=True, text=True,
            ).stdout.strip()
            self.assertEqual(
                restored_origin, str(remote),
                "the promoted checkout's own origin must stay the real upstream, "
                f"not the ephemeral local staging/live path - got {restored_origin!r}",
            )

    def test_canary_refuses_when_a_tracked_file_has_an_uncommitted_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            live_root = _make_live_repo(tmp_path)
            # A real, uncommitted edit to an already-TRACKED file.
            (live_root / "config.json").write_text('{\n  "retries": 0,\n  "USER_UNCOMMITTED": true\n}\n', encoding="utf-8")
            proposal = _make_approved_proposal(_GOOD_DIFF)

            with self.assertRaises(CanaryDeployError):
                deploy_canary(proposal, live_root=live_root, build_test_command=[sys.executable, "check.py"])

            self.assertIn(
                "USER_UNCOMMITTED", (live_root / "config.json").read_text(encoding="utf-8"),
                "a real uncommitted edit to a tracked file must never be silently discarded",
            )
            self.assertEqual(list(tmp_path.glob("live-project.backup-*")), [], "a refused deploy must never rename anything aside")


class DeployCanaryApprovalBindingTests(unittest.TestCase):
    """V07-003 (P1): the
    review pass's own exact reproduction - an approval for OTHER_PROJECT
    applied cleanly to a checkout whose real manifest names a
    completely different project, because deploy_canary() only ever
    checked `status == "approved"`."""

    def test_tampering_with_the_approved_diff_on_disk_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            live_root = _make_live_repo(tmp_path)
            proposal = _make_approved_proposal(_GOOD_DIFF)
            # A saved, approved proposal file is real, mutable JSON on
            # disk - simulate a hand-edited diff, approval left intact.
            tampered = _replace(proposal, diff=_STILL_FAILING_DIFF)

            with self.assertRaises(ApprovalInvalidError):
                deploy_canary(tampered, live_root=live_root, build_test_command=[sys.executable, "check.py"])
            self.assertEqual(list(tmp_path.glob("live-project.backup-*")), [])
            # A caller catching only the module's own CanaryDeployError
            # (cli.py's own _cmd_control_deploy_canary does exactly
            # this) must still catch this failure mode.
            self.assertTrue(issubclass(ApprovalInvalidError, CanaryDeployError))

    def test_deploying_to_a_checkout_that_names_a_different_project_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            live_root = _make_live_repo(tmp_path)
            # live_root's own real manifest names a DIFFERENT project
            # than the one this proposal was approved for.
            (live_root / "hydra-umc.project.json").write_text(json.dumps({"name": "HYDRA-UMC-EXAMPLE"}), encoding="utf-8")
            _run(["git", "add", "."], live_root)
            _run(["git", "commit", "-q", "-m", "add manifest"], live_root)
            proposal = _make_approved_proposal(_GOOD_DIFF)  # approved for "test-project"

            with self.assertRaises(TargetProjectMismatchError):
                deploy_canary(proposal, live_root=live_root, build_test_command=[sys.executable, "check.py"])
            self.assertIn('"retries": 0', (live_root / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(list(tmp_path.glob("live-project.backup-*")), [])

    def test_deploying_to_a_checkout_with_no_manifest_at_all_is_not_blocked_by_this_check(self):
        # An honest "can't tell" (no manifest present) must never itself
        # block a deploy - that would be a real, separate regression.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            live_root = _make_live_repo(tmp_path)
            proposal = _make_approved_proposal(_GOOD_DIFF)
            result = deploy_canary(proposal, live_root=live_root, build_test_command=[sys.executable, "check.py"])
            self.assertTrue(result.promoted, result.detail)


class DeployCanarySafetyGateTests(unittest.TestCase):
    def test_refuses_to_run_against_an_unapproved_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            live_root = _make_live_repo(Path(tmp))
            pending = propose_change(
                incident_id="inc-1", correlation_id="corr-1", project_name="test-project",
                description="x", diff=_GOOD_DIFF, rationale="x",
            )
            with self.assertRaises(ChangeNotApprovedError):
                deploy_canary(pending, live_root=live_root, build_test_command=[sys.executable, "check.py"])
            # Nothing was touched - original content untouched, no backup created.
            self.assertIn('"retries": 0', (live_root / "config.json").read_text(encoding="utf-8"))


class DeployCanaryFailureModesTests(unittest.TestCase):
    def test_a_diff_that_does_not_apply_leaves_the_live_checkout_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            live_root = _make_live_repo(tmp_path)
            proposal = _make_approved_proposal(_NON_APPLYING_DIFF)

            with self.assertRaises(DiffApplyError):
                deploy_canary(proposal, live_root=live_root, build_test_command=[sys.executable, "check.py"])

            self.assertIn('"retries": 0', (live_root / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(list(tmp_path.glob("live-project.backup-*")), [])
            self.assertEqual(list(tmp_path.glob("ops-agent-canary-*")), [])

    def test_a_failed_build_verification_leaves_the_live_checkout_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            live_root = _make_live_repo(tmp_path)
            proposal = _make_approved_proposal(_STILL_FAILING_DIFF)

            result = deploy_canary(proposal, live_root=live_root, build_test_command=[sys.executable, "check.py"])

            self.assertFalse(result.promoted)
            self.assertEqual(result.stage_reached, "diff_applied")
            self.assertIn("live checkout was never touched", result.detail)
            self.assertIn('"retries": 0', (live_root / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(list(tmp_path.glob("live-project.backup-*")), [])
            self.assertEqual(list(tmp_path.glob("ops-agent-canary-*")), [])

    def test_promotion_self_heals_when_the_second_rename_fails(self):
        # V07-004: a real regression this exact self-heal path never had
        # (HYDRA-UMC-UPDATER's own sibling fix - the same real gap in
        # install.py's own clone_or_pull() - got this same test; this
        # module's own self-heal code already existed but was untested).
        # Injects a real failure into exactly the second promotion
        # rename (staging clone into place) and confirms the previous
        # checkout is restored rather than silently lost.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            live_root = _make_live_repo(tmp_path)
            proposal = _make_approved_proposal(_GOOD_DIFF)

            original_rename = Path.rename

            def flaky_rename(self, target):
                # Only the staging clone's own rename (the second, real
                # promotion rename) fails - the first rename (live
                # checkout -> backup) must go through normally so this
                # test actually reaches the self-heal path.
                if self.name.startswith("ops-agent-canary-"):
                    raise OSError("synthetic failure injected by test")
                return original_rename(self, target)

            with mock.patch.object(Path, "rename", flaky_rename):
                with self.assertRaises(CanaryDeployError) as ctx:
                    deploy_canary(proposal, live_root=live_root, build_test_command=[sys.executable, "check.py"])

            self.assertIn("restored the previous checkout", str(ctx.exception))
            self.assertTrue(live_root.is_dir())
            self.assertIn('"retries": 0', (live_root / "config.json").read_text(encoding="utf-8"))
            # Self-heal renamed the backup back - no orphaned backup left behind.
            self.assertEqual(list(tmp_path.glob("live-project.backup-*")), [])


if __name__ == "__main__":
    unittest.main()
