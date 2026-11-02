# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_incident_transport.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The authenticated channel: every refusal by its named code, the replies' own checks, and the real HTTP server."""
import dataclasses
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from _edge_fixtures import REGISTRY, SECRETS, InMemoryNetwork, make_edge
from hydra_umc_ops_agent.config import TransportConfig
from hydra_umc_ops_agent.incident_transport import (
    NODE_HEADER,
    RemoteNode,
    SqliteVerifierState,
    TransportError,
    TransportPolicy,
    VerifierState,
    load_registry,
    make_server,
    new_message,
    verify_message,
)

SNAPSHOT = {"sourceNode": "cm5-a", "incidents": [{"incidentId": "i1", "severity": "critical"}]}
CONFIG = TransportConfig()


def signed(node="control", to="cm5-a", kind="incident", payload=None, now=1000.0, secret=None):
    message = new_message(node, to, kind, payload if payload is not None else {"op": "snapshot"}, now=now)
    return message.signed(secret or SECRETS[node])


class VerifyMessageTests(unittest.TestCase):
    def check(self, message, **kwargs):
        kwargs.setdefault("authenticated_as", message.from_node)
        return verify_message(message, REGISTRY, TransportPolicy(), kwargs.pop("state", VerifierState()), now=1000.0, **kwargs)

    def test_a_good_message_passes(self):
        self.assertTrue(self.check(signed()).ok)

    def test_each_refusal_has_its_code(self):
        good = signed()
        cases = {
            "unknown-identity": self.check(good, authenticated_as="ghost"),
            "impersonation": self.check(good, authenticated_as="cm5-b"),
            "wrong-recipient": self.check(good, expected_to_node="cm5-b"),
            "incompatible-version": self.check(dataclasses.replace(good, contract_version="incident-transport/2")),
            "bad-signature": self.check(dataclasses.replace(good, payload={"op": "deploy"})),
            "stale": self.check(signed(now=100.0)),
        }
        for code, verdict in cases.items():
            self.assertFalse(verdict.ok, code)
            self.assertEqual(verdict.code, code)

    def test_a_message_signed_with_another_nodes_secret_is_refused(self):
        self.assertEqual(self.check(signed(secret=SECRETS["cm5-b"])).code, "bad-signature")

    def test_replay_and_rate_limit(self):
        state = VerifierState()
        message = signed()
        self.assertTrue(self.check(message, state=state).ok)
        self.assertEqual(self.check(message, state=state).code, "replay")
        policy = TransportPolicy(max_messages_per_minute=2)
        shared = VerifierState()
        results = [verify_message(signed(), REGISTRY, policy, shared, authenticated_as="control", now=1000.0).code for _ in range(3)]
        self.assertEqual(results, [None, None, "overloaded"])

    def test_the_replay_is_caught_across_processes_by_the_sqlite_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nonces.sqlite"
            message = signed()
            first = SqliteVerifierState(path)
            self.assertTrue(verify_message(message, REGISTRY, TransportPolicy(), first, authenticated_as="control", now=1000.0).ok)
            first.close()
            second = SqliteVerifierState(path)
            self.assertEqual(verify_message(message, REGISTRY, TransportPolicy(), second, authenticated_as="control", now=1000.0).code, "replay")
            second.close()


class RegistryTests(unittest.TestCase):
    def test_short_secret_or_bad_shape_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            for content in ('{"nodes": {"a": "short"}}', '{"nodes": {}}', "[]", "not json"):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(TransportError):
                    load_registry(path)
            path.write_text(json.dumps({"nodes": SECRETS}), encoding="utf-8")
            self.assertTrue(load_registry(path).is_registered("cm5-a"))


