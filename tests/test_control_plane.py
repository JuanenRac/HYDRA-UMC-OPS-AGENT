# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_control_plane.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import json
import tempfile
import unittest
from pathlib import Path

from hydra_umc_ops_agent.control_plane import SnapshotLoadError, load_snapshot, render_snapshot_report


class LoadSnapshotTests(unittest.TestCase):
    def test_a_missing_file_is_a_real_typed_error(self):
        with self.assertRaises(SnapshotLoadError):
            load_snapshot(Path(tempfile.gettempdir()) / "definitely-does-not-exist-ops-agent.json")

    def test_malformed_json_is_a_real_typed_error(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not json")
            path = Path(f.name)
        try:
            with self.assertRaises(SnapshotLoadError):
                load_snapshot(path)
        finally:
            path.unlink()

    def test_a_json_array_instead_of_object_is_a_real_typed_error(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("[1, 2, 3]")
            path = Path(f.name)
        try:
            with self.assertRaises(SnapshotLoadError):
                load_snapshot(path)
        finally:
            path.unlink()

    def test_a_real_valid_snapshot_loads_correctly(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"sourceNode": "cm5-1"}, f)
            path = Path(f.name)
        try:
            data = load_snapshot(path)
            self.assertEqual(data["sourceNode"], "cm5-1")
        finally:
            path.unlink()


class RenderSnapshotReportTests(unittest.TestCase):
    def test_an_empty_snapshot_renders_without_crashing(self):
        report = render_snapshot_report({"sourceNode": "cm5-1", "collectedAt": "now"})
        self.assertIn("cm5-1", report)
        self.assertIn("Incidents: 0", report)
        # V07-020: systemdAvailable absent (None) must render as a real
        # "never attempted" state, never silently treated as True.
        self.assertIn("not attempted", report)

    def test_a_real_checked_systemd_unit_renders_its_own_health(self):
        # V07-020: True (actually checked, systemd answered) must be
        # distinguished from None (never attempted) - both from
        # False (checked, systemd itself unavailable), already covered
        # by test_projects_and_incidents_appear_in_the_report below.
        snapshot = {
            "sourceNode": "cm5-1",
            "collectedAt": "now",
            "systemdAvailable": True,
            "serviceHealth": [{"unitName": "hydra-umc-server.service", "active": True, "detail": "active (running)"}],
        }
        report = render_snapshot_report(snapshot)
        self.assertIn("Service health checks: 1", report)
        self.assertIn("hydra-umc-server.service: active", report)
        self.assertNotIn("not attempted", report)

    def test_projects_and_incidents_appear_in_the_report(self):
        snapshot = {
            "sourceNode": "cm5-1",
            "collectedAt": "now",
            "projects": [{"name": "PROJ", "version": "1.0.0", "maturity": "established"}],
            "systemdAvailable": False,
            "systemdUnavailableReason": "no systemctl",
            "incidents": [
                {"severity": "critical", "component": "x.service", "symptom": "down", "incidentId": "i1"},
                {"severity": "warning", "component": "y", "symptom": "flaky", "incidentId": "i2"},
            ],
        }
        report = render_snapshot_report(snapshot)
        self.assertIn("PROJ v1.0.0", report)
        self.assertIn("Incidents: 2", report)
        self.assertIn("no systemctl", report)
        # Critical must be listed before warning regardless of input order.
        self.assertLess(report.index("[CRITICAL]"), report.index("[WARNING]"))

    def test_an_unhashable_severity_never_crashes_the_sort(self):
        # V07-011 (P2, residual of REV-014): `severity` is real, publicly-loaded
        # data - a real `[]`/`{}` used to raise TypeError straight out
        # of the sort key's own dict.get() (unhashable types can't be
        # looked up in a dict at all), crashing the entire report.
        snapshot = {
            "sourceNode": "cm5-1",
            "collectedAt": "now",
            "incidents": [
                {"severity": [], "component": "a", "symptom": "s", "incidentId": "i1"},
                {"severity": "critical", "component": "b", "symptom": "s", "incidentId": "i2"},
                {"severity": {}, "component": "c", "symptom": "s", "incidentId": "i3"},
            ],
        }
        report = render_snapshot_report(snapshot)  # must not raise
        self.assertIn("Incidents: 3", report)
        # The real, string severity still sorts to the front.
        self.assertLess(report.index("[CRITICAL]"), report.index("id=i1"))

    def test_a_textual_false_never_reads_as_a_real_active_or_reachable_state(self):
        # V07-011: `bool("false")` is True in Python - a real,
        # publicly-loaded "false" string must never render as if the
        # service/endpoint were actually active/reachable.
        snapshot = {
            "sourceNode": "cm5-1",
            "collectedAt": "now",
            "systemdAvailable": True,
            "serviceHealth": [{"unitName": "x.service", "active": "false", "detail": "d"}],
            "httpHealth": [{"url": "http://x", "reachable": "false", "detail": "d"}],
        }
        report = render_snapshot_report(snapshot)
        self.assertIn("x.service: NOT ACTIVE", report)
        self.assertIn("http://x: UNREACHABLE", report)

    # REV-014 regression: found while auditing the code: `projects=[null]` (JSON-valid,
    # structurally malformed) crashing this renderer with AttributeError -
    # `null.get(...)` - deep inside the loop below. A malformed entry must
    # be skipped and counted, never crash an otherwise-valid report.
    def test_a_null_entry_in_projects_is_skipped_not_crashed_on(self):
        snapshot = {
            "sourceNode": "cm5-1",
            "collectedAt": "now",
            "projects": [{"name": "GOOD", "version": "1.0.0", "maturity": "established"}, None],
        }
        report = render_snapshot_report(snapshot)
        self.assertIn("GOOD v1.0.0", report)
        self.assertIn("Projects found: 1", report)
        self.assertIn("1 malformed entry skipped", report)

    def test_a_string_entry_in_incidents_is_skipped_not_crashed_on(self):
        snapshot = {
            "sourceNode": "cm5-1",
            "collectedAt": "now",
            "incidents": [
                {"severity": "critical", "component": "x", "symptom": "down", "incidentId": "i1"},
                "not-a-real-incident",
                42,
            ],
        }
        report = render_snapshot_report(snapshot)
        self.assertIn("Incidents: 1", report)
        self.assertIn("2 malformed entries skipped", report)

    def test_a_non_list_section_never_crashes_and_reports_zero(self):
        report = render_snapshot_report({"sourceNode": "cm5-1", "collectedAt": "now", "projects": "not-a-list"})
        self.assertIn("Projects found: 0", report)


if __name__ == "__main__":
    unittest.main()
