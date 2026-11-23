"""Verify Packet Viewer automatically captures only when a G-Earth session is ready."""
import ast
import time
import types
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parent.parent / 'Habbo_Companion.pyw'
TREE = ast.parse(SOURCE.read_text(encoding='utf-8'))
APP = next(node for node in TREE.body
           if isinstance(node, ast.ClassDef) and node.name == 'ChatOverlayApp')


def extract_method(name):
    node = next(node for node in APP.body
                if isinstance(node, ast.FunctionDef) and node.name == name)
    scope = {'time': time}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'),
         scope)
    return scope[name]


def fake_app(capture=True, game_window=None):
    state = types.SimpleNamespace()
    state.packet_started = False
    state._packet_auto_retry_after = 0.0
    state.root = types.SimpleNamespace(winfo_id=lambda: 10)
    state.overlay = types.SimpleNamespace(winfo_id=lambda: 11)
    state.tracker = types.SimpleNamespace(find=lambda exclusions: game_window)
    state.room_id = None
    state.packet_auto_capture_var = types.SimpleNamespace(get=lambda: capture)
    state.packet_connection_status = Mock()
    state._connect_gearth = Mock(return_value=True)
    return state


class PacketAutoCaptureTests(TestCase):
    def test_attach_with_capture_on_by_default(self):
        app = fake_app(capture=True)
        extract_method('_maybe_auto_connect_packet_tools')(app)
        app._connect_gearth.assert_called_once_with(capture=True)

    def test_disabled_preference_attaches_without_logging(self):
        app = fake_app(capture=False)
        extract_method('_maybe_auto_connect_packet_tools')(app)
        app._connect_gearth.assert_called_once_with(capture=False)

    def test_does_not_attach_mid_air_handshake(self):
        app = fake_app(capture=True, game_window=object())
        extract_method('_maybe_auto_connect_packet_tools')(app)
        app._connect_gearth.assert_not_called()
        app.packet_connection_status.set.assert_called_once()

    def test_turning_capture_on_changes_live_state_and_saves(self):
        method = extract_method('_save_packet_auto_capture')
        app = types.SimpleNamespace(
            packet_auto_capture_var=types.SimpleNamespace(get=lambda: True),
            config={}, save=Mock(), packet_started=True,
            _habbo_session_connected=True, packet_active=False,
            packet_status=Mock(), packet_connection_status=Mock())
        method(app)
        self.assertTrue(app.packet_active)
        self.assertTrue(app.config['packet_auto_capture'])
        app.save.assert_called_once()
        app.packet_connection_status.set.assert_called_once()

    def test_turning_capture_off_stops_pending_session_capture(self):
        method = extract_method('_save_packet_auto_capture')
        app = types.SimpleNamespace(
            packet_auto_capture_var=types.SimpleNamespace(get=lambda: False),
            config={}, save=Mock(), packet_started=True,
            _habbo_session_connected=False, packet_active=True,
            packet_status=Mock(), packet_connection_status=Mock())
        method(app)
        self.assertFalse(app.packet_active)
        self.assertFalse(app.config['packet_auto_capture'])

    def test_game_connection_enables_auto_capture(self):
        worker = next(node for node in APP.body
                      if isinstance(node, ast.FunctionDef) and
                      node.name == '_packet_worker')
        source = ast.unparse(worker)
        self.assertIn("self.config.get('packet_auto_capture', True)", source)
        self.assertIn('self.packet_active = True', source)

    def test_preference_is_available_in_packet_viewer(self):
        panel = next(node for node in APP.body
                     if isinstance(node, ast.FunctionDef) and
                     node.name == '_make_packet_panel')
        source = ast.unparse(panel)
        self.assertIn('Automatically capture packets when Habbo connects', source)
        self.assertIn('self.packet_connection_status', source)
