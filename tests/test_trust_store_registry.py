# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_trust_store_registry.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The registry of approvers can also be the trust store of the dev server: alias -> `ed25519-public:<hex>`, with revoked aliases.
Public keys only, a revoked alias cannot approve, and anything doubtful refuses the whole file."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from hydra_umc_ops_agent import approval_signing

ANA = ed25519.Ed25519PrivateKey.generate()
BOB = ed25519.Ed25519PrivateKey.generate()


def public_text(key: ed25519.Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return "ed25519-public:" + raw.hex()


def write(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "trust.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_trust_store_is_read_as_a_registry(tmp_path: Path):
    path = write(tmp_path, {"trusted_keys": {"Ana bench 1": public_text(ANA), "bob": public_text(BOB)}, "revoked": []})
    approvers = approval_signing.load_approvers(path)
    assert set(approvers) == {"Ana bench 1", "bob"}
    fields = {"proposal": "p1", "approver": "bob"}
    signature = approval_signing.sign_envelope(BOB, fields)
    assert approval_signing.verify_envelope(approvers["bob"], fields, signature)
    assert not approval_signing.verify_envelope(approvers["Ana bench 1"], fields, signature)


def test_a_revoked_alias_cannot_approve(tmp_path: Path):
    path = write(tmp_path, {"trusted_keys": {"ana": public_text(ANA), "bob": public_text(BOB)}, "revoked": ["ana"]})
    assert set(approval_signing.load_approvers(path)) == {"bob"}


def test_a_store_where_everybody_is_revoked_refuses(tmp_path: Path):
    path = write(tmp_path, {"trusted_keys": {"ana": public_text(ANA)}, "revoked": ["ana"]})
    with pytest.raises(approval_signing.KeyLoadError, match="revoked"):
        approval_signing.load_approvers(path)


def test_a_private_seed_refuses_the_file_and_is_never_echoed(tmp_path: Path):
    seed = "ed25519-seed:" + "ab" * 32
    path = write(tmp_path, {"trusted_keys": {"ana": public_text(ANA), "oops": seed}})
    with pytest.raises(approval_signing.KeyLoadError) as caught:
        approval_signing.load_approvers(path)
    assert "oops" in str(caught.value)
    assert "abab" not in str(caught.value)


@pytest.mark.parametrize(
    "document",
    [
        {"trusted_keys": {}},
        {"trusted_keys": []},
        {"trusted_keys": {"ana": "ed25519-public:xyz"}},
        {"trusted_keys": {"ana": "ed25519-public:" + "AB" * 32}},
        {"trusted_keys": {"ana": "ed25519-public:" + "ab" * 31}},
        {"trusted_keys": {"ana": 7}},
        {"trusted_keys": {"-bad": "ed25519-public:" + "ab" * 32}},
        {"trusted_keys": {"a" * 41: "ed25519-public:" + "ab" * 32}},
        {"trusted_keys": {"ana": "ed25519-public:" + "ab" * 32}, "revoked": "ana"},
        {"trusted_keys": {"ana": "ed25519-public:" + "ab" * 32}, "revoked": [1]},
    ],
)
def test_bad_stores_are_refused(tmp_path: Path, document: object):
    with pytest.raises(approval_signing.KeyLoadError):
        approval_signing.load_approvers(write(tmp_path, document))


def test_the_old_registry_format_still_wins_when_it_is_the_one_given(tmp_path: Path):
    raw = ANA.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    import base64

    path = write(tmp_path, {"approvers": {"ana": base64.b64encode(raw).decode("ascii")}})
    assert set(approval_signing.load_approvers(path)) == {"ana"}
