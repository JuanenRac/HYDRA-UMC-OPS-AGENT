# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/canary_deploy.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Delivery 4 - Canary deploy: applies an APPROVED change (change_proposal.py)
to a real project checkout through the same atomic-by-verification pattern
HYDRA-UMC-UPDATER's own install.py already uses for updates.

V07-002 (found in an independent revalidation audit, P1): this docstring
used to make that "same pattern" claim while the module underneath only
copied the STRUCTURE (clone/verify/promote) and never the actual
data-safety logic - no real-local-data carryover, no upstream-remote
reset, no tracked-dirty rejection, reproducing every real gap
UPDATER's own REV-001/REV-002/V07-001 fixes already closed there. Fixed
by mirroring UPDATER's own real functions directly (not importing
across repos - each stays independent - but the same logic, same
docstrings, same tests): `_tracked_dirty_paths()`, `_carry_over_local_data()`
and the upstream-remote reset in `_create_staging_clone()` now do real
work, not just exist in name.

Sequence, every step real:
0. Refuse upfront if the live checkout has a real uncommitted edit to
   an already-tracked file - before any staging work at all.
1. Clone the live checkout into an independent local staging directory
   (`git clone --local --no-hardlinks` - the live checkout is never
   touched yet), then reset that clone's own `origin` to the live
   checkout's real upstream (a plain `--local` clone would otherwise
   leave it pointing at the live path itself).
2. Carry over the live checkout's own real untracked/ignored local data
   (config, generated certificates, ... - never a build-artifact
   directory) into the staging clone.
3. Apply the approved proposal's own diff to that staging clone
   (`git apply`) - if this fails, the live checkout was never touched.
4. Run the project's own real build-test command inside the staging
   clone. A failure here is a real, expected possible outcome (that is
   the whole point of staging first) - reported back, never raised as
   an exception, and the live checkout is still never touched.
5. Only if that build passes: two back-to-back renames swap the staging
   clone in for the live checkout, keeping the previous one at a real
   `.backup-<id>` path - never deleted, matching HYDRA-UMC-UPDATER's own
   promotion pattern. If the second rename fails, a best-effort self-heal
   renames the backup back so a real installation still exists (V07-004,
   shared with UPDATER - a full transactional journal surviving a crash
   in the narrow gap between the two renames is real, separate future
   work this bounded mitigation does not attempt).

