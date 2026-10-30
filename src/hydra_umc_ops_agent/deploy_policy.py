# =============================================================================
# HYDRA-UMC-OPS-AGENT - src/hydra_umc_ops_agent/deploy_policy.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The policy file of the canary deploy: which commands may run for which project.

A signed approval says WHAT change is allowed; it does not say which program runs
on the device to check it. Without a policy, whoever holds a valid approval picks
the command. The policy closes that: for each project it lists the build-test
commands that may run (compared word by word with the command given) and,
optionally, the paths a diff may touch. Whatever is not listed is denied, and a
missing or broken policy denies everything.

    {
      "projects": {
        "HYDRA-UMC-SERVER": {
          "build_test_commands": [["bash", "build-test.sh"]],
          "allowed_paths": ["src/*", "tests/*", "docs/*"]
        }
      }
    }

`allowed_paths` is optional: a project without it accepts any path the diff may
legitimately touch (the paths that decide how a change is checked are refused
separately, unless the approval allows them). Patterns are shell-style (`*`
also crosses folders).
"""
from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

DEFAULT_POLICY_FILE = "/etc/hydra-umc/ops-agent-policy.json"
POLICY_ENV = "OPS_AGENT_POLICY"


class DeployPolicyError(Exception):
    """The policy file is missing or malformed, or the deploy asked for something it does not list."""


@dataclass(frozen=True)
class ProjectPolicy:
    build_test_commands: tuple[tuple[str, ...], ...]
    allowed_paths: tuple[str, ...] | None = None


@dataclass(frozen=True)
class DeployPolicy:
    projects: dict[str, ProjectPolicy] = field(default_factory=dict)

    def check(self, project_name: str, build_test_command: Sequence[str], touched_paths: Sequence[str] = ()) -> None:
        """Raises DeployPolicyError unless the project is listed, the command is one of its commands and every path is allowed."""
        project = self.projects.get(project_name)
        if project is None:
            raise DeployPolicyError(f"the deploy policy does not list project {project_name!r} - nothing is allowed for it")
        if tuple(build_test_command) not in project.build_test_commands:
            raise DeployPolicyError(
                f"the command {' '.join(build_test_command)!r} is not one of the build-test commands the deploy policy lists for {project_name}"
            )
        if project.allowed_paths is not None:
            outside = [path for path in touched_paths if not any(fnmatch.fnmatchcase(path, pattern) for pattern in project.allowed_paths)]
            if outside:
                preview = ", ".join(outside[:5]) + (f" (+{len(outside) - 5} more)" if len(outside) > 5 else "")
                raise DeployPolicyError(f"the diff touches path(s) the deploy policy does not allow for {project_name}: {preview}")


def parse_policy(raw: object) -> DeployPolicy:
    """Builds the policy from the decoded file. Anything malformed raises: a half-read policy must not allow half a deploy."""
    projects_raw = raw.get("projects") if isinstance(raw, dict) else None
    if not isinstance(projects_raw, dict):
        raise DeployPolicyError('the policy must be an object with a "projects" object')
    projects: dict[str, ProjectPolicy] = {}
    for name, entry in projects_raw.items():
        if not isinstance(name, str) or not name or not isinstance(entry, dict):
            raise DeployPolicyError(f"the policy entry for {name!r} must be an object")
        commands_raw = entry.get("build_test_commands")
        if not isinstance(commands_raw, list) or not commands_raw:
            raise DeployPolicyError(f"{name}: build_test_commands must be a non-empty list of commands")
        commands: list[tuple[str, ...]] = []
        for command in commands_raw:
            if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
                raise DeployPolicyError(f"{name}: every build-test command must be a non-empty list of non-empty strings")
            commands.append(tuple(command))
        paths_raw = entry.get("allowed_paths")
        allowed: tuple[str, ...] | None = None
        if paths_raw is not None:
            if not isinstance(paths_raw, list) or not all(isinstance(part, str) and part for part in paths_raw):
                raise DeployPolicyError(f"{name}: allowed_paths must be a list of non-empty strings")
            allowed = tuple(paths_raw)
        projects[name] = ProjectPolicy(build_test_commands=tuple(commands), allowed_paths=allowed)
    return DeployPolicy(projects=projects)


def load_policy(path: Path) -> DeployPolicy:
    """Reads the policy file; a missing, unreadable or malformed file raises (the deploy is then refused)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DeployPolicyError(f"cannot read the deploy policy {path}: {exc.__class__.__name__} - nothing is allowed without it") from exc
    except ValueError as exc:
        raise DeployPolicyError(f"the deploy policy {path} is not valid JSON - nothing is allowed without it") from exc
    return parse_policy(raw)
