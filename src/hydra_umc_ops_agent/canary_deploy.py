# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/canary_deploy.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
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
-1. Refuse unless the proposal carries a valid SIGNED approval: an Ed25519
   signature by a registered approver over the exact diff, not expired, and
   given for the commit the live checkout is on now (change_proposal.py).
   Refuse a diff that touches the files that decide how a change is checked
   (CI, build-test scripts, service units) unless the approver signed that.
0. Refuse upfront if the live checkout has a real uncommitted edit to
   an already-tracked file - before any staging work at all.
1. Clone the live checkout into an independent local staging directory
   (`git clone --local --no-hardlinks` - the live checkout is never
   touched yet), then reset that clone's own `origin` to the live
   checkout's real upstream (a plain `--local` clone would otherwise
   leave it pointing at the live path itself).
2. Apply the approved proposal's own diff to that staging clone
   (`git apply`) - if this fails, the live checkout was never touched.
3. Carry over the live checkout's own real untracked/ignored local data
   (config, generated certificates, ... - never a build-artifact
   directory, at any depth) into the staging clone; a file the diff itself
   adds or changes wins over a local file of the same name.
4. Run the project's own real build-test command inside the staging
   clone, with a minimal environment (no tokens, keys or credentials of
   the operator). A failure here is a real, expected possible outcome (that
   is the whole point of staging first) - reported back, never raised as
   an exception, and the live checkout is still never touched.
5. Only if that build passes: with `service_unit` given, stop the service;
   check again that the live checkout is still clean and copy its local data
   once more (it may have changed during the build); then two back-to-back
   renames swap the staging clone in for the live checkout, keeping the
   previous one at a real `.backup-<id>` path - never deleted. A durable
   promotion journal (the optional HYDRA-UMC-SDK one) records the swap so
   `recover_interrupted_promotions()` can heal a crash between the renames.
   If the second rename fails, a best-effort self-heal renames the backup
   back so a real installation still exists.
6. With `service_unit` / `health_url` given: start the service and wait for
   its health check. If it does not become healthy in time, the previous
   checkout is put back (the failed one is kept aside) and the service is
   started again: stage `rolled_back`, `promoted` false.

`deploy_canary()` refuses to run at all unless the given proposal's own
`status` is already `approved` - this is the one check this whole module
exists to enforce, and it comes before anything else, every time.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .audit_journal import AuditJournalError, append_event
from .change_proposal import STATUS_APPROVED, ChangeProposal, ChangeProposalError
from .diff_policy import protected_paths_in, touched_paths as diff_touched_paths
from .inventory import check_http_health, read_git_commit_hash, validate_unit_name
from .log_redaction import redact_secrets

try:  # optional: HYDRA-UMC-SDK's durable promotion journal (the `sdk` extra)
    from hydra_umc_sdk.promotion_journal import PromotionJournal, PromotionPhase
    from hydra_umc_sdk.promotion_journal import recover as _recover_promotions

    _HAS_PROMOTION_JOURNAL = True
except ImportError:  # pragma: no cover - depends on the environment
    _HAS_PROMOTION_JOURNAL = False

_PROMOTION_JOURNAL_NAME = ".hydra_umc_ops_agent_promotion_journal.json"
_AUDIT_JOURNAL_NAME = ".hydra_umc_ops_agent_audit.jsonl"


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


class ProtectedPathsError(CanaryDeployError):
    """The diff touches files that decide how a change is checked or run
    and the signed approval does not allow that."""


class ServiceControlError(CanaryDeployError):
    """The service could not be stopped before the swap; nothing was changed."""


class StagingCloneError(CanaryDeployError):
    """Could not create an independent local staging clone of the live
    project checkout - the live checkout was never touched."""


class DiffApplyError(CanaryDeployError):
    """`git apply` rejected the proposal's own diff against the staging
    clone - the live checkout was never touched."""


