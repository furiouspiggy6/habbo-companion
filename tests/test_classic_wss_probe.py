"""Unauthenticated official Habbo Classic WebSocket reachability checks.

Offline only: these tests NEVER connect to the Internet or use account data.
"""
import base64
import hashlib
import re
import ssl
import unittest
from pathlib import Path
from unittest import mock

import habbo_tcp as tcp


def response(key, code=101, protocol="habbo-classic", accept_override=None):
    accept = accept_override or base64.b64encode(hashlib.sha1(
        (key + tcp._CLASSIC_WS_GUID).encode("ascii")).digest()).decode("ascii")
    return (
        "HTTP/1.1 " + str(code) + " Switching Protocols\r\n"
        "Connection: Upgrade\r\n"
        "Upgrade: websocket\r\n"
        "Sec-WebSocket-Accept: " + accept + "\r\n"
        "Sec-WebSocket-Protocol: " + protocol + "\r\n"
        "\r\n"
    ).encode("ascii")


class FakeTCP:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def settimeout(self, value):
        pass


class FakeTLS(FakeTCP):
    def __init__(self, good_response=True):
        self.sent = []
        self.reply = None
        self.good_response = good_response

    def sendall(self, data):
        self.sent.append(data)
        if data.startswith(b"GET /websocket"):
            m = re.search(rb"Sec-WebSocket-Key: ([A-Za-z0-9+/=]+)", data)
            if not m:
                raise AssertionError("Missing WebSocket key")
            key = m.group(1).decode("ascii")
            self.reply = (response(key) if self.good_response else response(
                key, protocol="wrong-protocol"))

    def recv(self, limit):
        if self.reply is None:
            raise AssertionError("Read before upgrade")
        value, self.reply = self.reply[:limit], self.reply[limit:]
        return value


class FakeContext:
    def __init__(self, tls):
        self.tls = tls
        self.hostname = None

    def wrap_socket(self, sock, server_hostname):
        self.hostname = server_hostname
        return self.tls


class TestClassicWebSocketProbe(unittest.TestCase):
    def test_upgrade_request_uses_fixed_host_and_no_credentials(self):
        key = base64.b64encode(b"x" * 16).decode("ascii")
        req = tcp._classic_ws_request(key).decode("ascii")
        self.assertTrue(req.startswith("GET /websocket HTTP/1.1\r\n"))
        self.assertIn("Host: game-us.habbo.com:30001\r\n", req)
        self.assertIn("Sec-WebSocket-Protocol: habbo-classic\r\n", req)
        self.assertIn("Origin: https://www.habbo.com\r\n", req)
        self.assertNotIn("Cookie:", req)
        self.assertNotIn("Authorization:", req)
        self.assertNotIn("SSO", req)
        self.assertNotIn("Password", req)
        with self.assertRaises(ValueError):
            tcp._classic_ws_request("unsafe\r\nCookie: bad")

    def test_upgrade_validation_requires_101_accept_and_subprotocol(self):
        key = base64.b64encode(b"a" * 16).decode("ascii")
        self.assertTrue(tcp._classic_ws_upgrade_response(response(key), key))
        for body in (
            response(key, code=403),
            response(key, protocol="wrong"),
            response(key, accept_override="invalid"),
            b"HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\n\r\n",
            b"not-http",
        ):
            with self.subTest(body=body[:40]):
                with self.assertRaises(tcp.HabboTcpError):
                    tcp._classic_ws_upgrade_response(body, key)

    def test_network_probe_verifies_certificate_and_closes_without_login(self):
        fake_tls = FakeTLS()
        context = FakeContext(fake_tls)
        with mock.patch.object(tcp.socket, "create_connection",
                               return_value=FakeTCP()) as dial, \
             mock.patch.object(tcp.ssl, "create_default_context",
                               return_value=context):
            result = tcp.probe_classic_websocket(timeout=3)
        self.assertIn("HTTP 101", result)
        self.assertIn("No login attempted", result)
        dial.assert_called_once_with((tcp.CLASSIC_WS_HOST,
                                      tcp.CLASSIC_WS_PORT), timeout=3)
        self.assertEqual(context.hostname, tcp.CLASSIC_WS_HOST)
        self.assertEqual(len(fake_tls.sent), 2)
        self.assertEqual(fake_tls.sent[1][0:2], b"\x88\x82")
        self.assertEqual(len(fake_tls.sent[1]), 8)
        self.assertNotIn(b"Cookie:", b"".join(fake_tls.sent))
        self.assertNotIn(b"SSO", b"".join(fake_tls.sent))

    def test_rejects_missing_subprotocol_before_claiming_success(self):
        tls = FakeTLS(good_response=False)
        with mock.patch.object(tcp.socket, "create_connection", return_value=FakeTCP()), \
             mock.patch.object(tcp.ssl, "create_default_context",
                               return_value=FakeContext(tls)):
            with self.assertRaisesRegex(tcp.HabboTcpError, "subprotocol"):
                tcp.probe_classic_websocket()

    def test_tls_failure_classified_without_leaking_socket_error(self):
        class BrokenSSL:
            def wrap_socket(self, sock, server_hostname):
                raise ssl.SSLError("private auth string")
        with mock.patch.object(tcp.socket, "create_connection", return_value=FakeTCP()), \
             mock.patch.object(tcp.ssl, "create_default_context",
                               return_value=BrokenSSL()):
            with self.assertRaises(tcp.HabboTcpError) as caught:
                tcp.probe_classic_websocket()
        self.assertIn("TLS handshake/certificate failed", str(caught.exception))
        self.assertNotIn("private auth string", str(caught.exception))

    def test_widget_connected_and_bundle_self_contained(self):
        source = (Path(__file__).resolve().parents[1] /
                  "Habbo_Companion.pyw").read_text(encoding="utf-8")
        self.assertIn("Test Classic WSS connection (no login)", source)
        self.assertIn("self._tcp_test_classic_websocket", source)
        self.assertIn("('classic_ws_probe',", source)
        from scripts.build_release import bundled_application
        bundle = bundled_application().decode("utf-8")
        self.assertIn("def probe_classic_websocket(", bundle)
        self.assertNotIn("from habbo_tcp import", bundle)
        compile(bundle, "Habbo_Companion.pyw", "exec")


if __name__ == "__main__":
    unittest.main()
