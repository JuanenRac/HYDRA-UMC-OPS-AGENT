# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/config.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The configuration file of the agent: every tunable value and every switch lives here, never in the code.

Everything that reaches beyond the local collect/propose/approve/deploy flow is OFF until the file turns it
on: the authenticated transport, the bridge from the node watchdog, the notification to the broker, the
multi-node canary, the model that drafts a diff and the metrics endpoint. A missing file means "all off with
the conservative defaults"; a malformed file raises, because half a configuration must not switch half a
feature on.

The file holds no secret. It names the files (the node registry with the shared secrets, the approvers) and the
environment variables (broker credentials, the metrics token, the model key) that do; those live outside any
repository. See `deploy/ops-agent.json.example`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

CONFIG_ENV = "OPS_AGENT_CONFIG"
DEFAULT_CONFIG_FILE = "/etc/hydra-umc/ops-agent.json"

SEVERITIES = ("info", "warning", "critical")
LANGUAGES = ("en", "es", "de", "fr", "it", "ja", "zh", "pt")


class ConfigError(ValueError):
    """The configuration file is malformed or holds a value outside its allowed range."""


@dataclass(frozen=True)
class TransportConfig:
    """The authenticated edge <-> control channel (`edge serve`, `control ... --remote`)."""

    enabled: bool = False
    bind: str = "127.0.0.1"
    port: int = 18310
    # Refused unless this is true: the channel is signed but not encrypted, so leaving the loopback is a decision.
    allow_non_loopback: bool = False
    registry_file: str | None = None
    state_file: str | None = None
    replay_window_seconds: int = 120
    max_messages_per_minute: int = 60
    max_body_bytes: int = 1_048_576
    request_timeout_seconds: float = 10.0
    tls_cert_file: str | None = None
    tls_key_file: str | None = None
    # A remote deploy still needs a person's Ed25519 approval inside the proposal; this only lets the edge try.
    allow_remote_deploy: bool = False
    approvers_file: str | None = None
    policy_file: str | None = None
    build_timeout_seconds: float = 600.0


@dataclass(frozen=True)
class HealingConfig:
    """The bridge from the node watchdog's transitions to incidents."""

    enabled: bool = False
    journal_file: str | None = None
    state_file: str | None = None
    trigger_statuses: tuple[str, ...] = ("UNREACHABLE", "INVALID")
    resolve_statuses: tuple[str, ...] = ("HEALTHY",)
    severity: str = "critical"


@dataclass(frozen=True)
class NotifyConfig:
    """Incident events published to the broker of the ecosystem."""

    enabled: bool = False
    broker_host: str = "127.0.0.1"
    broker_port: int = 1883
    tls: bool = False
    username_env: str | None = None
    password_env: str | None = None
    topic_prefix: str = "hydra/ops/incidents"
    qos: int = 1
    language: str = "en"
    min_severity: str = "warning"
    outbox_file: str | None = None
    timeout_seconds: float = 5.0
    source: str = "hydra-umc-ops-agent"


@dataclass(frozen=True)
class ProposalsConfig:
    """Incident proposals that the node watchdog publishes to the broker, turned into incidents for a person to review."""

    enabled: bool = False
    broker_host: str = "127.0.0.1"
    broker_port: int = 1883
    tls: bool = False
    username_env: str | None = None
    password_env: str | None = None
    topic_filter: str = "hydra/health/+/incident-proposal"
    # Comma-separated node names that may propose; empty accepts any node the topic names.
    allowed_nodes: str | None = None
    max_payload_bytes: int = 16_384
    max_per_minute: int = 30
    max_messages: int = 100
    listen_seconds: float = 30.0
    timeout_seconds: float = 5.0
    severity_cap: str = "critical"
    # A proposal WAITS for a person (stored as pending, listed and approved or rejected on purpose). true opens it as an incident directly.
    auto_open: bool = False
    # Where the pending proposals are kept; none: next to the incident store, with the ending ".pending-proposals.json".
    pending_store: str | None = None
    max_pending: int = 200


@dataclass(frozen=True)
class MultiNodeConfig:
    """A canary that goes to a few nodes first, is observed, and only then goes on (or is undone)."""

    enabled: bool = False
    canary_nodes: int = 1
    wave_size: int = 0  # 0: every remaining node in one wave
    observe_seconds: float = 300.0
    poll_seconds: float = 10.0
    max_failed_probes: int = 1
    max_nodes: int = 20


@dataclass(frozen=True)
class LlmProposeConfig:
    """A model drafts the diff of a proposal. The draft is only a PENDING proposal; a person signs or rejects it."""

    enabled: bool = False
    endpoint: str = "http://127.0.0.1:11434/v1/chat/completions"
    model: str = ""
    allow_non_loopback: bool = False
    api_key_env: str | None = None
    timeout_seconds: float = 120.0
    max_tokens: int = 2048
    max_diff_bytes: int = 20_000
    max_files: int = 3
    max_changed_lines: int = 120


@dataclass(frozen=True)
class MetricsConfig:
    """Prometheus/OpenMetrics text of the incident store and of the audit journal."""

    enabled: bool = False
    namespace: str = "hydra_ops_agent"
    include_audit: bool = True
    token_env: str | None = None


