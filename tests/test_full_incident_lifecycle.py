# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_full_incident_lifecycle.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""F08 ("Diagnostico OPS -> incidente saneado -> propuesta ligada a
hash/revision -> pruebas -> aprobacion -> staging UPDATER ->
verificacion -> cierre o rollback") - found while auditing the code, with a
real gap: every stage already had its own real CLI round-trip test
(test_cli.py's own Delivery345CliTests), but no single test threaded ONE
real incident through every stage in order, ending in a real, re-verified
closure. This file is that missing chain, start to finish, against a real
git repo and a real manifest-scan incident - not a synthetic/mocked one -
the only mock anywhere in this file is the LLM call inside
diagnose_incident() itself (test_cli.py's own established precedent: an
LLM's own wording is not deterministic, so it is the one real external
dependency worth mocking; every real project/incident/diff/deploy/
re-verification step below is genuinely exercised).
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from hydra_umc_ops_agent import cli
from hydra_umc_ops_agent.cli import main
from hydra_umc_ops_agent.diagnosis import DiagnosisResult

_MANIFEST_FIX_DIFF = (
    "--- a/hydra-umc.project.json\n"
    "+++ b/hydra-umc.project.json\n"
    "@@ -1,4 +1,5 @@\n"
    " {\n"
    '   "name": "broken-project",\n'
    '+  "version": "0.0.1",\n'
    '   "maturity": "scaffolding"\n'
    " }\n"
)

# The real build-test command this chain's own canary deploy runs inside
# the staging clone - re-validates the exact same real rule
# inventory.py's own scan_project_manifests() enforces (name/version/
# maturity all present and non-empty), proving the diff actually fixes
# what the incident was really about, not just that `git apply` succeeded.
_MANIFEST_VALIDATOR = (
    "import json, sys; "
    "d = json.load(open('hydra-umc.project.json', encoding='utf-8')); "
    "sys.exit(0 if all(isinstance(d.get(k), str) and d.get(k) for k in ('name', 'version', 'maturity')) else 1)"
)


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


class FullIncidentLifecycleTests(unittest.TestCase):
    """One real incident, threaded through every real F08 stage in order,
    with a real re-collection proving closure at the end - not each
    stage's own isolated fixture."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.projects_root = self.root / "projects"
        self.projects_root.mkdir()
        self.live_root = self.projects_root / "broken-project"
        self.live_root.mkdir()
        # The real, incomplete manifest - inventory.py's own
        # scan_project_manifests() will report this as a real
        # ManifestScanIssue (missing "version"), not silently skip it.
        (self.live_root / "hydra-umc.project.json").write_text(
            '{\n  "name": "broken-project",\n  "maturity": "scaffolding"\n}\n', encoding="utf-8"
        )
        _git(["init", "-q"], self.live_root)
        _git(["config", "user.email", "t@example.com"], self.live_root)
        _git(["config", "user.name", "T"], self.live_root)
        _git(["add", "."], self.live_root)
        _git(["commit", "-q", "-m", "initial (broken) manifest"], self.live_root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_diagnose_to_closure_real_chain(self):
        # 1. Diagnostico OPS: a real edge collection over projects_root
        # finds the real manifest issue and derives a real incident from
        # it - nothing here is a hand-built fixture incident.
        snapshot_file = self.root / "snapshot-1.json"
        exit_code = main([
            "edge", "collect", "--node-name", "cm5-test",
            "--projects-root", str(self.projects_root), "--out", str(snapshot_file),
        ])
        self.assertEqual(exit_code, 0)
        snapshot = json.loads(snapshot_file.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["manifestIssues"][0]["reason"], "missing/empty required field(s): version")
        self.assertEqual(len(snapshot["incidents"]), 1)
        incident_id = snapshot["incidents"][0]["incidentId"]

        # 2. Incidente saneado (diagnosis) - the LLM call itself is the
        # one real external dependency mocked here (test_cli.py's own
        # established precedent), everything around it is real.
        diagnosis_file = self.root / "diagnosis.json"
        fake_diagnosis = DiagnosisResult(
            incident_id=incident_id, correlation_id=snapshot["correlationId"],
            provider="anthropic", model="claude-sonnet-5",
            generated_at="2026-09-08T00:00:00+00:00",
            explanation="hydra-umc.project.json is missing its required 'version' field.",
        )
        with mock.patch.object(cli, "diagnose_incident", return_value=fake_diagnosis):
            exit_code = main([
                "control", "diagnose", str(snapshot_file),
                "--incident-id", incident_id, "--out", str(diagnosis_file),
            ])
        self.assertEqual(exit_code, 0)
        self.assertIn("version", json.loads(diagnosis_file.read_text(encoding="utf-8"))["explanation"])

        # 3. Propuesta ligada a hash/revision: a real diff against the
        # real committed manifest, tied to this same real incident id.
        diff_file = self.root / "fix.diff"
        diff_file.write_text(_MANIFEST_FIX_DIFF, encoding="utf-8")
        proposal_file = self.root / "proposal.json"
        exit_code = main([
            "control", "propose", str(snapshot_file), "--incident-id", incident_id,
            "--project-name", "broken-project", "--description", "add the missing version field",
            "--diff-file", str(diff_file), "--rationale", fake_diagnosis.explanation,
            "--out", str(proposal_file),
        ])
        self.assertEqual(exit_code, 0)
        proposal = json.loads(proposal_file.read_text(encoding="utf-8"))
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(proposal["incidentId"], incident_id)

        # 4. Aprobacion.
        exit_code = main(["control", "approve", str(proposal_file), "--approved-by", "Juan Enrique"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(proposal_file.read_text(encoding="utf-8"))["status"], "approved")

        # 5. Pruebas + staging (canary_deploy.py's own real UPDATER-
        # pattern clone/apply/build/promote, exercised for real against
        # this real git repo).
        deploy_result_file = self.root / "deploy-result.json"
        exit_code = main([
            "control", "deploy-canary", str(proposal_file),
            "--live-root", str(self.live_root),
            "--build-test-command", f"{sys.executable} -c \"{_MANIFEST_VALIDATOR}\"",
            "--out", str(deploy_result_file),
        ])
        self.assertEqual(exit_code, 0)
        deploy_result = json.loads(deploy_result_file.read_text(encoding="utf-8"))
        self.assertTrue(deploy_result["promoted"], deploy_result)
        self.assertEqual(deploy_result["stageReached"], "promoted")

        # 6. Verificacion + cierre: re-collecting over the SAME
        # projects_root now finds NO manifest issue and a real,
        # complete project entry - the incident this chain started from
        # is genuinely resolved, not merely assumed closed because the
        # deploy step reported success.
        snapshot_file_2 = self.root / "snapshot-2.json"
        exit_code = main([
            "edge", "collect", "--node-name", "cm5-test",
            "--projects-root", str(self.projects_root), "--out", str(snapshot_file_2),
        ])
        self.assertEqual(exit_code, 0)
        snapshot_2 = json.loads(snapshot_file_2.read_text(encoding="utf-8"))
        self.assertEqual(snapshot_2["manifestIssues"], [])
        self.assertEqual(len(snapshot_2["projects"]), 1)
        self.assertEqual(snapshot_2["projects"][0]["version"], "0.0.1")
        self.assertEqual(snapshot_2["incidents"], [])

    def test_a_failing_fix_never_promotes_and_the_incident_survives_reopened(self):
        # Rollback-shaped counterpart to the happy path above: a diff
        # that does NOT actually satisfy the real validator (a typo'd
        # field name) must never be promoted, and the original incident
        # must still be real and reproducible afterward - proving
        # "cierre o rollback" is a real branch, not just documented prose.
        snapshot_file = self.root / "snapshot-1.json"
        main(["edge", "collect", "--node-name", "cm5-test", "--projects-root", str(self.projects_root), "--out", str(snapshot_file)])
        incident_id = json.loads(snapshot_file.read_text(encoding="utf-8"))["incidents"][0]["incidentId"]

        bad_diff = _MANIFEST_FIX_DIFF.replace('"version"', '"versionx"')
        diff_file = self.root / "bad-fix.diff"
        diff_file.write_text(bad_diff, encoding="utf-8")
        proposal_file = self.root / "proposal.json"
        main([
            "control", "propose", str(snapshot_file), "--incident-id", incident_id,
            "--project-name", "broken-project", "--description", "typo'd field name",
            "--diff-file", str(diff_file), "--rationale", "x", "--out", str(proposal_file),
        ])
        main(["control", "approve", str(proposal_file), "--approved-by", "Juan Enrique"])

        deploy_result_file = self.root / "deploy-result.json"
        exit_code = main([
            "control", "deploy-canary", str(proposal_file),
            "--live-root", str(self.live_root),
            "--build-test-command", f"{sys.executable} -c \"{_MANIFEST_VALIDATOR}\"",
            "--out", str(deploy_result_file),
        ])
        # cli.py's own real `return 0 if result.promoted else 1` - a
        # failed build is still a real, written result (never a crash),
        # but the CLI's own exit code honestly reflects "nothing was
        # deployed", matching every other real CLI outcome-vs-crash
        # distinction already made in this file.
        self.assertEqual(exit_code, 1)
        deploy_result = json.loads(deploy_result_file.read_text(encoding="utf-8"))
        self.assertFalse(deploy_result["promoted"])
        self.assertEqual(deploy_result["stageReached"], "diff_applied")

        # The live checkout was genuinely never touched - re-collecting
        # finds the exact same real incident, still open.
        snapshot_file_2 = self.root / "snapshot-2.json"
        main(["edge", "collect", "--node-name", "cm5-test", "--projects-root", str(self.projects_root), "--out", str(snapshot_file_2)])
        snapshot_2 = json.loads(snapshot_file_2.read_text(encoding="utf-8"))
        self.assertEqual(snapshot_2["manifestIssues"][0]["reason"], "missing/empty required field(s): version")
        self.assertEqual(len(snapshot_2["incidents"]), 1)


if __name__ == "__main__":
    unittest.main()
