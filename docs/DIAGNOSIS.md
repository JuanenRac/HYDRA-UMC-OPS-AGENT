# Diagnosis (Delivery 2)

## What this is

`diagnose_incident()` (`src/hydra_umc_ops_agent/diagnosis.py`) sends ONE
already-collected, already-redacted `MaintenanceIncident` to an AI
provider and gets back a plain-text proposed root-cause explanation. It
is the second stage of this project's own real lifecycle:

```
evidence (Delivery 1) -> diagnosis (Delivery 2, this doc) -> human-approved
change (Delivery 3) -> canary deploy via HYDRA-UMC-UPDATER (Delivery 4)
-> verification (Delivery 5)
```

## What this is not

- **Not a decision.** `DiagnosisResult` carries its own `disclaimer`
  field verbatim in every serialized copy, saying exactly that: this is
  an AI-generated suggestion, not a decision, and nothing has been
  changed on any host because of it.
- **Not an action.** The system prompt this module sends explicitly
  instructs the model not to propose a specific fix, patch, or command -
  that is Delivery 3's own job, gated on human approval. `diagnose_incident()`
  never parses its own output back into anything executable; the result
  is inert display text for a person to read.
- **Not automatic.** Nothing in this codebase calls `diagnose_incident()`
  on its own. It only runs when an operator explicitly invokes
  `hydra-umc-ops-agent control diagnose`.

## Provider-agnostic by design

`diagnose_incident()` depends only on a minimal `AIProvider` Protocol -
one method, `complete(system_prompt, user_prompt, model, max_tokens) ->
str`. It is never locked to one AI vendor. Two real, concrete providers
ship out of the box:

| Provider | CLI value | Optional extra | Credential env var | Default model |
|---|---|---|---|---|
| Anthropic | `--provider anthropic` (default) | `pip install -e ".[ai-anthropic]"` | `ANTHROPIC_API_KEY` | `claude-sonnet-5` |
| OpenAI | `--provider openai` | `pip install -e ".[ai-openai]"` | `OPENAI_API_KEY` | `gpt-4o-mini` |

Each provider's own SDK is imported lazily, so every other part of this
project (`edge collect`, `control show`, and Delivery 2 itself when no
provider is actually invoked) keeps working with zero extra
dependencies installed. A credential is read ONLY from that provider's
own real environment variable, or an explicit `api_key` argument for a
caller that already has one in memory - never from a CLI flag (it would
land in shell history) and never from a file inside this repository.

A caller with a third vendor, or a local model server, can pass any
object implementing `AIProvider` directly as `diagnose_incident(...,
provider=my_own_provider)` - this module never needs to know it exists,
and `provider_name`/the two built-ins above are only the convenience
path.

## The real seam this module is tested against

Every real test in `tests/test_diagnosis.py` injects a fake object
implementing the one-method `AIProvider` Protocol - the test suite never
needs the real `anthropic`/`openai` package installed, a real API key,
or a real network call to pass. This mirrors the same lazy-import /
injectable-seam pattern this ecosystem already uses for other optional
real SDKs (e.g. VISION-STREAMER's own `hailo_runtime.py` for HailoRT).

## Redaction: defense in depth

`MaintenanceIncident.to_dict()` already redacts `symptom` once. This
module redacts every field it places in the outbound prompt AGAIN,
independently, immediately before that prompt is sent - see
`_build_prompt()`. This is deliberate: sending sanitized evidence to a
third-party AI provider is the one genuinely new secret-exfiltration
surface Delivery 2 introduces, so it gets its own explicit, local check
rather than trusting that every upstream caller was diligent.

## Real, honest limits of this delivery

- No real end-to-end call against a live Anthropic or OpenAI API has
  been exercised during this project's own development (no API key was
  available in that session) - the request-construction, response-
  parsing, and every failure/degradation path (missing key, package not
  installed, provider error, malformed response) ARE real and tested
  against a fake provider, but a live call is still a real, separate
  verification an operator with a key should do once.
- There is no retry/backoff around the real provider call - a
  transient failure surfaces immediately as `ProviderRequestError`
  rather than being silently retried. Given this delivery's own
  low-frequency, human-triggered usage pattern (one incident, one
  explicit CLI invocation), that is an acceptable, honest simplification
  for now rather than an oversight.
- No caching exists - re-running `control diagnose` on the same
  incident makes a new real API call every time.
