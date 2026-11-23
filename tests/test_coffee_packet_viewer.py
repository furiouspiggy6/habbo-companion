"""Offline regression coverage for locally injected Coffee Pass Loop viewer events."""
import ast
import queue
import re
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parent.parent / "Habbo_Companion.pyw"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
APP = next(n for n in TREE.body if isinstance(n, ast.ClassDef)
           and n.name == "ChatOverlayApp")


def extract_function(name):
    node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef)
                and n.name == name)
    scope = {"re": re}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"),
         scope)
    return scope[name]


def extract_method(name):
    node = next(n for n in APP.body if isinstance(n, ast.FunctionDef)
                and n.name == name)
    scope = {"re": re, "datetime": datetime, "time": time,
             "queue": queue, "format_coffee_packet_viewer_event":
                 extract_function("format_coffee_packet_viewer_event"),
             "coffee_delay_ms": lambda interval: 50,
             "coffee_delivery_text": lambda *args: "request sent"}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"),
         scope)
    return scope[name]


class FakeTree:
    def __init__(self):
        self.rows = {}
        self.serial = 0
        self.selected = ()

    def insert(self, parent, where, values):
        self.serial += 1
        key = str(self.serial)
        self.rows[key] = tuple(values)
        return key

    def get_children(self):
        return list(self.rows)

    def delete(self, *items):
        for key in items:
            self.rows.pop(key, None)

    def selection(self):
        return self.selected

    def item(self, key, option):
        if option == "values":
            return self.rows[key]
        raise AssertionError(option)


def fake_viewer(*events, active=True, needle=""):
    tree = FakeTree()
    packet_queue = queue.Queue()
    for event in events:
        packet_queue.put_nowait(event)
    status = Mock()
    app = SimpleNamespace(
        root=SimpleNamespace(winfo_exists=lambda: True,
                             after=lambda *args: None),
        packet_queue=packet_queue,
        packet_active=active,
        packet_data=[],
        packet_filter_var=SimpleNamespace(get=lambda: needle),
        packet_tree=tree, _pump_packets=lambda: None,
        manipulator_status=status)
    return app