@dataclass(frozen=True)
class ScenarioIngestConfig:
    """Hands the before/after ScenarioOutcome of `control verify` (a manifest incident compared by commit, or the check of a live HTTP/systemd service) to HYDRA-UMC-SERVER (`POST /api/ingest/scenario-outcome`).

    The credential is a file: the token the SERVER issued (`token_file`), or an account (`username` and the password in `password_file`).
    The SERVER keeps this feed off (404) until its own switch HYDRA_UMC_INGEST_SCENARIO is 1.
    """

    enabled: bool = False
    server_url: str | None = None
    token_file: str | None = None
    username: str | None = None
    password_file: str | None = None
    timeout_seconds: float = 5.0
    # The credential only goes over HTTPS or to this machine; a bench that needs plain HTTP says so.
    allow_plain_http: bool = False


@dataclass(frozen=True)
class EvidenceBundleConfig:
    """`control evidence-bundle` builds the EvidenceBundle of an incident (versions, manifests, redacted log excerpts, steps, impact, checksum) as a file for a development node.

    It only writes a file; nothing is sent. Off until switched on.
    """

    enabled: bool = False
    # true: `control propose-from-diagnosis` also writes the bundle of the incident next to the proposal (needs `enabled`).
    with_proposal: bool = False
    # Lines kept from the end of every log file given to the command.
    max_log_lines: int = 200
    # Characters kept from every manifest given to the command.
    max_manifest_chars: int = 20000


@dataclass(frozen=True)
class ContractsConfig:
    """What happens when a snapshot or a change proposal read from a file does not match the closed schema of the shared SDK: `off`, `warn` (says it and goes on) or `strict` (refuses the file)."""

    validate: str = "off"


@dataclass(frozen=True)
class HostChecksConfig:
    """What the machine says about itself, added to `edge collect`: free disk space, temperature, throttling (`vcgencmd` on a Raspberry Pi) and the backups on disk.

    A reading the machine cannot give (no thermal zone, no `vcgencmd`) is reported as unavailable and never becomes an incident.
    """

    enabled: bool = False
    # Comma-separated folders; the volume of each one is measured.
    disk_paths: str = "/"
    disk_warn_free_percent: float = 15.0
    disk_critical_free_percent: float = 5.0
    temperature_warn_celsius: float = 75.0
    temperature_critical_celsius: float = 82.0
    check_throttling: bool = True
    vcgencmd_timeout_seconds: float = 3.0
    # The folder that holds the backups (for example the output of cm5_recovery.sh); none: backups are not checked.
    backup_dir: str | None = None
    backup_pattern: str = "*"
    backup_min_count: int = 1
    # An incident when the newest backup is older than this many days; 0 switches the age check off.
    backup_max_age_days: float = 8.0


