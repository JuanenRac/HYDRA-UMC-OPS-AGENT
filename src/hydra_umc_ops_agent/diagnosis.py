# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/diagnosis.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Delivery 2 - Diagnosis: an AI-provider-assisted read of the evidence
Delivery 1 already collects (a single real `MaintenanceIncident`), producing
a proposed root-cause explanation.

This module is a SUGGESTION generator only. It never:
- decides anything (that is Delivery 3 - a human-approved change),
- mutates an incident, a snapshot file, or anything else on disk,
- retries or auto-applies its own output.

Provider-agnostic by design - real, deliberately NOT locked to one AI
vendor. `diagnose_incident()` depends only on the minimal `AIProvider`
Protocol below (one method: `complete()`); everything provider-specific
(which SDK, which request/response shape) lives behind that seam in its
own small class. Two real, concrete providers ship out of the box -
`AnthropicProvider` (the official `anthropic` package) and
`OpenAIProvider` (the official `openai` package) - both optional
dependencies (`pip install -e ".[ai-anthropic]"` / `".[ai-openai]"`),
each imported lazily so the Delivery-1 core keeps working with zero
extra dependencies when this feature is never used. A caller with its
own provider (a third vendor, a local model server, ...) can pass any
object implementing `AIProvider` directly - `diagnose_incident()` never
needs to know it exists.

