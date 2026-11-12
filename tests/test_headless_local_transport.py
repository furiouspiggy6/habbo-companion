"""Headless local network proof: distinct accounts and bounded frames.

Does not use Habbo.com, login credentials, packet headers or game sessions.
"""
from pathlib import Path
import json
import socket
import struct
import time
import unittest

import headless_transport as h


A = "ab1234567890"
B = "cd1234567890"
C = "ef1234567890"


class LocalFrameTests(unittest.TestCase):
    def test_length_prefixed_payload_roundtrips_and_limits(self):
        x, y = socket.socketpair()
        try:
            x.sendall(h.encode_message("PING", nonce="example"))
            msg = h.read_message(y)
            self.assertEqual(msg, {"kind": "PING", "nonce": "example"})
            self.assertEqual(h.encode_message("AUTH", account_id=A)[:4], h.MAGIC)
            with self.assertRaises(ValueError):
                h.encode_message("bad")
            with self.assertRaises(ValueError):
                h.encode_message("PING", huge="z" * (h.MAX_BODY + 1))
        finally:
            x.close()
            y.close()

    def test_rejects_invalid_and_oversize_frame(self):
        x, y = socket.socketpair()
        try:
            x.sendall(b"BAD!" + struct.pack("!I", 12) + b"x" * 12)
            with self.assertRaises(h.ProtocolError):
                h.read_message(y)
        finally:
            x.close()
            y.close()
        x, y = socket.socketpair()
        try:
            x.sendall(h.MAGIC + struct.pack("!I", h.MAX_BODY + 1))
            with self.assertRaises(h.ProtocolError):
                h.read_message(y)
        finally:
            x.close()
            y.close()

    def test_rejects_non_json_payload(self):
        x, y = socket.socketpair()
        try:
            x.sendall(h.MAGIC + struct.pack("!I", 5) + b"hello")
            with self.assertRaises(h.ProtocolError):
                h.read_message(y)
        finally:
            x.close()
            y.close()


class HeadlessLocalSessionTests(unittest.TestCase):
    def setUp(self):
        self.server = h.LocalHeadlessTestServer([A, B])
        self.port = self.server.start()
        self.clients = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for c in self.clients:
            c.close()
        self.server.stop()

    def connect(self, account_id, ticket=None):
        c = h.HeadlessLocalSession(account_id)
        self.clients.append(c)
        c.connect(h.HOST, self.port, ticket if ticket is not None
                  else self.server.tickets[account_id])
        return c

    def test_independent_auth_and_ping_without_any_windows(self):
        ca = self.connect(A)
        cb = self.connect(B)
        self.assertEqual(ca.status, "Local test authenticated")
        self.assertTrue(ca.ping())
        self.assertTrue(cb.ping())
        self.assertEqual(self.server.authenticated_ids, {A, B})
        ca.close()
        self.assertTrue(cb.ping())
        end = time.monotonic() + 1.0
        while A in self.server.authenticated_ids and time.monotonic() < end:
            time.sleep(0.01)
        self.assertEqual(self.server.authenticated_ids, {B})

    def test_wrong_profile_token_cannot_authenticate(self):
        incorrect = self.server.tickets[B]
        with self.assertRaises(h.ProtocolError):
            self.connect(A, incorrect)
        self.assertNotIn(A, self.server.authenticated_ids)
        valid = self.connect(B)
        self.assertTrue(valid.ping())

    def test_invalid_or_replayed_ticket_rejected(self):
        token = self.server.tickets[A]
        ca = self.connect(A)
        with self.assertRaises(h.ProtocolError):
            self.connect(A, token)
        self.assertTrue(ca.ping())
        ca.close()
        with self.assertRaises(h.ProtocolError):
            self.connect(A, token)

    def test_no_external_host_or_tokenless_connection(self):
        self.assertRaises(ValueError,
                          h.LocalHeadlessTestServer, [A], "0.0.0.0")
        c = h.HeadlessLocalSession(A)
        with self.assertRaises(ValueError):
            c.connect("habbo.com", 30000, "placeholder")
        with self.assertRaises(ValueError):
            c.connect("127.0.0.1", self.port, "")
        self.assertNotIn(A, self.server.authenticated_ids)

    def test_server_token_never_in_auth_ack_or_ping(self):
        token = self.server.tickets[A]
        ca = self.connect(A)
        self.assertTrue(ca.ping())
        self.assertNotIn(token, repr(ca.__dict__))
        self.assertEqual(ca.status, "Local test authenticated")