class CanaryPendingError(CanaryDeployError):
    """A previous canary is still in this checkout as an uncommitted change (it was deployed without a local
    commit). Another canary would build on a clone that does not have it and replace it silently, so it is
    refused until the change is dropped (`control canary-clear`) or reaches the checkout through an update."""


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


def _run(command: list[str], cwd: Path, timeout_s: float, env: Mapping[str, str] | None = None) -> tuple[int, str]:
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
                command, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT,
                env=None if env is None else dict(env), **options,
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
    command = ["git", "status", "--porcelain", "-z"] + (["--ignored=matching"] if ignored else []) + (["-uall"] if all_untracked else [])
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
        if os.path.lexists(destination) and destination.is_symlink():
            # Already linked by an earlier pass (the data is copied once before
            # the build and once more just before the swap): replace the link
            # of the staging clone, never follow it.
            try:
                destination.unlink()
            except OSError:
                return
        try:
            os.symlink(os.readlink(source), destination, target_is_directory=source.is_dir())
            return
        except OSError:
            if not source.exists():
                return  # a dangling link that cannot be recreated here has nothing to copy
            # The platform refused to create the link (Windows without the
            # privilege): fall through to copying what it points at.
    if source.is_dir():
        shutil.copytree(
            source, destination, dirs_exist_ok=True, symlinks=True,
            ignore=shutil.ignore_patterns(*_NEVER_CARRIED_OVER_DIR_NAMES),
        )
    else:
        shutil.copy2(source, destination)


def _carry_over_local_data(live_root: Path, staging_path: Path, skip: Sequence[str] = ()) -> None:
    """Copies every real untracked/ignored file or directory from
    `live_root` into `staging_path` before it is built/promoted -
    mirrors HYDRA-UMC-UPDATER's own `_carry_over_local_data()`
    exactly. Without this, a real project's own operational
    data living inside its checkout (config, accounts, generated
    certificates, ...) is silently left behind in `.backup-*` on every
    canary promotion - the same real data-loss shape UPDATER itself
    used to have."""
    skipped = [path.rstrip("/") for path in skip]
    for rel_path in _real_untracked_paths(live_root):
        parts = rel_path.rstrip("/").split("/")
        # Regenerable build output is skipped wherever it sits in the path.
        if any(part in _NEVER_CARRIED_OVER_DIR_NAMES for part in parts):
            continue
        # A path the approved diff itself adds or changes is the diff's, not the live file's.
        candidate = rel_path.rstrip("/")
        if any(candidate == path or candidate.startswith(path + "/") or path.startswith(candidate + "/") for path in skipped):
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

    # Hidden, so `edge collect` never reports it as a second copy of the
    # project while a build runs, and private to the user running the deploy:
    # it holds a copy of the live checkout's local data.
    staging_path = staging_parent / f".ops-agent-canary-{uuid.uuid4().hex[:8]}"
    returncode, output = _run(
        ["git", "clone", "--local", "--no-hardlinks", str(live_root), str(staging_path)],
        cwd=staging_parent,
        timeout_s=120.0,
    )
    if returncode != 0 or not staging_path.is_dir():
        raise StagingCloneError(f"git clone --local --no-hardlinks of {live_root} failed (exit {returncode}): {output}")
    if os.name != "nt":
        try:
            os.chmod(staging_path, 0o700)
        except OSError:
            pass

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
    else:
        # The live checkout has no upstream. The clone's `origin` would point
        # at the live path - which becomes the backup after the swap - so
        # later fetches would quietly "work" against a stale copy forever.
        # Better no remote at all.
        remote_code, remote_output = _run(["git", "remote", "remove", "origin"], cwd=staging_path, timeout_s=_GIT_TIMEOUT_S)
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


_PENDING_MARKER = "ops-agent-canary-pending.json"


def _git_dir(path: Path) -> Path:
    code, output = _run(["git", "rev-parse", "--absolute-git-dir"], cwd=path, timeout_s=30.0)
    if code != 0 or not output.strip():
        raise CanaryDeployError(f"could not find the git directory of {path}: {output.strip()}")
    return Path(output.strip().splitlines()[-1])


