# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/notify.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Notifications without a voice service: incident events published to the MQTT broker of the ecosystem.

An event is an `EventEnvelope` of the ecosystem contract (`schema_version`, `event_id`, `type`, `source`,
`timestamp_utc`, `sequence`, `correlation_id`) plus the fields of the incident (redacted again here, the last
place before they leave the process) and a sentence in the configured language. It goes to
`<topic_prefix>/<node>`, where the mobile apps and the watch already listen for events.

The publisher is a plain MQTT 3.1.1 client (CONNECT, PUBLISH with QoS 0 or 1, DISCONNECT) with no dependency.
Broker credentials come from the environment variables the configuration names, never from a file. When the
broker cannot be reached the event is appended to an outbox file and sent by the next `flush_outbox()`, so a
broker restart does not lose the incident that was open during it.
"""
from __future__ import annotations

import json
import socket
import ssl
import struct
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ._atomic import atomic_write_text, exclusive_lock
from .config import SEVERITIES, NotifyConfig
from .incident_store import TrackedIncident
from .log_redaction import redact_secrets
from .messages import translate


class NotifyError(RuntimeError):
    """The broker refused or did not answer."""


class Publisher(Protocol):
    def publish(self, topic: str, payload: bytes, qos: int) -> None: ...


def _utf8(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def _remaining_length(size: int) -> bytes:
    out = bytearray()
    while True:
        digit, size = size % 128, size // 128
        out.append(digit | (0x80 if size else 0))
        if not size:
            return bytes(out)


def _read_exact(sock: socket.socket, count: int) -> bytes:
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise NotifyError("the broker closed the connection")
        data += chunk
    return data


class MqttPublisher:
    """One connection per publish: events are rare, and a connection that is not kept cannot go stale."""

    def __init__(self, host: str, port: int, *, tls: bool = False, username: str | None = None, password: str | None = None,
                 timeout_s: float = 5.0, client_id: str | None = None) -> None:
        self.host, self.port, self.tls = host, port, tls
        self.username, self.password = username, password
        self.timeout_s = timeout_s
        self.client_id = client_id or f"ops-agent-{uuid.uuid4().hex[:8]}"

    def publish(self, topic: str, payload: bytes, qos: int) -> None:
        if qos not in (0, 1):
            raise NotifyError("only QoS 0 and 1 are supported")
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout_s) as raw:
                sock: socket.socket = raw
                if self.tls:
                    context = ssl.create_default_context()
                    context.minimum_version = ssl.TLSVersion.TLSv1_2
                    sock = context.wrap_socket(raw, server_hostname=self.host)
                sock.settimeout(self.timeout_s)
                flags = 0x02 | (0x80 if self.username else 0) | (0x40 if self.username and self.password else 0)
                body = _utf8("MQTT") + bytes([4, flags]) + struct.pack(">H", 30) + _utf8(self.client_id)
                if self.username:
                    body += _utf8(self.username) + (_utf8(self.password) if self.password else b"")
                sock.sendall(bytes([0x10]) + _remaining_length(len(body)) + body)
                connack = _read_exact(sock, 4)
                if connack[0] != 0x20 or connack[3] != 0:
                    raise NotifyError(f"the broker refused the connection (code {connack[3]})")
                packet_id = 1
                variable = _utf8(topic) + (struct.pack(">H", packet_id) if qos else b"")
                sock.sendall(bytes([0x30 | (qos << 1)]) + _remaining_length(len(variable) + len(payload)) + variable + payload)
                if qos:
                    puback = _read_exact(sock, 4)
                    if puback[0] != 0x40 or struct.unpack(">H", puback[2:4])[0] != packet_id:
                        raise NotifyError("the broker did not acknowledge the event")
                sock.sendall(bytes([0xE0, 0x00]))
        except (OSError, ssl.SSLError, TimeoutError) as exc:
            raise NotifyError(f"cannot publish to {self.host}:{self.port}: {exc.__class__.__name__}") from exc


class Notifier:
    def __init__(self, config: NotifyConfig, publisher: Publisher, *, clock: Any = None) -> None:
        self.config = config
        self.publisher = publisher
        self._sequence = int(time.time())
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def topic_for(self, node: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in node) or "unknown"
        return f"{self.config.topic_prefix.rstrip('/')}/{safe}"

    def build_event(self, kind: str, tracked: TrackedIncident) -> dict[str, Any]:
        """`kind`: opened, updated or resolved."""
        incident = tracked.incident
        self._sequence += 1
        component = redact_secrets(incident.component)
        return {
            "schema_version": "1.0",
            "event_id": str(uuid.uuid4()),
            "type": f"ops.incident.{kind}",
            "source": self.config.source,
            "timestamp_utc": self._clock().isoformat(timespec="seconds"),
            "sequence": self._sequence,
            "correlation_id": incident.correlation_id,
            "node": incident.source_node,
            "incidentId": incident.incident_id,
            "severity": incident.severity,
            "component": component,
            "symptom": redact_secrets(incident.symptom),
            "occurrenceCount": tracked.occurrence_count,
            "language": self.config.language,
            "message": translate(f"incident.{kind}", self.config.language,
                                 severity=incident.severity, node=incident.source_node, component=component),
        }

    def wanted(self, kind: str, tracked: TrackedIncident) -> bool:
        """Resolutions always go out (a person who was told about the problem is told it is over); the rest by severity."""
        if kind == "resolved":
            return True
        return SEVERITIES.index(tracked.incident.severity) >= SEVERITIES.index(self.config.min_severity) if tracked.incident.severity in SEVERITIES else True

    def send(self, event: dict[str, Any]) -> bool:
        """Publishes, or queues in the outbox when the broker cannot be reached. True: published now."""
        topic = self.topic_for(str(event.get("node", "")))
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
        try:
            self.publisher.publish(topic, payload, self.config.qos)
            return True
        except NotifyError:
            if self.config.outbox_file:
                self._queue(topic, event)
            return False

    def _queue(self, topic: str, event: dict[str, Any]) -> None:
        path = Path(self.config.outbox_file or "")
        with exclusive_lock(path):
            lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
            lines.append(json.dumps({"topic": topic, "event": event}, ensure_ascii=False))
            atomic_write_text(path, "\n".join(lines[-1000:]) + "\n")

    def flush_outbox(self) -> int:
        """Sends what the outbox holds, oldest first, stopping at the first failure. Returns how many went out."""
        if not self.config.outbox_file or not Path(self.config.outbox_file).is_file():
            return 0
        path = Path(self.config.outbox_file)
        sent = 0
        with exclusive_lock(path):
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            remaining = list(lines)
            for line in lines:
                try:
                    entry = json.loads(line)
                    self.publisher.publish(entry["topic"], json.dumps(entry["event"], ensure_ascii=False).encode("utf-8"), self.config.qos)
                except (NotifyError, ValueError, KeyError):
                    break
                remaining.remove(line)
                sent += 1
            atomic_write_text(path, "".join(f"{line}\n" for line in remaining))
        return sent

    def notify_changes(self, before: list[TrackedIncident], after: list[TrackedIncident]) -> int:
        """Events for what changed between two states of the store: new open incidents, and those that closed. Returns how many were published."""
        was_open = {item.incident.incident_id for item in before if item.resolved_at is None}
        was_closed = {item.incident.incident_id for item in before if item.resolved_at is not None}
        published = 0
        for item in after:
            incident_id = item.incident.incident_id
            if item.resolved_at is None and incident_id not in was_open:
                kind = "opened"
            elif item.resolved_at is not None and incident_id not in was_closed and incident_id in was_open:
                kind = "resolved"
            else:
                continue
            if self.wanted(kind, item) and self.send(self.build_event(kind, item)):
                published += 1
        return published
