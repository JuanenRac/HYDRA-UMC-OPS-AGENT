# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/contract_check.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The files this agent reads (a snapshot, a change proposal) checked against the closed schemas of the shared SDK.

`contracts.validate` in the configuration file picks what happens when a file does not match: `off` (the default) checks nothing, `warn` says it on the error output and
goes on, `strict` refuses the file. The checks need the SDK (`pip install .[sdk]`); without it `warn` says once that it cannot check and `strict` refuses.
"""
from __future__ import annotations

import sys
from typing import Any

MODES = ("off", "warn", "strict")

_mode = "off"
_said_missing = False


class ContractCheckError(ValueError):
    """A file does not match its contract (mode `strict`), or the SDK that checks it is not installed."""


def set_mode(mode: str) -> None:
    global _mode
    _mode = mode if mode in MODES else "off"


def current_mode() -> str:
    return _mode


def check(contract: str, payload: Any, source: str, mode: str | None = None) -> None:
    """Check `payload` against the SDK validator of `contract` ("NodeSnapshot", "ChangeProposal" or "CanaryDeployResult"); nothing happens while the mode is `off`."""
    global _said_missing
    chosen = mode or _mode
    if chosen == "off":
        return
    try:
        from hydra_umc_sdk import maintenance_agent as sdk  # type: ignore[import-not-found]
        from hydra_umc_sdk.validation import ContractValidationError  # type: ignore[import-not-found]
    except ImportError:
        if chosen == "strict":
            raise ContractCheckError(f"{source} cannot be checked: the SDK is not installed") from None
        if not _said_missing:
            _said_missing = True
            print("WARNING: contracts.validate is on, but the SDK is not installed: the files are not checked", file=sys.stderr)
        return
    validators = {"NodeSnapshot": sdk.validate_node_snapshot, "ChangeProposal": sdk.validate_change_proposal,
                  "CanaryDeployResult": sdk.validate_canary_deploy_result}
    try:
        validators[contract](payload)
    except ContractValidationError as exc:
        if chosen == "strict":
            raise ContractCheckError(f"{source} does not match the {contract} contract: {exc}") from exc
        print(f"WARNING: {source} does not match the {contract} contract: {exc}", file=sys.stderr)
