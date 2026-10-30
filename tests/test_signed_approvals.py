# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_signed_approvals.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Signed approvals, the diff policy, and everything the deploy now does around
the swap (environment, service, health, rollback, audit journal)."""
from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from _approvals import APPROVERS, NAMES, PUBLIC_KEY, SIGNING_KEY, write_key_files
from cryptography.hazmat.primitives.asymmetric import ed25519

from hydra_umc_ops_agent import canary_deploy
from hydra_umc_ops_agent import approval_signing
from hydra_umc_ops_agent.audit_journal import read_events, verify_chain
from hydra_umc_ops_agent.canary_deploy import (
    ApprovalInvalidError,
    CanaryDeployError,
    ServiceControlError,
    TrackedDirtyError,
    deploy_canary,
    list_backups,
    prune_backups,
    rollback_deploy,
)
from hydra_umc_ops_agent.change_proposal import (
    DiffTooLargeError,
    ProposalLoadError,
    ProtectedPathError,
    SecretShapedDiffError,
    approve_change,
    load_proposal,
    propose_change,
    save_proposal,
)
from hydra_umc_ops_agent.diff_policy import diff_looks_secret_shaped, protected_paths_in, touched_paths

GOOD_DIFF = "--- a/config.json\n+++ b/config.json\n@@ -1,3 +1,3 @@\n {\n-  \"retries\": 0\n+  \"retries\": 3\n }\n"
PASS = [sys.executable, "-c", "pass"]


def git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def make_live(root: Path, extra: dict[str, str] | None = None, remote: bool = True) -> Path:
    live = root / "live-project"
    live.mkdir()
    files = {"config.json": "{\n  \"retries\": 0\n}\n", "hydra-umc.project.json": json.dumps({"name": "p"})}
    files.update(extra or {})
    for name, content in files.items():
        target = live / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
    git(["init", "-q"], live)
    for key, value in (("user.email", "t@example.com"), ("user.name", "T"), ("core.autocrlf", "false")):
        git(["config", key, value], live)
    if remote:
        git(["remote", "add", "origin", "https://example.invalid/p.git"], live)
    git(["add", "."], live)
    git(["commit", "-q", "-m", "initial"], live)
    return live


def pending(diff: str = GOOD_DIFF, **kwargs):
    return propose_change(
        incident_id="i", correlation_id="c", project_name="p", description="d", diff=diff, rationale="r", **kwargs,
    )


def approved(diff: str = GOOD_DIFF, **kwargs):
    approve_args = {key: kwargs.pop(key) for key in ("base_commit", "valid_for", "now") if key in kwargs}
    return approve_change(pending(diff, **kwargs), approved_by="Someone", signing_key=SIGNING_KEY, **approve_args)


# --------------------------------------------------------------------------
# the approval is a signature
# --------------------------------------------------------------------------

def test_a_hand_edited_approval_is_refused(tmp_path: Path):
    live = make_live(tmp_path)
    digest = hashlib.sha256(("p\n" + GOOD_DIFF).encode("utf-8")).hexdigest()
    forged = dataclasses.replace(
        pending(), status="approved", decided_by="Someone", decided_at="2026-01-01T00:00:00+00:00",
        approved_content_digest=digest,
    )
    with pytest.raises(ApprovalInvalidError, match="no signed approval"):
        deploy_canary(forged, live_root=live, approvers=APPROVERS, build_test_command=PASS)


def test_a_diff_changed_after_approval_is_refused(tmp_path: Path):
    live = make_live(tmp_path)
    other = GOOD_DIFF.replace('+  "retries": 3', '+  "retries": 99')
    tampered = dataclasses.replace(approved(), diff=other)
    with pytest.raises(ApprovalInvalidError):
        deploy_canary(tampered, live_root=live, approvers=APPROVERS, build_test_command=PASS)
    assert "99" not in (live / "config.json").read_text(encoding="utf-8")


def test_a_signature_by_another_key_under_a_registered_name_is_refused(tmp_path: Path):
    live = make_live(tmp_path)
    impostor = ed25519.Ed25519PrivateKey.generate()
    forged = approve_change(pending(), approved_by="Someone", signing_key=impostor)
    with pytest.raises(ApprovalInvalidError, match="not a valid signature"):
        deploy_canary(forged, live_root=live, approvers=APPROVERS, build_test_command=PASS)


def test_an_approver_missing_from_the_registry_is_refused(tmp_path: Path):
    live = make_live(tmp_path)
    with pytest.raises(ApprovalInvalidError, match="not a registered approver"):
        deploy_canary(approved(), live_root=live, approvers={"Somebody Else": PUBLIC_KEY}, build_test_command=PASS)


def test_an_empty_registry_refuses_everything(tmp_path: Path):
    live = make_live(tmp_path)
    with pytest.raises(ApprovalInvalidError):
        deploy_canary(approved(), live_root=live, approvers={}, build_test_command=PASS)


def test_an_expired_approval_is_refused(tmp_path: Path):
    live = make_live(tmp_path)
    long_ago = datetime.now(timezone.utc) - timedelta(days=3)
    stale = approved(now=long_ago, valid_for=timedelta(hours=1))
    with pytest.raises(ApprovalInvalidError, match="expired"):
        deploy_canary(stale, live_root=live, approvers=APPROVERS, build_test_command=PASS)


def test_an_approval_for_another_commit_is_refused_and_one_for_this_commit_deploys(tmp_path: Path):
    live = make_live(tmp_path)
    wrong = approved(base_commit="0" * 40)
    with pytest.raises(ApprovalInvalidError, match="approved for commit"):
        deploy_canary(wrong, live_root=live, approvers=APPROVERS, build_test_command=PASS)
    here = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=live, text=True).strip()
    result = deploy_canary(approved(base_commit=here), live_root=live, approvers=APPROVERS, build_test_command=PASS)
    assert result.promoted


def test_the_signature_covers_the_protected_paths_decision(tmp_path: Path):
    live = make_live(tmp_path)
    signed = approved()
    flipped = dataclasses.replace(signed, allow_protected_paths=True)
    with pytest.raises(ApprovalInvalidError, match="not a valid signature"):
        deploy_canary(flipped, live_root=live, approvers=APPROVERS, build_test_command=PASS)


def test_a_signed_approval_survives_saving_and_loading(tmp_path: Path):
    live = make_live(tmp_path)
    path = tmp_path / "proposal.json"
    save_proposal(approved(), path)
    result = deploy_canary(load_proposal(path), live_root=live, approvers=APPROVERS, build_test_command=PASS)
    assert result.promoted


def test_a_proposal_file_with_a_field_of_the_wrong_type_is_refused(tmp_path: Path):
    path = tmp_path / "proposal.json"
    save_proposal(approved(), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["decidedBy"] = 42
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProposalLoadError):
        load_proposal(path)


def test_the_approver_registry_loads_and_rejects_bad_files(tmp_path: Path):
    _key_path, registry = write_key_files(tmp_path)
    assert set(approval_signing.load_approvers(Path(registry))) == set(NAMES)
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"approvers": {"x": "not base64!"}}), encoding="utf-8")
    with pytest.raises(approval_signing.KeyLoadError):
        approval_signing.load_approvers(broken)
    broken.write_text(json.dumps({"approvers": {}}), encoding="utf-8")
    with pytest.raises(approval_signing.KeyLoadError):
        approval_signing.load_approvers(broken)
    with pytest.raises(approval_signing.KeyLoadError):
        approval_signing.load_approvers(tmp_path / "missing.json")


def test_keygen_never_overwrites_a_private_key(tmp_path: Path):
    key = tmp_path / "me.pem"
    public = approval_signing.generate_keypair(key, tmp_path / "me.pub")
    assert (tmp_path / "me.pub").read_text(encoding="ascii").strip() == public
    loaded = approval_signing.load_private_key(key)
    assert approval_signing.public_key_b64(loaded.public_key()) == public
    with pytest.raises(approval_signing.KeyLoadError):
        approval_signing.generate_keypair(key)


# --------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------

def run_cli(*argv: str):
    from hydra_umc_ops_agent.cli import main

    return main(list(argv))


def test_cli_keygen_approve_and_deploy_round_trip(tmp_path: Path, capsys):
    live = make_live(tmp_path)
    proposal_path = tmp_path / "proposal.json"
    save_proposal(pending(), proposal_path)
    key_path = tmp_path / "ana.pem"
    assert run_cli("control", "keygen", "--name", "ana", "--key-out", str(key_path), "--public-out", str(tmp_path / "ana.pub")) == 0
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"approvers": {"ana": (tmp_path / "ana.pub").read_text(encoding="ascii").strip()}}), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"

    assert run_cli("control", "approve", str(proposal_path), "--approved-by", "ana", "--key", str(key_path),
                   "--live-root", str(live), "--yes", "--audit-journal", str(audit)) == 0
    assert run_cli("control", "deploy-canary", str(proposal_path), "--live-root", str(live),
                   "--build-test-command", f"{sys.executable} -c pass", "--approvers", str(registry),
                   "--audit-journal", str(audit)) == 0
    assert '"retries": 3' in (live / "config.json").read_text(encoding="utf-8")
    events = [entry["event"] for entry in read_events(audit)]
    assert events == ["approve", "deploy-start", "deploy-finished"]
    assert verify_chain(audit) == []


def test_cli_approve_needs_to_know_which_checkout_it_is_for(tmp_path: Path, capsys):
    proposal_path = tmp_path / "proposal.json"
    save_proposal(pending(), proposal_path)
    key_path, _registry = write_key_files(tmp_path)
    assert run_cli("control", "approve", str(proposal_path), "--approved-by", "Someone", "--key", key_path, "--yes") == 1
    assert "--live-root" in capsys.readouterr().err
    assert json.loads(proposal_path.read_text(encoding="utf-8"))["status"] == "pending"


def test_cli_approve_without_a_terminal_or_yes_signs_nothing(tmp_path: Path, monkeypatch, capsys):
    proposal_path = tmp_path / "proposal.json"
    save_proposal(pending(), proposal_path)
    key_path, _registry = write_key_files(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert run_cli("control", "approve", str(proposal_path), "--approved-by", "Someone", "--key", key_path, "--any-commit") == 1
    assert json.loads(proposal_path.read_text(encoding="utf-8"))["status"] == "pending"


def test_cli_deploy_without_a_registry_is_refused(tmp_path: Path, monkeypatch, capsys):
    live = make_live(tmp_path)
    proposal_path = tmp_path / "proposal.json"
    save_proposal(approved(), proposal_path)
    monkeypatch.delenv("OPS_AGENT_APPROVERS", raising=False)
    assert run_cli("control", "deploy-canary", str(proposal_path), "--live-root", str(live),
                   "--build-test-command", f"{sys.executable} -c pass") == 1
    assert "no approver registry" in capsys.readouterr().err
    assert '"retries": 0' in (live / "config.json").read_text(encoding="utf-8")


def test_cli_rollback_and_prune(tmp_path: Path, capsys):
    live = make_live(tmp_path)
    audit = tmp_path / "audit.jsonl"
    assert deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=PASS).promoted
    assert '"retries": 3' in (live / "config.json").read_text(encoding="utf-8")
    assert run_cli("control", "rollback", "--live-root", str(live), "--audit-journal", str(audit)) == 0
    assert '"retries": 0' in (live / "config.json").read_text(encoding="utf-8")
    assert list(tmp_path.glob("live-project.rolledback-*")), "the checkout that was replaced must be kept"
    assert run_cli("control", "prune-backups", "--live-root", str(live), "--keep", "0", "--dry-run") == 0
    assert "would be removed" in capsys.readouterr().out


# --------------------------------------------------------------------------
# what a diff may hold and touch
# --------------------------------------------------------------------------

@pytest.mark.parametrize("added", [
    'def login(user, password=None):',
    'password = os.environ["APP_PASSWORD"]',
    'tokens = 5',
    'PWD=/home/pi',
    'token: str',
    'api_key=os.environ.get("KEY")',
    'DB_PASSWORD = "changeme-in-production"',
    'secret = "<your secret here>"',
    'url = "https://user:${PASSWORD}@host/path"',
])
def test_ordinary_code_that_mentions_secrets_is_not_refused(added: str):
    diff = f"--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x\n+{added}\n"
    assert diff_looks_secret_shaped(diff) is False
    pending(diff)  # accepted end to end


@pytest.mark.parametrize("added", [
    'GITHUB = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"',
    'key = "sk-ant-api03-aB3dEf6hIj9kLm2nOp5qRs8tUv1wXy4z"',
    'AWS = "AKIAIOSFODNN7EXAMPLE"',
    'password = "correct-horse-battery-staple"',
    'url = "https://deploy:Zx9fQ2mK7pLw@git.example.org/repo"',
    '-----BEGIN OPENSSH PRIVATE KEY-----',
    'headers = {"Authorization": "Basic dXNlcjpwYXNzd29yZA=="}',
])
def test_a_secret_shaped_line_is_refused(added: str):
    diff = f"--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x\n+{added}\n"
    assert diff_looks_secret_shaped(diff) is True
    with pytest.raises(SecretShapedDiffError):
        pending(diff)


def test_a_secret_on_a_removed_line_is_not_a_reason_to_refuse():
    diff = '--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-password = "correct-horse-battery-staple"\n+password = os.environ["P"]\n'
    assert diff_looks_secret_shaped(diff) is False


def test_touched_and_protected_paths_are_read_from_the_headers():
    diff = (
        "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-a\n+b\n"
        "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n--- a/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n@@ -1 +1 @@\n-a\n+b\n"
        "--- /dev/null\n+++ b/build-test.sh\n@@ -0,0 +1 @@\n+exit 0\n"
    )
    assert touched_paths(diff) == ["src/app.py", ".github/workflows/ci.yml", "build-test.sh"]
    assert protected_paths_in(diff) == [".github/workflows/ci.yml", "build-test.sh"]


def test_a_diff_that_rewrites_the_check_is_refused_unless_the_proposal_says_so():
    diff = "--- a/build-test.sh\n+++ b/build-test.sh\n@@ -1 +1 @@\n-bash check.sh\n+exit 0\n"
    with pytest.raises(ProtectedPathError):
        pending(diff)
    allowed = pending(diff, allow_protected_paths=True)
    assert allowed.allow_protected_paths is True


def test_the_deploy_refuses_protected_paths_the_approval_does_not_allow(tmp_path: Path):
    diff = "--- a/build-test.sh\n+++ b/build-test.sh\n@@ -1 +1 @@\n-bash check.sh\n+exit 0\n"
    live = make_live(tmp_path, {"build-test.sh": "bash check.sh\n"})
    assert deploy_canary(approved(diff, allow_protected_paths=True), live_root=live, approvers=APPROVERS, build_test_command=PASS).promoted

    second_root = tmp_path / "second"
    second_root.mkdir()
    second = make_live(second_root, {"build-test.sh": "bash check.sh\n"})
    forged = dataclasses.replace(approved(diff, allow_protected_paths=True), allow_protected_paths=False)
    with pytest.raises(ApprovalInvalidError):
        deploy_canary(forged, live_root=second, approvers=APPROVERS, build_test_command=PASS)
    assert "bash check.sh" in (second / "build-test.sh").read_text(encoding="utf-8")


def test_a_huge_diff_is_refused():
    lines = "".join(f"+line {n}\n" for n in range(60000))
    with pytest.raises(DiffTooLargeError):
        pending(f"--- a/big.txt\n+++ b/big.txt\n@@ -0,0 +1,60000 @@\n{lines}")


# --------------------------------------------------------------------------
# the deploy around the swap
# --------------------------------------------------------------------------

def test_the_build_does_not_see_the_operators_secrets(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPS_AGENT_TEST_SECRET", "hunter2")
    live = make_live(tmp_path)
    probe = [sys.executable, "-c", "import os, sys; sys.exit(1 if 'OPS_AGENT_TEST_SECRET' in os.environ else 0)"]
    assert deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=probe).promoted

    other = tmp_path / "second"
    other.mkdir()
    live2 = make_live(other)
    result = deploy_canary(approved(), live_root=live2, approvers=APPROVERS, build_test_command=probe,
                           build_env_allow=["OPS_AGENT_TEST_SECRET"])
    assert not result.promoted and result.stage_reached == "diff_applied"


def test_a_file_edited_during_the_build_stops_the_swap(tmp_path: Path):
    live = make_live(tmp_path)
    editor = [sys.executable, "-c", f"open(r'{live / 'config.json'}', 'a').write(' ')"]
    with pytest.raises(TrackedDirtyError, match="changed while"):
        deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=editor)
    assert not list(tmp_path.glob("live-project.backup-*"))
    assert not list(tmp_path.glob(".ops-agent-canary-*")), "the staging clone must be removed"


def test_local_data_written_during_the_build_reaches_the_new_checkout(tmp_path: Path):
    live = make_live(tmp_path, {".gitignore": "data/\n"})
    (live / "data").mkdir()
    (live / "data" / "state.txt").write_text("before\n", encoding="utf-8")
    writer = [sys.executable, "-c", f"open(r'{live / 'data' / 'state.txt'}', 'w').write('written during the build\\n')"]
    result = deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=writer)
    assert result.promoted
    assert (live / "data" / "state.txt").read_text(encoding="utf-8").strip() == "written during the build"


def test_build_output_is_not_carried_over_and_a_diff_wins_over_a_local_file(tmp_path: Path):
    live = make_live(tmp_path, {".gitignore": "node_modules/\nnotes.txt\n"})
    nested = live / "web" / "node_modules" / "pkg"
    nested.mkdir(parents=True)
    (nested / "index.js").write_text("x", encoding="utf-8")
    (live / "notes.txt").write_text("local notes", encoding="utf-8")
    add_notes = "--- /dev/null\n+++ b/notes.txt\n@@ -0,0 +1 @@\n+from the diff\n"
    result = deploy_canary(approved(add_notes), live_root=live, approvers=APPROVERS, build_test_command=PASS)
    assert result.promoted, result.detail
    assert not (live / "web" / "node_modules").exists()
    assert (live / "notes.txt").read_text(encoding="utf-8").strip() == "from the diff"


def test_a_checkout_without_an_upstream_gets_no_remote_at_all(tmp_path: Path):
    live = make_live(tmp_path, remote=False)
    assert deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=PASS).promoted
    remotes = subprocess.check_output(["git", "remote"], cwd=live, text=True).split()
    assert remotes == []


def test_the_staging_folder_is_hidden_while_the_build_runs(tmp_path: Path):
    live = make_live(tmp_path)
    seen = tmp_path / "seen.txt"
    probe = [sys.executable, "-c",
             f"import os; open(r'{seen}', 'w').write(os.path.basename(os.getcwd()))"]
    assert deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=probe).promoted
    assert seen.read_text(encoding="utf-8").startswith(".ops-agent-canary-")


class FakeServices:
    def __init__(self, stop_code: int = 0):
        self.calls: list[tuple[str, str]] = []
        self.stop_code = stop_code

    def __call__(self, action: str, unit: str, cwd: Path):
        self.calls.append((action, unit))
        if action == "stop":
            return self.stop_code, "" if self.stop_code == 0 else "Failed to stop"
        return 0, "active"


def fake_health(monkeypatch, healthy: bool):
    from hydra_umc_ops_agent.inventory import HttpHealthResult

    monkeypatch.setattr(
        canary_deploy, "check_http_health",
        lambda url, timeout_s=5.0: HttpHealthResult(url=url, reachable=healthy, status_code=200 if healthy else 503, detail="HTTP"),
    )


def test_the_service_is_stopped_before_the_swap_and_started_after_it(tmp_path: Path, monkeypatch):
    live = make_live(tmp_path)
    services = FakeServices()
    monkeypatch.setattr(canary_deploy, "_systemctl", services)
    fake_health(monkeypatch, True)
    result = deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=PASS,
                           service_unit="demo.service", health_url="http://127.0.0.1:1/health", health_timeout_s=1)
    assert result.promoted
    assert [call[0] for call in services.calls] == ["stop", "start"]


def test_an_unhealthy_promotion_is_rolled_back(tmp_path: Path, monkeypatch):
    live = make_live(tmp_path)
    services = FakeServices()
    monkeypatch.setattr(canary_deploy, "_systemctl", services)
    fake_health(monkeypatch, False)
    audit = tmp_path / "audit.jsonl"
    result = deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=PASS,
                           service_unit="demo.service", health_url="http://127.0.0.1:1/health", health_timeout_s=0.2,
                           audit_path=audit)
    assert result.promoted is False and result.stage_reached == "rolled_back"
    assert '"retries": 0' in (live / "config.json").read_text(encoding="utf-8")
    assert list(tmp_path.glob("live-project.failed-*")), "the failed checkout is kept for inspection"
    assert not list(tmp_path.glob("live-project.backup-*")), "the backup went back into place"
    assert [call[0] for call in services.calls] == ["stop", "start", "start"]
    assert [entry["event"] for entry in read_events(audit)] == ["deploy-start", "deploy-finished"]


def test_a_service_that_will_not_stop_leaves_everything_as_it_was(tmp_path: Path, monkeypatch):
    live = make_live(tmp_path)
    monkeypatch.setattr(canary_deploy, "_systemctl", FakeServices(stop_code=1))
    with pytest.raises(ServiceControlError):
        deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=PASS, service_unit="demo.service")
    assert '"retries": 0' in (live / "config.json").read_text(encoding="utf-8")
    assert not list(tmp_path.glob(".ops-agent-canary-*"))


def test_a_service_unit_that_looks_like_an_option_is_refused(tmp_path: Path):
    live = make_live(tmp_path)
    with pytest.raises(CanaryDeployError, match="not a valid systemd unit name"):
        deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=PASS, service_unit="--host=elsewhere")


def test_refusals_and_deploys_are_written_to_the_audit_journal(tmp_path: Path):
    live = make_live(tmp_path)
    audit = tmp_path / "audit.jsonl"
    with pytest.raises(ApprovalInvalidError):
        deploy_canary(approved(), live_root=live, approvers={}, build_test_command=PASS, audit_path=audit)
    assert deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=PASS, audit_path=audit).promoted
    assert [entry["event"] for entry in read_events(audit)] == ["deploy-refused", "deploy-start", "deploy-finished"]
    assert verify_chain(audit) == []


def test_a_deploy_that_cannot_be_recorded_does_not_happen(tmp_path: Path):
    live = make_live(tmp_path)
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("x", encoding="utf-8")
    with pytest.raises(CanaryDeployError, match="audit journal"):
        deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=PASS, audit_path=blocked / "audit.jsonl")
    assert '"retries": 0' in (live / "config.json").read_text(encoding="utf-8")


def test_rollback_and_prune_keep_what_they_should(tmp_path: Path):
    live = make_live(tmp_path)
    for retries in (3, 5):
        diff = GOOD_DIFF.replace('+  "retries": 3', f'+  "retries": {retries}')
        current = (live / "config.json").read_text(encoding="utf-8").split(":")[1].strip().split()[0]
        diff = diff.replace('-  "retries": 0', f'-  "retries": {current}')
        assert deploy_canary(approved(diff), live_root=live, approvers=APPROVERS, build_test_command=PASS, keep_local_commit=True).promoted
    backups = list_backups(live)
    assert len(backups) == 2
    removed = prune_backups(live, keep=1)
    assert len(removed) == 1 and len(list_backups(live)) == 1
    used = rollback_deploy(live)
    assert '"retries": 3' in (live / "config.json").read_text(encoding="utf-8")
    assert used.name.startswith("live-project.backup-")
    with pytest.raises(CanaryDeployError):
        rollback_deploy(live)  # no backup is left


def test_the_swap_is_journaled_when_the_sdk_is_available(tmp_path: Path):
    pytest.importorskip("hydra_umc_sdk")
    live = make_live(tmp_path)
    assert deploy_canary(approved(), live_root=live, approvers=APPROVERS, build_test_command=PASS).promoted
    from hydra_umc_sdk.promotion_journal import PromotionJournal

    assert PromotionJournal(tmp_path / ".hydra_umc_ops_agent_promotion_journal.json").pending() == []
