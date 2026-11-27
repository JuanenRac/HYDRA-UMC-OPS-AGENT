"""A project adds protected paths of its own; the fixed list stays."""

import pytest

from hydra_umc_ops_agent.deploy_policy import DeployPolicyError, parse_policy
from hydra_umc_ops_agent.diff_policy import protected_paths_in


def diff(path: str) -> str:
    return f"--- a/{path}\n+++ b/{path}\n"


@pytest.mark.parametrize("path", ["GNUmakefile", "sub/makefile", "Makefile"])
def test_every_name_make_reads_is_protected(path: str) -> None:
    assert protected_paths_in(diff(path)) == [path]


def test_the_policy_adds_paths_and_never_removes_one() -> None:
    policy = parse_policy({"projects": {"P": {"build_test_commands": [["make"]], "protected_paths": ["conftest.py", "ci/"]}}})
    extra = policy.protected_for("P")
    assert policy.protected_for("other") == ()
    for path in ("conftest.py", "tests/conftest.py", "ci/run.sh", "Makefile"):
        assert protected_paths_in(diff(path), extra) == [path]
    assert protected_paths_in(diff("src/main.py"), extra) == []
    assert protected_paths_in(diff("conftest.py")) == []


@pytest.mark.parametrize("value", ["conftest.py", [""], [3]])
def test_a_malformed_list_denies_the_whole_policy(value: object) -> None:
    with pytest.raises(DeployPolicyError):
        parse_policy({"projects": {"P": {"build_test_commands": [["make"]], "protected_paths": value}}})
