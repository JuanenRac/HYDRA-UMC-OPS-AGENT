# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_host_health.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
import json
import os
import tempfile
import time
import unittest
from collections import namedtuple
from pathlib import Path

from hydra_umc_ops_agent.config import ConfigError, HostChecksConfig, parse_config
from hydra_umc_ops_agent.edge_agent import collect_snapshot
from hydra_umc_ops_agent.host_health import collect_host_health, decode_throttled, read_celsius
from hydra_umc_ops_agent.incident import IncidentBatch

Usage = namedtuple("Usage", "total used free")


def _settings(**changes) -> HostChecksConfig:
    base = {"enabled": True, "disk_paths": "/data", "backup_dir": None}
    base.update(changes)
    return HostChecksConfig(**base)


def _health(settings, *, free_percent=50.0, celsius=45.0, throttled=0, backups=None, now=None):
    thermal_dir = tempfile.TemporaryDirectory()
    self_files = Path(thermal_dir.name) / "temp"
    if celsius is not None:
        self_files.write_text(str(int(celsius * 1000)), encoding="ascii")
    health = collect_host_health(
        settings,
        usage=lambda path: Usage(1000, 1000 - int(free_percent * 10), int(free_percent * 10)),
        thermal_file=self_files,
        throttled=lambda timeout: throttled,
        clock=(lambda: now) if now is not None else time.time,
    )
    thermal_dir.cleanup()
    return health


class DecodeTests(unittest.TestCase):
    def test_the_bits_of_vcgencmd_are_named(self):
        now, past = decode_throttled(0x50005)
        self.assertEqual(now, ("under-voltage now", "throttled now"))
        self.assertEqual(past, ("under-voltage has occurred", "throttling has occurred"))
        self.assertEqual(decode_throttled(0), ((), ()))

    def test_a_missing_or_garbled_thermal_file_is_unavailable_not_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(read_celsius(Path(folder) / "missing"))
            bad = Path(folder) / "bad"
            bad.write_text("hot", encoding="ascii")
            self.assertIsNone(read_celsius(bad))


class IncidentTests(unittest.TestCase):
    def _incidents(self, settings, health):
        batch = IncidentBatch()
        return batch.add_host_health("cm5-a", settings, health)

    def test_a_healthy_host_produces_no_incident(self):
        settings = _settings()
        self.assertEqual(self._incidents(settings, _health(settings)), [])

    def test_low_disk_space_is_a_warning_then_critical(self):
        settings = _settings()
        warn = self._incidents(settings, _health(settings, free_percent=10.0))
        self.assertEqual([(i.severity, i.component) for i in warn], [("warning", "host:disk:/data")])
        critical = self._incidents(settings, _health(settings, free_percent=3.0))
        self.assertEqual([i.severity for i in critical], ["critical"])

    def test_the_threshold_is_the_one_of_the_configuration(self):
        settings = _settings(disk_warn_free_percent=60.0, disk_critical_free_percent=20.0)
        self.assertEqual(len(self._incidents(settings, _health(settings, free_percent=50.0))), 1)

    def test_heat_and_throttling_are_reported_when_the_machine_says_so(self):
        settings = _settings()
        hot = self._incidents(settings, _health(settings, celsius=78.0))
        self.assertEqual([(i.severity, i.component) for i in hot], [("warning", "host:temperature")])
        very_hot = self._incidents(settings, _health(settings, celsius=84.5))
        self.assertEqual([i.severity for i in very_hot], ["critical"])
        throttled = self._incidents(settings, _health(settings, throttled=0x4))
        self.assertEqual([(i.component, "throttled now" in i.symptom) for i in throttled], [("host:throttling", True)])
        past_only = self._incidents(settings, _health(settings, throttled=0x40000))
        self.assertEqual(past_only, [], "a flag that only says it happened earlier is data, not an open incident")

    def test_a_machine_that_cannot_answer_is_not_a_failing_machine(self):
        settings = _settings()
        health = _health(settings, celsius=None, throttled=None)
        self.assertIsNone(health.thermal.celsius)
        self.assertFalse(health.thermal.vcgencmd_available)
        self.assertEqual(self._incidents(settings, health), [])

    def test_backups_missing_or_old_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = _settings(backup_dir=folder, backup_pattern="*.tar.gz", backup_min_count=2, backup_max_age_days=3.0)
            empty = self._incidents(settings, _health(settings))
            self.assertEqual([i.component for i in empty], [f"host:backups:{folder}"])
            self.assertIn("0 backup(s) found", empty[0].symptom)
            old = Path(folder) / "a.tar.gz"
            old.write_bytes(b"x")
            (Path(folder) / "b.tar.gz").write_bytes(b"x")
            (Path(folder) / "notes.txt").write_bytes(b"x")
            past = time.time() - 10 * 86400
            os.utime(old, (past, past))
            os.utime(Path(folder) / "b.tar.gz", (past, past))
            health = _health(settings)
            self.assertEqual(health.backups.count, 2)
            stale = self._incidents(settings, health)
            self.assertEqual(len(stale), 1)
            self.assertIn("day(s) old", stale[0].symptom)
            os.utime(Path(folder) / "b.tar.gz", None)
            self.assertEqual(self._incidents(settings, _health(settings)), [])

    def test_a_backup_folder_that_does_not_exist_is_an_incident(self):
        settings = _settings(backup_dir="/nonexistent/hydra-backups")
        found = self._incidents(settings, _health(settings))
        self.assertEqual(len(found), 1)
        self.assertIn("cannot be read", found[0].symptom)

    def test_the_age_check_can_be_switched_off(self):
        with tempfile.TemporaryDirectory() as folder:
            old = Path(folder) / "a.tar.gz"
            old.write_bytes(b"x")
            past = time.time() - 400 * 86400
            os.utime(old, (past, past))
            settings = _settings(backup_dir=folder, backup_max_age_days=0.0)
            self.assertEqual(self._incidents(settings, _health(settings)), [])