def pending_canary(live_root: Path) -> dict[str, Any] | None:
    """The record of a canary that is in the checkout without a local commit, or None."""
    try:
        marker = _git_dir(live_root) / _PENDING_MARKER
        return json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else None
    except (CanaryDeployError, OSError, ValueError):
        return None


_EXCLUDE_BEGIN = "# ops-agent canary begin"
_EXCLUDE_END = "# ops-agent canary end"
_GITIGNORE_SPECIAL = set("\[]*?!#")


def _exclude_line(name: str) -> str:
    """A rule of .git/info/exclude that names exactly one path from the top of the checkout."""
    return "/" + "".join(("\\" + ch) if ch in _GITIGNORE_SPECIAL else ch for ch in name)


def _write_exclude(git_dir: Path, names: list[str]) -> None:
    """Keep the files a canary created out of `git status` with a local ignore block (the checkout stays clean)."""
    exclude = git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    lines = existing.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    block = [_EXCLUDE_BEGIN, *[_exclude_line(name) for name in names], _EXCLUDE_END]
    exclude.write_text("\n".join(lines + block) + "\n", encoding="utf-8")


def _remove_exclude(git_dir: Path) -> None:
    exclude = git_dir / "info" / "exclude"
    if not exclude.is_file():
        return
    kept, inside = [], False
    for line in exclude.read_text(encoding="utf-8").split("\n"):
        if line == _EXCLUDE_BEGIN:
            inside = True
        elif line == _EXCLUDE_END:
            inside = False
        elif not inside:
            kept.append(line)
    exclude.write_text("\n".join(kept), encoding="utf-8")


def _leave_canary_uncommitted(staging_path: Path, touched_paths: list[str], *, deploy_id: str, patch_file: Path | None) -> None:
    """Take the canary commit back out of the staging clone, keeping its change in the working tree.

    The checkout then has no local commit, so the updater's fast-forward is never blocked by one. The tracked
    files the diff changed are marked `skip-worktree`, which keeps `git status` clean (the dirty check of the next
    deploy and of the updater do not trip on them) while the change stays in place; the files it created stay
    untracked. A record next to the git data names the deploy, the patch file and both lists so the change can be
    dropped knowingly (`clear_pending_canary`)."""
    if not touched_paths:
        return
    steps = (
        ["git", "reset", "--soft", "HEAD~1"],
        ["git", "reset", "-q", "HEAD", "--", *touched_paths],
    )
    for command in steps:
        code, output = _run(command, cwd=staging_path, timeout_s=30.0)
        if code != 0:
            raise DiffCommitError(f"{' '.join(command[:3])} failed against the staging clone (exit {code}): {output}")
    code, listing = _run(["git", "ls-files", "-z", "--", *touched_paths], cwd=staging_path, timeout_s=30.0)
    tracked = [name for name in listing.split("\0") if name] if code == 0 else []
    if tracked:
        code, output = _run(["git", "update-index", "--skip-worktree", "--", *tracked], cwd=staging_path, timeout_s=30.0)
        if code != 0:
            raise DiffCommitError(f"git update-index failed against the staging clone (exit {code}): {output}")
    created = [name for name in touched_paths if name not in tracked and (staging_path / name).exists()]
    if created:
        # the files the canary created stay untracked; a local ignore rule keeps `git status` clean for them too
        _write_exclude(_git_dir(staging_path), created)
    record = {"deployId": deploy_id, "patch": str(patch_file) if patch_file else None, "tracked": tracked, "created": created}
    (_git_dir(staging_path) / _PENDING_MARKER).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def clear_pending_canary(live_root: Path) -> dict[str, Any]:
    """Drop a canary that was deployed without a local commit: the changed files go back to what the checkout
    commit holds and the files the canary created are removed. Returns what was done."""
    record = pending_canary(live_root)
    if record is None:
        raise CanaryDeployError(f"{live_root} has no pending canary")
    tracked, created = list(record.get("tracked") or []), list(record.get("created") or [])
    if tracked:
        for command in (["git", "update-index", "--no-skip-worktree", "--", *tracked], ["git", "checkout", "HEAD", "--", *tracked]):
            code, output = _run(command, cwd=live_root, timeout_s=60.0)
            if code != 0:
                raise CanaryDeployError(f"{' '.join(command[:3])} failed (exit {code}): {output}")
    _remove_exclude(_git_dir(live_root))
    root = live_root.resolve()
    for name in created:
        target = (live_root / name).resolve()
        if root in target.parents and target.is_file():
            target.unlink()
    (_git_dir(live_root) / _PENDING_MARKER).unlink()
    return {"deployId": record.get("deployId"), "restored": tracked, "removed": created, "patch": record.get("patch")}


