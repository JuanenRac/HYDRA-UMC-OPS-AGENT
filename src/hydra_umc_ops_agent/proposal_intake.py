# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/proposal_intake.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Incident proposals from the node watchdog: a subscriber of the broker that turns them into incidents to review.

The watchdog publishes, after a node has stayed in a failing state for a time written in its configuration, ONE
proposal of a maintenance incident on `<prefix>/<node>/incident-proposal` (not retained). It is only a proposal:
this module decides whether to believe it. Everything that arrives is untrusted:

* a payload over the configured size, a message that is not a JSON object, one with another `schema_version`, a
  missing or ill-typed field, a severity or label outside what the contract accepts is refused with a named reason;
* a RETAINED message is ignored (a proposal is an event, a stale retained one must not open an incident again);
* the topic names the node, and the node inside the payload must be that node, so a client of the broker cannot
  speak for another one; when `allowed_nodes` is set, any other node is refused;
* at most `max_per_minute` messages are looked at, the rest are counted and dropped;
* the severity can never be above `severity_cap`, and every text is redacted again before it is stored.

An accepted proposal becomes (or updates) the open incident of that node in the same durable store the watchdog
bridge uses, under the same component, so the `HEALTHY` transition that `edge healing-ingest` reads closes it. It
is marked `requestedBy = node-healing:proposal`; nothing is deployed, changed or stopped by it.

