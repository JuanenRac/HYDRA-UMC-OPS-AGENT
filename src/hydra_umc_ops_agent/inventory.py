# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/inventory.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real, read-only inventory collection for the edge role - Delivery 1
("Observabilidad read-only") of this repo's own 6-delivery
plan: "edge-agent inventaria versiones, servicios, health checks y logs
saneados". Nothing in this module mutates anything - it only ever reads a
manifest file, asks systemd/an HTTP endpoint for its own current state, or
redacts text already collected elsewhere (see log_redaction.py).

Real platform honesty, not a simulated pass: this development machine is not
a CM5, so `check_systemd_unit_health()` cannot be exercised against a real
unit here - it degrades with a distinct, typed `SystemdUnavailableError`
instead of a guessed status, and is unit-tested for exactly that degradation
path (the one thing genuinely verifiable without the real hardware).
"""
from __future__ import annotations

import base64
import http.client
import json
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# The only schemes `check_http_health()` will ever actually open - a real
# health endpoint is HTTP(S), never `data:`/`file:`/`ftp:`. Restricting this
# explicitly (rather than trying every scheme and hoping the result looks
# HTTP-shaped) is what stops a malformed/hostile URL from reaching
# `urlopen()` at all, not just from crashing once it gets there.
_SUPPORTED_HTTP_SCHEMES = ("http", "https")


class _HttpOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """A health endpoint that redirects (`/health` -> `/health/`, http ->
    https) is still answering, so redirects are followed - but only to
    `http`/`https`. urllib would also follow one to `ftp:`, which turns a
    health probe into a connection to wherever a misbehaving endpoint says."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - stdlib hook
        if urllib.parse.urlsplit(newurl).scheme.lower() not in _SUPPORTED_HTTP_SCHEMES:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_HTTP_OPENER = urllib.request.build_opener(_HttpOnlyRedirects)


def _request_for(url: str) -> urllib.request.Request:
    """The request for a health URL. urllib does not understand credentials
    written into the URL (`http://user:password@host/health`): it takes
    `user:password@host` for the host name and fails to resolve it, so a
    credentialed URL - which the incident redaction code expects people to
    configure - was reported unreachable forever, a permanent false
    incident. The userinfo is split off and sent as a Basic `Authorization`
    header instead, added as an UNREDIRECTED header so it is never carried
    along if the endpoint redirects somewhere else."""
    parts = urllib.parse.urlsplit(url)
    if parts.username is None and parts.password is None:
        return urllib.request.Request(url)
    userinfo = f"{urllib.parse.unquote(parts.username or '')}:{urllib.parse.unquote(parts.password or '')}"
    bare = urllib.parse.urlunsplit((parts.scheme, parts.netloc.rpartition("@")[2], parts.path, parts.query, parts.fragment))
    request = urllib.request.Request(bare)
    request.add_unredirected_header("Authorization", "Basic " + base64.b64encode(userinfo.encode("utf-8")).decode("ascii"))
    return request


# A systemd unit name: letters, digits and `: _ . @ -`, never starting with a
# dash. Anything else could be read by `systemctl` as an option.
_UNIT_NAME_RE = re.compile(r"^[A-Za-z0-9:_.@\\][A-Za-z0-9:_.@\\-]*$")


def validate_unit_name(unit_name: str) -> str:
    """Returns `unit_name` if it is a plausible systemd unit name, else raises
    ValueError. A name such as `--version` or `--host=other` would otherwise be
    taken by `systemctl` for an option and answer about something else."""
    if not isinstance(unit_name, str) or not _UNIT_NAME_RE.fullmatch(unit_name) or len(unit_name) > 256:
        raise ValueError(f"{unit_name!r} is not a valid systemd unit name")
    return unit_name


class SystemdUnavailableError(RuntimeError):
    """Raised when `systemctl` itself is not available on this host (a
    non-Linux development machine, or a Linux host without systemd) - a
    real, distinct, typed reason, never a guessed "unknown"/"down" status
    that would be indistinguishable from a genuinely failed real unit."""


@dataclass(frozen=True)
class ProjectVersion:
    """One real project's own declared identity, read straight from its
    hydra-umc.project.json - never re-derived or guessed from a directory
    name."""
    name: str
    version: str
    maturity: str
    manifest_path: str


@dataclass(frozen=True)
class ManifestScanIssue:
    """A real, named reason ONE candidate directory did not yield a
    ProjectVersion - kept distinct from a silently-skipped entry so a
    caller (and a future incident deriver) can tell "no project here at
    all" apart from "a project is here, but its manifest is broken"."""
    path: str
    reason: str


@dataclass(frozen=True)
class ManifestScanResult:
    projects: tuple[ProjectVersion, ...]
    issues: tuple[ManifestScanIssue, ...]


