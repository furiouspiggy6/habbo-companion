import sys
import types
import unittest
from unittest.mock import Mock, patch

import habbo_tcp as tcp


class SocksProxyTests(unittest.TestCase):
    def test_off_uses_original_direct_socket(self):
        with patch.object(tcp.socket, "create_connection") as dial:
            self.assertIs(tcp.open_game_socket(12), dial.return_value)
            dial.assert_called_once_with((tcp.TCP_HOST, tcp.TCP_PORT), timeout=12)

    def test_on_uses_configured_proxy(self):
        module = types.ModuleType("python_socks.sync")
        module.Proxy = Mock()
        proxy = module.Proxy.from_url.return_value
        url = "socks5://127.0.0.1:1080"
        with patch.dict(sys.modules, {"python_socks.sync": module}), \
                patch.object(tcp.socket, "create_connection") as direct:
            self.assertIs(tcp.open_game_socket(12, url), proxy.connect.return_value)
            module.Proxy.from_url.assert_called_once_with(url)
            proxy.connect.assert_called_once_with(
                dest_host=tcp.TCP_HOST, dest_port=tcp.TCP_PORT, timeout=12)
            direct.assert_not_called()
            proxy.connect.side_effect = OSError("private endpoint detail")
            with self.assertRaisesRegex(tcp.HabboTcpError, "SOCKS5 connection failed"):
                tcp.open_game_socket(12, url)
            direct.assert_not_called()

    def test_invalid_endpoint_does_not_dial(self):
        with patch.object(tcp.socket, "create_connection") as dial:
            for url in ("", "http://localhost:1080", "socks5://localhost",
                        "socks5://a:b@localhost:1080", "socks5://localhost:65536"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    tcp.open_game_socket(12, url)
            dial.assert_not_called()
