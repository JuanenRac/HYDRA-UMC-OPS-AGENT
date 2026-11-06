# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_evidence_bundle.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The EvidenceBundle this agent writes: redacted, sealed with the checksum the readers recompute, off until switched on, and the same as the shared contract."""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from hydra_umc_ops_agent.cli import main
from hydra_umc_ops_agent.config import ConfigError, parse_config
from hydra_umc_ops_agent.evidence_bundle import (
    EvidenceBundleError, build_bundle, bundle_checksum, bundle_matches_checksum, component_versions_of, validate_bundle,
)
from hydra_umc_ops_agent.incident import MaintenanceIncident

PASSWORD_LINE = "db password=" + "hunter2-" + "not-a-real-one"


def make_incident() -> MaintenanceIncident:
    return MaintenanceIncident(
        incident_id="inc-1", source_node="cm5-a", detected_at="2026-01-01T00:00:00+00:00", severity="critical",
        component="hydra-server", symptom="the service does not answer", evidence_refs=("unit:hydra-server",),
        redaction_level="sanitized", requested_by=None, correlation_id="corr-1",
    )


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class BuildTests(unittest.TestCase):
    def build(self, **kwargs):
        return build_bundle(make_incident(), component_versions={"hydra-server": "1.0.0"}, now=datetime(2026, 1, 1, tzinfo=timezone.utc), **kwargs)

    def test_a_bundle_is_valid_and_its_checksum_matches(self):
        bundle = self.build()
        validate_bundle(bundle)
        self.assertTrue(bundle_matches_checksum(bundle))
        self.assertEqual(bundle["checksum"], bundle_checksum(bundle))
        self.assertEqual(bundle["componentVersions"], {"hydra-server": "1.0.0"})
        self.assertGreaterEqual(len(bundle["reproductionSteps"]), 1)
        self.assertIn("not validated", bundle["localValidationResult"])

    def test_an_edited_bundle_no_longer_matches(self):
        bundle = self.build()
        bundle["impact"] = "something else"
        self.assertFalse(bundle_matches_checksum(bundle))

    def test_every_text_is_redacted(self):
        bundle = self.build(log_excerpts=[PASSWORD_LINE], manifests=[PASSWORD_LINE], failed_tests=[PASSWORD_LINE], actions_attempted=[PASSWORD_LINE],
                            reproduction_steps=[PASSWORD_LINE], impact=PASSWORD_LINE, local_validation_result=PASSWORD_LINE)
        self.assertNotIn("hunter2", json.dumps(bundle))

    def test_the_shape_is_closed_and_strict(self):
        bundle = self.build()
        for mutate in (
            lambda b: b.pop("impact"),
            lambda b: b.update(extra="x"),
            lambda b: b.update(reproductionSteps=[]),
            lambda b: b.update(failedTests=[1]),
            lambda b: b.update(date="yesterday"),
            lambda b: b.update(componentVersions=[]),
        ):
            broken = json.loads(json.dumps(bundle))
            mutate(broken)
            with self.assertRaises(EvidenceBundleError):
                validate_bundle(broken)

    def test_versions_come_from_the_projects_of_a_snapshot(self):
        snapshot = {"projects": [{"name": "a", "version": "1"}, "junk", {"name": "b"}, {"name": "c", "version": "2"}]}
        self.assertEqual(component_versions_of(snapshot), {"a": "1", "c": "2"})


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.snapshot = self.dir / "snapshot.json"
        self.snapshot.write_text(json.dumps({
            "sourceNode": "cm5-a",
            "projects": [{"name": "hydra-server", "version": "1.0.0"}],
            "incidents": [make_incident().to_dict()],
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, enabled: bool) -> str:
        path = self.dir / "cfg.json"
        path.write_text(json.dumps({"evidence_bundle": {"enabled": enabled, "max_log_lines": 2}}), encoding="utf-8")
        return str(path)

    def test_it_is_off_by_default_and_names_its_switch(self):
        code, _, err = run_cli("--config", self.config(False), "control", "evidence-bundle", str(self.snapshot), "--incident-id", "inc-1")
        self.assertEqual(code, 1)
        self.assertIn("evidence_bundle.enabled", err)

    def test_switched_on_it_writes_a_redacted_sealed_file(self):
        log = self.dir / "service.log"
        log.write_text("old line\nmiddle\n" + PASSWORD_LINE + "\nlast line\n", encoding="utf-8")
        out = self.dir / "bundle.json"
        code, text, err = run_cli("--config", self.config(True), "control", "evidence-bundle", str(self.snapshot), "--incident-id", "inc-1",
                                  "--log-file", str(log), "--failed-test", "test_health", "--out", str(out))
        self.assertEqual(code, 0, err)
        bundle = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(bundle_matches_checksum(bundle))
        self.assertEqual(bundle["componentVersions"], {"hydra-server": "1.0.0"})
        excerpt = bundle["redactedLogExcerpts"][0]
        self.assertNotIn("old line", excerpt)
        self.assertIn("last line", excerpt)
        self.assertNotIn("hunter2", out.read_text(encoding="utf-8"))
        self.assertEqual(bundle["failedTests"], ["test_health"])

    def test_an_unknown_incident_is_an_error(self):
        code, _, err = run_cli("--config", self.config(True), "control", "evidence-bundle", str(self.snapshot), "--incident-id", "nope")
        self.assertEqual(code, 1)
        self.assertIn("nope", err)

    def test_the_section_rejects_wrong_values(self):
        with self.assertRaises(ConfigError):
            parse_config({"evidence_bundle": {"enabled": True, "max_log_lines": 0}})
        with self.assertRaises(ConfigError):
            parse_config({"evidence_bundle": {"surprise": 1}})


class SharedContractTests(unittest.TestCase):
    """The same bundle against the validator of the SDK, when it is installed."""

    def test_the_sdk_accepts_the_bundle_and_computes_the_same_checksum(self):
        try:
            from hydra_umc_sdk.evidence_bundle import bundle_matches_checksum as sdk_matches, validate_evidence_bundle
        except ImportError:
            self.skipTest("the installed SDK has no evidence bundle contract yet")
        bundle = build_bundle(make_incident(), component_versions={"hydra-server": "1.0.0"}, log_excerpts=["a line"])
        validate_evidence_bundle(bundle)
        self.assertTrue(sdk_matches(bundle))


if __name__ == "__main__":
    unittest.main()
