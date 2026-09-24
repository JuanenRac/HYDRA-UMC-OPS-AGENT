# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_verification.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import http.server
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from hydra_umc_ops_agent.incident import IncidentBatch, MaintenanceIncident
from hydra_umc_ops_agent.inventory import ManifestScanIssue
from hydra_umc_ops_agent.verification import SdkUnavailableError, VerificationError, VerificationResult, verify_incident_resolved

try:
    import hydra_umc_sdk  # noqa: F401
    _SDK_INSTALLED = True
except ImportError:
    _SDK_INSTALLED = False


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


def _git(command, cwd):
    subprocess.run(["git", *command], cwd=str(cwd), check=True, capture_output=True)


def _init_and_commit_manifest(root: Path, **fields) -> Path:
    manifest = root / "hydra-umc.project.json"
    manifest.write_text(json.dumps(fields), encoding="utf-8")
    _git(["init", "--quiet"], root)
    _git(["config", "user.name", "test"], root)
    _git(["config", "user.email", "test@example.invalid"], root)
    _git(["add", "hydra-umc.project.json"], root)
    _git(["commit", "-m", "c1", "--no-verify"], root)
    return manifest


@unittest.skipUnless(_SDK_INSTALLED, "the optional 'hydra-umc-sdk' extra is not installed")
class VerifyManifestIncidentWithBaseCommitTests(unittest.TestCase):
    """N01: once a manifest incident carries a real `base_commit:` (see
    incident.py's own add_manifest_issue()), verification re-checks the
    manifest AND runs the shared compare_runs T07/control against
    the checkout's real current commit."""

    def setUp(self):
        if shutil.which("git") is None:
            self.skipTest("no real git on this host")
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_manifest_fixed_by_a_real_new_commit_is_reported_resolved(self):
        manifest = _init_and_commit_manifest(self.root)  # no name/version/maturity - a real issue
        batch = IncidentBatch()
        incident = batch.add_manifest_issue("cm5-1", ManifestScanIssue(path=str(manifest), reason="missing/empty required field(s): name, version, maturity"))

        # The real fix, actually committed - the base genuinely moves.
        manifest.write_text(json.dumps({"name": "P", "version": "1.0.0", "maturity": "functional"}), encoding="utf-8")
        _git(["add", "hydra-umc.project.json"], self.root)
        _git(["commit", "-m", "fix", "--no-verify"], self.root)

        result = verify_incident_resolved(incident)
        self.assertTrue(result.resolved)

    def test_a_still_broken_manifest_is_reported_unresolved(self):
        manifest = _init_and_commit_manifest(self.root)
        batch = IncidentBatch()
        incident = batch.add_manifest_issue("cm5-1", ManifestScanIssue(path=str(manifest), reason="missing/empty required field(s): name, version, maturity"))
        # Nothing committed since - still genuinely broken.
        result = verify_incident_resolved(incident)
        self.assertFalse(result.resolved)

    def test_an_uncommitted_hand_edit_is_reported_unresolved_as_apparent_success(self):
        # The whole point of N01: the file now LOOKS fine, but the
        # checkout's own commit never actually moved - a real, plausible
        # "fixed on disk, never committed" trap this must not miss.
        manifest = _init_and_commit_manifest(self.root)
        batch = IncidentBatch()
        incident = batch.add_manifest_issue("cm5-1", ManifestScanIssue(path=str(manifest), reason="missing/empty required field(s): name, version, maturity"))

        manifest.write_text(json.dumps({"name": "P", "version": "1.0.0", "maturity": "functional"}), encoding="utf-8")
        # Deliberately never committed.

        result = verify_incident_resolved(incident)
        self.assertFalse(result.resolved)
        self.assertIn("nothing was actually applied", result.detail)


class VerifyManifestIncidentSdkUnavailableTests(unittest.TestCase):
    """Real even without the optional extra installed at all - a manifest
    incident carrying a base_commit is refused with a typed, actionable
    error, never a bare ImportError, when 'hydra-umc-sdk' is missing."""

    def test_a_missing_sdk_raises_a_real_typed_actionable_error(self):
        import sys
        from unittest import mock

        incident = MaintenanceIncident(
            incident_id="i1", source_node="cm5-1", detected_at="2026-09-06T12:00:00+00:00",
            severity="warning", component="/some/path/hydra-umc.project.json",
            symptom="manifest scan issue: not valid JSON: ...",
            evidence_refs=("/some/path/hydra-umc.project.json", "base_commit:deadbeef"),
            redaction_level="sanitized", requested_by="edge-agent:auto", correlation_id="c1",
        )
        with mock.patch.dict(sys.modules, {"hydra_umc_sdk": None}):
            with self.assertRaises(SdkUnavailableError) as ctx:
                verify_incident_resolved(incident)
        self.assertIn("hydra-umc-sdk", str(ctx.exception))
        self.assertIn("[sdk]", str(ctx.exception))


class VerifyUnrecognizedIncidentTests(unittest.TestCase):
    def test_an_unrecognized_symptom_shape_raises_a_real_error(self):
        incident = _make_incident("whatever", "something this module has never seen before")
        with self.assertRaises(VerificationError):
            verify_incident_resolved(incident)


class VerificationResultFromDictTests(unittest.TestCase):
    """
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
        # The review pass's own exact reproduction: bool("false") is True.
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
