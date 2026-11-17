"""Offline tests for passive connected-server display in Protocol Lab."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'Habbo_Companion.pyw'
TREE = ast.parse(SOURCE.read_text(encoding='utf-8'))
APP = next(n for n in TREE.body if isinstance(n, ast.ClassDef)
           and n.name == 'ChatOverlayApp')
METHOD = next(n for n in APP.body if isinstance(n, ast.FunctionDef)
              and n.name == '_fuzz_refresh_connected_server')
NAMESPACE = {}
exec(compile(ast.Module(body=[METHOD], type_ignores=[]),
             str(SOURCE), 'exec'), NAMESPACE)
refresh = NAMESPACE[METHOD.name]


class Var:
    def __init__(self, value=''):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class ReadOnlySocket:
    def __init__(self, peer):
        self.peer = peer
        self.reads = 0

    def getpeername(self):
        self.reads += 1
        return self.peer

    def sendall(self, *_):
        raise AssertionError('Never transmit to a live game socket')


class TestProtocolLabEndpoint(unittest.TestCase):
    @staticmethod
    def make_app(sessions=None, connected=False):
        class Context:
            pass
        app = Context()
        app._tcp_sessions = sessions or {}
        app._habbo_session_connected = connected
        app.gearth_host_var = Var('game-us.habbo.com')
        app.gearth_game_port_var = Var('30000')
        app.fuzz_connected_server_var = Var()
        return app

    def test_read_actual_direct_tcp_peer_without_sending(self):
        sock = ReadOnlySocket(('203.0.113.10', 30000))
        session = type('Session', (), {'authenticated': True, 'sock': sock})()
        app = self.make_app({'abc': session})
        refresh(app)
        self.assertIn('203.0.113.10:30000', app.fuzz_connected_server_var.get())
        self.assertIn('read-only', app.fuzz_connected_server_var.get())
        self.assertEqual(sock.reads, 1)

    def test_gearth_setting_explicitly_unverified(self):
        app = self.make_app(connected=True)
        refresh(app)
        self.assertIn('game-us.habbo.com:30000', app.fuzz_connected_server_var.get())
        self.assertIn('unverified', app.fuzz_connected_server_var.get())

    def test_no_connection_does_not_infer_server(self):
        app = self.make_app()
        refresh(app)
        self.assertIn('none detected', app.fuzz_connected_server_var.get())

    def test_unauthenticated_tcp_socket_not_reported(self):
        sock = ReadOnlySocket(('203.0.113.10', 30000))
        session = type('Session', (), {'authenticated': False, 'sock': sock})()
        app = self.make_app({'abc': session})
        refresh(app)
        self.assertIn('none detected', app.fuzz_connected_server_var.get())
        self.assertEqual(sock.reads, 0)

    def test_fuzzer_targets_only_local_mock(self):
        lab = next(n for n in TREE.body if isinstance(n, ast.FunctionDef)
                   and n.name == 'run_local_boofuzz')
        body = ast.unparse(lab)
        self.assertIn('validate_owned_lab_ip', body)
        self.assertIn('LoopbackServer((bind_ip, 0)', body)
        self.assertIn('TCPSocketConnection(bind_ip,', body)


if __name__ == '__main__':
    unittest.main()
