# =============================================================================
# HYDRA-UMC-SDK - tools/canonical/redaction.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""One shared, pure redaction of secrets for text and JSON-like values.

This file has a single canonical copy (`tools/canonical/redaction.py` of HYDRA-UMC-SDK) that is vendored,
byte for byte, into the Python projects that send text out of their process (the ops agent and the local
technician); `tools/sync_repo_tools.py` keeps the copies identical. The cases every implementation has to
pass, in any language, are in `contracts/redaction/vectors.json`.

Deliberately a fixed, explicit list of real, well-known secret shapes, never a fuzzy "looks random enough"
heuristic: a heuristic invites both false positives (redacting an innocuous long identifier) and false
negatives (a genuine secret shaped just differently enough to dodge a vague pattern).

The module never decides what to collect; it only narrows what a caller already gathered, so the same
function guards every path data leaves a process on (a saved snapshot, a network transport, an AI request).
"""
from __future__ import annotations

import re

# KEY=VALUE / KEY: VALUE / KEY = "VALUE" - the real .env-file and shell-export
# shape this project's own contract names explicitly. Case-insensitive;
# matches the secret word as a SUBSTRING of the real key token (not
# requiring a \b word boundary immediately before it) because `_` is a
# real \w character - a plain \b(?:password)\b would never match the very
# real "DB_PASSWORD=..." shape, since regex sees no boundary inside
# "DB_PASSWORD" at all. VALUE is greedy up to the real end of that line
# only, never spanning lines (so no other content on the redacted line is
# ever swallowed).
#
# Deliberately excludes "auth"/"authorization" - that generic a key name
# collides with the dedicated Bearer-token shape below (an
# "Authorization: Bearer <token>" line would otherwise get redacted
# twice, corrupting the result into losing the word "Bearer" itself) and
# already-redacted output could then also update-match. The Bearer
# pattern is the real, precise handler for that specific real header
# shape instead.
_SECRET_KEY_NAMES = (
    "password", "passwd", "pwd",
    "secret", "token", "api_key", "apikey", "api-key",
    "private_key", "privatekey", "private-key",
    "credential", "credentials",
    "ssh_key", "sshkey",
)
#
# Every pattern that begins with an identifier-like run starts with a
# lookbehind that forbids a character of that run right before it: without it
# the engine tries every start inside a long run and rescans the rest of the
# run each time, which is quadratic (a megabyte of letters took days).
# The URL patterns also bound the length of each part, for the same reason (a
# long run of `x://` pieces with no `@`): a password over 1024 characters in a
# URL is the one thing this leaves unredacted.
_KEY_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?P<key>[A-Za-z0-9_-]*(?:" + "|".join(_SECRET_KEY_NAMES) + r")[A-Za-z0-9_-]*\s*[:=]\s*)"
    # Quoted value: anything up to the matching closing quote, so a real
    # quoted secret containing spaces is still captured whole. Unquoted
    # value: non-whitespace only, so an unquoted KEY=value token stops at
    # the next real word on the same line (e.g. "db=main" right after)
    # instead of a greedy match swallowing the rest of the line.
    r"(?:(?P<quote>[\"'])[^\r\n]*?(?P=quote)|\S+)",
    re.IGNORECASE,
)

# JSON string-key shape: `"password": "value"` / `"password":123` /
# `"password":true`. The generic _KEY_VALUE_RE above requires the secret
# word to be followed directly (after optional identifier chars) by `:`/`=`
# - in real JSON the key itself is wrapped in a closing `"` first, which
# _KEY_VALUE_RE's own assumption never accounts for, so a real
# `{"password": "..."}` snapshot field silently passed through unredacted.
# A separate pattern (not a generalization of the one above) keeps each
# real shape's own assumptions explicit rather than one regex trying to
# match both a shell KEY=VALUE line and a JSON string-key pair at once.
_JSON_KEY_VALUE_RE = re.compile(
    r'(?P<key>"[A-Za-z0-9_-]*(?:' + "|".join(_SECRET_KEY_NAMES) + r')[A-Za-z0-9_-]*"\s*:\s*)'
    r'(?:"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null)',
    re.IGNORECASE,
)

# "Authorization: Bearer <token>" / a bare "Bearer <token>" - the real HTTP
# auth-header shape, distinct from the generic KEY=VALUE case above (no `=`
# or `:` directly before the secret itself).
_BEARER_RE = re.compile(r"\bBearer\s+\S+", re.IGNORECASE)

# `scheme://user:password@host` - a real credential embedded in a URL's own
# userinfo component (e.g. a copy-pasted broker/API endpoint). The username
# itself is kept (it is rarely secret on its own and keeping it helps a
# human recognize which credential was in play); only the password half is
# replaced.
_URL_CREDENTIALS_RE = re.compile(
    r"(?<![A-Za-z0-9+.-])(?P<scheme>[A-Za-z][A-Za-z0-9+.-]{0,39}://)(?P<user>[^\s:/@]{1,256}):(?P<password>[^\s@]{1,1024})@"
)

# A real PEM-format private key block (SSH, TLS, GPG all share this real
# envelope) - re.DOTALL so the key MATERIAL between the markers (which is
# exactly what must never leave this process) is captured and dropped too,
# not just the header/footer lines.
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

_REDACTED = "[REDACTED]"

# Credentials that carry no label at all - a token pasted bare into a log line
# or an error message. Every shape here is a real, published format (GitHub
# personal/OAuth/app tokens, Anthropic and OpenAI keys, AWS access key ids,
# Slack tokens, JWTs). The generic `sk-` shape also requires a digit so an
# ordinary hyphenated phrase that happens to start with those letters stays
# readable.
TOKEN_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-(?:ant-|proj-)?(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
)

# `Authorization: Basic dXNlcjpwYXNz` - only in its header form, so the word
# "Basic" in ordinary prose is left alone.
_BASIC_AUTH_RE = re.compile(r"(?i)\b((?:proxy-)?authorization\s*[:=]\s*)basic\s+[A-Za-z0-9+/=]{6,}")

# A command line carries its secrets as `--token VALUE` / `-password VALUE`
# (the value is a separate argument, so the KEY=VALUE shape never sees it).
# Only a flag whose name contains a secret word is matched, and only a value
# that does not itself start with "-" is taken as the secret.
_FLAG_VALUE_RE = re.compile(
    r"(?P<flag>(?<![A-Za-z0-9_-])--?[A-Za-z0-9_-]*(?:" + "|".join(_SECRET_KEY_NAMES) + r")s?[A-Za-z0-9_-]*)"
    r"(?P<sep>[ \t]+)(?!-)(?P<value>\S+)",
    re.IGNORECASE,
)

# A bare `Basic <base64>` (a header pasted without its name, or a log line that
# prints only the scheme and the credential). The credential must look like
# base64 data (a digit or one of `+/=` in it) so the word "Basic" in prose
# ("Basic configuration") is left alone.
_BASIC_BARE_RE = re.compile(r"\bBasic\s+(?=[A-Za-z0-9+/=_-]*[0-9+/=])[A-Za-z0-9+/=_-]{8,}")

# A cookie header carries session secrets as a whole.
_COOKIE_RE = re.compile(r"(?P<header>\b(?:Set-)?Cookie\s*:\s*)[^\r\n]+", re.IGNORECASE)

# `scheme://TOKEN@host` - a token used as the whole userinfo (no password part).
_URL_TOKEN_USERINFO_RE = re.compile(r"(?<![A-Za-z0-9+.-])(?P<scheme>[A-Za-z][A-Za-z0-9+.-]{0,39}://)(?P<token>[^\s:/@]{16,1024})@")

# A residual outside a few earlier known examples: a
# secret-named key
# whose value is itself a nested JSON object or array
# (`"password": {"value": "FAKE"}`, `"api_key": ["FAKE"]`) matches
# neither _JSON_KEY_VALUE_RE's nor _KEY_VALUE_RE's own value
# alternation (a quoted string, unquoted token, or JSON scalar only) -
# the real secret one level deeper silently passed through unredacted.
# Regex alone can't reliably match balanced/nested brackets, so
# _redact_nested_structured_values() below manually scans forward from
# a matched key, tracking real bracket depth (ignoring brackets inside
# a quoted string) to find the true end of the structure - run BEFORE
# the simple-value patterns, which still own every non-nested case
# unchanged.
_SECRET_KEY_PATTERN = re.compile(
    r'(?<![A-Za-z0-9_-])"?[A-Za-z0-9_-]*(?:' + "|".join(_SECRET_KEY_NAMES) + r')[A-Za-z0-9_-]*"?\s*[:=]\s*',
    re.IGNORECASE,
)


def _redact_nested_structured_values(text: str) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in _SECRET_KEY_PATTERN.finditer(text):
        if match.start() < cursor:
            continue  # inside a span this loop's own earlier iteration already redacted
        value_start = match.end()
        if value_start >= len(text) or text[value_start] not in "{[":
            continue  # not a nested structure - the caller's simple-value patterns handle this
        opening = text[value_start]
        closing = "}" if opening == "{" else "]"
        depth = 0
        in_string = False
        escape = False
        end = None
        for i in range(value_start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == opening:
                depth += 1
            elif ch == closing:
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            continue  # unbalanced/truncated structure - not this function's real case
        pieces.append(text[cursor:match.start()])
        pieces.append(f"{match.group(0)}{_REDACTED}")
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def redact_secrets(text: str) -> str:
    """Returns `text` with every real, recognized secret shape replaced by
    a fixed [REDACTED] marker."""
    if not text:
        return text
    # A truncated PEM block (a real BEGIN marker with no
    # matching END - a log excerpt cut off mid-key) used to leave the
    # ENTIRE block, key material included, completely unredacted,
    # because _PEM_BLOCK_RE's own DOTALL match requires both markers.
    # Handled first, and separately from the balanced BEGIN/END case
    # right below it, so a real, complete PEM block still keeps its own
    # more specific match.
    result = re.sub(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----(?!.*-----END).*", _REDACTED, text, flags=re.DOTALL)
    result = _PEM_BLOCK_RE.sub(_REDACTED, result)
    result = _BEARER_RE.sub(f"Bearer {_REDACTED}", result)
    result = _BASIC_AUTH_RE.sub(lambda m: f"{m.group(1)}Basic {_REDACTED}", result)
    result = _BASIC_BARE_RE.sub(f"Basic {_REDACTED}", result)
    result = _COOKIE_RE.sub(lambda m: f"{m.group('header')}{_REDACTED}", result)
    for shape in TOKEN_SHAPES:
        result = shape.sub(_REDACTED, result)
    result = _URL_TOKEN_USERINFO_RE.sub(lambda m: f"{m.group('scheme')}{_REDACTED}@", result)
    result = _URL_CREDENTIALS_RE.sub(lambda m: f"{m.group('scheme')}{m.group('user')}:{_REDACTED}@", result)
    result = _redact_nested_structured_values(result)
    result = _JSON_KEY_VALUE_RE.sub(lambda m: f"{m.group('key')}{_REDACTED}", result)
    result = _KEY_VALUE_RE.sub(lambda m: f"{m.group('key')}{_REDACTED}", result)
    result = _FLAG_VALUE_RE.sub(lambda m: f"{m.group('flag')}{m.group('sep')}{_REDACTED}", result)
    return result


def redact_json(value: object) -> object:
    """redact_secrets() applied to every string inside a JSON-like value, and
    to the value of any key whose name is a secret word, so a structured
    result is clean as a whole and not only in the fields somebody remembered
    to redact. This is the single point the CLI, the evidence files and the
    audit journal go through."""
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, (list, tuple)):
        return [redact_json(item) for item in value]
    if isinstance(value, dict):
        cleaned: dict = {}
        for key, item in value.items():
            if (
                isinstance(key, str) and _SECRET_KEY_PATTERN.fullmatch(key + ":")
                and isinstance(item, (str, int, float)) and not isinstance(item, bool)
            ):
                cleaned[str(key)] = _REDACTED
            else:
                cleaned[str(key)] = redact_json(item)
        return cleaned
    return value


def redact_lines(lines: list[str]) -> list[str]:
    """redact_secrets() applied across the WHOLE joined text, then split
    back into lines - REQUIRED so a real secret shape that spans multiple
    list entries (a PEM block whose own BEGIN/END markers land in two
    different lines of a bounded log excerpt) is still recognized as one
    real shape, instead of two line-local fragments neither of which
    matches `_PEM_BLOCK_RE` on its own. Redacting line-by-line used to miss
    exactly this real case."""
    if not lines:
        return []
    return redact_secrets("\n".join(lines)).split("\n")
