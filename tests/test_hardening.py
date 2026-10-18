# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_hardening.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Behaviour at the edges: an endpoint that is not HTTP, a manifest that is not
UTF-8, a credentialed health URL across runs, a half-written store, a diff that
renames a file or targets a CRLF one, a build that forks and never ends. Real
sockets, real files and a real throwaway git repository - nothing is mocked
except the one rename that has to fail."""
import base64
import contextlib
import dataclasses
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from _approvals import APPROVERS, SIGNING_KEY
from hydra_umc_ops_agent import canary_deploy, cli
from hydra_umc_ops_agent._atomic import atomic_write_text
from hydra_umc_ops_agent.canary_deploy import CanaryDeployError, deploy_canary
from hydra_umc_ops_agent.change_proposal import (
    ApprovalContentMismatchError,
    ProposalLoadError,
    approve_change,
    load_proposal,
    propose_change,
    save_proposal,
)
from hydra_umc_ops_agent.edge_agent import collect_snapshot
from hydra_umc_ops_agent.incident import MaintenanceIncident
from hydra_umc_ops_agent.incident_store import (
    MAX_RESOLVED_INCIDENTS,
    TrackedIncident,
    load_incident_store,
    reconcile_incidents,
    save_incident_store,
)
from hydra_umc_ops_agent.inventory import check_http_health, check_project_manifest, scan_project_manifests


class _Server:
    def __init__(self, handler):
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self.server.server_address[1]

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _closed_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class HttpHealthEdgeTests(unittest.TestCase):
    def test_an_endpoint_that_does_not_speak_http_is_unreachable_not_a_crash(self):
        class NotHttp(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.wfile.write(b"this is not http\r\n\r\n")

            def log_message(self, *args):
                pass

        with _Server(NotHttp) as port:
            result = check_http_health(f"http://127.0.0.1:{port}/")
        self.assertFalse(result.reachable)
        self.assertIsNone(result.status_code)

    def test_a_redirect_to_a_non_http_scheme_is_not_followed(self):
        class ToFtp(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(302)
                self.send_header("Location", "ftp://127.0.0.1:1/elsewhere")
                self.end_headers()

            def log_message(self, *args):
                pass

        with _Server(ToFtp) as port:
            result = check_http_health(f"http://127.0.0.1:{port}/")
        self.assertFalse(result.reachable)
        self.assertEqual(result.status_code, 302)

    def test_a_redirect_between_http_urls_is_still_followed(self):
        class Final(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        with _Server(Final) as final_port:
            class Moved(BaseHTTPRequestHandler):
                def do_GET(self):  # noqa: N802
                    self.send_response(301)
                    self.send_header("Location", f"http://127.0.0.1:{final_port}/health/")
                    self.end_headers()

                def log_message(self, *args):
                    pass

            with _Server(Moved) as port:
                result = check_http_health(f"http://127.0.0.1:{port}/health")
        self.assertTrue(result.reachable)
        self.assertEqual(result.status_code, 200)


class HealthUrlCredentialsTests(unittest.TestCase):
    def test_credentials_in_the_url_are_sent_as_basic_auth_and_the_url_still_resolves(self):
        seen = []

        class NeedsAuth(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                seen.append(self.headers.get("Authorization"))
                expected = "Basic " + base64.b64encode(b"op:p@ss word").decode("ascii")
                self.send_response(200 if self.headers.get("Authorization") == expected else 401)
                self.end_headers()

            def log_message(self, *args):
                pass

        with _Server(NeedsAuth) as port:
            good = check_http_health(f"http://op:p%40ss%20word@127.0.0.1:{port}/health")
            bad = check_http_health(f"http://op:wrong@127.0.0.1:{port}/health")
        self.assertTrue(good.reachable, good.detail)
        self.assertEqual(good.status_code, 200)
        self.assertEqual(bad.status_code, 401)

    def test_the_credentials_are_not_forwarded_when_the_endpoint_redirects(self):
        leaked = []

        class Other(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                leaked.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        with _Server(Other) as other_port:
            class Redirects(BaseHTTPRequestHandler):
                def do_GET(self):  # noqa: N802
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{other_port}/")
                    self.end_headers()

                def log_message(self, *args):
                    pass

            with _Server(Redirects) as port:
                result = check_http_health(f"http://op:secret@127.0.0.1:{port}/health")
        self.assertTrue(result.reachable)
        self.assertEqual(leaked, [None], "the redirect target must not receive the credentials")


class ManifestScanEdgeTests(unittest.TestCase):
    def test_a_manifest_that_is_not_utf8_is_one_issue_and_the_scan_goes_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a-broken").mkdir()
            (root / "a-broken" / "hydra-umc.project.json").write_bytes(b'{"name": "\xff\xfe"}')
            (root / "b-fine").mkdir()
            (root / "b-fine" / "hydra-umc.project.json").write_text(
                json.dumps({"name": "FINE", "version": "1.0.0", "maturity": "functional"}), encoding="utf-8",
            )
            result = scan_project_manifests(root)
        self.assertEqual([p.name for p in result.projects], ["FINE"])
        self.assertEqual(len(result.issues), 1)
        self.assertIn("UTF-8", result.issues[0].reason)

    def test_a_manifest_over_the_size_cap_is_an_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hydra-umc.project.json"
            path.write_bytes(b'{"name": "' + b"a" * 1_100_000 + b'"}')
            checked = check_project_manifest(path)
        self.assertIn("larger than", checked.reason)


class CredentialedUrlTrackingTests(unittest.TestCase):
    def test_a_health_url_with_a_password_is_one_incident_across_runs_and_closes_when_healthy(self):
        port = _closed_port()
        url = f"http://operator:s3cret-pass@127.0.0.1:{port}/health"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / "incidents.json"
            first = collect_snapshot("node-1", root, http_health_urls=[url], incident_store_path=store)
            second = collect_snapshot("node-1", root, http_health_urls=[url], incident_store_path=store)
            tracked = load_incident_store(store)

            self.assertEqual(len(tracked), 1, "the same endpoint must not open a new incident on every pass")
            self.assertEqual(tracked[0].occurrence_count, 2)
            self.assertEqual(first.incidents[0].incident_id, second.incidents[0].incident_id)
            self.assertNotIn("s3cret-pass", store.read_text(encoding="utf-8"))

            class Healthy(BaseHTTPRequestHandler):
                def do_GET(self):  # noqa: N802
                    expected = "Basic " + base64.b64encode(b"operator:s3cret-pass").decode("ascii")
                    self.send_response(200 if self.headers.get("Authorization") == expected else 401)
                    self.end_headers()

                def log_message(self, *args):
                    pass

            # The endpoint comes back (on the same port) and only answers 200 to the right credentials.
            server = HTTPServer(("127.0.0.1", port), Healthy)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                third = collect_snapshot("node-1", root, http_health_urls=[url], incident_store_path=store)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
            tracked = load_incident_store(store)
        self.assertEqual(third.incidents, ())
        self.assertIsNotNone(tracked[0].resolved_at)


class StoreDurabilityTests(unittest.TestCase):
    def _incident(self, n: int) -> MaintenanceIncident:
        return MaintenanceIncident(
            incident_id=f"id-{n}", source_node="node-1", detected_at="2026-01-01T00:00:00+00:00", severity="warning",
            component=f"unit-{n}", symptom="s", evidence_refs=(), redaction_level="sanitized",
            requested_by="edge-agent:auto", correlation_id="c",
        )

    def test_a_failed_save_leaves_the_previous_store_intact_and_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "incidents.json"
            save_incident_store(reconcile_incidents([], [self._incident(1)], {("node-1", "unit-1")}), path)
            before = path.read_text(encoding="utf-8")
            with mock.patch("hydra_umc_ops_agent._atomic.os.replace", side_effect=OSError("disk gone")):
                with self.assertRaises(OSError):
                    save_incident_store([], path)
            self.assertEqual(path.read_text(encoding="utf-8"), before)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["incidents.json"])

    def test_resolved_history_is_capped_to_the_newest_entries(self):
        total = MAX_RESOLVED_INCIDENTS + 25
        store = [
            TrackedIncident(self._incident(n), "t", "t", 1, resolved_at=f"2026-01-01T00:{n // 60:02d}:{n % 60:02d}+00:00")
            for n in range(total)
        ]
        result = reconcile_incidents(store, [], set())
        self.assertEqual(len(result), MAX_RESOLVED_INCIDENTS)
        kept = {tracked.incident.incident_id for tracked in result}
        self.assertIn(f"id-{total - 1}", kept)
        self.assertNotIn("id-0", kept)

    def test_open_incidents_are_never_dropped_by_the_cap(self):
        resolved = [
            TrackedIncident(self._incident(n), "t", "t", 1, resolved_at=f"2026-01-01T00:{n // 60:02d}:{n % 60:02d}+00:00")
            for n in range(MAX_RESOLVED_INCIDENTS + 5)
        ]
        open_one = TrackedIncident(self._incident(9999), "t", "t", 1)
        result = reconcile_incidents(resolved + [open_one], [], set())
        self.assertIn("id-9999", {tracked.incident.incident_id for tracked in result})

    def test_atomic_write_creates_missing_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a" / "b" / "out.json"
            atomic_write_text(target, "é\n")
            self.assertEqual(target.read_bytes(), "é\n".encode("utf-8"))


class ProposalEdgeTests(unittest.TestCase):
    def _approved(self):
        proposal = propose_change(
            incident_id="i", correlation_id="c", project_name="P", description="d",
            diff="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n", rationale="r",
        )
        return approve_change(proposal, approved_by="Someone", signing_key=SIGNING_KEY)

    def test_a_failed_save_keeps_the_reviewed_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposal.json"
            approved = self._approved()
            save_proposal(approved, path)
            before = path.read_bytes()
            with mock.patch("hydra_umc_ops_agent._atomic.os.replace", side_effect=OSError("disk gone")):
                with self.assertRaises(OSError):
                    save_proposal(approved, path)
            self.assertEqual(path.read_bytes(), before)

    def test_a_proposal_file_that_is_not_utf8_is_a_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposal.json"
            path.write_bytes(b'{"proposalId": "\xff"}')
            with self.assertRaises(ProposalLoadError):
                load_proposal(path)

    def test_a_digest_that_is_not_a_string_is_a_mismatch_not_a_typeerror(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposal.json"
            save_proposal(self._approved(), path)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["approvedContentDigest"] = 12345
            path.write_text(json.dumps(data), encoding="utf-8")
            # A saved file with a digest of the wrong type is refused when it is
            # loaded; a proposal object built in memory with one is a mismatch.
            with self.assertRaises(ProposalLoadError):
                load_proposal(path)
            data["approvedContentDigest"] = "0" * 64
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = load_proposal(path)
            with self.assertRaises(ApprovalContentMismatchError):
                dataclasses.replace(loaded, approved_content_digest=12345).verify_approval_content()


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _make_repo(root: Path, files: dict[str, bytes]) -> Path:
    live = root / "live-project"
    live.mkdir()
    for name, content in files.items():
        (live / name).write_bytes(content)
    _git(["init", "-q"], live)
    for key, value in (("user.email", "t@example.com"), ("user.name", "T"), ("core.autocrlf", "false")):
        _git(["config", key, value], live)
    _git(["add", "."], live)
    _git(["commit", "-q", "-m", "initial"], live)
    return live


_PASS = [sys.executable, "-c", "pass"]


def _approved(diff: str, project: str = "p"):
    proposal = propose_change(
        incident_id="i", correlation_id="c", project_name=project, description="d", diff=diff, rationale="r",
    )
    return approve_change(proposal, approved_by="Someone", signing_key=SIGNING_KEY)


def _status(live: Path) -> str:
    return subprocess.run(["git", "status", "--porcelain"], cwd=str(live), capture_output=True, text=True, check=True).stdout


class DiffShapeTests(unittest.TestCase):
    def test_a_diff_that_renames_a_file_promotes_and_leaves_a_clean_tree(self):
        diff = (
            "diff --git a/old.txt b/new.txt\nsimilarity index 66%\nrename from old.txt\nrename to new.txt\n"
            "index 4cb29ea..f384549 100644\n--- a/old.txt\n+++ b/new.txt\n@@ -1,3 +1,4 @@\n one\n two\n three\n+four\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            live = _make_repo(Path(tmp), {"old.txt": b"one\ntwo\nthree\n", "hydra-umc.project.json": b'{"name": "p"}'})
            result = deploy_canary(_approved(diff), live_root=live, approvers=APPROVERS, build_test_command=_PASS)
            self.assertTrue(result.promoted, result.detail)
            self.assertFalse((live / "old.txt").exists())
            self.assertEqual((live / "new.txt").read_bytes().replace(b"\r\n", b"\n"), b"one\ntwo\nthree\nfour\n")
            self.assertEqual(_status(live), "", "the removal of the old path must be part of the commit")

    def test_a_file_name_with_non_ascii_characters_is_committed(self):
        name = "café.txt"
        diff = f"--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n-before\n+after\n"
        with tempfile.TemporaryDirectory() as tmp:
            live = _make_repo(Path(tmp), {name: b"before\n", "hydra-umc.project.json": b'{"name": "p"}'})
            result = deploy_canary(_approved(diff), live_root=live, approvers=APPROVERS, build_test_command=_PASS)
            self.assertTrue(result.promoted, result.detail)
            self.assertEqual((live / name).read_bytes().replace(b"\r\n", b"\n"), b"after\n")
            self.assertEqual(_status(live), "")

    def test_a_diff_against_a_crlf_file_reaches_git_apply_unchanged(self):
        diff = "--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,2 @@\n alpha\r\n-beta\r\n+gamma\r\n"
        with tempfile.TemporaryDirectory() as tmp:
            live = _make_repo(Path(tmp), {"f.txt": b"alpha\r\nbeta\r\n", "hydra-umc.project.json": b'{"name": "p"}'})
            result = deploy_canary(_approved(diff), live_root=live, approvers=APPROVERS, build_test_command=_PASS)
            self.assertTrue(result.promoted, result.detail)
            self.assertEqual((live / "f.txt").read_bytes(), b"alpha\r\ngamma\r\n")

    def test_the_cli_keeps_a_crlf_diff_byte_for_byte_when_it_makes_a_proposal(self):
        diff = "--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,2 @@\n alpha\r\n-beta\r\n+gamma\r\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "snapshot.json"
            snapshot.write_text(json.dumps({"incidents": [{
                "incidentId": "inc-1", "sourceNode": "n", "detectedAt": "t", "severity": "warning", "component": "c",
                "symptom": "s", "evidenceRefs": [], "redactionLevel": "sanitized", "requestedBy": "x", "correlationId": "corr",
            }]}), encoding="utf-8")
            (root / "change.diff").write_bytes(diff.encode("utf-8"))
            out = root / "proposal.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main([
                    "control", "propose", str(snapshot), "--incident-id", "inc-1", "--project-name", "p",
                    "--description", "d", "--diff-file", str(root / "change.diff"), "--rationale", "r", "--out", str(out),
                ])
            self.assertEqual(code, 0)
            self.assertEqual(load_proposal(out).diff, diff)


class PromotionAndBuildTests(unittest.TestCase):
    def test_a_failed_promotion_keeps_the_verified_candidate_it_promises(self):
        diff = "--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-a\n+b\n"
        original_rename = Path.rename

        def flaky(self, target):
            if self.name.startswith(".ops-agent-canary-"):
                raise OSError("synthetic failure injected by test")
            return original_rename(self, target)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = _make_repo(root, {"f.txt": b"a\n", "hydra-umc.project.json": b'{"name": "p"}'})
            with mock.patch.object(Path, "rename", flaky):
                with self.assertRaises(CanaryDeployError) as ctx:
                    deploy_canary(_approved(diff), live_root=live, approvers=APPROVERS, build_test_command=_PASS)
            self.assertIn("still available at", str(ctx.exception))
            candidates = list(root.glob(".ops-agent-canary-*"))
            self.assertEqual(len(candidates), 1, "the candidate the message points to must still exist")
            self.assertEqual((candidates[0] / "f.txt").read_bytes().replace(b"\r\n", b"\n"), b"b\n")

    def test_an_empty_build_command_is_refused_before_anything_is_staged(self):
        diff = "--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-a\n+b\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = _make_repo(root, {"f.txt": b"a\n", "hydra-umc.project.json": b'{"name": "p"}'})
            with self.assertRaises(CanaryDeployError):
                deploy_canary(_approved(diff), live_root=live, approvers=APPROVERS, build_test_command=[])
            self.assertEqual(list(root.glob(".ops-agent-canary-*")), [])

    def test_an_ignored_symlink_is_carried_over_as_a_symlink(self):
        diff = "--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-a\n+b\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = root / "external-storage"
            storage.mkdir()
            (storage / "big.bin").write_bytes(b"x" * 1000)
            live = _make_repo(root, {"f.txt": b"a\n", ".gitignore": b"data\n", "hydra-umc.project.json": b'{"name": "p"}'})
            try:
                os.symlink(storage, live / "data", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("this platform does not allow creating symlinks here")
            result = deploy_canary(_approved(diff), live_root=live, approvers=APPROVERS, build_test_command=_PASS)
            self.assertTrue(result.promoted, result.detail)
            self.assertTrue((live / "data").is_symlink(), "a link to external storage must not become a copy of it")
            self.assertTrue(os.path.samefile(live / "data", storage))


class RunHelperTests(unittest.TestCase):
    def test_a_timeout_kills_the_whole_tree_and_returns_promptly(self):
        script = (
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "time.sleep(60)\n"
        )
        started = time.monotonic()
        code, output = canary_deploy._run([sys.executable, "-c", script], Path.cwd(), timeout_s=2.0)
        self.assertEqual(code, 124)
        self.assertIn("TIMEOUT", output)
        self.assertLess(time.monotonic() - started, 30)

    def test_output_is_bounded_to_its_tail(self):
        script = "import sys\nsys.stdout.write('A' * 3_000_000 + 'THE-END')\n"
        code, output = canary_deploy._run([sys.executable, "-c", script], Path.cwd(), timeout_s=60.0)
        self.assertEqual(code, 0)
        self.assertLess(len(output), canary_deploy._OUTPUT_TAIL_BYTES + 200)
        self.assertTrue(output.endswith("THE-END"))
        self.assertIn("earlier output dropped", output)

    def test_output_that_is_not_utf8_does_not_crash(self):
        script = "import sys\nsys.stdout.buffer.write(bytes([0xff, 0xfe]) + b' tail')\n"
        code, output = canary_deploy._run([sys.executable, "-c", script], Path.cwd(), timeout_s=30.0)
        self.assertEqual(code, 0)
        self.assertIn("tail", output)

    def test_a_missing_executable_and_an_empty_command_are_results_not_exceptions(self):
        self.assertEqual(canary_deploy._run(["definitely-not-a-real-program-xyz"], Path.cwd(), 5.0)[0], 127)
        self.assertEqual(canary_deploy._run([], Path.cwd(), 5.0)[0], 127)

    def test_a_non_utf8_file_name_in_git_status_does_not_crash_the_dirty_check(self):
        if os.name == "nt":
            self.skipTest("Windows file names are Unicode, there is no such thing as a non-UTF-8 one")
        with tempfile.TemporaryDirectory() as tmp:
            live = _make_repo(Path(tmp), {"f.txt": b"a\n"})
            with open(os.path.join(os.fsencode(str(live)), b"odd-\xff-name.txt"), "wb") as handle:
                handle.write(b"x")
            self.assertEqual(canary_deploy._tracked_dirty_paths(live), [])


class CliRobustnessTests(unittest.TestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_a_corrupt_incident_store_is_an_error_line_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "store.json").write_text("{ half written", encoding="utf-8")
            code, _, err = self._run(["edge", "collect", "--node-name", "n", "--projects-root", str(root), "--incident-store", str(root / "store.json")])
        self.assertEqual(code, 1)
        self.assertIn("ERROR", err)

    def test_a_snapshot_with_a_malformed_incident_record_is_not_found_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot.json"
            snapshot.write_text(json.dumps({"incidents": ["not an object", {"incidentId": "inc-1"}]}), encoding="utf-8")
            code, _, err = self._run(["control", "verify", str(snapshot), "--incident-id", "inc-1", "--node-name", "n"])
        self.assertEqual(code, 1)
        self.assertIn("no incident with id", err)

    def test_a_snapshot_whose_incidents_is_not_a_list_is_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot.json"
            snapshot.write_text(json.dumps({"incidents": {"a": 1}}), encoding="utf-8")
            code, _, err = self._run(["control", "verify", str(snapshot), "--incident-id", "inc-1", "--node-name", "n"])
        self.assertEqual(code, 1)
        self.assertIn("no incident with id", err)

    def test_a_snapshot_that_is_not_utf8_is_an_error_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot.json"
            snapshot.write_bytes(b'{"sourceNode": "\xff"}')
            code, _, err = self._run(["control", "show", str(snapshot)])
        self.assertEqual(code, 1)
        self.assertIn("ERROR", err)

    def test_an_unbalanced_quote_in_the_build_command_is_an_error_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            proposal = Path(tmp) / "proposal.json"
            save_proposal(_approved("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"), proposal)
            code, _, err = self._run(["control", "deploy-canary", str(proposal), "--live-root", tmp, "--build-test-command", 'bash "unclosed'])
        self.assertEqual(code, 1)
        self.assertIn("not a valid command line", err)

    def test_an_unwritable_output_path_is_an_error_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "a-file"
            blocker.write_text("x", encoding="utf-8")
            code, _, err = self._run(["edge", "collect", "--node-name", "n", "--projects-root", tmp, "--out", str(blocker / "child.json")])
        self.assertEqual(code, 1)
        self.assertIn("ERROR: could not write", err)


if __name__ == "__main__":
    unittest.main()