class EdgeServiceTests(unittest.TestCase):
    def setUp(self):
        self.network = InMemoryNetwork()
        self.edge = make_edge("cm5-a", CONFIG, SNAPSHOT)
        self.network.services["http://cm5-a"] = self.edge
        self.remote = RemoteNode("cm5-a", "http://cm5-a", "control", REGISTRY, opener=self.network)

    def test_snapshot_round_trip_with_a_signed_reply(self):
        self.assertEqual(self.remote.request("snapshot")["sourceNode"], "cm5-a")

    def test_health_reports_critical_incidents(self):
        result = self.remote.request("health")
        self.assertFalse(result["healthy"])

    def test_unknown_and_disabled_operations(self):
        with self.assertRaises(TransportError) as raised:
            self.remote.request("deploy", {"proposal": {}})
        self.assertEqual(raised.exception.code, "unknown-operation")  # a deploy is not offered unless the configuration allows it

    def test_verify_of_an_unknown_incident_is_a_clean_error(self):
        with self.assertRaises(TransportError) as raised:
            self.remote.request("verify", {"incidentId": "nope"})
        self.assertEqual(raised.exception.code, "operation-failed")

    def test_the_edge_refuses_a_request_signed_for_another_node(self):
        message = signed(to="cm5-b")
        status, answer = self.edge.handle(json.dumps(message.to_dict()).encode(), "control")
        self.assertEqual((status, answer["code"]), (403, "wrong-recipient"))

    def test_a_replayed_request_is_refused(self):
        raw = json.dumps(signed(now=time.time()).to_dict()).encode()
        self.assertEqual(self.edge.handle(raw, "control")[0], 200)
        status, answer = self.edge.handle(raw, "control")
        self.assertEqual((status, answer["code"]), (409, "replay"))

    def test_garbage_is_a_400_not_a_traceback(self):
        self.assertEqual(self.edge.handle(b"\xff\xfe", "control")[0], 400)
        self.assertEqual(self.edge.handle(b"[]", "control")[0], 400)

    def test_a_forged_reply_is_not_accepted_by_the_control(self):
        forged = RemoteNode("cm5-a", "http://cm5-a", "control", REGISTRY, opener=self._forging_opener())
        with self.assertRaises(TransportError) as raised:
            forged.request("snapshot")
        self.assertEqual(raised.exception.code, "reply-bad-signature")

    def _forging_opener(self):
        network = self.network

        def opener(request, timeout=None):
            response = network(request, timeout)
            document = json.loads(response.read())
            document["payload"]["result"]["sourceNode"] = "tampered"
            from _edge_fixtures import _Response
            return _Response(json.dumps(document).encode())
        return opener

    def test_an_unreachable_edge_is_a_named_error(self):
        self.network.down.add("http://cm5-a")
        with self.assertRaises(TransportError) as raised:
            self.remote.request("snapshot")
        self.assertEqual(raised.exception.code, "unreachable")


class RealServerTests(unittest.TestCase):
    def test_the_http_server_serves_signed_requests_and_metrics_with_a_token(self):
        config = TransportConfig(enabled=True, port=0)
        edge = make_edge("cm5-a", config, SNAPSHOT)
        server = make_server(edge, config, metrics=lambda: "up 1\n", metrics_token="t0ken")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            remote = RemoteNode("cm5-a", url, "control", REGISTRY, timeout_s=5)
            self.assertEqual(remote.request("snapshot")["sourceNode"], "cm5-a")
            denied = urllib.request.Request(url + "/metrics")
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(denied, timeout=5)
            ok = urllib.request.Request(url + "/metrics", headers={"Authorization": "Bearer t0ken"})
            self.assertEqual(urllib.request.urlopen(ok, timeout=5).read(), b"up 1\n")
            wrong = urllib.request.Request(url + "/v1/message", data=b"{}", method="POST", headers={NODE_HEADER: "ghost"})
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(wrong, timeout=5)
        finally:
            server.shutdown()
            server.server_close()

    def test_switched_off_and_non_loopback_are_refused(self):
        edge = make_edge("cm5-a", CONFIG, SNAPSHOT)
        with self.assertRaises(TransportError):
            make_server(edge, TransportConfig(enabled=False))
        with self.assertRaises(TransportError):
            make_server(edge, TransportConfig(enabled=True, bind="0.0.0.0", port=0))
        with self.assertRaises(TransportError):
            make_server(edge, TransportConfig(enabled=True, port=0, tls_cert_file="only-one.pem"))


if __name__ == "__main__":
    unittest.main()