The API key is read ONLY from a real environment variable specific to
the chosen provider (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`), or an
explicit `api_key` argument for a caller that already has one - never
from a CLI flag (which would land in shell history) and never from a
repository file.

Every piece of incident text this module sends out is passed through
`redact_secrets()` again immediately before being placed in the prompt -
defense in depth, exactly like `MaintenanceIncident.to_dict()` already
does for its own serialization - because sending sanitized evidence to an
external AI provider is the one new real secret-exfiltration surface this
delivery introduces.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .incident import MaintenanceIncident
from .log_redaction import redact_secrets

DEFAULT_MAX_TOKENS = 1024

# One sensible default model per built-in provider, used only when the
# caller does not pass `model` explicitly - always overridable, never a
# silent, hidden choice.
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4o-mini",
}

_SYSTEM_PROMPT = (
    "You are a maintenance-diagnosis assistant for a robotics automation "
    "ecosystem. You are given ONE already-sanitized incident record "
    "(secrets, tokens and credentials have already been redacted before "
    "it reached you). Propose a plausible root cause and, if useful, what "
    "additional READ-ONLY evidence would help confirm it. Do not propose "
    "a specific fix, patch, command to run, or any action to take - a "
    "separate, human-approved step handles that. Do not invent facts not "
    "present in the incident record. Keep your answer under 200 words."
)


class DiagnosisError(RuntimeError):
    """Base for every real, distinct failure this module can report -
    never a bare exception, so a caller (the CLI) can always print an
    honest, specific reason instead of a raw traceback."""


class UnknownProviderError(DiagnosisError):
    """`provider_name` did not match any built-in provider, and no real
    `AIProvider` object was passed in its place."""


class ProviderUnavailableError(DiagnosisError):
    """The chosen provider's own optional SDK package is not installed.
    Distinct from a network/API failure - this is a real environment
    fact, not a transient condition, and the fix is a real `pip
    install`, not a retry."""


class MissingApiKeyError(DiagnosisError):
    """No API key was supplied and the provider's own real environment
    variable is not set. Distinct from every other failure mode - this
    is a real configuration gap, not a network or provider problem, and
    retrying changes nothing."""


class ProviderRequestError(DiagnosisError):
    """The provider was reached but the request itself failed (a real
    HTTP/API error, a timeout, a connection failure) - wraps whatever
    that provider's own SDK exception hierarchy raised, so callers of
    this module never need to import or catch that hierarchy
    themselves."""


class ProviderResponseError(DiagnosisError):
    """The provider answered, but the response did not have the real
    shape this module knows how to read (e.g. an empty choice/content
    list) - distinct from a request failure, since the request itself
    succeeded."""


class AIProvider(Protocol):
    """The one real seam `diagnose_incident()` depends on. Any object
    with this single method works - the two built-in providers below,
    a test's own fake, or a caller's own third-vendor/local-model
    wrapper. Everything provider-specific (SDK shape, model defaults,
    credential env var) stays inside the concrete implementation."""

    def complete(self, *, system_prompt: str, user_prompt: str, model: str, max_tokens: int) -> str: ...


class AnthropicProvider:
    """Real Anthropic Messages API provider - the official `anthropic`
    package, imported lazily. See `AIProvider` above for the contract
    this implements."""

    name = "anthropic"

    def __init__(self, *, api_key: str | None = None) -> None:
        resolved = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved:
            raise MissingApiKeyError(
                "no Anthropic API key available - set ANTHROPIC_API_KEY "
                "(this module never reads one from a CLI flag or a repository file)"
            )
        self._api_key = resolved

    def complete(self, *, system_prompt: str, user_prompt: str, model: str, max_tokens: int) -> str:
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderUnavailableError(
                "the optional 'anthropic' package is not installed - run: pip install -e \".[ai-anthropic]\""
            ) from exc
        client = anthropic.Anthropic(api_key=self._api_key)
        try:
            response = client.messages.create(
                model=model, max_tokens=max_tokens, system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as exc:  # the real SDK's own APIError/APIConnectionError/etc. hierarchy
            raise ProviderRequestError(f"the request to Anthropic failed: {exc}") from exc
        content = getattr(response, "content", None)
        if not content:
            raise ProviderResponseError("Anthropic's response had no content blocks")
        text = getattr(content[0], "text", None)
        if not text:
            raise ProviderResponseError("Anthropic's response content block had no text")
        return str(text)


class OpenAIProvider:
    """Real OpenAI Chat Completions API provider - the official
    `openai` package, imported lazily. See `AIProvider` above for the
    contract this implements."""

    name = "openai"

    def __init__(self, *, api_key: str | None = None) -> None:
        resolved = api_key or os.environ.get("OPENAI_API_KEY")
        if not resolved:
            raise MissingApiKeyError(
                "no OpenAI API key available - set OPENAI_API_KEY "
                "(this module never reads one from a CLI flag or a repository file)"
            )
        self._api_key = resolved

    def complete(self, *, system_prompt: str, user_prompt: str, model: str, max_tokens: int) -> str:
        try:
            import openai
        except ImportError as exc:
            raise ProviderUnavailableError(
                "the optional 'openai' package is not installed - run: pip install -e \".[ai-openai]\""
            ) from exc
        client = openai.OpenAI(api_key=self._api_key)
        try:
            response = client.chat.completions.create(
                model=model, max_tokens=max_tokens,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            )
        except Exception as exc:  # the real SDK's own APIError/APIConnectionError/etc. hierarchy
            raise ProviderRequestError(f"the request to OpenAI failed: {exc}") from exc
        choices = getattr(response, "choices", None)
        if not choices:
            raise ProviderResponseError("OpenAI's response had no choices")
        text = getattr(choices[0].message, "content", None) if hasattr(choices[0], "message") else None
        if not text:
            raise ProviderResponseError("OpenAI's response choice had no message content")
        return str(text)


_BUILTIN_PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}


def resolve_provider(provider_name: str, *, api_key: str | None = None) -> AIProvider:
    """Real provider lookup by name - `diagnose_incident()`'s own
    default path when a caller does not already have an `AIProvider`
    object of their own to pass in directly."""
    provider_cls = _BUILTIN_PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise UnknownProviderError(
            f"unknown provider {provider_name!r} - built-in providers are {sorted(_BUILTIN_PROVIDERS)}; "
            "pass a real AIProvider object directly for anything else"
        )
    return provider_cls(api_key=api_key)


@dataclass(frozen=True)
class DiagnosisResult:
    """A single proposed diagnosis for one incident - itself just another
    piece of evidence for a human to read, never something this project
    acts on by itself. `to_dict()`/`from_dict()` mirror
    `MaintenanceIncident`'s own camelCase JSON contract style."""
    incident_id: str
    correlation_id: str
    provider: str
    model: str
    generated_at: str
    explanation: str
    disclaimer: str = (
        "This is an AI-generated suggestion, not a decision. It has not "
        "been reviewed or approved by a person, and nothing has been "
        "changed on any host because of it."
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "incidentId": self.incident_id,
            "correlationId": self.correlation_id,
            "provider": self.provider,
            "model": self.model,
            "generatedAt": self.generated_at,
            "explanation": redact_secrets(self.explanation),
            "disclaimer": self.disclaimer,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "DiagnosisResult":
        return cls(
            incident_id=str(data["incidentId"]),
            correlation_id=str(data["correlationId"]),
            provider=str(data.get("provider", "")),
            model=str(data["model"]),
            generated_at=str(data["generatedAt"]),
            explanation=str(data["explanation"]),
            disclaimer=str(data.get("disclaimer", "")),
        )


def _build_prompt(incident: MaintenanceIncident) -> str:
    # Every field is redacted again here, immediately before leaving this
    # process for a real external network call - the incident object may
    # already be sanitized (it always is, by the time Delivery 1 produced
    # it), but this is the one place a raw secret would actually leave the
    # host, so it gets its own explicit, local defense rather than trusting
    # an upstream caller's own diligence.
    lines = [
        f"severity: {redact_secrets(incident.severity)}",
        f"component: {redact_secrets(incident.component)}",
        f"symptom: {redact_secrets(incident.symptom)}",
        f"evidence references: {', '.join(redact_secrets(ref) for ref in incident.evidence_refs) or '(none)'}",
        f"detected at: {incident.detected_at}",
    ]
    return "Incident record:\n" + "\n".join(lines)


def diagnose_incident(
    incident: MaintenanceIncident,
    *,
    provider: AIProvider | None = None,
    provider_name: str = "anthropic",
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> DiagnosisResult:
    """Produces one real DiagnosisResult for one real incident, via
    WHATEVER provider is given. Pass `provider` directly to use any
    `AIProvider` (a fake in a test, a third vendor, a local model) - the
    `provider_name`/`api_key` pair is only the convenience path for one
    of the two built-in providers. Raises a distinct `DiagnosisError`
    subclass for every real way this can fail - never returns a
    placeholder/empty result for a failure, since a silent fallback here
    would be indistinguishable from a genuine "nothing to add"
    diagnosis."""
    if provider is None:
        provider = resolve_provider(provider_name, api_key=api_key)
    resolved_name = getattr(provider, "name", provider_name)
    resolved_model = model or DEFAULT_MODELS.get(resolved_name)
    if not resolved_model:
        raise DiagnosisError(
            f"no default model known for provider {resolved_name!r} - pass `model` explicitly"
        )

    prompt = _build_prompt(incident)
    try:
        explanation = provider.complete(system_prompt=_SYSTEM_PROMPT, user_prompt=prompt, model=resolved_model, max_tokens=max_tokens)
    except DiagnosisError:
        raise
    except Exception as exc:  # a caller-supplied provider that does not itself raise DiagnosisError subclasses
        raise ProviderRequestError(f"the request to the AI provider failed: {exc}") from exc

    return DiagnosisResult(
        incident_id=incident.incident_id,
        correlation_id=incident.correlation_id,
        provider=resolved_name,
        model=resolved_model,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        explanation=explanation,
    )