def _save_canary_patch(staging_path: Path, patch_dir: Path, deploy_id: str, touched_paths: list[str]) -> Path | None:
    """Writes the canary commit as a patch file OUTSIDE the checkout (`git format-patch`), so that the change that went
    live is kept as a plain file as well as a local commit. A node whose checkout carries the local commit can no
    longer fast-forward to upstream; with the patch the operator (or the updater) can see exactly what the commit holds,
    check whether upstream already contains it (`git apply --check --reverse`) and drop the commit with confidence.
    Best effort: a failure to write it never changes the result of the deploy."""
    if not touched_paths:
        return None
    code, output = _run(["git", "format-patch", "-1", "HEAD", "--stdout"], cwd=staging_path, timeout_s=30.0)
    if code != 0 or not output.strip():
        return None
    try:
        patch_dir.mkdir(parents=True, exist_ok=True)
        target = patch_dir / f"{deploy_id}.patch"
        target.write_bytes(output.encode("utf-8"))
    except OSError:
        return None
    return target


def _make_writable_and_retry(function, target, *_ignored) -> None:
    """rmtree error handler: git writes its objects read-only, which makes the
    removal of a clone that has had a commit made in it fail on Windows. Make
    the file and its folder writable and try that one removal again."""
    try:
        os.chmod(target, stat.S_IRWXU)
        os.chmod(os.path.dirname(target) or ".", stat.S_IRWXU)
        function(target)
    except OSError:
        pass


def _rmtree_best_effort(path: Path, *, attempts: int = 5, delay_s: float = 0.3) -> None:
    """Mirrors HYDRA-UMC-UPDATER's own install.py retry helper - a
    Windows antivirus/indexer can transiently hold a handle open on a
    just-created staging clone's own files, and a cleanup failure must
    never mask the real deploy result that already happened."""
    for attempt in range(attempts):
        try:
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=_make_writable_and_retry)
            else:
                shutil.rmtree(path, onerror=_make_writable_and_retry)
            return
        except FileNotFoundError:
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
    backup_path: str | None = None
    # The canary commit as a patch file kept outside the checkout; None when none was written.
    patch_path: str | None = None

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
            "backupPath": self.backup_path,
            "patchPath": self.patch_path,
        }


# What a build-test command gets to see of the operator's environment. Everything
# else - API keys, tokens, SSH agent sockets, cloud credentials - is left out, so
# a build script (which the approved diff could change) cannot read or send them.
_BUILD_ENV_KEEP = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "OS", "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TZ", "TEMP", "TMP", "TMPDIR",
)


def build_environment(home: Path, allow: Sequence[str] = ()) -> dict[str, str]:
    """The minimal environment of a build-test run: the variables a toolchain
    cannot start without, a private empty HOME, and whatever names the operator
    explicitly lists in `allow`."""
    environment = {name: os.environ[name] for name in _BUILD_ENV_KEEP if name in os.environ}
    environment["HOME"] = str(home)
    environment["USERPROFILE"] = str(home)
    for name in allow:
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def _systemctl(action: str, unit: str, cwd: Path) -> tuple[int, str]:
    return _run(["systemctl", action, "--", unit], cwd=cwd, timeout_s=60.0)


