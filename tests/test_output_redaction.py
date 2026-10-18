# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_output_redaction.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Everything this tool prints, writes as evidence or appends to the audit
journal goes through one redaction function."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hydra_umc_ops_agent import cli
from hydra_umc_ops_agent.audit_journal import append_event, read_events, verify_chain
from hydra_umc_ops_agent.cli import main

SECRETS = ("hunter2-token-value", "dXNlcjpwYXNzd29yZA", "abcdef0123456789", "swordfish99")


def _noisy() -> dict:
    return {
        "argv": "streamer --token hunter2-token-value --port 8080",
        "header": "Authorization: Basic dXNlcjpwYXNzd29yZA==",
        "cookie": "Cookie: session=abcdef0123456789",
        "nested": {"password": "swordfish99", "lines": ["ok", "ghp_" + "a" * 36]},
    }


class AuditJournalRedactionTests(unittest.TestCase):
    def test_the_journal_stores_no_command_line_secret_and_the_chain_stays_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            append_event(path, "deploy", _noisy())
            raw = path.read_text(encoding="utf-8")
            for secret in SECRETS + ("ghp_" + "a" * 36,):
                self.assertNotIn(secret, raw)
            self.assertIn("--port 8080", raw)
            self.assertEqual(read_events(path)[0]["event"], "deploy")
            self.assertEqual(verify_chain(path), [])


class CliOutputRedactionTests(unittest.TestCase):
    def test_edge_collect_output_goes_through_the_redaction_point(self):
        snapshot = mock.Mock()
        snapshot.to_dict.return_value = _noisy()
        snapshot.incidents = []
        out = io.StringIO()
        with mock.patch.object(cli, "collect_snapshot", return_value=snapshot), contextlib.redirect_stdout(out):
            code = main(["edge", "collect", "--node-name", "n", "--projects-root", "."])
        self.assertEqual(code, 0)
        text = out.getvalue()
        for secret in SECRETS:
            self.assertNotIn(secret, text)
        self.assertEqual(json.loads(text)["nested"]["password"], "[REDACTED]")

    def test_an_output_file_is_redacted_too(self):
        snapshot = mock.Mock()
        snapshot.to_dict.return_value = _noisy()
        snapshot.incidents = []
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "snap.json"
            with mock.patch.object(cli, "collect_snapshot", return_value=snapshot), contextlib.redirect_stdout(io.StringIO()):
                main(["edge", "collect", "--node-name", "n", "--projects-root", ".", "--out", str(target)])
            written = target.read_text(encoding="utf-8")
        for secret in SECRETS:
            self.assertNotIn(secret, written)


if __name__ == "__main__":
    unittest.main()
