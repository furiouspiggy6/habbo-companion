"""Arcturus emulator tests: offline framing, safety boundaries and boofuzz."""
import importlib.util
import runpy
import struct
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
APP=runpy.run_path(str(ROOT/'Habbo_Companion.pyw'),
                   run_name='arcturus_local_emulator_test')
BOOFUZZ_AVAILABLE=importlib.util.find_spec('boofuzz') is not None


class LocalArcturusEncoderTests(unittest.TestCase):
    def test_vl64_known_single_and_multibyte_values(self):
        encode=APP['ArcturusVL64Encoder']().encode
        self.assertEqual(encode(struct.pack('>i',0)),b'\x40')
        self.assertEqual(encode(struct.pack('>i',1)),b'\x41')
        self.assertEqual(encode(struct.pack('>i',-1)),b'\x45')
        self.assertEqual(encode(struct.pack('>i',4)),b'\x08\x41')
        self.assertNotEqual(encode(struct.pack('>i',0x7fffffff)),b'')
        self.assertLessEqual(len(encode(struct.pack('>i',-0x80000000))),6)
        with self.assertRaises(ValueError):
            encode(b'\x00\x01')

    def test_b64_never_emits_outside_character_alphabet(self):
        enc=APP['ArcturusB64Encoder']()
        alphabet=set(APP['ARCTURUS_B64_ALPHABET'])
        self.assertEqual(enc.encode(b'0'),b'A')
        self.assertEqual(enc.encode(b'1'),b'B')
        self.assertEqual(enc.encode(b'-1'),b'@B')
        for v in range(-63,64):
            result=enc.encode(str(v).encode('ascii'))
            digits=result[1:] if v<0 else result
            self.assertTrue(digits)
            self.assertTrue(all(d in alphabet for d in digits))
        for value in (b'64',b'-64',b'not-an-int',b'20.2',b'\xff'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                enc.encode(value)

    def test_reject_guessing_header_id_and_excessive_cases(self):
        validate=APP['validate_arcturus_emulator_parameters']
        self.assertEqual(validate(42,20),(42,20))
        for header in (-1,65536,'42',None,True):
            with self.subTest(header=header),self.assertRaises(ValueError):
                validate(header,1)
        for cases in (0,51,'10',False):
            with self.subTest(cases=cases),self.assertRaises(ValueError):
                validate(42,cases)
        self.assertEqual(APP['ARCTURUS_EMULATOR_HOST'],'127.0.0.1')
        self.assertEqual(APP['ARCTURUS_EMULATOR_PORT'],30000)

    @unittest.skipUnless(BOOFUZZ_AVAILABLE,'boofuzz optional dependency')
    def test_boofuzz_renders_correct_big_endian_length_for_header_and_body(self):
        preview=APP['preview_arcturus_emulator_packet']
        with mock.patch('socket.create_connection',
                        side_effect=AssertionError('Preview opened a network socket')):
            for header in (0,1,896,65535):
                frame=preview(header)
                self.assertEqual(int.from_bytes(frame[:4],'big'),len(frame)-4)
                self.assertEqual(int.from_bytes(frame[4:6],'big'),header)
                self.assertLessEqual(len(frame),24)

    @unittest.skipUnless(BOOFUZZ_AVAILABLE,'boofuzz optional dependency')
    def test_run_targets_only_loopback_and_checks_emulator_first(self):
        expected=('127.0.0.1',30000)
        def check(address, timeout):
            self.assertEqual(address,expected)
            self.assertLessEqual(timeout,1)
            raise ConnectionRefusedError('test emulator not running')
        with mock.patch('socket.create_connection',side_effect=check):
            with self.assertRaises(ConnectionRefusedError):
                APP['run_arcturus_emulator_boofuzz'](header_id=3,cases=2)


if __name__=='__main__':
    unittest.main()
