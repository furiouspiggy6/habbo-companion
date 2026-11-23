"""Offline AST-extracted coverage for the Habbo-framed local Protocol Lab mock."""
import ast
import importlib.util
import ipaddress
import socketserver
import tempfile
import threading
from datetime import datetime
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parent.parent / 'Habbo_Companion.pyw'
TREE = ast.parse(SOURCE.read_text(encoding='utf-8'))
FUNCTION_NAMES = (
    'encode_vl64', 'decode_vl64', 'encode_b64', 'decode_b64',
    'validate_habbo_framing_frame', 'validate_habbo_header',
    'run_local_habbo_boofuzz',
)


def load_protocol_lab():
    nodes = [
        node for node in TREE.body
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTION_NAMES
    ]
    assert len(nodes) == len(FUNCTION_NAMES)
    namespace = {
        'Path': Path, 'threading': threading, 'socketserver': socketserver,
        'datetime': datetime, 'ipaddress': ipaddress,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'),
         namespace)
    return namespace


class HabboProtocolLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lab = load_protocol_lab()

    def test_known_vl64_vectors(self):
        vectors = {
            0: '40', 1: '41', -1: '45', 4: '0841',
        }
        for number, expected in vectors.items():
            with self.subTest(number=number):
                self.assertEqual(self.lab['encode_vl64'](number).hex(), expected)

    def test_known_b64_vectors(self):
        vectors = {
            0: '40', 1: '41', -1: '4041', 64: '0140',
        }
        for number, expected in vectors.items():
            with self.subTest(number=number):
                self.assertEqual(self.lab['encode_b64'](number).hex(), expected)

    def test_signed_round_trips(self):
        spread = (
            -(2 ** 31), -65536, -4096, -256, -64, -4, -1,
            0, 1, 2, 3, 4, 63, 64, 255, 256, 4096,
            65535, 65536, 2 ** 31 - 1,
        )
        for value in spread:
            with self.subTest(value=value):
                for codec in ('vl64', 'b64'):
                    encoded = self.lab['encode_' + codec](value)
                    decoded, end = self.lab['decode_' + codec](encoded)
                    self.assertEqual((decoded, end), (value, len(encoded)))

    def test_offsets_and_unterminated_fields(self):
        prefix = b'xx'
        for codec in ('vl64', 'b64'):
            value = self.lab['encode_' + codec](-256)
            decoded, end = self.lab['decode_' + codec](prefix + value, 2)
            self.assertEqual(decoded, -256)
            self.assertEqual(end, 2 + len(value))
        for broken in (b'\x08', b'\x08\x01', b''):
            with self.subTest(broken=broken):
                with self.assertRaises(ValueError):
                    self.lab['decode_vl64'](broken)
        with self.assertRaises(ValueError):
            self.lab['decode_b64'](b'\x01')

    def test_framing_and_declared_length(self):
        body = (
            (896).to_bytes(2, 'big') +
            self.lab['encode_vl64'](-64) +
            self.lab['encode_b64'](64)
        )
        frame = len(body).to_bytes(4, 'big') + body
        self.assertTrue(self.lab['validate_habbo_framing_frame'](frame))
        self.assertFalse(self.lab['validate_habbo_framing_frame'](
            (len(body) + 1).to_bytes(4, 'big') + body))
        self.assertFalse(self.lab['validate_habbo_framing_frame'](frame[:-1]))
        extended = body + b'\x41'
        self.assertFalse(self.lab['validate_habbo_framing_frame'](
            len(extended).to_bytes(4, 'big') + extended))
        self.assertFalse(self.lab['validate_habbo_framing_frame'](
            (8193).to_bytes(4, 'big') + b'\x00' * 8193))
        self.assertFalse(self.lab['validate_habbo_framing_frame'](b''))

    def test_header_range(self):
        for value in (0, 896, 0xffff):
            self.assertTrue(self.lab['validate_habbo_header'](value))
        for value in (-1, 0x10000, True, None, '896'):
            self.assertFalse(self.lab['validate_habbo_header'](value))

    @unittest.skipUnless(importlib.util.find_spec('boofuzz') is not None,
                         'boofuzz optional dependency not installed')
    def test_three_cases_use_only_pc_mock(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.lab['run_local_habbo_boofuzz'](
                seed_id=896, cases=3, output_dir=temp)
        self.assertGreater(result['requests'], 0)
        self.assertEqual(result['requests'],
                         result['accepted'] + result['rejected'])
        self.assertEqual(result['scope'], 'this-PC Habbo-framing mock only')
        self.assertEqual(result['bind_ip'], '127.0.0.1')


if __name__ == '__main__':
    unittest.main()
