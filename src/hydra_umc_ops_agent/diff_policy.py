# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/diff_policy.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""What a proposed diff is allowed to contain and to touch.

Three questions are answered here, all about the text of a diff and nothing
else (it is never applied by this module):

- Does it look like it carries a real secret? Only the lines the diff ADDS are
  looked at, and only a value that has the shape of a secret: a known token
  format, a private key, a password in a URL, or a long literal string assigned
  to a secret-named key. Reading a password from the environment, a parameter
  named `password`, or a placeholder is ordinary source code and passes.
- Which files does it touch? Paths are read from the diff headers.
- Does it touch files that decide how the change is verified or run (CI
  workflows, the project's own build-test scripts, service units, provisioning
  scripts)? A change that rewrites the check that is supposed to judge it
  proves nothing, so such a diff is only accepted when the proposal says so
  explicitly - and that statement is part of what the approver signs.
"""
from __future__ import annotations

import fnmatch
import re

from .log_redaction import TOKEN_SHAPES

#: A diff larger than this is not a hot fix; it is refused outright.
MAX_DIFF_BYTES = 256 * 1024

#: Paths (relative to the repository root) that decide how a change is checked
#: or how it runs. `dir/` entries match everything below that directory,
#: the others are shell-style patterns matched against the whole path and
#: against its last component.
PROTECTED_PATH_PATTERNS: tuple[str, ...] = (
    ".github/",
    "tools/",
    "scripts/",
    "provisioning/",
    "build-test.*",
    "build.sh",
    "build.bat",
    "bump_version.py",
    "bump_manifest_version.py",
    "install_*.sh",
    "*.service",
    "*.timer",
    "Makefile",
)

_DIFF_GIT_RE = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")
_FILE_HEADER_RE = re.compile(r"^(?P<kind>--- |\+\+\+ )(?P<path>[^\t\r\n]+)")

_PLACEHOLDER_MARKERS = (
    "changeme", "change-me", "example", "placeholder", "your", "xxxx", "****", "<", "${", "{{",
    "os.environ", "getenv", "env[", "process.env", "secrets.", "redacted", "dummy", "sample", "todo",
)
_LITERAL_SECRET_RE = re.compile(
    r"(?i)[A-Za-z0-9_-]*(?:password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|credential)[A-Za-z0-9_-]*"
    r"\s*[:=]\s*(?P<quote>[\"'])(?P<value>[^\"'\r\n]{12,})(?P=quote)"
)
_URL_PASSWORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s:/@]+:(?P<password>[^\s@]+)@")
_BASIC_HEADER_RE = re.compile(r"(?i)authorization[\"']?\s*[:=]\s*[\"']?basic\s+[A-Za-z0-9+/=]{6,}")


def _added_lines(diff_text: str) -> list[str]:
    return [line[1:] for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++")]


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return True
    return len(set(value)) <= 2  # "aaaaaaaaaaaa", "000000000000"


def diff_looks_secret_shaped(diff_text: str) -> bool:
    """True when a line the diff adds holds something with the shape of a real
    secret (see the module docstring for what does not count)."""
    added = "\n".join(_added_lines(diff_text))
    if "PRIVATE KEY-----" in added:
        return True
    if any(shape.search(added) for shape in TOKEN_SHAPES):
        return True
    if _BASIC_HEADER_RE.search(added):
        return True
    for match in _URL_PASSWORD_RE.finditer(added):
        if not _looks_like_placeholder(match.group("password")):
            return True
    for match in _LITERAL_SECRET_RE.finditer(added):
        if not _looks_like_placeholder(match.group("value")):
            return True
    return False


def touched_paths(diff_text: str) -> list[str]:
    """Every file path named in the headers of a unified diff, without the
    `a/` and `b/` prefixes and without `/dev/null`, in order of appearance."""
    paths: list[str] = []

    def add(path: str) -> None:
        path = path.strip().strip('"')
        if path in ("", "/dev/null"):
            return
        for prefix in ("a/", "b/"):
            if path.startswith(prefix):
                path = path[len(prefix):]
                break
        if path not in paths:
            paths.append(path)

    for line in diff_text.splitlines():
        git = _DIFF_GIT_RE.match(line)
        if git:
            add(git.group("a"))
            add(git.group("b"))
            continue
        header = _FILE_HEADER_RE.match(line)
        if header:
            add(header.group("path"))
    return paths


def _is_protected(path: str) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    last = normalized.rsplit("/", 1)[-1]
    for pattern in PROTECTED_PATH_PATTERNS:
        if pattern.endswith("/"):
            if normalized.startswith(pattern) or f"/{pattern}" in normalized:
                return True
        elif fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(last, pattern):
            return True
    return False


def protected_paths_in(diff_text: str) -> list[str]:
    """The paths of `diff_text` that decide how a change is verified or run."""
    return [path for path in touched_paths(diff_text) if _is_protected(path)]