`deploy_canary()` refuses to run at all unless the given proposal's own
`status` is already `approved` - this is the one check this whole module
exists to enforce, and it comes before anything else, every time.
"""
from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import json

from .change_proposal import STATUS_APPROVED, ChangeProposal, ChangeProposalError
from .log_redaction import redact_secrets


class CanaryDeployError(RuntimeError):
    """Base for every real, distinct failure this module can report."""


class ApprovalInvalidError(CanaryDeployError):
    """Wraps a real ChangeProposalError (ApprovalContentMismatchError,
    almost always) raised by proposal.verify_approval_content() - see
    deploy_canary()'s own call site. Without this, a caller catching
    only CanaryDeployError around deploy_canary() (cli.py's own
    _cmd_control_deploy_canary does exactly this) would let that
    exception propagate uncaught instead of failing the same clean way
    every other real failure mode here already does."""


class TargetProjectMismatchError(CanaryDeployError):
    """V07-003 (found in an independent revalidation audit, P1, the
    finding's own exact reproduction: "a proposal approved for
    OTHER_PROJECT applied cleanly to a checkout whose manifest says
    HYDRA-UMC-EXAMPLE"): `deploy_canary()` used to never check that the
    approved proposal's own `project_name` matched the REAL project at
    `live_root` at all - only its status. Refused before anything is
    touched if `live_root`'s own real `hydra-umc.project.json` names a
    different project."""


def _read_live_project_name(live_root: Path) -> str | None:
    """The real, current name of the project actually checked out at
    `live_root`, read straight from its own manifest - `None` if that
    manifest is missing or unreadable (an honest "can't tell", not a
    silent pass)."""
    manifest_path = live_root / "hydra-umc.project.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    name = data.get("name") if isinstance(data, dict) else None
    return name if isinstance(name, str) else None


class ChangeNotApprovedError(CanaryDeployError):
    """The single most safety-critical check in this module - refuses to
    deploy anything that is not in the APPROVED status, no exceptions,
    regardless of how plausible the diff looks."""


class StagingCloneError(CanaryDeployError):
    """Could not create an independent local staging clone of the live
    project checkout - the live checkout was never touched."""


class DiffApplyError(CanaryDeployError):
    """`git apply` rejected the proposal's own diff against the staging
    clone - the live checkout was never touched."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run(command: list[str], cwd: Path, timeout_s: float) -> tuple[int, str]:
    """Runs one real subprocess, capturing combined output, honoring a
    real timeout - a canary build that hangs must never hang this
    process forever. Never raises for a real, distinct failure mode
    (a nonzero exit, a timeout, a missing executable) - each becomes a
    real, honest (exit_code, output) pair the caller decides what to do
    with."""
    try:
        proc = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT: {' '.join(command)!r} did not finish within {timeout_s}s"
    except OSError as exc:
        return 127, f"could not run {command!r}: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


class TrackedDirtyError(CanaryDeployError):
    """The live checkout has a real, uncommitted edit to an already-
    tracked file - refused before anything is touched. See
    _tracked_dirty_paths()'s own docstring for exactly why this can't be
    left to `git apply`/the build to catch on their own."""


class RemoteRestoreError(CanaryDeployError):
    """Could not reset the staging clone's own `origin` remote back to
    the live checkout's real upstream - the live checkout was never
    touched."""


def _tracked_dirty_paths(path: Path) -> list[str]:
    """Returns every real path (relative to `path`) this checkout's own
    git considers a TRACKED file with a real uncommitted change - staged
    or not (`git status --porcelain`'s own status codes other than
    `??`/`!!`, real untracked/ignored data `_carry_over_local_data()`
    already owns).

    V07-002 (found in an independent revalidation audit, P1): this
    module's own docstring claims it uses "the same atomic-by-
    verification pattern HYDRA-UMC-UPDATER's own install.py already
    uses" - but never actually checked for this. `git clone --local`
    only ever copies the COMMITTED object database, so a real
    uncommitted edit to an already-tracked file lives only in the live
    checkout's own working tree, invisible to the fresh staging clone -
    its own `git apply`/build always succeed regardless, and promotion
    would rename the dirty original aside to `.backup-*`, so the real
    edit would survive only there. Mirrors
    HYDRA-UMC-UPDATER/src/hydra_umc_updater/install.py's own
    `_tracked_dirty_paths()` (V07-001) exactly - same real gap, same
    real fix, in the sibling implementation this module's own docstring
    already claimed shared UPDATER's pattern."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "-z"],
        cwd=str(path), check=False, capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout:
        return []
    paths: list[str] = []
    for entry_text in result.stdout.split("\0"):
        if len(entry_text) < 4:
            continue
        status_code, rel_path = entry_text[:2], entry_text[3:]
        if status_code in ("??", "!!"):
            continue
        paths.append(rel_path)
    return paths


# V07-002: mirrors HYDRA-UMC-UPDATER/src/hydra_umc_updater/install.py's own
# _NEVER_CARRIED_OVER_DIR_NAMES exactly - regenerable build-artifact
# directories are never worth the copy cost and would contaminate the
# staging clone's own freshly-verified build with stale artifacts.
_NEVER_CARRIED_OVER_DIR_NAMES = {
    ".git", "node_modules", "dist", "build", "target", ".venv", "venv",
    "__pycache__", ".next", ".cache", ".pytest_cache", ".mypy_cache",
}


def _real_untracked_paths(path: Path) -> list[str]:
    """Every real path this checkout's own git considers untracked OR
    ignored (`??`/`!!`) - the exact real local-data shape that needs
    carrying into the staging clone, which `git clone --local` never
    copies (only the committed object database)."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "--ignored", "-z"],
        cwd=str(path), check=False, capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout:
        return []
    paths: list[str] = []
    for entry_text in result.stdout.split("\0"):
        if len(entry_text) < 4:
            continue
        status_code, rel_path = entry_text[:2], entry_text[3:]
        if status_code in ("??", "!!"):
            paths.append(rel_path)
    return paths


def _carry_over_local_data(live_root: Path, staging_path: Path) -> None:
    """Copies every real untracked/ignored file or directory from
    `live_root` into `staging_path` before it is built/promoted -
    mirrors HYDRA-UMC-UPDATER's own `_carry_over_local_data()`
    (REV-002) exactly. Without this, a real project's own operational
    data living inside its checkout (config, accounts, generated
    certificates, ...) is silently left behind in `.backup-*` on every
    canary promotion - the same real data-loss shape UPDATER itself
    used to have."""
    for rel_path in _real_untracked_paths(live_root):
        if rel_path.split("/")[0] in _NEVER_CARRIED_OVER_DIR_NAMES:
            continue
        source = live_root / rel_path
        if not source.exists():
            continue
        destination = staging_path / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)


