# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_verification.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import http.server
import shutil
import socket
import threading
import unittest

from hydra_umc_ops_agent.incident import MaintenanceIncident
from hydra_umc_ops_agent.verification import VerificationError, VerificationResult, verify_incident_resolved


def _make_incident(component: str, symptom: str) -> MaintenanceIncident:
    return MaintenanceIncident(
        incident_id="inc-1",
        source_node="cm5-cell-3",
        detected_at="2026-09-06T12:00:00+00:00",
        severity="critical",
        component=component,
        symptom=symptom,
        evidence_refs=(component,),
        redaction_level="sanitized",
        requested_by="edge-agent:auto",
        correlation_id="corr-1",
    )


class _OkHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        pass


class VerifyHttpIncidentTests(unittest.TestCase):
    def _serve(self, handler_cls):
        server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(thread.join, 2)
        return server.server_address[1]

    def test_a_now_healthy_http_incident_is_reported_resolved(self):
        port = self._serve(_OkHandler)
        url = f"http://127.0.0.1:{port}/health"
        incident = _make_incident(url, f"health endpoint check failed: unreachable: earlier failure")
        result = verify_incident_resolved(incident)
        self.assertTrue(result.resolved)
        self.assertEqual(result.incident_id, "inc-1")

    def test_a_still_unreachable_http_incident_is_reported_unresolved(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        url = f"http://127.0.0.1:{port}/health"
        incident = _make_incident(url, "health endpoint check failed: unreachable: earlier failure")
        result = verify_incident_resolved(incident, timeout_s=1.0)
        self.assertFalse(result.resolved)


class VerifySystemdIncidentTests(unittest.TestCase):
    def test_honest_error_when_systemctl_is_not_on_this_host(self):
        if shutil.which("systemctl") is not None:
            self.skipTest("this host has a real systemctl - covered by a different real environment")
        incident = _make_incident("hydra-umc-server.service", "systemd unit is not active: inactive")
        with self.assertRaises(VerificationError):
            verify_incident_resolved(incident)


class VerifyManifestIncidentTests(unittest.TestCase):
    def test_a_manifest_incident_raises_a_real_explanatory_error_not_a_guess(self):
        incident = _make_incident("/some/path/hydra-umc.project.json", "manifest scan issue: not valid JSON: ...")
        with self.assertRaises(VerificationError) as ctx:
            verify_incident_resolved(incident)
        self.assertIn("edge collect", str(ctx.exception))


class VerifyUnrecognizedIncidentTests(unittest.TestCase):
    def test_an_unrecognized_symptom_shape_raises_a_real_error(self):
        incident = _make_incident("whatever", "something this module has never seen before")
        with self.assertRaises(VerificationError):
            verify_incident_resolved(incident)


class VerificationResultFromDictTests(unittest.TestCase):
    """V07-021 (found in an independent revalidation audit, P2):
    from_dict() is a real public loading boundary - whatever produced
    `data` need not be this module's own to_dict(). `bool(data["resolved"])`
    used to coerce ANY non-empty value, including the literal textual
    string "false", to True (Python's own bool("false") is True - a
    non-empty string is always truthy). A publicly-loaded 'false' would
    silently become a resolved=True incident."""

    def _payload(self, **overrides):
        payload = {"incidentId": "i", "verifiedAt": "now", "resolved": False, "detail": "test"}
        payload.update(overrides)
        return payload

    def test_a_real_boolean_false_round_trips_as_false(self):
        result = VerificationResult.from_dict(self._payload(resolved=False))
        self.assertIs(result.resolved, False)

    def test_a_real_boolean_true_round_trips_as_true(self):
        result = VerificationResult.from_dict(self._payload(resolved=True))
        self.assertIs(result.resolved, True)

    def test_the_textual_string_false_is_rejected_not_coerced_to_true(self):
        # The audit's own exact reproduction: bool("false") is True.
        with self.assertRaises(VerificationError):
            VerificationResult.from_dict(self._payload(resolved="false"))

    def test_other_non_boolean_resolved_values_are_also_rejected(self):
        for bad in (0, 1, "0", None, [], {}):
            with self.subTest(bad=bad):
                with self.assertRaises(VerificationError):
                    VerificationResult.from_dict(self._payload(resolved=bad))

    def test_an_empty_incident_id_is_rejected(self):
        with self.assertRaises(VerificationError):
            VerificationResult.from_dict(self._payload(incidentId=""))

    def test_a_non_string_detail_is_rejected_instead_of_silently_stringified(self):
        with self.assertRaises(VerificationError):
            VerificationResult.from_dict(self._payload(detail=12345))


if __name__ == "__main__":
    unittest.main()