The subscriber is a plain MQTT 3.1.1 client (CONNECT, SUBSCRIBE at QoS 0 or 1, PUBACK, PINGREQ) with no dependency.
"""
from __future__ import annotations

import json
import re
import socket
import ssl
import struct
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from ._atomic import exclusive_lock
from .config import SEVERITIES, ProposalsConfig
from .healing_bridge import COMPONENT_PREFIX
from .incident import REDACTION_LEVEL_SANITIZED, MaintenanceIncident
from .incident_store import IncidentStoreError, load_incident_store, reconcile_incidents, save_incident_store
from .log_redaction import redact_secrets
from .notify import NotifyError, _read_exact, _remaining_length, _utf8

SCHEMA_VERSION = "1.0"
REQUESTED_BY = "node-healing:proposal"
LABEL = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
MAX_SYMPTOM = 2000
MAX_COMPONENT = 500
MAX_REFS = 20
KEEPALIVE_SECONDS = 30


class ProposalRefused(ValueError):
    """The message is not an acceptable proposal; the text is the named reason (never the payload itself)."""


def topic_matches(topic_filter: str, topic: str) -> bool:
    """MQTT topic filter matching with `+` and a trailing `#`."""
    wanted, got = topic_filter.split("/"), topic.split("/")
    for index, part in enumerate(wanted):
        if part == "#":
            return index == len(wanted) - 1
        if index >= len(got) or (part != "+" and part != got[index]):
            return False
    return len(wanted) == len(got)


def node_of_topic(topic_filter: str, topic: str) -> str | None:
    """The topic segment that stands where the filter has its first `+` (the node), or None."""
    if not topic_matches(topic_filter, topic):
        return None
    wanted, got = topic_filter.split("/"), topic.split("/")
    for index, part in enumerate(wanted):
        if part == "+":
            return got[index]
    return None


def _text(data: dict, key: str, limit: int, *, pattern: re.Pattern | None = None) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ProposalRefused(f"field-{key}")
    if pattern is not None and not pattern.match(value):
        raise ProposalRefused(f"field-{key}")
    return value


def _segment(name: str) -> str:
    """The same rule the watchdog applies to a node name when it builds the topic."""
    cleaned = re.sub(r"[^A-Za-z0-9._:-]", "_", name)
    return cleaned or "_"


def parse_proposal(topic: str, payload: bytes, config: ProposalsConfig) -> MaintenanceIncident:
    """The incident a proposal describes, or `ProposalRefused` with the reason."""
    node = node_of_topic(config.topic_filter, topic)
    if node is None:
        raise ProposalRefused("topic")
    if len(payload) > config.max_payload_bytes:
        raise ProposalRefused("too-large")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ProposalRefused("not-json") from None
    if not isinstance(data, dict):
        raise ProposalRefused("not-an-object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ProposalRefused("schema-version")
    source = _text(data, "sourceNode", 64, pattern=LABEL)
    if _segment(source) != node and source != node:
        raise ProposalRefused("node-mismatch")
    allowed = {item.strip() for item in (config.allowed_nodes or "").split(",") if item.strip()}
    if allowed and source not in allowed and node not in allowed:
        raise ProposalRefused("node-not-allowed")
    incident_id = _text(data, "incidentId", 64, pattern=LABEL)
    correlation_id = _text(data, "correlationId", 64, pattern=LABEL)
    detected_at = _text(data, "detectedAt", 40)
    try:
        datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
    except ValueError:
        raise ProposalRefused("field-detectedAt") from None
    severity = _text(data, "severity", 16)
    if severity not in SEVERITIES:
        raise ProposalRefused("field-severity")
    if SEVERITIES.index(severity) > SEVERITIES.index(config.severity_cap):
        severity = config.severity_cap
    symptom = _text(data, "symptom", MAX_SYMPTOM)
    component = _text(data, "component", MAX_COMPONENT)
    refs = data.get("evidenceRefs", [])
    if not isinstance(refs, list) or len(refs) > MAX_REFS or not all(isinstance(ref, str) and len(ref) <= MAX_COMPONENT for ref in refs):
        raise ProposalRefused("field-evidenceRefs")
    return MaintenanceIncident(
        incident_id=incident_id, source_node=source, detected_at=detected_at, severity=severity,
        component=f"{COMPONENT_PREFIX}{source}",
        symptom=redact_secrets(f"proposal from the node watchdog: {symptom}"),
        evidence_refs=tuple(redact_secrets(ref) for ref in [f"proposal component: {component}", *refs]),
        redaction_level=REDACTION_LEVEL_SANITIZED, requested_by=REQUESTED_BY, correlation_id=correlation_id,
    )


@dataclass
class IntakeResult:
    received: int = 0
    accepted: int = 0
    refused: dict[str, int] = field(default_factory=dict)
    ignored_retained: int = 0
    rate_limited: int = 0

    def refuse(self, reason: str) -> None:
        self.refused[reason] = self.refused.get(reason, 0) + 1


class ProposalIntake:
    """Applies messages one at a time to the incident store, with the rate limit and the counters."""

    def __init__(self, config: ProposalsConfig, store_path: Path, *, notifier: object | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if not config.enabled:
            raise IncidentStoreError("the incident proposals are switched off in the configuration (proposals.enabled)")
        self.config, self.store_path, self.notifier, self.clock = config, store_path, notifier, clock
        self.result = IntakeResult()
        self._window: list[float] = []

    def _within_rate(self) -> bool:
        now = self.clock()
        self._window = [stamp for stamp in self._window if now - stamp < 60.0]
        if len(self._window) >= self.config.max_per_minute:
            return False
        self._window.append(now)
        return True

    def handle(self, topic: str, payload: bytes, *, retained: bool = False) -> bool:
        result = self.result
        result.received += 1
        if retained:
            result.ignored_retained += 1
            return False
        if not self._within_rate():
            result.rate_limited += 1
            return False
        try:
            incident = parse_proposal(topic, payload, self.config)
        except ProposalRefused as exc:
            result.refuse(str(exc))
            return False
        with exclusive_lock(self.store_path):
            before = load_incident_store(self.store_path)
            store = reconcile_incidents(before, [incident], set())
            save_incident_store(store, self.store_path)
        if self.notifier is not None:
            self.notifier.notify_changes(before, store)  # type: ignore[attr-defined]
        result.accepted += 1
        return True


class MqttSubscriber:
    """Listens for a limited time (or number of messages) and hands each PUBLISH to a callback."""

    def __init__(self, host: str, port: int, *, tls: bool = False, username: str | None = None,
                 password: str | None = None, timeout_s: float = 5.0, client_id: str | None = None) -> None:
        self.host, self.port, self.tls = host, port, tls
        self.username, self.password = username, password
        self.timeout_s = timeout_s
        self.client_id = client_id or f"ops-agent-sub-{uuid.uuid4().hex[:8]}"

    def listen(self, topic_filter: str, on_message: Callable[[str, bytes, bool], None], *, duration_s: float,
               max_messages: int, qos: int = 1) -> int:
        """Returns the number of messages delivered. Raises NotifyError when the broker cannot be used."""
        delivered = 0
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout_s) as raw:
                sock: socket.socket = raw
                if self.tls:
                    context = ssl.create_default_context()
                    context.minimum_version = ssl.TLSVersion.TLSv1_2
                    sock = context.wrap_socket(raw, server_hostname=self.host)
                flags = 0x02 | (0x80 if self.username else 0) | (0x40 if self.username and self.password else 0)
                body = _utf8("MQTT") + bytes([4, flags]) + struct.pack(">H", KEEPALIVE_SECONDS) + _utf8(self.client_id)
                if self.username:
                    body += _utf8(self.username) + (_utf8(self.password) if self.password else b"")
                sock.settimeout(self.timeout_s)
                sock.sendall(bytes([0x10]) + _remaining_length(len(body)) + body)
                connack = _read_exact(sock, 4)
                if connack[0] != 0x20 or connack[3] != 0:
                    raise NotifyError(f"the broker refused the connection (code {connack[3]})")
                sub = struct.pack(">H", 1) + _utf8(topic_filter) + bytes([qos])
                sock.sendall(bytes([0x82]) + _remaining_length(len(sub)) + sub)
                suback = self._read_packet(sock, wait_s=self.timeout_s)
                if suback is None or suback[0] >> 4 != 9 or suback[1][-1:] == b"\x80":
                    raise NotifyError("the broker refused the subscription")
                deadline = time.monotonic() + duration_s
                last_ping = time.monotonic()
                while delivered < max_messages:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    if time.monotonic() - last_ping > KEEPALIVE_SECONDS / 2:
                        sock.sendall(bytes([0xC0, 0x00]))
                        last_ping = time.monotonic()
                    packet = self._read_packet(sock, wait_s=min(remaining, 1.0))
                    if packet is None or packet[0] >> 4 != 3:
                        continue
                    first, data = packet
                    level, retained = (first >> 1) & 3, bool(first & 1)
                    size = struct.unpack(">H", data[:2])[0]
                    topic = data[2:2 + size].decode("utf-8", "replace")
                    cursor = 2 + size
                    if level:
                        sock.sendall(bytes([0x40, 0x02]) + data[cursor:cursor + 2])
                        cursor += 2
                    delivered += 1
                    on_message(topic, data[cursor:], retained)
                sock.sendall(bytes([0xE0, 0x00]))
        except (OSError, ssl.SSLError, TimeoutError) as exc:
            raise NotifyError(f"cannot listen to {self.host}:{self.port}: {exc.__class__.__name__}") from exc
        return delivered

    @staticmethod
    def _read_packet(sock: socket.socket, *, wait_s: float) -> tuple[int, bytes] | None:
        previous = sock.gettimeout()
        sock.settimeout(max(wait_s, 0.05))
        try:
            try:
                head = sock.recv(1)
            except (socket.timeout, TimeoutError):
                return None
            if not head:
                raise NotifyError("the broker closed the connection")
            sock.settimeout(previous or 5.0)
            size, shift = 0, 0
            while True:
                digit = _read_exact(sock, 1)[0]
                size |= (digit & 0x7F) << shift
                shift += 7
                if not digit & 0x80:
                    break
                if shift > 21:
                    raise NotifyError("malformed packet")
            return head[0], _read_exact(sock, size) if size else b""
        finally:
            sock.settimeout(previous)


def run_intake(config: ProposalsConfig, store_path: Path, subscriber: MqttSubscriber, *, notifier: object | None = None) -> IntakeResult:
    """Listens to the broker for `listen_seconds` (or `max_messages`) and applies what arrives."""
    intake = ProposalIntake(config, store_path, notifier=notifier)
    subscriber.listen(
        config.topic_filter, lambda topic, payload, retained: intake.handle(topic, payload, retained=retained),
        duration_s=config.listen_seconds, max_messages=config.max_messages,
    )
    return intake.result

