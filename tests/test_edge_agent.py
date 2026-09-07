# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_edge_agent.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from hydra_umc_ops_agent.edge_agent import NodeSnapshot, collect_snapshot
from hydra_umc_ops_agent.inventory import HttpHealthResult, ManifestScanIssue, ServiceHealthResult


def _write_manifest(path: Path, **fields) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "hydra-umc.project.json").write_text(json.dumps(fields), encoding="utf-8")


class CollectSnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_clean_root_with_no_checks_requested_yields_an_empty_but_valid_snapshot(self):
        # V07-020 (found in an independent revalidation audit, P2):
        # systemd_available used to default to True and this test
        # asserted exactly that stale default as if it were correct -
        # but "no unit was ever configured" is a genuinely different,
        # unknown state from "systemd was actually asked and answered
        # True". None is the real, honest answer here.
        snapshot = collect_snapshot("cm5-test", self.root)
        self.assertEqual(snapshot.source_node, "cm5-test")
        self.assertEqual(snapshot.projects, ())
        self.assertEqual(snapshot.incidents, ())
        self.assertIsNone(snapshot.systemd_available, "no units were requested, so systemd was never actually asked anything")

    def test_a_real_valid_project_appears_in_the_snapshot_with_no_incident(self):
        _write_manifest(self.root / "proj", name="PROJ", version="1.0.0", maturity="established")
        snapshot = collect_snapshot("cm5-test", self.root)
        self.assertEqual(len(snapshot.projects), 1)
        self.assertEqual(snapshot.incidents, ())

    def test_a_malformed_manifest_becomes_a_real_incident_in_the_same_batch(self):
        project_dir = self.root / "broken"
        project_dir.mkdir()
        (project_dir / "hydra-umc.project.json").write_text("{not json", encoding="utf-8")
        snapshot = collect_snapshot("cm5-test", self.root)
        self.assertEqual(len(snapshot.manifest_issues), 1)
        self.assertEqual(len(snapshot.incidents), 1)
        self.assertEqual(snapshot.incidents[0].correlation_id, snapshot.correlation_id)

    def test_requesting_a_systemd_unit_on_a_host_without_systemctl_degrades_honestly(self):
        if shutil.which("systemctl") is not None:
            self.skipTest("this host has a real systemctl")
        snapshot = collect_snapshot("cm5-test", self.root, systemd_units=["some.service"])
        self.assertFalse(snapshot.systemd_available)
        self.assertIsNotNone(snapshot.systemd_unavailable_reason)
        self.assertEqual(snapshot.service_health, (), "no fake health result should be invented")

    def test_to_dict_is_real_json_serializable(self):
        _write_manifest(self.root / "proj", name="PROJ", version="1.0.0", maturity="established")
        snapshot = collect_snapshot("cm5-test", self.root)
        # Must not raise - proves every field really is JSON-plain, not a
        # dataclass/tuple that json.dumps would choke on.
        payload = json.dumps(snapshot.to_dict())
        reloaded = json.loads(payload)
        self.assertEqual(reloaded["sourceNode"], "cm5-test")
        self.assertEqual(len(reloaded["projects"]), 1)

    # REV-013 regression: a real audit found manifestIssues[].reason,
    # serviceHealth[].detail and httpHealth[].detail/url (all real,
    # free-text fields that can carry a copy-pasted secret, same as an
    # incident's own symptom) leaving to_dict() completely unredacted -
    # only incidents[].symptom ever went through redact_secrets().
    def test_secret_shaped_snapshot_fields_are_redacted_in_to_dict(self):
        snapshot = NodeSnapshot(
            source_node="cm5-test",
            collected_at="now",
            correlation_id="corr-1",
            projects=(),
            manifest_issues=(ManifestScanIssue(path="p", reason='could not read: password="AUDIT_FAKE_SECRET"'),),
            systemd_available=True,
            systemd_unavailable_reason=None,
            service_health=(ServiceHealthResult(unit_name="u", active=True, detail="token=AUDIT_FAKE_SECRET"),),
            http_health=(
                HttpHealthResult(
                    url="https://audit:AUDIT_FAKE_SECRET@example.invalid/",
                    reachable=True, status_code=200, detail="HTTP 200 token=AUDIT_FAKE_SECRET",
                ),
            ),
            incidents=(),
        )
        self.assertNotIn("AUDIT_FAKE_SECRET", json.dumps(snapshot.to_dict()))


if __name__ == "__main__":
    unittest.main()
