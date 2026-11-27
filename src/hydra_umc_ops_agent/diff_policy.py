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
    "makefile",
    "GNUmakefile",  # make reads it before Makefile
)

_DIFF_GIT_RE = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")
_FILE_HEADER_RE = re.compile(r"^(?P<kind>--- |\+\+\+ )(?P<path>[^\t\r\n]+)")
# `git apply` takes the real names of a rename or a copy from these lines, whatever the `diff --git` line says
_MOVE_HEADER_RE = re.compile(r"^(?:rename|copy) (?:from|to) (?P<path>.+)$")
_C_ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, "\\": 92, '"': 34}


def _unquote_c(path: str) -> str:
    """The name `git apply` reads from a name in double quotes: the C escapes (a backslash and a letter, a quote, a backslash or up to three octal digits)
    are decoded, so a name written with an octal escape for one letter is the plain name. A name that is not wholly in quotes is returned as it is."""
    if len(path) < 2 or not (path.startswith('"') and path.endswith('"')):
        return path
    body = path[1:-1]
    out = bytearray()
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\" or index + 1 >= len(body):
            out.extend(char.encode("utf-8"))
            index += 1
            continue
        following = body[index + 1]
        if following in "01234567":
            digits = following
            index += 2
            while index < len(body) and len(digits) < 3 and body[index] in "01234567":
                digits += body[index]
                index += 1
            out.append(int(digits, 8) & 0xFF)
        elif following in _C_ESCAPES:
            out.append(_C_ESCAPES[following])
            index += 2
        else:
            out.extend(("\\" + following).encode("utf-8"))
            index += 2
    return out.decode("utf-8", errors="replace")

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
    """Every file path named in the headers of a unified diff (the `diff --git`, `---` and `+++` lines and the `rename` and `copy` lines, names in quotes
    decoded the way `git apply` decodes them), without the `a/` and `b/` prefixes and without `/dev/null`, in order of appearance."""
    paths: list[str] = []

    def add(path: str, *, prefixed: bool = True) -> None:
        path = _unquote_c(path.strip())
        if path in ("", "/dev/null"):
            return
        if prefixed:
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
        move = _MOVE_HEADER_RE.match(line)
        if move:
            add(move.group("path"), prefixed=False)  # the names of a rename or a copy carry no a/ or b/
            continue
        header = _FILE_HEADER_RE.match(line)
        if header:
            add(header.group("path"))
    return paths


def _is_protected(path: str, extra: tuple[str, ...] = ()) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    last = normalized.rsplit("/", 1)[-1]
    for pattern in (*PROTECTED_PATH_PATTERNS, *extra):
        if pattern.endswith("/"):
            if normalized.startswith(pattern) or f"/{pattern}" in normalized:
                return True
        elif fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(last, pattern):
            return True
    return False


def is_protected_path(path: str, extra: tuple[str, ...] = ()) -> bool:
    """True for a path that decides how a change is verified or run (the check `protected_paths_in` applies to every path of a diff)."""
    return _is_protected(path, extra)


def protected_paths_in(diff_text: str, extra: tuple[str, ...] = ()) -> list[str]:
    """The paths of `diff_text` that decide how a change is verified or run: the fixed list and `extra`, the `protected_paths` of the project."""
    return [path for path in touched_paths(diff_text) if _is_protected(path, extra)]
