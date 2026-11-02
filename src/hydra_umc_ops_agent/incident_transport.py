# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/incident_transport.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""An authenticated channel between the edge role (a CM5) and the control role (a development host).

Every message is signed with the shared secret of the node that sends it (HMAC-SHA256 over a canonical JSON
body) and carries a nonce, a timestamp and a contract version, in the same wire format as the incident
transport of the development server (`incident-transport/1`). The receiver refuses, each with a named code:
an unregistered node (`unknown-identity`), a node speaking as another (`impersonation`), a message for someone
else (`wrong-recipient`), an incompatible version (`incompatible-version`), a wrong signature (`bad-signature`),
a timestamp outside the window (`stale`), a repeated nonce (`replay`) and too many messages a minute
(`overloaded`). The nonce and rate state lives in a SQLite file, so it holds across processes and restarts.

What travels is what the edge already produces and the control already consumes: a snapshot (`snapshot`), the
re-check of one incident (`verify`), a health probe (`health`) and, only when the edge was told to allow it, a
deploy of a proposal and the rollback of one (`deploy`, `rollback`). A deploy over the channel does not widen
what a deploy can do: the proposal still carries a person's Ed25519 approval, which the edge verifies against its
own registry of approvers, and the build-test command is the one its own policy file lists for the project.

The shared secrets are in a registry file that is never part of a repository. The channel is signed, not
encrypted: it listens on the loopback unless the configuration allows another address, and it can be wrapped in
TLS with a certificate and key named in the configuration (or tunnelled through SSH).
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import math
import secrets
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import TransportConfig

CONTRACT_VERSION = "incident-transport/1"

KIND_INCIDENT = "incident"
KIND_DIAGNOSIS = "diagnosis"
KIND_DEPLOY_VERIFICATION = "deploy-verification"
KIND_ACK = "ack"
KINDS = (KIND_INCIDENT, KIND_DIAGNOSIS, KIND_DEPLOY_VERIFICATION, KIND_ACK)

#: Which kind carries which operation of the edge.
OPERATION_KIND = {
    "snapshot": KIND_INCIDENT,
    "verify": KIND_DEPLOY_VERIFICATION,
    "health": KIND_DEPLOY_VERIFICATION,
    "deploy": KIND_DEPLOY_VERIFICATION,
    "rollback": KIND_DEPLOY_VERIFICATION,
}

NODE_HEADER = "X-Ops-Node"
MIN_SECRET_LENGTH = 16


class TransportError(RuntimeError):
    """A message was refused or could not be delivered; `code` names why."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


def compatible(version: str) -> bool:
    return version == CONTRACT_VERSION or version.startswith("incident-transport/1.")


# ---------------------------------------------------------------------------
# Registry and message
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NodeRegistry:
    """node id -> shared secret."""

    secrets: dict[str, str] = field(default_factory=dict)

    def is_registered(self, node_id: str) -> bool:
        return node_id in self.secrets

    def secret_for(self, node_id: str) -> str | None:
        return self.secrets.get(node_id)


def load_registry(path: Path) -> NodeRegistry:
    """`{"nodes": {"<node id>": "<secret of at least 16 characters>"}}`; anything else raises."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TransportError("registry-unreadable", f"cannot read the node registry {path}: {exc.__class__.__name__}") from exc
    nodes = raw.get("nodes") if isinstance(raw, dict) else None
    if not isinstance(nodes, dict) or not nodes:
        raise TransportError("registry-invalid", 'the node registry must be an object with a non-empty "nodes" object')
    for node_id, secret in nodes.items():
        if not isinstance(node_id, str) or not node_id or not isinstance(secret, str) or len(secret) < MIN_SECRET_LENGTH:
            raise TransportError("registry-invalid", f"the secret of node {node_id!r} must be a string of at least {MIN_SECRET_LENGTH} characters")
    return NodeRegistry(secrets=dict(nodes))


