"""Offline tests for the real-transport adapter. NEVER contact Habbo.com."""
import socket
import struct
import threading
import time
import unittest
from unittest import mock

import habbo_tcp as tcp


class ProtocolTests(unittest.TestCase):
    def test_binary_frame_string_and_sizes(self):
        self.assertEqual(tcp._frame(4000, tcp._string("test")),
                         struct.pack(">IHH", 8, 4000, 4) + b"test")
        self.assertEqual(tcp._decode_string(tcp._string("Habbo!")),
                         ("Habbo!", 8))
        with self.assertRaises(tcp.HabboTcpError):
            tcp._decode_string(b"\x00\xffx")
        with self.assertRaises(ValueError):
            tcp._frame(1, b"a" * tcp.TCP_MAX_FRAME)

    def test_cipher_has_independent_mutable_stream_states(self):
        key = b"independent-key"
        plain = b"\x01\x02\x03\x04" * 32
        writer = tcp._ArcFour(key)
        encrypted = writer.apply(plain[:40]) + writer.apply(plain[40:])
        reader = tcp._ArcFour(key)
        self.assertEqual(reader.apply(encrypted), plain)
        other = tcp._ArcFour(key, inbound=True)
        self.assertNotEqual(other.apply(encrypted), plain)

    def test_invalid_sso_and_bad_rsa_unpad_rejected(self):
        with self.assertRaises(tcp.HabboTcpError):
            tcp._rsa_decipher_decimal("00")
        with self.assertRaises(ValueError):
            tcp.HabboTcpSession("../credentials")
        with self.assertRaises(ValueError):
            tcp.HabboTcpSession("a" * 12).connect("not-a-ticket")

    def test_http_ticket_request_restricted_to_official_site(self):
        with self.assertRaises(ValueError):
            tcp._official_request("https://attacker.example")
        with mock.patch.object(tcp, "_official_request",
                               return_value=b'{"ticket":"hhus.0123456789.V4"}') as request:
            ticket = tcp.fetch_habbo_sso_ticket("id_abcdef", "token_abcdef")
        self.assertEqual(ticket, "hhus.0123456789.V4")
        args, kwargs = request.call_args
        self.assertEqual(args[0], tcp.TCP_SSO_URL)
        self.assertEqual(kwargs["method"], "POST")
        self.assertIn("session.id=id_abcdef", kwargs["headers"]["Cookie"])
        self.assertNotIn("id_abcdef", repr(ticket))
        with self.assertRaises(ValueError):
            tcp.fetch_habbo_sso_ticket("bad;cookie", "safe")

    def test_official_release_fallback_without_network(self):
        with mock.patch.object(tcp, "_official_request",
                               return_value=b"flash.client.version=WIN63-202611171530-99999999"):
            self.assertEqual(tcp.official_release(),
                             ("WIN63-202611171530-99999999", True))
        with mock.patch.object(tcp, "_official_request", side_effect=OSError):
            self.assertEqual(tcp.official_release(),
                             (tcp.TCP_FALLBACK_RELEASE, False))


class FakeGameSocket:
    def __init__(self, incoming):
        self.pending = bytearray(incoming)
        self.outgoing = []
        self.closed = False
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def recv(self, size):
        if self.closed:
            return b""
        if not self.pending:
            time.sleep(0.015)
            raise socket.timeout()
        take = min(size, 3)
        chunk = bytes(self.pending[:take])
        del self.pending[:take]
        return chunk

    def sendall(self, data):
        if self.closed:
            raise OSError("closed")
        self.outgoing.append(bytes(data))

    def shutdown(self, how):
        self.closed = True

    def close(self):
        self.closed = True


class FragmentedSocket:
    """Socket-shaped fake with deliberate fragmented reads and timeouts."""
    def __init__(self, events):
        self.events = list(events)
        self.closed = False

    def recv(self, length):
        if not self.events:
            raise AssertionError("Unexpected extra read")
        value = self.events.pop(0)
        if isinstance(value, BaseException):
            raise value
        chunk = value[:length]
        if len(value) > length:
            self.events.insert(0, value[length:])
        return chunk

    def shutdown(self, direction):
        self.closed = True

    def close(self):
        self.closed = True


class FrameReassemblyTests(unittest.TestCase):
    def test_fragmented_plaintext_header_and_body_with_timeouts(self):
        frame = tcp._frame(1593, b"the-payload")
        sock = FragmentedSocket([
            frame[:2], socket.timeout(), frame[2:4],
            frame[4:7], socket.timeout(), frame[7:],
        ])
        session = tcp.HabboTcpSession("abcdef123456")
        session.sock = sock
        with self.assertRaises(socket.timeout):
            session._read()
        self.assertEqual(session._recv_pending, frame[:2])
        self.assertIsNone(session._frame_size)
        with self.assertRaises(socket.timeout):
            session._read()
        self.assertEqual(session._frame_size, len(frame) - 4)
        self.assertEqual(session._recv_pending, frame[4:7])
        self.assertEqual(session._read(), (1593, b"the-payload"))
        self.assertIsNone(session._frame_size)
        self.assertFalse(session._recv_pending)
        session.close()

    def test_encrypted_frame_keystream_not_consumed_twice_on_retry(self):
        key = b"secret-session-key"
        first = tcp._frame(1234, b"one")
        second = tcp._frame(4321, b"two")
        # The inbound cipher is a stream: continuous stream across packets.
        encrypted = tcp._ArcFour(key, inbound=True).apply(first + second)
        sock = FragmentedSocket([
            encrypted[:1], socket.timeout(), encrypted[1:4],
            encrypted[4:6], socket.timeout(), encrypted[6:len(first)],
            encrypted[len(first):len(first)+4], encrypted[len(first)+4:],
        ])
        session = tcp.HabboTcpSession("abcdef123456")
        session.sock = sock
        session.rx = tcp._ArcFour(key, inbound=True)
        with self.assertRaises(socket.timeout):
            session._read()
        with self.assertRaises(socket.timeout):
            session._read()
        self.assertEqual(session._read(), (1234, b"one"))
        self.assertEqual(session._read(), (4321, b"two"))
        session.close()

    def test_oversized_frame_fails_and_disconnect_clears_pending(self):
        too_big = struct.pack(">I", tcp.TCP_MAX_FRAME + 1)
        session = tcp.HabboTcpSession("abcdef123456")
        session.sock = FragmentedSocket([too_big])
        with self.assertRaisesRegex(tcp.HabboTcpError, "frame length"):
            session._read()
        session._recv_pending.extend(b"secret")
        session._frame_size = 12
        session.close()
        self.assertEqual(session._recv_pending, bytearray())
        self.assertIsNone(session._frame_size)


