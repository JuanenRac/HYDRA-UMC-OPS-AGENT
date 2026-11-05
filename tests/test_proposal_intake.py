# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_proposal_intake.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The incident proposals of the node watchdog: validation, rate limit, the store, and the subscriber against a simulated broker."""
import json
import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path

from hydra_umc_ops_agent.config import ProposalsConfig, parse_config
from hydra_umc_ops_agent.healing_bridge import COMPONENT_PREFIX
from hydra_umc_ops_agent.incident_store import IncidentStoreError, load_incident_store
from hydra_umc_ops_agent.notify import NotifyError
from hydra_umc_ops_agent.proposal_intake import (
    MqttSubscriber, PendingError, ProposalIntake, ProposalRefused, decide_pending, load_pending, node_of_topic,
    parse_proposal, pending_path_for, run_intake, topic_matches,
)
from hydra_umc_ops_agent.edge_service import build_handlers
from hydra_umc_ops_agent.config import TransportConfig
from hydra_umc_ops_agent.incident_transport import TransportError, OPERATION_KIND

TOPIC = "hydra/health/cm5-01/incident-proposal"


def cfg(**changes):
    values = {"enabled": True, "auto_open": True}
    values.update(changes)
    return ProposalsConfig(**values)


def proposal(**changes):
    data = {
        "schema_version": "1.0", "incidentId": "heal-cm5-01-1", "sourceNode": "cm5-01",
        "detectedAt": "2000-01-01T00:00:00Z", "severity": "critical", "component": "cm5-01",
        "symptom": "cm5-01 has been UNREACHABLE for at least 60 s", "evidenceRefs": ["mqtt:hydra/health/cm5-01/state"],
        "redactionLevel": "sanitized", "requestedBy": None, "correlationId": "heal-1",
    }
    data.update(changes)
    return json.dumps(data).encode()


class FilterTests(unittest.TestCase):
    def test_wildcards(self):
        self.assertTrue(topic_matches("hydra/health/+/incident-proposal", TOPIC))
        self.assertFalse(topic_matches("hydra/health/+/incident-proposal", "hydra/health/a/b/incident-proposal"))
        self.assertTrue(topic_matches("hydra/#", TOPIC))
        self.assertFalse(topic_matches("hydra/health/+", TOPIC))
        self.assertEqual(node_of_topic("hydra/health/+/incident-proposal", TOPIC), "cm5-01")


class ParseTests(unittest.TestCase):
    def test_a_good_proposal_becomes_the_incident_of_the_node(self):
        incident = parse_proposal(TOPIC, proposal(), cfg())
        self.assertEqual(incident.component, f"{COMPONENT_PREFIX}cm5-01")
        self.assertEqual(incident.requested_by, "node-healing:proposal")
        self.assertEqual(incident.severity, "critical")

    def refused(self, payload, reason, topic=TOPIC, config=None):
        with self.assertRaises(ProposalRefused) as caught:
            parse_proposal(topic, payload, config or cfg())
        self.assertEqual(str(caught.exception), reason)

    def test_refusals_are_named(self):
        self.refused(b"{", "not-json")
        self.refused(b"[]", "not-an-object")
        self.refused(proposal(schema_version="2.0"), "schema-version")
        self.refused(proposal(severity="fatal"), "field-severity")
        self.refused(proposal(detectedAt="yesterday"), "field-detectedAt")
        self.refused(proposal(sourceNode="bad node"), "field-sourceNode")
        self.refused(proposal(symptom=""), "field-symptom")
        self.refused(proposal(evidenceRefs="x"), "field-evidenceRefs")
        self.refused(proposal(), "topic", topic="other/topic")
        self.refused(proposal(), "too-large", config=cfg(max_payload_bytes=256))

    def test_a_node_cannot_speak_for_another(self):
        self.refused(proposal(sourceNode="cm5-02"), "node-mismatch")

    def test_allowed_nodes(self):
        self.refused(proposal(), "node-not-allowed", config=cfg(allowed_nodes="cm5-09, cm5-10"))
        parse_proposal(TOPIC, proposal(), cfg(allowed_nodes="cm5-09,cm5-01"))

    def test_severity_cap_and_redaction(self):
        incident = parse_proposal(TOPIC, proposal(symptom="login failed password=hunter2 for cm5-01"), cfg(severity_cap="warning"))
        self.assertEqual(incident.severity, "warning")
        self.assertNotIn("hunter2", incident.symptom)


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name) / "store.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_off_by_default(self):
        with self.assertRaises(IncidentStoreError):
            ProposalIntake(ProposalsConfig(), self.store)

    def test_accept_dedup_retained_and_refused(self):
        intake = ProposalIntake(cfg(), self.store)
        self.assertTrue(intake.handle(TOPIC, proposal()))
        self.assertTrue(intake.handle(TOPIC, proposal(incidentId="heal-cm5-01-2")))
        self.assertFalse(intake.handle(TOPIC, proposal(), retained=True))
        self.assertFalse(intake.handle(TOPIC, b"nope"))
        store = load_incident_store(self.store)
        self.assertEqual(len(store), 1)
        self.assertEqual(store[0].occurrence_count, 2)
        self.assertEqual(intake.result.accepted, 2)
        self.assertEqual(intake.result.ignored_retained, 1)
        self.assertEqual(intake.result.refused, {"not-json": 1})

    def test_rate_limit(self):
        now = [0.0]
        intake = ProposalIntake(cfg(max_per_minute=2), self.store, clock=lambda: now[0])
        results = [intake.handle(TOPIC, proposal()) for _ in range(4)]
        self.assertEqual(results, [True, True, False, False])
        self.assertEqual(intake.result.rate_limited, 2)
        now[0] = 61.0
        self.assertTrue(intake.handle(TOPIC, proposal()))


