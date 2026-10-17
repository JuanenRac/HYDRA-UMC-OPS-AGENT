# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/_atomic.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Durable, all-or-nothing file writes for the files this tool keeps between
runs (the incident store, change proposals, snapshots, results).

A plain `write_text` truncates the target first and writes second, so a power
cut or a kill in between leaves a half-written file - for the incident store
that means every later `edge collect` refuses to start until a person deletes
it, and for a proposal being approved it means the reviewed diff is gone.
This writes a temporary file next to the target, flushes it to disk, and only
then renames it over the target; the rename is atomic, so a reader (or a
restart) sees either the old content or the new content, never a mixture.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
