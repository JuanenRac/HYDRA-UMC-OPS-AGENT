# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/_edge_fixtures.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Simulated edge nodes for the tests: an edge service reached through an in-memory opener (no socket), and a
real throwaway git checkout to deploy to."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import urllib.error
from pathlib import Path

from hydra_umc_ops_agent.config import TransportConfig
from hydra_umc_ops_agent.edge_service import build_handlers
from hydra_umc_ops_agent.incident_transport import (
    NODE_HEADER,
    EdgeService,
    NodeRegistry,
    TransportPolicy,
    VerifierState,
)

SECRETS = {"control": "control-secret-0123456789", "cm5-a": "cm5-a-secret-0123456789abc", "cm5-b": "cm5-b-secret-0123456789abc",
           "cm5-c": "cm5-c-secret-0123456789abc"}
REGISTRY = NodeRegistry(secrets=dict(SECRETS))

GOOD_DIFF = '--- a/config.json\n+++ b/config.json\n@@ -1,3 +1,3 @@\n {\n-  "retries": 0\n+  "retries": 3\n }\n'
CHECK_SCRIPT = (
    "import json, sys\n"
    "data = json.loads(open('config.json', encoding='utf-8').read())\n"
    "sys.exit(0 if data.get('retries', 0) >= 3 else 1)\n"
)


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def make_checkout(projects_root: Path, name: str = "test-project") -> Path:
    live = projects_root / name
    live.mkdir(parents=True)
    (live / "config.json").write_text('{\n  "retries": 0\n}\n', encoding="utf-8")
    (live / "check.py").write_text(CHECK_SCRIPT, encoding="utf-8")
    _git(["init", "-q"], live)
    _git(["config", "user.email", "test@example.com"], live)
    _git(["config", "user.name", "Test"], live)
    _git(["add", "."], live)
    _git(["commit", "-q", "-m", "initial"], live)
    return live


class InMemoryNetwork:
    """Routes a request to the EdgeService registered under its URL, turning a non-200 into an HTTPError like a socket would."""

    def __init__(self) -> None:
        self.services: dict[str, EdgeService] = {}
        self.down: set[str] = set()
        self.requests: list[tuple[str, dict]] = []

    def __call__(self, request, timeout=None):
        base = request.full_url.rsplit("/v1/message", 1)[0]
        if base in self.down:
            raise urllib.error.URLError("connection refused")
        self.requests.append((base, json.loads(request.data)))
        status, answer = self.services[base].handle(request.data, request.get_header(NODE_HEADER.capitalize()) or "")
        body = json.dumps(answer).encode("utf-8")
        if status != 200:
            raise urllib.error.HTTPError(request.full_url, status, "error", {}, io.BytesIO(body))  # type: ignore[arg-type]
        return _Response(body)


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_edge(node: str, handlers_config: TransportConfig, snapshot: dict, **kwargs) -> EdgeService:
    handlers = build_handlers(node, lambda: snapshot, handlers_config, **kwargs)
    return EdgeService(node, REGISTRY, TransportPolicy(), VerifierState(), handlers)


def python_command() -> list[str]:
    return [sys.executable, "check.py"]