class MultiAccountManagerTests(unittest.TestCase):
    def test_connects_two_accounts_and_disconnects_all(self):
        server = h.LocalHeadlessTestServer([A, B, C])
        server.start()
        self.addCleanup(server.stop)
        manager = h.HeadlessLocalManager()
        self.addCleanup(manager.disconnect_all)
        states = manager.connect_all(server, [A, B, C])
        self.assertEqual(set(states), {A, B, C})
        self.assertTrue(all(s.endswith("ping OK") for s in states.values()))
        self.assertEqual(set(server.authenticated_ids), {A, B, C})
        self.assertTrue(all(s.endswith("ping OK")
                            for s in manager.ping_all().values()))
        # Clicking Connect all a second time must not replay test tickets
        # or replace healthy sockets.
        original_sockets = dict(manager.sessions)
        repeat = manager.connect_all(server, [A, B, C])
        self.assertTrue(all(s.endswith("ping OK") for s in repeat.values()))
        self.assertEqual(original_sockets, manager.sessions)
        manager.disconnect_all()
        end = time.monotonic() + 1.0
        while server.authenticated_ids and time.monotonic() < end:
            time.sleep(0.01)
        self.assertFalse(server.authenticated_ids)

    def test_duplicate_profile_ids_and_more_than_16_refused(self):
        with self.assertRaises(ValueError):
            h.LocalHeadlessTestServer([A, A])
        with self.assertRaises(ValueError):
            h.HeadlessLocalSession("../habbopw")
        with self.assertRaises(ValueError):
            h.LocalHeadlessTestServer([f"{i:012x}" for i in range(17)])
        manager = h.HeadlessLocalManager()
        with self.assertRaises(ValueError):
            manager.connect_all(None, [A, A])
        with self.assertRaises(ValueError):
            manager.connect_all(None, [])

    def test_local_test_module_does_not_reach_official_habbo(self):
        source = (Path(__file__).resolve().parents[1] /
                  "headless_transport.py").read_text(encoding="utf-8")
        self.assertNotIn("https://www.habbo.com", source)
        self.assertNotIn("game-us.habbo.com", source)
        self.assertNotIn("getAllCookies", source)
        self.assertIn("host != HOST", source)
        self.assertIn('scope="local-test"', source)


class CompanionUiContractTests(unittest.TestCase):
    def test_ui_integration_and_cleanup(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "Habbo_Companion.pyw").read_text(encoding="utf-8")
        self.assertIn("self.notebook.add(headless,text='  Headless Test  ')", source)
        self.assertIn("self._make_headless_panel(headless)", source)
        self.assertIn("Start/reset local test server", source)
        self.assertIn("Connect all (local test)", source)
        self.assertIn("No Habbo.com network traffic", source)
        self.assertIn("self._headless_manager.disconnect_all()", source)
        self.assertIn("self._headless_server.stop()", source)
        self.assertNotIn("account_saved_login_read(account['id'])",
                         source.split("def _make_headless_panel(", 1)[1].split(
                             "def _make_accounts_panel(", 1)[0])

    def test_updater_includes_module_not_just_main_script(self):
        root = Path(__file__).resolve().parents[1]
        build = (root / "scripts" / "build_release.py").read_text(encoding="utf-8")
        update = (root / "Habbo_Update_Helper.py").read_text(encoding="utf-8")
        install = (root / "Install_Habbo_Companion.py").read_text(encoding="utf-8")
        self.assertIn('"headless_transport.py"', build)
        self.assertIn("'headless_transport.py'", update)
        self.assertIn("'headless_transport.py'", install)


if __name__ == "__main__":
    unittest.main()