_RETIRED_COPY_MARKERS = (".backup-", ".rolledback-", ".failed-")
_MANIFEST_FILENAME = "hydra-umc.project.json"
# A real manifest is a few hundred bytes; anything past this is not one, and
# reading it whole into memory on every scan is not worth finding out.
_MANIFEST_MAX_BYTES = 1_000_000
_REQUIRED_FIELDS = ("name", "version", "maturity")


def check_project_manifest(manifest_path: Path) -> ProjectVersion | ManifestScanIssue:
    """Re-validates ONE real hydra-umc.project.json directly by path - the
    same real checks scan_project_manifests()'s own loop applies to each
    candidate directory it finds, factored out here so a caller that
    already knows exactly which manifest to look at (verification.py's
    own re-check of a manifest-scan incident) never needs
    a full root re-scan just to answer one question about one file."""
    if not manifest_path.is_file():
        return ManifestScanIssue(path=str(manifest_path), reason="manifest file no longer exists")
    try:
        if manifest_path.stat().st_size > _MANIFEST_MAX_BYTES:
            return ManifestScanIssue(path=str(manifest_path), reason=f"manifest is larger than {_MANIFEST_MAX_BYTES} bytes")
        raw = manifest_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        # A byte that is not UTF-8 is a broken manifest to report, not a
        # reason for the whole scan (and every project after it) to crash.
        return ManifestScanIssue(path=str(manifest_path), reason=f"not valid UTF-8: {exc}")
    except OSError as exc:
        return ManifestScanIssue(path=str(manifest_path), reason=f"could not read: {exc}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ManifestScanIssue(path=str(manifest_path), reason=f"not valid JSON: {exc}")
    if not isinstance(data, dict):
        return ManifestScanIssue(path=str(manifest_path), reason="manifest is not a JSON object")
    missing = [field for field in _REQUIRED_FIELDS if not isinstance(data.get(field), str) or not data.get(field)]
    if missing:
        return ManifestScanIssue(path=str(manifest_path), reason=f"missing/empty required field(s): {', '.join(missing)}")
    return ProjectVersion(name=data["name"], version=data["version"], maturity=data["maturity"], manifest_path=str(manifest_path))


def read_git_commit_hash(path: Path, *, timeout_s: float = 5.0) -> str | None:
    """Best-effort `git rev-parse HEAD` for `path` - `None` (never a
    guessed/empty string) whenever this can't be answered for real: `git`
    missing from PATH, `path` is not inside a real git checkout, or the
    command times out. Used to pin a manifest incident's before/
    after evidence to the exact source state it was raised and resolved
    against - see verification.py's own header comment."""
    git = shutil.which("git")
    if git is None:
        return None
    try:
        result = subprocess.run(
            [git, "rev-parse", "HEAD"], cwd=str(path), capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def scan_project_manifests(root: Path) -> ManifestScanResult:
    """Scans the immediate subdirectories of `root` for a real
    hydra-umc.project.json each, reading its own name/version/maturity.

    A subdirectory with no manifest at all is not an issue (most
    subdirectories of a workspace root are not HYDRA-UMC/URTC checkouts) -
    only a PRESENT-but-unreadable/malformed/incomplete manifest is recorded
    as a ManifestScanIssue, so real, honest partial failures are visible
    rather than silently dropped.
    """
    if not root.is_dir():
        return ManifestScanResult(projects=(), issues=(ManifestScanIssue(path=str(root), reason="root is not a real directory"),))

    projects: list[ProjectVersion] = []
    issues: list[ManifestScanIssue] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        # canary_deploy.py's deploy_canary() (and HYDRA-UMC-UPDATER's
        # install.py, same convention) renames the PREVIOUS checkout aside to
        # `<name>.backup-<id>` on every promotion, by design, never deleted;
        # a rollback leaves `.rolledback-` and `.failed-` copies, and both
        # tools stage candidates in hidden folders (`.ops-agent-canary-*`,
        # `.<name>.update-*`). Without this skip, a re-scan picks those up as
        # if they were live projects - a retired copy's manifest is whatever
        # it was the moment it was retired, so an already-fixed incident
        # would falsely reappear forever, and a staging folder would show up
        # as a second copy of the project while a build runs.
        if entry.name.startswith(".") or any(marker in entry.name for marker in _RETIRED_COPY_MARKERS):
            continue
        manifest_path = entry / _MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue
        checked = check_project_manifest(manifest_path)
        if isinstance(checked, ManifestScanIssue):
            issues.append(checked)
        else:
            projects.append(checked)
    return ManifestScanResult(projects=tuple(projects), issues=tuple(issues))


@dataclass(frozen=True)
class ServiceHealthResult:
    unit_name: str
    active: bool
    detail: str


def check_systemd_unit_health(unit_name: str, *, timeout_s: float = 5.0) -> ServiceHealthResult:
    """Real `systemctl is-active <unit_name>` check for the edge role.

    Raises SystemdUnavailableError (never a guessed ServiceHealthResult) if
    `systemctl` itself cannot be found on PATH at all - the honest platform
    gate this module's own header comment describes, matching
    HYDRA-UMC-OS-REBUILDER's own check_build_platform() pattern: fail
    loudly and specifically before pretending to check anything.
    """
    validate_unit_name(unit_name)
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        raise SystemdUnavailableError("systemctl not found on PATH - not a real systemd host")
    try:
        result = subprocess.run(
            [systemctl, "is-active", "--", unit_name],
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except subprocess.TimeoutExpired:
        return ServiceHealthResult(unit_name=unit_name, active=False, detail=f"systemctl is-active timed out after {timeout_s}s")
    except OSError as exc:
        return ServiceHealthResult(unit_name=unit_name, active=False, detail=f"could not run systemctl: {exc}")
    detail = (result.stdout or result.stderr or "").strip() or f"exit code {result.returncode}"
    return ServiceHealthResult(unit_name=unit_name, active=result.returncode == 0, detail=detail)


@dataclass(frozen=True)
class HttpHealthResult:
    url: str
    reachable: bool
    status_code: int | None
    detail: str


_REDACTION_MARKER = "[REDACTED]"
_UNHEALTHY_STATUS_WORDS = {"degraded", "unhealthy", "error", "down", "fail", "failed", "failing", "critical"}
_HEALTH_BODY_LIMIT = 65536


def _interpret_health_body(response, detail: str) -> tuple[bool, str]:
    """A 2xx health endpoint that says in its JSON body that it is not well
    (`"status": "degraded"`, `"persistenceHealthy": false`) is not healthy.
    A body that is not JSON, or says nothing of the kind, changes nothing."""
    try:
        content_type = response.headers.get("Content-Type", "") if hasattr(response, "headers") else ""
        if "json" not in content_type.lower():
            return True, detail
        body = json.loads(response.read(_HEALTH_BODY_LIMIT).decode("utf-8", errors="replace"))
    except (OSError, ValueError, http.client.HTTPException):
        return True, detail
    if not isinstance(body, dict):
        return True, detail
    status = body.get("status")
    if isinstance(status, str) and status.strip().lower() in _UNHEALTHY_STATUS_WORDS:
        return False, f"{detail}, but the endpoint reports status {status!r}"
    for key, value in body.items():
        if isinstance(key, str) and key.lower().endswith("healthy") and value is False:
            return False, f"{detail}, but the endpoint reports {key}=false"
    return True, detail


def check_http_health(url: str, *, timeout_s: float = 5.0) -> HttpHealthResult:
    """Real HTTP GET (stdlib urllib, no dependency) against a project's own
    health endpoint - a genuine network failure (refused connection, DNS,
    timeout) and a real-but-unhealthy HTTP response (a real 5xx, say) are
    reported as two distinct, honest outcomes, never collapsed into one
    bare boolean that would hide which one actually happened."""
    if _REDACTION_MARKER in url:
        return HttpHealthResult(
            url=url, reachable=False, status_code=None,
            detail="the URL carries a redacted password (as stored in a snapshot) - it cannot be checked "
            "without the real credentials",
        )
    try:
        scheme = urllib.parse.urlsplit(url).scheme.lower()
    except ValueError as exc:
        return HttpHealthResult(url=url, reachable=False, status_code=None, detail=f"not a valid URL: {exc}")
    if scheme not in _SUPPORTED_HTTP_SCHEMES:
        return HttpHealthResult(
            url=url, reachable=False, status_code=None,
            detail=f"unsupported URL scheme {scheme!r} - only http/https are ever checked",
        )
    try:
        with _HTTP_OPENER.open(_request_for(url), timeout=timeout_s) as response:
            status_code = response.getcode()
            if not isinstance(status_code, int):
                # A real HTTP(S) response always has an int status code -
                # anything else means this handler did not actually give us
                # one (seen with some non-HTTP-shaped responses even under
                # an http(s) URL), and `200 <= status_code < 300` would
                # raise TypeError on it instead of reporting a real result.
                return HttpHealthResult(
                    url=url, reachable=False, status_code=None,
                    detail="response did not report a real HTTP status code",
                )
            reachable = 200 <= status_code < 300
            detail = f"HTTP {status_code}"
            if reachable:
                reachable, detail = _interpret_health_body(response, detail)
            return HttpHealthResult(url=url, reachable=reachable, status_code=status_code, detail=detail)
    except urllib.error.HTTPError as exc:
        # A real response was received - the server IS reachable - it just
        # reported a non-2xx status. Distinct from URLError below.
        return HttpHealthResult(url=url, reachable=False, status_code=exc.code, detail=f"HTTP {exc.code}: {exc.reason}")
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        # http.client.HTTPException (a status line that is not HTTP, a
        # truncated body) is not an OSError, so urllib lets it through raw -
        # one odd endpoint used to crash the whole `edge collect`.
        return HttpHealthResult(url=url, reachable=False, status_code=None, detail=f"unreachable: {exc}")