def utf8(text):
    raw = text.encode()
    return struct.pack(">H", len(raw)) + raw


def remaining(size):
    out = bytearray()
    while True:
        digit, size = size % 128, size // 128
        out.append(digit | (0x80 if size else 0))
        if not size:
            return bytes(out)


def read_packet(conn):
    first = conn.recv(1)
    if not first:
        return None, b""
    size, shift = 0, 0
    while True:
        digit = conn.recv(1)[0]
        size |= (digit & 0x7F) << shift
        shift += 7
        if not digit & 0x80:
            break
    data = b""
    while len(data) < size:
        data += conn.recv(size - len(data))
    return first[0], data


class FakeBroker:
    """Accepts one client, acknowledges the subscription, sends the given messages (topic, payload, retain, qos)."""

    def __init__(self, messages, refuse=False):
        self.messages, self.refuse = messages, refuse
        self.acks = []
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        conn, _ = self.server.accept()
        with conn:
            conn.settimeout(5)
            read_packet(conn)
            conn.sendall(bytes([0x20, 0x02, 0x00, 0x05 if self.refuse else 0x00]))
            if self.refuse:
                return
            read_packet(conn)  # SUBSCRIBE
            conn.sendall(bytes([0x90, 0x03, 0x00, 0x01, 0x01]))
            for index, (topic, payload, retain, qos) in enumerate(self.messages, start=10):
                variable = utf8(topic) + (struct.pack(">H", index) if qos else b"")
                conn.sendall(bytes([0x30 | (qos << 1) | int(retain)]) + remaining(len(variable) + len(payload)) + variable + payload)
                if qos:
                    first, data = read_packet(conn)
                    self.acks.append((first, struct.unpack(">H", data)[0]))
            try:
                while read_packet(conn)[0] is not None:
                    pass
            except (OSError, IndexError):
                pass
        self.server.close()