class IdentityStream:
    def __init__(self, key, inbound=False):
        self.inbound = inbound

    def apply(self, data):
        return bytes(data)


class SessionIntegrationTests(unittest.TestCase):
    def test_real_frame_handshake_then_server_auth_ok_required(self):
        incoming = (tcp._frame(tcp.TCP_IN["init_dh"],
                               tcp._string("signed-p") + tcp._string("signed-g"))
                    + tcp._frame(tcp.TCP_IN["finish_dh"], tcp._string("signed-public")
                                 + b"\x00")
                    + tcp._frame(tcp.TCP_IN["auth_ok"]))
        fake = FakeGameSocket(incoming)
        messages = []
        session = tcp.HabboTcpSession("012345abcdef", status=messages.append)
        self.addCleanup(session.close)
        with (mock.patch.object(tcp.socket, "create_connection", return_value=fake) as dial,
              mock.patch.object(tcp, "official_release",
                                return_value=("WIN63-202611171530-99999999", True)),
              mock.patch.object(tcp, "_rsa_decipher_decimal",
                                side_effect=[2**255 - 19, 5, 7]),
              mock.patch.object(tcp, "_rsa_encipher_decimal",
                                return_value="encrypted"),
              mock.patch.object(tcp, "_ArcFour", IdentityStream)):
            session.connect("0123456789abcdef.V4")
        self.assertTrue(session.authenticated)
        self.assertIn("Authenticated with Habbo.com via direct TCP", messages)
        dial.assert_called_once_with((tcp.TCP_HOST, tcp.TCP_PORT), timeout=12)
        sent_ids = [struct.unpack_from(">H", packet, 4)[0]
                    for packet in fake.outgoing]
        self.assertEqual(sent_ids[:6],
                         [tcp.TCP_OUT["hello"], tcp.TCP_OUT["init_dh"],
                          tcp.TCP_OUT["finish_dh"], tcp.TCP_OUT["version"],
                          tcp.TCP_OUT["unique"], tcp.TCP_OUT["sso"]])
        self.assertEqual(sent_ids[6], tcp.TCP_OUT["info"])
        self.assertNotIn(b"0123456789abcdef.V4",
                         b"".join(fake.outgoing[:2]))

    def test_plain_tcp_without_authentication_is_not_logged_in(self):
        fake = FakeGameSocket(tcp._frame(tcp.TCP_IN["disconnect"]))
        session = tcp.HabboTcpSession("012345abcdef")
        with mock.patch.object(tcp.socket, "create_connection", return_value=fake), \
             mock.patch.object(tcp, "official_release",
                               return_value=(tcp.TCP_FALLBACK_RELEASE, True)):
            with self.assertRaises(tcp.HabboTcpError):
                session.connect("0123456789abcdef.V4")
        self.assertFalse(session.authenticated)
        self.assertTrue(fake.closed)


class RepositoryIntegrationTests(unittest.TestCase):
    def test_bundle_has_no_unresolved_transport_dependency(self):
        from scripts.build_release import bundled_application
        source = bundled_application().decode("utf-8")
        self.assertIn("class HabboTcpSession:", source)
        self.assertNotIn("from habbo_tcp import", source)
        compile(source, "Habbo_Companion.pyw", "exec")

    def test_ui_is_integrated_and_sessions_closed_on_exit(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] /
                  "Habbo_Companion.pyw").read_text(encoding="utf-8")
        self.assertIn("self.notebook.add(tcp,text='  Direct TCP  ')", source)
        self.assertIn("self._make_live_tcp_panel(tcp)", source)
        self.assertIn("if item[0] in ('tcp_state','tcp_connected'", source)
        self.assertIn("self._tcp_disconnect_all()", source)
        self.assertIn("account_session_cookie_write(", source)
        self.assertIn("Credential Manager", source)
        self.assertIn("tcp_auto_connect=False", source)
        self.assertIn("self.root.after(1200,self._tcp_auto_connect_startup)", source)
        self.assertIn("Automatically connect saved TCP accounts", source)
        self.assertIn("self._tcp_disconnect_all()", source.split("    def close(self):",1)[1])
        # The startup path must use the same vetted multi-account connector.
        startup = source.split("    def _tcp_auto_connect_startup(self):",1)[1].split(
            "    def _tcp_connect_one(",1)[0]
        self.assertIn("if not self.tcp_autostart_var.get():", startup)
        self.assertIn("self._tcp_connect_all()", startup)
        self.assertNotIn("account_login_browser(", startup)


if __name__ == "__main__":
    unittest.main()
