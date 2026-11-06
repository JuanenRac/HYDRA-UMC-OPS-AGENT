# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_contract_check.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The snapshot and proposal files read with `contracts.validate`: off by default, `warn` says it, `strict` refuses; the verdict is the one of the SDK validators."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from hydra_umc_ops_agent import contract_check
from hydra_umc_ops_agent.change_proposal import ProposalLoadError, load_proposal
from hydra_umc_ops_agent.config import ConfigError, parse_config
from hydra_umc_ops_agent.control_plane import SnapshotLoadError, load_snapshot

try:
    import hydra_umc_sdk.maintenance_agent  # noqa: F401
    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False


class ConfigTests(unittest.TestCase):
    def test_it_is_off_by_default(self):
        self.assertEqual(parse_config({}).contracts.validate, "off")

    def test_only_the_three_modes_are_accepted(self):
        for mode in ("off", "warn", "strict"):
            self.assertEqual(parse_config({"contracts": {"validate": mode}}).contracts.validate, mode)
        with self.assertRaises(ConfigError):
            parse_config({"contracts": {"validate": "loud"}})


@unittest.skipUnless(HAVE_SDK, "the SDK is not installed")
class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        contract_check.set_mode("off")

    def tearDown(self):
        contract_check.set_mode("off")
        self.tmp.cleanup()

    def write(self, name: str, payload: dict) -> Path:
        path = self.dir / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_off_reads_a_file_that_does_not_match(self):
        path = self.write("snapshot.json", {"sourceNode": "n", "incidents": []})
        self.assertEqual(load_snapshot(path)["sourceNode"], "n")

    def test_strict_refuses_a_snapshot_that_does_not_match(self):
        path = self.write("snapshot.json", {"sourceNode": "n", "incidents": []})
        contract_check.set_mode("strict")
        with self.assertRaises(SnapshotLoadError) as caught:
            load_snapshot(path)
        self.assertIn("NodeSnapshot", str(caught.exception))

    def test_warn_says_it_and_goes_on(self):
        path = self.write("snapshot.json", {"sourceNode": "n", "incidents": []})
        contract_check.set_mode("warn")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(load_snapshot(path)["sourceNode"], "n")
        self.assertIn("NodeSnapshot", err.getvalue())

    def test_strict_refuses_a_proposal_that_does_not_match(self):
        path = self.write("proposal.json", {"proposalId": "p1"})
        contract_check.set_mode("strict")
        with self.assertRaises(ProposalLoadError):
            load_proposal(path)

    def test_the_canary_result_is_checked_too(self):
        with self.assertRaises(contract_check.ContractCheckError):
            contract_check.check("CanaryDeployResult", {"deployId": "d"}, "result.json", mode="strict")


if __name__ == "__main__":
    unittest.main()