class ConfigurationTests(unittest.TestCase):
    def test_off_by_default_and_validated(self):
        self.assertFalse(parse_config({}).host_checks.enabled)
        parsed = parse_config({"host_checks": {"enabled": True, "disk_paths": "/,/var/lib", "backup_dir": "/root/backups"}})
        self.assertTrue(parsed.host_checks.enabled)
        for bad in ({"disk_warn_free_percent": 200}, {"temperature_warn_celsius": 90, "temperature_critical_celsius": 80},
                    {"disk_warn_free_percent": 5, "disk_critical_free_percent": 10}, {"disk_paths": " , "}, {"unknown_key": 1}):
            with self.assertRaises(ConfigError, msg=str(bad)):
                parse_config({"host_checks": bad})


class SnapshotTests(unittest.TestCase):
    def test_the_snapshot_carries_the_readings_and_resolves_a_recovered_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "projects"
            root.mkdir()
            store = Path(folder) / "store.json"
            low = HostChecksConfig(enabled=True, disk_paths=folder, disk_warn_free_percent=100.0, disk_critical_free_percent=0.0, check_throttling=False)
            first = collect_snapshot("cm5-a", root, incident_store_path=store, host_checks=low)
            self.assertIsNotNone(first.host_health)
            self.assertEqual([i.component for i in first.incidents], [f"host:disk:{folder}"])
            data = json.loads(json.dumps(first.to_dict()))
            self.assertEqual(data["hostHealth"]["disks"][0]["path"], folder)
            fine = HostChecksConfig(enabled=True, disk_paths=folder, disk_warn_free_percent=0.0, disk_critical_free_percent=0.0, check_throttling=False)
            second = collect_snapshot("cm5-a", root, incident_store_path=store, host_checks=fine)
            self.assertEqual(second.incidents, ())
            stored = json.loads(store.read_text(encoding="utf-8"))
            self.assertTrue(json.dumps(stored).count("resolved") >= 1, "the open disk incident must be resolved once the disk is fine again")

    def test_without_host_checks_the_snapshot_is_what_it_always_was(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = collect_snapshot("cm5-a", Path(folder))
            self.assertIsNone(snapshot.host_health)
            self.assertNotIn("hostHealth", snapshot.to_dict())
            off = collect_snapshot("cm5-a", Path(folder), host_checks=HostChecksConfig())
            self.assertIsNone(off.host_health)


if __name__ == "__main__":
    unittest.main()
