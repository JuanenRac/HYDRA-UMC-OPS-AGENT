# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/inventory.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real, read-only inventory collection for the edge role - Delivery 1
("Observabilidad read-only") of the ecosystem-wide proposal's own 6-delivery
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

import json
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


_MANIFEST_FILENAME = "hydra-umc.project.json"
_REQUIRED_FIELDS = ("name", "version", "maturity")


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
        # Real gap found 2026-09-08 while building a real end-to-end
        # incident-lifecycle test (F08): canary_deploy.py's own
        # deploy_canary() (and HYDRA-UMC-UPDATER's own install.py,
        # exact same convention) renames the PREVIOUS checkout aside to
        # `<name>.backup-<uuid>` on every real promotion, by design,
        # never deleted. Without this skip, a re-scan of the same
        # projects_root after a real promotion picks the retired,
        # never-updated backup back up as if it were a live project -
        # its manifest is whatever it was the moment it was retired, so
        # a real, already-fixed incident would falsely reappear forever,
        # every single scan, from that point on.
        if ".backup-" in entry.name:
            continue
        manifest_path = entry / _MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue
        try:
            raw = manifest_path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(ManifestScanIssue(path=str(manifest_path), reason=f"could not read: {exc}"))
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            issues.append(ManifestScanIssue(path=str(manifest_path), reason=f"not valid JSON: {exc}"))
            continue
        if not isinstance(data, dict):
            issues.append(ManifestScanIssue(path=str(manifest_path), reason="manifest is not a JSON object"))
            continue
        missing = [field for field in _REQUIRED_FIELDS if not isinstance(data.get(field), str) or not data.get(field)]
        if missing:
            issues.append(ManifestScanIssue(path=str(manifest_path), reason=f"missing/empty required field(s): {', '.join(missing)}"))
            continue
        projects.append(ProjectVersion(
            name=data["name"],
            version=data["version"],
            maturity=data["maturity"],
            manifest_path=str(manifest_path),
        ))
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
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        raise SystemdUnavailableError("systemctl not found on PATH - not a real systemd host")
    try:
        result = subprocess.run(
            [systemctl, "is-active", unit_name],
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except subprocess.TimeoutExpired:
        return ServiceHealthResult(unit_name=unit_name, active=False, detail=f"systemctl is-active timed out after {timeout_s}s")
    detail = (result.stdout or result.stderr or "").strip() or f"exit code {result.returncode}"
    return ServiceHealthResult(unit_name=unit_name, active=result.returncode == 0, detail=detail)


@dataclass(frozen=True)
class HttpHealthResult:
    url: str
    reachable: bool
    status_code: int | None
    detail: str


def check_http_health(url: str, *, timeout_s: float = 5.0) -> HttpHealthResult:
    """Real HTTP GET (stdlib urllib, no dependency) against a project's own
    health endpoint - a genuine network failure (refused connection, DNS,
    timeout) and a real-but-unhealthy HTTP response (a real 5xx, say) are
    reported as two distinct, honest outcomes, never collapsed into one
    bare boolean that would hide which one actually happened."""
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in _SUPPORTED_HTTP_SCHEMES:
        return HttpHealthResult(
            url=url, reachable=False, status_code=None,
            detail=f"unsupported URL scheme {scheme!r} - only http/https are ever checked",
        )
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
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
            return HttpHealthResult(
                url=url,
                reachable=200 <= status_code < 300,
                status_code=status_code,
                detail=f"HTTP {status_code}",
            )
    except urllib.error.HTTPError as exc:
        # A real response was received - the server IS reachable - it just
        # reported a non-2xx status. Distinct from URLError below.
        return HttpHealthResult(url=url, reachable=False, status_code=exc.code, detail=f"HTTP {exc.code}: {exc.reason}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return HttpHealthResult(url=url, reachable=False, status_code=None, detail=f"unreachable: {exc}")
