# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_deploy_policy.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The deploy policy lists which build-test command may run for which project; whatever is not listed is denied."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _approvals import APPROVERS, write_key_files  # noqa: E402
from test_signed_approvals import approved, make_live, run_cli  # noqa: E402

from hydra_umc_ops_agent.canary_deploy import DeployPolicyDeniedError, deploy_canary  # noqa: E402
from hydra_umc_ops_agent.change_proposal import save_proposal  # noqa: E402
from hydra_umc_ops_agent.deploy_policy import DeployPolicyError, load_policy, parse_policy  # noqa: E402

POLICY = {"projects": {"p": {"build_test_commands": [["bash", "build-test.sh"], ["python", "-c", "pass"]], "allowed_paths": ["src/*", "config.json"]}}}


def test_a_listed_command_and_path_pass() -> None:
    policy = parse_policy(POLICY)
    policy.check("p", ["bash", "build-test.sh"], ["src/a.py", "config.json"])


def test_an_unlisted_project_is_denied() -> None:
    with pytest.raises(DeployPolicyError, match="does not list project"):
        parse_policy(POLICY).check("other", ["bash", "build-test.sh"])


@pytest.mark.parametrize("command", [["bash", "other.sh"], ["bash", "build-test.sh", "--extra"], ["rm", "-rf", "/"], ["bash"]])
def test_an_unlisted_command_is_denied_word_by_word(command: list[str]) -> None:
    with pytest.raises(DeployPolicyError, match="not one of the build-test commands"):
        parse_policy(POLICY).check("p", command)


def test_a_path_outside_the_allowed_ones_is_denied() -> None:
    with pytest.raises(DeployPolicyError, match="does not allow"):
        parse_policy(POLICY).check("p", ["bash", "build-test.sh"], ["src/a.py", "deploy/run.sh"])


def test_a_project_without_allowed_paths_accepts_any_path() -> None:
    policy = parse_policy({"projects": {"p": {"build_test_commands": [["bash", "build-test.sh"]]}}})
    policy.check("p", ["bash", "build-test.sh"], ["anything/at/all.txt"])


@pytest.mark.parametrize("raw", [
    None, [], {}, {"projects": []},
    {"projects": {"p": []}},
    {"projects": {"p": {}}},
    {"projects": {"p": {"build_test_commands": []}}},
    {"projects": {"p": {"build_test_commands": ["bash build-test.sh"]}}},
    {"projects": {"p": {"build_test_commands": [["bash", ""]]}}},
    {"projects": {"p": {"build_test_commands": [["bash"]], "allowed_paths": "src/*"}}},
])
def test_a_malformed_policy_is_refused(raw: object) -> None:
    with pytest.raises(DeployPolicyError):
        parse_policy(raw)


def test_a_missing_or_broken_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DeployPolicyError, match="nothing is allowed"):
        load_policy(tmp_path / "nope.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    with pytest.raises(DeployPolicyError, match="not valid JSON"):
        load_policy(broken)


def test_the_deploy_refuses_a_command_the_policy_does_not_list(tmp_path: Path) -> None:
    live = make_live(tmp_path)
    policy = parse_policy({"projects": {"p": {"build_test_commands": [["bash", "build-test.sh"]]}}})
    with pytest.raises(DeployPolicyDeniedError):
        deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=[sys.executable, "-c", "pass"], policy=policy)
    assert '"retries": 0' in (live / "config.json").read_text(encoding="utf-8")


def test_the_deploy_refuses_a_diff_outside_the_allowed_paths(tmp_path: Path) -> None:
    live = make_live(tmp_path)
    policy = parse_policy({"projects": {"p": {"build_test_commands": [[sys.executable, "-c", "pass"]], "allowed_paths": ["src/*"]}}})
    with pytest.raises(DeployPolicyDeniedError, match="does not allow"):
        deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=[sys.executable, "-c", "pass"], policy=policy)


def test_the_command_line_refuses_without_a_policy(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.delenv("OPS_AGENT_POLICY", raising=False)
    live = make_live(tmp_path)
    proposal_path = tmp_path / "proposal.json"
    save_proposal(approved(), proposal_path)
    _, registry = write_key_files(tmp_path)
    code = run_cli("control", "deploy-canary", str(proposal_path), "--live-root", str(live),
                   "--build-test-command", f"{sys.executable} -c pass", "--approvers", registry,
                   "--policy", str(tmp_path / "missing-policy.json"))
    assert code == 1
    assert "nothing is allowed" in capsys.readouterr().err
    assert '"retries": 0' in (live / "config.json").read_text(encoding="utf-8")


def test_the_command_line_refuses_an_unlisted_command(tmp_path: Path, capsys) -> None:
    live = make_live(tmp_path)
    proposal_path = tmp_path / "proposal.json"
    save_proposal(approved(), proposal_path)
    _, registry = write_key_files(tmp_path)
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"projects": {"p": {"build_test_commands": [["bash", "build-test.sh"]]}}}), encoding="utf-8")
    code = run_cli("control", "deploy-canary", str(proposal_path), "--live-root", str(live),
                   "--build-test-command", f"{sys.executable} -c pass", "--approvers", registry, "--policy", str(policy))
    assert code == 1
    assert "not one of the build-test commands" in capsys.readouterr().err
