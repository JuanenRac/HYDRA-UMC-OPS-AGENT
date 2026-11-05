# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_scenario_ingest.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
#
# The sending end of POST /api/ingest/scenario-outcome. The stand-in server of the shared SDK (conformance/fake-server) answers it when the SDK
# checkout is at hand (HYDRA_UMC_SDK_DIR, or a HYDRA-UMC-SDK folder next to this repository); a small server of this file always answers too.
# =============================================================================
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from hydra_umc_ops_agent.cli_extra import scenario_outcome_sink
from hydra_umc_ops_agent.config import AgentConfig, ConfigError, parse_config
from hydra_umc_ops_agent.incident import IncidentBatch
from hydra_umc_ops_agent.inventory import ManifestScanIssue
from hydra_umc_ops_agent.scenario_ingest import IngestSettings, outcome_problem, post_scenario_outcome
from hydra_umc_ops_agent.verification import verify_incident_resolved

from test_verification import _SDK_INSTALLED, _git, _init_and_commit_manifest


def _fake_server_module():
    candidates = []
    if os.environ.get("HYDRA_UMC_SDK_DIR"):
        candidates.append(Path(os.environ["HYDRA_UMC_SDK_DIR"]))
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent.parent / "HYDRA-UMC-SDK")
        candidates.append(parent / "HYDRA-UMC-SDK")
    for sdk in candidates:
        folder = sdk / "conformance" / "fake-server"
        if (folder / "hydra_fake_server.py").is_file():
            sys.path.insert(0, str(folder))
            try:
                import hydra_fake_server  # type: ignore[import-not-found]

                return hydra_fake_server
            except Exception:  # noqa: BLE001
                return None
    return None


FAKE = _fake_server_module()

OUTCOME = {
    "schema_version": "1.0", "scenario_id": "inc-1", "run_id": "inc-1:before", "base_fingerprint": "abc", "phase": "before",
    "repro_case": "comp", "observed": {"outcome": "reproduced"}, "timestamp_utc": "2026-01-01T00:00:00+00:00",
}


class OutcomeShapeTests(unittest.TestCase):
    def test_only_a_scenario_outcome_1_0_is_sent(self):
        self.assertIsNone(outcome_problem(OUTCOME))
        self.assertIn("lacks", outcome_problem({"schema_version": "1.0"}))
        self.assertIn("phase", outcome_problem({**OUTCOME, "phase": "during"}))
        self.assertIn("observed.outcome", outcome_problem({**OUTCOME, "observed": {"outcome": "maybe"}}))
        self.assertIn("not an object", outcome_problem([]))

    def test_nothing_is_sent_for_a_bad_outcome_or_an_address_that_may_not_carry_a_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "t"
            token.write_text("secret-token\n", encoding="utf-8")
            result = post_scenario_outcome({"x": 1}, IngestSettings("http://127.0.0.1:1", token_file=str(token)))
            self.assertFalse(result.ok)
            self.assertIsNone(result.status)
            plain = post_scenario_outcome(OUTCOME, IngestSettings("http://server.example:3000", token_file=str(token)))
            self.assertIn("HTTPS", plain.detail)
            userinfo = post_scenario_outcome(OUTCOME, IngestSettings("https://u:p@server.example", token_file=str(token)))
            self.assertIn("must not carry", userinfo.detail)
            self.assertNotIn("secret-token", json.dumps(plain.to_dict()))


class _Answer(http.server.BaseHTTPRequestHandler):
    status = 201
    seen: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        type(self).seen.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(length) or b"{}")))
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        if type(self).status == 302:
            self.send_header("Location", "http://127.0.0.1:9/elsewhere")
        self.end_headers()
        self.wfile.write(b'{"seq": 7}')

    def log_message(self, format, *args):  # noqa: A002
        pass


