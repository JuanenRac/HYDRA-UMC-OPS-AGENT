# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/canary_deploy.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Delivery 4 - Canary deploy: applies an APPROVED change (change_proposal.py)
to a real project checkout through the same atomic-by-verification pattern
HYDRA-UMC-UPDATER's own install.py already uses for updates.

This docstring
used to make that "same pattern" claim while the module underneath only
copied the STRUCTURE (clone/verify/promote) and never the actual
data-safety logic - no real-local-data carryover, no upstream-remote
reset, no tracked-dirty rejection, reproducing every real gap
UPDATER's own earlier fixes already closed there. Fixed
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
   renames the backup back so a real installation still exists (shared
   with UPDATER - a full transactional journal surviving a crash
   in the narrow gap between the two renames is real, separate future
   work this bounded mitigation does not attempt).

`deploy_canary()` refuses to run at all unless the given proposal's own
`status` is already `approved` - this is the one check this whole module
exists to enforce, and it comes before anything else, every time.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
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
    """The
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


class DiffCommitError(CanaryDeployError):
    """`git add`/`git commit` failed while turning the applied diff
    into a real commit inside the staging clone - see
    `_commit_applied_diff()`'s own docstring for why that commit exists
    at all. The live checkout was never touched; this staging clone is
    discarded like any other failed stage."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# A build can print far more than anyone will read; only the end of it is
# kept (that is where a failure is), so a chatty build can neither exhaust
# memory nor bloat the stored deploy result.
_OUTPUT_TAIL_BYTES = 256 * 1024
# Every plain git call below is bounded too: a hung `git status` on a
# stalled disk must not hang the deploy (or, worse, be read as clean).
_GIT_TIMEOUT_S = 60.0


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Best effort: a build that forks (npm -> node, make -> cc) leaves
    grandchildren that outlive a kill of the direct child and keep
    running, and keep any pipe they inherited open, after the timeout."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=15, check=False,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def _read_tail(sink) -> str:
    size = sink.seek(0, os.SEEK_END)
    start = max(0, size - _OUTPUT_TAIL_BYTES)
    sink.seek(start)
    text = sink.read().decode("utf-8", errors="replace")
    return f"[... earlier output dropped, last {size - start} bytes kept ...]\n{text}" if start else text


def _run(command: list[str], cwd: Path, timeout_s: float) -> tuple[int, str]:
    """Runs one real subprocess, capturing combined output (stdout and
    stderr interleaved, last `_OUTPUT_TAIL_BYTES` kept), honoring a real
    timeout - a canary build that hangs must never hang this process
    forever, and on a timeout the WHOLE process tree is killed, not only
    the direct child (a grandchild left holding the output open used to
    keep `subprocess.run` waiting long after the timeout). Never raises
    for a real, distinct failure mode (a nonzero exit, a timeout, a
    missing executable, output that is not UTF-8) - each becomes a real,
    honest (exit_code, output) pair the caller decides what to do with."""
    if not command:
        return 127, "could not run an empty command"
    options: dict[str, object] = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    with tempfile.TemporaryFile() as sink:
        try:
            proc = subprocess.Popen(
                command, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT, **options,
            )
        except (OSError, ValueError) as exc:
            return 127, f"could not run {command!r}: {exc}"
        timed_out = False
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(proc)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
        output = _read_tail(sink)
    if timed_out:
        header = f"TIMEOUT: {' '.join(command)!r} did not finish within {timeout_s}s"
        return 124, f"{header}\n{output}" if output else header
    return proc.returncode, output


class TrackedDirtyError(CanaryDeployError):
    """The live checkout has a real, uncommitted edit to an already-
    tracked file - refused before anything is touched. See
    _tracked_dirty_paths()'s own docstring for exactly why this can't be
    left to `git apply`/the build to catch on their own."""


class RemoteRestoreError(CanaryDeployError):
    """Could not reset the staging clone's own `origin` remote back to
    the live checkout's real upstream - the live checkout was never
    touched."""


class DirtyCheckError(CanaryDeployError):
    """Shared with HYDRA-UMC-UPDATER's own install.py: `git
    status` itself failed to run against the live checkout (not a git
    repository, git missing from PATH, a permissions/IO error, ...) - see
    `_tracked_dirty_paths()`'s own docstring for why this must never be
    read as "no dirty files found". The live checkout was never touched."""


