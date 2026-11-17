"""Tests for remote boofuzz mode: lab ownership proof, no Habbo SSO involved."""
import ast
import hashlib
import hmac
import importlib.util
import ipaddress
import socket
import socketserver
import tempfile
import threading
from datetime import datetime
from pathlib import Path
import unittest
import sys

ROOT=Path(__file__).resolve().parent.parent
SOURCE=ROOT/'Habbo_Companion.pyw'
TREE=ast.parse(SOURCE.read_text(encoding='utf-8'))
sys.path.insert(0,str(ROOT))
from lab_remote_server import make_server,read_exact,MAGIC

def get_functions(*names):
    nodes=[x for x in TREE.body if isinstance(x,ast.FunctionDef) and x.name in names]
    assert set(names)=={x.name for x in nodes}
    ctx={'ipaddress':ipaddress,'hmac':hmac,'hashlib':hashlib,'Path':Path,
         'datetime':datetime,'threading':threading,'socket':socket}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),ctx)
    return ctx

class RemoteLabTests(unittest.TestCase):
    def test_accepts_arbitrary_host_classes_but_demands_lab_key(self):
        f=get_functions('validate_remote_lab_target')['validate_remote_lab_target']
        key='a'*40
        self.assertEqual(f('127.0.0.1',39099,key)[:2],('127.0.0.1',39099))
        self.assertEqual(f('8.8.8.8',39099,key)[:2],('8.8.8.8',39099))
        for host in ('0.0.0.0','224.0.0.1','example.com'):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    f(host,39099,key)
        with self.assertRaises(ValueError):
            f('8.8.8.8',39099,'short')
        with self.assertRaises(ValueError):
            f('8.8.8.8',0,key)

    def test_remote_server_requires_signed_challenge(self):
        key='correct-'+'c'*40
        server=make_server('127.0.0.1',0,key)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with socket.create_connection(server.server_address,timeout=2) as conn:
                conn.settimeout(2)
                challenge=read_exact(conn,21)
                self.assertEqual(challenge[:5],MAGIC)
                conn.sendall(hmac.new(b'wrong-key',challenge[5:],hashlib.sha256).digest())
                self.assertEqual(conn.recv(3),b'')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @unittest.skipUnless(importlib.util.find_spec('boofuzz') is not None,
                         'Install boofuzz to enable end-to-end tests')
    def test_remote_boofuzz_authenticated_mock(self):
        key='remote-lab-'+('A'*40)
        server=make_server('127.0.0.1',0,key)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            ctx=get_functions('validate_remote_lab_target','run_remote_boofuzz')
            with tempfile.TemporaryDirectory() as root:
                result=ctx['run_remote_boofuzz'](
                    '127.0.0.1',server.server_address[1],key,
                    seed_id=896,cases=3,output_dir=root)
            self.assertEqual(result['scope'],'authenticated synthetic remote lab only')
            self.assertGreater(result['requests'],0)
            self.assertGreater(result['accepted']+result['rejected'],0)
            self.assertNotIn(key,str(result))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @unittest.skipUnless(importlib.util.find_spec('boofuzz') is not None,
                         'Install boofuzz to enable end-to-end tests')
    def test_wrong_key_never_sends_fuzz(self):
        key='remote-lab-'+('A'*40)
        server=make_server('127.0.0.1',0,key)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            ctx=get_functions('validate_remote_lab_target','run_remote_boofuzz')
            with tempfile.TemporaryDirectory() as root:
                with self.assertRaises(Exception):
                    ctx['run_remote_boofuzz'](
                        '127.0.0.1',server.server_address[1],'invalid-'+('B'*40),
                        seed_id=896,cases=3,output_dir=root)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

if __name__=='__main__':
    unittest.main()
