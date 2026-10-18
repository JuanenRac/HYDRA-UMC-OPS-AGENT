# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/audit_journal.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""An append-only record of what was proposed, approved, rejected, deployed
and verified: one JSON object per line, each carrying the SHA-256 of the line
before it. Removing, editing or reordering a line breaks every hash after it,
and `verify_chain()` says where.

The chain proves the file was not changed in the middle; it cannot prove that
the last lines were not cut off, nor stop someone who rewrites the whole file.
Keep a copy elsewhere (or sign the last hash) if that matters.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._atomic import exclusive_lock
from .log_redaction import redact_json

GENESIS_HASH = "0" * 64


class AuditJournalError(RuntimeError):
    """The journal could not be read or written."""


def _redacted(value: Any) -> Any:
    return redact_json(value)


def _hash_of(entry: dict[str, Any]) -> str:
    body = {key: value for key, value in entry.items() if key != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def _read_lines(path: Path) -> list[str]:
    try:
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise AuditJournalError(f"could not read the audit journal {path}: {exc}") from exc


def append_event(path: Path, event: str, data: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Appends one event and returns the stored entry. Safe against two
    processes appending at the same time."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(path):
            lines = _read_lines(path)
            previous, sequence = GENESIS_HASH, 0
            if lines:
                try:
                    last = json.loads(lines[-1])
                    previous, sequence = str(last["hash"]), int(last["seq"])
                except (ValueError, KeyError, TypeError) as exc:
                    raise AuditJournalError(f"the last line of {path} is not a valid journal entry: {exc}") from exc
            try:
                user = getpass.getuser()
            except Exception:  # noqa: BLE001 - no login name is not a reason to lose the record
                user = "unknown"
            entry: dict[str, Any] = {
                "seq": sequence + 1,
                "at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
                "event": event,
                "user": user,
                "host": platform.node(),
                "data": _redacted(data),
                "prev": previous,
            }
            entry["hash"] = _hash_of(entry)
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(entry, sort_keys=True) + "\n")
                stream.flush()
            return entry
    except OSError as exc:
        raise AuditJournalError(f"could not write the audit journal {path}: {exc}") from exc


def read_events(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for number, line in enumerate(_read_lines(Path(path)), start=1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuditJournalError(f"line {number} of {path} is not valid JSON: {exc}") from exc
        if not isinstance(entry, dict):
            raise AuditJournalError(f"line {number} of {path} is not an object")
        entries.append(entry)
    return entries


def verify_chain(path: Path) -> list[str]:
    """The problems found in the hash chain of `path` (empty when it is intact)."""
    try:
        entries = read_events(Path(path))
    except AuditJournalError as exc:
        return [str(exc)]
    problems: list[str] = []
    previous = GENESIS_HASH
    for index, entry in enumerate(entries, start=1):
        if entry.get("seq") != index:
            problems.append(f"entry {index}: sequence number is {entry.get('seq')!r}, expected {index}")
        if entry.get("prev") != previous:
            problems.append(f"entry {index}: does not follow the entry before it")
        if entry.get("hash") != _hash_of(entry):
            problems.append(f"entry {index}: its content does not match its hash")
        previous = str(entry.get("hash"))
    return problems