def _wait_until_healthy(service_unit: str | None, health_url: str | None, timeout_s: float, cwd: Path) -> tuple[bool, str]:
    """Polls the health URL (or, with none, `systemctl is-active`) until it
    answers healthy or `timeout_s` has passed."""
    deadline = time.monotonic() + timeout_s
    detail = "no health check configured"
    while True:
        if health_url:
            outcome = check_http_health(health_url, timeout_s=5.0)
            healthy, detail = outcome.reachable, outcome.detail
        elif service_unit:
            code, output = _systemctl("is-active", service_unit, cwd)
            healthy, detail = code == 0, output.strip() or f"systemctl is-active exited {code}"
        else:
            return True, detail
        if healthy:
            return True, detail
        if time.monotonic() >= deadline:
            return False, detail
        time.sleep(min(2.0, max(0.1, deadline - time.monotonic())))


def _audit(audit_path: Path, event: str, data: dict[str, object]) -> None:
    append_event(audit_path, event, data)


def deploy_canary(
    proposal: ChangeProposal,
    *,
    live_root: Path,
    build_test_command: list[str],
    approvers: Mapping[str, Any],
    staging_parent: Path | None = None,
    build_timeout_s: float = 600.0,
    build_env_allow: Sequence[str] = (),
    service_unit: str | None = None,
    health_url: str | None = None,
    health_timeout_s: float = 30.0,
    audit_path: Path | None = None,
    journal_path: Path | None = None,
    keep_local_commit: bool = False,
) -> CanaryDeployResult:
    """Applies an approved proposal to a staged clone, verifies it and promotes
    it. By default the promoted checkout carries the change WITHOUT a local commit (the commit is only used inside
    the staging clone; the change is kept as a patch file and the checkout stays able to fast-forward to upstream);
    `keep_local_commit=True` keeps the commit in the checkout as before. `approvers` is the registry of approvers' public keys (see
    approval_signing.load_approvers): without a signature by one of them the
    deploy refuses. The outcome is always written to the audit journal
    (`audit_path`, by default a hidden file next to the checkout)."""
    audit_path = audit_path or live_root.parent / _AUDIT_JOURNAL_NAME
    try:
        return _deploy_canary(
            proposal, live_root=live_root, build_test_command=build_test_command, approvers=approvers,
            staging_parent=staging_parent, build_timeout_s=build_timeout_s, build_env_allow=build_env_allow,
            service_unit=service_unit, health_url=health_url, health_timeout_s=health_timeout_s,
            audit_path=audit_path, journal_path=journal_path, keep_local_commit=keep_local_commit,
        )
    except CanaryDeployError as exc:
        try:
            _audit(audit_path, "deploy-refused", {
                "proposalId": proposal.proposal_id, "projectName": proposal.project_name,
                "liveRoot": str(live_root), "reason": str(exc)[:500],
            })
        except (AuditJournalError, OSError):
            pass  # the refusal itself is what the caller reports; nothing was changed
        raise


