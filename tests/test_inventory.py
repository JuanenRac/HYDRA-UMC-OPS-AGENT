# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_inventory.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import http.server
import json
import shutil
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from hydra_umc_ops_agent.inventory import (
    SystemdUnavailableError,
    check_http_health,
    check_systemd_unit_health,
    scan_project_manifests,
)


def _write_manifest(path: Path, **fields) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "hydra-umc.project.json").write_text(json.dumps(fields), encoding="utf-8")


class ScanProjectManifestsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_missing_root_is_a_real_reported_issue_not_a_crash(self):
        result = scan_project_manifests(self.root / "does-not-exist")
        self.assertEqual(result.projects, ())
        self.assertEqual(len(result.issues), 1)
        self.assertIn("not a real directory", result.issues[0].reason)

    def test_an_empty_root_yields_nothing_and_no_issues(self):
        result = scan_project_manifests(self.root)
        self.assertEqual(result.projects, ())
        self.assertEqual(result.issues, ())

    def test_a_subdirectory_with_no_manifest_is_silently_not_a_project(self):
        (self.root / "not-a-hydra-project").mkdir()
        result = scan_project_manifests(self.root)
        self.assertEqual(result.projects, ())
        self.assertEqual(result.issues, (), "a subdirectory with no manifest at all is not an ISSUE")

    def test_a_real_valid_manifest_is_read_correctly(self):
        _write_manifest(self.root / "HYDRA-UMC-EXAMPLE", name="HYDRA-UMC-EXAMPLE", version="1.2.3", maturity="established")
        result = scan_project_manifests(self.root)
        self.assertEqual(len(result.projects), 1)
        self.assertEqual(result.projects[0].name, "HYDRA-UMC-EXAMPLE")
        self.assertEqual(result.projects[0].version, "1.2.3")
        self.assertEqual(result.projects[0].maturity, "established")

    def test_two_real_projects_are_both_found_in_sorted_order(self):
        _write_manifest(self.root / "b-project", name="B", version="0.0.1", maturity="scaffolding")
        _write_manifest(self.root / "a-project", name="A", version="0.0.1", maturity="scaffolding")
        result = scan_project_manifests(self.root)
        self.assertEqual([p.name for p in result.projects], ["A", "B"])

    def test_malformed_json_is_a_real_reported_issue_not_silently_skipped(self):
        project_dir = self.root / "broken"
        project_dir.mkdir()
        (project_dir / "hydra-umc.project.json").write_text("{not json", encoding="utf-8")
        result = scan_project_manifests(self.root)
        self.assertEqual(result.projects, ())
        self.assertEqual(len(result.issues), 1)
        self.assertIn("not valid JSON", result.issues[0].reason)

    def test_a_manifest_missing_a_required_field_is_a_real_reported_issue(self):
        _write_manifest(self.root / "incomplete", name="Incomplete")  # no version/maturity
        result = scan_project_manifests(self.root)
        self.assertEqual(result.projects, ())
        self.assertEqual(len(result.issues), 1)
        self.assertIn("missing/empty required field(s)", result.issues[0].reason)
        self.assertIn("version", result.issues[0].reason)

    def test_a_manifest_that_is_a_json_array_not_object_is_a_real_reported_issue(self):
        project_dir = self.root / "wrong-shape"
        project_dir.mkdir()
        (project_dir / "hydra-umc.project.json").write_text("[1, 2, 3]", encoding="utf-8")
        result = scan_project_manifests(self.root)
        self.assertEqual(result.projects, ())
        self.assertIn("not a JSON object", result.issues[0].reason)


class CheckSystemdUnitHealthTests(unittest.TestCase):
    def test_honest_degradation_when_systemctl_is_not_on_this_host(self):
        # This development machine (Windows) genuinely has no systemctl -
        # the one real, verifiable thing about this function here: it
        # must raise the typed error, never guess a status.
        if shutil.which("systemctl") is not None:
            self.skipTest("this host has a real systemctl - covered by a different real environment")
        with self.assertRaises(SystemdUnavailableError):
            check_systemd_unit_health("some.service")


class _OkHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):  # noqa: A002
        pass


class _ServerErrorHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(503)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        pass


class CheckHttpHealthTests(unittest.TestCase):
    def _serve(self, handler_cls):
        server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(thread.join, 2)
        return server.server_address[1]

    def test_a_real_reachable_2xx_endpoint_is_reported_reachable(self):
        port = self._serve(_OkHandler)
        result = check_http_health(f"http://127.0.0.1:{port}/health")
        self.assertTrue(result.reachable)
        self.assertEqual(result.status_code, 200)

    def test_a_real_5xx_response_is_reported_as_reached_but_not_reachable(self):
        port = self._serve(_ServerErrorHandler)
        result = check_http_health(f"http://127.0.0.1:{port}/health")
        self.assertFalse(result.reachable)
        self.assertEqual(result.status_code, 503)

    def test_a_genuinely_closed_port_is_reported_unreachable_with_no_status_code(self):
        # Reserve a real port, then close it immediately - guarantees
        # nothing is listening, a real connection-refused condition.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        result = check_http_health(f"http://127.0.0.1:{port}/health", timeout_s=1.0)
        self.assertFalse(result.reachable)
        self.assertIsNone(result.status_code)
        self.assertIn("unreachable", result.detail)

    # REV-015 regression: a real audit found a non-HTTP URL scheme (a real
    # `data:` URI, opened successfully by urllib) making `getcode()` return
    # None, and `200 <= None < 300` raising a real, unhandled TypeError -
    # aborting the whole edge collect run instead of reporting one honest
    # HttpHealthResult.
    def test_a_non_http_scheme_is_refused_before_ever_calling_urlopen(self):
        result = check_http_health("data:text/plain,audit")
        self.assertFalse(result.reachable)
        self.assertIsNone(result.status_code)
        self.assertIn("unsupported URL scheme", result.detail)

    def test_a_file_scheme_is_also_refused(self):
        result = check_http_health("file:///etc/passwd")
        self.assertFalse(result.reachable)
        self.assertIsNone(result.status_code)
        self.assertIn("unsupported URL scheme", result.detail)


if __name__ == "__main__":
    unittest.main()
