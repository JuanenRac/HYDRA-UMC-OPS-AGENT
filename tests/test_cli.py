# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_cli.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real end-to-end CLI tests - `edge collect` writing a real file, then
`control show` reading that exact file back, exactly the two-role real flow
this delivery ships. `control diagnose` is tested against a real snapshot
too, with `diagnosis.diagnose_incident` monkeypatched to a fake so no real
network call or `anthropic` package is ever needed here."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hydra_umc_ops_agent import cli
from hydra_umc_ops_agent.cli import main
from hydra_umc_ops_agent.diagnosis import DiagnosisResult, MissingApiKeyError


def _write_manifest(path: Path, **fields) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "hydra-umc.project.json").write_text(json.dumps(fields), encoding="utf-8")


class CliEndToEndTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_edge_collect_writes_a_real_readable_snapshot_file(self):
        _write_manifest(self.root / "proj", name="PROJ", version="1.0.0", maturity="established")
        out_file = self.root / "snapshot.json"
        exit_code = main([
            "edge", "collect",
            "--node-name", "cm5-test",
            "--projects-root", str(self.root),
            "--out", str(out_file),
        ])
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_file.is_file())
        data = json.loads(out_file.read_text(encoding="utf-8"))
        self.assertEqual(data["sourceNode"], "cm5-test")
        self.assertEqual(len(data["projects"]), 1)

    def test_edge_collect_without_out_prints_the_snapshot_to_stdout(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(["edge", "collect", "--node-name", "cm5-test", "--projects-root", str(self.root)])
        self.assertEqual(exit_code, 0)
        printed = json.loads(stdout.getvalue())
        self.assertEqual(printed["sourceNode"], "cm5-test")

    def test_control_show_renders_a_real_collected_snapshot(self):
        _write_manifest(self.root / "proj", name="PROJ", version="1.0.0", maturity="established")
        out_file = self.root / "snapshot.json"
        main(["edge", "collect", "--node-name", "cm5-test", "--projects-root", str(self.root), "--out", str(out_file)])

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(["control", "show", str(out_file)])
        self.assertEqual(exit_code, 0)
        self.assertIn("PROJ v1.0.0", stdout.getvalue())

    def test_control_show_on_a_missing_file_fails_with_a_real_nonzero_exit(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = main(["control", "show", str(self.root / "does-not-exist.json")])
        self.assertEqual(exit_code, 1)
        self.assertIn("ERROR", stderr.getvalue())

    def test_control_diagnose_writes_a_real_diagnosis_for_a_real_incident(self):
        # Force one real incident to exist: an unreachable HTTP health URL.
        out_file = self.root / "snapshot.json"
        main([
            "edge", "collect",
            "--node-name", "cm5-test",
            "--projects-root", str(self.root),
            "--http-health-url", "http://127.0.0.1:1/does-not-listen",
            "--out", str(out_file),
        ])
        snapshot = json.loads(out_file.read_text(encoding="utf-8"))
        incident_id = snapshot["incidents"][0]["incidentId"]

        fake_result = DiagnosisResult(
            incident_id=incident_id,
            correlation_id=snapshot["correlationId"],
            provider="anthropic",
            model="claude-sonnet-5",
            generated_at="2026-09-06T12:00:00+00:00",
            explanation="The health endpoint is likely not running yet.",
        )
        diagnosis_out = self.root / "diagnosis.json"
        with mock.patch.object(cli, "diagnose_incident", return_value=fake_result) as fake_diagnose:
            exit_code = main([
                "control", "diagnose", str(out_file),
                "--incident-id", incident_id,
                "--out", str(diagnosis_out),
            ])
        self.assertEqual(exit_code, 0)
        fake_diagnose.assert_called_once()
        written = json.loads(diagnosis_out.read_text(encoding="utf-8"))
        self.assertEqual(written["incidentId"], incident_id)
        self.assertIn("not running yet", written["explanation"])

    def test_control_diagnose_on_an_unknown_incident_id_fails_cleanly(self):
        out_file = self.root / "snapshot.json"
        main(["edge", "collect", "--node-name", "cm5-test", "--projects-root", str(self.root), "--out", str(out_file)])
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = main(["control", "diagnose", str(out_file), "--incident-id", "does-not-exist"])
        self.assertEqual(exit_code, 1)
        self.assertIn("ERROR", stderr.getvalue())

    def test_control_diagnose_reports_a_missing_api_key_cleanly_not_as_a_traceback(self):
        out_file = self.root / "snapshot.json"
        main([
            "edge", "collect", "--node-name", "cm5-test", "--projects-root", str(self.root),
            "--http-health-url", "http://127.0.0.1:1/does-not-listen", "--out", str(out_file),
        ])
        snapshot = json.loads(out_file.read_text(encoding="utf-8"))
        incident_id = snapshot["incidents"][0]["incidentId"]
        stderr = io.StringIO()
        with mock.patch.object(cli, "diagnose_incident", side_effect=MissingApiKeyError("no key")):
            with contextlib.redirect_stderr(stderr):
                exit_code = main(["control", "diagnose", str(out_file), "--incident-id", incident_id])
        self.assertEqual(exit_code, 1)
        self.assertIn("ERROR", stderr.getvalue())

    def test_version_flag_prints_the_real_package_version(self):
        from hydra_umc_ops_agent import __version__
        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stdout(stdout):
                main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn(__version__, stdout.getvalue())


_REAL_DIFF = (
    "--- a/config.json\n"
    "+++ b/config.json\n"
    "@@ -1,3 +1,3 @@\n"
    " {\n"
    '-  "retries": 0\n'
    '+  "retries": 3\n'
    " }\n"
)


class SplitCommandTests(unittest.TestCase):
    def test_a_windows_path_with_backslashes_survives_intact(self):
        # Real bug found live via the deploy-canary CLI test on this
        # development machine: plain shlex.split() treats backslash as
        # an escape character in POSIX mode and silently mangles a
        # Windows path.
        command = r"C:\Users\juane\.venv\Scripts\python.exe check.py"
        self.assertEqual(cli._split_command(command), [r"C:\Users\juane\.venv\Scripts\python.exe", "check.py"])

    def test_a_simple_command_still_splits_on_whitespace(self):
        self.assertEqual(cli._split_command("bash build-test.sh"), ["bash", "build-test.sh"])

    def test_a_quoted_argument_with_a_space_is_still_kept_as_one_token(self):
        self.assertEqual(
            cli._split_command('python3 "tools/build test.py" --flag'),
            ["python3", "tools/build test.py", "--flag"],
        )


class Delivery345CliTests(unittest.TestCase):
    """Real end-to-end CLI round-trips for propose/approve/reject/
    deploy-canary/verify - Deliveries 3-5. deploy-canary is exercised
    against a real throwaway git repo, same as test_canary_deploy.py."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _real_incident_snapshot(self) -> tuple[Path, str]:
        out_file = self.root / "snapshot.json"
        main([
            "edge", "collect", "--node-name", "cm5-test", "--projects-root", str(self.root),
            "--http-health-url", "http://127.0.0.1:1/does-not-listen", "--out", str(out_file),
        ])
        snapshot = json.loads(out_file.read_text(encoding="utf-8"))
        return out_file, snapshot["incidents"][0]["incidentId"]

    def test_propose_approve_reject_round_trip(self):
        snapshot_file, incident_id = self._real_incident_snapshot()
        diff_file = self.root / "fix.diff"
        diff_file.write_text(_REAL_DIFF, encoding="utf-8")
        proposal_file = self.root / "proposal.json"

        exit_code = main([
            "control", "propose", str(snapshot_file), "--incident-id", incident_id,
            "--project-name", "test-project", "--description", "raise retries",
            "--diff-file", str(diff_file), "--rationale", "fixes the flaky check",
            "--out", str(proposal_file),
        ])
        self.assertEqual(exit_code, 0)
        proposal = json.loads(proposal_file.read_text(encoding="utf-8"))
        self.assertEqual(proposal["status"], "pending")

        exit_code = main(["control", "approve", str(proposal_file), "--approved-by", "Juan Enrique"])
        self.assertEqual(exit_code, 0)
        approved = json.loads(proposal_file.read_text(encoding="utf-8"))
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["decidedBy"], "Juan Enrique")

    def test_reject_writes_a_real_rejected_status(self):
        snapshot_file, incident_id = self._real_incident_snapshot()
        diff_file = self.root / "fix.diff"
        diff_file.write_text(_REAL_DIFF, encoding="utf-8")
        proposal_file = self.root / "proposal.json"
        main([
            "control", "propose", str(snapshot_file), "--incident-id", incident_id,
            "--project-name", "test-project", "--description", "x", "--diff-file", str(diff_file),
            "--rationale", "x", "--out", str(proposal_file),
        ])

        exit_code = main(["control", "reject", str(proposal_file), "--rejected-by", "Juan Enrique", "--reason", "too risky"])
        self.assertEqual(exit_code, 0)
        rejected = json.loads(proposal_file.read_text(encoding="utf-8"))
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["decisionReason"], "too risky")

    def test_deploy_canary_end_to_end_against_a_real_git_repo(self):
        import subprocess
        import sys

        live_root = self.root / "live-project"
        live_root.mkdir()
        (live_root / "config.json").write_text('{\n  "retries": 0\n}\n', encoding="utf-8")
        (live_root / "check.py").write_text(
            "import json, sys\n"
            "data = json.loads(open('config.json', encoding='utf-8').read())\n"
            "sys.exit(0 if data.get('retries', 0) >= 3 else 1)\n",
            encoding="utf-8",
        )
        for args in (["git", "init", "-q"], ["git", "config", "user.email", "t@example.com"],
                     ["git", "config", "user.name", "T"], ["git", "add", "."], ["git", "commit", "-q", "-m", "x"]):
            subprocess.run(args, cwd=str(live_root), check=True, capture_output=True, text=True)

        proposal_file = self.root / "proposal.json"
        # This test focuses on deploy-canary itself, so the proposal is
        # built directly (propose_change/approve_change already have
        # their own real CLI round-trip test above).
        from hydra_umc_ops_agent.change_proposal import approve_change, propose_change, save_proposal
        proposal = approve_change(
            propose_change(
                incident_id="inc-x", correlation_id="corr-x", project_name="test-project",
                description="raise retries", diff=_REAL_DIFF, rationale="fixes the flaky check",
            ),
            approved_by="Juan Enrique",
        )
        save_proposal(proposal, proposal_file)

        result_file = self.root / "deploy-result.json"
        exit_code = main([
            "control", "deploy-canary", str(proposal_file),
            "--live-root", str(live_root),
            "--build-test-command", f"{sys.executable} check.py",
            "--out", str(result_file),
        ])
        self.assertEqual(exit_code, 0)
        result = json.loads(result_file.read_text(encoding="utf-8"))
        self.assertTrue(result["promoted"])
        self.assertIn('"retries": 3', (live_root / "config.json").read_text(encoding="utf-8"))

    def test_verify_reports_unresolved_for_a_still_broken_incident(self):
        snapshot_file, incident_id = self._real_incident_snapshot()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = main(["control", "verify", str(snapshot_file), "--incident-id", incident_id])
        # The health URL used by _real_incident_snapshot() never listens, so
        # the real re-check must still fail - exit code 1, not a crash.
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