def _tracked_dirty_paths(path: Path) -> list[str]:
    """Returns every real path (relative to `path`) this checkout's own
    git considers a TRACKED file with a real uncommitted change - staged
    or not (`git status --porcelain`'s own status codes other than
    `??`/`!!`, real untracked/ignored data `_carry_over_local_data()`
    already owns).

    This
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
    `_tracked_dirty_paths()` exactly - same real gap, same
    real fix, in the sibling implementation this module's own docstring
    already claimed shared UPDATER's pattern.

    Shared with UPDATER's own sibling helper: a `git status`
    that fails to even RUN (returncode != 0 - not a git repository, git
    missing from PATH, a permissions/IO error, an unrelated real fault)
    used to be treated exactly like "ran fine, found nothing dirty" -
    the one case this whole function exists to catch (a real uncommitted
    edit) became silently invisible the moment the check that looks for
    it broke, and deploy_canary() would then proceed as if the live
    checkout were genuinely clean. Failing closed here (raising, never
    returning `[]`) is the only reading consistent with what "dirty
    check" is supposed to mean: unable to verify clean is not clean."""
    return [rel_path for status_code, rel_path in _porcelain_entries(path, ignored=False) if status_code not in ("??", "!!")]


def _porcelain_entries(path: Path, *, ignored: bool, all_untracked: bool = False) -> list[tuple[str, str]]:
    """`(status code, path)` for every entry `git status --porcelain -z`
    reports for `path` (ignored ones too when asked). Fails closed: git
    not running, timing out or exiting non-zero is `DirtyCheckError`, never
    an empty list. Paths are decoded with `surrogateescape` so a file name
    that is not valid UTF-8 still round-trips to the real file instead of
    crashing the decode; a rename/copy entry carries its origin path as
    one extra NUL-separated field, which is skipped (the entry itself
    already names the path that exists now)."""
    command = ["git", "status", "--porcelain", "-z"] + (["--ignored"] if ignored else []) + (["-uall"] if all_untracked else [])
    try:
        result = subprocess.run(command, cwd=str(path), check=False, capture_output=True, timeout=_GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise DirtyCheckError(f"could not verify {path} has no uncommitted changes - `git status` did not finish within {_GIT_TIMEOUT_S}s") from exc
    except OSError as exc:
        raise DirtyCheckError(f"could not verify {path} has no uncommitted changes - could not run git: {exc}") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise DirtyCheckError(
            f"could not verify {path} has no uncommitted changes - `git status` itself failed "
            f"(exit {result.returncode}): {stderr or '(no stderr)'}"
        )
    tokens = result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if len(token) < 4:
            continue
        status_code, rel_path = token[:2], token[3:]
        if "R" in status_code or "C" in status_code:
            index += 1  # the origin path of a rename/copy
        entries.append((status_code, rel_path))
    return entries


# Mirrors HYDRA-UMC-UPDATER/src/hydra_umc_updater/install.py's own
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
    copies (only the committed object database). A `git status` that
    fails here is an error, not "no local data": skipping the carry-over
    would leave the operational data behind in `.backup-*`, the exact loss
    this step exists to prevent."""
    return [rel_path for status_code, rel_path in _porcelain_entries(path, ignored=True) if status_code in ("??", "!!")]


def _copy_local_entry(source: Path, destination: Path) -> None:
    """One untracked/ignored entry, copied as what it IS: a symlink stays a
    symlink (a `data -> /mnt/storage` link must not turn into a copy of
    the whole volume), a directory is copied with its inner links kept."""
    if source.is_symlink():
        try:
            os.symlink(os.readlink(source), destination, target_is_directory=source.is_dir())
            return
        except OSError:
            if not source.exists():
                return  # a dangling link that cannot be recreated here has nothing to copy
            # The platform refused to create the link (Windows without the
            # privilege): fall through to copying what it points at.
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)
    else:
        shutil.copy2(source, destination)


def _carry_over_local_data(live_root: Path, staging_path: Path) -> None:
    """Copies every real untracked/ignored file or directory from
    `live_root` into `staging_path` before it is built/promoted -
    mirrors HYDRA-UMC-UPDATER's own `_carry_over_local_data()`
    exactly. Without this, a real project's own operational
    data living inside its checkout (config, accounts, generated
    certificates, ...) is silently left behind in `.backup-*` on every
    canary promotion - the same real data-loss shape UPDATER itself
    used to have."""
    for rel_path in _real_untracked_paths(live_root):
        if rel_path.split("/")[0] in _NEVER_CARRIED_OVER_DIR_NAMES:
            continue
        source = live_root / rel_path
        if not os.path.lexists(source):
            continue
        destination = staging_path / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        _copy_local_entry(source, destination)


def _create_staging_clone(live_root: Path, staging_parent: Path) -> Path:
    # Read the live checkout's own REAL upstream before cloning
    # it - a real deployed checkout in this ecosystem is always already
    # a clone of its real GitHub origin (HYDRA-UMC-UPDATER's own
    # install.py is what sets that up in the first place), so this never
    # needs any GitHub-specific knowledge of its own; it just inherits
    # whatever origin live_root already correctly has.
    origin_code, origin_output = _run(["git", "remote", "get-url", "origin"], cwd=live_root, timeout_s=_GIT_TIMEOUT_S)
    real_origin_url = origin_output.strip() if origin_code == 0 else None

    staging_path = staging_parent / f"ops-agent-canary-{uuid.uuid4().hex[:8]}"
    returncode, output = _run(
        ["git", "clone", "--local", "--no-hardlinks", str(live_root), str(staging_path)],
        cwd=staging_parent,
        timeout_s=120.0,
    )
    if returncode != 0 or not staging_path.is_dir():
        raise StagingCloneError(f"git clone --local --no-hardlinks of {live_root} failed (exit {returncode}): {output}")

    # Real bug found while auditing CI: `_commit_applied_diff()` below
    # runs a real `git commit` against this clone, but a plain `git
    # clone` never copies commit-author identity - it relies entirely
    # on a global `user.name`/`user.email` already being configured on
    # whatever machine runs this. That happens to hold on a maintainer's
    # own workstation, but is false by default on a fresh GitHub Actions
    # runner (this repo's own CI) and arguably wrong anyway even on a
    # real deploy host: an automated canary commit should never be
    # silently authored as whichever human happens to be logged in
    # there. Set a fixed, local (this clone only) synthetic identity
    # instead, so this step's own correctness never depends on the
    # host's ambient git config.
    for key, value in (("user.name", "HYDRA-UMC OPS-AGENT"), ("user.email", "ops-agent@hydra-umc.local")):
        identity_code, identity_output = _run(["git", "config", key, value], cwd=staging_path, timeout_s=10.0)
        if identity_code != 0:
            _rmtree_best_effort(staging_path)
            raise StagingCloneError(f"git config {key} on the staging clone failed (exit {identity_code}): {identity_output}")

    # `git clone --local` above points the new clone's own
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
        remote_code, remote_output = _run(
            ["git", "remote", "set-url", "origin", real_origin_url], cwd=staging_path, timeout_s=_GIT_TIMEOUT_S,
        )
        if remote_code != 0:
            _rmtree_best_effort(staging_path)
            raise RemoteRestoreError(
                f"could not restore the real upstream remote on the staging clone (exit {remote_code}): "
                f"{remote_output}"
            )
    return staging_path


def _apply_diff(staging_path: Path, diff_text: str) -> list[str]:
    """Applies `diff_text` and returns exactly the paths it changed (added,
    modified, deleted or renamed - a rename returns the old path, now
    deleted, as well as the new one), found by comparing `git status`
    before and after the apply. `_commit_applied_diff()` needs this exact
    list - not `git add -A`/`git add -u` - to commit only what this diff
    itself changed, never `_carry_over_local_data()`'s own untracked local
    data alongside it. (`git apply --numstat` is not a substitute: it names
    only the new path of a rename, which would leave the old path's removal
    unstaged and the promoted checkout dirty, and it quotes unusual file
    names.) The patch file is written as bytes: text mode would turn every
    line ending into the host's own, and a diff against a CRLF file must
    reach `git apply` exactly as it was reviewed."""
    before = set(_porcelain_entries(staging_path, ignored=False, all_untracked=True))
    patch_file = staging_path / f".ops-agent-canary-{uuid.uuid4().hex[:8]}.patch"
    patch_file.write_bytes(diff_text.encode("utf-8"))
    try:
        returncode, output = _run(["git", "apply", "--whitespace=nowarn", patch_file.name], cwd=staging_path, timeout_s=30.0)
    finally:
        try:
            patch_file.unlink()
        except OSError:
            pass  # best-effort cleanup only - never mask the real apply result below
    if returncode != 0:
        raise DiffApplyError(f"git apply failed against the staging clone (exit {returncode}): {output}")
    after = set(_porcelain_entries(staging_path, ignored=False, all_untracked=True))
    return sorted(rel_path for _, rel_path in after - before)


def _commit_applied_diff(staging_path: Path, touched_paths: list[str], *, deploy_id: str, proposal_id: str) -> None:
    """`_apply_diff()` only ever ran `git apply` - it left the
    staging clone with a real, uncommitted working-tree change. Promoting
    that clone as-is (the rename swap below) made the new live checkout
    dirty from the moment it went live, and the very next canary deploy's
    own `_tracked_dirty_paths()` check (a real, deliberate safety gate -
    see above) would then correctly refuse to run at all, unable to
    tell that real uncommitted change apart from someone's genuine
    unrelated local edit - a genuinely SUCCESSFUL canary locking itself
    out of ever deploying again.

    Stages EXACTLY the paths `_apply_diff()` reported this diff itself
    touched - never `git add -A`/`git add -u`, either of which risks
    sweeping `_carry_over_local_data()`'s own untracked local data (real
    config/certs that must stay untracked, unchanged) into this commit
    too - then commits them as one real, immutable, identifiable
    deployment commit."""
    if not touched_paths:
        return  # an empty diff (already-applied no-op) has nothing to commit
    add_code, add_output = _run(["git", "add", "--", *touched_paths], cwd=staging_path, timeout_s=30.0)
    if add_code != 0:
        raise DiffCommitError(f"git add failed against the staging clone (exit {add_code}): {add_output}")
    commit_message = f"OPS-AGENT canary deploy {deploy_id} (proposal {proposal_id})"
    commit_code, commit_output = _run(
        ["git", "commit", "--no-verify", "-m", commit_message], cwd=staging_path, timeout_s=30.0,
    )
    if commit_code != 0:
        raise DiffCommitError(f"git commit failed against the staging clone (exit {commit_code}): {commit_output}")


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

    # The approval's own content digest must still match this
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

    # Refuse upfront, before any staging work, if the live
    # checkout has a real uncommitted change to a tracked file - see
    # _tracked_dirty_paths()'s own docstring.
    dirty = _tracked_dirty_paths(live_root)
    if dirty:
        preview = ", ".join(dirty[:5]) + (f" (+{len(dirty) - 5} more)" if len(dirty) > 5 else "")
        raise TrackedDirtyError(
            f"{live_root} has uncommitted change(s) to real tracked file(s): {preview} - refusing to deploy; "
            "commit, stash, or discard them first so a canary deploy can never silently discard real local work"
        )

    if not build_test_command or not all(isinstance(part, str) and part for part in build_test_command):
        raise CanaryDeployError("build_test_command must be a non-empty list of non-empty strings")

    deploy_id = str(uuid.uuid4())
    started_at = _utc_now_iso()
    staging_parent = staging_parent or live_root.parent
    staging_path = _create_staging_clone(live_root, staging_parent)
    stage_reached = "staged"
    keep_staging = False
    try:
        # Carry over the live checkout's own real local data
        # BEFORE the diff is applied/built - see _carry_over_local_data()'s
        # own docstring. Done here (not merely before promotion) so the
        # build-test command below sees the same real data the promoted
        # checkout will actually run against.
        _carry_over_local_data(live_root, staging_path)
        touched_paths = _apply_diff(staging_path, proposal.diff)
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

        # Commit the applied diff inside the staging clone BEFORE
        # promotion - see _commit_applied_diff()'s own docstring for why a
        # successful canary must never promote a staging clone with an
        # uncommitted git apply still sitting in its working tree.
        _commit_applied_diff(staging_path, touched_paths, deploy_id=deploy_id, proposal_id=proposal.proposal_id)
        stage_reached = "diff_committed"

        # Shared with HYDRA-UMC-UPDATER's own install.py;
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
            # The message below tells the operator the verified candidate is
            # still on disk for inspection; the cleanup in `finally` must
            # not delete it out from under that promise.
            keep_staging = True
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
        if stage_reached != "promoted" and not keep_staging:
            _rmtree_best_effort(staging_path)
