# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_incident_store.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""real deduplication/persistence of MaintenanceIncidents
across multiple scans - no mocking, real temp files on disk."""
import json
import tempfile
import unittest
from pathlib import Path

from hydra_umc_ops_agent.incident import MaintenanceIncident
from hydra_umc_ops_agent.incident_store import (
    IncidentStoreError,
    TrackedIncident,
    load_incident_store,
    reconcile_incidents,
    save_incident_store,
)


def _incident(component: str, symptom: str = "s", source_node: str = "node-1", incident_id: str = "i1") -> MaintenanceIncident:
    return MaintenanceIncident(
        incident_id=incident_id, source_node=source_node, detected_at="2026-01-01T00:00:00+00:00",
        severity="critical", component=component, symptom=symptom, evidence_refs=("ref",),
        redaction_level="sanitized", requested_by="edge-agent:auto", correlation_id="c1",
    )


class ReconcileIncidentsTests(unittest.TestCase):
    def test_a_brand_new_incident_on_an_empty_store_is_tracked_as_a_new_open_record(self):
        result = reconcile_incidents([], [_incident("unit-a")], {("node-1", "unit-a")})
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0].resolved_at)
        self.assertEqual(result[0].occurrence_count, 1)

    def test_the_same_real_problem_reoccurring_keeps_the_same_incident_id_and_bumps_occurrence_count(self):
        first = reconcile_incidents([], [_incident("unit-a", incident_id="original-id")], {("node-1", "unit-a")})
        second = reconcile_incidents(first, [_incident("unit-a", symptom="different detail now", incident_id="fresh-uuid-2")], {("node-1", "unit-a")})

        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].incident.incident_id, "original-id", "the durable incidentId must never change across occurrences")
        self.assertEqual(second[0].incident.symptom, "different detail now", "the latest symptom must be reflected")
        self.assertEqual(second[0].occurrence_count, 2)

    def test_a_component_genuinely_rechecked_and_now_clean_gets_resolved(self):
        open_store = reconcile_incidents([], [_incident("unit-a")], {("node-1", "unit-a")})

        resolved = reconcile_incidents(open_store, [], {("node-1", "unit-a")}, now="2026-01-02T00:00:00+00:00")

        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].resolved_at, "2026-01-02T00:00:00+00:00")

    def test_a_component_simply_not_checked_this_run_stays_open_untouched(self):
        open_store = reconcile_incidents([], [_incident("unit-a")], {("node-1", "unit-a")})

        # checked_components is empty this run - unit-a was never asked
        # about at all, so its open record must NOT be silently resolved.
        still_open = reconcile_incidents(open_store, [], set())

        self.assertEqual(len(still_open), 1)
        self.assertIsNone(still_open[0].resolved_at)

    def test_a_problem_that_reoccurs_after_being_resolved_starts_a_genuinely_new_incident(self):
        opened = reconcile_incidents([], [_incident("unit-a", incident_id="first-id")], {("node-1", "unit-a")})
        closed = reconcile_incidents(opened, [], {("node-1", "unit-a")})
        reopened = reconcile_incidents(closed, [_incident("unit-a", incident_id="second-id")], {("node-1", "unit-a")})

        open_records = [t for t in reopened if t.resolved_at is None]
        self.assertEqual(len(open_records), 1)
        self.assertEqual(open_records[0].incident.incident_id, "second-id")
        self.assertEqual(open_records[0].occurrence_count, 1)
        # The original closed record is preserved as real history, never
        # dropped.
        closed_records = [t for t in reopened if t.resolved_at is not None]
        self.assertEqual(len(closed_records), 1)
        self.assertEqual(closed_records[0].incident.incident_id, "first-id")

    def test_different_components_never_get_conflated(self):
        result = reconcile_incidents([], [_incident("unit-a"), _incident("unit-b")], {("node-1", "unit-a"), ("node-1", "unit-b")})
        self.assertEqual(len(result), 2)


class LoadSaveIncidentStoreTests(unittest.TestCase):
    def test_a_never_written_store_is_a_real_empty_list_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_incident_store(Path(tmp) / "store.json"), [])

    def test_save_then_load_round_trips_a_real_tracked_incident(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "store.json"
            tracked = TrackedIncident(
                incident=_incident("unit-a"), first_seen_at="2026-01-01T00:00:00+00:00",
                last_seen_at="2026-01-01T00:00:00+00:00", occurrence_count=3, resolved_at=None,
            )
            save_incident_store([tracked], path)

            loaded = load_incident_store(path)

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].incident.incident_id, tracked.incident.incident_id)
            self.assertEqual(loaded[0].occurrence_count, 3)

    def test_a_malformed_store_file_raises_a_real_named_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(IncidentStoreError):
                load_incident_store(path)

    def test_a_store_file_that_is_not_a_json_array_raises_a_real_named_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.json"
            path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
            with self.assertRaises(IncidentStoreError):
                load_incident_store(path)


if __name__ == "__main__":
    unittest.main()