def _deploy_canary(
    proposal: ChangeProposal,
    *,
    live_root: Path,
    build_test_command: list[str],
    approvers: Mapping[str, Any],
    staging_parent: Path | None,
    build_timeout_s: float,
    build_env_allow: Sequence[str],
    service_unit: str | None,
    health_url: str | None,
    health_timeout_s: float,
    audit_path: Path,
    journal_path: Path | None,
    keep_local_commit: bool = False,
) -> CanaryDeployResult:
    if proposal.status != STATUS_APPROVED:
        raise ChangeNotApprovedError(
            f"refusing to deploy proposal {proposal.proposal_id} - status is {proposal.status!r}, not {STATUS_APPROVED!r}"
        )
    if not live_root.is_dir():
        raise CanaryDeployError(f"live_root {live_root} is not a real directory")

    # The approval must be a valid SIGNATURE of a registered approver over the
    # proposal as it is today, not expired and given for this checkout's
    # commit - a status field proves nothing, anyone able to write the file
    # could set it. Then confirm the approved project_name is the one actually
    # checked out here.
    try:
        proposal.verify_signed_approval(approvers, live_base_commit=read_git_commit_hash(live_root))
    except ChangeProposalError as exc:
        raise ApprovalInvalidError(str(exc)) from exc
    live_project_name = _read_live_project_name(live_root)
    if live_project_name is not None and live_project_name != proposal.project_name:
        raise TargetProjectMismatchError(
            f"proposal {proposal.proposal_id} was approved for project {proposal.project_name!r}, "
            f"but {live_root} is really {live_project_name!r} - refusing to deploy a change to the wrong project"
        )
    protected = protected_paths_in(proposal.diff)
    if protected and not proposal.allow_protected_paths:
        raise ProtectedPathsError(
            "the diff touches files that decide how a change is checked or run "
            f"({', '.join(protected[:5])}) and the signed approval does not allow that"
        )

    # Refuse upfront, before any staging work, if the live
    # checkout has a real uncommitted change to a tracked file - see
    # _tracked_dirty_paths()'s own docstring.
    pending = pending_canary(live_root)
    if pending is not None:
        raise CanaryPendingError(
            f"{live_root} still carries canary {pending.get('deployId')} without a local commit (patch: {pending.get('patch')}); "
            "drop it with `control canary-clear` or let an update replace it before another canary"
        )
    dirty = _tracked_dirty_paths(live_root)
    if dirty:
        preview = ", ".join(dirty[:5]) + (f" (+{len(dirty) - 5} more)" if len(dirty) > 5 else "")
        raise TrackedDirtyError(
            f"{live_root} has uncommitted change(s) to real tracked file(s): {preview} - refusing to deploy; "
            "commit, stash, or discard them first so a canary deploy can never silently discard real local work"
        )

    if not build_test_command or not all(isinstance(part, str) and part for part in build_test_command):
        raise CanaryDeployError("build_test_command must be a non-empty list of non-empty strings")
    if service_unit is not None:
        try:
            validate_unit_name(service_unit)
        except ValueError as exc:
            raise CanaryDeployError(str(exc)) from exc

    deploy_id = str(uuid.uuid4())
    started_at = _utc_now_iso()
    try:
        _audit(audit_path, "deploy-start", {
            "deployId": deploy_id, "proposalId": proposal.proposal_id, "projectName": proposal.project_name,
            "approvedBy": proposal.decided_by, "diffSha256": proposal.approved_content_digest,
            "liveRoot": str(live_root), "serviceUnit": service_unit,
        })
    except (AuditJournalError, OSError) as exc:
        raise CanaryDeployError(f"could not write the audit journal {audit_path} - nothing was changed: {exc}") from exc

    staging_parent = staging_parent or live_root.parent
    staging_path = _create_staging_clone(live_root, staging_parent)
    stage_reached = "staged"
    keep_staging = False
    service_stopped = False
    try:
        touched_paths = _apply_diff(staging_path, proposal.diff)
        stage_reached = "diff_applied"
        # The diff first, then the live checkout's own local data: a file the
        # diff adds or changes is the diff's, and a local file of the same name
        # no longer makes `git apply` fail on "already exists".
        # (The diff's own headers are consulted too: a new file that .gitignore
        # ignores never shows up in `git status`.)
        carry_over_skip = sorted(set(touched_paths) | set(diff_touched_paths(proposal.diff)))
        _carry_over_local_data(live_root, staging_path, skip=carry_over_skip)

        with tempfile.TemporaryDirectory(prefix="ops-agent-home-") as home:
            environment = build_environment(Path(home), build_env_allow)
            returncode, build_output = _run(build_test_command, cwd=staging_path, timeout_s=build_timeout_s, env=environment)
        if returncode != 0:
            result = CanaryDeployResult(
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
            _audit_result(audit_path, result)
            return result
        stage_reached = "build_verified"

        # Commit the applied diff inside the staging clone BEFORE
        # promotion - see _commit_applied_diff()'s own docstring for why a
        # successful canary must never promote a staging clone with an
        # uncommitted git apply still sitting in its working tree.
        _commit_applied_diff(staging_path, touched_paths, deploy_id=deploy_id, proposal_id=proposal.proposal_id)
        stage_reached = "diff_committed"
        patch_file = _save_canary_patch(
            staging_path, live_root.parent / f"{live_root.name}.canary-patches", deploy_id, touched_paths
        )
        if not keep_local_commit:
            _leave_canary_uncommitted(staging_path, touched_paths, deploy_id=deploy_id, patch_file=patch_file)

        # The build may have taken minutes. Stop the service (if one was named),
        # then look again: a tracked file edited meanwhile stops the deploy, and
        # local data written meanwhile is copied once more.
        if service_unit:
            code, output = _systemctl("stop", service_unit, live_root.parent)
            if code != 0:
                raise ServiceControlError(f"could not stop {service_unit} (exit {code}): {output.strip()} - nothing was changed")
            service_stopped = True
        dirty_now = _tracked_dirty_paths(live_root)
        if dirty_now:
            raise TrackedDirtyError(
                f"{live_root} changed while the candidate was being built ({', '.join(dirty_now[:5])}) - "
                "nothing was changed; deploy again once it is clean"
            )
        _carry_over_local_data(live_root, staging_path, skip=carry_over_skip)

        backup_path = live_root.parent / f"{live_root.name}.backup-{uuid.uuid4().hex[:8]}"
        journal = None
        record = None
        if _HAS_PROMOTION_JOURNAL:
            journal = PromotionJournal(journal_path or live_root.parent / _PROMOTION_JOURNAL_NAME)
            record = journal.begin(live_root.name, live_root, staging_path, backup_path, health_check_url=health_url)
        live_root.rename(backup_path)
        if journal and record:
            journal.advance(record.promotion_id, PromotionPhase.BACKED_UP)
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
            if journal and record:
                journal.complete(record.promotion_id)
            raise CanaryDeployError(
                f"promotion failed (exit path unavailable: {exc}) - restored the previous checkout at {live_root}; "
                f"the verified candidate is still available at {staging_path} for manual inspection"
            ) from exc
        if journal and record:
            journal.advance(record.promotion_id, PromotionPhase.PROMOTED)
        stage_reached = "promoted"

        if service_unit:
            code, output = _systemctl("start", service_unit, live_root.parent)
            service_stopped = False
            healthy, health_detail = (False, f"could not start {service_unit}: {output.strip()}") if code != 0 else _wait_until_healthy(
                service_unit, health_url, health_timeout_s, live_root.parent
            )
        elif health_url:
            healthy, health_detail = _wait_until_healthy(None, health_url, health_timeout_s, live_root.parent)
        else:
            healthy, health_detail = True, "no health check configured"

        if not healthy:
            failed_path = live_root.parent / f"{live_root.name}.failed-{deploy_id[:8]}"
            live_root.rename(failed_path)
            backup_path.rename(live_root)
            if journal and record:
                journal.complete(record.promotion_id)
            if service_unit:
                _systemctl("start", service_unit, live_root.parent)
            result = CanaryDeployResult(
                deploy_id=deploy_id,
                proposal_id=proposal.proposal_id,
                project_name=proposal.project_name,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                promoted=False,
                stage_reached="rolled_back",
                build_output=build_output,
                detail=(
                    f"the promoted checkout did not become healthy ({health_detail}) - the previous checkout is back "
                    f"at {live_root}; the failed one was kept at {failed_path}"
                ),
                backup_path=None,
            )
            _audit_result(audit_path, result)
            return result

        if journal and record:
            journal.complete(record.promotion_id)
        result = CanaryDeployResult(
            deploy_id=deploy_id,
            proposal_id=proposal.proposal_id,
            project_name=proposal.project_name,
            started_at=started_at,
            finished_at=_utc_now_iso(),
            promoted=True,
            stage_reached=stage_reached,
            build_output=build_output,
            detail=f"promoted - the previous checkout was kept at {backup_path}, never deleted ({health_detail})",
            backup_path=str(backup_path),
            patch_path=str(patch_file) if patch_file else None,
        )
        _audit_result(audit_path, result)
        return result
    except CanaryDeployError:
        if service_stopped and service_unit:
            _systemctl("start", service_unit, live_root.parent)
        raise
    finally:
        if stage_reached != "promoted" and not keep_staging:
            _rmtree_best_effort(staging_path)


def _audit_result(audit_path: Path, result: CanaryDeployResult) -> None:
    try:
        _audit(audit_path, "deploy-finished", {
            "deployId": result.deploy_id, "proposalId": result.proposal_id, "promoted": result.promoted,
            "stageReached": result.stage_reached, "backupPath": result.backup_path, "patchPath": result.patch_path, "detail": result.detail[:500],
        })
    except (AuditJournalError, OSError):
        pass  # the deploy already happened; the start record is in the journal


def recover_interrupted_promotions(projects_root: Path, journal_path: Path | None = None) -> list[str]:
    """Heals a promotion this tool started and never finished (a crash, a
    power cut between the two renames). Needs the optional SDK; without it
    there is nothing durable to recover from and an empty list comes back."""
    if not _HAS_PROMOTION_JOURNAL:
        return []
    return _recover_promotions(PromotionJournal(journal_path or projects_root / _PROMOTION_JOURNAL_NAME))


_BACKUP_SUFFIX = re.compile(r"\.backup-[0-9a-f]{8}$")


def list_backups(live_root: Path) -> list[Path]:
    """The `<name>.backup-xxxxxxxx` folders next to `live_root`, newest first."""
    found = [
        candidate for candidate in live_root.parent.iterdir()
        if candidate.is_dir() and candidate.name.startswith(live_root.name + ".backup-")
        and _BACKUP_SUFFIX.search(candidate.name)
    ]
    return sorted(found, key=lambda candidate: candidate.stat().st_mtime, reverse=True)


def rollback_deploy(live_root: Path, backup_path: Path | None = None) -> Path:
    """Puts a backup back in place of `live_root` (the newest one unless one is
    named). The checkout it replaces is kept beside it as
    `<name>.rolledback-xxxxxxxx`; nothing is deleted. Returns the backup used."""
    backups = list_backups(live_root)
    chosen = backup_path if backup_path is not None else (backups[0] if backups else None)
    if chosen is None:
        raise CanaryDeployError(f"there is no backup of {live_root.name} next to it to roll back to")
    if chosen not in backups:
        raise CanaryDeployError(f"{chosen} is not a backup of {live_root.name} (expected {live_root.name}.backup-xxxxxxxx)")
    set_aside = live_root.parent / f"{live_root.name}.rolledback-{uuid.uuid4().hex[:8]}"
    try:
        if live_root.exists():
            live_root.rename(set_aside)
        chosen.rename(live_root)
    except OSError as exc:
        raise CanaryDeployError(f"could not roll back {live_root}: {exc}") from exc
    return chosen


def prune_backups(live_root: Path, *, keep: int) -> list[Path]:
    """Removes all but the newest `keep` backups of `live_root`; returns what was removed."""
    if keep < 0:
        raise CanaryDeployError("keep must not be negative")
    removed: list[Path] = []
    for old in list_backups(live_root)[keep:]:
        _rmtree_best_effort(old)
        if not old.exists():
            removed.append(old)
    return removed