class LocalServerTests(unittest.TestCase):
    def setUp(self):
        _Answer.seen = []
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), _Answer)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.token = Path(self.tmp.name) / "token"
        self.token.write_text("tok-123\n", encoding="utf-8")
        self.settings = IngestSettings(f"http://127.0.0.1:{self.httpd.server_address[1]}", token_file=str(self.token))

    def test_it_sends_the_outcome_with_the_token_and_reads_the_sequence(self):
        _Answer.status = 201
        result = post_scenario_outcome(OUTCOME, self.settings)
        self.assertTrue(result.ok)
        self.assertEqual(result.seq, 7)
        path, authorization, body = _Answer.seen[0]
        self.assertEqual((path, authorization, body["run_id"]), ("/api/ingest/scenario-outcome", "Bearer tok-123", "inc-1:before"))

    def test_each_refusal_is_named_and_never_raised(self):
        for status, words in ((404, "feed off"), (401, "credential"), (403, "operator"), (400, "does not take"), (503, "sign")):
            _Answer.status = status
            result = post_scenario_outcome(OUTCOME, self.settings)
            self.assertFalse(result.ok)
            self.assertEqual(result.status, status)
            self.assertIn(words, result.detail)

    def test_a_redirect_is_not_followed(self):
        _Answer.status = 302
        result = post_scenario_outcome(OUTCOME, self.settings)
        self.assertFalse(result.ok)
        self.assertEqual(len(_Answer.seen), 1)

    def test_a_server_that_is_down_is_a_result(self):
        self.httpd.shutdown()
        result = post_scenario_outcome(OUTCOME, self.settings)
        self.assertFalse(result.ok)
        self.assertIsNone(result.status)


@unittest.skipUnless(FAKE is not None, "the SDK checkout with the stand-in server is not at hand")
class FakeServerTests(unittest.TestCase):
    def setUp(self):
        self.state = FAKE.FakeHydra(robots=1)
        self.httpd, _ = FAKE.start(self.state)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.password = Path(self.tmp.name) / "password"
        self.password.write_text("admin\n", encoding="utf-8")

    def test_it_logs_in_with_the_account_and_the_server_keeps_the_outcome(self):
        settings = IngestSettings(self.url, username="admin", password_file=str(self.password))
        result = post_scenario_outcome(OUTCOME, settings)
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(self.state.scenario_outcomes[0]["scenario_id"], "inc-1")

    def test_a_wrong_password_and_a_refused_token_are_told(self):
        self.password.write_text("wrong\n", encoding="utf-8")
        result = post_scenario_outcome(OUTCOME, IngestSettings(self.url, username="admin", password_file=str(self.password)))
        self.assertFalse(result.ok)
        self.assertIn("login", result.detail)
        token = Path(self.tmp.name) / "token"
        token.write_text("not-a-session\n", encoding="utf-8")
        refused = post_scenario_outcome(OUTCOME, IngestSettings(self.url, token_file=str(token)))
        self.assertEqual(refused.status, 401)

    @unittest.skipUnless(_SDK_INSTALLED and shutil.which("git"), "needs the hydra-umc-sdk extra and git")
    def test_control_verify_hands_both_runs_to_the_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = _init_and_commit_manifest(root)
            incident = IncidentBatch().add_manifest_issue("cm5-1", ManifestScanIssue(path=str(manifest), reason="missing/empty required field(s): name, version, maturity"))
            manifest.write_text(json.dumps({"name": "P", "version": "1.0.0", "maturity": "functional"}), encoding="utf-8")
            _git(["add", "hydra-umc.project.json"], root)
            _git(["commit", "-m", "fix", "--no-verify"], root)
            config = parse_config({"scenario_ingest": {"enabled": True, "server_url": self.url, "username": "admin", "password_file": str(self.password)}})
            sink, sent = scenario_outcome_sink(config)
            result = verify_incident_resolved(incident, outcome_sink=sink)
        self.assertTrue(result.resolved)
        self.assertEqual([o["phase"] for o in self.state.scenario_outcomes], ["before", "after"])
        self.assertEqual([r["ok"] for r in sent], [True, True])


class ConfigTests(unittest.TestCase):
    def test_it_is_off_by_default_and_needs_an_address_and_a_credential_when_on(self):
        self.assertFalse(AgentConfig().scenario_ingest.enabled)
        self.assertEqual(scenario_outcome_sink(AgentConfig()), (None, []))
        with self.assertRaises(ConfigError):
            parse_config({"scenario_ingest": {"enabled": True}})
        with self.assertRaises(ConfigError):
            parse_config({"scenario_ingest": {"enabled": True, "server_url": "https://s.example"}})
        ok = parse_config({"scenario_ingest": {"enabled": True, "server_url": "https://s.example", "token_file": "/run/secrets/t"}})
        self.assertTrue(ok.scenario_ingest.enabled)
        with self.assertRaises(ConfigError):
            parse_config({"scenario_ingest": {"timeout_seconds": 0}})


if __name__ == "__main__":
    unittest.main()
