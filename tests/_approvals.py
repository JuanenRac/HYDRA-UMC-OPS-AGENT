# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/_approvals.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""One throwaway approver key for the whole test run, registered under every
name the tests approve with, so a test can sign an approval in one line."""
from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric import ed25519

SIGNING_KEY = ed25519.Ed25519PrivateKey.generate()
PUBLIC_KEY = SIGNING_KEY.public_key()
NAMES = ("Test Approver", "Someone", "Juan Enrique", "Juan", "A", "B", "Approver")
APPROVERS = {name: PUBLIC_KEY for name in NAMES}


def write_policy(directory, project: str, command: str) -> str:
    """Writes a deploy policy that lists one build-test command for one project; returns its path for `--policy`."""
    import json
    from pathlib import Path

    from hydra_umc_ops_agent.cli import _split_command

    path = Path(directory) / "deploy-policy.json"
    path.write_text(json.dumps({"projects": {project: {"build_test_commands": [_split_command(command)]}}}), encoding="utf-8")
    return str(path)


def write_key_files(directory) -> tuple[str, str]:
    """Writes the test key as a PEM file and a registry JSON naming it; returns
    (private key path, registry path) as strings for the command line."""
    import json
    from pathlib import Path

    from cryptography.hazmat.primitives import serialization

    directory = Path(directory)
    key_path = directory / "approver.pem"
    registry_path = directory / "approvers.json"
    key_path.write_bytes(SIGNING_KEY.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    from hydra_umc_ops_agent.approval_signing import public_key_b64

    registry_path.write_text(json.dumps({"approvers": {name: public_key_b64(PUBLIC_KEY) for name in NAMES}}), encoding="utf-8")
    return str(key_path), str(registry_path)
