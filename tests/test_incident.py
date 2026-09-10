# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_incident.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import unittest

from hydra_umc_ops_agent.incident import (
    REDACTION_LEVEL_SANITIZED,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    IncidentBatch,
    MaintenanceIncident,
)
from hydra_umc_ops_agent.inventory import HttpHealthResult, ManifestScanIssue, ServiceHealthResult


class MaintenanceIncidentRoundTripTests(unittest.TestCase):
    def test_to_dict_uses_the_real_contract_field_names(self):
        incident = MaintenanceIncident(
            incident_id="i1", source_node="cm5-1", detected_at="2026-01-01T00:00:00+00:00",
            severity=SEVERITY_WARNING, component="comp", symptom="something",
            evidence_refs=("ref1",), redaction_level=REDACTION_LEVEL_SANITIZED,
            requested_by="edge-agent:auto", correlation_id="c1",
        )
        data = incident.to_dict()
        self.assertEqual(data["incidentId"], "i1")
        self.assertEqual(data["sourceNode"], "cm5-1")
        self.assertEqual(data["evidenceRefs"], ["ref1"])
        self.assertEqual(data["correlationId"], "c1")

    def test_to_dict_redacts_a_secret_that_ended_up_in_the_symptom_text(self):
        incident = MaintenanceIncident(
            incident_id="i1", source_node="cm5-1", detected_at="now",
            severity=SEVERITY_WARNING, component="comp",
            symptom="config error: DB_PASSWORD=hunter2 could not connect",
            evidence_refs=(), redaction_level=REDACTION_LEVEL_SANITIZED,
            requested_by="edge-agent:auto", correlation_id="c1",
        )
        self.assertNotIn("hunter2", incident.to_dict()["symptom"])

    def test_to_dict_redacts_a_secret_that_ended_up_in_component_or_evidence_refs(self):
        # V07-010 (P1, residual outside REV-013's own three original examples):
        # component/evidenceRefs (often a real URL, e.g. a configured
        # http_health_urls entry with embedded userinfo credentials)
        # were never redacted here, while redactionLevel unconditionally
        # still claimed the whole record was "sanitized".
        incident = MaintenanceIncident(
            incident_id="i1", source_node="cm5-1", detected_at="now",
            severity=SEVERITY_WARNING, component="https://audit:hunter2@example.invalid/health",
            symptom="unreachable", evidence_refs=("DB_PASSWORD=hunter2",),
            redaction_level=REDACTION_LEVEL_SANITIZED,
            requested_by="edge-agent:auto", correlation_id="c1",
        )
        data = incident.to_dict()
        self.assertNotIn("hunter2", data["component"])
        self.assertNotIn("hunter2", data["evidenceRefs"][0])

    def test_round_trips_through_from_dict(self):
        original = MaintenanceIncident(
            incident_id="i1", source_node="cm5-1", detected_at="now",
            severity=SEVERITY_CRITICAL, component="comp", symptom="symptom",
            evidence_refs=("a", "b"), redaction_level=REDACTION_LEVEL_SANITIZED,
            requested_by="edge-agent:auto", correlation_id="c1",
        )
        restored = MaintenanceIncident.from_dict(original.to_dict())
        self.assertEqual(original, restored)


class IncidentBatchTests(unittest.TestCase):
    def test_all_incidents_in_one_batch_share_the_same_correlation_id(self):
        batch = IncidentBatch()
        batch.add_manifest_issue("cm5-1", ManifestScanIssue(path="p1", reason="bad"))
        batch.add_manifest_issue("cm5-1", ManifestScanIssue(path="p2", reason="also bad"))
        self.assertEqual(len(batch.incidents), 2)
        self.assertEqual(batch.incidents[0].correlation_id, batch.incidents[1].correlation_id)

    def test_two_separate_batches_get_different_correlation_ids(self):
        self.assertNotEqual(IncidentBatch().correlation_id, IncidentBatch().correlation_id)

    def test_manifest_issue_is_always_a_real_incident(self):
        batch = IncidentBatch()
        incident = batch.add_manifest_issue("cm5-1", ManifestScanIssue(path="p1", reason="bad"))
        self.assertEqual(incident.severity, SEVERITY_WARNING)
        self.assertIn("p1", incident.component)

    def test_a_healthy_service_produces_no_incident_at_all(self):
        batch = IncidentBatch()
        result = batch.add_service_health("cm5-1", ServiceHealthResult(unit_name="x.service", active=True, detail="active"))
        self.assertIsNone(result)
        self.assertEqual(batch.incidents, [])

    def test_an_inactive_service_produces_a_real_critical_incident(self):
        batch = IncidentBatch()
        incident = batch.add_service_health("cm5-1", ServiceHealthResult(unit_name="x.service", active=False, detail="failed"))
        self.assertIsNotNone(incident)
        self.assertEqual(incident.severity, SEVERITY_CRITICAL)
        self.assertEqual(incident.component, "x.service")

    def test_a_reachable_http_endpoint_produces_no_incident(self):
        batch = IncidentBatch()
        result = batch.add_http_health("cm5-1", HttpHealthResult(url="http://x", reachable=True, status_code=200, detail="HTTP 200"))
        self.assertIsNone(result)

    def test_an_unreachable_http_endpoint_produces_a_real_warning_incident(self):
        batch = IncidentBatch()
        incident = batch.add_http_health("cm5-1", HttpHealthResult(url="http://x", reachable=False, status_code=None, detail="unreachable: refused"))
        self.assertIsNotNone(incident)
        self.assertEqual(incident.severity, SEVERITY_WARNING)


if __name__ == "__main__":
    unittest.main()