class SubscriberTests(unittest.TestCase):
    def test_messages_from_a_broker_reach_the_store(self):
        broker = FakeBroker([(TOPIC, proposal(), False, 1), (TOPIC, proposal(), True, 0), (TOPIC, b"junk", False, 0)])
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "s.json"
            subscriber = MqttSubscriber("127.0.0.1", broker.port, timeout_s=3)
            result = run_intake(cfg(max_messages=3, listen_seconds=5), store, subscriber)
            self.assertEqual((result.received, result.accepted, result.ignored_retained), (3, 1, 1))
            self.assertEqual(result.refused, {"not-json": 1})
            self.assertEqual(len(load_incident_store(store)), 1)
        broker.thread.join(5)
        self.assertEqual(broker.acks, [(0x40, 10)])

    def test_a_refused_connection_is_an_error(self):
        broker = FakeBroker([], refuse=True)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(NotifyError):
                run_intake(cfg(), Path(tmp) / "s.json", MqttSubscriber("127.0.0.1", broker.port, timeout_s=3))

    def test_nothing_listening_is_an_error(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(NotifyError):
                run_intake(cfg(), Path(tmp) / "s.json", MqttSubscriber("127.0.0.1", port, timeout_s=1))


class ConfigTests(unittest.TestCase):
    def test_section_parses_and_checks_ranges(self):
        config = parse_config({"proposals": {"enabled": True, "allowed_nodes": "a,b", "max_per_minute": 5}})
        self.assertTrue(config.proposals.enabled)
        self.assertEqual(config.proposals.allowed_nodes, "a,b")
        with self.assertRaises(Exception):
            parse_config({"proposals": {"max_per_minute": 0}})
        with self.assertRaises(Exception):
            parse_config({"proposals": {"severity_cap": "fatal"}})


class HumanApprovalTests(unittest.TestCase):
    """Without `auto_open` a proposal waits for a person; nothing reaches the incident store until it is approved."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name) / "store.json"
        self.config = ProposalsConfig(enabled=True)

    def tearDown(self):
        self.dir.cleanup()

    def test_the_default_is_to_wait_for_a_person(self):
        self.assertFalse(ProposalsConfig().auto_open)
        intake = ProposalIntake(self.config, self.store)
        self.assertTrue(intake.handle(TOPIC, proposal()))
        self.assertEqual((intake.result.accepted, intake.result.pending), (1, 1))
        self.assertEqual(load_incident_store(self.store), [])
        pending = load_pending(pending_path_for(self.config, self.store))["pending"]
        self.assertEqual([item["incident"]["incidentId"] for item in pending], ["heal-cm5-01-1"])

    def test_the_same_incident_updates_the_waiting_one(self):
        intake = ProposalIntake(self.config, self.store)
        intake.handle(TOPIC, proposal())
        intake.handle(TOPIC, proposal(symptom="again"))
        self.assertEqual(len(load_pending(pending_path_for(self.config, self.store))["pending"]), 1)

    def test_the_pending_list_has_a_limit(self):
        intake = ProposalIntake(ProposalsConfig(enabled=True, max_pending=1), self.store)
        self.assertTrue(intake.handle(TOPIC, proposal()))
        self.assertFalse(intake.handle(TOPIC, proposal(incidentId="heal-cm5-01-2")))
        self.assertEqual(intake.result.pending_full, 1)

    def test_approving_opens_the_incident_and_records_who(self):
        intake = ProposalIntake(self.config, self.store)
        intake.handle(TOPIC, proposal())
        pending = pending_path_for(self.config, self.store)
        record = decide_pending(pending, self.store, "heal-cm5-01-1", "approved", by="operator-1")
        self.assertEqual((record["decision"], record["by"]), ("approved", "operator-1"))
        incidents = load_incident_store(self.store)
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0].incident.requested_by, "node-healing:proposal")
        data = load_pending(pending)
        self.assertEqual(data["pending"], [])
        self.assertEqual(data["decided"][0]["incidentId"], "heal-cm5-01-1")

    def test_rejecting_opens_nothing(self):
        intake = ProposalIntake(self.config, self.store)
        intake.handle(TOPIC, proposal())
        pending = pending_path_for(self.config, self.store)
        decide_pending(pending, self.store, "heal-cm5-01-1", "rejected", by="operator-1")
        self.assertEqual(load_incident_store(self.store), [])
        self.assertEqual(load_pending(pending)["decided"][0]["decision"], "rejected")

    def test_a_decision_needs_a_waiting_proposal_a_known_verdict_and_a_name(self):
        pending = pending_path_for(self.config, self.store)
        ProposalIntake(self.config, self.store).handle(TOPIC, proposal())
        for args, reason in ((("nope", "approved"), "not-pending"), (("heal-cm5-01-1", "maybe"), "decision")):
            with self.assertRaises(PendingError) as caught:
                decide_pending(pending, self.store, args[0], args[1], by="op")
            self.assertEqual(str(caught.exception), reason)
        with self.assertRaises(PendingError):
            decide_pending(pending, self.store, "heal-cm5-01-1", "approved", by="bad name")
        self.assertEqual(len(load_pending(pending)["pending"]), 1)
        self.assertEqual(load_incident_store(self.store), [])
        with self.assertRaises(PendingError):  # decided once, it is not pending any more
            decide_pending(pending, self.store, "heal-cm5-01-1", "rejected", by="op")
            decide_pending(pending, self.store, "heal-cm5-01-1", "approved", by="op")

    def test_the_channel_lists_and_decides_only_when_the_feature_is_on(self):
        transport = TransportConfig()
        off = build_handlers("n", lambda: {}, transport, proposals=ProposalsConfig(), incident_store_path=self.store)
        self.assertNotIn("proposals", off)
        handlers = build_handlers("n", lambda: {}, transport, proposals=self.config, incident_store_path=self.store)
        ProposalIntake(self.config, self.store).handle(TOPIC, proposal())
        self.assertEqual(len(handlers["proposals"]({})["pending"]), 1)
        with self.assertRaises(TransportError):
            handlers["proposal-decide"]({"incidentId": "heal-cm5-01-1", "decision": "maybe", "by": "op"})
        done = handlers["proposal-decide"]({"incidentId": "heal-cm5-01-1", "decision": "approved", "by": "op"})
        self.assertEqual(done["decision"], "approved")
        self.assertEqual(len(load_incident_store(self.store)), 1)
        self.assertIn("proposals", OPERATION_KIND)

    def test_config_keys(self):
        config = parse_config({"proposals": {"auto_open": True, "max_pending": 5, "pending_store": "/tmp/p.json"}})
        self.assertTrue(config.proposals.auto_open)
        with self.assertRaises(Exception):
            parse_config({"proposals": {"max_pending": 0}})


if __name__ == "__main__":
    unittest.main()