@dataclass(frozen=True)
class IncidentMessage:
    message_id: str
    from_node: str
    to_node: str
    kind: str
    contract_version: str
    nonce: str
    sent_at: float
    payload: dict[str, Any]
    mac: str = ""

    def to_dict(self, *, include_mac: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "message_id": self.message_id, "from_node": self.from_node, "to_node": self.to_node, "kind": self.kind,
            "contract_version": self.contract_version, "nonce": self.nonce, "sent_at": self.sent_at, "payload": self.payload,
        }
        if include_mac:
            data["mac"] = self.mac
        return data

    def _signing_bytes(self) -> bytes:
        return json.dumps(self.to_dict(include_mac=False), sort_keys=True, separators=(",", ":")).encode("utf-8")

    def signed(self, secret: str) -> "IncidentMessage":
        mac = hmac.new(secret.encode("utf-8"), self._signing_bytes(), hashlib.sha256).hexdigest()
        return IncidentMessage(**{**self.to_dict(include_mac=False), "mac": mac})

    @staticmethod
    def from_dict(data: object) -> "IncidentMessage":
        if not isinstance(data, dict):
            raise TransportError("malformed", "a message must be a JSON object")
        texts: dict[str, str] = {}
        for name in ("message_id", "from_node", "to_node", "kind", "contract_version", "nonce"):
            value = data.get(name)
            if not isinstance(value, str) or not value:
                raise TransportError("malformed", f"'{name}' must be a non-empty string")
            texts[name] = value
        if texts["kind"] not in KINDS:
            raise TransportError("malformed", f"'kind' must be one of {KINDS}")
        sent_at = data.get("sent_at")
        if isinstance(sent_at, bool) or not isinstance(sent_at, (int, float)):
            raise TransportError("malformed", "'sent_at' must be a number (unix seconds)")
        payload = data.get("payload", {})
        mac = data.get("mac", "")
        if not isinstance(payload, dict) or not isinstance(mac, str):
            raise TransportError("malformed", "'payload' must be an object and 'mac' a string")
        return IncidentMessage(sent_at=float(sent_at), payload=payload, mac=mac, **texts)


def new_message(from_node: str, to_node: str, kind: str, payload: dict[str, Any], *, now: float | None = None) -> IncidentMessage:
    return IncidentMessage(
        message_id=secrets.token_hex(8), from_node=from_node, to_node=to_node, kind=kind, contract_version=CONTRACT_VERSION,
        nonce=secrets.token_hex(16), sent_at=time.time() if now is None else now, payload=payload,
    )


# ---------------------------------------------------------------------------
# Verification state and the check itself
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TransportPolicy:
    replay_window_seconds: int = 120
    max_messages_per_minute: int = 60

    @staticmethod
    def from_config(config: TransportConfig) -> "TransportPolicy":
        return TransportPolicy(config.replay_window_seconds, config.max_messages_per_minute)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    code: str | None = None
    reason: str | None = None


class VerifierState:
    """Nonces already seen and the per-node message times, in memory."""

    def __init__(self) -> None:
        self.nonce_times: dict[str, float] = {}
        self.rate_log: dict[str, list[float]] = {}
        self._lock = threading.RLock()

    @contextlib.contextmanager
    def exclusive(self) -> Iterator[None]:
        with self._lock:
            yield

    def nonce_seen(self, nonce: str) -> bool:
        return nonce in self.nonce_times

    def messages_in_window(self, node: str, at: float, window: float = 60.0) -> int:
        recent = self.rate_log.setdefault(node, [])
        recent[:] = [moment for moment in recent if at - moment < window]
        return len(recent)

    def accept(self, node: str, nonce: str, at: float, replay_window: float) -> None:
        for old, seen_at in list(self.nonce_times.items()):
            if at - seen_at > replay_window:
                del self.nonce_times[old]
        self.nonce_times[nonce] = at
        self.rate_log.setdefault(node, []).append(at)


