# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/approval_signing.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Ed25519 signatures for human approvals.

A proposal file is plain JSON on disk, so a field that merely says "approved"
(or a hash anyone can recompute) proves nothing: whoever can write the file
could write that. An approval therefore carries a signature, made with the
approver's own private key over a canonical statement of exactly what is being
approved (the proposal, the SHA-256 of the diff, who approves, when, until
when, and the commit of the checkout it is meant for). Deploying verifies that
signature against a registry of approvers' PUBLIC keys; the private key lives
only with the person who approves, never on the machine that proposes or
deploys.

Registry file format (JSON, public information):

    {"approvers": {"alice": "<base64 of the 32 raw bytes of her public key>"}}

The `cryptography` package provides the Ed25519 primitives. It is imported only
when signing or verifying, so the rest of the tool keeps working without it.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
from typing import Any, Mapping

ENVELOPE_VERSION = 1


class ApprovalSigningError(RuntimeError):
    """Base for every failure of this module."""


class SigningUnavailableError(ApprovalSigningError):
    """The `cryptography` package is not installed."""


class KeyLoadError(ApprovalSigningError):
    """A private key or an approver registry could not be read."""


def _ed25519():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SigningUnavailableError(
            "the 'cryptography' package is not installed - run: pip install -e \".[signing]\""
        ) from exc
    return ed25519, serialization, InvalidSignature


def canonical_envelope(fields: Mapping[str, Any]) -> bytes:
    """The exact bytes that are signed: the fields as JSON with sorted keys and
    no insignificant whitespace, plus the envelope version."""
    payload = dict(fields)
    payload["v"] = ENVELOPE_VERSION
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def generate_keypair(private_path: Path, public_path: Path | None = None) -> str:
    """Creates a new approver key pair. The private key is written as an
    unencrypted PKCS#8 PEM readable only by its owner; the base64 public key
    (what goes into the registry) is returned and, if a path is given, also
    written there. Refuses to overwrite an existing private key."""
    ed25519, serialization, _ = _ed25519()
    private_path = Path(private_path)
    if private_path.exists():
        raise KeyLoadError(f"{private_path} already exists - refusing to overwrite a private key")
    key = ed25519.Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(pem)
    public = public_key_b64(key.public_key())
    if public_path is not None:
        Path(public_path).write_text(public + "\n", encoding="ascii")
    return public


def public_key_b64(public_key: Any) -> str:
    _, serialization, _ = _ed25519()
    raw = public_key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def load_private_key(path: Path):
    ed25519, serialization, _ = _ed25519()
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise KeyLoadError(f"could not read the private key {path}: {exc}") from exc
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except (ValueError, TypeError) as exc:
        raise KeyLoadError(f"{path} is not an unencrypted PEM private key: {exc}") from exc
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise KeyLoadError(f"{path} is not an Ed25519 private key")
    return key


def load_approvers(path: Path) -> dict[str, Any]:
    """Reads the registry of approvers' public keys: name -> public key."""
    ed25519, _, _ = _ed25519()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise KeyLoadError(f"could not read the approver registry {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise KeyLoadError(f"{path} is not valid JSON: {exc}") from exc
    entries = data.get("approvers") if isinstance(data, dict) else None
    if not isinstance(entries, dict) or not entries:
        raise KeyLoadError(f"{path} must hold a non-empty object under \"approvers\"")
    approvers: dict[str, Any] = {}
    for name, encoded in entries.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(encoded, str):
            raise KeyLoadError(f"{path}: every approver needs a name and a base64 public key")
        try:
            raw = base64.b64decode(encoded, validate=True)
            approvers[name] = ed25519.Ed25519PublicKey.from_public_bytes(raw)
        except (binascii.Error, ValueError) as exc:
            raise KeyLoadError(f"{path}: the public key of {name!r} is not a valid Ed25519 key: {exc}") from exc
    return approvers


def sign_envelope(private_key: Any, fields: Mapping[str, Any]) -> str:
    return base64.b64encode(private_key.sign(canonical_envelope(fields))).decode("ascii")


def verify_envelope(public_key: Any, fields: Mapping[str, Any], signature_b64: str) -> bool:
    _, _, invalid_signature = _ed25519()
    try:
        signature = base64.b64decode(signature_b64, validate=True)
        public_key.verify(signature, canonical_envelope(fields))
    except (binascii.Error, ValueError, invalid_signature):
        return False
    return True
