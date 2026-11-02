# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_multinode_canary.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The canary across nodes: the control logic against fake nodes, and a full rollout of an approved proposal to
three simulated edge nodes with real git checkouts through the authenticated channel."""
import json
import tempfile
import unittest
from pathlib import Path

from _approvals import SIGNING_KEY, write_key_files
from _edge_fixtures import GOOD_DIFF, REGISTRY, InMemoryNetwork, make_checkout, make_edge, python_command
from hydra_umc_ops_agent.change_proposal import approve_change, propose_change
from hydra_umc_ops_agent.config import MultiNodeConfig, TransportConfig
from hydra_umc_ops_agent.incident_transport import RemoteNode
from hydra_umc_ops_agent.multinode_canary import MultiNodeCanaryError, RemoteTarget, run_multinode_canary


def approved():
    proposal = propose_change(incident_id="i", correlation_id="c", project_name="test-project", description="d", diff=GOOD_DIFF, rationale="r")
    return approve_change(proposal, approved_by="Test Approver", signing_key=SIGNING_KEY)


class Clock:
    """Simulated time: sleeping advances it, so an observation window takes no real time."""

    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds

    def monotonic(self):
        return self.now


class FakeNode:
    def __init__(self, name, deploys=True, healthy_after_deploy=True, fail_probe_at=None, rollback_error=False, deploy_error=False):
        self.name, self.deploys, self.deploy_error, self.rollback_error = name, deploys, deploy_error, rollback_error
        self.healthy_after_deploy, self.fail_probe_at = healthy_after_deploy, fail_probe_at
        self.deployed = self.rolled_back = False
        self.probes = 0

    def deploy(self, proposal):
        if self.deploy_error:
            raise OSError("connection lost")
        self.deployed = self.deploys
        return self.deploys

    def probe(self):
        self.probes += 1
        if not self.deployed:
            return True, "not changed"
        if not self.healthy_after_deploy or (self.fail_probe_at is not None and self.probes >= self.fail_probe_at):
            return False, "unhealthy"
        return True, "ok"

    def rollback(self, project):
        if self.rollback_error:
            raise OSError("disk")
        self.rolled_back = True
        return f"backup-of-{self.name}"


def run(nodes, proposal=None, **config):
    clock = Clock()
    settings = MultiNodeConfig(enabled=True, observe_seconds=30, poll_seconds=10, **config)
    events = []
    result = run_multinode_canary(proposal or approved(), nodes, settings, sleep=clock.sleep, monotonic=clock.monotonic,
                                  on_event=lambda event, data: events.append(event))
    return result, events


class RolloutLogicTests(unittest.TestCase):
    def test_healthy_canary_then_the_rest_in_waves(self):
        nodes = [FakeNode(f"n{i}") for i in range(5)]
        result, events = run(nodes, canary_nodes=1, wave_size=2)
        self.assertTrue(result.promoted)
        self.assertTrue(all(node.deployed and not node.rolled_back for node in nodes))
        self.assertEqual(events.count("wave-healthy"), 3)  # canary + two waves
        self.assertGreaterEqual(nodes[0].probes, 3 * 4)  # watched through every wave

    def test_a_canary_that_turns_unhealthy_stops_the_rollout_and_nothing_else_is_touched(self):
        nodes = [FakeNode("n0", fail_probe_at=2), FakeNode("n1"), FakeNode("n2")]
        result, _ = run(nodes)
        self.assertEqual(result.outcome, "rolled-back")
        self.assertTrue(nodes[0].rolled_back)
        self.assertFalse(nodes[1].deployed or nodes[2].deployed)
        self.assertEqual([node.state for node in result.nodes], ["rolled-back", "pending", "pending"])

    def test_a_failure_in_a_later_wave_undoes_the_canary_too(self):
        nodes = [FakeNode("n0"), FakeNode("n1"), FakeNode("n2", healthy_after_deploy=False)]
        result, events = run(nodes, canary_nodes=1, wave_size=1)
        self.assertEqual(result.outcome, "rolled-back")
        self.assertTrue(all(node.rolled_back for node in nodes))
        self.assertIn("rolled-back", events)

    def test_a_node_that_refuses_the_change_aborts_and_undoes_those_that_took_it(self):
        nodes = [FakeNode("n0"), FakeNode("n1", deploys=False)]
        result, _ = run(nodes, canary_nodes=2)
        self.assertEqual(result.outcome, "rolled-back")
        self.assertTrue(nodes[0].rolled_back and not nodes[1].rolled_back)
        self.assertEqual(result.nodes[1].state, "refused")

    def test_refused_by_the_first_node_is_an_abort_with_nothing_to_undo(self):
        result, _ = run([FakeNode("n0", deploys=False), FakeNode("n1")])
        self.assertEqual(result.outcome, "aborted")

    def test_a_lost_answer_is_unknown_never_rolled_back_blindly_and_flags_the_rollout(self):
        nodes = [FakeNode("n0"), FakeNode("n1", deploy_error=True)]
        result, _ = run(nodes, canary_nodes=1, wave_size=1)
        self.assertEqual(result.nodes[1].state, "unknown")
        self.assertFalse(nodes[1].rolled_back)
        self.assertTrue(nodes[0].rolled_back)
        self.assertEqual(result.outcome, "rollback-incomplete")

    def test_a_rollback_that_fails_is_reported(self):
        nodes = [FakeNode("n0", healthy_after_deploy=False, rollback_error=True)]
        result, _ = run(nodes)
        self.assertEqual((result.outcome, result.nodes[0].state), ("rollback-incomplete", "rollback-failed"))

    def test_a_probe_that_raises_counts_as_failed(self):
        node = FakeNode("n0")
        node.probe = lambda: (_ for _ in ()).throw(OSError("x"))  # type: ignore[method-assign]
        result, _ = run([node])
        self.assertEqual(result.outcome, "rolled-back")

    def test_max_failed_probes_tolerates_a_blip(self):
        flaky = FakeNode("n0")
        answers = iter([(True, "ok"), (False, "blip"), (True, "ok"), (True, "ok"), (True, "ok"), (True, "ok")])
        flaky.probe = lambda: next(answers, (True, "ok"))  # type: ignore[method-assign]
        result, _ = run([flaky], max_failed_probes=2)
        self.assertTrue(result.promoted)

    def test_refusals_before_anything_changes(self):
        proposal = propose_change(incident_id="i", correlation_id="c", project_name="p", description="d", diff=GOOD_DIFF, rationale="r")
        with self.assertRaises(MultiNodeCanaryError):
            run([FakeNode("n0")], proposal=proposal)  # pending, not approved
        with self.assertRaises(MultiNodeCanaryError):
            run_multinode_canary(approved(), [FakeNode("n0")], MultiNodeConfig())  # switched off
        with self.assertRaises(MultiNodeCanaryError):
            run([FakeNode("n0"), FakeNode("n0")])
        with self.assertRaises(MultiNodeCanaryError):
            run([FakeNode(f"n{i}") for i in range(3)], max_nodes=2)
        with self.assertRaises(MultiNodeCanaryError):
            run([])


class SimulatedFleetTests(unittest.TestCase):
    """Three edge nodes (separate checkouts, each with its own approver registry and policy) behind the signed channel."""

    def build(self, tmp: Path, names=("cm5-a", "cm5-b", "cm5-c"), broken=()):
        key_path, approvers = write_key_files(tmp)
        policy = tmp / "policy.json"
        policy.write_text(json.dumps({"projects": {"test-project": {"build_test_commands": [python_command()]}}}), encoding="utf-8")
        config = TransportConfig(enabled=True, allow_remote_deploy=True, approvers_file=approvers, policy_file=str(policy), build_timeout_seconds=60)
        network, targets, roots = InMemoryNetwork(), [], {}
        for name in names:
            root = tmp / name
            root.mkdir()
            roots[name] = make_checkout(root)
            if name in broken:
                (roots[name] / "check.py").write_text("import sys; sys.exit(1)\n", encoding="utf-8")
                subprocess_commit(roots[name])
            network.services[f"http://{name}"] = make_edge(name, config, {"incidents": []}, projects_root=root)
            targets.append(RemoteTarget(RemoteNode(name, f"http://{name}", "control", REGISTRY, opener=network)))
        return targets, roots, network

    def retries(self, root):
        return json.loads((root / "config.json").read_text(encoding="utf-8"))["retries"]

    def test_a_signed_approval_rolls_out_to_every_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            targets, roots, network = self.build(Path(tmp))
            result, _ = run(targets, canary_nodes=1, wave_size=0)
            self.assertTrue(result.promoted, result.to_dict())
            self.assertEqual({self.retries(root) for root in roots.values()}, {3})
            self.assertEqual([body["payload"]["op"] for _, body in network.requests][:2], ["deploy", "health"])

    def test_a_node_whose_build_check_fails_rolls_everything_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            targets, roots, _ = self.build(Path(tmp), broken=("cm5-c",))
            result, _ = run(targets, canary_nodes=1, wave_size=1)
            self.assertEqual(result.outcome, "rolled-back", result.to_dict())
            self.assertEqual({self.retries(root) for root in roots.values()}, {0})  # the canary was put back too
            self.assertEqual(result.nodes[2].state, "refused")

    def test_an_edge_refuses_a_tampered_approval_even_though_the_control_sent_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            targets, roots, _ = self.build(Path(tmp), names=("cm5-a",))
            proposal = approved()
            from dataclasses import replace
            forged = replace(proposal, diff=proposal.diff.replace("3", "9"))
            result, _ = run(targets, proposal=forged)
            self.assertEqual(result.outcome, "aborted")
            self.assertEqual(self.retries(roots["cm5-a"]), 0)

    def test_a_deploy_is_not_offered_when_the_edge_does_not_allow_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            network = InMemoryNetwork()
            network.services["http://cm5-a"] = make_edge("cm5-a", TransportConfig(enabled=True), {"incidents": []}, projects_root=Path(tmp))
            target = RemoteTarget(RemoteNode("cm5-a", "http://cm5-a", "control", REGISTRY, opener=network))
            result, _ = run([target])
            self.assertEqual(result.outcome, "aborted")
            self.assertEqual(result.nodes[0].state, "refused")  # the edge said it does not offer a deploy: nothing changed

    def test_an_unreachable_node_during_observation_triggers_the_rollback(self):
        import urllib.error

        with tempfile.TemporaryDirectory() as tmp:
            targets, roots, network = self.build(Path(tmp), names=("cm5-a",))
            original = network.__call__

            def flaky(request, timeout=None):
                if json.loads(request.data)["payload"]["op"] == "health":
                    raise urllib.error.URLError("connection refused")
                return original(request, timeout)

            targets[0].remote._open = flaky
            result, _ = run(targets)
            self.assertEqual(result.outcome, "rolled-back")
            self.assertEqual(self.retries(roots["cm5-a"]), 0)


def subprocess_commit(root: Path) -> None:
    import subprocess
    subprocess.run(["git", "add", "."], cwd=str(root), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "break the check"], cwd=str(root), check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
