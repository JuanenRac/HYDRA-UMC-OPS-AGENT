# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/host_health.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""What the machine itself says about its health: free disk space, temperature, throttling and the backups on disk.

Everything here is a read: it asks the operating system (`shutil.disk_usage`, the thermal zone file, `vcgencmd get_throttled` on a Raspberry Pi,
the listing of the backup folder) and never changes anything. A reading the machine cannot give (no thermal zone, no `vcgencmd`) is said as
unavailable, never guessed and never turned into an incident: a development machine is not a failing CM5.

The thresholds live in the `host_checks` section of the configuration file (see `config.py` and `deploy/ops-agent.json.example`), never here.
The readings are injectable so the logic is tested without a Raspberry Pi.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import HostChecksConfig

THERMAL_ZONE_FILE = Path("/sys/class/thermal/thermal_zone0/temp")

# the bits of `vcgencmd get_throttled` (Raspberry Pi firmware documentation)
THROTTLED_NOW_BITS = {0: "under-voltage now", 1: "arm frequency capped now", 2: "throttled now", 3: "soft temperature limit active now"}
THROTTLED_PAST_BITS = {16: "under-voltage has occurred", 17: "arm frequency cap has occurred", 18: "throttling has occurred", 19: "soft temperature limit has occurred"}


@dataclass(frozen=True)
class DiskReading:
    path: str
    free_bytes: int | None
    total_bytes: int | None
    free_percent: float | None
    error: str | None = None


@dataclass(frozen=True)
class ThermalReading:
    celsius: float | None
    throttled_raw: int | None
    throttled_now: tuple[str, ...]
    throttled_past: tuple[str, ...]
    vcgencmd_available: bool


@dataclass(frozen=True)
class BackupReading:
    directory: str
    count: int | None
    newest_age_days: float | None
    error: str | None = None


@dataclass(frozen=True)
class HostHealth:
    disks: tuple[DiskReading, ...]
    thermal: ThermalReading
    backups: BackupReading | None

    def to_dict(self) -> dict[str, object]:
        return {
            "disks": [{"path": d.path, "freeBytes": d.free_bytes, "totalBytes": d.total_bytes,
                       "freePercent": d.free_percent, "error": d.error} for d in self.disks],
            "thermal": {"celsius": self.thermal.celsius, "throttledRaw": self.thermal.throttled_raw,
                        "throttledNow": list(self.thermal.throttled_now), "throttledPast": list(self.thermal.throttled_past),
                        "vcgencmdAvailable": self.thermal.vcgencmd_available},
            "backups": None if self.backups is None else {
                "directory": self.backups.directory, "count": self.backups.count,
                "newestAgeDays": self.backups.newest_age_days, "error": self.backups.error},
        }


def disk_paths(settings: HostChecksConfig) -> tuple[str, ...]:
    return tuple(part.strip() for part in settings.disk_paths.split(",") if part.strip())


def read_disk(path: str, usage: Callable[[str], object] = shutil.disk_usage) -> DiskReading:
    try:
        reading = usage(path)
        total = int(reading.total)  # type: ignore[attr-defined]
        free = int(reading.free)  # type: ignore[attr-defined]
    except (OSError, ValueError, AttributeError) as exc:
        return DiskReading(path, None, None, None, f"{exc.__class__.__name__}")
    percent = round(100.0 * free / total, 1) if total > 0 else None
    return DiskReading(path, free, total, percent)


def read_celsius(thermal_file: Path = THERMAL_ZONE_FILE) -> float | None:
    try:
        return int(thermal_file.read_text(encoding="ascii").strip()) / 1000.0
    except (OSError, ValueError):
        return None


def decode_throttled(raw: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    now = tuple(text for bit, text in THROTTLED_NOW_BITS.items() if raw & (1 << bit))
    past = tuple(text for bit, text in THROTTLED_PAST_BITS.items() if raw & (1 << bit))
    return now, past


def run_vcgencmd_throttled(timeout_s: float) -> int | None:
    """The value of `vcgencmd get_throttled`, or None when the command is not there, fails or prints something else."""
    executable = shutil.which("vcgencmd")
    if executable is None:
        return None
    try:
        result = subprocess.run([executable, "get_throttled"], capture_output=True, text=True, timeout=timeout_s, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None
    text = (result.stdout or "").strip()
    if result.returncode != 0 or not text.startswith("throttled=0x"):
        return None
    try:
        return int(text.split("=", 1)[1], 16)
    except ValueError:
        return None


def read_backups(directory: str, now: float, pattern: str) -> BackupReading:
    folder = Path(directory)
    try:
        files = [entry for entry in folder.glob(pattern) if entry.is_file()]
    except OSError as exc:
        return BackupReading(directory, None, None, exc.__class__.__name__)
    if not folder.is_dir():
        return BackupReading(directory, None, None, "the backup folder does not exist")
    newest: float | None = None
    for entry in files:
        try:
            modified = entry.stat().st_mtime
        except OSError:
            continue
        newest = modified if newest is None or modified > newest else newest
    age = None if newest is None else round(max(0.0, now - newest) / 86400.0, 2)
    return BackupReading(directory, len(files), age)


def collect_host_health(
    settings: HostChecksConfig,
    *,
    usage: Callable[[str], object] = shutil.disk_usage,
    thermal_file: Path = THERMAL_ZONE_FILE,
    throttled: Callable[[float], int | None] = run_vcgencmd_throttled,
    clock: Callable[[], float] = time.time,
) -> HostHealth:
    disks = tuple(read_disk(path, usage) for path in disk_paths(settings))
    raw = throttled(settings.vcgencmd_timeout_seconds) if settings.check_throttling else None
    now_flags, past_flags = decode_throttled(raw) if raw is not None else ((), ())
    thermal = ThermalReading(read_celsius(thermal_file), raw, now_flags, past_flags, raw is not None)
    backups = read_backups(settings.backup_dir, clock(), settings.backup_pattern) if settings.backup_dir else None
    return HostHealth(disks, thermal, backups)
