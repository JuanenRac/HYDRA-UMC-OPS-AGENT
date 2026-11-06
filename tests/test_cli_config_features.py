# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_cli_config_features.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The commands that depend on the configuration: off without it, and working end to end when it turns them on."""
import contextlib
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from _edge_fixtures import GOOD_DIFF, make_checkout, python_command
from hydra_umc_ops_agent.change_proposal import load_proposal
from hydra_umc_ops_agent.cli import main


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def write_config(directory: Path, **sections) -> str:
    path = directory / "ops-agent.json"
    path.write_text(json.dumps(sections), encoding="utf-8")
    return str(path)


class EverythingIsOffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.config = write_config(self.dir)  # an empty file: every default
        (self.dir / "snapshot.json").write_text(json.dumps({"sourceNode": "n", "incidents": []}), encoding="utf-8")
        (self.dir / "store.json").write_text("[]", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_each_feature_command_names_its_switch(self):
        d = self.dir
        cases = [
            (["edge", "serve", "--node-name", "n", "--snapshot-file", str(d / "snapshot.json")], "transport"),
            (["edge", "healing-ingest", "--incident-store", str(d / "store.json")], "healing.enabled"),
            (["control", "remote", "snapshot", "--url", "http://127.0.0.1:1", "--node", "a", "--local-node", "b"], "transport.enabled"),
            (["control", "metrics", "--incident-store", str(d / "store.json")], "metrics.enabled"),
        ]
        for argv, word in cases:
            code, _, err = run_cli("--config", self.config, *argv)
            self.assertEqual(code, 1, argv)
            self.assertIn(word, err, argv)

    def test_a_missing_explicit_config_or_a_broken_one_is_an_error(self):
        code, _, err = run_cli("--config", str(self.dir / "nope.json"), "control", "metrics", "--incident-store", "s")
        self.assertEqual(code, 1)
        broken = self.dir / "broken.json"
        broken.write_text('{"transport": {"enabled": "yes"}}', encoding="utf-8")
        code, _, err = run_cli("--config", str(broken), "control", "metrics", "--incident-store", "s")
        self.assertEqual(code, 1)
        self.assertIn("true or false", err)

    def test_edge_collect_works_without_any_configuration_as_before(self):
        root = self.dir / "projects"
        root.mkdir()
        code, out, _ = run_cli("--config", self.config, "edge", "collect", "--node-name", "n", "--projects-root", str(root))
        self.assertEqual(code, 0)
        self.assertIn('"sourceNode": "n"', out)


class _FakeLlm(BaseHTTPRequestHandler):
    reply = GOOD_DIFF

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps({"choices": [{"message": {"content": self.reply}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


class ProposeFromDiagnosisCliTests(unittest.TestCase):
    def test_a_local_model_server_produces_a_pending_proposal_that_yes_cannot_approve(self):
        server = HTTPServer(("127.0.0.1", 0), _FakeLlm)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                d = Path(tmp)
                live = make_checkout(d / "projects")
                config = write_config(d, llm_propose={"enabled": True, "model": "m", "endpoint": f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"},
                                      evidence_bundle={"enabled": True, "with_proposal": True})
                policy = d / "policy.json"
                policy.write_text(json.dumps({"projects": {"test-project": {"build_test_commands": [python_command()]}}}), encoding="utf-8")
                incident = {"incidentId": "i1", "sourceNode": "n", "detectedAt": "t", "severity": "warning", "component": "c", "symptom": "s",
                            "evidenceRefs": [], "redactionLevel": "sanitized", "requestedBy": None, "correlationId": "c1"}
                snapshot = d / "snapshot.json"
                snapshot.write_text(json.dumps({"sourceNode": "n", "incidents": [incident]}), encoding="utf-8")
                out = d / "proposal.json"
                code, stdout, err = run_cli("--config", config, "control", "propose-from-diagnosis", str(snapshot), "--incident-id", "i1",
                                            "--project-name", "test-project", "--live-root", str(live), "--file", "config.json",
                                            "--policy", str(policy), "--language", "es", "--out", str(out), "--audit-journal", str(d / "audit.jsonl"))
                self.assertEqual(code, 0, err)
                self.assertIn("no está aplicada", stdout)
                # the incident that opened the proposal also got its sealed evidence bundle, next to the proposal
                from hydra_umc_ops_agent.evidence_bundle import bundle_matches_checksum
                self.assertTrue(bundle_matches_checksum(json.loads((d / "evidence-i1.json").read_text(encoding="utf-8"))))
                proposal = load_proposal(out)
                self.assertEqual((proposal.status, proposal.generated_by), ("pending", "llm:m"))
                self.assertIn("GENERADO POR UN MODELO", proposal.description)
                self.assertIn("propose-generated", (d / "audit.jsonl").read_text(encoding="utf-8"))
                self.assertIn('"retries": 0', (live / "config.json").read_text(encoding="utf-8"))
                from _approvals import write_key_files
                key_path, _ = write_key_files(d)
                code, _, err = run_cli("control", "approve", str(out), "--approved-by", "Test Approver", "--key", key_path, "--any-commit", "--yes")
                self.assertEqual(code, 1)
                self.assertIn("only at a terminal", err)
                self.assertEqual(load_proposal(out).status, "pending")
                # and with the feature off, the same command refuses
                off = write_config(d)
                code, _, err = run_cli("--config", off, "control", "propose-from-diagnosis", str(snapshot), "--incident-id", "i1",
                                       "--project-name", "test-project", "--live-root", str(live), "--file", "config.json", "--policy", str(policy))
                self.assertEqual(code, 1)
                self.assertIn("llm_propose.enabled", err)
        finally:
            server.shutdown()
            server.server_close()


class MetricsCliTests(unittest.TestCase):
    def test_metrics_prints_text_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "store.json").write_text("[]", encoding="utf-8")
            code, out, _ = run_cli("--config", write_config(d, metrics={"enabled": True}), "control", "metrics", "--incident-store", str(d / "store.json"))
            self.assertEqual(code, 0)
            self.assertIn("hydra_ops_agent_up 1", out)


if __name__ == "__main__":
    unittest.main()
