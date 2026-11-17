#!/usr/bin/env python3
"""Standalone, authenticated synthetic protocol server for remote boofuzz labs.

Run only on a machine you own or are expressly authorised to test.
No Habbo traffic, SSO tickets, or official game protocol is involved.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import ipaddress
import os
import secrets
import socket
import socketserver
import threading

MAGIC=b'HCFZ1'
ACK=b'OK!'
MAX_FRAME=4096

def read_exact(conn, size):
    data=bytearray()
    while len(data)<size:
        chunk=conn.recv(size-len(data))
        if not chunk:
            raise ConnectionError("Remote test socket closed")
        data.extend(chunk)
    return bytes(data)

def frame_is_valid(frame):
    if not isinstance(frame,bytes) or len(frame)<8:
        return False
    size=int.from_bytes(frame[:4],'big')
    if size<4 or size>MAX_FRAME or len(frame)!=size+4:
        return False
    return int.from_bytes(frame[6:8],'big')==size-4

def make_server(host, port, key):
    ip=ipaddress.IPv4Address(host)
    if ip.is_multicast or ip.is_reserved:
        raise ValueError("Invalid listening IP")
    if not isinstance(port,int) or not 0<=port<=65535:
        raise ValueError("Port must be between 0 and 65535")
    if not isinstance(key,str) or not 32<=len(key)<=200:
        raise ValueError("Set HABBO_LAB_KEY to a unique random 32+ character key")
    secret=key.encode('utf-8')
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            conn=self.request
            conn.settimeout(2)
            challenge=secrets.token_bytes(16)
            try:
                conn.sendall(MAGIC+challenge)
                proof=read_exact(conn,32)
                expected=hmac.new(secret,challenge,hashlib.sha256).digest()
                if not hmac.compare_digest(proof,expected):
                    return
                conn.sendall(ACK)
                conn.settimeout(0.45)
                frame=b''
                try:
                    prefix=read_exact(conn,4)
                    declared=int.from_bytes(prefix,'big')
                    if declared<4 or declared>MAX_FRAME:
                        conn.sendall(b'REJECT')
                        return
                    body=read_exact(conn,declared)
                    frame=prefix+body
                except (TimeoutError,ConnectionError,OSError):
                    conn.sendall(b'REJECT')
                    return
                conn.sendall(b'OK' if frame_is_valid(frame) else b'REJECT')
            except (TimeoutError,OSError,ConnectionError):
                pass
    class LabServer(socketserver.ThreadingTCPServer):
        allow_reuse_address=True
        daemon_threads=True
    return LabServer((str(ip),port),Handler)

def main():
    parser=argparse.ArgumentParser(description="Controlled remote synthetic fuzz lab server")
    parser.add_argument('--listen',default='127.0.0.1',
                        help="IP assigned to this test machine (0.0.0.0 only for intentionally exposed labs)")
    parser.add_argument('--port',type=int,default=39099)
    args=parser.parse_args()
    key=os.environ.get('HABBO_LAB_KEY','')
    server=make_server(args.listen,args.port,key)
    print("Synthetic fuzz lab server listening at {}:{}. No Habbo accounts or SSO.".format(*server.server_address),flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__=='__main__':
    main()
