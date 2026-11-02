# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_config.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The configuration: everything optional is off by default, and a malformed file raises."""
import json
import tempfile
import unittest
from pathlib import Path

from hydra_umc_ops_agent.config import AgentConfig, ConfigError, load_config, parse_config
from hydra_umc_ops_agent.messages import message_keys, translate

LANGUAGES = ("en", "es", "de", "fr", "it", "ja", "zh", "pt")


class DefaultsTests(unittest.TestCase):
    def test_every_optional_feature_is_off_without_a_file(self):
        config = load_config(None)
        for section in ("transport", "healing", "notify", "multinode", "llm_propose", "metrics"):
            self.assertFalse(getattr(config, section).enabled, section)
        self.assertFalse(config.transport.allow_remote_deploy)
        self.assertFalse(config.transport.allow_non_loopback)
        self.assertFalse(config.llm_propose.allow_non_loopback)
        self.assertEqual(config.transport.bind, "127.0.0.1")
        self.assertIn("127.0.0.1", config.llm_propose.endpoint)

    def test_the_example_file_parses_and_has_everything_off(self):
        example = Path(__file__).resolve().parent.parent / "deploy" / "ops-agent.json.example"
        config = load_config(example)
        self.assertIsInstance(config, AgentConfig)
        self.assertFalse(config.transport.enabled or config.notify.enabled or config.llm_propose.enabled or config.multinode.enabled)


class ParsingTests(unittest.TestCase):
    def test_values_are_read_and_typed(self):
        config = parse_config({"multinode": {"enabled": True, "canary_nodes": 2, "observe_seconds": 30, "poll_seconds": 0.5},
                               "healing": {"trigger_statuses": ["unreachable"]}, "notify": {"language": "pt"}})
        self.assertTrue(config.multinode.enabled)
        self.assertEqual((config.multinode.canary_nodes, config.multinode.observe_seconds, config.multinode.poll_seconds), (2, 30.0, 0.5))
        self.assertEqual(config.healing.trigger_statuses, ("UNREACHABLE",))
        self.assertEqual(config.notify.language, "pt")

    def test_malformed_input_raises(self):
        bad = [
            [], {"nope": {}}, {"transport": {"enabled": "yes"}}, {"transport": {"port": 0}}, {"transport": {"port": True}},
            {"transport": {"max_body_bytes": 1.5}}, {"transport": {"unknown": 1}}, {"notify": {"language": "xx"}},
            {"healing": {"severity": "loud"}}, {"healing": {"trigger_statuses": "UNREACHABLE"}}, {"multinode": {"canary_nodes": 0}},
            {"transport": "on"}, {"notify": {"topic_prefix": ""}},
        ]
        for raw in bad:
            with self.assertRaises(ConfigError, msg=str(raw)):
                parse_config(raw)

    def test_a_file_that_exists_but_is_broken_raises_and_a_missing_one_means_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            self.assertFalse(load_config(path).transport.enabled)
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)
            path.write_text(json.dumps({"metrics": {"enabled": True}}), encoding="utf-8")
            self.assertTrue(load_config(path).metrics.enabled)


class MessagesTests(unittest.TestCase):
    def test_every_message_exists_in_the_eight_languages_with_its_placeholders(self):
        sample = {"severity": "critical", "node": "n1", "component": "c1", "detail": "d1", "count": 3, "project": "p1"}
        for key in message_keys():
            english = translate(key, "en", **sample)
            for language in LANGUAGES:
                text = translate(key, language, **sample)
                self.assertTrue(text.strip(), (key, language))
                for value in sample.values():
                    if str(value) in english:
                        self.assertIn(str(value), text, (key, language))
            if key != "proposal.generated_marker":
                self.assertNotEqual(translate(key, "ja", **sample), english)

    def test_unknown_language_falls_back_to_english_and_unknown_key_raises(self):
        self.assertEqual(translate("incident.resolved", "xx", node="n", component="c"), translate("incident.resolved", "en", node="n", component="c"))
        with self.assertRaises(KeyError):
            translate("nope")

    def test_portuguese_is_european(self):
        self.assertIn("revertido", translate("canary.rolled_back", "pt", node="n", detail="d"))


if __name__ == "__main__":
    unittest.main()
