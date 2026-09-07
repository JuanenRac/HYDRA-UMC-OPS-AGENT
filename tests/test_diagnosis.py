# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_diagnosis.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real tests for diagnosis.py, all against a fake `AIProvider` (the one
real seam this module depends on) - no real network call, no real
`anthropic`/`openai` package needed. A couple of tests also exercise the
real provider RESOLUTION path (resolve_provider / diagnose_incident's
own provider_name handling) against the real, installed-or-not state of
those optional packages on this machine."""
import os
import unittest

from hydra_umc_ops_agent.diagnosis import (
    AnthropicProvider,
    DiagnosisResult,
    MissingApiKeyError,
    OpenAIProvider,
    ProviderRequestError,
    UnknownProviderError,
    _build_prompt,
    diagnose_incident,
    resolve_provider,
)
from hydra_umc_ops_agent.incident import MaintenanceIncident


def _make_incident(symptom: str = "systemd unit is not active: inactive") -> MaintenanceIncident:
    return MaintenanceIncident(
        incident_id="inc-1",
        source_node="cm5-cell-3",
        detected_at="2026-09-06T12:00:00+00:00",
        severity="critical",
        component="hydra-umc-server.service",
        symptom=symptom,
        evidence_refs=("systemctl is-active hydra-umc-server.service",),
        redaction_level="sanitized",
        requested_by="edge-agent:auto",
        correlation_id="corr-1",
    )


class _FakeProvider:
    """The whole real seam this module depends on - one method. Records
    the exact call it received, and returns a fixed answer or raises a
    fixed exception, both configurable per test."""

    name = "fake"

    def __init__(self, answer: str | None = None, to_raise: Exception | None = None) -> None:
        self._answer = answer
        self._to_raise = to_raise
        self.last_call: dict[str, object] | None = None

    def complete(self, *, system_prompt, user_prompt, model, max_tokens):
        self.last_call = {"system_prompt": system_prompt, "user_prompt": user_prompt, "model": model, "max_tokens": max_tokens}
        if self._to_raise is not None:
            raise self._to_raise
        return self._answer


class BuildPromptTests(unittest.TestCase):
    def test_prompt_includes_the_real_incident_fields(self):
        prompt = _build_prompt(_make_incident())
        self.assertIn("hydra-umc-server.service", prompt)
        self.assertIn("critical", prompt)
        self.assertIn("systemctl is-active", prompt)

    def test_prompt_redacts_a_secret_shape_even_if_the_incident_object_did_not(self):
        # incident.py's own to_dict() already redacts - this proves the
        # outbound-to-an-AI-provider path has its OWN independent
        # redaction pass too, not a reliance on every upstream caller
        # having already done it.
        incident = _make_incident(symptom="crash loop, env dump: DB_PASSWORD=hunter2")
        prompt = _build_prompt(incident)
        self.assertNotIn("hunter2", prompt)
        self.assertIn("[REDACTED]", prompt)


class DiagnoseIncidentWithAnyProviderTests(unittest.TestCase):
    """Proves the module is genuinely provider-agnostic: any object with
    a real `.complete()` method works, regardless of name or vendor."""

    def test_successful_diagnosis_returns_a_real_result_with_the_provider_text(self):
        fake = _FakeProvider(answer="Likely cause: the service crashed on startup.")
        result = diagnose_incident(_make_incident(), provider=fake, model="some-model")
        self.assertIsInstance(result, DiagnosisResult)
        self.assertEqual(result.incident_id, "inc-1")
        self.assertEqual(result.correlation_id, "corr-1")
        self.assertEqual(result.provider, "fake")
        self.assertEqual(result.model, "some-model")
        self.assertIn("crashed on startup", result.explanation)
        self.assertIn("suggestion, not a decision", result.disclaimer)

    def test_the_real_call_carries_the_system_prompt_and_the_incident_in_the_user_prompt(self):
        fake = _FakeProvider(answer="ok")
        diagnose_incident(_make_incident(), provider=fake, model="some-model")
        self.assertIsNotNone(fake.last_call)
        self.assertIn("root cause", fake.last_call["system_prompt"])
        self.assertIn("hydra-umc-server.service", fake.last_call["user_prompt"])

    def test_a_provider_side_exception_is_wrapped_not_leaked_raw(self):
        fake = _FakeProvider(to_raise=ConnectionError("connection reset"))
        with self.assertRaises(ProviderRequestError):
            diagnose_incident(_make_incident(), provider=fake, model="some-model")

    def test_the_result_re_redacts_the_explanation_on_serialization(self):
        fake = _FakeProvider(answer="token=abcdef1234 was found in the logs")
        result = diagnose_incident(_make_incident(), provider=fake, model="some-model")
        serialized = result.to_dict()
        self.assertNotIn("abcdef1234", serialized["explanation"])

    def test_round_trip_to_dict_from_dict(self):
        fake = _FakeProvider(answer="a clean explanation")
        result = diagnose_incident(_make_incident(), provider=fake, model="some-model")
        restored = DiagnosisResult.from_dict(result.to_dict())
        self.assertEqual(restored.incident_id, result.incident_id)
        self.assertEqual(restored.explanation, result.explanation)
        self.assertEqual(restored.provider, "fake")

    def test_no_model_and_no_known_default_for_this_provider_name_raises_a_real_error(self):
        fake = _FakeProvider(answer="ok")
        fake.name = "totally-unrecognized-provider"
        with self.assertRaises(Exception):
            diagnose_incident(_make_incident(), provider=fake)  # no model, no known default


class ProviderResolutionTests(unittest.TestCase):
    def test_unknown_provider_name_raises_a_real_distinct_error(self):
        with self.assertRaises(UnknownProviderError):
            resolve_provider("not-a-real-provider")

    def test_anthropic_provider_requires_a_real_api_key(self):
        old = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            with self.assertRaises(MissingApiKeyError):
                AnthropicProvider()
        finally:
            if old is not None:
                os.environ["ANTHROPIC_API_KEY"] = old

    def test_openai_provider_requires_a_real_api_key(self):
        old = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with self.assertRaises(MissingApiKeyError):
                OpenAIProvider()
        finally:
            if old is not None:
                os.environ["OPENAI_API_KEY"] = old

    def test_resolve_provider_builds_the_right_real_class(self):
        provider = resolve_provider("anthropic", api_key="sk-ant-fake-for-construction-only")
        self.assertIsInstance(provider, AnthropicProvider)
        provider = resolve_provider("openai", api_key="sk-fake-for-construction-only")
        self.assertIsInstance(provider, OpenAIProvider)

    def test_diagnose_incident_with_no_provider_and_no_api_key_raises_a_real_error(self):
        old = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            with self.assertRaises(MissingApiKeyError):
                diagnose_incident(_make_incident())  # default provider_name="anthropic", no key anywhere
        finally:
            if old is not None:
                os.environ["ANTHROPIC_API_KEY"] = old


if __name__ == "__main__":
    unittest.main()
