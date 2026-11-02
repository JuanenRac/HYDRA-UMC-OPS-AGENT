# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_healing_notify_metrics.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The bridge from the node watchdog, the notifications to the broker (against a simulated broker) and the metrics."""
import json
import socket
import struct
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from hydra_umc_ops_agent.audit_journal import append_event
from hydra_umc_ops_agent.config import HealingConfig, MetricsConfig, NotifyConfig
from hydra_umc_ops_agent.healing_bridge import ingest, parse_transition
from hydra_umc_ops_agent.incident_store import IncidentStoreError, load_incident_store
from hydra_umc_ops_agent.metrics import collect_metrics, render_metrics
from hydra_umc_ops_agent.notify import MqttPublisher, NotifyError, Notifier


def log_line(node, before, after, detail=""):
    text = f"[node-healing] {node}: {before} -> {after}" + (f" ({detail})" if detail else "")
    return json.dumps({"event": "log", "message": text, "time": "2000-01-01T00:00:00Z", "prev": "0"})


def structured(node, before, after):
    return json.dumps({"event": "transition", "node": node, "from": before, "to": after, "detail": "x", "time": "t"})


class FakePublisher:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def publish(self, topic, payload, qos):
        if self.fail:
            raise NotifyError("down")
        self.sent.append((topic, json.loads(payload), qos))


class HealingBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.journal, self.store = root / "journal.jsonl", root / "store.json"
        self.config = HealingConfig(enabled=True, journal_file=str(self.journal), state_file=str(root / "offset.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, *lines):
        with self.journal.open("a", encoding="utf-8", newline="\n") as handle:
            handle.writelines(line + "\n" for line in lines)

    def test_parsing_both_shapes_and_ignoring_the_rest(self):
        self.assertEqual(parse_transition(log_line("cm5-a", "HEALTHY", "UNREACHABLE", "timeout")).to_status, "UNREACHABLE")
        self.assertEqual(parse_transition(structured("cm5-a", "unreachable", "healthy")).to_status, "HEALTHY")
        for line in ("not json", "[]", json.dumps({"event": "log", "message": "something else"}), json.dumps({"event": "transition"})):
            self.assertIsNone(parse_transition(line))

    def test_unreachable_opens_one_incident_healthy_closes_it_and_a_rerun_adds_nothing(self):
        self.write(log_line("cm5-a", "HEALTHY", "UNREACHABLE", "timeout"), log_line("cm5-b", "UNKNOWN", "DEGRADED"))
        result = ingest(self.config, self.store)
        self.assertEqual((result.transitions, result.opened_or_updated, result.resolved), (2, 1, 0))
        store = load_incident_store(self.store)
        self.assertEqual(len(store), 1)
        self.assertEqual((store[0].incident.source_node, store[0].incident.severity), ("cm5-a", "critical"))
        self.assertEqual(ingest(self.config, self.store).transitions, 0)
        self.write(log_line("cm5-a", "UNREACHABLE", "INVALID"), log_line("cm5-a", "INVALID", "HEALTHY"))
        ingest(self.config, self.store)
        store = load_incident_store(self.store)
        self.assertEqual(len(store), 1)
        self.assertIsNotNone(store[0].resolved_at)
        self.assertEqual(store[0].occurrence_count, 2)

    def test_a_healthy_transition_without_an_open_incident_does_nothing(self):
        self.write(log_line("cm5-a", "UNKNOWN", "HEALTHY"))
        self.assertEqual(ingest(self.config, self.store).resolved, 0)

    def test_a_rotated_journal_is_read_from_the_start_and_a_half_line_waits(self):
        self.write(log_line("cm5-a", "HEALTHY", "UNREACHABLE"))
        ingest(self.config, self.store)
        self.journal.write_text(log_line("cm5-b", "HEALTHY", "INVALID") + "\n", encoding="utf-8")
        self.assertEqual(ingest(self.config, self.store).opened_or_updated, 1)
        with self.journal.open("a", encoding="utf-8") as handle:
            handle.write(log_line("cm5-c", "HEALTHY", "INVALID")[:20])
        self.assertEqual(ingest(self.config, self.store).transitions, 0)

    def test_switched_off_or_unconfigured_refuses(self):
        with self.assertRaises(IncidentStoreError):
            ingest(HealingConfig(), self.store)
        with self.assertRaises(IncidentStoreError):
            ingest(HealingConfig(enabled=True), self.store)

    def test_the_transition_also_notifies(self):
        publisher = FakePublisher()
        notifier = Notifier(NotifyConfig(enabled=True, language="es"), publisher)
        self.write(log_line("cm5-a", "HEALTHY", "UNREACHABLE"))
        ingest(self.config, self.store, notifier=notifier)
        topic, event, _ = publisher.sent[0]
        self.assertEqual(topic, "hydra/ops/incidents/cm5-a")
        self.assertTrue(event["message"].startswith("Incidencia"))


class NotifierTests(unittest.TestCase):
    def tracked(self, severity="critical", resolved=False):
        from hydra_umc_ops_agent.incident import MaintenanceIncident
        from hydra_umc_ops_agent.incident_store import TrackedIncident

        incident = MaintenanceIncident("i1", "cm5-a", "2000-01-01T00:00:00+00:00", severity, "https://u:hunter2secret@host/health", "down", ("r",), "sanitized", None, "c1")
        return TrackedIncident(incident, "t0", "t1", 1, "t2" if resolved else None)

    def test_the_event_is_an_envelope_redacted_and_localised(self):
        notifier = Notifier(NotifyConfig(enabled=True, language="de"), FakePublisher())
        event = notifier.build_event("opened", self.tracked())
        for key in ("schema_version", "event_id", "type", "source", "timestamp_utc", "sequence", "correlation_id"):
            self.assertIn(key, event)
        self.assertEqual((event["schema_version"], event["type"]), ("1.0", "ops.incident.opened"))
        self.assertNotIn("hunter2secret", json.dumps(event))
        self.assertTrue(event["message"].startswith("Vorfall"))
        self.assertGreater(notifier.build_event("opened", self.tracked())["sequence"], event["sequence"])

    def test_changes_publish_opened_and_resolved_and_filter_by_severity(self):
        publisher = FakePublisher()
        notifier = Notifier(NotifyConfig(enabled=True, min_severity="critical"), publisher)
        sent = notifier.notify_changes([], [self.tracked("info"), self.tracked("critical")])
        self.assertEqual(sent, 1)
        before = [self.tracked("critical")]
        sent = notifier.notify_changes(before, [self.tracked("critical", resolved=True)])
        self.assertEqual(publisher.sent[-1][1]["type"], "ops.incident.resolved")
        self.assertEqual(sent, 1)
        self.assertEqual(notifier.notify_changes(before, before), 0)

    def test_a_down_broker_queues_the_event_and_the_next_flush_sends_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = Path(tmp) / "outbox.jsonl"
            config = NotifyConfig(enabled=True, outbox_file=str(outbox))
            down = Notifier(config, FakePublisher(fail=True))
            self.assertEqual(down.notify_changes([], [self.tracked()]), 0)
            self.assertEqual(len(outbox.read_text(encoding="utf-8").splitlines()), 1)
            self.assertEqual(down.flush_outbox(), 0)
            up = FakePublisher()
            self.assertEqual(Notifier(config, up).flush_outbox(), 1)
            self.assertEqual(outbox.read_text(encoding="utf-8"), "")
            self.assertEqual(len(up.sent), 1)


class SimulatedBroker:
    """Accepts one MQTT 3.1.1 connection: CONNECT -> CONNACK, PUBLISH (-> PUBACK for QoS 1), DISCONNECT."""

    def __init__(self, connack_code=0):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.connack_code = connack_code
        self.connect_body = b""
        self.published = None
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @staticmethod
    def _read(conn, count):
        data = b""
        while len(data) < count:
            chunk = conn.recv(count - len(data))
            if not chunk:
                return data
            data += chunk
        return data

    def _packet(self, conn):
        first = self._read(conn, 1)
        if not first:
            return None, b""
        length, shift = 0, 0
        while True:
            digit = self._read(conn, 1)[0]
            length += (digit & 0x7F) << shift
            shift += 7
            if not digit & 0x80:
                break
        return first[0], self._read(conn, length)

    def _serve(self):
        conn, _ = self.listener.accept()
        with conn:
            kind, body = self._packet(conn)
            self.connect_body = body
            conn.sendall(bytes([0x20, 2, 0, self.connack_code]))
            if self.connack_code:
                return
            kind, body = self._packet(conn)
            topic_length = struct.unpack(">H", body[:2])[0]
            topic = body[2:2 + topic_length].decode()
            rest = body[2 + topic_length:]
            if kind & 0x06:
                packet_id, rest = rest[:2], rest[2:]
                conn.sendall(bytes([0x40, 2]) + packet_id)
            self.published = (kind, topic, rest)
            self._packet(conn)
        self.listener.close()


class MqttPublisherTests(unittest.TestCase):
    def test_publish_qos1_reaches_the_broker_with_credentials(self):
        broker = SimulatedBroker()
        MqttPublisher("127.0.0.1", broker.port, username="user", password="pass", timeout_s=5).publish("hydra/ops/incidents/n", b'{"a":1}', 1)
        broker.thread.join(5)
        kind, topic, payload = broker.published
        self.assertEqual((kind & 0xF0, kind >> 1 & 3, topic, payload), (0x30, 1, "hydra/ops/incidents/n", b'{"a":1}'))
        self.assertIn(b"user", broker.connect_body)
        self.assertIn(b"pass", broker.connect_body)

    def test_a_refusing_broker_and_an_absent_one_are_notify_errors(self):
        broker = SimulatedBroker(connack_code=5)
        with self.assertRaises(NotifyError):
            MqttPublisher("127.0.0.1", broker.port, timeout_s=5).publish("t", b"x", 0)
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        with self.assertRaises(NotifyError):
            MqttPublisher("127.0.0.1", port, timeout_s=1).publish("t", b"x", 0)
        with self.assertRaises(NotifyError):
            MqttPublisher("127.0.0.1", port).publish("t", b"x", 2)


class MetricsTests(unittest.TestCase):
    def test_text_reports_open_by_severity_mttr_and_audit_counts(self):
        from hydra_umc_ops_agent.incident import MaintenanceIncident
        from hydra_umc_ops_agent.incident_store import TrackedIncident, save_incident_store

        def tracked(i, severity, first, resolved=None):
            incident = MaintenanceIncident(i, "n", first, severity, f"comp-{i}", "s", (), "sanitized", None, "c")
            return TrackedIncident(incident, first, first, 2, resolved)

        store = [tracked("a", "critical", "2000-01-01T00:00:00+00:00"), tracked("b", "warning", "2000-01-01T00:00:00+00:00"),
                 tracked("c", "warning", "2000-01-01T00:00:00+00:00", "2000-01-01T01:00:00+00:00"),
                 tracked("d", "info", "2000-01-01T00:00:00+00:00", "2000-01-01T03:00:00+00:00")]
        now = datetime(2000, 1, 1, 2, tzinfo=timezone.utc)
        text = render_metrics(store, MetricsConfig(enabled=True), audit_events=[{"event": "deploy-promoted"}, {"event": "deploy-promoted"}], now=now)
        self.assertIn('hydra_ops_agent_incidents_open{severity="critical"} 1', text)
        self.assertIn('hydra_ops_agent_incidents_open{severity="warning"} 1', text)
        self.assertIn("hydra_ops_agent_incidents_resolved 2", text)
        self.assertIn("hydra_ops_agent_incident_mttr_seconds 7200.000", text)  # (1 h + 3 h) / 2
        self.assertIn("hydra_ops_agent_incident_oldest_open_age_seconds 7200.000", text)
        self.assertIn('hydra_ops_agent_audit_events{event="deploy-promoted"} 2', text)
        self.assertNotIn("comp-a", text)  # nothing from an incident reaches a label
        with tempfile.TemporaryDirectory() as tmp:
            path, audit = Path(tmp) / "s.json", Path(tmp) / "a.jsonl"
            save_incident_store(store, path)
            append_event(audit, "deploy-promoted", {"x": 1})
            self.assertIn('{event="deploy-promoted"} 1', collect_metrics(MetricsConfig(enabled=True), path, audit))
            self.assertNotIn("audit_events", collect_metrics(MetricsConfig(enabled=True, include_audit=False), path, audit))

    def test_a_broken_store_is_up_zero_not_no_incidents_and_off_means_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            path.write_text("{broken", encoding="utf-8")
            self.assertIn("hydra_ops_agent_up 0", collect_metrics(MetricsConfig(enabled=True), path))
            with self.assertRaises(IncidentStoreError):
                collect_metrics(MetricsConfig(), path)

    def test_empty_store_has_zero_mttr(self):
        text = render_metrics([], MetricsConfig(enabled=True))
        self.assertIn("hydra_ops_agent_incident_mttr_seconds 0.000", text)


if __name__ == "__main__":
    unittest.main()