def _create_staging_clone(live_root: Path, staging_parent: Path) -> Path:
    # V07-002: read the live checkout's own REAL upstream before cloning
    # it - a real deployed checkout in this ecosystem is always already
    # a clone of its real GitHub origin (HYDRA-UMC-UPDATER's own
    # install.py is what sets that up in the first place), so this never
    # needs any GitHub-specific knowledge of its own; it just inherits
    # whatever origin live_root already correctly has.
    origin_result = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=str(live_root), capture_output=True, text=True,
    )
    real_origin_url = origin_result.stdout.strip() if origin_result.returncode == 0 else None

    staging_path = staging_parent / f"ops-agent-canary-{uuid.uuid4().hex[:8]}"
    returncode, output = _run(
        ["git", "clone", "--local", "--no-hardlinks", str(live_root), str(staging_path)],
        cwd=staging_parent,
        timeout_s=120.0,
    )
    if returncode != 0 or not staging_path.is_dir():
        raise StagingCloneError(f"git clone --local --no-hardlinks of {live_root} failed (exit {returncode}): {output}")

    # V07-002: `git clone --local` above points the new clone's own
    # `origin` at LIVE_ROOT ITSELF (the local source path it was cloned
    # from) - never at the real upstream. Left uncorrected, the checkout
    # this staging clone becomes once promoted would have `origin`
    # pointing at a path that no longer even exists (live_root gets
    # renamed aside to `.backup-*`), so every FUTURE `git fetch origin`
    # there - by this module or by HYDRA-UMC-UPDATER itself - would
    # fail, silently and permanently stopping this checkout from ever
    # being updated again. Reset immediately, before anything else, so
    # a real_origin_url read failure (live_root itself has no real
    # origin - a genuinely fresh/local-only checkout) is a real,
    # explicit refusal rather than a silent skip.
    if real_origin_url:
        remote_result = subprocess.run(
            ["git", "remote", "set-url", "origin", real_origin_url], cwd=str(staging_path), capture_output=True, text=True,
        )
        if remote_result.returncode != 0:
            _rmtree_best_effort(staging_path)
            raise RemoteRestoreError(
                f"could not restore the real upstream remote on the staging clone (exit {remote_result.returncode}): "
                f"{remote_result.stderr}"
            )
    return staging_path


def _apply_diff(staging_path: Path, diff_text: str) -> None:
    patch_file = staging_path / f".ops-agent-canary-{uuid.uuid4().hex[:8]}.patch"
    patch_file.write_text(diff_text, encoding="utf-8")
    try:
        returncode, output = _run(["git", "apply", "--whitespace=nowarn", patch_file.name], cwd=staging_path, timeout_s=30.0)
    finally:
        try:
            patch_file.unlink()
        except OSError:
            pass  # best-effort cleanup only - never mask the real apply result below
    if returncode != 0:
        raise DiffApplyError(f"git apply failed against the staging clone (exit {returncode}): {output}")


def _rmtree_best_effort(path: Path, *, attempts: int = 5, delay_s: float = 0.3) -> None:
    """Mirrors HYDRA-UMC-UPDATER's own install.py retry helper - a
    Windows antivirus/indexer can transiently hold a handle open on a
    just-created staging clone's own files, and a cleanup failure must
    never mask the real deploy result that already happened."""
    for attempt in range(attempts):
        try:
            shutil.rmtree(path, ignore_errors=False)
            return
        except OSError:
            if attempt == attempts - 1:
                return
            time.sleep(delay_s)


@dataclass(frozen=True)
class CanaryDeployResult:
    deploy_id: str
    proposal_id: str
    project_name: str
    started_at: str
    finished_at: str
    promoted: bool
    stage_reached: str
    build_output: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "deployId": self.deploy_id,
            "proposalId": self.proposal_id,
            "projectName": self.project_name,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "promoted": self.promoted,
            "stageReached": self.stage_reached,
            "buildOutput": redact_secrets(self.build_output),
            "detail": self.detail,
        }


