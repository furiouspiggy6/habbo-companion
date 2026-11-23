"""Local G-Earth-compatible Flash packet relay tests.

No external server, AIR executable, real G-Earth, SSO, or credentials.
Tests actual bidirectional socket framing with a fake G-Earth proxy that
replaces and blocks plaintext game messages in its 'modification' stage.
"""
from __future__ import annotations

import socket
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import clientless_gearth_bridge as b
import habbo_tcp as tcp


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1",0))
        return s.getsockname()[1]


def wait_until(predicate,seconds=2.0):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if predicate():
            return True
        time.sleep(.01)
    return False


class FakeGearthProxy:
    """The two connections G-Earth's Flash pipeline normally owns."""
    def __init__(self,port):
        self.port=port
        self.server=socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self.server.bind(("127.0.0.2",port))
        self.server.listen(1)
        self.front=None
        self.upstream=None
        self.seen_to_server=[]
        self.seen_to_client=[]
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def run(self):
        try:
            self.server.settimeout(3)
            self.front,_=self.server.accept()
            self.upstream=socket.create_connection(("127.0.0.3",self.port),timeout=2)
            hello_id,hello_body=b._read_frame(self.front)
            assert hello_id==4000
            self.upstream.sendall(b._frame(hello_id,hello_body))
            self.front.settimeout(0.1)
            self.upstream.settimeout(0.1)
            while not self.stop.is_set():
                # Simulate G-Earth TO_SERVER intercept, replace, block.
                try:
                    header,body=b._read_frame(self.front)
                    self.seen_to_server.append((header,body))
                    if body==b"block-me":
                        pass
                    else:
                        replacement=b"modified-out" if body==b"original-out" else body
                        self.upstream.sendall(b._frame(header,replacement))
                except socket.timeout:
                    pass
                # Simulate G-Earth TO_CLIENT intercept, replace, block.
                try:
                    header,body=b._read_frame(self.upstream)
                    self.seen_to_client.append((header,body))
                    if body==b"block-in":
                        pass
                    else:
                        replacement=b"modified-in" if body==b"original-in" else body
                        self.front.sendall(b._frame(header,replacement))
                except socket.timeout:
                    pass
        except (OSError,AssertionError,b.GearthBridgeError):
            pass

    def close(self):
        self.stop.set()
        for sock in (self.front,self.upstream,self.server):
            if sock:
                try:sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
                try:sock.close()
                except OSError:pass
        self.thread.join(timeout=1)


class GearthGameplayBridgeTests(unittest.TestCase):
    def setUp(self):
        self.port=free_port()
        self.bridge=b.ClientlessGearthBridge("abcdef123456",port=self.port)
        self.bridge.prepare()
        self.proxy=FakeGearthProxy(self.port)
        self.bridge.connect(tcp.TCP_FALLBACK_RELEASE,timeout=5)
        self.to_server=[]
        self.to_client=[]
        self.session=SimpleNamespace(
            authenticated=True,
            stop=threading.Event(),
            _send=lambda header,body,via_gearth=False:
                self.to_server.append((header,body,via_gearth)),
            on_packet=lambda header,size:self.to_client.append(("id",header,size)),
            on_content=lambda header,body:self.to_client.append(("body",header,body)),
        )
        self.bridge.attach(self.session)

    def tearDown(self):
        self.session.authenticated=False
        self.bridge.close()
        self.proxy.close()

    def test_real_socket_pipeline_outbound_replace_and_block(self):
        self.bridge.send_outgoing(3463,b"original-out")
        self.assertTrue(wait_until(lambda:len(self.to_server)==1))
        self.assertEqual(self.to_server[0],(3463,b"modified-out",True))
        self.bridge.send_outgoing(3463,b"block-me")
        self.assertTrue(wait_until(lambda:len(self.proxy.seen_to_server)==2))
        time.sleep(.12)
        self.assertEqual(len(self.to_server),1)

    def test_real_socket_pipeline_inbound_replace_and_block(self):
        self.bridge.send_incoming(3477,b"original-in")
        self.assertTrue(wait_until(lambda:len(self.to_client)==2))
        self.assertEqual(self.to_client[1],("body",3477,b"modified-in"))
        self.bridge.send_incoming(3477,b"block-in")
        self.assertTrue(wait_until(lambda:len(self.proxy.seen_to_client)==2))
        time.sleep(.12)
        self.assertEqual(len(self.to_client),2)

    def test_unmapped_outgoing_is_not_injected_to_game(self):
        with self.assertRaises(b.GearthBridgeError):
            self.bridge.send_outgoing(65535,b"anything")
        self.assertEqual(self.to_server,[])

    def test_disconnect_does_not_revert_to_direct_gameplay(self):
        self.session.authenticated=False
        self.bridge.close()
        with self.assertRaises(b.GearthBridgeError):
            self.bridge.send_outgoing(3463,b"anything")
        with self.assertRaises(b.GearthBridgeError):
            self.bridge.send_incoming(3477,b"anything")


class PacketSafetyAndTransportTests(unittest.TestCase):
    def test_only_loopback_bridge_domain_is_allowed(self):
        with patch.object(b.socket,"getaddrinfo",return_value=[
            (socket.AF_INET,socket.SOCK_STREAM,6,"",("127.0.0.3",0))]):
            self.assertEqual(b.verify_bridge_alias("127.0.0.3.nip.io"),
                             "127.0.0.3.nip.io")
        with patch.object(b.socket,"getaddrinfo",return_value=[
            (socket.AF_INET,socket.SOCK_STREAM,6,"",("203.0.113.5",0))]):
            with self.assertRaises(b.GearthBridgeError):
                b.verify_bridge_alias("wrong.example")
        with self.assertRaises(b.GearthBridgeError):
            b.verify_bridge_alias("127.0.0.2;evil")

    def test_tcp_transport_does_not_send_directly_while_bridge_active(self):
        sent=[]
        fake_bridge=SimpleNamespace(
            ready=True,send_outgoing=lambda header,body:
                sent.append(("bridge",header,body)),close=lambda:None)
        account=tcp.HabboTcpSession("abcdef123456",gameplay_bridge=fake_bridge)
        account.sock=SimpleNamespace(sendall=lambda data:sent.append(("socket",data)))
        account.authenticated=True
        account._send(3463,b"hello")
        self.assertEqual(sent,[("bridge",3463,b"hello")])
        account._send(3463,b"edited",via_gearth=True)
        self.assertEqual(sent[-1],("socket",tcp._frame(3463,b"edited")))
        fake_bridge.send_outgoing=lambda *a:(_ for _ in ()).throw(
            b.GearthBridgeError("bridge disconnected"))
        with self.assertRaises(b.GearthBridgeError):
            account._send(3463,b"no-bypass")
        self.assertEqual(len(sent),2)
        account.authenticated=False
        account.sock=None
        account.close()

    def test_oversized_and_invalid_frames_rejected(self):
        with self.assertRaises(b.GearthBridgeError):
            b._frame(1,b"a"*b.BRIDGE_MAX_FRAME)
        with self.assertRaises(b.GearthBridgeError):
            b._frame(-1,b"a")


if __name__=="__main__":
    unittest.main()
