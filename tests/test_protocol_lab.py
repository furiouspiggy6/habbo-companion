"""Offline tests for passive G-Earth metadata + loopback-only boofuzz lab."""
import ast
from pathlib import Path
import unittest

SOURCE=Path(__file__).resolve().parent.parent/'Habbo_Companion.pyw'
TREE=ast.parse(SOURCE.read_text(encoding='utf-8'))

def load_validator():
    node=next(node for node in TREE.body if isinstance(node,ast.FunctionDef)
              and node.name=='validate_local_habbo_frame')
    namespace={}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),namespace)
    return namespace['validate_local_habbo_frame']

class ProtocolLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator=staticmethod(load_validator())

    def test_synthetic_baseline(self):
        text=b'sample'
        body=(896).to_bytes(2,'big')+len(text).to_bytes(2,'big')+text
        frame=len(body).to_bytes(4,'big')+body
        self.assertTrue(self.validator(frame))

    def test_rejects_truncated_frame(self):
        text=b'sample'
        body=(896).to_bytes(2,'big')+len(text).to_bytes(2,'big')+text
        frame=len(body).to_bytes(4,'big')+body
        self.assertFalse(self.validator(frame[:-1]))

    def test_rejects_mismatched_string_length(self):
        body=(896).to_bytes(2,'big')+(999).to_bytes(2,'big')+b'sample'
        self.assertFalse(self.validator(len(body).to_bytes(4,'big')+body))

    def test_rejects_large_declared_length(self):
        self.assertFalse(self.validator((9000).to_bytes(4,'big')+b'\\x00'*5))

    def test_rejects_short_frames(self):
        self.assertFalse(self.validator(b'\\x00'))
        self.assertFalse(self.validator(b''))

    def test_runtime_hardcodes_loopback(self):
        fuzzer=next(node for node in TREE.body if isinstance(node,ast.FunctionDef)
                    and node.name=='run_local_boofuzz')
        calls=[node for node in ast.walk(fuzzer) if isinstance(node,ast.Call)]
        tcp_calls=[node for node in calls
                   if isinstance(node.func,ast.Name) and node.func.id=='TCPSocketConnection']
        self.assertEqual(len(tcp_calls),1)
        self.assertIsInstance(tcp_calls[0].args[0],ast.Constant)
        self.assertEqual(tcp_calls[0].args[0].value,'127.0.0.1')
        binds=[node for node in calls
               if isinstance(node.func,ast.Name) and node.func.id=='LoopbackServer']
        self.assertEqual(len(binds),1)
        self.assertIsInstance(binds[0].args[0],ast.Tuple)
        self.assertEqual(binds[0].args[0].elts[0].value,'127.0.0.1')

    def test_existing_gearth_hook_remains_passive_for_lab(self):
        cls=next(n for n in TREE.body if isinstance(n,ast.ClassDef)
                 and n.name=='ChatOverlayApp')
        worker=next(n for n in cls.body if isinstance(n,ast.FunctionDef)
                    and n.name=='_packet_worker')
        source=ast.unparse(worker)
        self.assertIn("'fuzz_observation'",source)
        self.assertIn('msg.packet.header_id()',source)
        self.assertNotIn("send_to_server(packet)",source.split("if self.fuzz_monitoring:",1)[1].split("if not (self.packet_active",1)[0])

if __name__=='__main__':
    unittest.main()