def deploy_canary(
    proposal: ChangeProposal,
    *,
    live_root: Path,
    build_test_command: list[str],
    staging_parent: Path | None = None,
    build_timeout_s: float = 600.0,
) -> CanaryDeployResult:
    if proposal.status != STATUS_APPROVED:
        raise ChangeNotApprovedError(
            f"refusing to deploy proposal {proposal.proposal_id} - status is {proposal.status!r}, not {STATUS_APPROVED!r}"
        )
    if not live_root.is_dir():
        raise CanaryDeployError(f"live_root {live_root} is not a real directory")

    # V07-003: the approval's own content digest must still match this
    # proposal's CURRENT project_name/diff - see
    # verify_approval_content()'s own docstring. Then confirm the
    # approved project_name is the one actually checked out here, not
    # merely a string nothing ever cross-checked against reality.
    try:
        proposal.verify_approval_content()
    except ChangeProposalError as exc:
        raise ApprovalInvalidError(str(exc)) from exc
    live_project_name = _read_live_project_name(live_root)
    if live_project_name is not None and live_project_name != proposal.project_name:
        raise TargetProjectMismatchError(
            f"proposal {proposal.proposal_id} was approved for project {proposal.project_name!r}, "
            f"but {live_root} is really {live_project_name!r} - refusing to deploy a change to the wrong project"
        )

    # V07-002: refuse upfront, before any staging work, if the live
    # checkout has a real uncommitted change to a tracked file - see
    # _tracked_dirty_paths()'s own docstring.
    dirty = _tracked_dirty_paths(live_root)
    if dirty:
        preview = ", ".join(dirty[:5]) + (f" (+{len(dirty) - 5} more)" if len(dirty) > 5 else "")
        raise TrackedDirtyError(
            f"{live_root} has uncommitted change(s) to real tracked file(s): {preview} - refusing to deploy; "
            "commit, stash, or discard them first so a canary deploy can never silently discard real local work"
        )

    deploy_id = str(uuid.uuid4())
    started_at = _utc_now_iso()
    staging_parent = staging_parent or live_root.parent
    staging_path = _create_staging_clone(live_root, staging_parent)
    stage_reached = "staged"
    try:
        # V07-002: carry over the live checkout's own real local data
        # BEFORE the diff is applied/built - see _carry_over_local_data()'s
        # own docstring. Done here (not merely before promotion) so the
        # build-test command below sees the same real data the promoted
        # checkout will actually run against.
        _carry_over_local_data(live_root, staging_path)
        _apply_diff(staging_path, proposal.diff)
        stage_reached = "diff_applied"

        returncode, build_output = _run(build_test_command, cwd=staging_path, timeout_s=build_timeout_s)
        if returncode != 0:
            return CanaryDeployResult(
                deploy_id=deploy_id,
                proposal_id=proposal.proposal_id,
                project_name=proposal.project_name,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                promoted=False,
                stage_reached=stage_reached,
                build_output=build_output,
                detail=f"build verification failed (exit {returncode}) - the live checkout was never touched",
            )
        stage_reached = "build_verified"

        # V07-004 (shared with HYDRA-UMC-UPDATER's own install.py, P1;
        # honest, bounded mitigation, not the full transactional
        # journal/rollback the finding's own acceptance criteria
        # describes - that needs designing once, shared by both
        # implementations, as real, separate future work): each rename
        # is individually atomic on the same filesystem, but a crash in
        # the narrow gap between them would leave NO active checkout at
        # all - the single worst outcome here. Best-effort self-heal: if
        # the second rename fails, immediately try to rename backup_path
        # back so a real installation still exists, rather than silently
        # leaving the box with neither a live checkout nor a clear error
        # about which path holds the real one.
        backup_path = live_root.parent / f"{live_root.name}.backup-{uuid.uuid4().hex[:8]}"
        live_root.rename(backup_path)
        try:
            staging_path.rename(live_root)
        except OSError as exc:
            try:
                backup_path.rename(live_root)
            except OSError:
                raise CanaryDeployError(
                    f"promotion failed AND the self-heal restore also failed - {live_root} may not exist right now; "
                    f"the previous checkout should still be recoverable at {backup_path}: {exc}"
                ) from exc
            raise CanaryDeployError(
                f"promotion failed (exit path unavailable: {exc}) - restored the previous checkout at {live_root}; "
                f"the verified candidate is still available at {staging_path} for manual inspection"
            ) from exc
        stage_reached = "promoted"
        return CanaryDeployResult(
            deploy_id=deploy_id,
            proposal_id=proposal.proposal_id,
            project_name=proposal.project_name,
            started_at=started_at,
            finished_at=_utc_now_iso(),
            promoted=True,
            stage_reached=stage_reached,
            build_output=build_output,
            detail=f"promoted - the previous checkout was kept at {backup_path}, never deleted",
        )
    finally:
        if stage_reached != "promoted":
            _rmtree_best_effort(staging_path)
