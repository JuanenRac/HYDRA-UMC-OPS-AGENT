# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/_atomic.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
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

import contextlib
import os
import tempfile
import time
from pathlib import Path
from typing import Iterator


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


@contextlib.contextmanager
def exclusive_lock(path: Path, *, timeout_s: float = 30.0) -> Iterator[None]:
    """Holds an exclusive lock for `path` (on a `<name>.lock` file beside it)
    for the duration of the block, so two processes that read, change and
    write the same file one after the other cannot overwrite each other's
    result. Waits up to `timeout_s` for another holder, then raises
    `TimeoutError`."""
    lock_path = Path(path).with_name(Path(path).name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")  # noqa: SIM115 - kept open for as long as the lock is held
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"another process is holding {lock_path} - gave up after {timeout_s} s") from None
                time.sleep(0.1)
        try:
            yield
        finally:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        handle.close()
