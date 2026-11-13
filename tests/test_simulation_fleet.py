# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_simulation_fleet.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Simulation bench: the real multi-node canary against simulated fleets with injected faults (a node that refuses, one that
answers nothing, one that turns unhealthy, one that cannot roll back) drawn from a fixed seed, on a simulated clock. No node,
no network, no hardware."""
import random
import unittest

from hydra_umc_ops_agent.config import MultiNodeConfig
from hydra_umc_ops_agent.multinode_canary import run_multinode_canary
from test_multinode_canary import Clock, FakeNode, approved

OUTCOMES = {"promoted", "rolled-back", "aborted", "rollback-incomplete"}


def _fleet(rng: random.Random, size: int) -> list[FakeNode]:
    nodes = []
    for index in range(size):
        nodes.append(FakeNode(
            f"sim-node-{index}",
            deploys=rng.random() > 0.12,
            deploy_error=rng.random() < 0.05,
            healthy_after_deploy=rng.random() > 0.12,
            fail_probe_at=rng.choice([None, None, None, 2, 3]),
            rollback_error=rng.random() < 0.1,
        ))
    return nodes


def _rollout(seed: int):
    rng = random.Random(seed)
    nodes = _fleet(rng, rng.randint(1, 9))
    config = MultiNodeConfig(
        enabled=True, canary_nodes=rng.randint(1, 3), wave_size=rng.choice([0, 1, 2, 3]),
        observe_seconds=30, poll_seconds=10, max_failed_probes=rng.randint(1, 2),
    )
    clock = Clock()
    result = run_multinode_canary(approved(), nodes, config, sleep=clock.sleep, monotonic=clock.monotonic)
    return nodes, result


class FleetSimulationTests(unittest.TestCase):
    def test_every_rollout_of_200_simulated_fleets_keeps_its_invariants(self):
        seen = set()
        for seed in range(200):
            nodes, result = _rollout(seed)
            seen.add(result.outcome)
            label = f"seed {seed}: {result.outcome} {[n.state for n in result.nodes]}"
            self.assertIn(result.outcome, OUTCOMES, label)
            self.assertEqual([n.name for n in result.nodes], [n.name for n in nodes], label)
            states = {n.name: n.state for n in result.nodes}
            for node in nodes:
                state = states[node.name]
                if state == "unknown":
                    # an answer lost mid-deploy is never rolled back blindly
                    self.assertFalse(node.rolled_back, label)
                    self.assertNotIn(result.outcome, ("promoted", "rolled-back"), label)
                if state == "refused":
                    self.assertFalse(node.deployed or node.rolled_back, label)
                if state == "pending":
                    self.assertFalse(node.deployed or node.rolled_back, label)
                if node.rolled_back:
                    self.assertTrue(node.deployed, label)  # only a node that took the change is put back
            if result.outcome == "promoted":
                self.assertTrue(all(n.deployed and states[n.name] == "deployed" for n in nodes), label)
            elif result.outcome == "rolled-back":
                for node in nodes:
                    if node.deployed:
                        self.assertTrue(node.rolled_back and states[node.name] == "rolled-back", label)
            elif result.outcome == "aborted":
                self.assertFalse(any(n.deployed for n in nodes), label)
            elif result.outcome == "rollback-incomplete":
                self.assertTrue(any(s in ("rollback-failed", "unknown") for s in states.values()), label)
        # the draw must actually reach the different endings, or the bench proves nothing
        self.assertGreaterEqual(len(seen), 3, f"only {sorted(seen)} were reached")

    def test_the_same_seed_gives_the_same_rollout(self):
        for seed in (3, 11, 42):
            first = _rollout(seed)[1].to_dict()
            second = _rollout(seed)[1].to_dict()
            for item in (first, second):
                for key in ("proposalId", "startedAt", "finishedAt"):
                    item.pop(key)
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