class SqliteVerifierState(VerifierState):
    """The same state in a SQLite file (WAL): shared by every process that opens it, kept across restarts. The
    check and the update of one message happen in one `BEGIN IMMEDIATE` transaction."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), isolation_level=None, timeout=10.0, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(
            "CREATE TABLE IF NOT EXISTS nonces (nonce TEXT PRIMARY KEY, at REAL NOT NULL);"
            "CREATE TABLE IF NOT EXISTS messages (node TEXT NOT NULL, at REAL NOT NULL);"
            "CREATE INDEX IF NOT EXISTS messages_by_node ON messages(node, at);"
        )

    def close(self) -> None:
        self._conn.close()

    @contextlib.contextmanager
    def exclusive(self) -> Iterator[None]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def nonce_seen(self, nonce: str) -> bool:
        return self._conn.execute("SELECT 1 FROM nonces WHERE nonce = ?", (nonce,)).fetchone() is not None

    def messages_in_window(self, node: str, at: float, window: float = 60.0) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM messages WHERE node = ? AND ? - at < ?", (node, at, window)).fetchone()
        return int(row[0])

    def accept(self, node: str, nonce: str, at: float, replay_window: float) -> None:
        self._conn.execute("DELETE FROM nonces WHERE ? - at > ?", (at, replay_window))
        self._conn.execute("DELETE FROM messages WHERE ? - at >= 60.0", (at,))
        self._conn.execute("INSERT INTO nonces(nonce, at) VALUES (?, ?)", (nonce, at))
        self._conn.execute("INSERT INTO messages(node, at) VALUES (?, ?)", (node, at))


def verify_message(
    message: IncidentMessage, registry: NodeRegistry, policy: TransportPolicy, state: VerifierState,
    *, authenticated_as: str, expected_to_node: str | None = None, now: float | None = None,
) -> VerifyResult:
    at = time.time() if now is None else now
    if not registry.is_registered(authenticated_as):
        return VerifyResult(False, "unknown-identity", f"{authenticated_as!r} is not a registered node")
    if message.from_node != authenticated_as:
        return VerifyResult(False, "impersonation", f"the message claims {message.from_node!r} but the channel is {authenticated_as!r}")
    if expected_to_node is not None and message.to_node != expected_to_node:
        return VerifyResult(False, "wrong-recipient", f"the message is for {message.to_node!r}, not {expected_to_node!r}")
    if not compatible(message.contract_version):
        return VerifyResult(False, "incompatible-version", f"{message.contract_version!r} is not compatible with {CONTRACT_VERSION!r}")
    expected = message.signed(registry.secret_for(authenticated_as) or "").mac
    if not message.mac or not hmac.compare_digest(message.mac, expected):
        return VerifyResult(False, "bad-signature", "the HMAC does not match the registered secret")
    if not math.isfinite(message.sent_at) or abs(at - message.sent_at) > policy.replay_window_seconds:
        return VerifyResult(False, "stale", f"sent_at is outside the {policy.replay_window_seconds}s window")
    with state.exclusive():
        if state.nonce_seen(message.nonce):
            return VerifyResult(False, "replay", "the nonce was already accepted")
        recent = state.messages_in_window(authenticated_as, at)
        if recent >= policy.max_messages_per_minute:
            return VerifyResult(False, "overloaded", f"{recent} messages in the last minute (limit {policy.max_messages_per_minute})")
        state.accept(authenticated_as, message.nonce, at, policy.replay_window_seconds)
    return VerifyResult(True)


# ---------------------------------------------------------------------------
# Edge side
# ---------------------------------------------------------------------------
Handler = Callable[[dict[str, Any]], dict[str, Any]]

_HTTP_STATUS = {
    "malformed": 400, "unknown-identity": 401, "bad-signature": 401, "impersonation": 403, "wrong-recipient": 403,
    "incompatible-version": 400, "stale": 400, "replay": 409, "overloaded": 429, "unknown-operation": 404,
    "operation-disabled": 403, "operation-failed": 500,
}


class EdgeService:
    """Receives a signed request and answers with a signed reply. Socket-free so it can be tested directly."""

    def __init__(self, node_name: str, registry: NodeRegistry, policy: TransportPolicy, state: VerifierState,
                 handlers: dict[str, Handler], *, clock: Callable[[], float] = time.time) -> None:
        if not registry.is_registered(node_name):
            raise TransportError("registry-invalid", f"this node ({node_name!r}) is not in the node registry")
        self.node_name = node_name
        self.registry = registry
        self.policy = policy
        self.state = state
        self.handlers = handlers
        self._clock = clock

    def _reply(self, to_node: str, ok: bool, payload: dict[str, Any], kind: str = KIND_ACK) -> dict[str, Any]:
        message = new_message(self.node_name, to_node, kind, {"ok": ok, **payload}, now=self._clock())
        return message.signed(self.registry.secret_for(self.node_name) or "").to_dict()

    def handle(self, raw: bytes, authenticated_as: str) -> tuple[int, dict[str, Any]]:
        try:
            message = IncidentMessage.from_dict(json.loads(raw.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            return 400, {"ok": False, "code": "malformed", "reason": "the body is not JSON"}
        except TransportError as exc:
            return 400, {"ok": False, "code": exc.code, "reason": exc.reason}
        verdict = verify_message(message, self.registry, self.policy, self.state, authenticated_as=authenticated_as,
                                 expected_to_node=self.node_name, now=self._clock())
        if not verdict.ok:
            code = verdict.code or "bad-signature"
            return _HTTP_STATUS.get(code, 400), {"ok": False, "code": code, "reason": verdict.reason}
        operation = message.payload.get("op")
        handler = self.handlers.get(operation) if isinstance(operation, str) else None
        if handler is None:
            known = ", ".join(sorted(self.handlers)) or "none"
            return 404, self._reply(message.from_node, False, {"code": "unknown-operation", "reason": f"operation {operation!r} is not offered (offered: {known})"})
        try:
            result = handler(message.payload)
        except TransportError as exc:
            return _HTTP_STATUS.get(exc.code, 500), self._reply(message.from_node, False, {"code": exc.code, "reason": exc.reason})
        except Exception as exc:  # noqa: BLE001 - one failed operation must not stop the service
            return 500, self._reply(message.from_node, False, {"code": "operation-failed", "reason": f"{exc.__class__.__name__}: {str(exc)[:300]}"})
        return 200, self._reply(message.from_node, True, {"op": operation, "result": result}, kind=OPERATION_KIND.get(str(operation), KIND_ACK))


def _is_loopback(address: str) -> bool:
    return address in ("127.0.0.1", "::1", "localhost")


def make_server(service: EdgeService, config: TransportConfig, *, metrics: Callable[[], str] | None = None,
                metrics_token: str | None = None) -> ThreadingHTTPServer:
    """Builds the HTTP server (not started). Refuses to listen outside the loopback unless the configuration allows it."""
    if not config.enabled:
        raise TransportError("operation-disabled", "the transport is switched off in the configuration (transport.enabled)")
    if not _is_loopback(config.bind) and not config.allow_non_loopback:
        raise TransportError("operation-disabled", f"{config.bind!r} is not a loopback address; set transport.allow_non_loopback to listen there")
    if (config.tls_cert_file is None) != (config.tls_key_file is None):
        raise TransportError("registry-invalid", "transport.tls_cert_file and transport.tls_key_file go together")

    class Handler_(BaseHTTPRequestHandler):
        server_version = "ops-agent"
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - the signature of the base class
            return

        def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/message":
                self._send(404, b'{"ok":false,"code":"not-found"}')
                return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                length = -1
            if length < 0 or length > config.max_body_bytes:
                self._send(413, b'{"ok":false,"code":"malformed","reason":"missing or too large body"}')
                return
            raw = self.rfile.read(length)
            status, answer = service.handle(raw, self.headers.get(NODE_HEADER, ""))
            self._send(status, json.dumps(answer).encode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/metrics" or metrics is None:
                self._send(404, b'{"ok":false,"code":"not-found"}')
                return
            if metrics_token is not None and not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {metrics_token}"):
                self._send(401, b'{"ok":false,"code":"unauthorized"}')
                return
            self._send(200, metrics().encode("utf-8"), "text/plain; version=0.0.4; charset=utf-8")

    server = ThreadingHTTPServer((config.bind, config.port), Handler_)
    server.daemon_threads = True
    if config.tls_cert_file and config.tls_key_file:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(config.tls_cert_file, config.tls_key_file)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


# ---------------------------------------------------------------------------
# Control side
# ---------------------------------------------------------------------------
class RemoteNode:
    """One edge node as the control role sees it: sends signed requests, accepts only signed, fresh, addressed replies."""

    def __init__(self, name: str, url: str, local_node: str, registry: NodeRegistry, *, policy: TransportPolicy | None = None,
                 timeout_s: float = 10.0, opener: Callable[..., Any] | None = None, clock: Callable[[], float] = time.time) -> None:
        for node in (name, local_node):
            if not registry.is_registered(node):
                raise TransportError("unknown-identity", f"{node!r} is not in the node registry")
        self.name = name
        self.url = url.rstrip("/")
        self.local_node = local_node
        self.registry = registry
        self.policy = policy or TransportPolicy()
        self.timeout_s = timeout_s
        self._open = opener or urllib.request.urlopen
        self._clock = clock
        self._state = VerifierState()

    def request(self, operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Returns the `result` of the operation, or raises TransportError with the code the edge (or the check of the reply) gave."""
        kind = OPERATION_KIND.get(operation, KIND_ACK)
        message = new_message(self.local_node, self.name, kind, {**(payload or {}), "op": operation}, now=self._clock())
        body = json.dumps(message.signed(self.registry.secret_for(self.local_node) or "").to_dict()).encode("utf-8")
        request = urllib.request.Request(self.url + "/v1/message", data=body, method="POST",
                                         headers={"Content-Type": "application/json", NODE_HEADER: self.local_node})
        try:
            with self._open(request, timeout=self.timeout_s) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise TransportError("unreachable", f"cannot reach {self.name}: {exc.__class__.__name__}") from exc
        try:
            document = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise TransportError("malformed", "the reply is not JSON") from exc
        if isinstance(document, dict) and "mac" not in document:
            raise TransportError(str(document.get("code", "refused")), str(document.get("reason", "the edge refused the request")))
        reply = IncidentMessage.from_dict(document)
        verdict = verify_message(reply, self.registry, self.policy, self._state, authenticated_as=self.name,
                                 expected_to_node=self.local_node, now=self._clock())
        if not verdict.ok:
            raise TransportError(f"reply-{verdict.code}", verdict.reason or "the reply did not verify")
        if not reply.payload.get("ok"):
            raise TransportError(str(reply.payload.get("code", "operation-failed")), str(reply.payload.get("reason", "")))
        result = reply.payload.get("result", {})
        return result if isinstance(result, dict) else {"value": result}