class CoffeeViewerTests(TestCase):
    def test_pickup_and_pass_summaries(self):
        format_event = extract_function("format_coffee_packet_viewer_event")
        pickup = format_event(
            "{out:UseFurniture}{i:476989081}{i:0}", True)
        passed = format_event(
            "{out:PassCarryItem}{i:68808036}", True)
        self.assertIn("UseFurniture → furniture 476989081", pickup)
        self.assertIn("PassCarryItem → recipient 68808036", passed)
        for detail in (pickup, passed):
            self.assertIn("server/recipient unverified", detail)
            self.assertIn("[Coffee Pass Loop]", detail)
            self.assertNotIn("server confirmed", detail)

    def test_failed_and_unknown_sends_do_not_echo_sensitive_data(self):
        format_event = extract_function("format_coffee_packet_viewer_event")
        self.assertIn("local G-Earth send failed", format_event(
            "{out:PassCarryItem}{i:68808036}", False))
        result = format_event("{out:Secret}{s:private-access-token}", False)
        self.assertIn("unrecognized generated action", result)
        self.assertNotIn("private-access-token", result)

    def test_pump_intercepted_and_local_events_have_distinct_source(self):
        format_event = extract_function("format_coffee_packet_viewer_event")
        local = format_event("{out:UseFurniture}{i:476989081}{i:0}", True)
        app = fake_viewer(
            ("packet", "17:10:18", "Incoming", "{in:Something}{i:1}"),
            ("packet_local", "17:10:19", "Outgoing", local))
        extract_method("_pump_packets")(app)
        self.assertEqual(len(app.packet_data), 2)
        self.assertEqual(
            [entry[3] for entry in app.packet_tree.rows.values()],
            ["G-Earth", "Coffee Pass Loop"])
        self.assertEqual(
            [entry[1] for entry in app.packet_tree.rows.values()],
            ["Incoming", "Outgoing"])

    def test_pause_suppresses_local_viewer_events(self):
        format_event = extract_function("format_coffee_packet_viewer_event")
        app = fake_viewer(("packet_local", "17:10:20", "Outgoing",
                           format_event("{out:PassCarryItem}{i:68808036}", True)),
                          active=False)
        extract_method("_pump_packets")(app)
        self.assertEqual(app.packet_data, [])
        self.assertEqual(app.packet_tree.rows, {})

    def test_search_and_maximum_500_records(self):
        format_event = extract_function("format_coffee_packet_viewer_event")
        detail = format_event("{out:UseFurniture}{i:476989024}{i:0}", True)
        app = fake_viewer(*[
            ("packet_local", "17:10:20", "Outgoing", detail) for _ in range(510)
        ], needle="coffee")
        pump = extract_method("_pump_packets")
        for _ in range(4):
            pump(app)
        self.assertEqual(len(app.packet_data), 500)
        self.assertEqual(len(app.packet_tree.rows), 500)

    def test_local_summary_cannot_be_loaded_for_replay(self):
        app = fake_viewer()
        key = app.packet_tree.insert("", "end", values=(
            "17:10:21", "Outgoing", "[Coffee Pass Loop] UseFurniture",
            "Coffee Pass Loop"))
        app.packet_tree.selected = (key,)
        extract_method("_load_packet_for_sending")(app)
        app.manipulator_status.set.assert_called_once()
        self.assertIn("not replayable",
                      app.manipulator_status.set.call_args.args[0])

    def test_default_export_omits_local_ids_but_names_action(self):
        export = extract_function("packet_export_record")
        detail = extract_function("format_coffee_packet_viewer_event")(
            "{out:PassCarryItem}{i:68808036}", True)
        line = export("17:10:22", "Outgoing", detail)
        self.assertIn("type PassCarryItem", line)
        self.assertIn("payload omitted", line)
        self.assertNotIn("68808036", line)

    def test_actual_coffee_tick_queues_local_request(self):
        method = extract_method("_coffee_loop_tick")
        captured = []
        packet = SimpleNamespace(is_incomplete_packet=lambda: False,
                                 is_corrupted=lambda: False)
        extension = SimpleNamespace(
            string_to_packet=lambda expr: packet,
            send_to_server=lambda pkt: True)
        app = SimpleNamespace(
            _coffee_after_id=None, _coffee_running=True,
            _coffee_generation=2, _coffee_wait_for_hand=False,
            _coffee_ack_phase=None, packet_started=True,
            packet_extension=extension, _habbo_session_connected=True,
            _coffee_group_active=False, _coffee_index=0,
            _coffee_sequence=(
                "{out:UseFurniture}{i:476989081}{i:0}",
                "{out:PassCarryItem}{i:68808036}"),
            _coffee_sent=0, _coffee_recorder=None,
            _coffee_speed_active=False, _coffee_pass_requests=0,
            _coffee_completed=0, _coffee_limit=0, _coffee_interval=0.1,
            _coffee_target_name="", packet_active=True,
            _coffee_target_room_index=None,
            _coffee_carry_observations=0, _coffee_last_pass_at=0.0,
            coffee_status_var=Mock(), coffee_delivery_var=Mock(),
            root=SimpleNamespace(after=lambda *args: 5),
            _packet_put=lambda item: captured.append(item),
            _stop_coffee_loop=lambda reason: None)
        method(app, 2)
        method(app, 2)
        self.assertEqual(app._coffee_sent, 2)
        self.assertEqual([item[0] for item in captured],
                         ["packet_local", "packet_local"])
        self.assertIn("UseFurniture", captured[0][3])
        self.assertIn("PassCarryItem", captured[1][3])
        self.assertTrue(all("unverified" in item[3] for item in captured))
