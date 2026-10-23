"""The shared redaction passes the cases every implementation of it must pass."""
import json
import unittest
from pathlib import Path

from hydra_umc_ops_agent.log_redaction import redact_json, redact_lines, redact_secrets

VECTORS = json.loads((Path(__file__).resolve().parent / "redaction_vectors.json").read_text(encoding="utf-8"))


class SharedRedactionVectorsTest(unittest.TestCase):
    def test_text_cases(self):
        for case in VECTORS["text"]:
            with self.subTest(case["name"]):
                self.assertEqual(redact_secrets(case["input"]), case["expected"])

    def test_json_cases(self):
        for case in VECTORS["json"]:
            with self.subTest(case["name"]):
                self.assertEqual(redact_json(case["input"]), case["expected"])

    def test_line_cases(self):
        for case in VECTORS["lines"]:
            with self.subTest(case["name"]):
                self.assertEqual(redact_lines(case["input"]), case["expected"])


if __name__ == "__main__":
    unittest.main()