@dataclass(frozen=True)
class AgentConfig:
    transport: TransportConfig = field(default_factory=TransportConfig)
    healing: HealingConfig = field(default_factory=HealingConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    proposals: ProposalsConfig = field(default_factory=ProposalsConfig)
    multinode: MultiNodeConfig = field(default_factory=MultiNodeConfig)
    llm_propose: LlmProposeConfig = field(default_factory=LlmProposeConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    host_checks: HostChecksConfig = field(default_factory=HostChecksConfig)
    scenario_ingest: ScenarioIngestConfig = field(default_factory=ScenarioIngestConfig)
    evidence_bundle: EvidenceBundleConfig = field(default_factory=EvidenceBundleConfig)
    contracts: ContractsConfig = field(default_factory=ContractsConfig)


# (minimum, maximum) of every number; anything outside raises.
_RANGES: dict[str, tuple[float, float]] = {
    "port": (1, 65535), "broker_port": (1, 65535),
    "replay_window_seconds": (1, 3600), "max_messages_per_minute": (1, 6000),
    "max_body_bytes": (1024, 64 * 1024 * 1024), "request_timeout_seconds": (0.1, 600),
    "build_timeout_seconds": (1, 86400), "qos": (0, 1), "timeout_seconds": (0.1, 600),
    "canary_nodes": (1, 100), "wave_size": (0, 100), "observe_seconds": (0, 86400),
    "poll_seconds": (0.05, 3600), "max_failed_probes": (1, 100), "max_nodes": (1, 500),
    "max_tokens": (64, 32768), "max_diff_bytes": (100, 1_000_000), "max_files": (1, 50),
    "max_changed_lines": (1, 5000),
    "max_payload_bytes": (256, 1_048_576), "max_per_minute": (1, 6000), "max_messages": (1, 10000),
    "listen_seconds": (0.1, 86400), "max_pending": (1, 10000),
    "max_log_lines": (1, 5000), "max_manifest_chars": (100, 1_000_000),
    "disk_warn_free_percent": (0, 100), "disk_critical_free_percent": (0, 100),
    "temperature_warn_celsius": (30, 120), "temperature_critical_celsius": (30, 120),
    "vcgencmd_timeout_seconds": (0.1, 60), "backup_min_count": (0, 10000), "backup_max_age_days": (0, 3650),
}
_CHOICES: dict[str, tuple[str, ...]] = {"severity": SEVERITIES, "min_severity": SEVERITIES, "severity_cap": SEVERITIES, "language": LANGUAGES}


def _build(section: str, cls: type, raw: object) -> Any:
    if raw is None:
        return cls()
    if not isinstance(raw, dict):
        raise ConfigError(f"'{section}' must be an object")
    known = {item.name: item for item in fields(cls)}
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise ConfigError(f"'{section}' has unknown key(s): {', '.join(unknown)}")
    default = cls()
    values: dict[str, Any] = {}
    for name, value in raw.items():
        reference = getattr(default, name)
        where = f"'{section}.{name}'"
        if isinstance(reference, bool):
            if not isinstance(value, bool):
                raise ConfigError(f"{where} must be true or false")
        elif isinstance(reference, tuple):
            if not isinstance(value, list) or not all(isinstance(part, str) and part for part in value):
                raise ConfigError(f"{where} must be a list of non-empty strings")
            value = tuple(part.upper() for part in value)
        elif isinstance(reference, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{where} must be a number")
            low, high = _RANGES.get(name, (float("-inf"), float("inf")))
            if not low <= value <= high:
                raise ConfigError(f"{where} must be between {low} and {high}")
            if isinstance(reference, int):
                if not float(value).is_integer():
                    raise ConfigError(f"{where} must be a whole number")
                value = int(value)
            else:
                value = float(value)
        else:  # a string, or a string-or-null
            if value is not None and not isinstance(value, str):
                raise ConfigError(f"{where} must be a string")
            if value is None and reference is not None:
                raise ConfigError(f"{where} must be a string")
            if isinstance(value, str) and not value.strip() and reference is not None and name != "model":
                raise ConfigError(f"{where} must not be empty")
        if name in _CHOICES and value not in _CHOICES[name]:
            raise ConfigError(f"{where} must be one of {', '.join(_CHOICES[name])}")
        values[name] = value
    return cls(**values)


def parse_config(raw: object) -> AgentConfig:
    if not isinstance(raw, dict):
        raise ConfigError("the configuration must be a JSON object")
    unknown = sorted(set(raw) - {item.name for item in fields(AgentConfig)})
    if unknown:
        raise ConfigError(f"unknown section(s): {', '.join(unknown)}")
    return AgentConfig(
        transport=_build("transport", TransportConfig, raw.get("transport")),
        healing=_build("healing", HealingConfig, raw.get("healing")),
        notify=_build("notify", NotifyConfig, raw.get("notify")),
        proposals=_build("proposals", ProposalsConfig, raw.get("proposals")),
        multinode=_build("multinode", MultiNodeConfig, raw.get("multinode")),
        llm_propose=_build("llm_propose", LlmProposeConfig, raw.get("llm_propose")),
        metrics=_build("metrics", MetricsConfig, raw.get("metrics")),
        host_checks=_check_host_checks(_build("host_checks", HostChecksConfig, raw.get("host_checks"))),
        scenario_ingest=_check_scenario_ingest(_build("scenario_ingest", ScenarioIngestConfig, raw.get("scenario_ingest"))),
        evidence_bundle=_build("evidence_bundle", EvidenceBundleConfig, raw.get("evidence_bundle")),
        contracts=_check_contracts(_build("contracts", ContractsConfig, raw.get("contracts"))),
    )


def _check_contracts(settings: ContractsConfig) -> ContractsConfig:
    if settings.validate not in ("off", "warn", "strict"):
        raise ConfigError("'contracts.validate' must be off, warn or strict")
    return settings


def _check_scenario_ingest(settings: ScenarioIngestConfig) -> ScenarioIngestConfig:
    """Switched on, it needs the address of the server and a credential."""
    if settings.enabled:
        if not settings.server_url:
            raise ConfigError("'scenario_ingest.server_url' is needed when 'scenario_ingest.enabled' is true")
        if not settings.token_file and not (settings.username and settings.password_file):
            raise ConfigError("'scenario_ingest' needs 'token_file', or 'username' and 'password_file'")
    return settings


def _check_host_checks(settings: HostChecksConfig) -> HostChecksConfig:
    """The critical thresholds must be stricter than the warning ones, or the warning could never be seen."""
    if settings.disk_critical_free_percent > settings.disk_warn_free_percent:
        raise ConfigError("'host_checks.disk_critical_free_percent' must not be above 'host_checks.disk_warn_free_percent'")
    if settings.temperature_critical_celsius < settings.temperature_warn_celsius:
        raise ConfigError("'host_checks.temperature_critical_celsius' must not be below 'host_checks.temperature_warn_celsius'")
    if not [part for part in settings.disk_paths.split(",") if part.strip()]:
        raise ConfigError("'host_checks.disk_paths' must name at least one folder")
    return settings


def load_config(path: Path | None) -> AgentConfig:
    """`path` None or missing: everything off. A file that exists but cannot be read or parsed raises."""
    if path is None or not path.is_file():
        return AgentConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read the configuration {path}: {exc.__class__.__name__}") from exc
    return parse_config(raw)
