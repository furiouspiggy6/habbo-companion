# -*- coding: utf-8 -*-
"""Habbo View Chat | Windows overlay, packet tools and account sessions.

Works with the companion patched HabboAir.swf for chat feeds. Optional G-Earth
extension integration and per-profile local browser automation use network
sockets on the same machine. Saved passwords are held in the local Windows Credential Manager vault only.
"""
from __future__ import annotations
from headless_transport import (HeadlessLocalManager, LocalHeadlessTestServer,
                                MAX_ACCOUNTS as HEADLESS_TEST_MAX_ACCOUNTS)
from local_classic_launch import (parse_classic_ticket, official_local_executable,
                                  launch_local_classic)
from habbo_tcp import (HabboTcpSession, HabboTcpError, fetch_habbo_sso_ticket,
                       probe_classic_websocket)
import ctypes
import csv
from ctypes import wintypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import time
import threading
import queue
import subprocess
import sys
import urllib.request
import urllib.parse
import shutil
import tempfile
import zipfile
import uuid
from pathlib import PurePosixPath
import hashlib
import math
import base64
import socket
import socketserver
import ipaddress
import hmac
import struct
import importlib.util
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font
from persona_responder import chat_expression_from_template
from persona_responder_ui import PersonaResponderMixin


def validate_local_habbo_frame(frame):
    """Validate the synthetic lab's 4+2+2+N format, not Habbo's real server."""
    if not isinstance(frame,bytes) or len(frame)<8:
        return False
    declared=int.from_bytes(frame[:4],'big')
    if declared<4 or declared>4096 or declared!=len(frame)-4:
        return False
    text_length=int.from_bytes(frame[6:8],'big')
    return text_length==declared-4



HABBO_MAX_FRAME = 8192


def encode_vl64(value):
    if isinstance(value, bool) or not isinstance(value, int) or not -(1 << 31) <= value < (1 << 31):
        raise ValueError('VL64 requires a signed 32-bit integer.')
    magnitude = abs(value)
    tail = []
    rest = magnitude >> 2
    while rest:
        tail.append(rest & 0x3f)
        rest >>= 6
    first = (0x04 if value < 0 else 0) | (len(tail) << 3) | (magnitude & 3)
    result = bytearray([first])
    result.extend(reversed(tail))
    result[-1] |= 0x40
    return bytes(result)


def decode_vl64(data, offset=0):
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError('VL64 input must be bytes.')
    raw = bytes(data)
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset < len(raw):
        raise ValueError('VL64 offset is out of range.')
    first = raw[offset]
    count = ((first >> 3) & 7) + 1
    end = offset + count
    if count > 6 or end > len(raw):
        raise ValueError('Incomplete or oversized VL64 value.')
    if count == 1:
        if not first & 0x40:
            raise ValueError('Unterminated VL64 value.')
    elif first & 0x40:
        raise ValueError('VL64 terminator in first byte.')
    tail = raw[offset + 1:end]
    if tail:
        if any(byte & 0xc0 for byte in tail[:-1]):
            raise ValueError('Invalid VL64 tail.')
        if not tail[-1] & 0x40 or tail[-1] & 0x80:
            raise ValueError('Unterminated VL64 tail.')
    high = 0
    for byte in tail:
        high = (high << 6) | (byte & 0x3f)
    magnitude = (high << 2) | (first & 3)
    value = -magnitude if first & 4 else magnitude
    if not -(1 << 31) <= value < (1 << 31):
        raise ValueError('VL64 value out of range.')
    if encode_vl64(value) != raw[offset:end]:
        raise ValueError('Non-canonical VL64 encoding.')
    return value, end


def encode_b64(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError('B64 requires an integer.')
    magnitude = abs(value)
    digits = []
    while magnitude:
        digits.append(magnitude & 0x3f)
        magnitude >>= 6
    if not digits:
        digits = [0]
    digits.reverse()
    out = bytearray(b'@' if value < 0 else b'')
    for index, digit in enumerate(digits):
        out.append(digit | (0x40 if index == len(digits) - 1 else 0))
    return bytes(out)


def decode_b64(data, offset=0):
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError('B64 input must be bytes.')
    raw = bytes(data)
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset < len(raw):
        raise ValueError('B64 offset is out of range.')
    start = offset
    negative = raw[offset] == 0x40 and offset + 1 < len(raw)
    if negative:
        offset += 1
    value = 0
    while offset < len(raw):
        digit = raw[offset]
        if digit & 0x80:
            raise ValueError('Invalid B64 digit.')
        value = (value << 6) | (digit & 0x3f)
        offset += 1
        if digit & 0x40:
            result = -value if negative else value
            if encode_b64(result) != raw[start:offset]:
                raise ValueError('Non-canonical B64 encoding.')
            return result, offset
    raise ValueError('Unterminated B64 value.')


def validate_habbo_framing_frame(frame):
    """The local mock's known VL64-then-B64 body; no handler registry."""
    if not isinstance(frame, (bytes, bytearray, memoryview)) or len(frame) < 6:
        return False
    raw = bytes(frame)
    declared = int.from_bytes(raw[:4], 'big')
    # Literal bound keeps this function standalone under AST extraction.
    if declared < 2 or declared > 8192 or declared != len(raw) - 4:
        return False
    try:
        _, offset = decode_vl64(raw, 6)
        _, offset = decode_b64(raw, offset)
    except ValueError:
        return False
    return offset == len(raw)


def validate_habbo_header(header):
    return isinstance(header, int) and not isinstance(header, bool) and 0 <= header <= 0xffff


def validate_owned_lab_ip(value):
    """Select an IPv4 address assigned to this PC, not a remote fuzz target.

    The eventual socket bind checks local ownership. SSO credentials are never
    sent to this address. Hostnames, public IPs, wildcard binds and IPv6 are
    deliberately excluded from this small, isolated test harness.
    """
    try:
        address=ipaddress.IPv4Address(str(value).strip())
    except (ipaddress.AddressValueError, ValueError, TypeError):
        raise ValueError('Enter a numerical IPv4 address assigned to this PC.')
    if (not (address.is_loopback or address.is_private)
        or address.is_unspecified or address.is_multicast
        or address.is_link_local or address.is_reserved):
        raise ValueError('Only a local loopback or private IPv4 address is accepted.')
    return str(address)


def run_local_boofuzz(seed_id=896, cases=60, output_dir=None, bind_ip='127.0.0.1'):
    """Fuzz a mock bound to this PC. Never contact remote hosts or Habbo."""
    from boofuzz import (Session,Target,TCPSocketConnection,s_initialize,s_size,
                         s_block_start,s_block_end,s_word,s_string,s_get)
    bind_ip=validate_owned_lab_ip(bind_ip)
    if not isinstance(seed_id,int) or not 0<=seed_id<=65535:
        raise ValueError('Invalid numeric message ID')
    if not isinstance(cases,int) or not 1<=cases<=100:
        raise ValueError('Use 1 to 100 local test cases')
    stats={'accepted':0,'rejected':0,'requests':0}
    lock=threading.Lock()

    class LocalHandler(socketserver.BaseRequestHandler):
        def handle(self):
            # Binding to a LAN interface must not expose the test parser to
            # other machines. Only connections sourced by this PC are served.
            if self.client_address[0] not in ('127.0.0.1',bind_ip):
                return
            self.request.settimeout(0.25)
            frame=b''
            try:
                while len(frame)<8192:
                    try:chunk=self.request.recv(4096)
                    except socket.timeout:break
                    if not chunk:break
                    frame+=chunk
                    if len(frame)>=4:
                        expected=int.from_bytes(frame[:4],'big')+4
                        if expected>4096 or len(frame)>=expected:break
                accepted=validate_local_habbo_frame(frame)
                with lock:
                    stats['requests']+=1
                    stats['accepted' if accepted else 'rejected']+=1
                self.request.sendall(b'OK' if accepted else b'REJECT')
            except OSError:
                pass

    class LoopbackServer(socketserver.ThreadingTCPServer):
        allow_reuse_address=True
        daemon_threads=True

    # A bind succeeds only for an IP actually assigned to this machine.
    # No remote host or arbitrary destination is ever accepted as target.
    try:
        server=LoopbackServer((bind_ip,0),LocalHandler)
    except OSError as exc:
        raise ValueError('The selected IP is not assigned to your PC or is unavailable.') from exc
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    output_dir=Path(output_dir) if output_dir else APP_DIR/'fuzz_lab'
    output_dir.mkdir(parents=True,exist_ok=True)
    db=output_dir/('boofuzz_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.db')
    try:
        s_initialize('synthetic_habbo_frame')
        s_size('frame_body',length=4,endian='>',name='declared_length')
        if s_block_start('frame_body'):
            s_word(seed_id,endian='>',name='message_id')
            s_size('synthetic_text',length=2,endian='>',name='text_length')
            if s_block_start('synthetic_text'):
                s_string('sample',max_len=32,name='synthetic_value')
                s_block_end()
            s_block_end()
        session=Session(
            target=Target(connection=TCPSocketConnection(bind_ip,
                             server.server_address[1],recv_timeout=0.5)),
            index_end=cases, sleep_time=0.01, receive_data_after_each_request=True,
            web_address='127.0.0.1',web_port=None,keep_web_open=False,
            db_filename=str(db))
        session.connect(s_get('synthetic_habbo_frame'))
        session.fuzz()
        return dict(stats,seed_id=seed_id,case_limit=cases,
                    scope='this-PC synthetic mock only',bind_ip=bind_ip,boofuzz_db=str(db))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)





def run_local_habbo_boofuzz(seed_id=896, cases=40, output_dir=None,
                            bind_ip='127.0.0.1', fuzz_header=False):
    """Fuzz only a temporary mock on this PC, never a Habbo server."""
    import socket
    import ipaddress
    from boofuzz import (Session, Target, TCPSocketConnection, s_initialize, s_size,
                         s_block, s_word, s_group, s_get)
    # boofuzz 0.4.2 accepts a callable block encoder but does not ship the
    # encoders module in every distribution. Preserve the Encoder ABC contract.
    try:
        from boofuzz.encoders import Encoder
    except ImportError:
        from abc import ABC, abstractmethod

        class Encoder(ABC):
            @abstractmethod
            def encode(self, data):
                raise NotImplementedError

            @abstractmethod
            def decode(self, data):
                raise NotImplementedError

    # Standalone under the repository tests' AST-extraction namespace.
    def validate_owned_lab_ip(value):
        try:
            address = ipaddress.IPv4Address(str(value).strip())
        except (ipaddress.AddressValueError, ValueError, TypeError):
            raise ValueError('Enter a numerical IPv4 address assigned to this PC.') from None
        if (not (address.is_loopback or address.is_private)
            or address.is_unspecified or address.is_multicast
            or address.is_link_local or address.is_reserved):
            raise ValueError('Only a local loopback or private IPv4 address is accepted.')
        return str(address)

    def _as_bytes(data):
        return data.encode('ascii') if isinstance(data, str) else bytes(data)

    def _as_text(data):
        return _as_bytes(data).decode('ascii') if isinstance(data, (bytes, bytearray, memoryview)) else str(data)

    class Vl64BlockEncoder(Encoder):
        def encode(self, value):
            return encode_vl64(int(_as_text(value)))

        def decode(self, data):
            raw = _as_bytes(data)
            value, end = decode_vl64(raw)
            if end != len(raw):
                raise ValueError('Trailing VL64 bytes.')
            return str(value)

        def __call__(self, data):
            return self.encode(data)

    class B64BlockEncoder(Encoder):
        def encode(self, value):
            return encode_b64(int(_as_text(value)))

        def decode(self, data):
            raw = _as_bytes(data)
            value, end = decode_b64(raw)
            if end != len(raw):
                raise ValueError('Trailing B64 bytes.')
            return str(value)

        def __call__(self, data):
            return self.encode(data)

    bind_ip = validate_owned_lab_ip(bind_ip)
    if not validate_habbo_header(seed_id):
        raise ValueError('Invalid numeric header ID.')
    if isinstance(cases, bool) or not isinstance(cases, int) or not 1 <= cases <= 100:
        raise ValueError('Use 1 to 100 local test cases.')
    stats = {'accepted': 0, 'rejected': 0, 'requests': 0}
    lock = threading.Lock()

    class LocalHandler(socketserver.BaseRequestHandler):
        def handle(self):
            if self.client_address[0] not in ('127.0.0.1', bind_ip):
                return
            self.request.settimeout(0.25)

            def recv_exact(count):
                received = bytearray()
                while len(received) < count:
                    try:
                        chunk = self.request.recv(count - len(received))
                    except socket.timeout:
                        break
                    if not chunk:
                        break
                    received.extend(chunk)
                return bytes(received)

            try:
                prefix = recv_exact(4)
                if len(prefix) == 4:
                    declared = int.from_bytes(prefix, 'big')
                    frame = prefix + (recv_exact(declared) if declared <= 8192 else b'')
                else:
                    frame = prefix
                accepted = validate_habbo_framing_frame(frame)
            except OSError:
                accepted = False
            with lock:
                stats['requests'] += 1
                stats['accepted' if accepted else 'rejected'] += 1
            try:
                self.request.sendall(b'OK' if accepted else b'REJECT')
            except OSError:
                pass

    class LoopbackServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    try:
        server = LoopbackServer((bind_ip, 0), LocalHandler)
    except OSError as exc:
        raise ValueError('The selected IP is not assigned to your PC or is unavailable.') from exc
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output_dir = Path(output_dir) if output_dir else Path.cwd() / 'fuzz_lab'
    output_dir.mkdir(parents=True, exist_ok=True)
    db = output_dir / ('boofuzz_habbo_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.db')
    try:
        values = [
            '0', '1', '-1', '2', '3', '4', '63', '64', '-64',
            '255', '256', '-256', '4096', '65535', '-65535',
            '2147483647', '-2147483648',
        ]
        s_initialize('habbo_framing_frame')
        s_size('habbo_frame_body', length=4, endian='>', output_format='binary',
               inclusive=False, fuzzable=False, name='habbo_declared_length')
        with s_block('habbo_frame_body'):
            s_word(seed_id, endian='>', name='habbo_header_id',
                   fuzzable=bool(fuzz_header),
                   fuzz_values=[seed_id, 0, 1, 2, 3, 4, 5, 4000, 0x7fff, 0xffff])
            with s_block('habbo_vl64', encoder=Vl64BlockEncoder()):
                s_group(name='habbo_vl64_value', values=values)
            with s_block('habbo_b64', encoder=B64BlockEncoder()):
                s_group(name='habbo_b64_value', values=values)
        session = Session(
            target=Target(connection=TCPSocketConnection(
                bind_ip, server.server_address[1], recv_timeout=0.5)),
            index_end=cases, restart_threshold=1, restart_timeout=0,
            sleep_time=0.01, receive_data_after_each_request=True,
            web_address='127.0.0.1', web_port=None, keep_web_open=False,
            db_filename=str(db))
        session.connect(s_get('habbo_framing_frame'))
        session.fuzz()
        return dict(stats, seed_id=seed_id, case_limit=cases,
                    scope='this-PC Habbo-framing mock only',
                    bind_ip=bind_ip, boofuzz_db=str(db))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


# Separate from Habbo's production session and the synthetic Companion mock.
# This tool always contacts ONLY an Arcturus emulator on this machine.
ARCTURUS_EMULATOR_HOST = '127.0.0.1'
ARCTURUS_EMULATOR_PORT = 30000
ARCTURUS_MAX_CASES = 50
ARCTURUS_B64_ALPHABET = b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'


class ArcturusEncoder:
    """Callable boofuzz s_block encoder base for a confirmed wire field."""
    def encode(self, data):
        raise NotImplementedError

    def __call__(self, data):
        return self.encode(data)


class ArcturusVL64Encoder(ArcturusEncoder):
    """Signed 32-bit value encoded as supplied by the local emulator source."""

    def encode(self, data):
        if not isinstance(data, bytes) or len(data) != 4:
            raise ValueError('VL64 input must be four big-endian bytes.')
        value=struct.unpack('>i',data)[0]
        magnitude=abs(value)
        tail=[]
        rest=magnitude>>2
        while rest:
            tail.append(rest&0x3f)
            rest>>=6
        bytecount=len(tail)+1
        first=(0x04 if value<0 else 0)|(bytecount-1)<<3|(magnitude&0x03)
        result=bytearray([first])
        result.extend(reversed(tail))
        result[-1]|=0x40
        return bytes(result)


class ArcturusB64Encoder(ArcturusEncoder):
    """Only the confirmed one-digit signed B64 range, never arbitrary bytes."""

    def encode(self, data):
        try:
            raw=data.decode('ascii') if isinstance(data,bytes) else str(data)
            if not re.fullmatch(r'-?(?:0|[1-9][0-9]?)',raw):
                raise ValueError
            value=int(raw)
        except (UnicodeError,ValueError):
            raise ValueError('Only a signed single-digit B64 integer is supported.') from None
        if abs(value)>63:
            raise ValueError('B64 value must be from -63 to 63.')
        terminal=ARCTURUS_B64_ALPHABET[abs(value)]|0x40
        result=(b'@' if value<0 else b'')+bytes([terminal])
        if any(ch not in ARCTURUS_B64_ALPHABET
               for ch in (result[1:] if value<0 else result)):
            raise ValueError('Encoded B64 character is outside its alphabet.')
        return result


def validate_arcturus_emulator_parameters(header_id,cases):
    """Keep the new emulator fuzzer deterministic and loopback-only."""
    if isinstance(header_id,bool) or not isinstance(header_id,int) or not 0<=header_id<=65535:
        raise ValueError('Enter a known 16-bit Arcturus header ID.')
    if isinstance(cases,bool) or not isinstance(cases,int) or not 1<=cases<=ARCTURUS_MAX_CASES:
        raise ValueError(f'Use between 1 and {ARCTURUS_MAX_CASES} test cases.')
    return header_id,cases


def build_arcturus_boofuzz_request(header_id):
    """One minimal frame; TODO: handler-specific fields and authentication.

    s_size wraps the complete header+body block; the body is precisely a
    VL64 integer followed by a single signed B64 digit for testing the
    encoder boundary. Never invent a handler or full B64 string encoding.
    """
    validate_arcturus_emulator_parameters(header_id,1)
    from boofuzz import (
        s_initialize,s_size,s_block,s_word,s_dword,s_group,s_get)
    request_name='local_arcturus_'+uuid.uuid4().hex
    s_initialize(request_name)
    s_size('header_and_body',length=4,endian='>',
           output_format='binary',inclusive=False,fuzzable=False,
           name='frame_length')
    with s_block('header_and_body'):
        s_word(header_id,endian='>',fuzzable=False,name='header_id')
        with s_block('vl64_field',encoder=ArcturusVL64Encoder()):
            s_dword(0,endian='>',name='vl64_source',
                    fuzz_values=[
                        0,1,2,3,4,63,64,255,256,65535,
                        0x7fffffff,0x80000000,0xffffffff])
        with s_block('b64_digit',encoder=ArcturusB64Encoder()):
            s_group(name='b64_source',values=[
                '-63','-32','-2','-1','0','1','2','3',
                '31','32','62','63'])
        # TODO: Supply the selected header's real body field sequence
        # from your emulator handler. Many Arcturus handlers expect an
        # authenticated session before any application packet.
        # TODO: Implement multidigit B64 only after confirming its order.
    return s_get(request_name)


def preview_arcturus_emulator_packet(header_id):
    """Validate the rendered length without sending any network traffic."""
    req=build_arcturus_boofuzz_request(header_id)
    raw=req.render()
    if len(raw)<6 or int.from_bytes(raw[:4],'big')!=len(raw)-4:
        raise ValueError('Invalid Arcturus frame length; nothing was sent.')
    if int.from_bytes(raw[4:6],'big')!=header_id:
        raise ValueError('Unexpected Arcturus header; nothing was sent.')
    return raw


def run_arcturus_emulator_boofuzz(header_id,cases=20,output_dir=None):
    """Opt-in, bounded loopback-only fuzzing of a local Arcturus emulator.

    This does not reuse live Habbo TCP sockets, G-Earth, SSO or browser
    credentials. The emulator may reject this minimal unauthenticated frame.
    """
    header_id,cases=validate_arcturus_emulator_parameters(header_id,cases)
    from boofuzz import Session,Target,TCPSocketConnection
    # A non-negotiable destination; do not expose a host input or use
    # discovered Habbo/G-Earth IPs here.
    host=ARCTURUS_EMULATOR_HOST
    port=ARCTURUS_EMULATOR_PORT
    # Fail before invoking a fuzz session when no local emulator is present.
    with socket.create_connection((host,port),timeout=0.75):
        pass

    output_dir=Path(output_dir) if output_dir else APP_DIR/'fuzz_lab'
    output_dir.mkdir(parents=True,exist_ok=True)
    database=output_dir/(
        'arcturus_'+datetime.now().strftime('%Y%m%d_%H%M%S')+
        '_'+uuid.uuid4().hex[:8]+'.db')
    sent={'count':0}

    class CountedLocalConnection(TCPSocketConnection):
        def __init__(self):
            super().__init__(host=host,port=port,
                             recv_timeout=0.6,send_timeout=0.6)

        def send(self,data):
            written=super().send(data)
            if written:
                sent['count']+=1
            return written

    req=build_arcturus_boofuzz_request(header_id)
    baseline=req.render()
    if len(baseline)<6 or int.from_bytes(baseline[:4],'big')!=len(baseline)-4:
        raise ValueError('Rendered boofuzz frame failed its size check.')
    session=Session(
        target=Target(connection=CountedLocalConnection()),
        index_end=cases,sleep_time=0.05,
        receive_data_after_each_request=False,
        web_address='127.0.0.1',web_port=None,
        keep_web_open=False,db_filename=str(database))
    session.connect(req)
    session.fuzz()
    return {
        'scope':'Local Arcturus emulator ONLY',
        'host':host,'port':port,'header_id':header_id,
        'case_limit':cases,'requests':sent['count'],
        'boofuzz_db':str(database),
        'note':'No authentication/handler schema assumed; packet acceptance unverified',
    }

def validate_remote_lab_target(host,port,secret):
    """Remote fuzz target must prove possession of the lab-only key.

    Hostnames are intentionally unsupported to avoid DNS target switching.
    Never send real Habbo credentials to this server.
    """
    try:
        address=ipaddress.IPv4Address(str(host).strip())
    except (ipaddress.AddressValueError, ValueError, TypeError):
        raise ValueError('Enter the numerical IPv4 address of your test server.')
    if (address.is_unspecified or address.is_multicast or address.is_link_local
        or address.is_reserved):
        raise ValueError('Enter a specific reachable IPv4 address, not a wildcard.')
    try:
        port=int(str(port).strip())
    except (TypeError,ValueError):
        raise ValueError('Enter a TCP port between 1024 and 65535.')
    if not 1024<=port<=65535:
        raise ValueError('Enter a TCP port between 1024 and 65535.')
    if (not isinstance(secret,str) or not 32<=len(secret)<=200
        or any(ord(ch)<33 or ord(ch)>126 for ch in secret)):
        raise ValueError('Enter the 32+ character lab key from your own test server.')
    return str(address),port,secret


def run_remote_boofuzz(host,port,secret,seed_id=896,cases=20,output_dir=None):
    """Fuzz ONLY a remote mock that authenticates with a lab-only HMAC key.

    An unrecognised service never receives a fuzz payload: authentication is
    enforced on EVERY new TCP connection before boofuzz can send one.
    No Habbo SSO ticket, cookies or packet contents are accepted.
    """
    from boofuzz import (Session,Target,TCPSocketConnection,s_initialize,s_size,
                         s_block_start,s_block_end,s_word,s_string,s_get,exception)
    host,port,secret=validate_remote_lab_target(host,port,secret)
    if not isinstance(seed_id,int) or not 0<=seed_id<=65535:
        raise ValueError('Invalid numeric message ID')
    if not isinstance(cases,int) or not 1<=cases<=60:
        raise ValueError('Use 1 to 60 remote lab cases')
    counts={'requests':0,'accepted':0,'rejected':0,'other':0}
    key=secret.encode('utf-8')

    class AuthenticatedLabConnection(TCPSocketConnection):
        def __init__(self):
            super().__init__(host,port,send_timeout=1,recv_timeout=1)
            self._lab_ready=False

        def _recv_exact(self,size):
            data=bytearray()
            while len(data)<size:
                fragment=self._sock.recv(size-len(data))
                if not fragment:
                    raise ConnectionError('Test server closed before authenticating')
                data.extend(fragment)
            return bytes(data)

        def open(self):
            self._lab_ready=False
            try:
                super().open()
                challenge=self._recv_exact(21)
                if not challenge.startswith(b'HCFZ1'):
                    raise ValueError('Not the Companion synthetic lab service')
                proof=hmac.new(key,challenge[5:],hashlib.sha256).digest()
                self._sock.sendall(proof)
                if self._recv_exact(3)!=b'OK!':
                    raise ValueError('Remote lab key was not recognised')
                self._lab_ready=True
            except (OSError,ConnectionError,TimeoutError,ValueError):
                self.close()
                raise exception.BoofuzzTargetConnectionFailedError(
                    'Remote endpoint did not prove it is your authorised lab server') from None

        def close(self):
            self._lab_ready=False
            super().close()

        def send(self,data):
            if not self._lab_ready:
                raise exception.BoofuzzTargetConnectionFailedError(
                    'Remote lab authentication required before sending')
            written=super().send(data)
            if written:
                counts['requests']+=1
            return written

        def recv(self,max_bytes):
            data=super().recv(max_bytes)
            if data==b'OK':
                counts['accepted']+=1
            elif data==b'REJECT':
                counts['rejected']+=1
            elif data:
                counts['other']+=1
            return data

    # Authenticate once before creating a fuzz Session, so misconfigured
    # servers fail early. The connection class repeats proof on EACH case.
    probe=AuthenticatedLabConnection()
    try:
        probe.open()
    finally:
        probe.close()
    output_dir=Path(output_dir) if output_dir else APP_DIR/'fuzz_lab'
    output_dir.mkdir(parents=True,exist_ok=True)
    db=output_dir/('boofuzz_remote_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.db')
    s_initialize('authenticated_remote_synthetic_frame')
    s_size('remote_frame_body',length=4,endian='>',name='remote_declared_length')
    if s_block_start('remote_frame_body'):
        s_word(seed_id,endian='>',name='remote_message_id')
        s_size('remote_synthetic_text',length=2,endian='>',name='remote_text_length')
        if s_block_start('remote_synthetic_text'):
            s_string('sample',max_len=32,name='remote_synthetic_value')
            s_block_end()
        s_block_end()
    session=Session(
        target=Target(connection=AuthenticatedLabConnection()),
        index_end=cases,sleep_time=0.02,receive_data_after_each_request=True,
        receive_data_after_fuzz=True,
        web_address='127.0.0.1',web_port=None,keep_web_open=False,
        db_filename=str(db),restart_threshold=1,restart_timeout=0)
    session.connect(s_get('authenticated_remote_synthetic_frame'))
    session.fuzz()
    return dict(counts,case_limit=cases,seed_id=seed_id,
                scope='authenticated synthetic remote lab only',
                remote_address=host,remote_port=port,boofuzz_db=str(db))


APP_NAME = 'Habbo View Chat'


class _NoUpdateRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow a release-feed redirect to an unexpected publisher."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Automatic update redirects are blocked for safety.')


def _open_official_update(req, timeout):
    """Network code still honours user proxy settings, but never redirects."""
    return urllib.request.build_opener(_NoUpdateRedirect()).open(
        req, timeout=timeout)


def redact_sensitive_diagnostic(value):
    """Best-effort protection for readable diagnostic messages.

    Raw packet contents are excluded from *default* exports separately,
    because regexes cannot guarantee detection of every session credential.
    """
    text = str(value or '')
    if re.search(
        r'(?i)\b(?:SSOTicket|LoginWithTicket|AuthenticationTicket)\b',text):
        return '[authentication packet omitted]'
    text = re.sub(
        r'\b(?:sk-[A-Za-z0-9_-]{15,}|gh[pousr]_[A-Za-z0-9_-]{15,}'
        r'|github_pat_[A-Za-z0-9_-]{15,})',
        '[REDACTED credential]',text)
    text = re.sub(
        r'(?i)\bBearer\s+[A-Za-z0-9._~+/\-=]{8,}',
        'Bearer [REDACTED]',text)
    text = re.sub(
        r'\bHABBO-[A-Za-z0-9._~+/\-=]{10,}',
        '[REDACTED session ticket]',text)
    text = re.sub(
        r'\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{6,}'
        r'(?:\.[A-Za-z0-9_-]{6,})?',
        '[REDACTED token]',text)
    text = re.sub(
        r'(?i)((?:"|\b)(?:access[_-]?token|refresh[_-]?token|'
        r'sso[_-]?ticket|ssoticket|session[_-]?id|cookie|password|passwd|'
        r'authorization|api[_-]?key|secret)(?:"|\b)\s*[:=]\s*)'
        r'(?:"[^"]{1,500}"|\'[^\']{1,500}\'|[^\s,;&}]{1,500})',
        lambda match:match.group(1)+'[REDACTED]',text)
    return text


def packet_export_record(timestamp,direction,detail,include_contents=False):
    """Default export cannot contain packet contents, even unknown secrets."""
    time_part = str(timestamp) if re.fullmatch(
        r'\d{2}:\d{2}:\d{2}',str(timestamp)) else '[time]'
    direction_part=direction if direction in ('Incoming','Outgoing') else 'Unknown'
    if include_contents:
        return (time_part+f' [{direction_part}] '+
                redact_sensitive_diagnostic(detail)+'\n')
    named=re.search(r'\{(?:in|out):([A-Za-z_][A-Za-z0-9_]{0,63})\}',
                    str(detail))
    label=('type '+named.group(1)) if named else 'type unknown'
    return f'{time_part} [{direction_part}] [{label}; payload omitted]\n'

APP_DIR = Path(os.environ.get('APPDATA', str(Path.home()))) / 'HabboViewChat'
CONFIG_PATH = APP_DIR / 'settings.json'
FEED_NAME = 'habbo_view_chat.jsonl'
TRANSPARENT = '#ff00fe'

# Shared modern-dark application chrome.  These colours apply only to the
# Companion control window; the original in-game Habbo bubble art and overlay
# themes above remain independent.
COMPANION_UI = {
    'background': '#0B111C',
    'sidebar': '#080E17',
    'surface': '#141F2E',
    'raised': '#1C2C40',
    'field': '#101B29',
    'border': '#29394D',
    'text': '#F0F5FC',
    'muted': '#A1B3C7',
    'faint': '#71859E',
    'accent': '#58B9F8',
    'accent_hover': '#80D2FF',
    'success': '#54D7B0',
    'danger': '#E58B9B',
}

DEFAULT = dict(
    x=22,
    anchor=80,
    width=540,
    font_size=14,
    gap=7,
    bottom_clearance=110,
    visible_messages=14,
    auto_fill_screen=True,
    history_limit=200,
    visible_only=True,
    show_room=True,
    bubbles=True,
    respect_chat_styles=True,
    original_bubble_images=True,
    single_line_bubbles=True,
    whispers_right=True,
    theme='Midnight',
    topmost=False,
    keep_log=False,
    feed_path='',
    gearth_path='',
    gearth_port=9092,
    gearth_host='game-us.habbo.com',
    gearth_game_port=30000,
    gearth_minimize=True,
    gearth_auto_arm=False,
    gearth_network_safety_v114=False,
    gearth_single_window_v116=False,
    gearth_background_v108=False,
    gearth_visible_debug_v106=False,
    gearth_startup_safety_v104=True,
    gearth_startup_uia_v105=False,
    packet_rules=[],
    coffee_cup_one='476989081',
    coffee_cup_two='476989024',
    coffee_recipient='68808036',
    coffee_username='',
    coffee_interval='0.1',
    coffee_cycles='0',
    coffee_group_names='',
    coffee_group_enabled=False,
    coffee_wait_for_hand=False,
    coffee_extra_furniture='',
    habbo_launcher_path='',
    account_profiles=[],
    account_active_id='',
    tcp_auto_connect=False,
    responder_persona='Mario35',
    responder_target='',
    responder_rotation=False,
    responder_capture=False,
    # Per-user public chat logging is separate from AI and starts enabled.
    background_public_chat_logging=True,
    responder_log_dir='',
    responder_style_mode='Custom personality',
    responder_personality=('A friendly, conversational Habbo player. Keep things '
                           'casual and genuine, use natural short replies, and '
                           'avoid sounding like a customer support bot.'),
    responder_tone='Casual',
    responder_humour=2,
    responder_responsiveness='Natural',
    responder_target_mode='Everyone',
    responder_targets='',
    responder_model='gpt-5-mini',
    update_manifest_url='https://raw.githubusercontent.com/furiouspiggy6/habbo-companion/main/latest.json',
)

THEMES = {
    'Midnight': dict(room='#0d1424',bubble='#e6ebf4',fg='#111b2b',name='#1b3047',acc='#63a9d9'),
    'Graphite': dict(room='#101013',bubble='#e8e8ea',fg='#141417',name='#34343b',acc='#b1b4c2'),
    'Violet': dict(room='#160e23',bubble='#ebe3f7',fg='#261834',name='#533974',acc='#c39ced'),
    'Habbo': dict(room='#102034',bubble='#f1f2f3',fg='#1c2029',name='#294b66',acc='#70bae6'),
}


# ChatStyle IDs are supplied by the patched AIR client. The original Habbo style
# sprites are not accessible to Tkinter here; these palettes are approximations
# that differentiate distinct selected styles instead of making all messages white.
# IDs are deterministic: a given speaker's chosen style will always have the
# same panel appearance until they change that style.
STYLE_VARIANTS = [
    ('#f0f1f3','#1b232e','#7489a1','#d9dee5'),
    ('#cfd2d8','#242936','#6b778b','#a9b0bd'),
    ('#d1eafe','#0e3b5a','#2b9bce','#8bc9f0'),
    ('#fce2e8','#6b304d','#c96088','#eb9eb5'),
    ('#fff0c8','#664518','#d5a334','#e6cf7e'),
    ('#d9f3e3','#22523d','#5cba84','#a2dab2'),
    ('#282f42','#f1f5ff','#749ad6','#54607d'),
    ('#eadff9','#53376f','#a280d9','#ccb8eb'),
    ('#f6dfc7','#694630','#cc8a52','#e0b48e'),
    ('#d8eff0','#214f58','#4d9ca4','#a8d7da'),
    ('#f5dcf4','#67376a','#c26abf','#dba5db'),
    ('#e4e4ee','#39384d','#81849d','#c1c1d6'),
]


def get_message_colors(msg, theme):
    if msg.style_id is None:
        return theme['bubble'],theme['fg'],theme['acc'],theme['name']
    # The style ID comes from the real sender's ChatItem.style field.
    base,fg,accent,border=STYLE_VARIANTS[abs(msg.style_id)%len(STYLE_VARIANTS)]
    if isinstance(msg.forced_color,int) and 0<=msg.forced_color<=0xffffff:
        # Forced game colour is carried over; avoid overly dark text areas.
        forced=msg.forced_color
        if forced>0:
            border=f'#{forced:06x}'
    return base,fg,accent,border


# G-Earth manipulation rules; intentionally disabled on every app startup.
RULE_DIRECTIONS=('Incoming','Outgoing','Both')
RULE_ACTIONS=('Block','Replace')

def validate_replay_interval(value):
    """Enforce a conservative single-packet repeat rate, in seconds."""
    try:
        interval=float(str(value).strip())
    except (ValueError,TypeError,OverflowError):
        raise ValueError('Enter a delay in seconds (0.1 to 120).')
    if not math.isfinite(interval) or not 0.1<=interval<=120.0:
        raise ValueError('Repeat delay must be between 0.1 and 120 seconds.')
    return interval



def validate_coffee_interval(value):
    """Accept a 100µs *requested* delay without promising sub-ms GUI timing.

    Cycles=0 remains unlimited until STOP or disconnection. Timing is
    best effort: Tkinter schedules in integer milliseconds and the
    G-Earth send itself can take longer than the requested interval.
    """
    try:
        interval=float(str(value).strip())
    except (ValueError,TypeError,OverflowError):
        raise ValueError('Enter a coffee delay in seconds (0.0001 to 120).')
    if not math.isfinite(interval) or not 0.0001<=interval<=120.0:
        raise ValueError('Coffee delay must be between 0.0001 and 120 seconds.')
    return interval


def coffee_delay_ms(interval):
    """Nonzero integer Tk delay (1ms minimum regardless of requested value)."""
    return max(1,round(validate_coffee_interval(interval)*1000))


def validate_habbo_login_url(value):
    """Only open HTTPS login pages; never embed or store account credentials."""
    url=str(value).strip()
    try:
        parsed=urllib.parse.urlsplit(url)
        host=parsed.hostname
        port=parsed.port
    except (ValueError,TypeError):
        raise ValueError('Enter a valid HTTPS login URL.')
    if (parsed.scheme!='https' or not host or parsed.username is not None
        or parsed.password is not None or port==0 or
        any(ch.isspace() for ch in url) or len(url)>300):
        raise ValueError('Enter a valid HTTPS login URL without credentials.')
    return url


def normalize_habbo_accounts(profiles):
    """Validate only labels, login URLs, local ports and opaque safe IDs."""
    if not isinstance(profiles,list):
        return []
    valid=[]
    ids=set()
    ports=set()
    for entry in profiles[:30]:
        if not isinstance(entry,dict):
            continue
        ident=str(entry.get('id','')).lower()
        label=str(entry.get('label','')).strip()
        try:
            port=int(entry.get('port',0))
            url=validate_habbo_login_url(entry.get('url',''))
        except (ValueError,TypeError,OverflowError):
            continue
        if (not re.fullmatch(r'[a-f0-9]{12}',ident)
            or not 1<=len(label)<=50
            or any(ord(ch)<32 for ch in label)
            or not 1024<=port<=65535
            or ident in ids or port in ports):
            continue
        ids.add(ident)
        ports.add(port)
        valid.append({'id':ident,'label':label,'port':port,'url':url})
        if len(valid)==12:
            break
    return valid


# Credentials stay in the current Windows user's Credential Manager vault.
# settings.json, GitHub releases and browser command lines never contain secrets.
class _HabboCredential(ctypes.Structure):
    _fields_=[
        ('Flags',wintypes.DWORD),('Type',wintypes.DWORD),
        ('TargetName',wintypes.LPWSTR),('Comment',wintypes.LPWSTR),
        ('LastWritten',wintypes.FILETIME),('CredentialBlobSize',wintypes.DWORD),
        ('CredentialBlob',ctypes.POINTER(ctypes.c_ubyte)),
        ('Persist',wintypes.DWORD),('AttributeCount',wintypes.DWORD),
        ('Attributes',ctypes.c_void_p),('TargetAlias',wintypes.LPWSTR),
        ('UserName',wintypes.LPWSTR)]


def _account_credential_target(account_id):
    ident=str(account_id).lower()
    if not re.fullmatch(r'[a-f0-9]{12}',ident):
        raise ValueError('Invalid account profile identifier.')
    return 'HabboCompanion:login:'+ident


def _account_credential_api():
    if os.name!='nt':
        raise OSError('Windows Credential Manager requires Windows.')
    api=ctypes.WinDLL('advapi32',use_last_error=True)
    ptr=ctypes.POINTER(_HabboCredential)
    api.CredWriteW.argtypes=[ptr,wintypes.DWORD]
    api.CredWriteW.restype=wintypes.BOOL
    api.CredReadW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,
                             wintypes.DWORD,ctypes.POINTER(ptr)]
    api.CredReadW.restype=wintypes.BOOL
    api.CredDeleteW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD]
    api.CredDeleteW.restype=wintypes.BOOL
    api.CredFree.argtypes=[ctypes.c_void_p]
    api.CredFree.restype=None
    return api


def account_saved_login_write(account_id,email,password):
    """Persist only in the per-user Windows Credential Manager vault."""
    target=_account_credential_target(account_id)
    email=str(email).strip()
    password=str(password)
    if not email or '@' not in email or any(ch.isspace() for ch in email):
        raise ValueError('Enter the email address used to sign into Habbo.')
    blob=password.encode('utf-16-le')
    if not password or len(blob)>512:
        raise ValueError('Enter a password up to 256 characters.')
    api=_account_credential_api()
    payload=ctypes.create_string_buffer(blob,len(blob))
    record=_HabboCredential()
    record.Type=1  # CRED_TYPE_GENERIC
    record.TargetName=target
    record.UserName=email
    record.CredentialBlobSize=len(blob)
    record.CredentialBlob=ctypes.cast(payload,ctypes.POINTER(ctypes.c_ubyte))
    record.Persist=2  # CRED_PERSIST_LOCAL_MACHINE, scoped to Windows user
    if not api.CredWriteW(ctypes.byref(record),0):
        raise OSError('Windows could not save this login in Credential Manager.')


def account_saved_login_read(account_id):
    """Return (email,password) in memory only, or None when not saved."""
    api=_account_credential_api()
    output=ctypes.POINTER(_HabboCredential)()
    if not api.CredReadW(_account_credential_target(account_id),1,0,
                         ctypes.byref(output)):
        if ctypes.get_last_error()==1168:  # ERROR_NOT_FOUND
            return None
        raise OSError('Windows could not read this saved login.')
    try:
        record=output.contents
        size=record.CredentialBlobSize
        if size>512 or size%2 or not record.CredentialBlob:
            raise ValueError('Saved login has an invalid credential value.')
        return (record.UserName or '',
                ctypes.string_at(record.CredentialBlob,size).decode('utf-16-le'))
    finally:
        api.CredFree(ctypes.cast(output,ctypes.c_void_p))


def account_saved_login_delete(account_id):
    api=_account_credential_api()
    if not api.CredDeleteW(_account_credential_target(account_id),1,0):
        if ctypes.get_last_error()!=1168:
            raise OSError('Windows could not forget this saved login.')



# Direct TCP website session cookies are opt-in and kept in Windows Credential
# Manager, never settings.json. They are not Habbo passwords and can expire.
def _account_session_target(account_id):
    return _account_credential_target(account_id).replace(':login:', ':session:', 1)


def account_session_cookie_write(account_id, session_id, browser_token):
    # Match strict cookie characters accepted by the official HTTPS requester.
    for token in (session_id, browser_token):
        if (not isinstance(token, str) or not 1 <= len(token) <= 900
            or any(ord(c) < 33 or ord(c) > 126 or c in ';,\r\n' for c in token)):
            raise ValueError('Invalid Habbo session cookie')
    blob=json.dumps({'session_id':session_id,'browser_token':browser_token},
                    separators=(',',':')).encode('utf-16-le')
    if len(blob)>2560:
        raise ValueError('Session cookies exceed Windows vault limits')
    api=_account_credential_api()
    payload=ctypes.create_string_buffer(blob,len(blob))
    record=_HabboCredential()
    record.Type=1
    record.TargetName=_account_session_target(account_id)
    record.UserName='habbo.com'
    record.CredentialBlobSize=len(blob)
    record.CredentialBlob=ctypes.cast(payload,ctypes.POINTER(ctypes.c_ubyte))
    record.Persist=2
    if not api.CredWriteW(ctypes.byref(record),0):
        raise OSError('Windows could not save Habbo session in Credential Manager')


def account_session_cookie_read(account_id):
    api=_account_credential_api()
    output=ctypes.POINTER(_HabboCredential)()
    if not api.CredReadW(_account_session_target(account_id),1,0,
                         ctypes.byref(output)):
        if ctypes.get_last_error()==1168:
            return None
        raise OSError('Windows could not read saved Habbo session')
    try:
        record=output.contents
        size=record.CredentialBlobSize
        if not 0<size<=2560 or size%2 or not record.CredentialBlob:
            raise ValueError('Invalid saved session data')
        data=json.loads(ctypes.string_at(
            record.CredentialBlob,size).decode('utf-16-le'))
        if not isinstance(data,dict):
            raise ValueError('Invalid saved session record')
        return (data['session_id'],data['browser_token'])
    finally:
        api.CredFree(ctypes.cast(output,ctypes.c_void_p))


def account_session_cookie_delete(account_id):
    api=_account_credential_api()
    if not api.CredDeleteW(_account_session_target(account_id),1,0):
        if ctypes.get_last_error()!=1168:
            raise OSError('Windows could not erase saved Habbo session')


def account_login_browser():
    """Prefer Brave; allow Chrome/Edge as separate user-data-dir browsers."""
    roots=[os.environ.get('LOCALAPPDATA',''),
           os.environ.get('PROGRAMFILES',''),
           os.environ.get('PROGRAMFILES(X86)','')]
    relative=[
        'BraveSoftware/Brave-Browser/Application/brave.exe',
        'Google/Chrome/Application/chrome.exe',
        'Microsoft/Edge/Application/msedge.exe']
    for rel in relative:
        for root in roots:
            if not root:
                continue
            candidate=Path(root)/rel
            if candidate.is_file():
                return candidate
    for name in ('brave.exe','chrome.exe','msedge.exe'):
        found=shutil.which(name)
        if found and Path(found).is_file():
            return Path(found)
    return None


def account_browser_debug_port(account_id):
    """Stable per-profile Chrome DevTools port; never a public listener."""
    ident=str(account_id).lower()
    if not re.fullmatch(r'[a-f0-9]{12}',ident):
        raise ValueError('Invalid account profile identifier.')
    return 43000+int(ident,16)%20000


def account_browser_command(browser,folder,url,debug_port=None):
    """Chromium isolated user data, never passing a username or password."""
    url=validate_habbo_login_url(url)
    browser=Path(browser)
    folder=Path(folder)
    if browser.suffix.lower()!='.exe':
        raise ValueError('Select a supported Windows browser executable.')
    args=[str(browser),'--user-data-dir='+str(folder),
          '--no-first-run','--new-window']
    if debug_port is not None:
        if not 1024<=int(debug_port)<=65535:
            raise ValueError('Invalid local browser control port.')
        args+=['--remote-debugging-address=127.0.0.1',
               '--remote-debugging-port='+str(int(debug_port))]
    return args+[url]


def account_browser_pages(debug_port):
    """Discover only page targets in a local, isolated Chromium profile."""
    if not 1024<=int(debug_port)<=65535:
        raise ValueError('Invalid local browser port.')
    req=urllib.request.Request(
        f'http://127.0.0.1:{int(debug_port)}/json/list',
        headers={'User-Agent':'HabboCompanionLocal/1.0'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req,timeout=1.5) as response:
        if response.status!=200:
            raise OSError('Browser automation endpoint not ready.')
        data=response.read(250000)
    pages=json.loads(data.decode('utf-8'))
    if not isinstance(pages,list):
        raise ValueError('Unexpected browser debugging response.')
    return [p for p in pages if isinstance(p,dict) and p.get('type')=='page'
            and isinstance(p.get('url'),str)
            and p.get('webSocketDebuggerUrl')]


def account_habbo_page(debug_port):
    """Pick a usable Habbo tab, not simply the first (possibly stale) tab.

    A profile may have several Habbo tabs. Each candidate is independently
    inspected over its own local DevTools page socket. Prefer an authenticated
    Play/Launch tab; never inspect an unrelated hostname or another profile.
    """
    pages=account_browser_pages(debug_port)
    candidates=[]
    for page in pages:
        try:
            target=urllib.parse.urlsplit(page['url'])
        except (ValueError,TypeError):
            continue
        if (target.scheme=='https' and target.hostname
            and (target.hostname=='habbo.com'
                 or target.hostname.endswith('.habbo.com'))):
            candidates.append(page)
    if not candidates:
        return None
    priorities={'launch':6,'play':5,'play-now':5,'download':4,
                'signed_in':3,'login':2,'open-login':2,'waiting':1,'not_habbo':0}
    best=None
    best_rank=-1
    last_error=''
    for page in candidates[:12]:
        try:
            step=account_inspect_play_page(page['webSocketDebuggerUrl'])
        except (OSError,RuntimeError,ValueError,socket.timeout,TimeoutError) as exc:
            # Never log session cookies, auth tokens, email or password.
            last_error=type(exc).__name__+': '+str(exc)[:95]
            continue
        kind=step.get('kind')
        score=priorities.get(kind,0)
        if score>best_rank:
            best=dict(page)
            best['_preflight_step']=step
            best_rank=score
        if score>=6:
            break
    if best is not None:
        return best
    # Preserve the category of the failed local browser operation for the
    # Accounts status instead of misreporting an active avatar as logged out.
    fallback=dict(candidates[0])
    fallback['_inspect_error']=last_error or 'No readable browser response'
    return fallback


def account_cdp_call(websocket_url,method,params=None,timeout=4):
    """Tiny one-shot Chrome DevTools client, using only Python stdlib.

    CDP is bound to loopback, never launched against a normal browser
    profile. A browser endpoint is not authentication for a Habbo avatar.
    """
    u=urllib.parse.urlsplit(websocket_url)
    if (u.scheme!='ws' or u.hostname not in ('127.0.0.1','localhost')
        or not u.port or not u.path.startswith('/devtools/page/')):
        raise ValueError('Refusing an external/non-page DevTools connection.')
    with socket.create_connection(('127.0.0.1',u.port),timeout=timeout) as sock:
        sock.settimeout(timeout)
        key=base64.b64encode(os.urandom(16)).decode('ascii')
        handshake=(
            f'GET {u.path} HTTP/1.1\r\n'
            f'Host: 127.0.0.1:{u.port}\r\n'
            'Upgrade: websocket\r\nConnection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n')
        sock.sendall(handshake.encode('ascii'))
        data=bytearray()
        while b'\r\n\r\n' not in data and len(data)<8192:
            chunk=sock.recv(4096)
            if not chunk:break
            data.extend(chunk)
        header,sep,rest=bytes(data).partition(b'\r\n\r\n')
        expected=base64.b64encode(hashlib.sha1(
            (key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('ascii')
            ).digest()).decode('ascii')
        if (not sep or not header.startswith(b'HTTP/1.1 101 ')
            or ('sec-websocket-accept: '+expected).encode('ascii').lower()
               not in header.lower()):
            first_line=header.split(b'\r\n',1)[0][:100].decode('ascii','replace')
            if not first_line.startswith('HTTP/'):
                first_line='invalid HTTP handshake'
            raise OSError('Browser DevTools socket rejected handshake: '+
                          first_line)

        def send_frame(payload,opcode=1):
            length=len(payload)
            if length<126:
                prefix=bytes([0x80|opcode,0x80|length])
            elif length<=65535:
                prefix=bytes([0x80|opcode,0x80|126])+struct.pack('!H',length)
            else:
                prefix=bytes([0x80|opcode,0x80|127])+struct.pack('!Q',length)
            mask=os.urandom(4)
            sock.sendall(prefix+mask+
                         bytes(b^mask[i%4] for i,b in enumerate(payload)))

        send_frame(json.dumps(
            {'id':1,'method':method,'params':params or {}},
            separators=(',',':')).encode('utf-8'))
        buffer=bytearray(rest)
        def read_n(n):
            while len(buffer)<n:
                chunk=sock.recv(4096)
                if not chunk:
                    raise OSError('Browser closed the debugging socket.')
                buffer.extend(chunk)
            value=bytes(buffer[:n]);del buffer[:n]
            return value
        for _ in range(80):
            b0,b1=read_n(2)
            size=b1&127
            if size==126:size=struct.unpack('!H',read_n(2))[0]
            elif size==127:size=struct.unpack('!Q',read_n(8))[0]
            if size>2_000_000:
                raise ValueError('Browser message too large.')
            mask=read_n(4) if b1&128 else None
            payload=read_n(size)
            if mask:
                payload=bytes(b^mask[i%4] for i,b in enumerate(payload))
            opcode=b0&15
            if opcode==9:
                send_frame(payload,10)
                continue
            if opcode==8:
                raise OSError('Browser closed the debugging socket.')
            if opcode!=1:
                continue
            reply=json.loads(payload.decode('utf-8'))
            if reply.get('id')!=1:
                continue
            if 'error' in reply:
                raise RuntimeError(str(reply['error'].get('message','CDP error'))[:120])
            return reply.get('result',{})
        raise TimeoutError('Browser did not answer the requested command.')


# Intentionally no authentication fields or access to cookies/tokens.
# Only inspect visible, text-labelled controls on the Habbo website.
HABBO_AUTO_PLAY_JS=r'''(() => {
  if (!/^https:$/.test(location.protocol) ||
      !/(^|\.)habbo\.com$/i.test(location.hostname))
    return {kind:'not_habbo'};
  const visible=el => {
    if (!el || el.disabled) return false;
    const rect=el.getBoundingClientRect(),style=getComputedStyle(el);
    return rect.width>0 && rect.height>0 &&
      style.display!=='none' && style.visibility!=='hidden' &&
      rect.bottom>0 && rect.top<innerHeight &&
      rect.right>0 && rect.left<innerWidth;
  };
  const label=el => (el.innerText || el.value ||
        el.getAttribute('aria-label') || el.textContent || '')
        .replace(/\s+/g,' ').trim();
  const login=Array.from(document.querySelectorAll('input[type=password]'))
    .some(visible);
  if (login) return {kind:'login',page:location.pathname};

  // The Habbo top-right PLAY control can be an anchor containing a
  // decorative H icon; don't rely on its exact innerHTML or child text.
  const matchKind=text => {
    if (/^launch\s*(?:and|&)\s*log\s*in!?$/i.test(text) ||
        /^launch\s*(?:and|&)\s*login!?$/i.test(text)) return 'launch';
    if (/^play\s*now!?(?:\s+h)?$/i.test(text)) return 'play-now';
    if (/^play\b(?:\s*[\u24bd\u24d7h])?!?$/i.test(text)) return 'play';
    if (/^download!?$/i.test(text)) return 'download';
    return null;
  };
  const clickable='a,button,[role="button"],input[type=button],input[type=submit]';
  const controls=Array.from(document.querySelectorAll(clickable));
  const match=el => {
    if (!visible(el)) return null;
    const text=label(el);
    if (!text || text.length>48) return null;
    const kind=matchKind(text);
    if (!kind) return null;
    const rect=el.getBoundingClientRect();
    return {kind,label:text,x:rect.left+rect.width/2,
            y:rect.top+rect.height/2,page:location.pathname};
  };
  // Prioritise the later "Launch and log in" step if a page has
  // both the older PLAY link and the launcher.
  const ordered=['launch','play-now','play','download'];
  const found=controls.map(match).filter(Boolean);
  for (const target of ordered) {
    const item=found.find(x=>x.kind===target);
    if (item) return item;
  }
  // A few Habbo layouts draw PLAY inside a styled div/span rather than
  // using a directly labelled button. Ascend to a clickable parent.
  const smallLabels=Array.from(document.querySelectorAll('span,strong,div'))
     .filter(el=>visible(el) && label(el).length<=32);
  for (const target of ordered) {
    for (const el of smallLabels) {
      if (matchKind(label(el))!==target) continue;
      let parent=el;
      for (let depth=0;parent && depth<4;depth++,parent=parent.parentElement) {
        const isClickable=parent.matches && parent.matches(clickable);
        const clickableStyle=visible(parent) &&
           getComputedStyle(parent).cursor==='pointer';
        if (visible(parent) &&
            (isClickable || typeof parent.onclick==='function' ||
             clickableStyle)) {
          const rect=parent.getBoundingClientRect();
          return {kind:target,label:label(el),x:rect.left+rect.width/2,
                  y:rect.top+rect.height/2,page:location.pathname};
        }
      }
    }
  }

  // On some authenticated home pages the PLAY control isn't exposed to
  // browser automation. Habbo shows the avatar name + avatar icon in a
  // dropdown at the top-right. That visible signed-in menu is separate
  // evidence of login, but *does not* authorise any guessed Play click.
  const menuItems=Array.from(document.querySelectorAll(
       'header a,header button,header [role=button],' +
       '[class*=header] a,[class*=header] button,' +
       '[class*=user] a,[class*=user] button,' +
       'a,button,[role=button]'));
  const username=/^[a-z0-9][a-z0-9._:\-]{2,31}$/i;
  const signedMenu=menuItems.find(el=>{
    if (!visible(el)) return false;
    const rect=el.getBoundingClientRect(),text=label(el);
    if (rect.top>220 || rect.left<innerWidth*0.53 ||
        rect.width>270 || rect.height>90 ||
        !username.test(text)) return false;
    const hasAvatar=!!el.querySelector('img,[class*=avatar],[class*=head]');
    const menuHint=/user|avatar|profile|account/i.test(
       String(el.className||'')+' '+String(el.getAttribute('aria-label')||''));
    return hasAvatar || menuHint;
  });
  if (signedMenu) return {kind:'signed_in',page:location.pathname,
                          evidence:'profile-menu'};
  // A signed-out landing page can hide its password form behind Log in.
  // Only identify the visible button here; Python sends a trusted click.
  const signIn=controls.find(el=> {
    if (!visible(el)) return false;
    const text=label(el);
    return text.length<=24 && /^(?:log\s*in|login|sign\s*in)$/i.test(text);
  });
  if (signIn) {
    const rect=signIn.getBoundingClientRect();
    return {kind:'open-login',label:'Log in',
            x:rect.left+rect.width/2,y:rect.top+rect.height/2,
            page:location.pathname};
  }
  return {kind:'waiting',page:location.pathname,
          reason:'no-visible-play-or-profile-menu'};
})()'''


def account_inspect_play_page(websocket_url):
    result=account_cdp_call(websocket_url,'Runtime.evaluate',{
        'expression':HABBO_AUTO_PLAY_JS,'returnByValue':True})
    if result.get('exceptionDetails'):
        raise RuntimeError('Habbo DOM inspection script failed.')
    value=result.get('result',{}).get('value')
    if not isinstance(value,dict) or not isinstance(value.get('kind'),str):
        raise RuntimeError('Habbo DOM inspection returned no readable status.')
    return value


def account_click_play_button(websocket_url,step):
    """Send a trusted Chrome mouse click, not a JS .click() fake gesture."""
    x,y=step['x'],step['y']
    for kind in ('mousePressed','mouseReleased'):
        account_cdp_call(websocket_url,'Input.dispatchMouseEvent',{
            'type':kind,'x':x,'y':y,'button':'left','clickCount':1})


# Inspect only visible login form controls on Habbo itself; never read existing
# password field values, browser cookies or session tokens.
HABBO_LOGIN_FIELDS_JS=r'''(() => {
  if (!/^https:$/.test(location.protocol) ||
      !/(^|\.)habbo\.com$/i.test(location.hostname))
    return {kind:'not_habbo'};
  const visible=el => {
    if (!el || el.disabled) return false;
    const r=el.getBoundingClientRect(),s=getComputedStyle(el);
    return r.width>0 && r.height>0 && s.display!=='none' &&
      s.visibility!=='hidden' && r.left<innerWidth && r.top<innerHeight &&
      r.right>0 && r.bottom>0;
  };
  const password=Array.from(document.querySelectorAll(
      'input[type=password]')).find(visible);
  const form=password && password.closest('form');
  // Avoid filling an unrelated header search box when the login contains a
  // plain text email field. Prefer controls inside the password's own form.
  const root=form || (password && password.closest(
      '[role=dialog],dialog,[class*=modal]')) || document;
  const candidates=Array.from(root.querySelectorAll(
      'input[type=email],input[autocomplete=username],input[placeholder*=email i],input[type=text]'
  )).filter(visible);
  const email=candidates.find(el=>el.type==='email') ||
      candidates.find(el=>/username/i.test(el.autocomplete||'') ||
        /e-?mail/i.test((el.placeholder||'')+' '+
          (el.getAttribute('aria-label')||''))) ||
      (form ? candidates.find(el=>el.type==='text') : null);
  const buttons=Array.from(root.querySelectorAll(
      'button,input[type=submit],[role=button]')).filter(visible);
  const submit=buttons.find(el =>
      /^(let'?s go!?|sign in|log in|login|continue)$/i.test(
          (el.innerText || el.value || el.getAttribute('aria-label') || '').trim()))
      || buttons.find(el => el.type==='submit');
  if (!email || !password || !submit) return {kind:'not_ready'};
  const point=el => {
    const r=el.getBoundingClientRect();
    return {x:r.left+r.width/2,y:r.top+r.height/2};
  };
  return {kind:'form',email:point(email),password:point(password),
          submit:point(submit)};
})()'''


HABBO_LOGIN_DIAGNOSTIC_JS=r'''(() => {
  if (location.protocol!=='https:' ||
      !/(^|\.)habbo\.com$/i.test(location.hostname))
    return {kind:'unverified-page'};
  const visible=el=>{
    if (!el) return false;
    const r=el.getBoundingClientRect(),s=getComputedStyle(el);
    return r.width>0 && r.height>0 && s.display!=='none' &&
           s.visibility!=='hidden';
  };
  // Inspect only login/challenge UI; return a category, never text or secrets.
  const otp=Array.from(document.querySelectorAll(
    'input[autocomplete=one-time-code],input[name*=otp i],input[name*=verification i]'
  )).some(visible);
  if (otp) return {kind:'verification'};
  // Passive/invisible CAPTCHA integrations can be mounted on login pages
  // even when there is no user-facing challenge. Never infer a required
  // human verification step from a hidden iframe or passive site markup.
  // Look only for a visible checkbox, challenge, or interactive widget.
  const captcha=Array.from(document.querySelectorAll(
    'iframe[title*=challenge i],iframe[title*=checkbox i],' +
    '.g-recaptcha,.h-captcha,.cf-turnstile,input[name*=captcha i]'
  )).some(visible);
  if (captcha) return {kind:'captcha'};
  const notices=Array.from(document.querySelectorAll(
    '[role=alert],[aria-live=assertive],[class*=error],' +
    '[class*=Error],[class*=alert],[class*=Alert]')).filter(visible);
  const hint=notices.slice(0,24).map(el=>
      (el.innerText||el.textContent||'').trim().slice(0,200))
      .filter(x=>x.length>2 && x.length<200).join(' ');
  if (/too many|try again later|rate.limit|temporarily blocked/i.test(hint))
    return {kind:'rate-limit'};
  if (/captcha|verify you are human|security check/i.test(hint))
    return {kind:'captcha'};
  if (/verification|verify your|one.time|two.factor|authenticator|security code/i.test(hint))
    return {kind:'verification'};
  if (/incorrect|invalid|wrong (?:email|password|login)|authentication failed/i.test(hint))
    return {kind:'invalid-credentials'};
  return {kind:'still-on-form'};
})()'''


def account_login_diagnostic(websocket_url):
    """Return a narrow safe failure category; no password or page text."""
    try:
        response=account_cdp_call(websocket_url,'Runtime.evaluate',{
            'expression':HABBO_LOGIN_DIAGNOSTIC_JS,
            'returnByValue':True},timeout=4)
        if response.get('exceptionDetails'):
            return 'unknown'
        value=response.get('result',{}).get('value',{})
        kind=value.get('kind') if isinstance(value,dict) else None
        allowed=('unverified-page','verification','captcha','rate-limit',
                 'invalid-credentials','still-on-form')
        return kind if kind in allowed else 'unknown'
    except (OSError,ValueError,RuntimeError,socket.timeout,TimeoutError):
        return 'unknown'


# The activeElement changes when Habbo's reactive login component
# rerenders. Find the actual login inputs by their form instead of assuming
# the keyboard focus remained where CDP clicked. Never return field contents.
# The only string substitutions are fixed, whitelist-controlled actions.
HABBO_LOGIN_INPUT_READY_JS=r'''(() => {
  if (location.protocol!=='https:' ||
      !/(^|\.)habbo\.com$/i.test(location.hostname))
    return {kind:'unverified-page'};
  const field=FIELD_PLACEHOLDER, action=ACTION_PLACEHOLDER;
  const visible=el=>{
    if (!el || el.disabled) return false;
    const r=el.getBoundingClientRect(),s=getComputedStyle(el);
    return r.width>0 && r.height>0 && s.display!=='none' &&
      s.visibility!=='hidden' && r.left<innerWidth && r.top<innerHeight &&
      r.right>0 && r.bottom>0;
  };
  const password=Array.from(document.querySelectorAll(
      'input[type=password]')).find(visible);
  if (!password) return {kind:'no-form'};
  const form=password.closest('form');
  const root=form || password.closest(
      '[role=dialog],dialog,[class*=modal]') || document;
  const candidates=Array.from(root.querySelectorAll(
      'input[type=email],input[autocomplete=username],input[placeholder*=email i],input[type=text]'
  )).filter(visible);
  const email=candidates.find(el=>el.type==='email') ||
      candidates.find(el=>/username/i.test(el.autocomplete||'') ||
        /e-?mail/i.test((el.placeholder||'')+' '+
          (el.getAttribute('aria-label')||''))) ||
      (form ? candidates.find(el=>el.type==='text') : null);
  const input=field==='password'?password:email;
  if (!input) return {kind:'no-form'};
  if (action==='focus') {
    input.focus({preventScroll:true});
    return {kind:document.activeElement===input?'focused':'not-focused'};
  }
  return {kind:input.value && input.value.length>0?'populated':'empty',
          field:field};
})()'''


def account_login_field_action(websocket_url,field,action):
    """Check/focus a selected form field, never returning user-entered text."""
    if field not in ('email','password') or action not in ('check','focus'):
        return 'invalid'
    expression=(HABBO_LOGIN_INPUT_READY_JS
                .replace('FIELD_PLACEHOLDER',json.dumps(field))
                .replace('ACTION_PLACEHOLDER',json.dumps(action)))
    result=account_cdp_call(websocket_url,'Runtime.evaluate',{
        'expression':expression,'returnByValue':True})
    if result.get('exceptionDetails'):
        return 'unknown'
    value=result.get('result',{}).get('value',{})
    if not isinstance(value,dict):
        return 'unknown'
    kind=value.get('kind')
    allowed=('populated','empty','focused','not-focused',
             'no-form','unverified-page')
    if kind not in allowed:
        return 'unknown'
    if action=='check' and kind in ('populated','empty'):
        return kind if value.get('field')==field else 'unknown'
    if action=='focus' and kind in ('focused','not-focused'):
        return kind
    return kind if kind in ('no-form','unverified-page') else 'unknown'


def account_login_input_confirmed(websocket_url,field):
    """Confirm the exact form input contains text; no values are exported."""
    return account_login_field_action(websocket_url,field,'check')=='populated'



# The login form itself is selected by DOM, not its screen coordinates. Focus
# the actual submit element, then use a browser key event. This operates only
# on the verified official Habbo HTTPS origin and never exposes field values.
# Count browser input events only; do not read credentials. CDP's
# Input.insertText should create trusted events that website handlers receive.
HABBO_LOGIN_INPUT_EVENTS_JS=r'''(() => {
  if (location.protocol!=='https:' ||
      !/(^|\.)habbo\.com$/i.test(location.hostname))
    return {kind:'unverified-page'};
  if (!window.__hcInputEventTrace) {
    const counts={email:0,password:0,emailTrusted:0,passwordTrusted:0};
    document.addEventListener('input',e=>{
      if (!e.target || e.target.tagName!=='INPUT') return;
      const isEmail=(e.target.type==='email' ||
        e.target.autocomplete==='username' ||
        /e-?mail|username/i.test(
          (e.target.placeholder||'')+' '+
          (e.target.getAttribute('aria-label')||'')));
      const kind=e.target.type==='password'?'password':
        (isEmail?'email':null);
      if (!kind) return;
      counts[kind]=Math.min(10,counts[kind]+1);
      if (e.isTrusted)
        counts[kind+'Trusted']=Math.min(10,counts[kind+'Trusted']+1);
    },true);
    window.__hcInputEventTrace=counts;
  }
  return {kind:'ready'};
})()'''


HABBO_LOGIN_INPUT_EVENTS_RESULT_JS=r'''(() => {
  if (location.protocol!=='https:' ||
      !/(^|\.)habbo\.com$/i.test(location.hostname))
    return {kind:'unverified-page'};
  const c=window.__hcInputEventTrace;
  if (!c) return {kind:'not-observed'};
  return {kind:'counts',email:c.email,password:c.password,
          emailTrusted:c.emailTrusted,passwordTrusted:c.passwordTrusted};
})()'''


# Inspect the actual login control and native form validity, then use a
# trusted browser-synthesized pointer click on its current DOM hit point.
HABBO_LOGIN_SUBMIT_FOCUS_JS=r'''(() => {
  // Inspects the real Habbo form and installs only non-secret event counters.
  // Browser Input.dispatchMouseEvent will perform the actual trusted click.
  if (location.protocol!=='https:' ||
      !/(^|\.)habbo\.com$/i.test(location.hostname))
    return {kind:'unverified-page'};
  const visible=el=>{
    if (!el) return false;
    const r=el.getBoundingClientRect(),s=getComputedStyle(el);
    return r.width>0 && r.height>0 && s.display!=='none' &&
      s.visibility!=='hidden' && r.right>0 && r.bottom>0;
  };
  const password=Array.from(document.querySelectorAll(
      'input[type=password]')).find(visible);
  if (!password) return {kind:'no-form'};
  const form=password.closest('form');
  const root=form || password.closest(
      '[role=dialog],dialog,[class*=modal]') || document;
  const candidates=Array.from(root.querySelectorAll(
      'input[type=email],input[autocomplete=username],input[placeholder*=email i],input[type=text]'
  )).filter(visible);
  const email=candidates.find(el=>el.type==='email') ||
      candidates.find(el=>/username/i.test(el.autocomplete||'') ||
        /e-?mail/i.test((el.placeholder||'')+' '+
          (el.getAttribute('aria-label')||''))) ||
      (form ? candidates.find(el=>el.type==='text') : null);
  const controls=Array.from(root.querySelectorAll(
      'button,input[type=submit],[role=button]')).filter(visible);
  const text=el=>(el.innerText || el.value ||
      el.getAttribute('aria-label') || '').trim();
  const submit=controls.find(el=>/^(let'?s go!?|sign in|log in|login|continue)$/i
      .test(text(el))) || controls.find(el=>el.type==='submit');
  if (!email || !submit) return {kind:'no-submit-or-email'};
  if (!email.value) return {kind:'empty-email'};
  if (!password.value) return {kind:'empty-password'};
  if (email.validity && !email.validity.valid) return {kind:'invalid-email'};
  if (password.validity && !password.validity.valid)
    return {kind:'invalid-password'};
  if (form && typeof form.checkValidity==='function' &&
      !form.checkValidity()) return {kind:'invalid-form'};
  if (submit.disabled || submit.getAttribute('aria-disabled')==='true')
    return {kind:'button-disabled'};
  if (!visible(submit)) return {kind:'button-not-visible'};
  try { submit.scrollIntoView({block:'center',inline:'center',behavior:'instant'}); }
  catch (_) { submit.scrollIntoView(); }
  const r=submit.getBoundingClientRect();
  // A centre-only hit test incorrectly treats a partly covered button as
  // wholly blocked. Check nine well-separated points *within the same
  // verified button*, never click an unrelated overlay or challenge.
  const offsets=[[.5,.5],[.25,.5],[.75,.5],[.5,.25],[.5,.75],
                 [.25,.25],[.75,.25],[.25,.75],[.75,.75]];
  let chosen=null,inspected=0,centerBlocked=false,blocker=null;
  const isPartOfSubmit=hit=>{
    if (!hit) return false;
    if (hit===submit || submit.contains(hit)) return true;
    // A button may host a shadow-root child; its hit-test belongs to the
    // submit control, not to a sibling that obstructs the button.
    const root=typeof hit.getRootNode==='function'?hit.getRootNode():null;
    return !!(root && root.host===submit);
  };
  for (const [fx,fy] of offsets) {
    const x=r.left+r.width*fx,y=r.top+r.height*fy;
    if (!(x>=0 && y>=0 && x<innerWidth && y<innerHeight)) continue;
    const hit=document.elementFromPoint(x,y);
    inspected++;
    if (isPartOfSubmit(hit)) {
      chosen={x,y};
      break;
    }
    if (fx===.5 && fy===.5) centerBlocked=true;
    if (!blocker && hit) {
      const tag=String(hit.tagName||'UNKNOWN').toUpperCase();
      const rawRole=hit.getAttribute&&hit.getAttribute('role');
      const role=String(rawRole||'').toLowerCase();
      const allowedTags=['DIV','SPAN','IFRAME','DIALOG','BUTTON','LABEL',
        'SECTION','FORM','IMG','INPUT','A','BODY','HTML','HEADER','MAIN',
        'P','ARTICLE','UNKNOWN'];
      const allowedRoles=['dialog','alertdialog','button','presentation',
        'none','status','group','form','alert'];
      blocker={tag:allowedTags.includes(tag)?tag:'OTHER',
               role:allowedRoles.includes(role)?role:'none'};
      if ((hit.closest && hit.closest('[role=dialog],[role=alertdialog],dialog')) ||
          tag==='DIALOG') blocker.role='dialog';
    }
  }
  if (!chosen) {
    if (inspected===0) return {kind:'button-offscreen'};
    return {kind:'button-obstructed',tested:inspected,
            blockerTag:blocker?blocker.tag:'UNKNOWN',
            blockerRole:blocker?blocker.role:'none'};
  }
  const x=chosen.x,y=chosen.y;
  // Lightweight event instrumentation to check whether the browser generated
  // a trusted click and whether the native form submitted. No input values.
  if (!window.__hcLoginEventTrace) {
    const trace={trustedClicks:0,untrustedClicks:0,formSubmits:0};
    document.addEventListener('click',event=>{
      const target=event.target;
      if (target && (target===submit || submit.contains(target))) {
        if (event.isTrusted) trace.trustedClicks++;
        else trace.untrustedClicks++;
      }
    },true);
    document.addEventListener('submit',event=>{
      if (form && event.target===form) trace.formSubmits++;
    },true);
    window.__hcLoginEventTrace=trace;
  }
  return {kind:'ready',x,y,centerBlocked,tested:inspected};
})()'''


HABBO_LOGIN_CLICK_TRACE_JS=r'''(() => {
  if (location.protocol!=='https:' ||
      !/(^|\.)habbo\.com$/i.test(location.hostname))
    return {kind:'unverified-page'};
  const t=window.__hcLoginEventTrace;
  if (!t) return {kind:'not-observed'};
  return {kind:'trace',
          trusted:Math.min(3,t.trustedClicks||0),
          untrusted:Math.min(3,t.untrustedClicks||0),
          submits:Math.min(3,t.formSubmits||0)};
})()'''


def account_login_auth_request(url,method):
    """Recognise first-party authentication requests; never return their URL."""
    if method not in ('POST','PUT','PATCH'):
        return False
    try:
        parts=urllib.parse.urlsplit(url)
        host=(parts.hostname or '').lower()
    except (TypeError,ValueError):
        return False
    return (parts.scheme=='https' and
            (host=='habbo.com' or host.endswith('.habbo.com')) and
            bool(re.search(r'auth|log[ -]?in|signin|sign-in|session|sso',
                           parts.path,re.I)))


def account_login_safe_error_code(body):
    """Only symbolic error identifiers. Never return message/body/user details."""
    if not isinstance(body,str) or len(body)>8192:
        return None
    try:
        payload=json.loads(body)
    except (TypeError,ValueError):
        return None
    if not isinstance(payload,dict):
        return None
    candidates=[payload]
    error=payload.get('error')
    if isinstance(error,dict):
        candidates.append(error)
    for item in candidates:
        for key in ('errorCode','error_code','code'):
            value=item.get(key)
            if (isinstance(value,str) and
                re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{1,48}',value) and
                not re.fullmatch(r'[A-Za-z0-9]{32,}',value) and
                not value.lower().startswith(('eyj','bearer','hhus'))):
                return value
    return None



def account_login_safe_server_message(body):
    """Expose only generic, known authentication-denial text verbatim.

    Servers sometimes include email, names or tokens in error strings. Never
    display arbitrary response text. Unrecognised messages remain withheld
    while the actual HTTP status and safe symbolic codes are still shown.
    """
    if not isinstance(body,str) or len(body)>8192:
        return None
    try:
        obj=json.loads(body)
    except (ValueError,TypeError):
        return None
    if not isinstance(obj,dict):
        return None
    entries=[obj]
    if isinstance(obj.get('error'),dict):
        entries.append(obj['error'])
    permitted={
        'invalid credentials','invalid email or password',
        'invalid username or password','incorrect email or password',
        'incorrect username or password','wrong email or password',
        'wrong username or password','incorrect password',
        'invalid password','authentication failed','login failed',
        'verification required','captcha required','access denied',
        'account locked','account disabled','too many requests',
        'too many login attempts','rate limit exceeded',
        'unauthorized','forbidden'
    }
    for item in entries:
        for name in ('message','error_description','detail'):
            msg=item.get(name)
            if isinstance(msg,str) and 5<=len(msg)<=140:
                simple=' '.join(msg.strip().lower().strip(' .!').split())
                if simple in permitted:
                    return msg.strip()
    return None


# URLs, query parameters, source text, JS exception bodies and arbitrary
# path segments may contain secrets. Only pass this bounded data to logs.
HABBO_SAFE_URL_PARTS=frozenset({
    'api','auth','authentication','authorize','login','logout','signin',
    'sign-in','session','sso','client','clientnative','url','account',
    'accounts','user','users','profile','home','public','native','status',
    'email','verify','verification','config','settings','feature','flags',
    'ping','token','ticket','security','challenge','captcha','loginpage',
    'login-form','external','v1','v2','v3','v4','v5','web','hotel',
    'system','info','identity','connect','oauth','authorize','callback',
    'validate','availability','graphql','action','credentials'
})


def account_login_safe_endpoint_path(url):
    """Reveal only recognised public route words, never opaque URL parts."""
    if not isinstance(url,str):
        return '/[hidden]'
    try:
        path=urllib.parse.urlsplit(url).path
    except (ValueError,TypeError):
        return '/[hidden]'
    parts=[p for p in path.split('/') if p]
    if not parts:
        return '/'
    result=[]
    for part in parts[:6]:
        if re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,23}',part) and (
                part.lower() in HABBO_SAFE_URL_PARTS):
            result.append(part.lower())
        else:
            result.append('[hidden]')
    if len(parts)>6:
        result.append('[more]')
    return '/'+'/'.join(result)


def account_login_safe_browser_error(text):
    """Categorise untrusted console/exception text without quoting secrets."""
    if not isinstance(text,str):
        return 'unknown error'
    if re.search(r'content.security.policy|\bcsp\b',text,re.I):
        return 'Content Security Policy blocked a resource'
    if re.search(r'cross.origin|\bcors\b',text,re.I):
        return 'CORS restriction'
    if re.search(r'failed to fetch|fetch failed',text,re.I):
        return 'Failed to fetch'
    if re.search(r'failed to load resource',text,re.I):
        code=re.search(r'\b(?:HTTP\s*)?(4\d\d|5\d\d)\b',text,re.I)
        if code:
            return 'Resource load HTTP '+code.group(1)
        return 'Resource failed to load'
    if re.search(r'net::ERR_[A-Z_]{3,50}',text):
        return re.search(r'net::ERR_[A-Z_]{3,50}',text).group(0)
    for error in ('TypeError','ReferenceError','SyntaxError','RangeError',
                  'NetworkError','SecurityError','NotAllowedError',
                  'AbortError','URIError','ChunkLoadError','EvalError'):
        if re.search(r'\b'+error+r'\b',text):
            return error
    if re.search(r'uncaught.*promise|unhandled.*rejection',text,re.I):
        return 'Uncaught promise rejection'
    return 'unclassified error'


def account_login_safe_error_location(url,line):
    """Allow only a broad source origin class and non-secret line number."""
    if not isinstance(url,str):
        return ''
    try:
        parts=urllib.parse.urlsplit(url)
        host=(parts.hostname or '').lower()
        if parts.scheme!='https':
            return ''
        source=('Habbo script' if host=='habbo.com' or
                host.endswith('.habbo.com') else 'external script')
    except (TypeError,ValueError):
        return ''
    if type(line) is int and 0<=line<=100000:
        return ' ('+source+', line '+str(line)+')'
    return ' ('+source+')'


class AccountLoginNetworkProbe:
    """Short-lived, account-specific page traffic monitor.

    Watch every HTTPS page request, rather than guessing an auth endpoint from
    its URL. Only print bounded, redacted method/type/origin-class and status
    summaries. No URLs, query strings, request headers, payloads, cookies,
    tokens, or raw browser console strings leave this monitor.
    """
    def __init__(self,websocket_url):
        self.url=websocket_url
        self.sock=None
        self.buffer=bytearray()
        self.sequence=0
        self.auth_ids=set()
        self.seen=False
        self.http_status=None
        self.failed=None
        self.mime=''
        self.finished_id=None
        self.error_code=None
        self.error_message=None
        self.javascript_exceptions=0
        self.requests={}
        self.request_count=0
        self.interesting_count=0
        self.responses=0
        self.failure_count=0
        self.redirect_count=0
        self.error_candidates=[]
        self.report=None
        self.lines_printed=0
        self.important_lines=0
        self.phase='startup'

    def __enter__(self):
        url=urllib.parse.urlsplit(self.url)
        if (url.scheme!='ws' or url.hostname!='127.0.0.1' or
            not url.port or not url.path.startswith('/devtools/page/')):
            raise ValueError('Only isolated local account browser monitoring is allowed.')
        self.sock=socket.create_connection(('127.0.0.1',url.port),timeout=3)
        try:
            self.sock.settimeout(3)
            key=base64.b64encode(os.urandom(16)).decode('ascii')
            expected=base64.b64encode(hashlib.sha1(
                (key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
                 ).encode('ascii')).digest()).decode('ascii')
            req=(f'GET {url.path} HTTP/1.1\r\n'
                 f'Host: 127.0.0.1:{url.port}\r\n'
                 'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                 f'Sec-WebSocket-Key: {key}\r\n'
                 'Sec-WebSocket-Version: 13\r\n\r\n')
            self.sock.sendall(req.encode('ascii'))
            while b'\r\n\r\n' not in self.buffer and len(self.buffer)<8192:
                data=self.sock.recv(4096)
                if not data:
                    raise OSError('Local browser network observer closed.')
                self.buffer.extend(data)
            header,sep,rest=bytes(self.buffer).partition(b'\r\n\r\n')
            if (not sep or not header.startswith(b'HTTP/1.1 101 ') or
                ('sec-websocket-accept: '+expected).encode('ascii').lower()
                 not in header.lower()):
                raise OSError('Local browser network observer refused connection.')
            self.buffer=bytearray(rest)
            return self
        except Exception:
            self.sock.close()
            self.sock=None
            raise

    def __exit__(self,kind,error,trace):
        if self.sock is not None:
            self.sock.close()
            self.sock=None

    def _send(self,payload,opcode=1):
        data=(json.dumps(payload,separators=(',',':')).encode('utf-8')
              if opcode==1 else payload)
        n=len(data)
        prefix=(bytes([0x80|opcode,0x80|n]) if n<126 else
                bytes([0x80|opcode,0x80|126])+struct.pack('!H',n)
                if n<=65535 else
                bytes([0x80|opcode,0x80|127])+struct.pack('!Q',n))
        mask=os.urandom(4)
        self.sock.sendall(prefix+mask+
                          bytes(byte^mask[i%4] for i,byte in enumerate(data)))

    def _take(self,n):
        while len(self.buffer)<n:
            chunk=self.sock.recv(4096)
            if not chunk:
                raise OSError('Local browser network observer disconnected.')
            self.buffer.extend(chunk)
        part=bytes(self.buffer[:n])
        del self.buffer[:n]
        return part

    def _next(self,timeout):
        self.sock.settimeout(max(0.05,timeout))
        for _ in range(200):
            b0,b1=self._take(2)
            size=b1&127
            if size==126:
                size=struct.unpack('!H',self._take(2))[0]
            elif size==127:
                size=struct.unpack('!Q',self._take(8))[0]
            if size>2_000_000:
                raise ValueError('Oversized browser event.')
            mask=self._take(4) if b1&128 else None
            data=self._take(size)
            if mask:
                data=bytes(byte^mask[i%4] for i,byte in enumerate(data))
            op=b0&15
            if op==9:
                self._send(data,10)
                continue
            if op==8:
                raise OSError('Browser page closed during login.')
            if op!=1:
                continue
            message=json.loads(data.decode('utf-8'))
            self._event(message)
            return message
        raise TimeoutError('Too many browser protocol events.')

    def _emit(self,line,important=False):
        # Reserve room for HTTP errors even if background XHR traffic is noisy.
        # All callers construct redacted, bounded, no-secret strings.
        if important:
            if self.important_lines>=8:
                return
            self.important_lines+=1
        else:
            if self.lines_printed>=12:
                return
            self.lines_printed+=1
        if self.report is not None:
            self.report(line)

    def _event(self,msg):
        name=msg.get('method')
        data=msg.get('params') or {}
        ident=data.get('requestId')
        if name=='Network.requestWillBeSent':
            req=data.get('request') or {}
            method=req.get('method')
            url=req.get('url')
            if not isinstance(url,str) or not isinstance(method,str):
                return
            try:
                target=urllib.parse.urlsplit(url)
                host=(target.hostname or '').lower()
            except (TypeError,ValueError):
                return
            if target.scheme!='https' or not host:
                return
            self.request_count+=1
            # The browser may reuse a request ID for an HTTP redirect.
            prior=self.requests.pop(ident,None)
            redirect=data.get('redirectResponse')
            if prior and isinstance(redirect,dict):
                self.redirect_count+=1
                status=redirect.get('status')
                if isinstance(status,(int,float)) and 300<=status<=399:
                    self._emit('SERVER <- #'+str(prior['ref'])+
                               ' HTTP '+str(int(status))+
                               ' redirect ('+prior['site']+').')
            is_habbo=(host=='habbo.com' or host.endswith('.habbo.com'))
            site='Habbo site' if is_habbo else 'external HTTPS site'
            resource=data.get('type')
            if resource not in ('Fetch','XHR','Document'):
                resource='Other'
            # Include all methods capable of login submission and all XHR
            # and fetch traffic regardless of URL path, including external
            # identity providers. Ignore static images/scripts and never
            # expose the hostname or query string in UI/logs.
            relevant=(method in ('POST','PUT','PATCH','DELETE','OPTIONS') or
                      resource in ('Fetch','XHR','Document'))
            if not relevant:
                return
            self.interesting_count+=1
            if len(self.requests)>=48:
                return
            if not re.fullmatch(r'[A-Z]{2,10}',method):
                method='HTTP'
            self.requests[ident]={'site':site,'method':method,
                                  'resource':resource,'status':None,
                                  'mime':'','failed':None,
                                  'ref':self.interesting_count,
                                  'path':account_login_safe_endpoint_path(url)}
            if account_login_auth_request(url,method):
                self.auth_ids.add(ident)
                self.seen=True
            self._emit('CLIENT -> #'+str(self.interesting_count)+
                       ' '+method+' '+self.requests[ident]['path']+
                       ' ('+site+', '+resource+').')
        elif name=='Network.responseReceived' and ident in self.requests:
            rec=self.requests[ident]
            response=data.get('response') or {}
            code=response.get('status')
            if isinstance(code,(int,float)) and 100<=code<=599:
                rec['status']=int(code)
                self.http_status=int(code)
                self.responses+=1
                self._emit('SERVER <- #'+str(rec['ref'])+' HTTP '+
                           str(int(code))+' '+rec['path']+
                           ' ('+rec['site']+', '+rec['resource']+').',
                           important=int(code)>=400)
            mime=response.get('mimeType')
            rec['mime']=mime.lower() if isinstance(mime,str) else ''
            self.mime=rec['mime']
        elif name=='Network.loadingFailed' and ident in self.requests:
            rec=self.requests[ident]
            blocked=data.get('blockedReason')
            error=data.get('errorText')
            if isinstance(blocked,str) and re.fullmatch(r'[A-Za-z_-]{2,32}',blocked):
                kind='blocked-'+blocked
            elif isinstance(error,str) and re.fullmatch(r'net::ERR_[A-Z_]{2,50}',error):
                kind=error
            else:
                kind='network-error'
            rec['failed']=kind
            self.failed=kind
            self.failure_count+=1
            self._emit('NETWORK <- #'+str(rec['ref'])+' '+kind+
                       ' ('+rec['site']+').',important=True)
        elif name=='Network.loadingFinished' and ident in self.requests:
            rec=self.requests[ident]
            if (rec['status'] is not None and rec['status']>=400 and
                'json' in rec['mime'] and rec['site']=='Habbo site' and
                len(self.error_candidates)<3):
                self.error_candidates.append(ident)
                self.finished_id=ident
        elif name=='Runtime.exceptionThrown':
            self.javascript_exceptions+=1
            if self.javascript_exceptions<=3:
                details=data.get('exceptionDetails') or {}
                exception=details.get('exception') or {}
                # The raw description may include credentials or app state.
                # Only return a tightly bounded recognised error category.
                category=account_login_safe_browser_error(
                    exception.get('description') or details.get('text'))
                location=account_login_safe_error_location(
                    details.get('url'),details.get('lineNumber'))
                self._emit('BROWSER <- '+self.phase+' JS '+category+location+
                           ' (not necessarily the login failure).',
                           important=True)
        elif name=='Log.entryAdded':
            entry=data.get('entry') or {}
            if entry.get('level')=='error':
                self.javascript_exceptions+=1
                if self.javascript_exceptions<=3:
                    category=account_login_safe_browser_error(entry.get('text'))
                    location=account_login_safe_error_location(
                        entry.get('url'),entry.get('lineNumber'))
                    self._emit('BROWSER <- '+self.phase+' console '+category+
                               location+'.',important=True)

    def _command(self,method,params=None,timeout=3):
        self.sequence+=1
        command_id=self.sequence
        self._send({'id':command_id,'method':method,'params':params or {}})
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            message=self._next(deadline-time.monotonic())
            if message.get('id')!=command_id:
                continue
            if 'error' in message:
                raise RuntimeError('Browser event observer command failed.')
            return message.get('result',{})
        raise TimeoutError('Browser did not confirm network observer command.')

    def enable(self):
        self._command('Network.enable',{'maxTotalBufferSize':1048576})
        self._command('Runtime.enable',{})
        try:
            self._command('Log.enable',{},timeout=1.5)
        except (OSError,ValueError,RuntimeError,socket.timeout,TimeoutError):
            # Not all Chromium builds support this domain on a page target.
            pass

    def observe(self,seconds=5.0):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            try:
                self._next(min(0.6,deadline-time.monotonic()))
            except socket.timeout:
                continue
            except (OSError,ValueError,TimeoutError):
                break
        # Only read unsuccessful JSON responses from the verified Habbo
        # origin, never successful bodies or external-provider payloads.
        for ident in self.error_candidates[:2]:
            try:
                result=self._command('Network.getResponseBody',
                                     {'requestId':ident},timeout=2)
                body=result.get('body')
                if result.get('base64Encoded') and isinstance(body,str):
                    body=base64.b64decode(body,validate=True).decode('utf-8')
                code=account_login_safe_error_code(body)
                message=account_login_safe_server_message(body)
                if code:
                    self.error_code=code
                    self._emit('SERVER <- Error code: '+code+'.',important=True)
                if message:
                    self.error_message=message
                    self._emit('SERVER <- Error message: '+message+'.',
                               important=True)
                if code or message:
                    break
            except (OSError,ValueError,RuntimeError,TimeoutError,
                    UnicodeError,TypeError):
                continue

    def summary(self):
        if self.interesting_count==0:
            return ('Login diagnostic: '+str(self.request_count)+
                    ' HTTPS request(s) observed on this page, but no '
                    'XHR/fetch/form request. No server login response '
                    'was captured; a browser-side issue is possible.')
        result=('Login diagnostic: '+str(self.interesting_count)+
                ' XHR/fetch/form request(s), '+str(self.responses)+
                ' HTTP response(s), '+str(self.redirect_count)+
                ' redirect(s), '+str(self.failure_count)+
                ' network failure(s).')
        if self.http_status is not None:
            result+=' Last observed HTTP '+str(self.http_status)+'.'
        if self.error_code:
            result+=' Server error code: '+self.error_code+'.'
        if self.error_message:
            result+=' Server message: '+self.error_message+'.'
        if not self.seen:
            result+=' No endpoint was independently identified as authentication.'
        if self.javascript_exceptions:
            result+=' Browser error(s): '+str(self.javascript_exceptions)+'.'
        result+=' HTTP 2xx alone does not confirm login; official SSO checks follow.'
        return result


def account_login_submit_readiness(websocket_url):
    """Return only safe form readiness and an ephemeral viewport hit point."""
    result=account_cdp_call(websocket_url,'Runtime.evaluate',{
        'expression':HABBO_LOGIN_SUBMIT_FOCUS_JS,'returnByValue':True})
    if result.get('exceptionDetails'):
        return {'kind':'inspection-error'}
    value=result.get('result',{}).get('value',{})
    if not isinstance(value,dict):
        return {'kind':'inspection-error'}
    allowed=('unverified-page','no-form','no-submit-or-email',
             'empty-email','empty-password','invalid-email',
             'invalid-password','invalid-form','button-disabled',
             'button-not-visible','button-offscreen',
             'button-obstructed','ready')
    kind=value.get('kind')
    if kind not in allowed:
        return {'kind':'inspection-error'}
    if kind=='button-obstructed':
        # Do not trust arbitrary page text or attributes as log messages.
        tested=value.get('tested')
        tag=value.get('blockerTag')
        role=value.get('blockerRole')
        if type(tested) is not int or not 1<=tested<=9:
            tested=0
        if tag not in ('DIV','SPAN','IFRAME','DIALOG','BUTTON','LABEL',
                       'SECTION','FORM','IMG','INPUT','A','BODY','HTML',
                       'HEADER','MAIN','P','ARTICLE','UNKNOWN','OTHER'):
            tag='UNKNOWN'
        if role not in ('dialog','alertdialog','button','presentation',
                        'none','status','group','form','alert'):
            role='none'
        return {'kind':kind,'tested':tested,'blockerTag':tag,'blockerRole':role}
    if kind!='ready':
        return {'kind':kind}
    x,y=value.get('x'),value.get('y')
    if (isinstance(x,bool) or isinstance(y,bool) or
        not isinstance(x,(int,float)) or not isinstance(y,(int,float)) or
        not math.isfinite(x) or not math.isfinite(y) or
        not 0<=x<=5000 or not 0<=y<=5000):
        return {'kind':'inspection-error'}
    center_blocked=value.get('centerBlocked')
    tested=value.get('tested')
    return {'kind':'ready','x':x,'y':y,
            'centerBlocked':center_blocked is True,
            'tested':tested if type(tested) is int and 1<=tested<=9 else 0}


def account_login_wait_for_submit_point(websocket_url):
    """Retry hit-testing only; never retry a credential submission."""
    ready={'kind':'inspection-error'}
    for attempt in range(3):
        ready=account_login_submit_readiness(websocket_url)
        if ready.get('kind')!='button-obstructed':
            return ready
        if attempt<2:
            time.sleep(0.55)
    return ready


def account_login_preflight_message(ready):
    """Explain an obstructed DOM button without exposing page contents."""
    kind=ready.get('kind','inspection-error')
    if kind=='ready':
        if ready.get('centerBlocked'):
            return ('FORM <- ready (button centre covered, but a verified '
                    'unobstructed point on the login button was found).')
        return 'FORM <- ready (fields populated, button unobstructed).'
    if kind=='button-obstructed':
        return ('FORM <- button-obstructed: '+str(ready.get('tested',0))+
                ' inspected button points covered; top element '+
                str(ready.get('blockerTag','UNKNOWN'))+' (role '+
                str(ready.get('blockerRole','none'))+
                '). No login click attempted.')
    return 'FORM <- '+kind+' (no login click attempted).'


def account_login_click_trace(websocket_url):
    """Read bounded click/submit event counts, never login field contents."""
    try:
        result=account_cdp_call(websocket_url,'Runtime.evaluate',{
            'expression':HABBO_LOGIN_CLICK_TRACE_JS,'returnByValue':True},
            timeout=2)
        value=result.get('result',{}).get('value',{})
        if not isinstance(value,dict) or value.get('kind')!='trace':
            return None
        counts=[]
        for name in ('trusted','untrusted','submits'):
            count=value.get(name)
            if not isinstance(count,int) or isinstance(count,bool) or not 0<=count<=3:
                return None
            counts.append(count)
        return counts
    except (OSError,RuntimeError,ValueError,TimeoutError,socket.timeout):
        return None


def account_focus_and_submit_login(websocket_url,ready=None):
    """Trusted Chrome pointer click on the verified DOM button.

    The viewport hit point comes from the inspected element immediately
    before the click. It is not a stored screen coordinate or a JS .click().
    This works in headless Chromium without moving the Windows OS cursor.
    """
    if ready is None:
        ready=account_login_submit_readiness(websocket_url)
    if ready.get('kind')!='ready':
        return False
    x,y=ready['x'],ready['y']
    account_cdp_call(websocket_url,'Input.dispatchMouseEvent',{
        'type':'mouseMoved','x':x,'y':y,'button':'none'})
    account_cdp_call(websocket_url,'Input.dispatchMouseEvent',{
        'type':'mousePressed','x':x,'y':y,'button':'left','clickCount':1})
    # Do not issue the click a second time if navigation immediately closes
    # the page socket during release. Let the existing session checks decide.
    try:
        account_cdp_call(websocket_url,'Input.dispatchMouseEvent',{
            'type':'mouseReleased','x':x,'y':y,'button':'left','clickCount':1})
    except (OSError,RuntimeError,ValueError,TimeoutError,socket.timeout):
        pass
    return True


def account_submit_with_network_diagnostics(websocket_url,report):
    """Monitor safe browser & HTTP evidence before one trusted DOM click."""
    started=False
    try:
        with AccountLoginNetworkProbe(websocket_url) as probe:
            probe.report=report
            probe.enable()
            started=True
            ready=account_login_wait_for_submit_point(websocket_url)
            report(account_login_preflight_message(ready))
            if ready['kind']!='ready':
                return False
            probe.phase='after-submit'
            report('BROWSER -> Trusted browser click on Habbo LETS GO element.')
            submitted=account_focus_and_submit_login(websocket_url,ready)
            if not submitted:
                report('BROWSER <- Habbo submit element could not be activated.')
                return False
            probe.observe(seconds=7.0)
            trace=account_login_click_trace(websocket_url)
            if trace is not None:
                report('BROWSER <- Login button trusted click event(s): '+
                       str(trace[0])+', untrusted: '+str(trace[1])+
                       ', native form submit event(s): '+str(trace[2])+'.')
            else:
                report('BROWSER <- Click/submit events unavailable after '
                       'login attempt (possibly due to navigation).')
            report(probe.summary())
            return True
    except (OSError,ValueError,RuntimeError,socket.timeout,TimeoutError):
        if started:
            # Never retry after a click might already have reached Habbo.
            report('Login diagnostics interrupted; the submit outcome is '
                   'unverified. No automatic duplicate request sent.')
            return True
        report('Login network observer unavailable. Checking the Habbo form '
               'before one trusted browser click without traffic capture.')
        ready=account_login_wait_for_submit_point(websocket_url)
        report(account_login_preflight_message(ready))
        return account_focus_and_submit_login(websocket_url,ready)


def account_login_input_event_counts(websocket_url):
    """Return bounded browser input-event counters, never input contents."""
    try:
        result=account_cdp_call(websocket_url,'Runtime.evaluate',{
            'expression':HABBO_LOGIN_INPUT_EVENTS_RESULT_JS,
            'returnByValue':True},timeout=2)
        val=result.get('result',{}).get('value',{})
        if not isinstance(val,dict) or val.get('kind')!='counts':
            return None
        out={}
        for key in ('email','password','emailTrusted','passwordTrusted'):
            n=val.get(key)
            if type(n) is not int or not 0<=n<=10:
                return None
            out[key]=n
        return out
    except (OSError,RuntimeError,ValueError,TimeoutError,socket.timeout):
        return None


def account_submit_saved_login(websocket_url,email,password,report=None):
    """Enter a saved login on official Habbo and verify before submission."""
    def fields_now():
        result=account_cdp_call(websocket_url,'Runtime.evaluate',{
            'expression':HABBO_LOGIN_FIELDS_JS,'returnByValue':True})
        return result.get('result',{}).get('value',{})

    # Observe the browser's input events before entering credentials.
    # Failure to instrument does not block legitimate website login.
    if report is not None:
        try:
            account_cdp_call(websocket_url,'Runtime.evaluate',{
                'expression':HABBO_LOGIN_INPUT_EVENTS_JS,
                'returnByValue':True},timeout=2)
        except (OSError,RuntimeError,ValueError,TimeoutError,socket.timeout):
            report('FORM <- Browser input event tracing unavailable.')
    for field,value in (('email',email),('password',password)):
        fields=fields_now()
        if fields.get('kind')!='form':
            return False
        for attempt in range(2):
            # Focus the selected form input directly rather than relying on
            # browser viewport coordinates. Actual typing still uses trusted
            # CDP keyboard/input events, not JS setting element.value.
            if account_login_field_action(
                    websocket_url,field,'focus')!='focused':
                return False
            account_cdp_call(websocket_url,'Input.dispatchKeyEvent',{
                'type':'keyDown','key':'a','code':'KeyA',
                'windowsVirtualKeyCode':65,'modifiers':2})
            account_cdp_call(websocket_url,'Input.dispatchKeyEvent',{
                'type':'keyUp','key':'a','code':'KeyA',
                'windowsVirtualKeyCode':65,'modifiers':2})
            # Only local CDP types the saved value. JS never receives it.
            account_cdp_call(websocket_url,'Input.insertText',{'text':value})
            time.sleep(0.15)
            if account_login_input_confirmed(websocket_url,field):
                break
        else:
            return False
    if report is not None:
        counts=account_login_input_event_counts(websocket_url)
        if counts is None:
            report('FORM <- Browser input event counts unavailable.')
        else:
            report('FORM <- Email input events '+str(counts['email'])+
                   ' (trusted '+str(counts['emailTrusted'])+
                   '); password input events '+str(counts['password'])+
                   ' (trusted '+str(counts['passwordTrusted'])+').')
    # The form can move or enable its submit button after input changes.
    fields=fields_now()
    if fields.get('kind')!='form':
        return False
    time.sleep(0.2)
    return account_submit_with_network_diagnostics(
        websocket_url,report or (lambda message:None))


def account_attempt_auto_play(debug_port,report,credentials=None,login_only=False):
    """Sign into an isolated profile if saved; optionally continue to Classic."""
    previous=None
    identical=0
    login_submitted=False
    login_waits=0
    login_prompt_clicks=0
    unrecognised_pages=0
    last_issue='No Habbo website tab detected in this browser profile.'
    control_failures=0
    missing_pages=0
    for iteration in range(28):
        try:
            page=account_habbo_page(debug_port)
        except (OSError,RuntimeError,ValueError,socket.timeout,TimeoutError) as exc:
            control_failures+=1
            last_issue='Browser control endpoint failed: '+type(exc).__name__
            if control_failures>=3:
                report(last_issue+'; close this account browser and retry.')
                return 'control_error'
            time.sleep(0.6);continue
        if page is None:
            missing_pages+=1
            last_issue='No HTTPS Habbo website tab detected in this profile.'
            if missing_pages>=6:
                report(last_issue)
                return 'no_habbo_tab'
            time.sleep(0.6);continue
        if page.get('_inspect_error'):
            control_failures+=1
            last_issue='Browser inspection failed: '+str(page['_inspect_error'])[:105]
            if control_failures>=3:
                report(last_issue+'; DevTools control is not working.')
                return 'inspect_error'
            time.sleep(0.6);continue
        try:
            step=page.get('_preflight_step') or account_inspect_play_page(
                page['webSocketDebuggerUrl'])
        except (OSError,RuntimeError,ValueError,socket.timeout,TimeoutError) as exc:
            control_failures+=1
            last_issue='Browser inspection failed: '+type(exc).__name__
            if control_failures>=3:
                report(last_issue)
                return 'inspect_error'
            time.sleep(0.6);continue
        control_failures=0
        kind=step.get('kind')
        if kind!='not_habbo':
            unrecognised_pages=0
        last_issue='Visible Play button and signed-in profile menu not detected.'
        if kind=='open-login':
            if not credentials:
                report('Sign in once manually or save email/password in the '
                       'Accounts tab for automatic sign-in.')
                return 'login'
            login_prompt_clicks+=1
            if login_prompt_clicks>2:
                report('The Habbo sign-in form did not open in the background '
                       'browser. Use Accounts > Open account login once.')
                return 'waiting'
            account_click_play_button(page['webSocketDebuggerUrl'],step)
            report('Opening the official Habbo sign-in form for this account.')
            time.sleep(1.1)
            continue
        if kind=='login':
            if not credentials:
                report('Sign in once manually or save email/password in the '
                       'Accounts tab for automatic sign-in.')
                return 'login'
            if login_submitted:
                login_waits+=1
                if login_waits>=8:
                    issue=account_login_diagnostic(
                        page['webSocketDebuggerUrl'])
                    details={
                        'invalid-credentials':'Habbo displayed a login error. '
                            'Check Account 2 saved email and password in Accounts.',
                        'verification':'Habbo appears to require a verification '
                            'code. Use Accounts > Open account login.',
                        'captcha':'A visible Habbo verification challenge was '
                            'detected. Open Accounts > Open account login and '
                            'complete it manually; background retries cannot '
                            'solve verification.',
                        'rate-limit':'Habbo appears to be limiting login attempts. '
                            'Avoid repeated automatic retries and try later.',
                        'unverified-page':'Browser navigated away from the '
                            'verified Habbo HTTPS page; no retry attempted.',
                        'still-on-form':'Habbo still shows the login form, but '
                            'no recognised error or challenge was detected. '
                            'Use Accounts > Open account login to check it.',
                        'unknown':'Could not inspect the Habbo login response. '
                            'Use Accounts > Open account login to check it.'
                    }
                    report(details[issue])
                    return 'login'
                time.sleep(1.2)
                continue
            if not account_submit_saved_login(
                    page['webSocketDebuggerUrl'],credentials[0],credentials[1],
                    report=report):
                report('Saved login could not be submitted to the verified Habbo '
                       'form. Check the preceding login diagnostic; no session '
                       'or browser token was saved.')
                return 'login'
            login_submitted=True
            report('Submitted saved login for this account. '
                   'Checking whether Habbo accepted it...')
            time.sleep(1.6)
            continue
        if login_only and kind in ('play','play-now','launch','download',
                                  'signed_in'):
            report('Habbo session is signed in. Use Auto Play to launch Classic.')
            return 'signed_in'
        if kind=='signed_in':
            # Login is authenticated, but clicking an invented Play coordinate
            # would risk sending clicks to the wrong website control.
            last_issue='Signed in, but the PLAY control is not identifiable.'
            time.sleep(0.6)
            continue
        if kind=='not_habbo':
            # Page targets can change origin during navigation even if the
            # DevTools target list still carries the old Habbo URL. Allow
            # short transitions to settle, but NEVER enter credentials.
            unrecognised_pages+=1
            last_issue='Browser page left the verified Habbo HTTPS origin.'
            if unrecognised_pages<5:
                time.sleep(0.7)
                continue
            report(last_issue+' Password entry was stopped for safety. '
                   'Use Accounts > Open account login to finish sign-in.')
            return 'unknown'
        if kind=='launch':
            account_click_play_button(page['webSocketDebuggerUrl'],step)
            report('Clicked Launch and log in. Approve any browser/Windows '
                   'launcher permission prompt; then select Classic if asked.')
            return 'launched'
        if kind in ('play','play-now','download'):
            identity=(page.get('url'),kind,step.get('page'))
            if identity==previous:
                identical+=1
                if identical>=2:
                    report('Habbo stayed on the same Play button. '
                           'Click it manually if the browser blocked automation.')
                    return 'stalled'
            else:
                identical=0
            previous=identity
            account_click_play_button(page['webSocketDebuggerUrl'],step)
            report('Continuing through Habbo '+step.get('label','Play')+'...')
            time.sleep(1.4)
        else:
            time.sleep(0.6)
    if login_only:
        report('Habbo sign-in could not be verified: '+last_issue)
        return 'waiting'
    report('Habbo launch incomplete: '+last_issue)
    return 'timeout'



# Playwright is the sole active browser navigation path. The legacy manual
# CDP interaction code above is kept temporarily for rollback/testing, but all
# account sign-in/Play/Launch callers use the new binding below.
_ACCOUNT_PLAYWRIGHT_VERSION='1.65.2'
_ACCOUNT_PLAYWRIGHT_INSTALL_LOCK=threading.Lock()


def account_playwright_engine(report):
    """Load or install a pinned Playwright Python runtime without browser downloads.

    The existing isolated Brave/Chrome/Edge process remains the browser; we
    attach Playwright to its loopback CDP port, preserving per-account profiles.
    Package dependencies are installed to LOCALAPPDATA, not to system Python.
    Never log pip output or any environment values.
    """
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        pass

    root=(Path(os.environ.get('LOCALAPPDATA',str(APP_DIR)))/
          'HabboCompanion'/'managed-playwright'/
          ('py'+str(sys.version_info.major)+str(sys.version_info.minor)))
    with _ACCOUNT_PLAYWRIGHT_INSTALL_LOCK:
        if (root/'playwright'/'sync_api').is_dir():
            if str(root) not in sys.path:
                sys.path.insert(0,str(root))
            importlib.invalidate_caches()
            try:
                from playwright.sync_api import sync_playwright
                return sync_playwright
            except ImportError:
                # An incomplete prior install is never trusted for account
                # credential entry. It must be repaired before continuing.
                pass

        report('Installing the Playwright browser controller for this '
               'Windows user (first run only; no browser download).')
        root.parent.mkdir(parents=True,exist_ok=True)
        staged=root.parent/('staging-'+uuid.uuid4().hex[:12])
        staged.mkdir(parents=True,exist_ok=False)
        try:
            flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
            args=[sys.executable,'-m','pip','install','--no-input',
                  '--disable-pip-version-check','--only-binary=:all:',
                  '--no-warn-script-location','--index-url',
                  'https://pypi.org/simple','--target',str(staged),
                  'playwright=='+_ACCOUNT_PLAYWRIGHT_VERSION]
            try:
                install=subprocess.run(args,stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,timeout=240,check=False,
                    creationflags=flags)
            except (OSError,subprocess.TimeoutExpired):
                raise RuntimeError(
                    'Playwright automatic installation could not run. '
                    'Check internet access and whether this Python has pip.') from None
            if install.returncode!=0 or not (
                    staged/'playwright'/'sync_api').is_dir():
                raise RuntimeError(
                    'Playwright automatic installation failed. Check internet '
                    'access and Python pip; no browser login was attempted.')
            if root.exists():
                shutil.rmtree(root)
            staged.rename(root)
            if str(root) not in sys.path:
                sys.path.insert(0,str(root))
            importlib.invalidate_caches()
            from playwright.sync_api import sync_playwright
            report('Playwright browser controller is installed.')
            return sync_playwright
        finally:
            if staged.exists():
                shutil.rmtree(staged,ignore_errors=True)


def account_playwright_is_official(url):
    """Restrict account automation to Habbo's verified HTTPS origin."""
    try:
        u=urllib.parse.urlsplit(url)
        host=(u.hostname or '').lower()
        return (u.scheme=='https' and u.port in (None,443) and
                (host=='habbo.com' or host.endswith('.habbo.com')))
    except (TypeError,ValueError):
        return False


def account_playwright_visible(locator):
    """Playwright locator query, not a page coordinate or JS hit-test."""
    try:
        return locator.filter(visible=True).count()>0
    except (OSError,RuntimeError):
        return False


def account_playwright_control(page,kind):
    """Find one visibly labelled Habbo control using Playwright locators."""
    patterns={
        'open-login':r'^(?:log\s*in|login|sign\s*in)\s*!?$',
        'submit':r"^(?:let['’]?s\s+go|log\s*in|login|sign\s*in|continue)\s*!?$",
        'play':r'^play(?:\s+now)?(?:\s+h)?\s*!?$',
        'launch':r'^launch\s*(?:and|&)\s*log\s*in\s*!?$',
    }
    pattern=re.compile(patterns[kind],re.I)
    # Prefer semantic buttons and links before custom-styled text controls.
    for role in ('button','link'):
        target=page.get_by_role(role,name=pattern).filter(visible=True)
        if account_playwright_visible(target):
            return target.first
    target=page.locator('button,a,[role="button"],input[type="submit"]').filter(
        has_text=pattern,visible=True)
    if account_playwright_visible(target):
        return target.first
    # Some Habbo PLAY buttons render as styled spans. Playwright still
    # dispatches trusted click input to the text/containing control.
    if kind in ('play','launch'):
        target=page.get_by_text(pattern,exact=True).filter(visible=True)
        if account_playwright_visible(target):
            return target.first
    return None


def account_playwright_select_page(browser):
    """Select a Habbo tab from the already isolated browser context."""
    candidates=[]
    for context in browser.contexts:
        for page in context.pages:
            if not account_playwright_is_official(page.url):
                continue
            try:
                if account_playwright_visible(
                        page.locator('input[type="password"]:visible')):
                    priority=3
                elif account_playwright_control(page,'launch') is not None:
                    priority=6
                elif account_playwright_control(page,'play') is not None:
                    priority=5
                elif account_playwright_control(page,'open-login') is not None:
                    priority=2
                else:
                    priority=1
                candidates.append((priority,page))
            except (OSError,RuntimeError):
                continue
    if not candidates:
        return None
    return max(candidates,key=lambda pair:pair[0])[1]


def account_playwright_login_form(page):
    """Associate email and submit controls with the visible password field."""
    passwords=page.locator('input[type="password"]:visible')
    if not account_playwright_visible(passwords):
        return None
    password=passwords.first
    form=password.locator('xpath=ancestor::form[1]')
    if form.count()>0:
        root=form.first
    else:
        dialog=password.locator(
            'xpath=ancestor::*[@role="dialog" or self::dialog][1]')
        root=dialog.first if dialog.count()>0 else page
    choices=(
        'input[type="email"]:visible',
        'input[autocomplete="username"]:visible',
        'input[placeholder*="email" i]:visible',
        'input[aria-label*="email" i]:visible',
        'input[type="text"]:visible'
    )
    email=None
    for selector in choices:
        loc=root.locator(selector).filter(visible=True)
        if account_playwright_visible(loc):
            email=loc.first
            break
    if email is None:
        return None
    button=account_playwright_control(root,'submit')
    if button is None:
        # HTML submit input's accessible name may not match; still restrict
        # the fallback to the visible form containing the password.
        loc=root.locator(
            'button[type="submit"],input[type="submit"]').filter(visible=True)
        if account_playwright_visible(loc):
            button=loc.first
    return (email,password,button) if button is not None else None


def account_playwright_safe_error(exc):
    """No raw Playwright error text: it can include page HTML/typed values."""
    detail=str(exc).lower()
    if 'intercepts pointer events' in detail:
        return 'another page element intercepts the login click'
    if 'not visible' in detail:
        return 'target is not visible'
    if 'not enabled' in detail or 'disabled' in detail:
        return 'target is disabled'
    if 'strict mode violation' in detail:
        return 'multiple matching elements'
    if 'timeout' in detail:
        return 'element did not become actionable before timeout'
    if 'connection closed' in detail or 'browser has been closed' in detail:
        return 'account browser disconnected'
    return 'browser action failed ('+type(exc).__name__+')'


def account_playwright_safe_result_flag(body):
    """Read only allowlisted JSON login result flags, never user-supplied text."""
    if not isinstance(body,str) or len(body)>8192:
        return None
    try:
        obj=json.loads(body)
    except (TypeError,ValueError):
        return None
    if not isinstance(obj,dict):
        return None
    candidates=[obj]
    if isinstance(obj.get('data'),dict):
        candidates.append(obj['data'])
    for payload in candidates:
        for name in ('success','authenticated','loggedIn','logged_in'):
            value=payload.get(name)
            if type(value) is bool:
                return name+'='+('true' if value else 'false')
        for name in ('status','result','state'):
            value=payload.get(name)
            if isinstance(value,str) and value.lower() in (
                    'success','failed','failure','error','unauthorized',
                    'forbidden','pending','verification_required',
                    'captcha_required','invalid_credentials'):
                return name+'='+value.lower()
    return None


def account_playwright_safe_service(url):
    """Only show known service labels; never log arbitrary external hostnames."""
    try:
        parts=urllib.parse.urlsplit(url)
        host=(parts.hostname or '').lower()
        if parts.scheme!='https' or parts.port not in (None,443):
            return None
    except (TypeError,ValueError):
        return None
    if host=='habbo.com' or host.endswith('.habbo.com'):
        return 'Habbo'
    labels={
        'accounts.google.com':'Google identity',
        'www.google.com':'Google',
        'appleid.apple.com':'Apple identity',
        'login.microsoftonline.com':'Microsoft identity',
        'www.facebook.com':'Facebook identity',
        'web.facebook.com':'Facebook identity',
        'challenges.cloudflare.com':'Cloudflare challenge',
        'www.hcaptcha.com':'hCaptcha challenge',
        'hcaptcha.com':'hCaptcha challenge',
        'www.recaptcha.net':'reCAPTCHA challenge',
    }
    return labels.get(host,'external HTTPS')


class AccountPlaywrightMonitor:
    """Account-scoped Playwright HTTPS diagnostics, with strict secret redaction.

    Covers login requests and redirects, response status, completion, failures,
    JSON outcomes and browser errors. Never log request/response payloads,
    cookies, token-bearing URLs, headers, usernames or raw console messages.
    """
    def __init__(self,page,report):
        self.page=page
        self.context=page.context
        self.report=report
        self.requests={}
        self.response_candidates=[]
        self.outgoing=0
        self.received=0
        self.failures=0
        self.failed_after_response=0
        self.finished=0
        self.redirects=0
        self.first_party_posts=0
        self.errors=0
        self.max_lines=120
        self.max_important_lines=65
        self.lines=0
        self.important_lines=0
        self.suppressed=0

    def _log(self,description,important=False):
        if important:
            if self.important_lines>=self.max_important_lines:
                self.suppressed+=1
                return
            self.important_lines+=1
        else:
            if self.lines>=self.max_lines:
                self.suppressed+=1
                return
            self.lines+=1
        self.report(description)

    def on_request(self,req):
        try:
            url=req.url
            # Check verified first-party origin before consulting the
            # optional service-label helper (also works in isolated tests).
            service=('Habbo' if account_playwright_is_official(url) else
                     account_playwright_safe_service(url))
            if service is None:
                return
            method=req.method
            kind=req.resource_type
            if kind not in ('xhr','fetch','document') and method not in (
                    'POST','PUT','PATCH','DELETE'):
                return
            self.outgoing+=1
            if len(self.requests)>=240:
                self.suppressed+=1
                return
            num=self.outgoing
            path=account_login_safe_endpoint_path(url)
            auth_path=bool(re.search(
                r'auth|login|sign.in|session|sso|identity|verify|captcha|oauth',
                path,re.I))
            significant=auth_path or method in ('POST','PUT','PATCH')
            if service=='Habbo' and method in ('POST','PUT','PATCH'):
                self.first_party_posts+=1
            rec={'number':num,'path':path,'service':service,
                 'method':method,'kind':kind,'significant':significant,
                 'status':None,'completed':False,'failed':False}
            self.requests[req]=rec
            self._log('CLIENT -> #'+str(num)+' '+method+' '+path+
                      ' ('+service+', '+kind+
                      (', login-related' if significant else '')+').',
                      important=significant)
        except Exception:
            self.errors+=1

    def on_response(self,res):
        try:
            rec=self.requests.get(res.request)
            if rec is None:
                return
            code=res.status
            if type(code) is not int or not 100<=code<=599:
                return
            if rec['status'] is not None:
                return
            rec['status']=code
            self.received+=1
            redirect=300<=code<=399
            if redirect:
                self.redirects+=1
            detail=' redirect' if redirect else ''
            headers=res.headers
            retry=''
            if code==429:
                seconds=str(headers.get('retry-after','')).strip()
                if seconds.isdigit() and int(seconds)<=3600:
                    retry='; retry-after '+seconds+'s'
            self._log('SERVER <- #'+str(rec['number'])+
                      ' HTTP '+str(code)+detail+' '+rec['path']+
                      ' ('+rec['service']+')'+retry+'.',
                      important=rec['significant'] or code>=400 or redirect)
            # Only first-party JSON response bodies are ever read, and only
            # to extract generic error codes / allowlisted outcome metadata.
            content_type=str(headers.get('content-type','')).lower()
            declared=str(headers.get('content-length','')).strip()
            fits=(not declared or (declared.isdigit() and
                                   int(declared)<=8192))
            if (rec['service']=='Habbo' and 'json' in content_type and fits
                    and (rec['significant'] or code>=400)
                    and len(self.response_candidates)<20):
                self.response_candidates.append((rec,res))
        except Exception:
            self.errors+=1

    def on_finished(self,req):
        try:
            rec=self.requests.get(req)
            if rec is None or rec['completed']:
                return
            rec['completed']=True
            self.finished+=1
            if rec['significant']:
                self._log('NETWORK <- #'+str(rec['number'])+
                          ' request completed'+(
                              ' after HTTP '+str(rec['status'])
                              if rec['status'] is not None else
                              ' (no HTTP status recorded)')+'.')
        except Exception:
            self.errors+=1

    def on_failed(self,req):
        try:
            rec=self.requests.get(req)
            if rec is None or rec['failed']:
                return
            rec['failed']=True
            self.failures+=1
            failure=req.failure
            reason=''
            if isinstance(failure,str):
                match=re.search(r'net::ERR_[A-Z_]{3,50}',failure)
                if match:
                    reason=' ('+match.group(0)+')'
            if rec['status'] is None:
                text=' request failed before an HTTP response'
            else:
                self.failed_after_response+=1
                text=' transfer interrupted after HTTP '+str(rec['status'])
            self._log('NETWORK <- #'+str(rec['number'])+text+reason+'.',
                      important=True)
        except Exception:
            self.errors+=1

    def on_pageerror(self,exc):
        self._log('BROWSER <- '+
                  account_login_safe_browser_error(str(exc))+
                  ' (JavaScript exception, contents withheld).',
                  important=True)

    def on_console(self,msg):
        if msg.type=='error':
            self._log('BROWSER <- '+
                      account_login_safe_browser_error(msg.text)+
                      ' (console error, contents withheld).',important=True)

    def start(self):
        # Context-wide events include workers and preserve per-account
        # separation; the selected page alone supplies DOM/console events.
        self.context.on('request',self.on_request)
        self.context.on('response',self.on_response)
        self.context.on('requestfinished',self.on_finished)
        self.context.on('requestfailed',self.on_failed)
        self.page.on('pageerror',self.on_pageerror)
        self.page.on('console',self.on_console)

    def finish(self):
        # Response.text() is read after the browser has completed submission,
        # not within network callbacks (which could re-enter Playwright).
        # A HTTP 200 may still contain an application-level login rejection.
        for rec,resp in self.response_candidates:
            try:
                body=resp.text()
                if not isinstance(body,str) or len(body)>8192:
                    continue
                code=account_login_safe_error_code(body)
                if code and re.fullmatch(r'[A-Z][A-Z0-9_]{2,48}',code):
                    self._log('SERVER <- #'+str(rec['number'])+
                              ' safe error code: '+code+'.',important=True)
                message=account_login_safe_server_message(body)
                if message:
                    self._log('SERVER <- #'+str(rec['number'])+
                              ' safe error message: '+message+'.',
                              important=True)
                flag=account_playwright_safe_result_flag(body)
                if flag:
                    self._log('SERVER <- #'+str(rec['number'])+
                              ' application result '+flag+
                              ' (HTTP '+str(rec['status'])+').',
                              important=True)
            except Exception:
                self.errors+=1
        self.report('Login network: '+str(self.outgoing)+' request(s), '+
                    str(self.received)+' HTTP response(s), '+
                    str(self.finished)+' completed, '+
                    str(self.failures)+' transport failure(s) ('+
                    str(self.failed_after_response)+' after an HTTP response, '+
                    str(self.failures-self.failed_after_response)+
                    ' before a response); '+str(self.redirects)+
                    ' redirect(s); '+str(self.first_party_posts)+
                    ' Habbo POST/PUT/PATCH request(s).')
        if self.suppressed:
            self.report('NETWORK <- '+str(self.suppressed)+
                        ' low-priority or excess diagnostics omitted; '
                        'authentication and errors were prioritised.')
        if self.errors:
            self.report('NETWORK <- '+str(self.errors)+
                        ' diagnostic event(s) could not be inspected; '
                        'authentication remains unverified.')
        try:
            cookies=self.context.cookies([
                'https://www.habbo.com/','https://habbo.com/'])
            present=set()
            for item in cookies:
                if item.get('name') in ('session.id','browser_token') and (
                        str(item.get('domain','')).lstrip('.').lower() in (
                            'habbo.com','www.habbo.com')) and (
                        item.get('secure') is True):
                    present.add(item['name'])
            self.report('SESSION <- Secure Habbo cookies present: '
                        'session.id='+('yes' if 'session.id' in present else 'no')+
                        ', browser_token='+(
                            'yes' if 'browser_token' in present else 'no')+
                        '. Cookie values never logged.')
        except Exception:
            self.report('SESSION <- Cookie-presence inspection unavailable.')

    def stop(self):
        for emitter,event,callback in (
            (self.context,'request',self.on_request),
            (self.context,'response',self.on_response),
            (self.context,'requestfinished',self.on_finished),
            (self.context,'requestfailed',self.on_failed),
            (self.page,'pageerror',self.on_pageerror),
            (self.page,'console',self.on_console)):
            try:
                emitter.remove_listener(event,callback)
            except Exception:
                pass


def account_playwright_session_hint(context):
    """Cookie *presence* only; official SSO validation remains authoritative."""
    try:
        cookies=context.cookies([
            'https://www.habbo.com/','https://habbo.com/'])
    except (OSError,RuntimeError,ValueError):
        return False
    names=set()
    for cookie in cookies:
        host=str(cookie.get('domain','')).lstrip('.').lower()
        if (host=='habbo.com' or host=='www.habbo.com') and (
                cookie.get('secure') is True):
            if cookie.get('name') in ('session.id','browser_token'):
                names.add(cookie['name'])
    return len(names)==2


def account_playwright_auto_play(debug_port,report,credentials=None,
                                 login_only=False):
    """Playwright-only Habbo website interactions for one isolated profile.

    All logins, Play and Launch controls use Playwright locators. We attach
    to Companion's *existing* loopback-only Chromium browser (Chrome, Brave,
    Edge), never open a generic user profile or pass credentials to an URL.
    No force clicks or CAPTCHA/MFA bypass; SSO is validated downstream.
    """
    try:
        load=account_playwright_engine(report)
    except (OSError,ValueError,RuntimeError,ImportError):
        report('Playwright browser controller unavailable. Automatic login '
               'stopped rather than falling back to coordinate automation.')
        return 'control_error'

    try:
        with load() as playwright:
            browser=playwright.chromium.connect_over_cdp(
                'http://127.0.0.1:'+str(int(debug_port)),timeout=12000)
            page=account_playwright_select_page(browser)
            if page is None:
                report('Playwright could not find an official HTTPS Habbo tab '
                       'inside this account browser.')
                return 'no_habbo_tab'
            monitor=AccountPlaywrightMonitor(page,report)
            monitor.start()
            try:
                # Never operate on a destination outside verified Habbo HTTPS.
                if not account_playwright_is_official(page.url):
                    return 'unknown'
                form=account_playwright_login_form(page)
                if form is None:
                    prompt=account_playwright_control(page,'open-login')
                    if prompt is not None and credentials is not None:
                        try:
                            prompt.click(timeout=7000)
                            report('Playwright opened the Habbo login form.')
                            page.locator(
                                'input[type="password"]:visible').first.wait_for(
                                state='visible',timeout=9000)
                            form=account_playwright_login_form(page)
                        except Exception as exc:
                            report('Playwright could not open the login form: '+
                                   account_playwright_safe_error(exc)+'.')
                            return 'waiting'
                if form is not None:
                    if credentials is None:
                        report('Save an email/password in Accounts or sign in '
                               'manually to this separate browser profile.')
                        return 'login'
                    if not account_playwright_is_official(page.url):
                        return 'unknown'
                    email,password,submit=form
                    try:
                        email.fill(credentials[0],timeout=8000)
                        password.fill(credentials[1],timeout=8000)
                        report('Playwright filled the selected Habbo login '
                               'form using element-based input events.')
                        # Inspect only boolean validity, not password values.
                        valid_email=email.evaluate(
                            '(el) => !el.validity || el.validity.valid')
                        valid_password=password.evaluate(
                            '(el) => !el.validity || el.validity.valid')
                        if not valid_email or not valid_password:
                            report('Habbo login fields failed built-in form '
                                   'validation; nothing was submitted.')
                            return 'login'
                        report('Playwright clicking LETS GO with actionability '
                               'checks (visible, stable, enabled, unblocked).')
                        submit.click(timeout=10000)
                    except Exception as exc:
                        report('Playwright login: '+
                               account_playwright_safe_error(exc)+
                               '. No forced click or automatic retry.')
                        return 'login'
                    report('Login button clicked; checking Habbo sign-in '
                           'outcome without re-submitting credentials.')
                    try:
                        page.locator(
                            'input[type="password"]:visible').first.wait_for(
                            state='hidden',timeout=13000)
                    except Exception:
                        # A persistent form can mean rejection, validation,
                        # security challenge or a failed browser handler.
                        report('Habbo still shows the password field after '
                               'Playwright clicked login.')
                        # Classify any visible security/validation message,
                        # without returning raw page text or account values.
                        try:
                            finding=page.evaluate(HABBO_LOGIN_DIAGNOSTIC_JS)
                            kind=finding.get('kind') if isinstance(
                                finding,dict) else None
                            findings={
                                'invalid-credentials':
                                    'login form reports invalid credentials',
                                'rate-limit':
                                    'login page reports a rate limit',
                                'captcha':
                                    'visible human-verification challenge',
                                'verification':
                                    'verification or one-time code required',
                                'still-on-form':
                                    'login form still visible; no recognised '
                                    'validation message',
                                'unverified-page':
                                    'page origin could not be verified',
                            }
                            if kind in findings:
                                report('BROWSER <- '+findings[kind]+'.')
                        except Exception:
                            report('BROWSER <- Could not classify login-page '
                                   'validation state.')
                if login_only:
                    if account_playwright_control(page,'play') is not None or (
                            account_playwright_control(page,'launch') is not None):
                        report('Playwright found the signed-in Habbo PLAY UI.')
                        return 'signed_in'
                    if account_playwright_session_hint(page.context):
                        report('Website session cookies detected; the official '
                               'SSO check will verify authentication.')
                        return 'signed_in'
                    if account_playwright_visible(
                            page.locator('input[type="password"]:visible')):
                        report('No verified sign-in; login form remains. '
                               'Complete any visible verification manually.')
                        return 'login'
                    report('Habbo login result not yet confirmed by Playwright; '
                           'the official SSO check will decide.')
                    return 'waiting'

                # Auto Play: click recognised website Play / Launch elements.
                # Native launcher approval remains a separate Windows action.
                last_play=False
                for _ in range(4):
                    if not account_playwright_is_official(page.url):
                        return 'unknown'
                    launch=account_playwright_control(page,'launch')
                    if launch is not None:
                        try:
                            launch.click(timeout=9000)
                        except Exception as exc:
                            report('Playwright launch: '+
                                   account_playwright_safe_error(exc)+'.')
                            return 'stalled'
                        report('Clicked Launch and log in via Playwright. '
                               'Select Classic/approve Windows prompt if shown.')
                        return 'launched'
                    play=account_playwright_control(page,'play')
                    if play is not None:
                        if last_play:
                            report('Habbo PLAY remained unchanged after click; '
                                   'not sending repeated clicks.')
                            return 'stalled'
                        try:
                            play.click(timeout=9000)
                        except Exception as exc:
                            report('Playwright PLAY: '+
                                   account_playwright_safe_error(exc)+'.')
                            return 'stalled'
                        report('Playwright clicked the Habbo PLAY control.')
                        last_play=True
                    page.wait_for_timeout(850)
                return 'waiting'
            finally:
                try:
                    monitor.finish()
                finally:
                    monitor.stop()
    except Exception as exc:
        report('Playwright could not operate the isolated browser: '+
               account_playwright_safe_error(exc)+'.')
        return 'control_error'


# Route all existing account-login and Auto Play buttons through Playwright.
# The older function above is no longer the runtime browser controller.
account_attempt_auto_play=account_playwright_auto_play


# This request uses ONLY the existing isolated browser profile's authenticated
# HTTPS Habbo.com page. No cookies are exported to Companion; no passwords are
# read. It cannot create a signed-in session from an email/password alone.
HABBO_SESSION_TICKET_JS=r'''(async () => {
  if (location.protocol !== 'https:' ||
      !['habbo.com','www.habbo.com'].includes(location.hostname)) {
    return {kind:'error',reason:'not_official_habbo'};
  }
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8500);
    let response;
    try {
      response = await fetch('/api/client/clientnative/url', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Accept':'application/json'},
        signal: controller.signal,
        redirect: 'error'
      });
    } finally {
      clearTimeout(timeout);
    }
    if (!response.ok) return {
      kind:'error',reason:'http_error',status:response.status
    };
    const data = await response.json();
    if (!data || typeof data !== 'object') return {
      kind:'error',reason:'unexpected_response'
    };
    // Never collect site cookies, browser storage or other session secrets.
    const candidate = [data.ticket,data.url,data.launchUrl,
                       data.launch_url,data.loginUrl].find(
      value => typeof value === 'string' && value.length > 8 && value.length < 400
    );
    if (!candidate) return {kind:'error',reason:'no_ticket_in_response'};
    return {kind:'ticket',value:candidate};
  } catch (_) {
    // Do not leak URLs, response bodies or credentials into diagnostic logs.
    return {kind:'error',reason:'request_unavailable'};
  }
})()'''


def account_parse_official_ticket_response(value):
    """Accept only the narrow known Habbo.com ticket shapes."""
    if not isinstance(value,str) or not 8<len(value)<400:
        raise ValueError('Habbo returned no usable SSO ticket.')
    candidate=value.strip()
    if re.fullmatch(r'[A-Za-z0-9-]{8,160}\.V[1-9][0-9]?(?:\.[A-Za-z0-9_.:-]{1,40})?',
                    candidate,re.I):
        candidate='hhus.'+candidate
    try:
        return parse_classic_ticket(candidate)
    except (TypeError,ValueError) as exc:
        raise ValueError(
            'Habbo returned a ticket format this version does not recognise; '
            'nothing was queued.') from exc


def account_fetch_ticket_from_signed_in_profile(debug_port):
    """Request a ticket without opening or automating any website UI.

    Requires a previously authenticated Companion Chromium profile running
    with its local debugging port. Browser/session identity is NOT inferred
    from profile labels. The official API is undocumented and may refuse use.
    """
    page=account_habbo_page(debug_port)
    if page is None:
        raise ValueError(
            'No official Habbo tab found in this account browser session.')
    if page.get('_inspect_error'):
        raise ValueError(
            'Local account browser control unavailable; reconnect its existing '
            'signed-in profile before requesting a ticket.')
    status=page.get('_preflight_step',{}).get('kind')
    if status not in ('play','play-now','launch','signed_in','download'):
        raise ValueError(
            'Habbo website session is not verified as signed in. '
            'This method cannot log in using a password.')
    response=account_cdp_call(
        page['webSocketDebuggerUrl'],'Runtime.evaluate',{
            'expression':HABBO_SESSION_TICKET_JS,
            'returnByValue':True,
            'awaitPromise':True
        },timeout=13)
    if response.get('exceptionDetails'):
        raise ValueError('The official Habbo ticket request could not run.')
    obj=response.get('result',{}).get('value')
    if not isinstance(obj,dict):
        raise ValueError('The official Habbo ticket response was unreadable.')
    if obj.get('kind')!='ticket':
        reason=obj.get('reason','unknown')
        if reason=='http_error':
            try:
                code=int(obj.get('status',0))
            except (ValueError,TypeError):
                code=0
            if code in (401,403):
                raise ValueError(
                    'Habbo rejected the existing session (HTTP '+str(code)+'). '
                    'Sign in normally if your session expired.')
            raise ValueError(
                'Habbo ticket request returned HTTP '+str(code)+'.')
        reasons={
            'not_official_habbo':'Selected tab was not Habbo.com.',
            'no_ticket_in_response':'Habbo response contained no recognised ticket field.',
            'unexpected_response':'Habbo returned an unexpected ticket response.',
            'request_unavailable':'Habbo ticket request was blocked or unavailable.'
        }
        raise ValueError(reasons.get(reason,'Habbo did not return a ticket.'))
    return account_parse_official_ticket_response(obj.get('value'))


def account_capture_habbo_session_cookies(debug_port,check_visible_login=True):
    """Get two first-party cookies from one isolated Companion browser tab.

    By default require visible signed-in controls. For recovery from sessions
    where the site UI is unrecognisable, the caller may skip that check *only*
    if it immediately validates the cookies against the official SSO API
    before retaining or using them. This does NOT access the normal browser
    profile or return unrelated website cookies.
    """
    if check_visible_login:
        page=account_habbo_page(debug_port)
        if page is None or page.get('_inspect_error'):
            raise ValueError('Companion account browser is not available or inspectable.')
        state=page.get('_preflight_step',{}).get('kind')
        if state not in ('play','play-now','launch','signed_in','download'):
            raise ValueError('This Habbo browser profile is not signed in.')
    else:
        # A logged-in Habbo browser can be at habbo.com *or* www.habbo.com.
        # Earlier versions rejected the bare-domain page, so cookie-first
        # import failed even after a legitimate website sign-in.
        page=None
        for candidate in account_browser_pages(debug_port):
            try:
                url=urllib.parse.urlsplit(candidate['url'])
                approved=(url.scheme=='https' and
                          url.hostname in ('habbo.com','www.habbo.com') and
                          url.port in (None,443))
            except (ValueError,KeyError,TypeError):
                approved=False
            if approved:
                page=candidate
                break
        if page is None:
            raise ValueError('No official Habbo tab in this isolated browser.')
    target=urllib.parse.urlsplit(page['url'])
    if (target.scheme!='https' or
        target.hostname not in ('habbo.com','www.habbo.com') or
        target.port not in (None,443)):
        raise ValueError('The selected tab is not a verified official Habbo origin.')
    ws=page['webSocketDebuggerUrl']
    parsed=urllib.parse.urlsplit(ws)
    if (parsed.scheme!='ws' or parsed.hostname!='127.0.0.1'
        or parsed.port!=int(debug_port)
        or not parsed.path.startswith('/devtools/page/')):
        raise ValueError('Account browser is not on its isolated local control port.')
    # Scope HttpOnly cookie extraction to the exact verified official origin
    # of the account's browser tab. No unrelated websites or other profiles.
    result=account_cdp_call(ws,'Network.getCookies',{
        'urls':['https://'+target.hostname+'/']
    })
    cookies=result.get('cookies')
    if not isinstance(cookies,list) or len(cookies)>250:
        raise ValueError('Habbo cookie response is unavailable or invalid.')
    found={}
    for cookie in cookies:
        if not isinstance(cookie,dict):
            continue
        name=cookie.get('name')
        if name not in ('session.id','browser_token'):
            continue
        domain=cookie.get('domain')
        if not isinstance(domain,str) or domain.lower() not in (
                'www.habbo.com','habbo.com','.habbo.com'):
            continue
        if cookie.get('secure') is not True:
            continue
        val=cookie.get('value')
        if (not isinstance(val,str) or not 1<=len(val)<=900
            or any(ord(ch)<33 or ord(ch)>126 or ch in ';,\r\n'
                   for ch in val)):
            raise ValueError('One of the required Habbo cookies is invalid.')
        if name in found and found[name]!=val:
            raise ValueError('Ambiguous duplicate Habbo session cookie.')
        found[name]=val
    if len(found)!=2:
        raise ValueError('Habbo session.id/browser_token not found in this '
                         'signed-in account browser.')
    return found['session.id'],found['browser_token']



def account_wait_for_background_session(debug_port,report,max_checks=24):
    """Wait for a cold-start isolated browser to restore Habbo website state.

    A responsive CDP port is NOT evidence the site has finished navigating.
    Poll only the official Habbo page's safe UI state, across all Habbo tabs;
    do not click, enter credentials, request repeated tickets or bypass
    verification. A session ticket is still required after the UI is ready.
    """
    if type(max_checks) is not int or not 1<=max_checks<=30:
        raise ValueError('Invalid browser readiness check count.')
    signed_in={'play','play-now','launch','signed_in','download'}
    last='loading'
    for check in range(max_checks):
        if check:
            time.sleep(0.6)
        try:
            page=account_habbo_page(debug_port)
        except (OSError,ValueError,RuntimeError,TimeoutError,socket.timeout,
                urllib.error.URLError):
            last='control_unavailable'
            continue
        if not page or page.get('_inspect_error'):
            last='loading'
            continue
        state=(page.get('_preflight_step') or {}).get('kind')
        if state in signed_in:
            report('BROWSER <- Background Habbo profile restored signed-in '
                   'PLAY/account UI; checking official SSO next.')
            return True
        if state in ('login','open-login'):
            last='login'
        else:
            last='loading'
    if last=='login':
        report('BROWSER <- Background profile shows a login form after '
               'readiness checks; saved login or manual verification may '
               'be required.')
    else:
        report('BROWSER <- Background profile did not confirm signed-in '
               'PLAY/account UI during readiness checks; checking official '
               'session evidence without assuming a login failure.')
    return False

def account_import_session_automatically(account,report):
    """On demand: headless isolated browser login -> two cookies -> fresh SSO.

    Uses an existing local account browser if one is running. Otherwise,
    starts this account's private Chromium profile in HEADLESS mode and
    attempts the existing saved-login flow once. Website MFA/CAPTCHA are
    never bypassed. The official ticket is validated before cookies are
    persisted in the per-account Windows Credential Manager vault.
    """
    ident=account['id']
    _account_credential_target(ident)
    port=account_browser_debug_port(ident)
    browser=account_login_browser()
    if browser is None:
        raise ValueError('Brave, Chrome or Edge is required to renew a website session.')
    # Never attach the wrong account: dedicated browser profile & CDP port.
    folder=APP_DIR/'account_browser_profiles'/ident
    browser_url=validate_habbo_login_url(account['url'])
    try:
        credentials=account_saved_login_read(ident)
    except (OSError,ValueError):
        raise ValueError('Could not read the saved login for this account.') from None
    spawned=None
    try:
        try:
            account_browser_pages(port)
            report('Reusing the existing isolated account browser session.')
        except (OSError,ValueError,TimeoutError,UnicodeError,
                urllib.error.URLError):
            folder.mkdir(parents=True,exist_ok=True)
            command=account_browser_command(browser,folder,browser_url,port)
            # Chromium can use its regular persistent profile while headless.
            # A first-time captcha or 2FA needs the Accounts login window.
            command.insert(-1,'--headless=new')
            command.insert(-1,'--window-size=1280,900')
            report('Opening this account in a private background browser.')
            spawned=subprocess.Popen(
                command,cwd=str(browser.parent),
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for _ in range(24):
                time.sleep(0.4)
                try:
                    account_browser_pages(port)
                    break
                except (OSError,ValueError,TimeoutError,UnicodeError,
                        urllib.error.URLError):
                    continue
            else:
                raise ValueError(
                    'Background browser control unavailable. Open account '
                    'login from Accounts to renew this profile.')
            report('BROWSER <- Local browser control is ready; waiting for '
                   'the saved Habbo profile to finish loading before login '
                   'or ticket requests.')
            account_wait_for_background_session(port,report)
        def verified_ticket_from_browser():
            # Preserve the legacy cookie-pair path for older authenticated
            # profiles, but modern site sessions may omit these cookie names.
            # The first-party browser route is already implemented by
            # "Fetch from signed-in local session". It uses only the isolated
            # Habbo tab and requests a real ticket from the official site.
            try:
                cookies=account_capture_habbo_session_cookies(
                    port,check_visible_login=False)
            except (OSError,ValueError,RuntimeError,TimeoutError,
                    socket.timeout):
                report('SESSION <- Legacy cookie pair unavailable; checking '
                       'the signed-in Habbo browser ticket endpoint.')
            else:
                try:
                    raw=fetch_habbo_sso_ticket(*cookies)
                    ticket=account_parse_official_ticket_response(raw)
                except (OSError,ValueError,RuntimeError,HabboTcpError,
                        TimeoutError,socket.timeout) as exc:
                    if isinstance(exc,HabboTcpError):
                        reason=str(exc)
                        if 'HTTP 401' in reason:
                            category='legacy-cookie SSO returned HTTP 401'
                        elif 'HTTP 403' in reason:
                            category='legacy-cookie SSO returned HTTP 403'
                        elif 'HTTP 429' in reason:
                            category='legacy-cookie SSO returned HTTP 429'
                        else:
                            category='legacy-cookie SSO did not issue a ticket'
                    else:
                        category='legacy-cookie ticket verification failed'
                    report('SESSION <- '+category+'; trying the authenticated '
                           'browser session directly.')
                else:
                    report('SESSION <- Official SSO ticket obtained using the '
                           'verified legacy cookie pair.')
                    return ticket,cookies
            try:
                ticket=account_fetch_ticket_from_signed_in_profile(port)
            except (OSError,ValueError,RuntimeError,TimeoutError,
                    socket.timeout) as exc:
                # No raw exception details: only known, bounded categories
                # from our own first-party ticket-request implementation.
                message=str(exc)
                if 'HTTP 401' in message:
                    category='official browser ticket endpoint returned HTTP 401'
                elif 'HTTP 403' in message:
                    category='official browser ticket endpoint returned HTTP 403'
                elif 'HTTP 429' in message:
                    category='official browser ticket endpoint returned HTTP 429'
                elif 'no recognised ticket field' in message:
                    category='official browser response contained no recognised ticket field'
                elif 'ticket format' in message:
                    category='official browser returned an unrecognised ticket format'
                elif 'not verified as signed in' in message:
                    category='selected Habbo tab was not confirmed signed in'
                elif 'No official Habbo tab' in message:
                    category='no official Habbo browser tab was found'
                elif 'request was blocked or unavailable' in message:
                    category='official browser ticket request was blocked or unavailable'
                else:
                    category='official browser ticket request could not be verified'
                report('SESSION <- '+category+'.')
                raise ValueError('The signed-in Habbo browser did not issue a '
                                 'usable official game ticket.') from None
            report('SESSION <- Official game ticket obtained from the '
                   'signed-in Habbo browser; no legacy cookie pair required.')
            return ticket,None

        def report_session_verification_failure(error):
            # Never print an exception verbatim: browser/session exceptions
            # could contain confidential data in future integrations.
            if isinstance(error,HabboTcpError):
                safe=str(error)
                if 'HTTP 401' in safe:
                    report('SESSION <- Official Habbo SSO returned HTTP 401 '
                           '(website session rejected).')
                elif 'HTTP 403' in safe:
                    report('SESSION <- Official Habbo SSO returned HTTP 403 '
                           '(website session rejected).')
                elif 'HTTP 429' in safe:
                    report('SESSION <- Official Habbo SSO returned HTTP 429 '
                           '(request rate limited).')
                elif 'HTTP 500' in safe or 'HTTP 503' in safe:
                    report('SESSION <- Official Habbo SSO returned a server error.')
                else:
                    report('SESSION <- Official Habbo SSO ticket was not '
                           'available or could not be verified.')
            else:
                report('SESSION <- Browser did not provide a verified pair '
                       'of Habbo session cookies and a valid SSO ticket.')

        report('Checking for an existing Habbo session in this account profile.')
        try:
            ticket,cookies=verified_ticket_from_browser()
        except (OSError,ValueError,RuntimeError,HabboTcpError,
                socket.timeout,TimeoutError):
            report('No usable existing session; checking saved website login.')
        else:
            if cookies is not None:
                account_session_cookie_write(ident,*cookies)
                report('Existing Habbo session verified and saved to Windows vault.')
            else:
                report('Existing signed-in browser session issued a game '
                       'ticket; trusted browser profile remains on disk.')
            return ticket

        if credentials is None:
            raise ValueError(
                'No valid session or saved Habbo login for this account. '
                'Use Accounts > Open account login once to sign in, or '
                'Accounts > Save login securely for automatic sign-in.')
        outcomes=[]
        def login_status(message):
            # Status messages contain no cookies, email addresses or passwords.
            # Previous versions silently swallowed the actual login diagnosis.
            safe=str(message)[:160]
            outcomes.append(safe)
            report(safe)
        login_result=account_attempt_auto_play(
            port,login_status,credentials=credentials,login_only=True)
        if login_result!='signed_in':
            # The real Habbo login uses LET'S GO! followed by a PLAY home
            # screen. An unchanged login DOM is not proof authentication
            # failed (a stale tab or slow SPA update can obscure success).
            # Confirm strictly with the first-party cookie pair + official
            # HTTPS SSO request before giving up. This never reads or uses
            # the separate 'Launch and log in' code shown in the PLAY modal.
            report('Login page did not confirm sign-in; checking the official '
                   'Habbo HTTPS session before failing.')
            try:
                ticket,cookies=verified_ticket_from_browser()
            except (OSError,ValueError,RuntimeError,HabboTcpError,
                    socket.timeout,TimeoutError) as exc:
                report_session_verification_failure(exc)
            else:
                if cookies is not None:
                    account_session_cookie_write(ident,*cookies)
                    report('Official Habbo HTTPS session is valid despite the '
                           'unrecognised page; saved to Windows vault.')
                else:
                    report('Official browser session issued a game ticket '
                           'despite the unrecognised page; profile preserved.')
                return ticket
            reasons={
                'login':'Website login form remains visible; '
                        'Habbo has not confirmed a new session after logout. '
                        'Use Accounts > Open account login to complete any '
                        'required verification, then retry Auto-import.',
                'waiting':'Habbo website did not expose recognised login '
                          'controls in headless mode. Use Accounts > '
                          'Open account login.',
                'no_habbo_tab':'Official Habbo.com tab did not open in this '
                               'account browser profile.',
                'control_error':'Local browser control was unavailable.',
                'inspect_error':'Browser page inspection failed.',
                'unknown':'Habbo browser left the verified Habbo HTTPS page. '
                          'Use Accounts > Open account login to finish sign-in.',
            }
            raise ValueError(reasons.get(
                login_result,
                'Website sign-in could not be confirmed. Use Accounts > '
                'Open account login to complete it.'))
        report('Website sign-in confirmed; verifying session with Habbo HTTPS.')
        try:
            ticket,cookies=verified_ticket_from_browser()
        except (OSError,ValueError,RuntimeError,HabboTcpError,
                socket.timeout,TimeoutError) as exc:
            report_session_verification_failure(exc)
            raise ValueError('Website sign-in appeared successful, but Habbo '
                             'did not validate the session for Direct TCP.') from None
        if cookies is not None:
            account_session_cookie_write(ident,*cookies)
            report('Official Habbo session validated and saved in Windows vault.')
        else:
            report('Official Habbo browser session issued a game ticket; '
                   'persistent account profile retained for next connection.')
        return ticket
    finally:
        # Only close a browser process created by this invocation. Never
        # close a user-opened browser or another account's browser.
        if spawned is not None:
            try:
                page=account_habbo_page(port)
                if page:
                    account_cdp_call(page['webSocketDebuggerUrl'],
                                     'Browser.close',timeout=2)
            except (OSError,ValueError,TimeoutError,RuntimeError):
                try:
                    spawned.terminate()
                except OSError:
                    pass


def account_is_native_habbo_window(title):
    """Strict native AIR title filter; excludes Habbo webpages and Launcher."""
    return bool(re.match(r'^HabboAir(?:Plus)?(?:\b|[\s\[\-])',
                         str(title).strip(),re.I))


def account_native_client_windows():
    """Snapshot visible native HabboAir windows by (HWND, process ID).

    Returns None if Windows enumeration fails, so an uncertain snapshot never
    authorises an additional account launch. This is NOT avatar verification.
    """
    if os.name!='nt':
        return None
    try:
        user32=ctypes.WinDLL('user32',use_last_error=True)
        cbtype=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        user32.EnumWindows.argtypes=[cbtype,wintypes.LPARAM]
        user32.EnumWindows.restype=wintypes.BOOL
        user32.IsWindowVisible.argtypes=[wintypes.HWND]
        user32.IsWindowVisible.restype=wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes=[wintypes.HWND]
        user32.GetWindowTextLengthW.restype=ctypes.c_int
        user32.GetWindowTextW.argtypes=[
            wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        user32.GetWindowTextW.restype=ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes=[
            wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype=wintypes.DWORD
        windows=set()
        @cbtype
        def on_window(hwnd,_):
            if not user32.IsWindowVisible(hwnd):
                return True
            n=user32.GetWindowTextLengthW(hwnd)
            if n<=0 or n>512:
                return True
            buf=ctypes.create_unicode_buffer(n+1)
            if user32.GetWindowTextW(hwnd,buf,n+1)<=0:
                return True
            if not account_is_native_habbo_window(buf.value):
                return True
            pid=wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value:
                windows.add((int(hwnd),int(pid.value)))
            return True
        if not user32.EnumWindows(on_window,0):
            return None
        return frozenset(windows)
    except (OSError,ValueError,TypeError,AttributeError):
        return None


def account_wait_for_new_native_window(baseline,seconds=1.5):
    """Confirm a NEW game window appeared after this account's launch request.

    Existing game windows in the baseline do not count as success. Never
    infer G-Earth proxy attachment or avatar ownership from a window title.
    """
    if baseline is None:
        return False
    end=time.monotonic()+max(0,float(seconds))
    while True:
        current=account_native_client_windows()
        if current is not None and current.difference(baseline):
            return True
        remaining=end-time.monotonic()
        if remaining<=0:
            return False
        time.sleep(min(0.3,remaining))


def account_select_classic_launcher(timeout=16):
    """Click a named Classic button in a Habbo Launcher window if accessible.

    This does not dismiss Windows permission prompts, enter login details,
    or click controls in arbitrary windows. Falls back to manual Classic.
    """
    if os.name!='nt':
        return False
    script=r'''
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root=[System.Windows.Automation.AutomationElement]::RootElement
$max=(Get-Date).AddSeconds(TIMEOUT_SECONDS)
while ((Get-Date) -lt $max) {
    $windows=$root.FindAll(
       [System.Windows.Automation.TreeScope]::Children,
       [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($window in $windows) {
        $title=$window.Current.Name
        if ($title -notmatch '(?i)(habbo.*launcher|launcher.*habbo)') {
            continue
        }
        $controls=$window.FindAll(
          [System.Windows.Automation.TreeScope]::Descendants,
          [System.Windows.Automation.Condition]::TrueCondition)
        foreach ($button in $controls) {
            if ($button.Current.Name -ne 'Classic' -or
                -not $button.Current.IsEnabled) { continue }
            try {
                $invoke=$button.GetCurrentPattern(
                  [System.Windows.Automation.InvokePattern]::Pattern)
                $invoke.Invoke()
                Write-Output 'CLASSIC_CLICKED'
                exit 0
            } catch { }
        }
    }
    Start-Sleep -Milliseconds 450
}
exit 2
'''.replace('TIMEOUT_SECONDS',str(int(max(1,min(30,timeout)))))
    encoded=base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    try:
        result=subprocess.run(
            ['powershell.exe','-NoProfile','-NonInteractive',
             '-EncodedCommand',encoded],
            timeout=timeout+6,capture_output=True,text=True,
            creationflags=flags)
        return result.returncode==0 and 'CLASSIC_CLICKED' in result.stdout
    except (OSError,subprocess.TimeoutExpired,ValueError):
        return False


def parse_coffee_group_names(raw):
    """Opt-in room activity list; never silently add people."""
    if not isinstance(raw,str):
        raise ValueError('Enter comma-separated participant usernames.')
    names=[n.strip() for n in re.split(r'[,\n]+',raw)]
    names=[n for n in names if n]
    if not 2<=len(names)<=8:
        raise ValueError('Group rotation requires 2 to 8 willing participants.')
    if len({n.casefold() for n in names})!=len(names):
        raise ValueError('Remove duplicate group usernames.')
    if any(len(n)>80 or any(c in n for c in '{}\r\x00') for n in names):
        raise ValueError('An invalid username is present in the participant list.')
    return tuple(names)


def parse_extra_furniture_sources(raw,cup_one,cup_two):
    """Validate optional bookcase / other hand-item furniture INSTANCE IDs."""
    if not isinstance(raw,str):
        raise ValueError('Extra hand-item sources must be comma-separated furniture IDs.')
    raw=raw.strip()
    if not raw:
        return ()
    candidates=[v.strip() for v in re.split(r'[,;\n]+',raw) if v.strip()]
    if len(candidates)>4:
        raise ValueError('You can add at most 4 additional furniture sources.')
    used=set()
    for label,val in (('Cup 1',cup_one),('Cup 2',cup_two)):
        text=str(val).strip()
        if not re.fullmatch(r'[0-9]{1,10}',text) or not 1<=int(text)<2147483648:
            raise ValueError(label+' needs a valid room furniture ID.')
        if int(text) in used:
            raise ValueError('Cup furniture IDs must be different.')
        used.add(int(text))
    extras=[]
    for item in candidates:
        if not re.fullmatch(r'[0-9]{1,10}',item) or not 1<=int(item)<2147483648:
            raise ValueError('Additional furniture IDs must be positive 32-bit numbers.')
        value=int(item)
        if value in used:
            raise ValueError('Duplicate furniture ID: '+str(value))
        used.add(value)
        extras.append(str(value))
    return tuple(extras)


def build_extended_coffee_sequence(cup_one,cup_two,extras,recipient,single_cup=False):
    """One pickup immediately followed by one pass, per source."""
    if single_cup:
        return build_coffee_pass_sequence(cup_one,'',recipient,single_cup=True)
    first=build_coffee_pass_sequence(cup_one,cup_two,recipient)
    if not extras:
        return first
    sequence=list(first)
    for furniture in extras:
        sequence.extend(build_coffee_pass_sequence(
            furniture,'',recipient,single_cup=True))
    return tuple(sequence)


def outgoing_furniture_id_from_packet(extension,direction,packet):
    """Recognize the next manual UseFurniture by named outgoing G-Earth header."""
    try:
        records=(getattr(extension,'packet_infos',None) or {}).get(
            direction,{}).get(packet.header_id(),())
        if not any(str(record.get('Name','')).casefold()=='usefurniture'
                   for record in records):
            return None
        instance_id=packet.read_int(6)
        return instance_id if 1<=instance_id<2147483648 else None
    except (ValueError,TypeError,AttributeError,IndexError):
        return None


def coffee_speed_test_report(elapsed,pickups,releases,requests,source_attempts,
                             source_confirmations,delay):
    """Only own-hand confirmations, never claimed recipient deliveries."""
    elapsed=max(0.001,float(elapsed))
    pickups=max(0,int(pickups))
    releases=max(0,int(releases))
    requests=max(0,int(requests))
    source_notes=[]
    for source,attempts in source_attempts.items():
        confirmed=source_confirmations.get(source,0)
        source_notes.append(f'{source}: {confirmed}/{attempts} pickups')
    return (f'Speed test ({float(delay):g}s delay; {elapsed:.1f}s elapsed): '
            f'own pickups confirmed {pickups}/{sum(source_attempts.values())}, '
            f'own hand emptied {releases}/{requests}; '
            f'{requests} pass requests, {60*pickups/elapsed:.1f} confirmed '
            'own pickups/min. Sources: '+('; '.join(source_notes) or 'none')+
            '. Recipient deliveries NOT verified.')


class CoffeeSessionRecorder:
    """Buffered local CSV recorder for NORMAL and confirmed coffee loops.

    Recording never changes packet timings or waits for acknowledgments.
    Writes only this user's own hand updates and the selected target's
    hand updates, never whole-room chat or arbitrary raw packet contents.
    """
    COLUMNS=('local_time','elapsed_ms','event','furniture_id',
             'recipient_name','recipient_account_id','avatar_room_index',
             'hand_item_type','action_number','cycle','note')
    MAX_BYTES=64*1024*1024

    def __init__(self,directory,interval,source_ids,recipients):
        directory=Path(directory)
        directory.mkdir(parents=True,exist_ok=True)
        slug=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.path=directory/('coffee_session_'+slug+'_'+uuid.uuid4().hex[:6]+'.csv')
        self.summary_path=self.path.with_suffix('.summary.txt')
        self._lock=threading.Lock()
        self._handle=open(self.path,'w',newline='',encoding='utf-8',buffering=65536)
        self._writer=csv.writer(self._handle)
        self._writer.writerow(self.COLUMNS)
        self.started=time.monotonic()
        self.interval=float(interval)
        self.source_ids=tuple(str(v) for v in source_ids)
        self.recipients=tuple((str(n),str(uid)) for n,uid in recipients)
        self.closed=False
        self.error=None
        self.bytes_written=0
        self.events=0
        self.pickup_requests=0
        self.pass_requests=0
        self.source_requests={}
        self.own_held_updates=0
        self.own_empty_updates=0
        self.target_held_updates=0
        self.target_empty_updates=0
        self.last_write_at=time.monotonic()
        self.record('session_start',note=(
            f'delay={self.interval:g}s; sources={",".join(self.source_ids)}; '
            'observed hand events do not prove receipt by a recipient'))
        if self.error:
            self._handle.close()
            raise OSError('Could not begin session recording: '+self.error)

    @staticmethod
    def _cell(value):
        """Prevent user-chosen names becoming spreadsheet formulas in CSV."""
        result=str(value if value is not None else '')
        if result.startswith(('=','+','-','@','\t','\r','\n')):
            return "'"+result
        return result

    def record(self,event,furniture='',name='',account_id='',room_index='',
               hand_item='',action_number='',cycle='',note=''):
        with self._lock:
            if self.closed:
                return False
            try:
                now=time.monotonic()
                row=(datetime.now().astimezone().isoformat(timespec='milliseconds'),
                     round((now-self.started)*1000),event,furniture,name,
                     account_id,room_index,hand_item,action_number,cycle,note)
                safe=tuple(self._cell(item) for item in row)
                self.bytes_written+=sum(len(v.encode('utf-8'))+4 for v in safe)
                if self.bytes_written>self.MAX_BYTES:
                    raise OSError('Coffee recording reached 64 MB size limit')
                self._writer.writerow(safe)
                self.events+=1
                if event=='pickup_request':
                    self.pickup_requests+=1
                    source=str(furniture)
                    self.source_requests[source]=self.source_requests.get(source,0)+1
                elif event=='pass_request':self.pass_requests+=1
                elif event=='own_held_update':self.own_held_updates+=1
                elif event=='own_empty_update':self.own_empty_updates+=1
                elif event=='target_held_update':self.target_held_updates+=1
                elif event=='target_empty_update':self.target_empty_updates+=1
                if self.events%25==0 or now-self.last_write_at>=3:
                    self._handle.flush()
                    self.last_write_at=now
                return True
            except (OSError,UnicodeError,ValueError) as exc:
                self.error=str(exc)
                return False

    def stats(self):
        with self._lock:
            seconds=max(0.001,time.monotonic()-self.started)
            return dict(seconds=seconds,pickups_sent=self.pickup_requests,
                        passes_sent=self.pass_requests,
                        own_held=self.own_held_updates,
                        own_empty=self.own_empty_updates,
                        target_held=self.target_held_updates,
                        target_empty=self.target_empty_updates,
                        events=self.events,error=self.error,
                        source_requests=dict(self.source_requests),
                        pickup_requests_per_min=60*self.pickup_requests/seconds,
                        own_held_updates_per_min=60*self.own_held_updates/seconds)

    def finish(self,reason):
        # Never leave a session without a saved CSV and a separate summary.
        self.record('session_stop',note=str(reason))
        stats=self.stats()
        with self._lock:
            if not self.closed:
                self.closed=True
                try:
                    self._handle.flush()
                finally:
                    self._handle.close()
        summary=(
            'HABBO COMPANION COFFEE SESSION — LOCAL RECORDING\n'
            f'CSV: {self.path}\n'
            f'Delay configured: {self.interval:g}s per action\n'
            f'Sources: {", ".join(self.source_ids)}\n'
            f'Recipients: {", ".join(n for n,_ in self.recipients)}\n'
            f'Elapsed: {stats["seconds"]:.2f}s\n'
            f'Pickup requests sent locally: {stats["pickups_sent"]}\n'
            f'Pass requests sent locally: {stats["passes_sent"]}\n'
            'Pickup requests by furniture: '+
            ', '.join(f'{source}: {count}' for source,count
                      in stats['source_requests'].items())+'\n'
            f'Own avatar holding-item updates: {stats["own_held"]}\n'
            f'Own avatar empty-hand updates: {stats["own_empty"]}\n'
            f'Target avatar holding-item updates: {stats["target_held"]}\n'
            f'Target avatar empty-hand updates: {stats["target_empty"]}\n'
            f'Pickup requests/min: {stats["pickup_requests_per_min"]:.1f}\n'
            f'Own holding-item updates/min: {stats["own_held_updates_per_min"]:.1f}\n'
            f'End reason: {reason}\n'
            f'Recording error: {stats["error"] or "none"}\n'
            'NOTE: CarryObject events are observations, not per-cup receipts.\n'
            'NOTE: Sent packets only confirm a local send, not server acceptance.\n'
            'NOTE: Own/target room index must be known to classify their events.\n'
            'Only the sender and actively selected recipient were monitored.\n'
        )
        self.summary_path.write_text(summary,encoding='utf-8')
        return stats


def build_coffee_group_sequence(cup_one,cup_two,recipients,extra_sources=()):
    """Each participant receives one action from each configured source per cycle."""
    if not 2<=len(recipients)<=8:
        raise ValueError('Group rotation needs 2 to 8 participants.')
    sources=(cup_one,cup_two,*extra_sources)
    sequence=[]
    for round_number in range(len(sources)):
        for i,(_,account_id) in enumerate(recipients):
            furniture=sources[(round_number+i)%len(sources)]
            sequence.extend(build_coffee_pass_sequence(
                furniture,'',account_id,single_cup=True))
    return tuple(sequence)


def build_coffee_pass_sequence(cup_one, cup_two, recipient, single_cup=False):
    """Build one two-cup/two-pass outgoing cycle from captured action IDs."""
    def positive_id(raw, label):
        value=str(raw).strip()
        if not re.fullmatch(r'[0-9]{1,10}',value):
            raise ValueError(label+' must be a positive numeric ID.')
        number=int(value)
        if not 1<=number<2147483648:
            raise ValueError(label+' must be a positive 32-bit ID.')
        return number

    first=positive_id(cup_one,'Cup 1')
    second=positive_id(cup_two,'Cup 2') if not single_cup else None
    target=positive_id(recipient,'Recipient')
    if single_cup:
        return (f'{{out:UseFurniture}}{{i:{first}}}{{i:0}}',
                f'{{out:PassCarryItem}}{{i:{target}}}')
    if first==second:
        raise ValueError('Cup 1 and Cup 2 must have different furniture IDs.')
    return (
        f'{{out:UseFurniture}}{{i:{first}}}{{i:0}}',
        f'{{out:PassCarryItem}}{{i:{target}}}',
        f'{{out:UseFurniture}}{{i:{second}}}{{i:0}}',
        f'{{out:PassCarryItem}}{{i:{target}}}',
    )



# Read the ID/name prefix of Users entries without relying on the full entity
# parser (whose optional fields changed in the 2026 client update).
ROOM_USER_PAIR_RE=re.compile(r'\{i:([0-9]{1,10})\}\{s:"((?:\\.|[^"\\])*)"\}')
ROOM_USER_INDEX_RE=re.compile(
    r'^\{s:"(?:\\.|[^"\\])*"\}\{s:"(?:\\.|[^"\\])*"\}\{i:([0-9]{1,10})\}')


def incoming_packet_is(description,name):
    if not isinstance(description,str):
        return False
    value=description.lstrip().lower()
    return value.startswith('{in:'+name.lower()+'}') or value.startswith('['+name.lower()+']')


def room_user_ids_from_packet(description,trusted_users=False):
    """Parse an incoming Users expression, only after checking its packet header."""
    if not trusted_users and not incoming_packet_is(description,'Users'):
        return {}
    found={}
    for match in ROOM_USER_PAIR_RE.finditer(description):
        try:
            user_id=int(match.group(1))
            name=json.loads('"'+match.group(2)+'"')
        except (ValueError,TypeError):
            continue
        if not 1<=user_id<2147483648 or not isinstance(name,str):
            continue
        if not name.strip() or len(name)>80 or any(ch in name for ch in '\r\n\x00'):
            continue
        # Older prefix: id, name, motto, figure, room index.
        # The index is optional because newer fields may have moved.
        index_match=ROOM_USER_INDEX_RE.match(description[match.end():])
        room_index=int(index_match.group(1)) if index_match else None
        found[name.casefold()]=(name,user_id,room_index)
    return found


def removed_room_user_index(description):
    if not incoming_packet_is(description,'UserRemove'):
        return None
    match=re.search(r'\{s:"([0-9]{1,10})"\}',description)
    return int(match.group(1)) if match else None



def classify_room_packet(extension,direction,packet,description=''):
    """Trust G-Earth's header metadata before inspecting packet data.

    g_string() is a legacy byte string, not a parsed {in:Users} expression.
    Packet headers can change, so never hardcode a numeric Users header.
    """
    names=set()
    try:
        records=(getattr(extension,'packet_infos',None) or {}).get(direction,{}).get(packet.header_id(),())
        for rec in records:
            name=rec.get('Name')
            if isinstance(name,str):names.add(name.casefold())
    except (ValueError,TypeError,AttributeError):
        pass
    for name in ('Users','RoomReady','UserRemove','ExtendedProfile','CarryObject','UserObject'):
        if name.casefold() in names or incoming_packet_is(description,name):
            return name
    return None


def room_users_from_binary_prefixes(packet,known_users=None):
    """Decode reliable Users entity prefixes without trusting old entity tails.

    G-Python's HEntity.parse reads the *whole* entity including optional
    2026-dependent fields. If just one tail changes, it can reject the
    complete roster, including our own avatar's room index. Instead find
    the typed prefix:
      [account ID, name, motto, figure, room index, x, y, z, facing, type]
    inside the actual Users packet. Validate all the fields before
    accepting an entry, and never overwrite with a guessed index.
    """
    # Bytewise prefix scanning must be constrained to server-identifiable
    # account ID + username pairs, or it can find accidental false records.
    if not isinstance(known_users,dict) or not known_users:
        return {}
    payload=(packet if isinstance(packet,(bytes,bytearray))
             else getattr(packet,'bytearray',None))
    if not isinstance(payload,(bytes,bytearray)) or not 14<=len(payload)<=500000:
        return {}
    raw=bytes(payload)
    count=int.from_bytes(raw[6:10],'big',signed=True)
    if not 1<=count<=500:
        return {}

    def string_at(pos,maximum,minimum=0):
        if pos+2>len(raw):
            return None
        length=int.from_bytes(raw[pos:pos+2],'big',signed=False)
        if not minimum<=length<=maximum or pos+2+length>len(raw):
            return None
        return raw[pos+2:pos+2+length].decode('iso-8859-1'),pos+2+length

    found={}
    # A Users packet can contain many entities, each with variable tails.
    # Searching the fixed typed prefix avoids needing to decode those tails.
    for offset in range(10,len(raw)-30):
        account_id=int.from_bytes(raw[offset:offset+4],'big',signed=True)
        if not 1<=account_id<2147483648:
            continue
        name_result=string_at(offset+4,80,1)
        if name_result is None:
            continue
        name,cursor=name_result
        if not name.strip() or any(ord(ch)<32 for ch in name):
            continue
        trusted=known_users.get(name.casefold())
        if (trusted is None or not isinstance(trusted,(tuple,list))
            or len(trusted)<2 or trusted[1]!=account_id):
            continue
        motto_result=string_at(cursor,1024)
        if motto_result is None:
            continue
        _,cursor=motto_result
        figure_result=string_at(cursor,1024)
        if figure_result is None:
            continue
        figure,cursor=figure_result
        # Habbo avatar figures are structured outfit tokens such as
        # hd-180-1.hr-100-42. Without this check, a bytewise scan may
        # mistake incidental strings in a large room packet for users.
        if not re.search(r'(?:^|\.)(?:hd|hr|ch|lg|sh|ha|fa|ca|cc|cp)-[0-9]+',
                         figure):
            continue
        if cursor+12>len(raw):
            continue
        room_index=int.from_bytes(raw[cursor:cursor+4],'big',signed=True)
        x=int.from_bytes(raw[cursor+4:cursor+8],'big',signed=True)
        y=int.from_bytes(raw[cursor+8:cursor+12],'big',signed=True)
        if not (0<=room_index<=1000000 and 0<=x<=4096 and 0<=y<=4096):
            continue
        z_result=string_at(cursor+12,32)
        if z_result is None:
            continue
        z,cursor=z_result
        try:
            if not z or not -1000<=float(z)<=1000:
                continue
        except ValueError:
            continue
        if cursor+8>len(raw):
            continue
        facing=int.from_bytes(raw[cursor:cursor+4],'big',signed=True)
        entity_type=int.from_bytes(raw[cursor+4:cursor+8],'big',signed=True)
        if not (0<=facing<=7 and 1<=entity_type<=4):
            continue
        key=name.casefold()
        record=(name,account_id,room_index)
        if key in found and found[key]!=record:
            # Conflicting indexes are unsafe; discard this roster.
            return {}
        found[key]=record
        if len(found)>count:
            return {}
    return found


def first_room_user_from_raw_packet(packet):
    """Decode only the stable [count, id, name] prefix, no outdated entity tail."""
    try:
        if not 1<=packet.read_int(6)<=500:
            return {}
        user_id=packet.read_int(10)
        name=packet.read_string(14)
        if not 1<=user_id<2147483648 or not isinstance(name,str):
            return {}
        if not 1<=len(name.strip())<=80 or any(c in name for c in '\r\n\x00'):
            return {}
        return {name.casefold():(name,user_id,None)}
    except (IndexError,ValueError,TypeError,UnicodeError,AttributeError):
        return {}


def profile_recipient_from_packet(packet):
    """Read server-confirmed [account ID, username] from ExtendedProfile."""
    try:
        user_id=packet.read_int(6)
        name=packet.read_string(10)
        if not isinstance(name,str) or not 1<=user_id<2147483648:
            return None
        if not 1<=len(name.strip())<=80 or any(ch in name for ch in '\r\n\x00'):
            return None
        return name,user_id
    except (IndexError,ValueError,TypeError,UnicodeError,AttributeError):
        return None


def merge_room_user_records(existing,incoming):
    """Do not erase a verified room index with an incomplete Users update.

    G-Earth may decode an entity's ID/name while missing its optional
    2026 room-index fields. The old code overwrote the earlier index with
    None, making a later UserRemove impossible to match by avatar index.
    """
    merged=dict(existing)
    for key,record in incoming.items():
        previous=merged.get(key)
        if (previous is not None and isinstance(record,(tuple,list))
            and len(record)>2 and record[2] is None
            and isinstance(previous,(tuple,list)) and len(previous)>2
            and isinstance(previous[2],int)
            and record[1]==previous[1]):
            merged[key]=(record[0],record[1],previous[2])
        else:
            merged[key]=record
    return merged


def remove_room_user_by_index(users,index):
    """Keep unaffected entries when an entity leaves, even if indexes are unknown."""
    if not isinstance(index,int) or index<0:
        return dict(users),()
    removed=tuple(name for name,record in users.items()
                  if record[2] is not None and record[2]==index)
    return ({name:record for name,record in users.items() if name not in removed},
            removed)


def coffee_profile_request_expression(username):
    """Encode username as a quoted Habbo packet string, never raw syntax."""
    username=str(username).strip()
    if not 1<=len(username)<=80 or any(c in username for c in '\r\n\x00{}'):
        raise ValueError('Enter a valid username (1-80 characters).')
    return '{out:GetExtendedProfileByName}{s:'+json.dumps(username,ensure_ascii=True)+'}'


def own_identity_from_packet(packet):
    """Habbo's UserObject starts with account ID and username."""
    try:
        ident=packet.read_int(6)
        name=packet.read_string(10)
        if not 1<=ident<2147483648 or not isinstance(name,str):
            return None
        if not 1<=len(name.strip())<=80 or any(c in name for c in '\r\n\x00'):
            return None
        return ident,name
    except (IndexError,ValueError,TypeError,UnicodeError,AttributeError):
        return None


def full_room_users_from_packet(packet,entity_parser=None):
    """Use G-Python's room entity format to obtain both account ID and room index.

    Do not let parser state modifications leak to other packet interceptors.
    Failure returns no entries and callers keep their legacy decoding fallback.
    """
    original=getattr(packet,'read_index',None)
    try:
        count=packet.read_int(6)
        if not isinstance(count,int) or not 1<=count<=500 or original is None:
            return {}
        if entity_parser is None:
            from g_python.hparsers import HEntity
            entity_parser=HEntity.parse
        packet.read_index=6
        entities=entity_parser(packet)
        if len(entities)!=count:
            return {}
        users={}
        for entity in entities:
            account_id=int(entity.id)
            room_index=int(entity.index)
            name=str(entity.name)
            if (not 1<=account_id<2147483648 or not 0<=room_index<=1000000
                or not 1<=len(name.strip())<=80
                or any(c in name for c in '\r\n\x00')):
                return {}
            users[name.casefold()]=(name,account_id,room_index)
        return users
    except (ImportError,IndexError,ValueError,TypeError,AttributeError,KeyError):
        return {}
    finally:
        if original is not None:
            packet.read_index=original


def carry_ack_matches(phase,our_room_index,packet_room_index,item_type,
                      event_time,action_time):
    """Only a new server update about our own avatar may advance the loop."""
    return (phase in ('pickup','release') and our_room_index is not None
            and packet_room_index==our_room_index
            and 0<=event_time-action_time<=25
            and (item_type>0 if phase=='pickup' else item_type==0))


def carry_object_from_packet(packet):
    """Read the incoming CarryObject [room avatar index, hand-item type].

    An avatar index is NOT a Habbo account ID, and a carrying update
    is not a receipt confirmation for a particular PassCarryItem request.
    """
    try:
        room_index=packet.read_int(6)
        item_type=packet.read_int(10)
        if not (0<=room_index<=1000000 and 0<=item_type<=100000):
            return None
        return room_index,item_type
    except (IndexError,ValueError,TypeError,UnicodeError,AttributeError):
        return None


def coffee_delivery_text(pass_requests,carry_observations,target_index):
    """Report observable facts only. A sent packet does not prove receipt."""
    sent=max(0,int(pass_requests))
    seen=max(0,int(carry_observations))
    if target_index is None:
        return (f'Pass requests sent: {sent}. Recipient room index unavailable: '
                'cannot verify receipt from this connection.')
    return (f'Pass requests sent: {sent}. Recipient carrying-item updates '
            f'observed: {seen}. An item update is not proof each cup arrived.')


def validate_manipulation_rule(candidate):
    if not isinstance(candidate,dict):raise ValueError('Invalid rule')
    direction=str(candidate.get('direction','Both'))
    action=str(candidate.get('action','Block'))
    if direction not in RULE_DIRECTIONS or action not in RULE_ACTIONS:
        raise ValueError('Choose a supported direction and action')
    raw_header=str(candidate.get('header','')).strip()
    if not raw_header or raw_header=='*':
        header='*'
    elif raw_header.isdecimal() and 0<=int(raw_header)<=65535:
        header=str(int(raw_header))
    else:raise ValueError('Header must be 0–65535, or * for any header')
    contains=str(candidate.get('contains','')).strip()
    if len(contains)>160:raise ValueError('Contains filter is too long (maximum 160 characters)')
    replacement=str(candidate.get('replacement','')).strip()
    if len(replacement)>4096:raise ValueError('Replacement is too long (maximum 4096 characters)')
    if action=='Replace' and not replacement:raise ValueError('Enter the replacement G-Earth packet expression')
    if header=='*' and not contains:
        raise ValueError('Specify a packet ID or a matching text filter to avoid affecting every packet')
    return {'enabled':bool(candidate.get('enabled',True)), 'direction':direction,
            'header':header,'contains':contains,'action':action,'replacement':replacement}

def apply_manipulation_rule(message,direction,packet_text,rules,extension):
    """Process at most one rule in G-Python's synchronous intercept callback.

    Returns (action, rule_number) or None. Does not touch the UI thread.
    """
    try:header=int(message.packet.header_id()) & 0xffff
    except (AttributeError,TypeError,ValueError):return None
    for index,rule in enumerate(rules):
        if not rule['enabled'] or rule['direction'] not in ('Both',direction):continue
        if rule['header']!='*' and int(rule['header'])!=header:continue
        if rule['contains'] and rule['contains'].lower() not in packet_text.lower():continue
        if rule['action']=='Block':
            message.is_blocked=True
            return ('Block',index+1)
        # G-Earth performs expression parsing; do not evaluate any user input as Python.
        new_packet=extension.string_to_packet(rule['replacement'])
        if new_packet is None or new_packet.is_incomplete_packet() or new_packet.is_corrupted():
            raise ValueError('Replacement packet could not be resolved or was corrupt')
        message.packet.bytearray=bytearray(new_packet.bytearray)
        message.packet.is_edited=True
        return ('Replace',index+1)
    return None

def load_config():
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        if not isinstance(saved,dict):
            return DEFAULT.copy()
        # One-time safety migration: prior releases automatically started AIR
        # interception and attached extensions before the connection was ready.
        # Do not keep re-enabling a mode that has frozen Habbo at 60%.
        if not saved.get('gearth_startup_safety_v104',False):
            saved['gearth_auto_arm']=False
            saved['gearth_minimize']=False
            saved['gearth_startup_safety_v104']=True
            try:
                APP_DIR.mkdir(exist_ok=True,parents=True)
                CONFIG_PATH.write_text(json.dumps(saved,indent=2),encoding='utf-8')
            except OSError:
                pass
        # v1.0.6: leave G-Earth visible while diagnosing startup failures.
        if not saved.get('gearth_visible_debug_v106',False):
            saved['gearth_minimize']=False
            saved['gearth_visible_debug_v106']=True
            try:
                APP_DIR.mkdir(exist_ok=True,parents=True)
                CONFIG_PATH.write_text(json.dumps(saved,indent=2),encoding='utf-8')
            except OSError:
                pass
        # One-time migration: the user requested hands-free beta preparation.
        # This replaces the previous unreliable --connect command startup.
        if not saved.get('gearth_startup_uia_v105', False):
            saved['gearth_auto_arm']=True
            saved['gearth_minimize']=False
            saved['gearth_startup_uia_v105']=True
            try:
                APP_DIR.mkdir(exist_ok=True,parents=True)
                CONFIG_PATH.write_text(json.dumps(saved,indent=2),encoding='utf-8')
            except OSError:
                pass
        # One-time preference migration: user explicitly wants background startup.
        # Preserve every other setting and keep the manual OFF toggle available.
        if not saved.get('gearth_background_v108',False):
            saved['gearth_auto_arm']=True
            saved['gearth_minimize']=True
            saved['gearth_background_v108']=True
            try:
                APP_DIR.mkdir(exist_ok=True,parents=True)
                CONFIG_PATH.write_text(json.dumps(saved,indent=2),encoding='utf-8')
            except OSError:pass
        if not saved.get('gearth_network_safety_v114',False):
            saved['gearth_auto_arm']=False
            saved['gearth_network_safety_v114']=True
            try:
                APP_DIR.mkdir(parents=True,exist_ok=True)
                CONFIG_PATH.write_text(json.dumps(saved,indent=2),encoding='utf-8')
            except OSError:pass
        # Single-user-facing-window upgrade. Only hide preference is changed;
        # never re-enable network interception if it was disabled.
        if not saved.get('gearth_single_window_v116',False):
            saved['gearth_minimize']=True
            saved['gearth_single_window_v116']=True
            try:
                APP_DIR.mkdir(parents=True,exist_ok=True)
                CONFIG_PATH.write_text(json.dumps(saved,indent=2),encoding='utf-8')
            except OSError:pass
        return {**DEFAULT,**{k:v for k,v in saved.items() if k in DEFAULT}}
    except (OSError, ValueError, TypeError):
        return DEFAULT.copy()


def save_config(cfg):
    APP_DIR.mkdir(exist_ok=True, parents=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding='utf-8')


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def is_whisper_chat(chat_type):
    """Habbo AIR: 0=speak, 1=whisper, 2=shout; bot whisper=12."""
    try:return int(chat_type) in (1,12)
    except (ValueError,TypeError):return False


def chat_one_line(text):
    return ' '.join(str(text or '').split())


def whisper_packet_text(packet_description):
    """Read only the message body from a named G-Earth Whisper packet."""
    if not isinstance(packet_description,str):
        return None
    if not re.match(r'^\s*(?:\{(?:in|out):Whisper\}|\[Whisper\])',
                    packet_description,re.IGNORECASE):
        return None
    strings=re.findall(r'\{s:"((?:\\.|[^"\\])*)"\}',packet_description)
    if not strings:
        return None
    try:
        return chat_one_line(json.loads('"'+strings[-1]+'"'))
    except (json.JSONDecodeError,ValueError,TypeError):
        return chat_one_line(strings[-1])


def match_recent_whisper(hints,body,arrived,window=8.0):
    """Consume one temporally matched whisper packet, not every matching chat."""
    needle=chat_one_line(body)
    hints[:]=[(at,text) for at,text in hints if arrived-at<=window]
    for i,(at,text) in enumerate(hints):
        if abs(arrived-at)<=window and text==needle:
            hints.pop(i)
            return True
    return False


def fit_line_ellipsis(text,font_obj,available_px):
    available_px=max(0,int(available_px))
    if font_obj.measure(text)<=available_px:return text
    if font_obj.measure('…')>available_px:return ''
    lo,hi=0,len(text)
    while lo<hi:
        mid=(lo+hi+1)//2
        if font_obj.measure(text[:mid]+'…')<=available_px:lo=mid
        else:hi=mid-1
    return text[:lo].rstrip()+'…'


def chat_line_mode_label(enabled):
    """Visible wording for the persistent one-line/wrapped layout toggle."""
    return ('One-line chat text: ON  (one long line)' if enabled
            else 'One-line chat text: OFF  (wrap onto multiple lines)')


def wrap_message(text, max_px, fnt):
    """Split on words; also break extremely long unspaced tokens."""
    text = re.sub(r'[\r\t]+',' ',str(text or '')).replace('\n',' ')
    rows=[]; line=''
    for token in text.split(' '):
        if not token: continue
        candidate=f'{line} {token}' if line else token
        if fnt.measure(candidate) <= max_px:
            line=candidate
        else:
            if line: rows.append(line)
            line=''
            while token and fnt.measure(token)>max_px:
                chars=max(1,int(len(token)*max_px/max(1,fnt.measure(token))))
                while chars>1 and fnt.measure(token[:chars])>max_px:chars-=1
                rows.append(token[:chars]);token=token[chars:]
            line=token
    if line: rows.append(line)
    return rows or ['']


@dataclass
class Message:
    name:str
    body:str
    arrived:float
    on_screen:bool=True
    room: int | None=None
    style_id: int | None=None
    chat_type: int=0
    forced_color: int | None=None
    bubble_image: Path | None=None
    chat_type_explicit: bool=False  # protect source chat type from packet hints


class WinTracker:
    """Locate an actual Habbo client window, not this settings app."""
    def __init__(self):
        self.enabled=os.name=='nt'
        self.user32=ctypes.windll.user32 if self.enabled else None
        if self.enabled:
            try:self.user32.SetProcessDPIAware()
            except (AttributeError, OSError):pass

    def find(self, exclude_hwnds=()):
        if not self.enabled:return None
        u=self.user32;results=[]
        CALLBACK=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        @CALLBACK
        def it(hwnd, lp):
            if hwnd in exclude_hwnds or not u.IsWindowVisible(hwnd) or u.IsIconic(hwnd):return True
            n=u.GetWindowTextLengthW(hwnd)
            if not n:return True
            b=ctypes.create_unicode_buffer(n+1)
            u.GetWindowTextW(hwnd,b,len(b)); title=b.value
            lower=title.lower()
            if not (lower.startswith('habboairplus') or lower=='habbo' or lower.startswith('habbo -')):
                return True
            rect=wintypes.RECT()
            if not u.GetClientRect(hwnd,ctypes.byref(rect)):return True
            pt=wintypes.POINT(0,0)
            if not u.ClientToScreen(hwnd,ctypes.byref(pt)):return True
            w=rect.right-rect.left;h=rect.bottom-rect.top
            if w>=250 and h>=250:results.append((pt.x,pt.y,w,h,int(hwnd),title))
            return True
        u.EnumWindows(it,0)
        results.sort(key=lambda p: ('airplus' not in p[5].lower(),-p[2]*p[3]))
        return results[0] if results else None

    def set_clickthrough(self, hwnd):
        """Make the *native outer window*, not only Tk's drawing HWND, transparent to input.

        Windows Tk Toplevel widgets may use a separate wrapper HWND around the
        client HWND returned by winfo_id(). Applying WS_EX_TRANSPARENT to the
        client alone can leave an invisible, full-screen mouse-blocking window.
        Re-apply after showing the window because Tk can recreate/change styles.
        """
        if not self.enabled:
            return False
        u=self.user32
        GWL_EXSTYLE=-20
        GA_ROOT=2
        WS_EX_LAYERED=0x00080000
        WS_EX_TRANSPARENT=0x00000020
        WS_EX_TOOLWINDOW=0x00000080
        WS_EX_NOACTIVATE=0x08000000
        flags=WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        try:
            u.GetAncestor.argtypes=(wintypes.HWND,wintypes.UINT)
            u.GetAncestor.restype=wintypes.HWND
            top=u.GetAncestor(int(hwnd),GA_ROOT) or int(hwnd)
            if ctypes.sizeof(ctypes.c_void_p)==8:
                getptr=u.GetWindowLongPtrW
                setptr=u.SetWindowLongPtrW
                getptr.argtypes=(wintypes.HWND,ctypes.c_int)
                getptr.restype=ctypes.c_ssize_t
                setptr.argtypes=(wintypes.HWND,ctypes.c_int,ctypes.c_ssize_t)
                setptr.restype=ctypes.c_ssize_t
            else:
                getptr=u.GetWindowLongW
                setptr=u.SetWindowLongW
                getptr.argtypes=(wintypes.HWND,ctypes.c_int)
                getptr.restype=ctypes.c_long
                setptr.argtypes=(wintypes.HWND,ctypes.c_int,ctypes.c_long)
                setptr.restype=ctypes.c_long
            before=getptr(top,GWL_EXSTYLE)
            if (before & flags)!=flags:
                setptr(top,GWL_EXSTYLE,before | flags)
                SWP_NOSIZE=0x0001
                SWP_NOMOVE=0x0002
                SWP_NOZORDER=0x0004
                SWP_NOACTIVATE=0x0010
                SWP_FRAMECHANGED=0x0020
                u.SetWindowPos(top,0,0,0,0,0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
            return (getptr(top,GWL_EXSTYLE) & flags)==flags
        except (OSError,AttributeError,ValueError,TypeError):
            return False


    def foreground_context(self, habbo_hwnd, settings_hwnd):
        """Return 'habbo', 'settings', or 'other' for the current foreground app.

        Only the foreground Habbo process (including its own popups) counts as
        Habbo. The Tk panel is allowed to stay visible while being edited.
        """
        if not self.enabled:return 'habbo'
        u=self.user32
        try:
            u.GetForegroundWindow.argtypes=()
            u.GetForegroundWindow.restype=wintypes.HWND
            u.GetAncestor.argtypes=(wintypes.HWND,wintypes.UINT)
            u.GetAncestor.restype=wintypes.HWND
            fg=int(u.GetForegroundWindow() or 0)
            if not fg:return 'other'
            def root_hwnd(h):
                return int(u.GetAncestor(int(h),2) or h)
            if root_hwnd(fg)==root_hwnd(settings_hwnd):return 'settings'
            if root_hwnd(fg)==root_hwnd(habbo_hwnd):return 'habbo'
            # AIR dialogs may have independent top-level HWNDs; recognise
            # windows belonging to the same process, but not other apps.
            u.GetWindowThreadProcessId.argtypes=(wintypes.HWND,ctypes.POINTER(wintypes.DWORD))
            u.GetWindowThreadProcessId.restype=wintypes.DWORD
            h_pid=wintypes.DWORD(0)
            f_pid=wintypes.DWORD(0)
            u.GetWindowThreadProcessId(int(habbo_hwnd),ctypes.byref(h_pid))
            u.GetWindowThreadProcessId(fg,ctypes.byref(f_pid))
            if h_pid.value and h_pid.value==f_pid.value:return 'habbo'
            return 'other'
        except (OSError,AttributeError,ValueError,TypeError):
            # Fail safely: never force our overlay over an unknown application.
            return 'other'


    def stack_above_habbo(self, overlay_hwnd, habbo_hwnd):
        """Keep the overlay immediately ABOVE Habbo in the normal z-order.

        This does *not* make the overlay topmost or focus it. Other windows
        (Spotify, Discord, Explorer) remain in front when they are activated.
        GetWindow(GW_HWNDPREV) returns the window directly ABOVE Habbo; by
        inserting the overlay *after* that window, it ends up above Habbo.
        """
        if not self.enabled:return False
        try:
            u=self.user32
            u.GetAncestor.argtypes=(wintypes.HWND,wintypes.UINT)
            u.GetAncestor.restype=wintypes.HWND
            u.GetWindow.argtypes=(wintypes.HWND,wintypes.UINT)
            u.GetWindow.restype=wintypes.HWND
            u.SetWindowPos.argtypes=(wintypes.HWND,wintypes.HWND,
                                    ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,
                                    wintypes.UINT)
            u.SetWindowPos.restype=wintypes.BOOL
            root=int(u.GetAncestor(int(overlay_hwnd),2) or int(overlay_hwnd))
            habbo=int(u.GetAncestor(int(habbo_hwnd),2) or int(habbo_hwnd))
            if root==habbo:return False
            GW_HWNDPREV=3
            preceding=int(u.GetWindow(habbo,GW_HWNDPREV) or 0)
            if preceding==root:
                return True # Already immediately above the game window
            # The insertion position follows the previous z-order window,
            # keeping every unrelated app that is above Habbo above us.
            SWP_NOSIZE=0x0001
            SWP_NOMOVE=0x0002
            SWP_NOACTIVATE=0x0010
            SWP_NOOWNERZORDER=0x0200
            return bool(u.SetWindowPos(root,preceding,0,0,0,0,
                SWP_NOSIZE|SWP_NOMOVE|SWP_NOACTIVATE|SWP_NOOWNERZORDER))
        except (OSError,AttributeError,ValueError,TypeError):
            return False


# Embedded-engine management: the official G-Earth runtime is installed once
# under APPDATA, and controlled from the Companion window. It is not repacked
# into the small auto-update ZIP or rewritten as an incomplete Python proxy.
GEARTH_ENGINE_VERSION='1.5.4-beta-29'
GEARTH_ENGINE_URL='https://github.com/G-Realm/G-Earth/releases/download/1.5.4-beta-29/G-Earth-windows-x64.zip'
GEARTH_ENGINE_SHA256='c2bffcf8ef8e9df6b2355fe6c5f45690bc24b7211f9848728209e0a9b2b4a6e6'
GEARTH_ENGINE_ARCHIVE_BYTES=103387681
GEARTH_ENGINE_DIR=APP_DIR/'engine'/GEARTH_ENGINE_VERSION
GEARTH_ENGINE_MARKER='companion-engine.json'

GEARTH_ENGINE_LICENSE="MIT License\n\nCopyright (c) 2018 sirjonasxx\n\nPermission is hereby granted, free of charge, to any person obtaining a copy\nof this software and associated documentation files (the \"Software\"), to deal\nin the Software without restriction, including without limitation the rights\nto use, copy, modify, merge, publish, distribute, sublicense, and/or sell\ncopies of the Software, and to permit persons to whom the Software is\nfurnished to do so, subject to the following conditions:\n\nThe above copyright notice and this permission notice shall be included in all\ncopies or substantial portions of the Software.\n\nTHE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\nIMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\nFITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\nAUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\nLIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\nOUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\nSOFTWARE.\n"



# Windows networking is never modified without explicit administrator approval.
_GEARTH_HOST=re.compile(rb'^[ \t]*127(?:\.[0-9]{1,3}){3}[ \t]+game-[a-z0-9-]+\.habbo\.com[ \t]+# G-Earth replacement[ \t]*$',re.I)

def gearth_hosts_path():
    return Path(os.environ.get('WINDIR',r'C:\Windows'))/'System32'/'drivers'/'etc'/'hosts'

def filter_gearth_hosts(data):
    kept=[];removed=[]
    for line in data.splitlines(keepends=True):
        (removed if _GEARTH_HOST.fullmatch(line.rstrip(b'\r\n')) else kept).append(line)
    return b''.join(kept),removed

def gearth_network_state():
    state={'redirects':0,'proxy':False,'proxy_server':'','local_proxy':False,'error':''}
    try:
        state['redirects']=len(filter_gearth_hosts(gearth_hosts_path().read_bytes())[1])
        if os.name=='nt':
            import winreg
            key=r'Software\Microsoft\Windows\CurrentVersion\Internet Settings'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_READ) as h:
                def read(name,default):
                    try:return winreg.QueryValueEx(h,name)[0]
                    except FileNotFoundError:return default
                state['proxy']=bool(int(read('ProxyEnable',0)))
                state['proxy_server']=str(read('ProxyServer',''))
        value=state['proxy_server'].lower()
        state['local_proxy']=bool(re.search(r'(^|[;= ])(?:https?://)?(?:localhost|127\.0\.0\.1|\[::1\]):\d+(?:$|[; ])',value))
    except (OSError,ValueError,TypeError) as exc:
        state['error']=str(exc)
    state['active_local_proxy']=bool(state['proxy'] and state['local_proxy'])
    state['unsafe']=bool(state['error'] or state['redirects'] or
                         state['active_local_proxy'])
    return state


def disable_active_local_proxy():
    """User-approved recovery for ONLY the enabled HKCU local manual proxy.

    Makes a JSON backup first and rechecks the server and enabled flag so a
    concurrently changed proxy is not disabled. Doesn't change ProxyServer
    or any other Windows registry setting, DNS or firewall.
    """
    if os.name!='nt':
        raise OSError('Windows required.')
    current=gearth_network_state()
    if current['error']:
        raise OSError('Network settings unavailable: '+current['error'])
    if not current['active_local_proxy']:
        return 'The Windows local manual proxy is already disabled. No changes made.'
    import winreg
    key=r'Software\Microsoft\Windows\CurrentVersion\Internet Settings'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_READ|winreg.KEY_SET_VALUE) as h:
        enabled,enabled_type=winreg.QueryValueEx(h,'ProxyEnable')
        server,server_type=winreg.QueryValueEx(h,'ProxyServer')
        if not enabled or str(server)!=current['proxy_server']:
            raise RuntimeError('Proxy settings changed during inspection. No changes made.')
        if enabled_type!=winreg.REG_DWORD:
            raise RuntimeError('Unexpected ProxyEnable registry type; no changes made.')
        folder=APP_DIR/'network-backups'
        folder.mkdir(parents=True,exist_ok=True)
        backup=folder/('proxy-before-recovery-'+uuid.uuid4().hex+'.json')
        with backup.open('x',encoding='utf-8') as fh:
            json.dump({'ProxyEnable':enabled,'ProxyServer':str(server),
                       'ProxyServer_registry_type':server_type,
                       'ProxyEnable_registry_type':enabled_type},fh,indent=2)
        winreg.SetValueEx(h,'ProxyEnable',0,winreg.REG_DWORD,0)
    # Inform WinINet clients of a settings change, best effort only.
    try:
        wininet=ctypes.WinDLL('wininet',use_last_error=True)
        wininet.InternetSetOptionW(None,39,None,0)  # SETTINGS_CHANGED
        wininet.InternetSetOptionW(None,37,None,0)  # REFRESH
    except (OSError,AttributeError):pass
    confirm=gearth_network_state()
    if confirm['proxy']:
        raise RuntimeError('Proxy remains enabled after recovery; check Windows Settings > Proxy.')
    return 'Disabled the active localhost manual proxy (ProxyEnable=0). Stored server left unchanged. Backup: '+str(backup)


def repair_gearth_hosts():
    """Targeted removal only; exact G-Earth-tagged Habbo redirects."""
    path=gearth_hosts_path()
    before=path.read_bytes()
    after,removed=filter_gearth_hosts(before)
    if not removed:return 'No tagged G-Earth Habbo redirects to repair.'
    folder=APP_DIR/'network-backups'
    folder.mkdir(parents=True,exist_ok=True)
    backup=folder/('hosts-'+uuid.uuid4().hex+'.bak')
    with backup.open('xb') as fp:fp.write(before)
    with path.open('r+b') as fp:
        if fp.read()!=before:
            raise RuntimeError('Hosts changed after backup; no edit performed.')
        fp.seek(0);fp.write(after);fp.truncate();fp.flush();os.fsync(fp.fileno())
    return 'Removed '+str(len(removed))+' tagged Habbo redirect(s). Original hosts backed up at: '+str(backup)

def elevated_gearth_repair(token):
    if not re.fullmatch('[0-9a-f]{32}',str(token)):return 2
    APP_DIR.mkdir(parents=True,exist_ok=True)
    out=APP_DIR/('gearth_repair_'+token+'.json')
    try:result={'ok':True,'msg':repair_gearth_hosts()}
    except Exception as exc:result={'ok':False,'msg':type(exc).__name__+': '+str(exc)[:500]}
    try:out.write_text(json.dumps(result),encoding='utf-8')
    except OSError:return 3
    return 0 if result['ok'] else 1


def managed_gearth_executable():
    """Return only a complete, previously registered managed runtime."""
    try:
        marker=json.loads((GEARTH_ENGINE_DIR/GEARTH_ENGINE_MARKER).read_text(encoding='utf-8'))
        if marker.get('version')!=GEARTH_ENGINE_VERSION:
            return None
        name=marker.get('executable')
        if not isinstance(name,str) or not name:
            return None
        rel=PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or rel.suffix.lower()!='.exe':
            return None
        exe=GEARTH_ENGINE_DIR.joinpath(*rel.parts)
        return exe if exe.is_file() else None
    except (OSError,ValueError,TypeError,AttributeError):
        return None


def install_managed_gearth(selected_executable, notify):
    """Copy the user's chosen working beta, or fetch verified official bytes.

    This function runs in a worker thread. It never accesses Tk widgets.
    The persistent installation is made visible only after a complete copy,
    hash check (for official downloads), and an executable-file check.
    """
    existing=managed_gearth_executable()
    if existing:
        return existing, 'already installed'
    root=GEARTH_ENGINE_DIR.parent
    root.mkdir(parents=True,exist_ok=True)
    staging=root/('staging-'+uuid.uuid4().hex)
    archive=root/('download-'+uuid.uuid4().hex+'.zip')
    runtime=staging/'runtime'
    origin='official verified release'
    try:
        candidate=Path(str(selected_executable or ''))
        use_local=(candidate.is_file() and candidate.suffix.lower()=='.exe'
                   and candidate.name.lower()=='g-earth.exe'
                   and '1.5.3' not in str(candidate).lower()
                   and root.resolve() not in candidate.resolve().parents)
        if use_local:
            # The user already selected this executable in Companion, so
            # reusing the adjacent runtime avoids another ~103 MB download.
            source_dir=candidate.resolve().parent
            if not source_dir.is_dir():
                raise ValueError('Saved G-Earth directory does not exist.')
            total_size=0
            count=0
            for item in source_dir.rglob('*'):
                if item.is_symlink():
                    raise ValueError('Cannot import a G-Earth folder containing symbolic links.')
                if item.is_file():
                    count+=1
                    total_size+=item.stat().st_size
                if count>5000 or total_size>800*1024*1024:
                    raise ValueError('Existing G-Earth folder is unexpectedly large.')
            notify('Importing the selected working G-Earth beta into Companion...')
            shutil.copytree(source_dir,runtime,symlinks=False)
            exe=runtime/candidate.name
            origin='existing user-selected executable (not SHA-verified)'
        else:
            notify('Downloading the official G-Earth beta engine (~103 MB)...')
            digest=hashlib.sha256()
            got=0
            last_bucket=-1
            req=urllib.request.Request(GEARTH_ENGINE_URL,headers={'User-Agent':'HabboCompanion/1.1'})
            with urllib.request.urlopen(req,timeout=30) as response,archive.open('wb') as output:
                while True:
                    block=response.read(1024*1024)
                    if not block:break
                    got+=len(block)
                    if got>115*1024*1024:raise ValueError('Engine download exceeds expected size.')
                    digest.update(block)
                    output.write(block)
                    bucket=got//(10*1024*1024)
                    if bucket!=last_bucket:
                        notify('Downloading engine: '+str(min(100,got*100//GEARTH_ENGINE_ARCHIVE_BYTES))+'%')
                        last_bucket=bucket
            if got!=GEARTH_ENGINE_ARCHIVE_BYTES or digest.hexdigest()!=GEARTH_ENGINE_SHA256:
                raise ValueError('Official engine download checksum or length does not match.')
            notify('Engine verified. Installing its runtime...')
            runtime.mkdir(parents=True,exist_ok=True)
            total_unpacked=0
            with zipfile.ZipFile(archive) as package:
                members=package.infolist()
                if len(members)>6000:
                    raise ValueError('Engine archive contains too many files.')
                for item in members:
                    name=item.filename
                    rel=PurePosixPath(name)
                    if (not name or name.startswith('/') or '\\' in name or
                            ':' in name or any(part in ('..','') for part in rel.parts)):
                        raise ValueError('Unsafe file path in engine archive.')
                    if ((item.external_attr>>16)&0o170000)==0o120000:
                        raise ValueError('Engine archive contains a symbolic link.')
                    total_unpacked+=item.file_size
                    if item.file_size>200*1024*1024 or total_unpacked>850*1024*1024:
                        raise ValueError('Engine archive exceeds extraction limits.')
                    dest=runtime.joinpath(*rel.parts)
                    if item.is_dir():
                        dest.mkdir(parents=True,exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True,exist_ok=True)
                        with package.open(item) as inp, dest.open('wb') as out:
                            shutil.copyfileobj(inp,out,1024*1024)
            executables=[f for f in runtime.rglob('G-Earth.exe') if f.is_file()]
            if len(executables)!=1:
                raise ValueError('Official engine archive has no unique G-Earth.exe.')
            exe=executables[0]
        if not exe.is_file():
            raise ValueError('Managed engine executable could not be located.')
        # Preserve the upstream MIT license for every locally installed copy.
        (staging/'THIRD_PARTY_G_EARTH_LICENSE.txt').write_text(
            GEARTH_ENGINE_LICENSE,encoding='utf-8')
        marker={
            'version':GEARTH_ENGINE_VERSION,
            'executable':exe.relative_to(staging).as_posix(),
            'origin':origin,
            'official_download':GEARTH_ENGINE_URL,
            'official_archive_sha256':GEARTH_ENGINE_SHA256
        }
        (staging/GEARTH_ENGINE_MARKER).write_text(
            json.dumps(marker,indent=2)+'\n',encoding='utf-8')
        if GEARTH_ENGINE_DIR.exists():
            # An incomplete older attempt may remain, but don't remove it if
            # it contains an executable that might still be in use.
            if any(GEARTH_ENGINE_DIR.rglob('G-Earth.exe')):
                raise ValueError('Existing managed engine needs manual inspection before replacing.')
            shutil.rmtree(GEARTH_ENGINE_DIR)
        staging.rename(GEARTH_ENGINE_DIR)
        path=managed_gearth_executable()
        if not path:
            raise ValueError('Engine installation did not pass final validation.')
        return path, origin
    finally:
        try:archive.unlink(missing_ok=True)
        except OSError:pass
        if staging.exists():
            try:shutil.rmtree(staging)
            except OSError:pass



class ChatOverlayApp(PersonaResponderMixin):
    def __init__(self,root):
        self.root=root;self.root.title('Habbo Companion')
        self.root.geometry('1120x820')
        self.root.attributes('-topmost',False)  # behave like a normal app window
        self.root.minsize(940,620)
        self.root.configure(bg=COMPANION_UI['background'])
        self.tracker=WinTracker()
        self.config=load_config()
        self._responder_app_dir=APP_DIR
        self._responder_palette=COMPANION_UI
        self._responder_setup()
        self._account_profiles=normalize_habbo_accounts(
            self.config.get('account_profiles',[]))
        self.config['account_profiles']=self._account_profiles
        self._account_active_id=str(self.config.get('account_active_id',''))
        if self._account_active_id not in {item['id'] for item in self._account_profiles}:
            self._account_active_id=''
        self.config['account_active_id']=self._account_active_id
        self._account_attached_port=None
        self.account_label_var=tk.StringVar(value='')
        self.account_login_url_var=tk.StringVar(value='https://www.habbo.com/')
        self.account_port_var=tk.StringVar(value='')
        self.account_email_var=tk.StringVar(value='')
        self.account_password_var=tk.StringVar(value='')
        self.account_status_var=tk.StringVar(
            value='Save each account login securely on this PC, then use '
                  'Open account login or Auto Play. One G-Earth endpoint at a time.')
        self._account_auto_running=False
        self._account_auto_generation=0
        self._account_run_states={}
        self._account_remaining_ids=()
        self._account_resume_requires_manual=False
        self.direct_classic_exe_var=tk.StringVar(
            value=str(self.config.get('direct_classic_executable','')))
        self.direct_ticket_var=tk.StringVar(value='')
        self.direct_status_var=tk.StringVar(
            value='Direct Classic launches a local Habbo.exe from a valid '
                  'ticket. No Bobba services; game login not verified.')
        self._direct_ticket_queue={}
        self._direct_launch_states={}
        self._direct_launch_running=False
        self._direct_ticket_fetch_running=False
        self._tcp_sessions={}
        self._tcp_inflight=set()
        self._tcp_generation={}
        self._tcp_states={}
        self._classic_probe_running=False
        self.tcp_status_var=tk.StringVar(
            value='Real TCP: enter an official ticket or save an authenticated Habbo session.')
        self.tcp_ticket_var=tk.StringVar(value='')
        self.tcp_session_id_var=tk.StringVar(value='')
        self.tcp_browser_token_var=tk.StringVar(value='')
        self.tcp_autostart_var=tk.BooleanVar(
            value=bool(self.config.get('tcp_auto_connect',False)))
        self._headless_manager=HeadlessLocalManager()
        self._headless_server=None
        self._headless_account_states={}
        self.headless_status_var=tk.StringVar(
            value='Local headless prototype only — NOT connected to Habbo.com.')
        # Original Habbo artwork is mandatory. Older settings may have saved
        # this as False while replacement bubbles were supported.
        self.config['original_bubble_images']=True
        # Packet tools are optional. The existing local AIR chat bridge works
        # even without G-Earth or G-Python installed.
        self.packet_queue=queue.Queue(maxsize=1200)
        self.packet_data=[]
        self.packet_active=False
        self.packet_started=False
        self.packet_extension=None
        # Passive G-Earth metadata: no raw payloads, tickets, or chat text stored.
        self.fuzz_monitoring=False
        self.fuzz_counts={}
        self.fuzz_seen=0
        self.fuzz_running=False
        self.fuzz_last_result=None
        self.fuzz_target_ip_var=tk.StringVar(value='127.0.0.1')
        self.fuzz_habbo_mode_var=tk.BooleanVar(value=False)
        self.fuzz_habbo_header_var=tk.BooleanVar(value=False)
        self.fuzz_remote_ip_var=tk.StringVar(value='')
        self.fuzz_remote_port_var=tk.StringVar(value='39099')
        # Never persist the remote lab key, like an actual Habbo ticket.
        self.fuzz_remote_key_var=tk.StringVar(value='')
        self.fuzz_live_var=tk.StringVar(value='Passive reader OFF. Connect G-Earth first.')
        self.fuzz_lab_var=tk.StringVar(value='Local boofuzz lab idle; never sends to Habbo.')
        self.arcturus_header_var=tk.StringVar(value='')
        self.arcturus_cases_var=tk.StringVar(value='20')
        self.arcturus_status_var=tk.StringVar(
            value='Arcturus emulator idle. Preview offline or explicitly start '
                  'a local-only test (127.0.0.1:30000).')
        self.fuzz_connected_server_var=tk.StringVar(value='Connected game server: none detected. Boofuzz traffic stays on your PC.')
        self._packet_auto_retry_after=0.0
        self.packet_connection_status=tk.StringVar(value='Waiting for G-Earth backend...')
        self.packet_rules=[]
        for rule in self.config.get('packet_rules',[]):
            try:self.packet_rules.append(validate_manipulation_rule(rule))
            except (ValueError,TypeError,KeyError):pass
        self.packet_rules=self.packet_rules[:60]
        self.manipulation_enabled=False  # never enabled automatically on start
        self.manipulation_enable_var=tk.BooleanVar(value=False)
        self.manipulator_status=tk.StringVar(value='Rule engine OFF — no packets are changed.')
        self.rule_direction_var=tk.StringVar(value='Outgoing')
        self.rule_action_var=tk.StringVar(value='Block')
        self.rule_header_var=tk.StringVar(value='')
        self.rule_contains_var=tk.StringVar(value='')
        self.rule_enabled_var=tk.BooleanVar(value=True)
        self.inject_direction_var=tk.StringVar(value='Outgoing')
        self.replay_interval_var=tk.StringVar(value='0.1')
        self.replay_status_var=tk.StringVar(value='Repeat OFF. Load an outgoing packet and start manually.')
        self._replay_running=False
        self._replay_expr=''
        self._replay_interval=0.1
        self._replay_count=0
        self._replay_after_id=None
        self._replay_generation=0
        self.coffee_cup_one_var=tk.StringVar(value=str(self.config.get('coffee_cup_one','476989081')))
        self.coffee_cup_two_var=tk.StringVar(value=str(self.config.get('coffee_cup_two','476989024')))
        self.coffee_extra_furniture_var=tk.StringVar(
            value=str(self.config.get('coffee_extra_furniture','')))
        self.coffee_furniture_capture_var=tk.StringVar(
            value='Optional bookcase / other sources: click Capture, then use the furniture in Habbo.')
        self._coffee_furniture_capture_pending=False
        self._coffee_furniture_capture_generation=0
        self._coffee_active_extra_sources=()
        self.coffee_recipient_var=tk.StringVar(value=str(self.config.get('coffee_recipient','68808036')))
        self.coffee_username_var=tk.StringVar(value=str(self.config.get('coffee_username','')))
        self.coffee_users_status_var=tk.StringVar(value='Room users not detected yet. Join a room with G-Earth attached.')
        self._room_users={}
        self._last_room_users_binary=None
        self._room_chat_names=set()
        self._room_profile_cache={}
        self._coffee_profile_pending=None
        self._coffee_profile_generation=0
        self._room_lookup_pending=False
        self._room_lookup_generation=0
        self._room_lookup_seen=False
        self._room_lookup_parse_failed=False
        self._coffee_target_name=''
        self._coffee_queued_single=False
        self.coffee_interval_var=tk.StringVar(value=str(self.config.get('coffee_interval','0.1')))
        self.coffee_cycles_var=tk.StringVar(value=str(self.config.get('coffee_cycles','0')))
        self.coffee_group_names_var=tk.StringVar(value=str(self.config.get('coffee_group_names','')))
        self.coffee_group_enabled_var=tk.BooleanVar(value=bool(self.config.get('coffee_group_enabled',False)))
        self.coffee_group_exclude_var=tk.StringVar(value='')
        self.coffee_wait_for_hand_var=tk.BooleanVar(
            value=bool(self.config.get('coffee_wait_for_hand',False)))
        self._own_account_id=None
        self._own_name=''
        self._own_room_index=None
        self._own_identity_last_request=0.0
        self._own_identity_pending=False
        self._coffee_wait_for_hand=False
        self._coffee_ack_phase=None
        self._coffee_ack_since=0.0
        self._coffee_ack_timer=None
        self._coffee_finish_after_ack=False
        self.coffee_own_status_var=tk.StringVar(value='Your avatar room index: not detected yet.')
        self._coffee_group_targets=[]
        self._coffee_group_active=False
        self.coffee_status_var=tk.StringVar(value='Coffee pass loop OFF. Choose a recipient and start manually.')
        self.coffee_delivery_var=tk.StringVar(value='Pass requests sent: 0. No recipient delivery evidence yet.')
        self.coffee_recording_var=tk.StringVar(
            value='Automatic recording starts with each coffee run (including 0.1s loops).')
        self._coffee_recorder=None
        self.coffee_speed_var=tk.StringVar(value='Speed test not run. Requires your own avatar room index.')
        self._coffee_speed_active=False
        self._coffee_speed_started=0.0
        self._coffee_speed_source_attempts={}
        self._coffee_speed_source_confirmations={}
        self._coffee_speed_pickups=0
        self._coffee_speed_releases=0
        self._coffee_speed_last_source=None
        self._coffee_speed_delay=0.1
        self._coffee_pass_requests=0
        self._coffee_carry_observations=0
        self._coffee_target_room_index=None
        self._coffee_last_pass_at=0.0
        self._coffee_running=False
        self._coffee_sequence=()
        self._coffee_interval=0.1
        self._coffee_limit=0
        self._coffee_index=0
        self._coffee_sent=0
        self._coffee_completed=0
        self._coffee_generation=0
        self._coffee_after_id=None
        self._coffee_start_queued=False
        self._coffee_queue_after_id=None
        self._coffee_queue_deadline=0.0
        self._habbo_session_connected=False
        self.gearth_process=None
        self._gearth_minimize_tries=0
        self._gearth_hide_pending=False
        self._gearth_hide_tries=0
        self._gearth_hide_failed=False
        self._gearth_manual_window=False
        self._gearth_hidden_confirmed=False
        self._gearth_autostart_active=False
        self._gearth_auto_arm_attempted=False
        self._gearth_launch_queued=False
        self._gearth_started_at=0.0
        self._gearth_launch_watch_until=0.0
        self._gearth_launch_started=0.0
        self._engine_installing=False
        self._engine_last_error=''
        self._engine_start_attempted=False
        self._diagnostic_running=False
        self._diagnostic_text='No diagnostic has run.'
        self._network_repair_report=None
        self._network_repair_deadline=0.0
        self._proxy_watch_until=0.0
        self._proxy_alerted=False
        self.engine_status_var=tk.StringVar(value='Engine: scheduled to start automatically...')
        self.gearth_auto_arm_var=tk.BooleanVar(value=bool(self.config.get('gearth_auto_arm',False)))
        self.habbo_path_display=tk.StringVar(value='Habbo launcher: '+str(self.config.get('habbo_launcher_path') or '(not selected)'))
        self.gearth_minimize_var=tk.BooleanVar(value=bool(self.config.get('gearth_minimize',True)))
        self.packet_filter_var=tk.StringVar(value='')
        self.gearth_port_var=tk.StringVar(value=str(self.config.get('gearth_port',9092)))
        self.gearth_host_var=tk.StringVar(value=str(self.config.get('gearth_host','game-us.habbo.com')))
        self.gearth_game_port_var=tk.StringVar(value=str(self.config.get('gearth_game_port',30000)))
        self.gearth_path_display=tk.StringVar(value='Managed engine: '+str(managed_gearth_executable() or '(initial setup pending)'))
        self.packet_status=tk.StringVar(value=('Starting G-Earth in background. Packet Viewer stays blank until Habbo connects.' if self.config.get('gearth_auto_arm') else 'G-Earth auto-start is OFF. Packet Viewer stays blank until Habbo connects.'))
        self.update_status=tk.StringVar(value='Ready to install a verified update ZIP.')
        self.update_manifest_var=tk.StringVar(value=str(self.config.get('update_manifest_url','')))
        self._online_update_busy=False
        self.messages=[]
        self.whisper_hints=[]  # Brief local G-Earth hints when the AIR feed lacks chatType=2
        # 0 = live/newest. Positive offsets browse older chat without expiring it.
        self.scroll_offset=0
        self.pending_wheel=0
        self.wheel_hook=None
        self._wheel_cb=None
        self.wheel_hook_ready=False
        self.native_images={}
        self.visible_count_current=0
        self.active_image_files=set()
        self.native_image_count=0
        self.last_native_check=0
        self.room_id=None
        self.feed=None
        self.feed_pos=0
        self.last_search=0
        self.started=time.time()
        self.last_rect=None
        self.last_overlay_geometry=None
        self.last_clickthrough_check=0
        self.last_stack_check=0.0
        self.last_overlay_draw_at=0.0
        self.last_overlay_draw_signature=None
        self.clickthrough_failed=False
        self.last_hotkeys=set()
        self.settings_open=True
        self.status=tk.StringVar(value='Waiting for Habbo...')
        self.scroll_status=tk.StringVar(value='LIVE · scroll up over the chat to see older messages')
        self.cfg_vars={}
        self.canvas_font=None;self.canvas_bold=None
        self._make_overlay()
        self._make_settings()
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.root.after(450,self._setup_wheel_hook)
        self.tick()
        self.root.after(200,self._pump_packets)
        self.root.after(1200,self._tcp_auto_connect_startup)
        # Pre-arm before the AIR client connects. Starting only after a Habbo
        # window is visible may be too late for its initial network handshake.
        self.root.after(1800,self._auto_prepare_gearth)
        self.root.after(2800,self._engine_heartbeat)

    def _make_overlay(self):
        self.overlay=tk.Toplevel(self.root)
        self.overlay.overrideredirect(True)
        self.overlay.attributes('-topmost',False)  # never cover unrelated applications
        self.overlay.config(bg=TRANSPARENT)
        self.overlay.wm_attributes('-transparentcolor',TRANSPARENT)
        self.stage=tk.Canvas(self.overlay,bg=TRANSPARENT,highlightthickness=0,borderwidth=0)
        self.stage.pack(fill='both',expand=True)
        self.overlay.geometry('1x1+0+0')
        self.overlay.withdraw()
        self.overlay.update_idletasks()
        # Apply native styles after the window is mapped in tick().


    def _ui_styles(self):
        """Common visual language for every Tk/ttk control in the workspace."""
        p=COMPANION_UI
        style=ttk.Style(self.root)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass
        style.configure('Panel.TFrame',background=p['background'])
        style.configure('Card.TFrame',background=p['surface'])
        style.configure('TLabel',background=p['background'],
                        foreground=p['text'],font=('Segoe UI',10))
        style.configure('Panel.TLabel',background=p['background'],
                        foreground=p['text'],font=('Segoe UI',10))
        style.configure('Card.TLabel',background=p['surface'],
                        foreground=p['text'],font=('Segoe UI',10))
        style.configure('Muted.TLabel',background=p['background'],
                        foreground=p['muted'],font=('Segoe UI',9))
        style.configure('TCheckbutton',background=p['background'],
                        foreground=p['text'],font=('Segoe UI',10),padding=5)
        style.map('TCheckbutton',
                  background=[('active',p['background'])],
                  foreground=[('disabled',p['faint'])])
        style.configure('Panel.TCheckbutton',background=p['background'],
                        foreground=p['text'],font=('Segoe UI',10),padding=5)
        style.map('Panel.TCheckbutton',
                  background=[('active',p['background'])],
                  foreground=[('disabled',p['faint'])])
        style.configure('TButton',font=('Segoe UI Semibold',9),
                        padding=(13,9),background=p['raised'],
                        foreground=p['text'],borderwidth=0,relief='flat',
                        focusthickness=0,focuscolor=p['raised'])
        style.map('TButton',
                  background=[('disabled',p['surface']),
                              ('pressed','#294662'),
                              ('active','#293D54')],
                  foreground=[('disabled',p['faint'])])
        style.configure('Primary.TButton',
                        font=('Segoe UI Semibold',10),padding=(14,10),
                        background=p['accent'],foreground='#071522',
                        borderwidth=0,relief='flat')
        style.map('Primary.TButton',
                  background=[('pressed','#3299D8'),
                              ('active',p['accent_hover'])],
                  foreground=[('disabled',p['faint'])])
        style.configure('Danger.TButton',background='#42283A',
                        foreground='#FFD4DB',font=('Segoe UI',9),
                        padding=(12,9),borderwidth=0)
        style.map('Danger.TButton',background=[('active','#5E324B')])
        style.configure('TEntry',fieldbackground=p['field'],
                        foreground=p['text'],insertcolor=p['text'],
                        bordercolor=p['border'],lightcolor=p['border'],
                        darkcolor=p['border'],padding=(10,8))
        style.map('TEntry',bordercolor=[('focus',p['accent'])])
        style.configure('TCombobox',fieldbackground=p['field'],
                        foreground=p['text'],arrowcolor=p['muted'],
                        background=p['raised'],padding=5)
        style.configure('TScale',background=p['background'],
                        troughcolor=p['raised'])
        style.configure('TLabelframe',background=p['background'],
                        bordercolor=p['border'])
        style.configure('TLabelframe.Label',background=p['background'],
                        foreground=p['text'])
        style.configure('Treeview',background=p['surface'],
                        fieldbackground=p['surface'],foreground=p['text'],
                        rowheight=34,borderwidth=0,relief='flat',
                        font=('Segoe UI',10))
        style.configure('Treeview.Heading',background=p['raised'],
                        foreground=p['muted'],padding=(9,9),
                        font=('Segoe UI Semibold',9),relief='flat')
        style.map('Treeview',
                  background=[('selected','#22415A')],
                  foreground=[('selected',p['text'])])
        style.map('Treeview.Heading',
                  background=[('active','#25394F')])
        style.configure('Vertical.TScrollbar',
                        background=p['raised'],troughcolor=p['background'],
                        arrowcolor=p['muted'],borderwidth=0)
        style.configure('TNotebook',background=p['background'],borderwidth=0)
        style.configure('TNotebook.Tab',background=p['raised'],
                        foreground=p['muted'],padding=(11,8))
        style.map('TNotebook.Tab',
                  background=[('selected',p['surface']),
                              ('active','#25394F')],
                  foreground=[('selected',p['text'])])

    def _ui_add_nav(self,group,items):
        p=COMPANION_UI
        tk.Label(self._ui_sidebar,text=group,font=('Segoe UI Semibold',9),
                 bg=p['sidebar'],fg=p['faint'],anchor='w').pack(
                     fill='x',padx=23,pady=(19,8))
        for key,label in items:
            button=tk.Button(self._ui_sidebar,text='   '+label,
                 font=('Segoe UI Semibold',10),anchor='w',
                 bg=p['sidebar'],fg=p['muted'],
                 activebackground=p['raised'],
                 activeforeground=p['text'],relief='flat',borderwidth=0,
                 cursor='hand2',padx=12,pady=10,
                 command=lambda dest=key:self._ui_show_page(dest))
            button.pack(fill='x',padx=10,pady=2)
            self._ui_nav_buttons[key]=button

    def _ui_show_page(self,key):
        if key not in self._ui_pages:
            return
        self._ui_active=key
        self._ui_pages[key].tkraise()
        p=COMPANION_UI
        title,subtitle=self._ui_page_meta[key]
        self._ui_title_var.set(title)
        self._ui_subtitle_var.set(subtitle)
        for dest,button in self._ui_nav_buttons.items():
            chosen=dest==key
            button.configure(bg=p['raised'] if chosen else p['sidebar'],
                             fg=p['text'] if chosen else p['muted'])
        if key=='overview':
            self._ui_refresh_dashboard()

    def _ui_scroll_area(self,page,key):
        """Scroll long tool panels without hiding controls on smaller displays."""
        p=COMPANION_UI
        holder=ttk.Frame(page,style='Panel.TFrame')
        holder.pack(fill='both',expand=True)
        canvas=tk.Canvas(holder,bg=p['background'],
                         borderwidth=0,highlightthickness=0,
                         yscrollincrement=20)
        bar=ttk.Scrollbar(holder,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        inside=ttk.Frame(canvas,style='Panel.TFrame')
        window=canvas.create_window((0,0),window=inside,anchor='nw')
        inside.bind('<Configure>',lambda e,c=canvas:
                    c.configure(scrollregion=c.bbox('all')))
        canvas.bind('<Configure>',lambda e,c=canvas,w=window:
                    c.itemconfigure(w,width=e.width))
        self._ui_scroll_canvases[key]=canvas
        return inside

    def _ui_mousewheel(self,event):
        # Do not also scroll the page when a text log, table or dropdown
        # already handles its own wheel movement.
        if isinstance(event.widget,(ttk.Treeview,tk.Text,ttk.Combobox)):
            return
        canvas=self._ui_scroll_canvases.get(self._ui_active)
        if canvas is not None and event.delta:
            canvas.yview_scroll(-int(event.delta/120)*3,'units')

    def _ui_refresh_dashboard(self):
        if not hasattr(self,'_ui_dashboard_vars'):
            return
        count=len(self._account_profiles)
        connected=sum(bool(sess and sess.authenticated)
                      for sess in self._tcp_sessions.values())
        joining=len(self._tcp_inflight)
        self._ui_dashboard_vars['accounts'].set(str(count))
        self._ui_dashboard_vars['connected'].set(str(connected))
        self._ui_dashboard_vars['connecting'].set(str(joining))
        self._ui_dashboard_status.set(
            ('%d authenticated TCP connection%s' %
             (connected,'' if connected==1 else 's'))+
            ('  ·  %d connecting' % joining if joining else
             '  ·  No pending TCP connections'))
        self._ui_header_state.set('%d ACCOUNTS  /  %d CONNECTED' %
                                  (count,connected))

    def _ui_dashboard_pulse(self):
        if not self.root.winfo_exists():
            return
        self._ui_refresh_dashboard()
        self.root.after(1700,self._ui_dashboard_pulse)

    def _make_dashboard_panel(self,parent):
        p=COMPANION_UI
        f=ttk.Frame(parent,style='Panel.TFrame',padding=(25,22))
        f.pack(fill='both',expand=True)
        tk.Label(f,text='Your companion, at a glance',
                 font=('Segoe UI Semibold',19),fg=p['text'],
                 bg=p['background']).pack(anchor='w',pady=(0,4))
        tk.Label(f,text='Manage your profiles, connections and tools from one workspace.',
                 font=('Segoe UI',10),fg=p['muted'],
                 bg=p['background']).pack(anchor='w',pady=(0,22))
        cards=ttk.Frame(f,style='Panel.TFrame')
        cards.pack(fill='x',pady=(0,22))
        self._ui_dashboard_vars={}
        for index,(key,label,color,desc) in enumerate((
            ('accounts','ACCOUNT PROFILES',p['accent'],'Saved on this PC'),
            ('connected','DIRECT TCP ONLINE',p['success'],'Server authenticated'),
            ('connecting','CONNECTING',p['muted'],'In progress'))):
            variable=tk.StringVar(value='0')
            self._ui_dashboard_vars[key]=variable
            card=ttk.Frame(cards,style='Card.TFrame',padding=(19,16))
            card.pack(side='left',fill='both',expand=True,
                      padx=(0,12) if index<2 else 0)
            tk.Label(card,text=label,font=('Segoe UI Semibold',9),
                     bg=p['surface'],fg=p['muted']).pack(anchor='w')
            tk.Label(card,textvariable=variable,font=('Segoe UI Semibold',31),
                     bg=p['surface'],fg=color).pack(anchor='w',pady=(4,1))
            tk.Label(card,text=desc,font=('Segoe UI',9),
                     bg=p['surface'],fg=p['faint']).pack(anchor='w')
        quick=ttk.Frame(f,style='Card.TFrame',padding=(22,20))
        quick.pack(fill='x',pady=(0,17))
        tk.Label(quick,text='QUICK ACTIONS',
                 font=('Segoe UI Semibold',9),
                 bg=p['surface'],fg=p['accent']).pack(anchor='w',pady=(0,7))
        tk.Label(quick,text='Get connected',
                 font=('Segoe UI Semibold',17),
                 bg=p['surface'],fg=p['text']).pack(anchor='w',pady=(0,3))
        tk.Label(quick,text='Open your saved profiles or connect them '
                 'through the official Habbo sign-in flow.',
                 font=('Segoe UI',10),bg=p['surface'],fg=p['muted'],
                 justify='left',wraplength=610).pack(anchor='w',pady=(0,15))
        buttons=ttk.Frame(quick,style='Card.TFrame')
        buttons.pack(fill='x')
        ttk.Button(buttons,text='Open Accounts',
                   style='Primary.TButton',
                   command=lambda:self._ui_show_page('accounts')).pack(
                       side='left',padx=(0,10))
        ttk.Button(buttons,text='Direct TCP',
                   command=lambda:self._ui_show_page('tcp')).pack(
                       side='left',padx=(0,10))
        ttk.Button(buttons,text='Check for updates',
                   command=lambda:self._ui_show_page('updates')).pack(side='left')
        health=ttk.Frame(f,style='Card.TFrame',padding=(22,20))
        health.pack(fill='x',pady=(0,10))
        tk.Label(health,text='CONNECTION STATUS',
                 font=('Segoe UI Semibold',9),
                 bg=p['surface'],fg=p['accent']).pack(anchor='w',pady=(0,8))
        self._ui_dashboard_status=tk.StringVar(value='No active TCP connections')
        tk.Label(health,textvariable=self._ui_dashboard_status,
                 font=('Segoe UI Semibold',11),
                 bg=p['surface'],fg=p['text']).pack(anchor='w')
        tk.Label(health,text='Direct TCP is counted as connected only after '
                 'Habbo confirms game-server authentication. Browser login '
                 'alone is not counted.',
                 font=('Segoe UI',9),fg=p['muted'],bg=p['surface'],
                 justify='left',wraplength=720).pack(anchor='w',pady=(8,0))
        self._ui_refresh_dashboard()

    def _make_settings(self):
        """A persistent sidebar and stacked workspaces preserve every tool."""
        self._ui_styles()
        p=COMPANION_UI
        self._ui_pages={}
        self._ui_scroll_canvases={}
        self._ui_nav_buttons={}
        self._ui_active='overview'
        self._ui_page_meta={
            'overview':('Overview','Your Habbo Companion workspace'),
            'accounts':('Accounts','Independent profiles, sign-in and browser sessions'),
            'tcp':('Direct TCP','Official game-server connections and live diagnostics'),
            'chat':('View Chat','Original Habbo bubbles and overlay settings'),
            'responder':('AI Responder','Room-aware writing style and target controls'),
            'packet':('Packet Viewer','G-Earth connection, filters and packet traffic'),
            'fuzz':('Protocol Lab','Passive G-Earth AIR reader and local boofuzz tests'),
            'manip':('Packet Manipulator','Advanced packet rules and manual actions'),
            'classic':('Direct Classic','Launch the installed Habbo client'),
            'headless':('Headless Test','Local-only connection testing'),
            'updates':('Updates','Check and install signed update packages'),
        }
        shell=tk.Frame(self.root,bg=p['background'])
        shell.pack(fill='both',expand=True)
        self._ui_sidebar=tk.Frame(shell,bg=p['sidebar'],width=214)
        self._ui_sidebar.pack(side='left',fill='y')
        self._ui_sidebar.pack_propagate(False)
        tk.Frame(shell,bg=p['border'],width=1).pack(side='left',fill='y')
        brand=tk.Frame(self._ui_sidebar,bg=p['sidebar'])
        brand.pack(fill='x',padx=18,pady=(24,23))
        tk.Label(brand,text='H',font=('Segoe UI Black',18),
                 bg=p['accent'],fg='#071522',width=2,
                 pady=3).pack(side='left',padx=(0,11))
        name=tk.Frame(brand,bg=p['sidebar'])
        name.pack(side='left',fill='x')
        tk.Label(name,text='HABBO',font=('Segoe UI Semibold',12),
                 bg=p['sidebar'],fg=p['text']).pack(anchor='w')
        tk.Label(name,text='COMPANION',font=('Segoe UI Semibold',9),
                 bg=p['sidebar'],fg=p['muted']).pack(anchor='w')
        tk.Frame(self._ui_sidebar,bg=p['border'],height=1).pack(
            fill='x',padx=18)
        self._ui_add_nav('WORKSPACE',(
            ('overview','Overview'),
            ('accounts','Accounts'),
            ('tcp','Direct TCP'),
            ('chat','View Chat'),
            ('responder','AI Responder')))
        self._ui_add_nav('TOOLS',(
            ('packet','Packet Viewer'),
            ('fuzz','Protocol Lab'),
            ('manip','Packet Manipulator'),
            ('classic','Direct Classic'),
            ('headless','Headless Test')))
        self._ui_add_nav('SYSTEM',(('updates','Updates'),))
        tk.Label(self._ui_sidebar,text='LOCAL • PRIVATE PROFILES',
                 bg=p['sidebar'],fg=p['faint'],
                 font=('Segoe UI',8)).pack(side='bottom',anchor='w',
                                           padx=22,pady=(12,22))
        main=tk.Frame(shell,bg=p['background'])
        main.pack(side='left',fill='both',expand=True)
        top=tk.Frame(main,bg=p['background'])
        top.pack(fill='x',padx=(27,23),pady=(23,12))
        h=ttk.Frame(top,style='Panel.TFrame')
        h.pack(side='left',fill='x',expand=True)
        self._ui_title_var=tk.StringVar(value='Overview')
        self._ui_subtitle_var=tk.StringVar(value='Your Habbo Companion workspace')
        tk.Label(h,textvariable=self._ui_title_var,
                 font=('Segoe UI Semibold',21),
                 bg=p['background'],fg=p['text']).pack(anchor='w')
        tk.Label(h,textvariable=self._ui_subtitle_var,
                 font=('Segoe UI',10),
                 bg=p['background'],fg=p['muted']).pack(anchor='w',pady=(3,0))
        self._ui_header_state=tk.StringVar(value='0 ACCOUNTS  /  0 CONNECTED')
        tk.Label(top,textvariable=self._ui_header_state,
                 font=('Segoe UI Semibold',9),
                 bg=p['raised'],fg=p['success'],
                 padx=13,pady=9).pack(side='right',anchor='n',pady=7)
        tk.Frame(main,bg=p['border'],height=1).pack(
            fill='x',padx=(27,23),pady=(0,4))
        stack=tk.Frame(main,bg=p['background'])
        stack.pack(fill='both',expand=True,padx=(9,9),pady=(0,7))
        stack.grid_rowconfigure(0,weight=1)
        stack.grid_columnconfigure(0,weight=1)
        for key in self._ui_page_meta:
            page=ttk.Frame(stack,style='Panel.TFrame')
            page.grid(row=0,column=0,sticky='nsew')
            self._ui_pages[key]=page
        self._make_dashboard_panel(self._ui_scroll_area(
            self._ui_pages['overview'],'overview'))
        self._make_packet_panel(self._ui_scroll_area(
            self._ui_pages['packet'],'packet'))
        self._make_fuzz_panel(self._ui_scroll_area(
            self._ui_pages['fuzz'],'fuzz'))
        self._make_responder_panel(self._ui_scroll_area(
            self._ui_pages['responder'],'responder'))
        self._make_accounts_panel(self._ui_scroll_area(
            self._ui_pages['accounts'],'accounts'))
        self._make_direct_classic_panel(self._ui_scroll_area(
            self._ui_pages['classic'],'classic'))
        self._make_live_tcp_panel(self._ui_scroll_area(
            self._ui_pages['tcp'],'tcp'))
        self._make_headless_panel(self._ui_scroll_area(
            self._ui_pages['headless'],'headless'))
        self._make_manipulator_panel(self._ui_scroll_area(
            self._ui_pages['manip'],'manip'))
        self._make_updates_panel(self._ui_scroll_area(
            self._ui_pages['updates'],'updates'))
        outer=self._ui_pages['chat']
        # Scrollable chat settings remain fully editable, with the same
        # original bubble controls, callbacks and keyboard shortcuts.
        # Scrollable control panel: every setting stays accessible on smaller monitors.
        content=tk.Canvas(outer,bg=COMPANION_UI['background'],highlightthickness=0,borderwidth=0)
        bar=ttk.Scrollbar(outer,orient='vertical',command=content.yview)
        content.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y')
        content.pack(side='left',fill='both',expand=True)
        f=ttk.Frame(content,style='Panel.TFrame',padding=(18,14))
        window=content.create_window((0,0),window=f,anchor='nw')
        f.bind('<Configure>',lambda e:content.configure(scrollregion=content.bbox('all')))
        content.bind('<Configure>',lambda e:content.itemconfigure(window,width=e.width))
        def scroll_panel(e):
            if e.delta:content.yview_scroll(-int(e.delta/120)*3,'units')
        self._ui_scroll_canvases['chat']=content
        self.root.bind('<MouseWheel>',self._ui_mousewheel)

        tk.Label(f,text='VIEW CHAT',font=('Segoe UI Semibold',19),bg=COMPANION_UI['background'],fg=COMPANION_UI['text']).pack(anchor='w')
        tk.Label(f,text='Screen-locked chat for your current Habbo view',font=('Segoe UI',9),bg=COMPANION_UI['background'],fg=COMPANION_UI['muted']).pack(anchor='w',pady=(0,10))
        lab=ttk.Label(f,textvariable=self.status,style='Panel.TLabel',wraplength=345)
        lab.pack(anchor='w',fill='x',pady=(0,10))
        self._check(f,'Only people inside my view','visible_only')
        self._check(f,'Hide room (ambient background)','show_room',invert=True)
        self._check(f,'Show original Habbo bubbles','bubbles')
        tk.Label(f,text='Original Habbo bubble artwork is always used (no imitation bubbles).',
                 wraplength=352,justify='left',font=('Segoe UI',9),
                 bg=COMPANION_UI['background'],fg=COMPANION_UI['muted']).pack(anchor='w',pady=(3,4))
        self._chat_line_toggle(f)
        self._check(f,'Whispers on the right','whispers_right')
        tk.Label(f,text='Original Habbo bubbles keep their genuine artwork, '
                     'font and wrapping. The one-line switch and Font size '
                     'control only affect text-only messages when Habbo has not '
                     'supplied an original PNG.',
                 wraplength=352,justify='left',font=('Segoe UI',9),
                 bg=COMPANION_UI['background'],fg=COMPANION_UI['muted']).pack(anchor='w',pady=(2,4))
        self._check(f,'Keep a local chat log after exit','keep_log')
        self._check(f,'Auto-fill available screen with chat bubbles','auto_fill_screen')
        tk.Label(f,text='The overlay stays above Habbo, but behind other apps. Switching windows does not clear chat.',
                 wraplength=352,justify='left',font=('Segoe UI',9),bg=COMPANION_UI['background'],fg=COMPANION_UI['muted']).pack(anchor='w',pady=(2,4))
        tk.Label(f,text='When auto-fill is on, the number of visible bubbles adapts to your screen height. Older messages stay in scrollback.',
                 wraplength=352,justify='left',font=('Segoe UI',9),bg=COMPANION_UI['background'],fg=COMPANION_UI['muted']).pack(anchor='w',pady=(2,4))
        for label,key,low,high,desc in [
            ('Vertical starting point','anchor',45,95,'% of screen height'),
            ('Left margin','x',0,200,'pixels from window edge'),
            ('Bubble width (wrapped mode)','width',250,800,'pixels'),
            ('Font size','font_size',11,23,'points'),
            ('Bubbles visible (manual mode)','visible_messages',3,100,'messages'),
            ('Messages kept for scrollback','history_limit',30,500,'in memory'),
            ('Bubble spacing','gap',2,18,'pixels'),
            ('Keep Habbo typing bar visible','bottom_clearance',65,220,'pixels reserved at bottom'),
        ]:
            sf=ttk.Frame(f,style='Panel.TFrame');sf.pack(fill='x',pady=(7,0))
            lf=ttk.Frame(sf,style='Panel.TFrame');lf.pack(fill='x')
            ttk.Label(lf,text=label,style='Panel.TLabel').pack(side='left')
            v=tk.IntVar(value=int(self.config[key]));self.cfg_vars[key]=v
            value=ttk.Label(lf,style='Panel.TLabel',text=f'{v.get()} {desc}')
            value.pack(side='right')
            def changed(raw,k=key,var=v,out=value,suffix=desc):
                n=int(float(raw));var.set(n);self.config[k]=n
                out.configure(text=f'{n} {suffix}')
                if k=='history_limit':self._trim_history()
                self.save()
            sl=ttk.Scale(sf,from_=low,to=high,orient='horizontal',command=changed)
            sl.set(v.get());sl.pack(fill='x',pady=(2,0))
        line=ttk.Frame(f,style='Panel.TFrame');line.pack(fill='x',pady=(11,6))
        ttk.Label(line,text='Background theme',style='Panel.TLabel').pack(side='left')
        self.theme=tk.StringVar(value=self.config['theme'])
        cb=ttk.Combobox(line,values=list(THEMES),width=13,textvariable=self.theme,state='readonly')
        cb.pack(side='right')
        cb.bind('<<ComboboxSelected>>',lambda e:self.update_theme())
        btns=ttk.Frame(f,style='Panel.TFrame');btns.pack(fill='x',pady=(8,4))
        ttk.Button(btns,text='Preview chat',command=self.preview).pack(side='left',expand=True,fill='x',padx=(0,5))
        ttk.Button(btns,text='Select log file',command=self.select_feed).pack(side='left',expand=True,fill='x',padx=(5,0))
        nav=ttk.Frame(f,style='Panel.TFrame');nav.pack(fill='x',pady=(7,1))
        ttk.Button(nav,text='↑ Older chat',command=lambda:self.scroll_chat(3)).pack(side='left',expand=True,fill='x',padx=(0,4))
        ttk.Button(nav,text='↓ Newer chat',command=lambda:self.scroll_chat(-3)).pack(side='left',expand=True,fill='x',padx=(0,4))
        ttk.Button(nav,text='Latest',command=self.jump_to_latest).pack(side='left',expand=True,fill='x')
        ttk.Label(f,textvariable=self.scroll_status,style='Panel.TLabel',wraplength=380).pack(anchor='w',fill='x',pady=(4,3))
        opts=ttk.Frame(f,style='Panel.TFrame');opts.pack(fill='x',pady=(4,0))
        ttk.Button(opts,text='Clear messages',command=self.clear_msgs).pack(side='left',expand=True,fill='x',padx=(0,5))
        ttk.Button(opts,text='Clear local log',command=self.clear_log).pack(side='left',expand=True,fill='x',padx=(5,0))
        tk.Label(f,text='Ctrl + Shift + F6  ·  show/hide settings\nCtrl + Shift + F7  ·  toggle room background\nCtrl + Shift + PgUp/PgDn  ·  older/newer chat',font=('Segoe UI',9),justify='left',bg=COMPANION_UI['background'],fg=COMPANION_UI['faint']).pack(anchor='w',pady=(13,0))
        tk.Label(f,text='Messages do not expire. Only recent bubbles are drawn; scroll for older.\nHistory is bounded in memory and cleared on exit (unless logging is enabled).\nOriginal artwork comes from your existing modified Habbo client.',font=('Segoe UI',8),justify='left',bg=COMPANION_UI['background'],fg=COMPANION_UI['faint']).pack(anchor='w',pady=(8,0))
        self._ui_show_page('overview')
        self.root.after(1700,self._ui_dashboard_pulse)


    def _make_live_tcp_panel(self, parent):
        """Authenticate a real Habbo socket without running a game client."""
        f=ttk.Frame(parent,style='Panel.TFrame',padding=16)
        f.pack(fill='both',expand=True)
        tk.Label(f,text='DIRECT HABBO TCP (EXPERIMENTAL)',
                 font=('Segoe UI Semibold',17),bg=COMPANION_UI['background'],
                 fg=COMPANION_UI['text']).pack(anchor='w',pady=(0,8))
        tk.Label(f,text='Connect directly to the official game server without '
                 'launching Habbo.exe or G-Earth. Auto-import may briefly open '
                 'your private Brave profile in the background to request an '
                 'SSO ticket. Authentication is confirmed by Habbo, not the website.',
                 bg=COMPANION_UI['background'],fg=COMPANION_UI['muted'],justify='left',
                 wraplength=615).pack(anchor='w',fill='x',pady=(0,10))
        self.tcp_table=ttk.Treeview(
            f,columns=('profile','state'),show='headings',
            height=5,selectmode='browse')
        self.tcp_table.heading('profile',text='Account profile')
        self.tcp_table.heading('state',text='Habbo server status')
        self.tcp_table.column('profile',width=170,stretch=False)
        self.tcp_table.column('state',width=380,stretch=True)
        self.tcp_table.pack(fill='x',pady=(0,8))
        ttk.Label(f,text='Optional: paste an official SSO ticket (selected account)',
                  style='Panel.TLabel').pack(anchor='w')
        ttk.Entry(f,textvariable=self.tcp_ticket_var,show='*').pack(
            fill='x',pady=(3,7))
        tk.Label(f,text='Recommended: Auto-import a new ticket from the existing '
                 'signed-in browser profile. Legacy session cookies are optional; '
                 'an isolated headless browser can be started if needed. '
                 'Habbo CAPTCHA or email verification remains manual.',
                 bg=COMPANION_UI['background'],fg=COMPANION_UI['muted'],justify='left',
                 wraplength=615).pack(anchor='w',pady=(1,7))
        for name,var in (('session.id',self.tcp_session_id_var),
                         ('browser_token',self.tcp_browser_token_var)):
            line=ttk.Frame(f,style='Panel.TFrame')
            line.pack(fill='x',pady=(0,6))
            ttk.Label(line,text=name,style='Panel.TLabel',width=18).pack(
                side='left')
            ttk.Entry(line,textvariable=var,show='*').pack(
                side='left',fill='x',expand=True)
        row=ttk.Frame(f,style='Panel.TFrame')
        row.pack(fill='x',pady=(0,8))
        ttk.Button(row,text='Save session in Windows vault',
                   command=self._tcp_save_session).pack(side='left',padx=(0,7))
        ttk.Button(row,text='Forget saved session',
                   command=self._tcp_forget_session).pack(side='left')
        ttk.Button(f,text='Auto-import session and connect (selected account)',
                    style='Primary.TButton',
                   command=self._tcp_auto_import_selected).pack(
                   anchor='w',pady=(1,7))
        ttk.Checkbutton(
            f,
            text='Automatically connect saved TCP accounts when Companion opens',
            variable=self.tcp_autostart_var,
            command=self._tcp_autostart_changed,
            style='Panel.TCheckbutton').pack(anchor='w',pady=(3,9))
        row=ttk.Frame(f,style='Panel.TFrame')
        row.pack(fill='x',pady=(0,8))
        ttk.Button(row,text='Connect selected',
                   command=self._tcp_connect_selected).pack(side='left',padx=(0,7))
        ttk.Button(row,text='Connect all saved',
                   command=self._tcp_connect_all).pack(side='left',padx=(0,7))
        ttk.Button(row,text='Disconnect selected',
                   command=self._tcp_disconnect_selected).pack(side='left')
        row=ttk.Frame(f,style='Panel.TFrame')
        row.pack(fill='x',pady=(0,9))
        ttk.Button(row,text='Disconnect all',
                   command=self._tcp_disconnect_all).pack(side='left',padx=(0,7))
        ttk.Button(row,text='Auto-import and connect all',
                   command=self._tcp_auto_import_all).pack(side='left',padx=(0,7))
        ttk.Button(row,text='Refresh account list',
                   command=self._tcp_render).pack(side='left')
        tk.Label(
            f,
            text='Habbo Classic (2026) uses a separate secure WebSocket '
                 'endpoint. Test its TLS/HTTP upgrade without using any '
                 'cookies, SSO tickets, saved accounts or game packets.',
            bg=COMPANION_UI['background'],fg=COMPANION_UI['muted'],justify='left',
            wraplength=615).pack(anchor='w',fill='x',pady=(1,7))
        ttk.Button(f,text='Test Classic WSS connection (no login)',
                   command=self._tcp_test_classic_websocket).pack(
                   anchor='w',pady=(0,9))
        tk.Label(f,textvariable=self.tcp_status_var,bg=COMPANION_UI['background'],
                 fg=COMPANION_UI['success'],justify='left',wraplength=615).pack(
                 anchor='w',fill='x',pady=(0,9))
        ttk.Label(f,text='TCP connection steps and incoming packet IDs (secrets hidden)',
                  style='Panel.TLabel').pack(anchor='w')
        self.tcp_log=tk.Text(f,height=5,state='disabled',
                             bg=COMPANION_UI['field'],fg=COMPANION_UI['muted'],
                             relief='flat',font=('Consolas',9))
        self.tcp_log.pack(fill='x',pady=(2,7))
        tk.Label(f,text='Automatic session import uses your own separate '
                 'Habbo account browser and any login already saved in the '
                 'Accounts tab. It never reads your regular Brave profile. '
                 'Cookies stay in Windows Credential Manager, not settings '
                 'or logs. CAPTCHA/2FA and expired or incorrect passwords '
                 'still require the normal official sign-in process.',
                 bg=COMPANION_UI['background'],fg=COMPANION_UI['muted'],justify='left',
                 wraplength=615).pack(anchor='w')
        self._tcp_render()

    def _tcp_test_classic_websocket(self):
        # One read-only protocol reachability check, independent of accounts.
        if self._classic_probe_running:
            self.tcp_status_var.set('Classic WebSocket probe already running.')
            return
        self._classic_probe_running=True
        self._tcp_log_event('classic','Probing wss://game-us.habbo.com:30001/websocket')
        self.tcp_status_var.set('Testing Classic WebSocket TLS and protocol upgrade...')
        threading.Thread(target=self._classic_ws_probe_worker,
                         daemon=True,name='companion-classic-wss-probe').start()

    def _classic_ws_probe_worker(self):
        try:
            result=probe_classic_websocket()
            self._packet_put(('classic_ws_probe',result))
        except HabboTcpError as exc:
            # Error strings are static protocol diagnostics without URL query,
            # HTTP response body, cookies, SSO tickets or user identifiers.
            self._packet_put(('classic_ws_probe',str(exc)[:150]))
        except Exception:
            self._packet_put(('classic_ws_probe',
                              'Classic WebSocket: unexpected probe failure'))

    def _tcp_log_event(self, ident, message):
        """Safe diagnostic log: redact token-shaped exception messages."""
        if not self.tcp_log.winfo_exists():
            return
        self.tcp_log.configure(state='normal')
        self.tcp_log.insert('end',
            time.strftime('%H:%M:%S')+' ['+ident[:6]+'] '+
            redact_sensitive_diagnostic(message)+'\n')
        if int(self.tcp_log.index('end-1c').split('.')[0])>90:
            self.tcp_log.delete('1.0','30.0')
        self.tcp_log.see('end')
        self.tcp_log.configure(state='disabled')

    def _tcp_selected(self):
        selected=self.tcp_table.selection()
        if not selected:
            self.tcp_status_var.set('Select an account first.')
            return None
        return next((a for a in self._account_profiles
                     if a['id']==selected[0]),None)

    def _tcp_render(self):
        table=self.tcp_table
        selected=table.selection()
        ident=selected[0] if selected else None
        for row in table.get_children():
            table.delete(row)
        for account in self._account_profiles:
            key=account['id']
            sess=self._tcp_sessions.get(key)
            state=('Authenticated (direct TCP)' if sess and sess.authenticated
                   else self._tcp_states.get(key,'Disconnected'))
            if key in self._tcp_inflight:
                state=self._tcp_states.get(key,'Connecting...')
            table.insert('', 'end',iid=key,
                         values=(account['label'],state))
        if ident and table.exists(ident):
            table.selection_set(ident)
        elif self._account_profiles:
            table.selection_set(self._account_profiles[0]['id'])
        self._fuzz_refresh_connected_server()

    def _tcp_save_session(self):
        account=self._tcp_selected()
        if not account:return
        try:
            account_session_cookie_write(
                account['id'],self.tcp_session_id_var.get(),
                self.tcp_browser_token_var.get())
        except (OSError,ValueError) as exc:
            self.tcp_status_var.set('Session not saved: '+str(exc)[:120])
            return
        self.tcp_session_id_var.set('')
        self.tcp_browser_token_var.set('')
        self.tcp_status_var.set(
            'Session saved in this Windows user vault; no website browser needed '
            'until Habbo expires these cookies.')

    def _tcp_forget_session(self):
        account=self._tcp_selected()
        if not account:return
        try:
            account_session_cookie_delete(account['id'])
        except OSError:
            self.tcp_status_var.set('Windows could not erase the saved session.')
            return
        self.tcp_session_id_var.set('')
        self.tcp_browser_token_var.set('')
        self.tcp_status_var.set('Saved website session removed from Windows vault.')

    def _tcp_autostart_changed(self):
        enabled=bool(self.tcp_autostart_var.get())
        self.config['tcp_auto_connect']=enabled
        self.save()
        self.tcp_status_var.set(
            'Saved account TCP auto-connect '+('enabled.' if enabled else 'disabled.')
            +' You will still need to sign in again if Habbo expires a session.')

    def _tcp_auto_connect_startup(self):
        if not self.tcp_autostart_var.get():
            return
        # Only existing saved sessions are requested; never start a browser,
        # prompt for credentials, or launch a game executable.
        self._tcp_connect_all()

    def _tcp_auto_import_selected(self):
        account=self._tcp_selected()
        if account is not None:
            self._tcp_connect_one(account,auto_capture=True)
            self._tcp_render()

    def _tcp_auto_import_all(self):
        for account in self._account_profiles:
            self._tcp_connect_one(account,auto_capture=True)
        self._tcp_render()
        self.tcp_status_var.set('Requested account-specific automatic session '
                                'imports; each uses its own isolated profile.')

    def _tcp_connect_one(self, account, use_form=False, auto_capture=False):
        ident=account['id']
        if ident in self._tcp_inflight:
            return
        existing=self._tcp_sessions.get(ident)
        if existing and existing.authenticated:
            return
        if existing:
            existing.close()
            self._tcp_sessions.pop(ident,None)
        ticket=None
        cookies=None
        if use_form:
            raw=self.tcp_ticket_var.get().strip()
            self.tcp_ticket_var.set('')
            if raw:
                try:
                    ticket=parse_classic_ticket(raw)
                except ValueError as exc:
                    self.tcp_status_var.set('Ticket invalid: '+str(exc)[:120])
                    return
            a=self.tcp_session_id_var.get().strip()
            b=self.tcp_browser_token_var.get().strip()
            if a or b:
                cookies=(a,b)
            self.tcp_session_id_var.set('')
            self.tcp_browser_token_var.set('')
        if not auto_capture and ticket is None:
            ticket=self._direct_ticket_queue.pop(ident,None)
        if not auto_capture and ticket is None and cookies is None:
            try:
                cookies=account_session_cookie_read(ident)
            except (OSError,ValueError):
                self._tcp_states[ident]='Could not read saved Windows session'
                return
        if ticket is None and cookies is None and not auto_capture:
            if use_form:
                # An explicit Connect selected click may acquire a missing
                # session using this account's saved browser login.
                auto_capture=True
            else:
                self._tcp_states[ident]='No saved session; click Auto-import'
                return
        if auto_capture and any(
            account_browser_debug_port(ident)==account_browser_debug_port(other['id'])
            for other in self._account_profiles if other['id']!=ident):
            self._tcp_states[ident]='Browser port conflict between accounts'
            return
        generation=self._tcp_generation.get(ident,0)+1
        self._tcp_generation[ident]=generation
        self._tcp_inflight.add(ident)
        self._tcp_states[ident]=(
            'Automatically importing website session' if auto_capture
            else 'Starting direct TCP')
        threading.Thread(
            target=self._tcp_connect_worker,
            args=(dict(account),ticket,cookies,generation,auto_capture),
            daemon=True,name='companion-live-tcp-'+ident).start()

    def _tcp_connect_worker(self,account,ticket,cookies,generation,
                            auto_capture=False):
        ident=account['id']
        session=None
        try:
            if auto_capture and ticket is None:
                ticket=account_import_session_automatically(
                    account,lambda message:self._packet_put(
                        ('tcp_state',ident,generation,message)))
            elif ticket is None:
                self._packet_put(('tcp_state',ident,generation,
                                  'Requesting SSO from official Habbo.com HTTPS'))
                try:
                    raw=fetch_habbo_sso_ticket(*cookies)
                    ticket=account_parse_official_ticket_response(raw)
                except HabboTcpError as exc:
                    # Only automatically renew an explicitly expired website
                    # session. Never loop retries, guess credentials or
                    # suppress CAPTCHA/MFA failures.
                    if ('Habbo rejected the website session' not in str(exc)
                        or any(account_browser_debug_port(ident)==
                               account_browser_debug_port(other['id'])
                               for other in self._account_profiles
                               if other['id']!=ident)):
                        raise
                    self._packet_put(('tcp_state',ident,generation,
                                      'Stored Habbo session expired; '
                                      'refreshing from this account browser'))
                    ticket=account_import_session_automatically(
                        account,lambda message:self._packet_put(
                            ('tcp_state',ident,generation,message)))
            # The .username suffix in a Habbo launch link is display
            # metadata, not part of the game-server SSO credential.
            # Bobba Launcher and our Direct Classic mode both pass only
            # <opaque>.V4 to the AIR authentication handler.
            actual=ticket.secret
            self._packet_put(('tcp_state',ident,generation,
                              'Official SSO ticket parsed; starting game connection'))
            session=HabboTcpSession(
                ident,
                status=lambda msg:self._packet_put(
                    ('tcp_state',ident,generation,msg)),
                packet=lambda packet_id,size:self._packet_put(
                    ('tcp_packet',ident,generation,packet_id,size)))
            session.connect(actual)
            self._packet_put(('tcp_connected',ident,generation,session))
        except (OSError,ValueError,RuntimeError,HabboTcpError,TimeoutError) as exc:
            if session:
                session.close()
            # Never put HTTP responses, cookies, or SSO tokens in UI diagnostics.
            detail=(str(exc)[:130] if isinstance(exc,(HabboTcpError,ValueError))
                    else type(exc).__name__)
            self._packet_put(('tcp_failed',ident,generation,detail))

    def _tcp_connect_selected(self):
        account=self._tcp_selected()
        if account:
            self._tcp_connect_one(account,use_form=True)
            self._tcp_render()
            self._direct_render()

    def _tcp_connect_all(self):
        for account in self._account_profiles:
            self._tcp_connect_one(account)
        self._tcp_render()
        self._direct_render()
        self.tcp_status_var.set('Requested independent TCP login for each '
                                'profile with a queued ticket or saved session.')

    def _tcp_disconnect_one(self,ident):
        self._tcp_generation[ident]=self._tcp_generation.get(ident,0)+1
        self._tcp_inflight.discard(ident)
        session=self._tcp_sessions.pop(ident,None)
        if session:
            session.close()
        self._tcp_states[ident]='Disconnected'

    def _tcp_disconnect_selected(self):
        account=self._tcp_selected()
        if account:
            self._tcp_disconnect_one(account['id'])
            self._tcp_render()
            self.tcp_status_var.set('Disconnected selected profile.')

    def _tcp_disconnect_all(self):
        for ident in tuple(self._tcp_generation):
            self._tcp_disconnect_one(ident)
        self._tcp_render()
        self.tcp_status_var.set('All direct TCP sessions disconnected.')


    def _make_headless_panel(self,parent):
        """Socket-based per-account LOCAL test; never claims live Habbo login."""
        f=ttk.Frame(parent,style='Panel.TFrame',padding=16)
        f.pack(fill='both',expand=True)
        tk.Label(f,text='HEADLESS CONNECTION TEST',
                 font=('Segoe UI Semibold',17),fg=COMPANION_UI['text'],
                 bg=COMPANION_UI['background']).pack(anchor='w',pady=(0,9))
        tk.Label(
            f,text='Proof of concept: multiple independent TCP connections '
                   'without Brave, Habbo Launcher, or Classic. This is a '
                   'loopback test server (127.0.0.1), NOT the live Habbo.com '
                   'game protocol, login or a G-Earth connection. The test '
                   'never uses your stored Habbo passwords or cookies.',
            fg=COMPANION_UI['muted'],bg=COMPANION_UI['background'],justify='left',
            wraplength=590).pack(anchor='w',fill='x',pady=(0,12))
        grid=ttk.Frame(f,style='Panel.TFrame')
        grid.pack(fill='x',pady=(0,10))
        self.headless_table=ttk.Treeview(
            grid,columns=('account','state'),show='headings',height=7)
        self.headless_table.heading('account',text='Saved account profile')
        self.headless_table.column('account',width=175,stretch=False)
        self.headless_table.heading('state',text='Local test socket status')
        self.headless_table.column('state',width=370,stretch=True)
        self.headless_table.pack(fill='x')
        controls=ttk.Frame(f,style='Panel.TFrame')
        controls.pack(fill='x',pady=(0,8))
        ttk.Button(controls,text='Start/reset local test server',
                   command=self._headless_start_test_server).pack(
                       side='left',padx=(0,6))
        ttk.Button(controls,text='Connect all (local test)',
                   command=self._headless_connect_all).pack(
                       side='left')
        actions=ttk.Frame(f,style='Panel.TFrame')
        actions.pack(fill='x',pady=(0,12))
        ttk.Button(actions,text='Ping all test sessions',
                   command=self._headless_ping_all).pack(
                       side='left',padx=(0,6))
        ttk.Button(actions,text='Disconnect all',
                   command=self._headless_disconnect_all).pack(
                       side='left',padx=(0,6))
        ttk.Button(actions,text='Refresh profiles',
                   command=self._headless_render).pack(side='left')
        tk.Label(f,textvariable=self.headless_status_var,
                 fg=COMPANION_UI['success'],bg=COMPANION_UI['background'],wraplength=590,
                 justify='left').pack(anchor='w',fill='x')
        tk.Label(
            f,text='No live account packets are sent by this mode. '
                   'A verified, authorised official game authentication '
                   'and protocol adapter would be required before this '
                   'could replace the normal Habbo login/launcher.',
            fg=COMPANION_UI['muted'],bg=COMPANION_UI['background'],wraplength=590,
            justify='left').pack(anchor='w',pady=(10,0))
        self._headless_render()

    def _headless_render(self):
        table=self.headless_table
        for row in table.get_children():
            table.delete(row)
        for account in self._account_profiles:
            ident=account['id']
            table.insert('', 'end',iid=ident,
                         values=(account['label'],
                                 self._headless_account_states.get(
                                     ident,'Not connected (local test)')))

    def _headless_start_test_server(self):
        accounts=tuple(a['id'] for a in self._account_profiles)
        if not accounts:
            self.headless_status_var.set('Add an account profile first.')
            return
        if len(accounts)>HEADLESS_TEST_MAX_ACCOUNTS:
            self.headless_status_var.set(
                f'Local test supports at most {HEADLESS_TEST_MAX_ACCOUNTS} profiles.')
            return
        self._tcp_disconnect_all()
        self._headless_manager.disconnect_all()
        if self._headless_server is not None:
            self._headless_server.stop()
            self._headless_server=None
        try:
            server=LocalHeadlessTestServer(accounts)
            server.start()
        except (OSError,ValueError,RuntimeError) as exc:
            self.headless_status_var.set('Local test server unavailable: '+
                                         type(exc).__name__)
            return
        self._headless_server=server
        self._headless_account_states={}
        self._headless_render()
        self.headless_status_var.set(
            f'Local test server ready on 127.0.0.1:{server.port}. '
            'No Habbo.com network traffic or credentials used.')

    def _headless_connect_all(self):
        server=self._headless_server
        if server is None or server.port is None:
            self.headless_status_var.set(
                'Start local test server before connecting account profiles.')
            return
        accounts=tuple(a['id'] for a in self._account_profiles)
        if any(a not in server.tickets and
               a not in self._headless_manager.sessions for a in accounts):
            self.headless_status_var.set(
                'Profile list changed or test ticket used. Reset local test server.')
            return
        self.headless_status_var.set(
            f'Connecting {len(accounts)} isolated local test socket(s)...')
        def work():
            try:
                results=self._headless_manager.connect_all(server,accounts)
                for ident,status in results.items():
                    self._packet_put(('headless_state',ident,status))
                success=sum('ping OK' in x for x in results.values())
                self._packet_put(('headless_status',
                    f'{success}/{len(accounts)} local test sockets authenticated '
                    f'and ping-verified. Not connected to Habbo.com.'))
            except (OSError,RuntimeError,ValueError) as exc:
                self._packet_put(('headless_status',
                                  'Local test error: '+type(exc).__name__))
        threading.Thread(target=work,daemon=True,
                         name='headless-test-connect').start()

    def _headless_ping_all(self):
        if not self._headless_manager.sessions:
            self.headless_status_var.set('No connected local test sessions.')
            return
        self.headless_status_var.set('Checking each local test socket...')
        def work():
            results=self._headless_manager.ping_all()
            for ident,status in results.items():
                self._packet_put(('headless_state',ident,status))
            self._packet_put(('headless_status',
                f'Local socket check: {sum("ping OK" in v for v in results.values())}'
                f'/{len(results)} verified; not Habbo.com connections.'))
        threading.Thread(target=work,daemon=True,
                         name='headless-test-ping').start()

    def _headless_disconnect_all(self):
        self._headless_manager.disconnect_all()
        for a in self._account_profiles:
            self._headless_account_states[a['id']]='Disconnected'
        self._headless_render()
        self.headless_status_var.set(
            'All local test sockets disconnected; no Habbo clients affected.')

    def _make_direct_classic_panel(self,parent):
        """Launch locally installed Habbo.exe via short-lived, user-given SSO."""
        f=ttk.Frame(parent,style='Panel.TFrame',padding=16)
        f.pack(fill='both',expand=True)
        tk.Label(f,text='DIRECT CLASSIC LAUNCH',
                 font=('Segoe UI Semibold',18),
                 bg=COMPANION_UI['background'],fg=COMPANION_UI['text']).pack(anchor='w',pady=(0,10))
        tk.Label(
            f,text='Use a Habbo.exe already installed ON YOUR PC and a valid '
                   'Habbo.com SSO launch ticket. No Bobba servers, downloads, '
                   'browser automation, or third-party APIs. The launched '
                   'official game client still connects to Habbo.com. '
                   'This does not generate or renew login tickets.',
            fg=COMPANION_UI['muted'],bg=COMPANION_UI['background'],justify='left',
            wraplength=605).pack(anchor='w',pady=(0,12))
        pathrow=ttk.Frame(f,style='Panel.TFrame')
        pathrow.pack(fill='x',pady=(0,10))
        ttk.Label(pathrow,text='Local Habbo.exe',style='Panel.TLabel',
                  width=16).pack(side='left')
        ttk.Entry(pathrow,textvariable=self.direct_classic_exe_var).pack(
            side='left',fill='x',expand=True,padx=(0,6))
        ttk.Button(pathrow,text='Browse',
                   command=self._direct_choose_executable).pack(side='left')
        self.direct_table=ttk.Treeview(
            f,columns=('profile','ticket_state'),
            show='headings',height=7,selectmode='browse')
        self.direct_table.heading('profile',text='Saved account')
        self.direct_table.heading('ticket_state',text='Ticket / local process')
        self.direct_table.column('profile',width=165,stretch=False)
        self.direct_table.column('ticket_state',width=390,stretch=True)
        self.direct_table.pack(fill='x',pady=(0,10))
        label=ttk.Label(f,text='Paste SSO ticket for the SELECTED account '
                        '(cleared after queueing):',style='Panel.TLabel')
        label.pack(anchor='w',pady=(0,4))
        ttk.Entry(f,textvariable=self.direct_ticket_var,show='*').pack(
            fill='x',pady=(0,8))
        row=ttk.Frame(f,style='Panel.TFrame')
        row.pack(fill='x',pady=(0,8))
        ttk.Button(row,text='Queue ticket locally',
                   command=self._direct_queue_selected).pack(
                       side='left',padx=(0,7))
        ttk.Button(row,text='Fetch from signed-in local session',
                   command=self._direct_fetch_session_ticket).pack(
                       side='left',padx=(0,7))
        ttk.Button(row,text='Clear selected ticket',
                   command=self._direct_clear_selected).pack(side='left')
        row=ttk.Frame(f,style='Panel.TFrame')
        row.pack(fill='x',pady=(0,10))
        ttk.Button(row,text='Launch selected',
                   command=self._direct_launch_selected).pack(
                       side='left',padx=(0,7))
        ttk.Button(row,text='Launch all queued',
                   command=self._direct_launch_all).pack(
                       side='left',padx=(0,7))
        ttk.Button(row,text='Refresh profiles',
                   command=self._direct_render).pack(side='left')
        tk.Label(f,textvariable=self.direct_status_var,
                 bg=COMPANION_UI['background'],fg=COMPANION_UI['success'],wraplength=600,
                 justify='left').pack(anchor='w',pady=(0,12))
        tk.Label(f,text='Fetch from signed-in local session uses the '
                 'already-running dedicated account browser profile to ask '
                 'Habbo.com for a ticket, without opening windows or copying '
                 'codes. It cannot sign in from email/password or replace an '
                 'expired website session. The official ticket endpoint may '
                 'change or reject the request.',
                 bg=COMPANION_UI['background'],fg=COMPANION_UI['muted'],wraplength=600,
                 justify='left').pack(anchor='w',pady=(0,10))
        tk.Label(f,text='Important: A ticket comes from the official Habbo '
                 'login flow and may expire. Valid format does not mean a '
                 'valid login. Tickets remain in RAM only, but Windows '
                 'process arguments can be inspected by other local programs. '
                 'A started Habbo.exe is not proof an avatar logged in. '
                 'Per-account AIR storage and multi-client G-Earth routing '
                 'are NOT implemented by this direct-launch option.',
                 bg=COMPANION_UI['background'],fg=COMPANION_UI['muted'],wraplength=600,
                 justify='left').pack(anchor='w')
        self._direct_render()

    def _direct_render(self):
        table=self.direct_table
        selection=table.selection()
        selected=selection[0] if selection else None
        for item in table.get_children():
            table.delete(item)
        active_ids={a['id'] for a in self._account_profiles}
        # No secret from a removed profile is retained.
        for account_id in tuple(self._direct_ticket_queue):
            if account_id not in active_ids:
                self._direct_ticket_queue.pop(account_id,None)
        for item in self._account_profiles:
            account_id=item['id']
            state=('Ticket queued (RAM only)'
                   if account_id in self._direct_ticket_queue
                   else self._direct_launch_states.get(account_id,'No ticket queued'))
            table.insert('', 'end',iid=account_id,
                         values=(item['label'],state))
        if selected and table.exists(selected):
            table.selection_set(selected)
        elif self._account_profiles:
            table.selection_set(self._account_profiles[0]['id'])

    def _direct_selected_profile(self):
        sel=self.direct_table.selection()
        if not sel:
            self.direct_status_var.set('Select an account profile first.')
            return None
        return next((a for a in self._account_profiles if a['id']==sel[0]),None)

    def _direct_choose_executable(self):
        path=filedialog.askopenfilename(
            parent=self.root,title='Choose a local Habbo.exe',
            filetypes=[('Habbo executable','Habbo.exe'),('Executables','*.exe')])
        if not path:
            return
        try:
            exe=official_local_executable(path)
        except ValueError as exc:
            self.direct_status_var.set(str(exc))
            return
        self.direct_classic_exe_var.set(str(exe))
        self.config['direct_classic_executable']=str(exe)
        self.save()
        self.direct_status_var.set(
            'Selected local Habbo.exe. This does not install or contact '
            'any third-party software.')

    def _direct_queue_selected(self):
        account=self._direct_selected_profile()
        value=self.direct_ticket_var.get()
        self.direct_ticket_var.set('')
        if account is None:
            return
        try:
            ticket=parse_classic_ticket(value)
            if any(p.secret==ticket.secret and ident!=account['id']
                   for ident,p in self._direct_ticket_queue.items()):
                raise ValueError(
                    'This same login ticket is already queued for another account.')
        except (ValueError,TypeError) as exc:
            self.direct_status_var.set('Ticket not queued: '+str(exc)[:155])
            return
        self._direct_ticket_queue[account['id']]=ticket
        self._direct_launch_states.pop(account['id'],None)
        self._direct_render()
        label=(' Username suffix: '+ticket.username+'.'
               if ticket.username else ' Username not included; confirm '
               'the ticket belongs to this account.')
        self.direct_status_var.set(
            f'{account["label"]}: hhus ticket queued in RAM only.'+label)

    def _direct_fetch_session_ticket(self):
        """Try the official API using a running LOCAL authenticated profile."""
        account=self._direct_selected_profile()
        if account is None:
            return
        if self._direct_ticket_fetch_running:
            self.direct_status_var.set(
                'A local ticket request is already in progress.')
            return
        if any(account_browser_debug_port(account['id'])==
               account_browser_debug_port(other['id'])
               for other in self._account_profiles
               if other['id']!=account['id']):
            self.direct_status_var.set(
                'Two account profiles have the same browser control port. '
                'No request was sent.')
            return
        self._direct_ticket_fetch_running=True
        self.direct_status_var.set(
            f'{account["label"]}: checking existing local Habbo session. '
            'No windows will be opened; no passwords are transmitted by Companion.')
        def work(account_id,label):
            try:
                ticket=account_fetch_ticket_from_signed_in_profile(
                    account_browser_debug_port(account_id))
                self._packet_put(('direct_ticket_fetched',account_id,ticket))
            except (OSError,RuntimeError,ValueError,socket.timeout,
                    TimeoutError) as exc:
                # Do not print exception details that might include tokens.
                message=(str(exc)[:175] if isinstance(exc,ValueError)
                         else 'Local browser connection unavailable ('+
                         type(exc).__name__+').')
                self._packet_put(('direct_ticket_fetch_failed',
                                  account_id,message))
        threading.Thread(target=work,
                         args=(account['id'],account['label']),
                         daemon=True,name='local-habbo-session-ticket').start()

    def _direct_clear_selected(self):
        account=self._direct_selected_profile()
        self.direct_ticket_var.set('')
        if account is None:
            return
        self._direct_ticket_queue.pop(account['id'],None)
        self._direct_render()
        self.direct_status_var.set(
            f'{account["label"]}: pending local ticket cleared.')

    def _direct_launch_selected(self):
        account=self._direct_selected_profile()
        if account is None:
            return
        self._direct_launch_profiles((account,))

    def _direct_launch_all(self):
        accounts=tuple(a for a in self._account_profiles
                       if a['id'] in self._direct_ticket_queue)
        if not accounts:
            self.direct_status_var.set(
                'Queue a separate valid SSO ticket for each account first.')
            return
        self._direct_launch_profiles(accounts)

    def _direct_launch_profiles(self,accounts):
        if self._direct_launch_running:
            self.direct_status_var.set('A direct launch batch is already running.')
            return
        try:
            exe=official_local_executable(self.direct_classic_exe_var.get())
        except ValueError as exc:
            self.direct_status_var.set('Local executable: '+str(exc)[:160])
            return
        queued=[(a['id'],a['label'],self._direct_ticket_queue[a['id']])
                for a in accounts if a['id'] in self._direct_ticket_queue]
        if not queued:
            self.direct_status_var.set(
                'No ticket queued for the selected account.')
            return
        # Consume tickets BEFORE spawning; never save, log or replay them.
        for ident,_,_ in queued:
            self._direct_ticket_queue.pop(ident,None)
            self._direct_launch_states[ident]='Starting local Habbo.exe'
        self.config['direct_classic_executable']=str(exe)
        self.save()
        self._direct_launch_running=True
        self._direct_render()
        self.direct_status_var.set(
            f'Starting {len(queued)} local Classic process(es). '
            'No Bobba services; login not verified.')
        threading.Thread(
            target=self._direct_launch_worker,
            args=(exe,tuple(queued)),daemon=True,
            name='companion-local-classic-launch').start()

    def _direct_launch_worker(self,exe,queued):
        for i,(ident,label,ticket) in enumerate(queued,1):
            try:
                pid=launch_local_classic(exe,ticket)
                message=f'Local Habbo.exe started (PID {pid}); login unverified'
            except (OSError,ValueError,subprocess.SubprocessError) as exc:
                message='Local launch failed: '+type(exc).__name__
            self._packet_put(('direct_launch_state',ident,message))
            self._packet_put(('direct_launch_status',
                f'{i}/{len(queued)} {label}: {message}. '
                'G-Earth account routing is separate.'))
            if i<len(queued):
                time.sleep(1.0)
        self._packet_put(('direct_launch_finished',))

    def _make_accounts_panel(self,parent):
        """Compact profile list + grouped account settings, all handlers intact."""
        p=COMPANION_UI
        f=ttk.Frame(parent,style='Panel.TFrame',padding=(22,19))
        f.pack(fill='both',expand=True)
        tk.Label(f,text='Manage your accounts',
                 font=('Segoe UI Semibold',18),bg=p['background'],
                 fg=p['text']).pack(anchor='w',pady=(0,3))
        tk.Label(f,text='Each account has its own private Brave session. '
                 'Choose a profile to edit it or open its official Habbo login.',
                 font=('Segoe UI',10),bg=p['background'],fg=p['muted'],
                 wraplength=790,justify='left').pack(
                     anchor='w',pady=(0,18))
        columns=ttk.Frame(f,style='Panel.TFrame')
        columns.pack(fill='both',expand=True)

        # LEFT — profile selection and lifecycle.
        left=ttk.Frame(columns,style='Card.TFrame',padding=15,width=316)
        left.pack(side='left',fill='y',padx=(0,15))
        left.pack_propagate(False)
        tk.Label(left,text='SAVED PROFILES',
                 font=('Segoe UI Semibold',9),
                 fg=p['accent'],bg=p['surface']).pack(
                     anchor='w',pady=(2,9))
        self.account_table=ttk.Treeview(
            left,columns=('name','port','launch_state'),
            show='headings',height=10,selectmode='browse')
        for key,heading,width in (
            ('name','Account',117),
            ('port','Port',48),
            ('launch_state','Status',120)):
            self.account_table.heading(key,text=heading)
            self.account_table.column(key,width=width,stretch=False)
        self.account_table.pack(fill='x',pady=(0,12))
        self.account_table.bind('<<TreeviewSelect>>',self._account_on_select)
        actions=ttk.Frame(left,style='Card.TFrame')
        actions.pack(fill='x',pady=(0,8))
        ttk.Button(actions,text='Add account',style='Primary.TButton',
                   command=self._account_add).pack(
                       side='left',padx=(0,7))
        ttk.Button(actions,text='Remove entry',style='Danger.TButton',
                   command=self._account_remove).pack(side='left')
        tk.Frame(left,bg=p['border'],height=1).pack(fill='x',pady=(10,12))
        tk.Label(left,text='PROFILES STAY SEPARATE',
                 font=('Segoe UI Semibold',9),
                 fg=p['muted'],bg=p['surface']).pack(anchor='w')
        tk.Label(left,text='Each account retains its own browser cookies, '
                 'trusted-device settings and local control port.',
                 font=('Segoe UI',9),fg=p['muted'],bg=p['surface'],
                 wraplength=277,justify='left').pack(
                     anchor='w',pady=(6,0))

        # RIGHT — profile details, login, and separate advanced controls.
        right=ttk.Frame(columns,style='Card.TFrame',padding=(20,19))
        right.pack(side='left',fill='both',expand=True)
        tk.Label(right,text='Account settings',
                 font=('Segoe UI Semibold',16),
                 fg=p['text'],bg=p['surface']).pack(anchor='w')
        tk.Label(right,text='Edit the selected account',
                 font=('Segoe UI',9),
                 fg=p['muted'],bg=p['surface']).pack(
                     anchor='w',pady=(2,14))

        def field(parent,label,var,row,column=0,span=1,secret=False):
            ttk.Label(parent,text=label,style='Card.TLabel').grid(
                row=row*2,column=column,columnspan=span,
                sticky='w',padx=(0,12),pady=(6,4))
            entry=ttk.Entry(parent,textvariable=var,
                            show='*' if secret else '')
            entry.grid(row=row*2+1,column=column,columnspan=span,
                       sticky='ew',padx=(0,12),pady=(0,8))
            return entry

        basics=ttk.Frame(right,style='Card.TFrame')
        basics.pack(fill='x')
        basics.columnconfigure(0,weight=2)
        basics.columnconfigure(1,weight=1)
        field(basics,'Account label',self.account_label_var,0)
        field(basics,'G-Earth extension port',self.account_port_var,0,1)
        field(basics,'Login website (HTTPS)',self.account_login_url_var,1,
              span=2)
        save_line=ttk.Frame(right,style='Card.TFrame')
        save_line.pack(fill='x',pady=(5,4))
        ttk.Button(save_line,text='Save changes',
                   command=self._account_save_selected).pack(side='left')
        ttk.Button(save_line,text='Use selected G-Earth port',
                   command=self._account_use_port).pack(
                       side='left',padx=(9,0))
        ttk.Button(save_line,text='Check port',
                   command=self._account_check_port).pack(
                       side='left',padx=(9,0))

        tk.Frame(right,bg=p['border'],height=1).pack(
            fill='x',pady=(15,14))
        tk.Label(right,text='LOGIN & SECURITY',
                 font=('Segoe UI Semibold',9),
                 fg=p['accent'],bg=p['surface']).pack(
                     anchor='w',pady=(0,6))
        security=ttk.Frame(right,style='Card.TFrame')
        security.pack(fill='x')
        security.columnconfigure(0,weight=1)
        security.columnconfigure(1,weight=1)
        field(security,'Login email',self.account_email_var,0)
        field(security,'Login password',self.account_password_var,0,1,
              secret=True)
        secrets_row=ttk.Frame(right,style='Card.TFrame')
        secrets_row.pack(fill='x',pady=(5,8))
        ttk.Button(secrets_row,text='Save login securely',
                   command=self._account_save_login).pack(
                       side='left',padx=(0,9))
        ttk.Button(secrets_row,text='Forget saved login',
                   command=self._account_forget_login).pack(side='left')
        ttk.Button(right,text='Open account login',
                   style='Primary.TButton',
                   command=self._account_open_login).pack(
                       anchor='w',pady=(3,7))
        tk.Label(right,text='Passwords stay in Windows Credential Manager, '
                 'not settings.json or GitHub. First-time CAPTCHA or email '
                 'verification is completed on Habbo, not in Companion.',
                 font=('Segoe UI',9),bg=p['surface'],fg=p['muted'],
                 wraplength=520,justify='left').pack(
                     anchor='w',pady=(5,0))

        tk.Frame(right,bg=p['border'],height=1).pack(
            fill='x',pady=(17,14))
        tk.Label(right,text='LAUNCH & AUTOMATION',
                 font=('Segoe UI Semibold',9),
                 fg=p['accent'],bg=p['surface']).pack(
                     anchor='w',pady=(0,8))
        autoplay=ttk.Frame(right,style='Card.TFrame')
        autoplay.pack(fill='x',pady=(0,7))
        ttk.Button(autoplay,text='Auto Play selected',
                   command=self._account_auto_play).pack(
                       side='left',padx=(0,9))
        ttk.Button(autoplay,text='Auto Play all saved accounts',
                   command=lambda:self._account_auto_play(
                       all_accounts=True)).pack(side='left')
        ttk.Button(right,text='Continue unfinished accounts',
                   command=self._account_resume_pending).pack(
                       anchor='w',pady=(0,11))
        tk.Label(right,textvariable=self.account_status_var,
                 bg=p['surface'],fg=p['success'],
                 wraplength=520,justify='left',
                 font=('Segoe UI',9)).pack(
                     anchor='w',fill='x',pady=(2,9))
        tk.Label(right,text='Auto Play launches Classic accounts sequentially '
                 'when native launcher interaction is required. '
                 'One G-Earth packet endpoint can be attached at a time; '
                 'multiple endpoints need separate configured proxies. '
                 'G-Earth routing to multiple game clients is NOT yet implemented.',
                 font=('Segoe UI',9),fg=p['muted'],bg=p['surface'],
                 wraplength=520,justify='left').pack(anchor='w')
        self._accounts_render()

    def _accounts_render(self,select_id=None):
        table=self.account_table
        if select_id is None:
            row=table.selection()
            select_id=row[0] if row else None
        for row in table.get_children():
            table.delete(row)
        for item in self._account_profiles:
            name=item['label']+(' (active)' if item['id']==self._account_active_id else '')
            table.insert('', 'end',iid=item['id'],
                         values=(name,item['port'],
                                  self._account_run_states.get(item['id'],'Not started')))
        if not select_id and self._account_profiles:
            select_id=self._account_profiles[0]['id']
        if select_id and table.exists(select_id):
            table.selection_set(select_id)
            table.focus(select_id)

    def _account_selected(self):
        selection=self.account_table.selection()
        if not selection:
            self.account_status_var.set('Select an account first.')
            return None
        return next((a for a in self._account_profiles if a['id']==selection[0]),None)

    def _account_on_select(self,event=None):
        account=self._account_selected()
        if account is None:return
        self.account_label_var.set(account['label'])
        self.account_login_url_var.set(account['url'])
        self.account_port_var.set(str(account['port']))
        self.account_password_var.set('')
        try:
            saved=account_saved_login_read(account['id'])
        except (OSError,ValueError):
            saved=None
        self.account_email_var.set(saved[0] if saved else '')
        self.account_status_var.set(
            f'Selected {account["label"]} — G-Earth extension {account["port"]}. '
            + ('Saved login available: Open account login signs in for you.'
               if saved else 'Enter email/password and click Save login securely.'))

    def _account_add(self):
        if len(self._account_profiles)>=12:
            self.account_status_var.set('Maximum 12 account profiles.')
            return
        used={a['port'] for a in self._account_profiles}
        try:base=int(self.gearth_port_var.get()) if not used else 9092
        except (ValueError,TypeError):base=9092
        port=next((p for p in [base,*range(9092,9110)] if 1024<=p<=65535
                   and p not in used),None)
        if port is None:
            self.account_status_var.set('No free extension port in the preset range.')
            return
        ident=uuid.uuid4().hex[:12]
        account={'id':ident,'label':f'Account {len(self._account_profiles)+1}',
                 'url':'https://www.habbo.com/','port':port}
        self._account_profiles.append(account)
        self.config['account_profiles']=self._account_profiles
        self.save()
        self._accounts_render(ident)
        self._account_on_select()
        self.account_status_var.set(
            f'Added {account["label"]}. Use Open account login to sign in.')

    def _account_save_selected(self):
        account=self._account_selected()
        if account is None:return
        label=self.account_label_var.get().strip()
        try:
            url=validate_habbo_login_url(self.account_login_url_var.get())
            port=int(self.account_port_var.get().strip())
            if not 1<=len(label)<=50 or any(ord(c)<32 for c in label):
                raise ValueError('Account label must be 1–50 printable characters.')
            if not 1024<=port<=65535:
                raise ValueError('Extension port must be between 1024 and 65535.')
            if any(x['port']==port and x['id']!=account['id']
                   for x in self._account_profiles):
                raise ValueError('Every account must have a different extension port.')
            if (account['id']==self._account_active_id
                and self.packet_started and self._account_attached_port!=port):
                raise ValueError('Cannot change the attached G-Earth port. '
                                 'Stop packet tools and restart Companion first.')
        except (ValueError,TypeError,OverflowError) as exc:
            self.account_status_var.set('Not saved: '+str(exc)[:170]);return
        account.update(label=label,url=url,port=port)
        self.config['account_profiles']=self._account_profiles
        self.save()
        self._accounts_render(account['id'])
        self.account_status_var.set(
            f'Saved {label} (port {port}). Login passwords are stored '
            'separately in Windows Credential Manager when you choose to save.')

    def _account_save_login(self):
        account=self._account_selected()
        if account is None:return
        try:
            account_saved_login_write(
                account['id'],self.account_email_var.get(),
                self.account_password_var.get())
        except (OSError,ValueError) as exc:
            self.account_status_var.set('Login not saved: '+str(exc)[:160])
            return
        self.account_password_var.set('')
        self.account_status_var.set(
            f'{account["label"]}: login saved in Windows Credential Manager. '
            'Open account login will now sign in automatically.')

    def _account_forget_login(self):
        account=self._account_selected()
        if account is None:return
        try:
            account_saved_login_delete(account['id'])
        except OSError as exc:
            self.account_status_var.set('Could not forget login: '+str(exc)[:160])
            return
        self.account_password_var.set('')
        self.account_status_var.set(
            f'{account["label"]}: saved password deleted from Windows vault. '
            'Its browser cookies are separate and may still be signed in.')

    def _account_remove(self):
        account=self._account_selected()
        if account is None:return
        if account['id']==self._account_active_id and self.packet_started:
            self.account_status_var.set(
                'Cannot remove the active attached account; restart Companion first.')
            return
        if not messagebox.askyesno('Remove account entry',
            f'Remove {account["label"]} from Companion? '
            'Browser login data on disk will NOT be deleted.',
            parent=self.root):
            return
        try:
            account_saved_login_delete(account['id'])
        except OSError as exc:
            self.account_status_var.set(
                'Could not remove saved login: '+str(exc)[:160])
            return
        try:
            account_session_cookie_delete(account['id'])
        except OSError:
            self.account_status_var.set('Could not erase saved website session.')
            return
        self._tcp_disconnect_one(account['id'])
        self._account_profiles=[x for x in self._account_profiles
                                if x['id']!=account['id']]
        if self._account_active_id==account['id']:
            self._account_active_id=''
        self.config.update(account_profiles=self._account_profiles,
                           account_active_id=self._account_active_id)
        self.save()
        self._accounts_render()
        self.account_status_var.set(
            'Account entry removed. Its isolated browser data remains on disk.')

    def _account_open_login(self):
        """Open just this browser profile and sign it in using the local vault."""
        self._account_auto_play(login_only=True)

    def _account_resume_pending(self):
        """Retry only account IDs not yet sent to the native Classic launcher."""
        if self._account_auto_running:
            self.account_status_var.set(
                'An account launch is still running; finish it before continuing.')
            return
        if not self._account_remaining_ids:
            self.account_status_var.set(
                'No unfinished accounts are queued. Use Auto Play all to '
                'start a fresh batch, or select one account to retry.')
            return
        if self._account_resume_requires_manual:
            if not messagebox.askyesno(
                'Continue remaining accounts',
                'A previous account reached the Habbo Launcher, but Companion '
                'could not confirm Classic was selected. Finish that launcher '
                'or its browser permission prompt before proceeding. '
                'Have you completed that manual step?',
                parent=self.root):
                return
        self._account_auto_play(remaining_only=True)

    def _account_auto_play(self,all_accounts=False,login_only=False,
                           remaining_only=False):
        """Open selected, all or only unfinished browser/Classic profiles."""
        if self._account_auto_running:
            self.account_status_var.set(
                'Account launch already in progress. Finish it first.')
            return
        if remaining_only:
            keep=set(self._account_remaining_ids)
            accounts=[a for a in self._account_profiles if a['id'] in keep]
        elif all_accounts:
            accounts=list(self._account_profiles)
        else:
            selected=self._account_selected()
            if selected is None:return
            accounts=[selected]
        if not accounts:
            self.account_status_var.set('Add at least one account first.')
            return
        # Browser login/Classic launching is independent of the packet engine.
        # Never block launching an Alt just because Main is attached to G-Earth.
        # Equally, never switch or attribute the active packet feed to the Alt.
        active_packet_port=(self._account_attached_port
                            if self.packet_started else None)
        if len({account_browser_debug_port(a['id']) for a in accounts})!=len(accounts):
            self.account_status_var.set(
                'Two account profiles share a browser control port. '
                'Remove/re-add one profile before automation.')
            return
        if not login_only and not self.packet_started and not all_accounts and not remaining_only:
            self._account_use_port()
            if (accounts[0]['port']==9092
                and not self._gearth_extension_port_responds(9092)):
                self._start_integrated_engine()
        if not login_only:
            self._account_remaining_ids=()
            self._account_resume_requires_manual=False
        self._account_auto_running=True
        self._account_auto_generation+=1
        generation=self._account_auto_generation
        packet_note=(
            f' Packet feed remains on G-Earth port {active_packet_port}; '
            'launching another account does NOT intercept its packets.'
            if active_packet_port is not None and
            any(a['port']!=active_packet_port for a in accounts)
            else '')
        for account in accounts:
            self._account_run_states[account['id']]='Queued'
        self._accounts_render()
        self.account_status_var.set(
            f'Starting all {len(accounts)} browser profile(s) before sign-in.'
            +packet_note)
        threading.Thread(
            target=self._account_auto_worker,
            args=(tuple(dict(a) for a in accounts),generation,login_only,
                  packet_note),
            daemon=True).start()

    def _account_auto_worker(self,accounts,generation,login_only=False,
                             packet_note=''):
        """Prepare ALL account browser logins before launching any native client.

        A failed profile must not prevent the other independent browser logins.
        Native launches remain sequential to avoid mixing launcher tickets.
        """
        def report(value):
            self._packet_put(('account_auto_status',generation,
                              (str(value)+packet_note)[:650]))

        def queue_unfinished(attempted_ids,manual_step=False):
            # No profile passwords, authentication cookies or launcher tickets
            # are persisted in the resume queue. Only existing opaque IDs.
            remainder=tuple(a['id'] for a in accounts
                            if a['id'] not in attempted_ids)
            self._packet_put(('account_remaining',generation,remainder,
                              bool(manual_step)))
            return remainder

        def stage(account,value):
            self._packet_put(('account_auto_stage',generation,
                              account['id'],str(value)[:95]))

        prelaunched=set()
        def ready_browser(account,browser):
            ident=account['id']
            folder=APP_DIR/'account_browser_profiles'/ident
            debug_port=account_browser_debug_port(ident)
            folder.mkdir(parents=True,exist_ok=True)
            try:
                account_browser_pages(debug_port)
                return debug_port
            except (OSError,ValueError,TimeoutError,
                    urllib.error.URLError,UnicodeError):
                pass
            # Avoid opening a duplicate tab/window for a profile that was
            # already started during the batch browser-open phase.
            if ident not in prelaunched:
                cmd=account_browser_command(browser,folder,account['url'],debug_port)
                subprocess.Popen(cmd,cwd=str(browser.parent),
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            for _ in range(28):
                time.sleep(0.45)
                try:
                    account_browser_pages(debug_port)
                    return debug_port
                except (OSError,ValueError,TimeoutError,
                        urllib.error.URLError,UnicodeError):
                    continue
            return None

        try:
            browser=account_login_browser()
            if browser is None:
                report('Brave/Chrome/Edge not found; install one first.')
                return
            authenticated=[]
            failures=[]
            total=len(accounts)
            # Phase 1: start ALL separate browsers immediately. The previous
            # loop did not open Alt until Main finished all login polling.
            for n,account in enumerate(accounts,1):
                label=account['label']
                stage(account,'Opening browser')
                report(f'Opening browser {n}/{total}: {label}...')
                try:
                    ident=account['id']
                    folder=APP_DIR/'account_browser_profiles'/ident
                    folder.mkdir(parents=True,exist_ok=True)
                    port=account_browser_debug_port(ident)
                    try:
                        account_browser_pages(port)
                        stage(account,'Browser already open')
                        report(f'{label}: its existing isolated browser is open.')
                        continue
                    except (OSError,ValueError,TimeoutError,
                            urllib.error.URLError,UnicodeError):
                        pass
                    cmd=account_browser_command(browser,folder,account['url'],port)
                    subprocess.Popen(cmd,cwd=str(browser.parent),
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                    prelaunched.add(ident)
                    stage(account,'Browser starting')
                    report(f'{label}: separate browser launch requested.')
                except (OSError,ValueError,TimeoutError) as exc:
                    failures.append(label)
                    stage(account,'Browser launch failed')
                    report(f'{label}: browser launch error '
                           f'({type(exc).__name__}); trying other accounts.')
            report(f'Browser launch phase finished ({total} profiles considered). '
                   'Checking sign-ins one by one next.')
            # Phase 2: wait for each browser and authenticate. Every other
            # separate browser was already requested before this potentially
            # long per-account stage begins.
            for n,account in enumerate(accounts,1):
                label=account['label']
                if label in failures:
                    continue
                stage(account,'Checking website login')
                report(f'{n}/{total}: checking {label} browser login...')
                try:
                    debug_port=ready_browser(account,browser)
                except (OSError,ValueError,TimeoutError) as exc:
                    report(f'{label}: could not open browser: '+str(exc)[:130])
                    failures.append(label)
                    stage(account,'Browser automation unavailable')
                    continue
                if debug_port is None:
                    report(f'{label}: browser opened, but local browser control '
                           'is unavailable. Close old dedicated account windows '
                           'and retry; other accounts will still be checked.')
                    failures.append(label)
                    stage(account,'Browser control unavailable')
                    continue
                try:
                    credentials=account_saved_login_read(account['id'])
                except (OSError,ValueError) as exc:
                    report(f'{label}: saved login unavailable: '+str(exc)[:130])
                    failures.append(label)
                    stage(account,'Saved login unavailable')
                    continue
                issue_messages=[]
                def relay_signin(msg,name=label):
                    issue_messages.append(str(msg)[:190])
                    report(f'{name}: {str(msg)[:190]}')
                result=account_attempt_auto_play(
                    debug_port,relay_signin,
                    credentials=credentials,login_only=True)
                if result=='signed_in':
                    authenticated.append((account,debug_port,credentials))
                    stage(account,'Website signed in')
                    report(f'{n}/{total}: {label} website login ready.')
                else:
                    failures.append(label)
                    reason={
                        'control_error':'Browser control endpoint failed',
                        'inspect_error':'Browser inspection failed',
                        'no_habbo_tab':'No Habbo tab in profile',
                        'waiting':'Website controls unrecognised',
                        'login':'Sign-in / verification required'
                    }.get(result,'Login not confirmed ('+str(result)+')')
                    # Keep the low-level failure reason visible for this
                    # specific profile even after the global batch message
                    # changes. Never include credentials or cookie contents.
                    detail=(issue_messages[-1][:93]
                            if issue_messages and result in
                            ('control_error','inspect_error','no_habbo_tab')
                            else reason)
                    stage(account,detail)
                    report(f'{n}/{total}: {label}: {reason}; '
                           'checking remaining accounts.')
            if login_only:
                report(f'Browser sign-in complete: {len(authenticated)}/{total} '
                       f'ready. {len(failures)} need attention.')
                return
            if not authenticated:
                if not login_only:
                    queue_unfinished(set())
                report('No website logins confirmed. Check each account status '
                       '(e.g. sign-in/verification, or browser control), then '
                       'select Continue unfinished accounts.')
                return

            # Phase 3: launch Classic, but never allow an unresolved native
            # launcher window to consume a different account's login ticket.
            attempted=0
            attempted_ids=set()
            classic_selected=0
            unresolved=False
            for n,(account,debug_port,credentials) in enumerate(authenticated,1):
                label=account['label']
                stage(account,'Requesting Classic launch')
                report(f'{n}/{len(authenticated)}: launching {label} Classic...')
                # Snapshot BEFORE the website Launch click. The AIR client
                # sometimes opens directly, bypassing the Launcher Classic
                # button. Never count a pre-existing game client as new.
                native_before=account_native_client_windows()
                result=account_attempt_auto_play(
                    debug_port,
                    lambda msg,name=label:report(f'{name}: {msg}'),
                    credentials=credentials,login_only=False)
                if result!='launched':
                    report(f'{label}: Classic launch not requested ({result}); '
                           'checking remaining accounts.')
                    failures.append(label)
                    stage(account,'Classic launch blocked ('+str(result)+')')
                    continue
                attempted+=1
                attempted_ids.add(account['id'])
                report(f'{label}: website launch requested; checking '
                       'for the native Classic button...')
                stage(account,'Checking native game / Classic launcher')
                # First check whether the direct HabboAirPlus window opened.
                # On some setups the launch URL starts the game immediately
                # and there is no visible Classic button to select.
                if account_wait_for_new_native_window(native_before,2.5):
                    stage(account,'New HabboAir window (account unverified)')
                    report(f'{label}: new native HabboAir window appeared. '
                           'Continuing to next profile; avatar and G-Earth '
                           'interception are NOT verified.')
                elif account_select_classic_launcher(16):
                    classic_selected+=1
                    stage(account,'Classic selected; client unverified')
                    report(f'{label}: Classic selected. G-Earth proxy '
                           'interception has NOT been verified for this avatar.')
                elif account_wait_for_new_native_window(native_before,0.8):
                    # Native game may appear during the Classic-selection
                    # wait. It is still safe to distinguish it from a game
                    # window that existed before this account's request.
                    stage(account,'New HabboAir window (account unverified)')
                    report(f'{label}: native HabboAir opened while checking '
                           'Classic. Continuing to next account.')
                else:
                    unresolved=True
                    stage(account,'Needs manual Classic / permission')
                    for future,_,_ in authenticated[n:]:
                        stage(future,'Waiting: previous launcher unresolved')
                    report(f'{label}: launcher requires manual Classic selection '
                           'or a browser permission prompt. Pausing remaining '
                           'native launches to avoid mixing account login tickets. '
                           'All independent browser logins were checked.')
                    break
            unfinished=queue_unfinished(attempted_ids,unresolved)
            report(f'Batch: {len(authenticated)}/{total} website logins; '
                   f'{attempted} native launch request(s); '
                   f'{classic_selected} Classic selection(s); '
                   f'{len(unfinished)} unfinished. '
                   + ('Finish the outstanding launcher/permission prompt, '
                      'then click Continue unfinished accounts. '
                      if unresolved and unfinished else
                      ('Complete missing sign-ins, then click Continue '
                       'unfinished accounts. ' if unfinished else ''))
                   + 'No multi-account G-Earth packet routing yet.')
        except Exception as exc:
            report('Auto Play stopped: '+type(exc).__name__+': '+str(exc)[:150])
        finally:
            self._packet_put(('account_auto_finished',generation))

    def _account_use_port(self):
        account=self._account_selected()
        if account is None:return
        port=account['port']
        if self.packet_started:
            if self._account_attached_port!=port:
                self.account_status_var.set(
                    f'Packet tools are attached on port {self._account_attached_port}. '
                    'Switching accounts now could mix packet sessions. '
                    'Restart Companion, then select this account before attaching.')
                return
            self.account_status_var.set(
                f'Already attached to port {port}. '
                'The current avatar identity still needs server confirmation.')
            return
        self._account_active_id=account['id']
        self.config['account_active_id']=account['id']
        self.gearth_port_var.set(str(port))
        self.config['gearth_port']=port
        self.save()
        self._accounts_render(account['id'])
        self.account_status_var.set(
            f'Active endpoint: {account["label"]}, port {port}. '
            'Make sure a SEPARATE G-Earth proxy listens there before connecting. '
            'An open extension port alone cannot verify which Habbo account owns it.')

    def _account_check_port(self):
        account=self._account_selected()
        if account is None:return
        online=self._gearth_extension_port_responds(account['port'])
        self.account_status_var.set(
            f'{account["label"]}: 127.0.0.1:{account["port"]} is '
            +('listening (not an authenticated avatar check).'
              if online else 'not listening. Configure/start its own G-Earth endpoint.'))

    def _make_updates_panel(self, parent):
        """One-click updates without replacing files by hand."""
        f=ttk.Frame(parent,style='Panel.TFrame',padding=18)
        f.pack(fill='both',expand=True)
        tk.Label(f,text='SOFTWARE UPDATES',font=('Segoe UI Semibold',18),
                 fg=COMPANION_UI['text'],bg=COMPANION_UI['background']).pack(anchor='w')
        root_dir=Path(__file__).resolve().parent
        self.update_installed_dir=root_dir
        try:
            info=json.loads((root_dir/'app_manifest.json').read_text(encoding='utf-8'))
            self.current_app_version=str(info['version'])
        except (OSError,ValueError,KeyError):
            self.current_app_version='unknown'
        ttk.Label(f,text=f'Installed version: {self.current_app_version}',style='Panel.TLabel').pack(anchor='w',pady=(12,4))
        ttk.Label(f,text='Your chat settings and G-Earth beta path stay in AppData. Updates do not replace your HabboAir.swf.',
                  style='Panel.TLabel',wraplength=510).pack(anchor='w',pady=(0,14))
        ttk.Button(f,text='Install update ZIP…',command=self._choose_update_zip).pack(anchor='w',pady=(2,8))
        ttk.Label(f,text='Select a Habbo Companion update ZIP from a source you trust. The app backs up the prior version and restarts.',
                  style='Panel.TLabel',wraplength=510).pack(anchor='w',pady=(0,16))
        ttk.Label(f,text='Online update manifest URL (optional)',style='Panel.TLabel').pack(anchor='w')
        ttk.Entry(f,textvariable=self.update_manifest_var,width=65).pack(fill='x',pady=(4,6))
        bar=ttk.Frame(f,style='Panel.TFrame');bar.pack(fill='x',pady=(0,14))
        ttk.Button(bar,text='Save source',command=self._save_update_source).pack(side='left',padx=(0,7))
        ttk.Button(bar,text='Check online',style='Primary.TButton',
                   command=self._check_online_update).pack(side='left')
        ttk.Label(f,text='Online updates are inactive until you enter a trusted HTTPS release-manifest URL. Updates are never installed silently.',
                  style='Panel.TLabel',wraplength=510).pack(anchor='w',pady=(0,14))
        ttk.Label(f,textvariable=self.update_status,style='Panel.TLabel',wraplength=510).pack(anchor='w',fill='x',pady=(0,10))
        ttk.Button(f,text='Restore previous version…',command=self._restore_previous_version).pack(anchor='w',pady=(2,8))
        ttk.Button(f,text='Open backups folder',command=self._open_backups).pack(anchor='w',pady=(2,10))
        ttk.Label(f,text='The updater verifies package file hashes and creates a rollback backup. Checksums detect accidental changes, not publisher identity: only install ZIPs you trust.',
                  style='Panel.TLabel',wraplength=510).pack(anchor='w')

    def _save_update_source(self):
        source=self.update_manifest_var.get().strip()
        if source:
            try:
                self._update_module().validate_official_release_url(
                    source,'manifest')
            except (ValueError,FileNotFoundError) as exc:
                messagebox.showerror('Update source',
                    str(exc)+'\n\nFor other sources, use Install update ZIP '
                    'and explicitly confirm the publisher.')
                return
        self.config['update_manifest_url']=source
        self.save()
        self.update_status.set('Update source saved.' if source else 'Online updates disabled; local update ZIPs still work.')

    def _update_module(self):
        helper=Path(__file__).resolve().parent/'Habbo_Update_Helper.py'
        if not helper.is_file():
            raise FileNotFoundError('Habbo_Update_Helper.py is missing. Re-run the one-click installer.')
        spec=importlib.util.spec_from_file_location('Habbo_Update_Helper',helper)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _choose_update_zip(self):
        p=filedialog.askopenfilename(title='Install Habbo Companion update',filetypes=[('Update package','*.zip')])
        if p:self._install_update_package(Path(p))

    def _install_update_package(self, package):
        try:
            helper=self._update_module()
            info=helper.inspect_package(package, current_version=self.current_app_version)
        except Exception as exc:
            messagebox.showerror('Update rejected',str(exc)[:600]);return
        if not messagebox.askyesno('Install Habbo Companion update',
            f'Install version {info["version"]}?\n\n'
            'The existing app will close, back up its files and restart.\n'
            'Your chat settings and saved G-Earth path will be preserved.\n\n'
            'Only continue if you trust the source of this update.'):
            return
        try:
            script=Path(__file__).resolve().parent/'Habbo_Update_Helper.py'
            args=[sys.executable,str(script),'apply','--package',str(package),
                  '--install-dir',str(Path(__file__).resolve().parent),
                  '--wait-pid',str(os.getpid()),'--restart-executable',sys.executable]
            kwargs={'cwd':str(Path(__file__).resolve().parent),'close_fds':True}
            if os.name=='nt':
                kwargs['creationflags']=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)
            subprocess.Popen(args,**kwargs)
            self.close()
        except (OSError,ValueError) as exc:
            messagebox.showerror('Update could not start',str(exc))

    def _restore_previous_version(self):
        backup_root=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'HabboCompanion' / 'Backups'
        candidates=sorted((p for p in backup_root.glob('*/app_manifest.json')
                           if (p.parent/'Habbo_Companion.pyw').is_file()),reverse=True)
        if not candidates:
            messagebox.showinfo('No backup','No restorable application backup was found yet.')
            return
        selected=candidates[0].parent
        try:
            version=json.loads((selected/'app_manifest.json').read_text(encoding='utf-8'))['version']
        except (OSError,ValueError,KeyError):
            messagebox.showerror('Invalid backup','The newest backup could not be read.')
            return
        if not messagebox.askyesno('Restore Habbo Companion',
            f'Restore saved app version {version}?\n\n'
            'The current application will be backed up first. Your settings and G-Earth path will not change.'):
            return
        try:
            script=Path(__file__).resolve().parent/'Habbo_Update_Helper.py'
            subprocess.Popen([sys.executable,str(script),'restore','--backup',str(selected),
                  '--install-dir',str(Path(__file__).resolve().parent),
                  '--wait-pid',str(os.getpid()),'--restart-executable',sys.executable],
                  cwd=str(Path(__file__).resolve().parent),close_fds=True)
            self.close()
        except (OSError,ValueError) as exc:
            messagebox.showerror('Restore failed to start',str(exc))

    def _open_backups(self):
        backups=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'HabboCompanion' / 'Backups'
        backups.mkdir(parents=True,exist_ok=True)
        try:os.startfile(str(backups))
        except (OSError,AttributeError):self.update_status.set('Backups are at: '+str(backups))

    def _check_online_update(self):
        if self._online_update_busy:return
        self._save_update_source()
        url=self.config.get('update_manifest_url','')
        if not url:return
        self._online_update_busy=True
        self.update_status.set('Checking for updates…')
        def worker():
            try:
                helper=self._update_module()
                helper.validate_official_release_url(url,'manifest')
                # Cache-busting is only applied after validating the exact
                # canonical publisher/path; redirects are not allowed.
                fresh_url=url+'?check='+uuid.uuid4().hex
                req=urllib.request.Request(fresh_url,headers={'User-Agent':'HabboCompanionUpdater/1.2','Cache-Control':'no-cache','Pragma':'no-cache'})
                with _open_official_update(req,timeout=12) as response:
                    if response.geturl()!=fresh_url:
                        raise ValueError('Update source changed unexpectedly')
                    raw=response.read(65_537)
                    if len(raw)>65_536:raise ValueError('Manifest is too large')
                info=json.loads(raw.decode('utf-8'))
                if info.get('app_id')!='habbo-companion':raise ValueError('Not a Habbo Companion update manifest')
                version=str(info['version']);package_url=str(info['package_url'])
                checksum=str(info['sha256']).lower()
                helper.validate_official_release_url(
                    package_url,'package',version=version)
                if not re.fullmatch(r'[a-f0-9]{64}',checksum):
                    raise ValueError('Invalid package checksum')
                if not helper.is_newer(version,self.current_app_version):
                    self.root.after(0,lambda v=version:self._finish_online_update(f'No newer update. Installed: {self.current_app_version}; feed: {v}.'))
                    return
                def ask_and_download():
                    self._online_update_busy=False
                    if not messagebox.askyesno('Update available',
                        f'Version {version} is available. Download and install it?\n\n'
                        f'Source: {urllib.parse.urlsplit(package_url).netloc}\n'
                        'Only continue if you trust this release source.'):
                        self.update_status.set('Update cancelled.');return
                    self._download_online_package(package_url,checksum)
                self.root.after(0,ask_and_download)
            except Exception as exc:
                desc=str(exc)[:220]
                self.root.after(0,lambda d=desc:self._finish_online_update('Update check failed: '+d))
        threading.Thread(target=worker,daemon=True).start()

    def _finish_online_update(self,msg):
        self._online_update_busy=False
        self.update_status.set(msg)

    def _download_online_package(self,url,expected_sha):
        if self._online_update_busy:return
        self._online_update_busy=True
        self.update_status.set('Downloading update package…')
        def worker():
            try:
                self._update_module().validate_official_release_url(
                    url,'package')
                folder=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'HabboCompanion' / 'Downloads'
                folder.mkdir(parents=True,exist_ok=True)
                dest=folder/'latest_habbo_companion_update.zip'
                req=urllib.request.Request(url,headers={'User-Agent':'HabboCompanionUpdater/1.0'})
                with _open_official_update(req,timeout=25) as response:
                    if response.geturl()!=url:
                        raise ValueError('Update download source changed unexpectedly')
                    digest=hashlib.sha256();size=0
                    with dest.open('wb') as f:
                        while True:
                            piece=response.read(65_536)
                            if not piece:break
                            size+=len(piece)
                            if size>12*1024*1024:raise ValueError('Update ZIP exceeds 12 MB limit')
                            digest.update(piece);f.write(piece)
                if digest.hexdigest()!=expected_sha:
                    dest.unlink(missing_ok=True)
                    raise ValueError('Package SHA-256 did not match release manifest')
                self.root.after(0,lambda p=dest:self._finish_online_download(p))
            except Exception as exc:
                desc=str(exc)[:220]
                self.root.after(0,lambda d=desc:self._finish_online_update('Update download failed: '+d))
        threading.Thread(target=worker,daemon=True).start()

    def _finish_online_download(self,p):
        self._online_update_busy=False
        self.update_status.set('Download verified. Ready to apply update.')
        self._install_update_package(p)

    def _make_packet_panel(self, parent):
        """Single-window front end for managed G-Earth and Habbo packets."""
        holder=ttk.Frame(parent,style='Panel.TFrame',padding=14)
        holder.pack(fill='both',expand=True)
        tk.Label(holder,text='CONNECTION + PACKETS',font=('Segoe UI Semibold',18),
                 fg=COMPANION_UI['text'],bg=COMPANION_UI['background']).pack(anchor='w')
        tk.Label(holder,text='Use Companion for everything. The working G-Earth engine starts normally '
                 'then hides after its backend is ready. Its original window is troubleshooting only.',
                 fg=COMPANION_UI['muted'],bg=COMPANION_UI['background'],wraplength=630,justify='left').pack(anchor='w',pady=(0,9))
        tk.Label(holder,textvariable=self.engine_status_var,bg=COMPANION_UI['background'],fg=COMPANION_UI['success'],
                 font=('Segoe UI Semibold',10),wraplength=630,justify='left').pack(anchor='w',pady=(0,9))
        main=ttk.Frame(holder,style='Panel.TFrame')
        main.pack(fill='x',pady=(0,9))
        ttk.Button(main,text='Start engine',style='Primary.TButton',
                   command=self._connect_habbo_air).pack(side='left',padx=(0,7))
        ttk.Button(main,text='Launch Habbo',command=self._launch_habbo_with_gearth).pack(side='left',padx=(0,7))
        ttk.Button(main,text='Connect packet tools (manual)',command=self._connect_gearth).pack(side='left')
        tk.Label(holder,text='Packet tools attach automatically when safe. Coffee Pass Loop can '
                 'also connect directly; this manual button is only for troubleshooting.',
                 fg=COMPANION_UI['muted'],bg=COMPANION_UI['background'],font=('Segoe UI',9),
                 wraplength=625,justify='left').pack(anchor='w',pady=(0,8))
        small=ttk.Frame(holder,style='Panel.TFrame')
        small.pack(fill='x',pady=(0,8))
        ttk.Checkbutton(small,text='Start engine automatically with Companion',
                        variable=self.gearth_auto_arm_var,
                        command=self._save_gearth_auto_arm).pack(side='left',padx=(0,12))
        self._engine_advanced_button=ttk.Button(
            small,text='Advanced settings ▾',command=self._toggle_engine_advanced)
        self._engine_advanced_button.pack(side='left')
        self._engine_advanced_visible=False
        self._engine_advanced_panel=ttk.Frame(holder,style='Panel.TFrame',padding=(4,6))
        adv=self._engine_advanced_panel
        ttk.Label(adv,text='ENGINE AND WINDOW',style='Panel.TLabel').pack(anchor='w',pady=(0,4))
        bar=ttk.Frame(adv,style='Panel.TFrame');bar.pack(fill='x',pady=(0,6))
        ttk.Button(bar,text='Show original G-Earth (troubleshoot)',
                   command=self._show_gearth).pack(side='left',padx=(0,6))
        ttk.Button(bar,text='Return to one window',
                   command=self._return_to_single_window).pack(side='left',padx=(0,6))
        ttk.Button(bar,text='Install / repair',
                   command=self._start_integrated_engine).pack(side='left')
        ttk.Checkbutton(adv,text='Hide original engine window when ready',
                        variable=self.gearth_minimize_var,
                        command=self._save_gearth_minimize).pack(anchor='w',pady=(0,7))
        tk.Label(adv,textvariable=self.gearth_path_display,bg=COMPANION_UI['background'],fg=COMPANION_UI['muted'],
                 font=('Segoe UI',9),wraplength=610,justify='left').pack(anchor='w',pady=(0,7))
        launcher=ttk.Frame(adv,style='Panel.TFrame');launcher.pack(fill='x',pady=(0,6))
        ttk.Button(launcher,text='Select Habbo launcher',
                   command=self._select_habbo_launcher).pack(side='left',padx=(0,7))
        tk.Label(launcher,textvariable=self.habbo_path_display,bg=COMPANION_UI['background'],fg=COMPANION_UI['muted'],
                 font=('Segoe UI',9),wraplength=390,justify='left').pack(side='left')
        hotel=ttk.Frame(adv,style='Panel.TFrame');hotel.pack(fill='x',pady=(0,8))
        ttk.Label(hotel,text='Host',style='Panel.TLabel').pack(side='left')
        ttk.Entry(hotel,textvariable=self.gearth_host_var,width=23).pack(side='left',padx=(5,9))
        ttk.Label(hotel,text='Port',style='Panel.TLabel').pack(side='left')
        ttk.Entry(hotel,textvariable=self.gearth_game_port_var,width=7).pack(side='left',padx=(5,9))
        ttk.Label(hotel,text='Extension',style='Panel.TLabel').pack(side='left')
        ttk.Entry(hotel,textvariable=self.gearth_port_var,width=7).pack(side='left',padx=(5,0))
        ttk.Label(adv,text='NETWORK SAFETY',style='Panel.TLabel').pack(anchor='w',pady=(0,4))
        net=ttk.Frame(adv,style='Panel.TFrame');net.pack(fill='x',pady=(0,7))
        ttk.Button(net,text='Check Windows network',
                   command=self._show_network_safety).pack(side='left',padx=(0,6))
        ttk.Button(net,text='Repair G-Earth hosts',
                   command=self._repair_gearth_hosts_ui).pack(side='left',padx=(0,6))
        ttk.Button(net,text='Disable active local proxy',
                   command=self._disable_local_proxy_ui).pack(side='left')
        diag=ttk.Frame(adv,style='Panel.TFrame');diag.pack(fill='x',pady=(0,7))
        ttk.Button(diag,text='Diagnose (may launch engine)',
                   command=self._diagnose_and_repair).pack(side='left',padx=(0,6))
        ttk.Button(diag,text='Copy diagnostic',
                   command=self._copy_engine_diagnostic).pack(side='left',padx=(0,6))
        ttk.Button(diag,text='Open engine without connecting',
                   command=self._open_managed_safe).pack(side='left')
        ttk.Label(holder,textvariable=self.packet_status,style='Panel.TLabel',
                  wraplength=630).pack(anchor='w',fill='x',pady=(0,8))
        opts=ttk.Frame(holder,style='Panel.TFrame')
        self._packet_search_row=opts
        opts.pack(fill='x',pady=(0,7))
        ttk.Label(opts,text='Find packets',style='Panel.TLabel').pack(side='left',padx=(0,6))
        ttk.Entry(opts,textvariable=self.packet_filter_var).pack(
            side='left',fill='x',expand=True,padx=(0,7))
        ttk.Button(opts,text='Pause / Resume',command=self._toggle_capture).pack(side='left')
        region=ttk.Frame(holder,style='Panel.TFrame');region.pack(fill='both',expand=True)
        self.packet_tree=ttk.Treeview(region,columns=('time','direction','summary'),show='headings',height=15)
        for col,head,width in [('time','Time',78),('direction','Direction',95),('summary','Packet (read-only)',390)]:
            self.packet_tree.heading(col,text=head)
            self.packet_tree.column(col,width=width,stretch=(col=='summary'))
        scroller=ttk.Scrollbar(region,orient='vertical',command=self.packet_tree.yview)
        self.packet_tree.configure(yscrollcommand=scroller.set)
        scroller.pack(side='right',fill='y')
        self.packet_tree.pack(side='left',fill='both',expand=True)
        self.packet_tree.bind('<<TreeviewSelect>>',self._select_packet)
        ttk.Label(holder,text='Selected packet',style='Panel.TLabel').pack(anchor='w',pady=(7,2))
        self.packet_details=tk.Text(holder,height=6,wrap='word',bg=COMPANION_UI['field'],fg=COMPANION_UI['text'],
                                    relief='flat',font=('Consolas',9),insertbackground='white')
        self.packet_details.pack(fill='x')
        actions=ttk.Frame(holder,style='Panel.TFrame');actions.pack(fill='x',pady=(8,0))
        ttk.Button(actions,text='Clear viewer',command=self._clear_packets).pack(side='left')
        ttk.Button(actions,text='Export visible packet log…',command=self._export_packets).pack(side='left',padx=(8,0))
        tk.Label(holder,text='Packets are stored only in memory (maximum 500). Nothing is sent anywhere.\n'
                 'G-Earth must prepare BEFORE Habbo begins connecting. On Companion startup, approve the\n'
                 'Windows administrator prompt. Launch Habbo only after G-Earth is waiting.\n'
                 'If Windows accessibility cannot press Connect, G-Earth stays open for manual connection.',
                 bg=COMPANION_UI['background'],fg=COMPANION_UI['muted'],justify='left',font=('Segoe UI',9),
                 wraplength=620).pack(anchor='w',pady=(12,0))


    def _make_fuzz_panel(self,parent):
        """One read-only live feed and an entirely separate loopback fuzz lab."""
        p=COMPANION_UI
        holder=ttk.Frame(parent,style='Panel.TFrame',padding=18)
        holder.pack(fill='both',expand=True)
        tk.Label(holder,text='PROTOCOL LAB',font=('Segoe UI Semibold',18),
                 bg=p['background'],fg=p['text']).pack(anchor='w')
        tk.Label(holder,text='Read Habbo AIR packet metadata through the existing G-Earth extension. '
                 'No raw packet contents, passwords, SSO tickets or chat are saved.',
                 wraplength=650,justify='left',bg=p['background'],fg=p['muted']).pack(anchor='w',pady=(6,12))
        ttk.Label(holder,textvariable=self.fuzz_live_var,style='Panel.TLabel',
                  wraplength=650).pack(anchor='w',pady=(0,8))
        ttk.Label(holder,textvariable=self.fuzz_connected_server_var,
                  style='Panel.TLabel',wraplength=650).pack(anchor='w',pady=(0,8))
        live=ttk.Frame(holder,style='Panel.TFrame');live.pack(fill='x',pady=(0,16))
        ttk.Button(live,text='Start / Stop passive reader',
                   command=self._fuzz_toggle_reader).pack(side='left',padx=(0,8))
        ttk.Button(live,text='Export redacted metadata JSON',
                   command=self._fuzz_export).pack(side='left')
        ttk.Button(live,text='Refresh connected server',
                   command=self._fuzz_refresh_connected_server).pack(side='left',padx=(8,0))
        ttk.Separator(holder,orient='horizontal').pack(fill='x',pady=(6,14))
        tk.Label(holder,text='LOCAL BOOFUZZ TEST',font=('Segoe UI Semibold',13),
                 bg=p['background'],fg=p['text']).pack(anchor='w')
        tk.Label(holder,text='Uses the most frequently observed outgoing message ID '
                 'as a numeric seed for a synthetic frame. The generated payloads go ONLY '
                 'to a temporary mock server on this PC, never to Habbo or '
                 'an external host. This cannot diagnose Habbo production.',
                 wraplength=650,justify='left',bg=p['background'],fg=p['muted']).pack(anchor='w',pady=(5,10))
        target=ttk.Frame(holder,style='Panel.TFrame')
        target.pack(fill='x',pady=(0,8))
        ttk.Label(target,text='Your PC test IP',style='Panel.TLabel').pack(side='left')
        ttk.Entry(target,textvariable=self.fuzz_target_ip_var,width=19).pack(
            side='left',padx=(9,10))
        tk.Label(target,text='127.0.0.1 or a private IP assigned to this computer',
                 bg=p['background'],fg=p['muted'],font=('Segoe UI',9)).pack(side='left')
        ttk.Label(holder,textvariable=self.fuzz_lab_var,style='Panel.TLabel',
                  wraplength=650).pack(anchor='w',pady=(0,8))
        bar=ttk.Frame(holder,style='Panel.TFrame');bar.pack(fill='x')
        ttk.Button(bar,text='Run 60 local boofuzz cases',
                   command=self._fuzz_start_lab).pack(side='left',padx=(0,8))
        ttk.Button(bar,text='Analyse results with local Ollama',
                   command=self._fuzz_analyse_ollama).pack(side='left')
        ttk.Checkbutton(
            holder,
            text='Habbo framing (VL64/B64 body) instead of the synthetic format',
            variable=self.fuzz_habbo_mode_var).pack(anchor='w',pady=(9,3))
        ttk.Checkbutton(
            holder,text='Also fuzz header IDs',
            variable=self.fuzz_habbo_header_var).pack(anchor='w',pady=(0,6))
        ttk.Button(holder,text='Run 40 Habbo-framing cases',
                   command=self._fuzz_start_habbo_lab).pack(anchor='w',pady=(0,3))
        ttk.Separator(holder,orient='horizontal').pack(fill='x',pady=(17,15))
        tk.Label(holder,text='LOCAL ARCTURUS EMULATOR',font=('Segoe UI Semibold',13),
                 bg=p['background'],fg=p['text']).pack(anchor='w')
        tk.Label(holder,text='Experimental binary-frame fuzzing for your own '
                 'Arcturus instance at 127.0.0.1:30000. This is independent '
                 'of Habbo, G-Earth and Direct TCP. The sample body contains '
                 'one VL64 integer and a signed single-digit B64 field; no '
                 'specific handler or authentication handshake is assumed. '
                 'Malformed test messages can crash your emulator.',
                 wraplength=650,justify='left',bg=p['background'],
                 fg=p['muted']).pack(anchor='w',pady=(5,9))
        inputs=ttk.Frame(holder,style='Panel.TFrame')
        inputs.pack(fill='x',pady=(0,7))
        ttk.Label(inputs,text='Known header ID',
                  style='Panel.TLabel').pack(side='left')
        ttk.Entry(inputs,textvariable=self.arcturus_header_var,
                  width=11).pack(side='left',padx=(7,13))
        ttk.Label(inputs,text='Cases (1–50)',
                  style='Panel.TLabel').pack(side='left')
        ttk.Entry(inputs,textvariable=self.arcturus_cases_var,
                  width=7).pack(side='left',padx=(7,0))
        actions=ttk.Frame(holder,style='Panel.TFrame')
        actions.pack(fill='x',pady=(0,7))
        ttk.Button(actions,text='Preview frame (offline)',
                   command=self._fuzz_preview_arcturus).pack(
                       side='left',padx=(0,8))
        ttk.Button(actions,text='Run Arcturus local fuzz',
                   command=self._fuzz_start_arcturus).pack(side='left')
        ttk.Label(holder,textvariable=self.arcturus_status_var,
                  style='Panel.TLabel',wraplength=650).pack(anchor='w',pady=(0,7))
        ttk.Separator(holder,orient='horizontal').pack(fill='x',pady=(17,15))
        tk.Label(holder,text='REMOTE TEST MACHINE',font=('Segoe UI Semibold',13),
                 bg=p['background'],fg=p['text']).pack(anchor='w')
        tk.Label(holder,text='Connect to a test server on another machine, using '
                 'its IP and TCP port. It must be running the Companion lab_remote_server.py '
                 'helper and share a lab-only key. Each connection proves server control '
                 'before any synthetic fuzz packets are sent. This is not an arbitrary '
                 'Habbo server scanner.',
                 wraplength=650,justify='left',bg=p['background'],
                 fg=p['muted']).pack(anchor='w',pady=(5,8))
        rem=ttk.Frame(holder,style='Panel.TFrame');rem.pack(fill='x',pady=(0,7))
        ttk.Label(rem,text='Server IPv4',style='Panel.TLabel').pack(side='left')
        ttk.Entry(rem,textvariable=self.fuzz_remote_ip_var,width=18).pack(
            side='left',padx=(7,14))
        ttk.Label(rem,text='TCP port',style='Panel.TLabel').pack(side='left')
        ttk.Entry(rem,textvariable=self.fuzz_remote_port_var,width=9).pack(
            side='left',padx=(7,0))
        ttk.Label(holder,text='Shared lab key (not your Habbo SSO ticket)',
                  style='Panel.TLabel').pack(anchor='w')
        ttk.Entry(holder,textvariable=self.fuzz_remote_key_var,show='*').pack(
            fill='x',pady=(3,8))
        ttk.Button(holder,text='Run 20 remote lab fuzz cases',
                   command=self._fuzz_start_remote).pack(anchor='w')
        tk.Label(holder,text='Only a server under your control running the '
                 'authenticated helper can receive fuzz payloads. Your official '
                 'Habbo SSO/encrypted Direct TCP connection is kept separate. '
                 'Install boofuzz in the Python running Companion.',
                 wraplength=650,justify='left',bg=p['background'],
                 fg=p['faint']).pack(anchor='w',pady=(16,0))

    def _fuzz_refresh_connected_server(self):
        """Read connection metadata only; never route test traffic to peers."""
        statuses=[]
        direct_peers=set()
        for session in self._tcp_sessions.values():
            if not getattr(session,'authenticated',False):
                continue
            sock=getattr(session,'sock',None)
            if sock is None:
                continue
            try:
                peer=sock.getpeername()
            except (OSError,ValueError):
                continue
            if isinstance(peer,tuple) and len(peer)>=2:
                direct_peers.add(f'{peer[0]}:{peer[1]}')
        if direct_peers:
            statuses.append('Active Direct TCP socket peer(s): '+
                            ', '.join(sorted(direct_peers))+' (verified peer address)')
        if self._habbo_session_connected:
            host=self.gearth_host_var.get().strip()
            port=self.gearth_game_port_var.get().strip()
            statuses.append(f'G-Earth AIR session active; configured target: {host}:{port} '
                            '(actual remote IP unverified)')
        self.fuzz_connected_server_var.set(
            ' | '.join(statuses)+' — read-only; boofuzz remains on your PC.'
            if statuses else
            'Connected game server: none detected. Boofuzz traffic stays on your PC.')

    def _fuzz_toggle_reader(self):
        if self.fuzz_monitoring:
            self.fuzz_monitoring=False
            self.fuzz_live_var.set(f'Paused: {self.fuzz_seen} packets; '
                                   f'{len(self.fuzz_counts)} direction/ID groups.')
        elif not self.packet_started or not self._habbo_session_connected:
            self.fuzz_live_var.set('Attach Companion to G-Earth and Habbo AIR first.')
        else:
            self.fuzz_monitoring=True
            self.fuzz_live_var.set('Passive reader ON — recording only ID, direction and byte length.')

    def _fuzz_export(self):
        if not self.fuzz_counts:
            self.fuzz_live_var.set('Nothing captured; start the passive reader first.')
            return
        destination=filedialog.asksaveasfilename(
            title='Save redacted G-Earth metadata',defaultextension='.json',
            filetypes=[('JSON','*.json')])
        if not destination:return
        report={'source':'G-Earth read-only Habbo AIR metadata',
                'total':self.fuzz_seen,'packet_content_included':False,
                'observations':[{'direction':d,'message_id':mid,
                                 'count':item['count'],'minimum_bytes':item['min'],
                                 'maximum_bytes':item['max']}
                                for (d,mid),item in sorted(self.fuzz_counts.items())]}
        try:
            Path(destination).write_text(json.dumps(report,indent=2),encoding='utf-8')
            self.fuzz_live_var.set('Saved redacted packet metadata: '+str(destination))
        except OSError as exc:
            self.fuzz_live_var.set('Export failed: '+str(exc)[:130])

    def _fuzz_start_lab(self):
        if self.fuzz_habbo_mode_var.get():
            self._fuzz_start_habbo_lab()
            return
        if self.fuzz_running:
            self.fuzz_lab_var.set('Local boofuzz session already running.')
            return
        try:
            bind_ip=validate_owned_lab_ip(self.fuzz_target_ip_var.get())
        except ValueError as exc:
            self.fuzz_lab_var.set(str(exc))
            return
        outgoing=[(v['count'],mid) for (direction,mid),v in self.fuzz_counts.items()
                  if direction=='Outgoing']
        seed=max(outgoing)[1] if outgoing else 896
        self.fuzz_running=True
        self.fuzz_lab_var.set(f'Running up to 60 synthetic cases on your PC at {bind_ip} (seed ID {seed})...')
        def work():
            try:
                result=run_local_boofuzz(seed_id=seed,cases=60,bind_ip=bind_ip)
                self._packet_put(('fuzz_result',result))
            except ModuleNotFoundError:
                self._packet_put(('fuzz_error',
                    'boofuzz not installed. Run: "'+sys.executable+
                    '" -m pip install boofuzz==0.4.2'))
            except Exception as exc:
                self._packet_put(('fuzz_error',type(exc).__name__+': '+str(exc)[:170]))
        threading.Thread(target=work,daemon=True).start()


    def _fuzz_start_habbo_lab(self):
        if self.fuzz_running:
            self.fuzz_lab_var.set('Local boofuzz session already running.')
            return
        try:
            bind_ip=validate_owned_lab_ip(self.fuzz_target_ip_var.get())
        except ValueError as exc:
            self.fuzz_lab_var.set(str(exc))
            return
        outgoing=[(v['count'],mid) for (direction,mid),v in self.fuzz_counts.items()
                  if direction=='Outgoing']
        seed=max(outgoing)[1] if outgoing else 896
        fuzz_header=bool(self.fuzz_habbo_header_var.get())
        self.fuzz_running=True
        self.fuzz_lab_var.set(
            f'Running up to 40 Habbo-framing cases on your PC at {bind_ip} '
            f'(seed ID {seed}; fuzz header: {fuzz_header})...')
        def work():
            try:
                result=run_local_habbo_boofuzz(
                    seed_id=seed,cases=40,bind_ip=bind_ip,fuzz_header=fuzz_header)
                self._packet_put(('fuzz_result',result))
            except ModuleNotFoundError:
                self._packet_put(('fuzz_error',
                    'boofuzz not installed. Run: "'+sys.executable+
                    '" -m pip install boofuzz==0.4.2'))
            except Exception as exc:
                self._packet_put(('fuzz_error',type(exc).__name__+': '+str(exc)[:170]))
        threading.Thread(target=work,daemon=True).start()

    def _fuzz_arcturus_header_id(self):
        raw=self.arcturus_header_var.get().strip()
        if not raw:
            raise ValueError('Enter a known Arcturus header ID; none is guessed.')
        header_id=int(raw,16 if raw.lower().startswith('0x') else 10)
        validate_arcturus_emulator_parameters(header_id,1)
        return header_id

    def _fuzz_preview_arcturus(self):
        try:
            header_id=self._fuzz_arcturus_header_id()
            frame=preview_arcturus_emulator_packet(header_id)
            self.arcturus_status_var.set(
                'Offline preview ONLY (no network): '+
                frame.hex(' ')[:180]+
                f' | {len(frame)} bytes; length field={len(frame)-4}.')
        except ModuleNotFoundError:
            self.arcturus_status_var.set(
                'boofuzz missing. Install with: "'+
                sys.executable+'" -m pip install boofuzz==0.4.2')
        except (ValueError,TypeError) as exc:
            self.arcturus_status_var.set('Preview error: '+str(exc)[:180])
        except Exception as exc:
            self.arcturus_status_var.set(
                'Preview failed: '+type(exc).__name__+'. Nothing was sent.')

    def _fuzz_start_arcturus(self):
        if self.fuzz_running:
            self.arcturus_status_var.set('Another boofuzz session is already running.')
            return
        try:
            header_id=self._fuzz_arcturus_header_id()
            cases=int(self.arcturus_cases_var.get().strip())
            validate_arcturus_emulator_parameters(header_id,cases)
        except (ValueError,TypeError) as exc:
            self.arcturus_status_var.set('Invalid Arcturus test: '+str(exc)[:180])
            return
        if not messagebox.askyesno(
                'Confirm LOCAL emulator fuzzing',
                f'Fuzz ONLY your local Arcturus emulator at '
                f'{ARCTURUS_EMULATOR_HOST}:{ARCTURUS_EMULATOR_PORT}?\n\n'
                f'Header ID: {header_id}; up to {cases} cases.\n'
                'This can crash your emulator. No Habbo login, '
                'G-Earth injection, or remote target is used.',
                default='no'):
            return
        self.fuzz_running=True
        self.arcturus_status_var.set(
            f'Running up to {cases} local Arcturus cases at '
            f'{ARCTURUS_EMULATOR_HOST}:{ARCTURUS_EMULATOR_PORT} ...')
        def work():
            try:
                result=run_arcturus_emulator_boofuzz(
                    header_id=header_id,cases=cases)
                self._packet_put(('arcturus_result',result))
            except ModuleNotFoundError:
                self._packet_put(('arcturus_error',
                    'boofuzz missing. Install with: "'+
                    sys.executable+'" -m pip install boofuzz==0.4.2'))
            except (OSError,ValueError) as exc:
                self._packet_put(('arcturus_error',
                    'Local Arcturus test failed: '+
                    type(exc).__name__+': '+
                    redact_sensitive_diagnostic(str(exc))[:150]))
            except Exception as exc:
                self._packet_put(('arcturus_error',
                    'Local Arcturus test failed: '+type(exc).__name__+
                    '. Check that your emulator is running on localhost:30000.'))
        threading.Thread(target=work,daemon=True).start()

    def _fuzz_start_remote(self):
        if self.fuzz_running:
            self.fuzz_lab_var.set('A fuzz session is already running.')
            return
        try:
            ip,port,key=validate_remote_lab_target(
                self.fuzz_remote_ip_var.get(),
                self.fuzz_remote_port_var.get(),
                self.fuzz_remote_key_var.get())
        except ValueError as exc:
            self.fuzz_lab_var.set(str(exc))
            return
        self.fuzz_running=True
        self.fuzz_lab_var.set(f'Checking authenticated remote test server {ip}:{port}...')
        outgoing=[(v['count'],mid) for (direction,mid),v in self.fuzz_counts.items()
                  if direction=='Outgoing']
        seed=max(outgoing)[1] if outgoing else 896
        def work():
            try:
                result=run_remote_boofuzz(ip,port,key,seed_id=seed,cases=20)
                self._packet_put(('fuzz_result',result))
            except ModuleNotFoundError:
                self._packet_put(('fuzz_error',
                    'boofuzz not installed. Run: "'+sys.executable+
                    '" -m pip install boofuzz==0.4.2'))
            except Exception as exc:
                # Never display raw passwords or lab keys in error diagnostics.
                self._packet_put(('fuzz_error',type(exc).__name__+
                                  ': The remote lab refused or failed the test.'))
        threading.Thread(target=work,daemon=True).start()

    def _fuzz_analyse_ollama(self):
        if not self.fuzz_last_result:
            self.fuzz_lab_var.set('Run a local boofuzz test first.')
            return
        summary=dict(self.fuzz_last_result)
        self.fuzz_lab_var.set('Requesting local Ollama explanation (no packet contents sent)...')
        def work():
            prompt=('Explain these SYNTHETIC localhost mock-server fuzz results. '
                    'Do not infer vulnerabilities in Habbo. Give one practical '
                    'parser hardening recommendation. Data: '+json.dumps(summary))
            payload=json.dumps({'model':'qwen2.5-coder:7b','prompt':prompt,
                                'stream':False}).encode('utf-8')
            try:
                req=urllib.request.Request('http://127.0.0.1:11434/api/generate',
                    data=payload,headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=90) as resp:
                    answer=json.load(resp).get('response','No response')
                self._packet_put(('fuzz_analysis',str(answer)[:1800]))
            except Exception as exc:
                self._packet_put(('fuzz_error','Local Ollama: '+str(exc)[:170]))
        threading.Thread(target=work,daemon=True).start()

    def _make_manipulator_panel(self,parent):
        # Keep original rules and packet replayer; add a separate action-loop tab.
        tabs=ttk.Notebook(parent)
        tabs.pack(fill='both',expand=True)
        rules_tab=ttk.Frame(tabs,style='Panel.TFrame')
        coffee_tab=ttk.Frame(tabs,style='Panel.TFrame')
        tabs.add(rules_tab,text='  Rules & Replay  ')
        tabs.add(coffee_tab,text='  Coffee Pass Loop  ')
        holder=ttk.Frame(rules_tab,style='Panel.TFrame',padding=13)
        holder.pack(fill='both',expand=True)
        tk.Label(holder,text='PACKET MANIPULATOR',font=('Segoe UI Semibold',18),
                 fg=COMPANION_UI['text'],bg=COMPANION_UI['background']).pack(anchor='w')
        ttk.Label(holder,text='Rules are OFF by default. Use a specific packet header or contains filter.',
                  style='Panel.TLabel',wraplength=640).pack(anchor='w',pady=(1,7))
        ttk.Checkbutton(holder,text='Enable packet manipulation for this session',
                        variable=self.manipulation_enable_var,command=self._toggle_manipulator).pack(anchor='w',pady=(0,5))
        ttk.Label(holder,textvariable=self.manipulator_status,style='Panel.TLabel',wraplength=650).pack(anchor='w',pady=(0,7))
        rules_box=ttk.Frame(holder,style='Panel.TFrame');rules_box.pack(fill='both',expand=True)
        self.rules_tree=ttk.Treeview(rules_box,columns=('on','dir','header','filter','action'),show='headings',height=7)
        for col,label,width in [('on','On',36),('dir','Direction',95),('header','ID',70),('filter','Contains',190),('action','Action',82)]:
            self.rules_tree.heading(col,text=label)
            self.rules_tree.column(col,width=width,stretch=(col=='filter'),anchor='w')
        rs=ttk.Scrollbar(rules_box,orient='vertical',command=self.rules_tree.yview)
        self.rules_tree.configure(yscrollcommand=rs.set)
        rs.pack(side='right',fill='y');self.rules_tree.pack(side='left',fill='both',expand=True)
        self.rules_tree.bind('<<TreeviewSelect>>',self._load_manipulation_rule)
        form=ttk.Frame(holder,style='Panel.TFrame');form.pack(fill='x',pady=(8,0))
        one=ttk.Frame(form,style='Panel.TFrame');one.pack(fill='x',pady=(0,5))
        ttk.Label(one,text='Direction',style='Panel.TLabel').pack(side='left')
        ttk.Combobox(one,textvariable=self.rule_direction_var,values=RULE_DIRECTIONS,state='readonly',width=10).pack(side='left',padx=(4,10))
        ttk.Label(one,text='Header ID',style='Panel.TLabel').pack(side='left')
        ttk.Entry(one,textvariable=self.rule_header_var,width=10).pack(side='left',padx=(4,10))
        ttk.Label(one,text='Action',style='Panel.TLabel').pack(side='left')
        ttk.Combobox(one,textvariable=self.rule_action_var,values=RULE_ACTIONS,state='readonly',width=10).pack(side='left',padx=(4,10))
        ttk.Checkbutton(one,text='Rule enabled',variable=self.rule_enabled_var).pack(side='left')
        two=ttk.Frame(form,style='Panel.TFrame');two.pack(fill='x',pady=(0,6))
        ttk.Label(two,text='Packet text contains',style='Panel.TLabel').pack(side='left')
        ttk.Entry(two,textvariable=self.rule_contains_var).pack(side='left',fill='x',expand=True,padx=(8,0))
        ttk.Label(form,text='Replacement G-Earth expression (only for Replace):',style='Panel.TLabel').pack(anchor='w')
        self.replace_expression=tk.Text(form,height=3,wrap='word',font=('Consolas',9),bg=COMPANION_UI['field'],fg=COMPANION_UI['text'],insertbackground='white')
        self.replace_expression.pack(fill='x',pady=(3,5))
        buttons=ttk.Frame(form,style='Panel.TFrame');buttons.pack(fill='x',pady=(0,6))
        ttk.Button(buttons,text='Add rule',command=self._add_manipulation_rule).pack(side='left',padx=(0,5))
        ttk.Button(buttons,text='Update selected',command=self._update_manipulation_rule).pack(side='left',padx=(0,5))
        ttk.Button(buttons,text='Delete selected',command=self._delete_manipulation_rule).pack(side='left',padx=(0,5))
        ttk.Button(buttons,text='Clear editor',command=self._clear_manipulation_editor).pack(side='left')
        ttk.Separator(holder,orient='horizontal').pack(fill='x',pady=(9,7))
        ttk.Label(holder,text='Manual packet send — requires a connected G-Earth session',style='Panel.TLabel').pack(anchor='w')
        send_row=ttk.Frame(holder,style='Panel.TFrame');send_row.pack(fill='x',pady=(5,3))
        ttk.Label(send_row,text='Direction',style='Panel.TLabel').pack(side='left')
        ttk.Combobox(send_row,textvariable=self.inject_direction_var,values=('Outgoing','Incoming'),state='readonly',width=11).pack(side='left',padx=(6,12))
        ttk.Button(send_row,text='Load selected viewer packet',command=self._load_packet_for_sending).pack(side='left')
        self.inject_expression=tk.Text(holder,height=3,wrap='word',font=('Consolas',9),bg=COMPANION_UI['field'],fg=COMPANION_UI['text'],insertbackground='white')
        self.inject_expression.pack(fill='x',pady=(3,6))
        ttk.Button(holder,text='Send packet once',command=self._send_manual_packet).pack(anchor='w')
        repeat_row=ttk.Frame(holder,style='Panel.TFrame')
        repeat_row.pack(fill='x',pady=(8,3))
        ttk.Label(repeat_row,text='Repeat outgoing packet every',style='Panel.TLabel').pack(side='left')
        ttk.Entry(repeat_row,textvariable=self.replay_interval_var,width=6).pack(side='left',padx=(6,5))
        ttk.Label(repeat_row,text='seconds',style='Panel.TLabel').pack(side='left',padx=(0,10))
        ttk.Button(repeat_row,text='Start repeating',command=self._start_packet_replay).pack(side='left',padx=(0,6))
        ttk.Button(repeat_row,text='STOP',command=self._stop_packet_replay).pack(side='left')
        ttk.Label(holder,textvariable=self.replay_status_var,style='Panel.TLabel',
                  wraplength=640).pack(anchor='w',pady=(0,4))
        ttk.Label(holder,text='Packet replay is OFF by default and sends only your selected outgoing action. '
                  'Minimum delay: 0.1 seconds (100 ms). Stops on disconnect or when Companion closes. '
                  'Avoid excessive automation or violating Habbo rules.',
                  style='Panel.TLabel',wraplength=630).pack(anchor='w',pady=(4,0))
        self._refresh_manipulation_rules()
        self._make_coffee_loop_panel(coffee_tab)


    def _make_coffee_loop_panel(self,parent):
        holder=ttk.Frame(parent,style='Panel.TFrame',padding=16)
        holder.pack(fill='both',expand=True)
        tk.Label(holder,text='COFFEE PASS',font=('Segoe UI Semibold',18),
                 fg=COMPANION_UI['text'],bg=COMPANION_UI['background']).pack(anchor='w')
        ttk.Label(holder,text='Give a cup to a player by Habbo username. '
                  'The existing alternating two-cup loop is also available.',
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(3,14))

        def entry(label,var,note):
            row=ttk.Frame(holder,style='Panel.TFrame');row.pack(fill='x',pady=(0,9))
            ttk.Label(row,text=label,style='Panel.TLabel',width=21).pack(side='left')
            ttk.Entry(row,textvariable=var,width=18).pack(side='left',padx=(4,10))
            ttk.Label(row,text=note,style='Panel.TLabel').pack(side='left')

        entry('Recipient username',self.coffee_username_var,'Exact name in the current room')
        entry('Recipient ID (fallback)',self.coffee_recipient_var,'Used only when username is blank')
        entry('Cup 1 furniture ID',self.coffee_cup_one_var,'One-cup action starts here')
        entry('Cup 2 furniture ID',self.coffee_cup_two_var,'For alternating loop')
        entry('Other furniture IDs',self.coffee_extra_furniture_var,
              'Optional bookcase / extras: comma-separated room IDs')
        ttk.Button(holder,text='Capture next furniture click',
                   command=self._arm_coffee_furniture_capture).pack(anchor='w',pady=(0,5))
        ttk.Label(holder,textvariable=self.coffee_furniture_capture_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,7))
        entry('Delay per action (sec)',self.coffee_interval_var,
              '0.0001 accepted; actual Tk scheduling minimum ~1ms')
        entry('Complete loop cycles',self.coffee_cycles_var,'0 = unlimited cycles until STOP')
        ttk.Checkbutton(holder,text='Wait for my avatar to receive/pass each cup',
                        variable=self.coffee_wait_for_hand_var).pack(anchor='w',pady=(4,5))
        ttk.Label(holder,text='Optional: uses server CarryObject updates for your '
                  'own avatar. Stops if your room index or a confirmation is '
                  'unavailable; never assumes the recipient accepted a cup.',
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,6))
        ttk.Checkbutton(holder,text='Rotate between willing participants (group mode)',
                        variable=self.coffee_group_enabled_var).pack(anchor='w',pady=(4,8))
        entry('Group usernames',self.coffee_group_names_var,
              'Comma-separated, 2-8; checked only in group mode')
        group_actions=ttk.Frame(holder,style='Panel.TFrame')
        group_actions.pack(anchor='w',pady=(0,8))
        ttk.Label(group_actions,text='Exclude participant',style='Panel.TLabel').pack(side='left')
        ttk.Entry(group_actions,textvariable=self.coffee_group_exclude_var,width=18).pack(side='left',padx=(8,8))
        ttk.Button(group_actions,text='Remove from rotation',
                   command=self._exclude_coffee_group_recipient).pack(side='left')
        ttk.Label(holder,text='Group mode: consenting users only; at least 10 seconds '
                  'between packet actions. No automatic retry of blocked or excluded users.',
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(1,8))

        ttk.Label(holder,textvariable=self.packet_connection_status,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(3,5))
        ttk.Label(holder,textvariable=self.coffee_users_status_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,4))
        ttk.Label(holder,textvariable=self.coffee_own_status_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,6))
        diagnostics=ttk.Frame(holder,style='Panel.TFrame')
        diagnostics.pack(anchor='w',pady=(0,9))
        ttk.Button(diagnostics,text='Refresh room players',
                   command=self._refresh_room_players).pack(side='left',padx=(0,8))
        ttk.Button(diagnostics,text='Detect my avatar',
                   command=lambda:self._request_own_identity(force=True)).pack(side='left')
        buttons=ttk.Frame(holder,style='Panel.TFrame');buttons.pack(fill='x',pady=(4,12))
        ttk.Button(buttons,text='Give 1 cup',command=lambda:self._start_coffee_loop(single_cup=True)).pack(side='left',padx=(0,9))
        ttk.Button(buttons,text='Start coffee pass loop',command=self._start_coffee_loop).pack(side='left',padx=(0,9))
        ttk.Button(buttons,text='Test speed (3 cycles)',command=self._run_coffee_speed_test).pack(side='left',padx=(0,9))
        ttk.Button(buttons,text='STOP',command=self._stop_coffee_loop).pack(side='left')
        ttk.Label(holder,textvariable=self.coffee_status_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(2,7))
        ttk.Label(holder,text='DELIVERY MONITOR (server activity, not a guarantee)',
                  style='Panel.TLabel').pack(anchor='w',pady=(3,3))
        ttk.Label(holder,textvariable=self.coffee_delivery_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,7))
        ttk.Label(holder,textvariable=self.coffee_speed_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,8))
        ttk.Label(holder,text='AUTOMATIC COFFEE SESSION RECORDING',
                  style='Panel.TLabel').pack(anchor='w',pady=(3,3))
        ttk.Label(holder,textvariable=self.coffee_recording_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,5))
        ttk.Button(holder,text='Open saved coffee results',
                   command=self._open_coffee_recordings).pack(anchor='w',pady=(0,10))
        ttk.Label(holder,text='No chat required: if the room list is missing, '
                   'the exact username is resolved through Habbo profile lookup. '
                   'Confirm the ID and ensure the recipient is in your room. '
                  'No ID is guessed if the name cannot be found. '
                  'One cup sends Cup 1 + Pass once; the loop alternates both cups. '
                  'G-Earth must be connected. The server can ignore or rate-limit requests.',
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(6,0))

    def _arm_coffee_furniture_capture(self):
        """Capture one outgoing manual furniture use, not every room interaction."""
        if self._coffee_running:
            self.coffee_furniture_capture_var.set(
                'Press STOP before capturing a furniture source.')
            return
        if (not self.packet_started or self.packet_extension is None
            or not self._habbo_session_connected):
            self.coffee_furniture_capture_var.set(
                'Connect Habbo and G-Earth before capturing the bookcase ID.')
            return
        self._coffee_furniture_capture_generation+=1
        generation=self._coffee_furniture_capture_generation
        self._coffee_furniture_capture_pending=True
        self.coffee_furniture_capture_var.set(
            'Capture armed: double-click your bookcase (or other dispenser) in Habbo.')
        self.root.after(15000,lambda gen=generation:self._coffee_capture_timeout(gen))

    def _coffee_capture_timeout(self,generation):
        if (generation!=self._coffee_furniture_capture_generation
            or not self._coffee_furniture_capture_pending):
            return
        self._coffee_furniture_capture_pending=False
        self.coffee_furniture_capture_var.set(
            'No UseFurniture packet captured in 15 seconds. '
            'Try Capture again and double-click the dispenser.')

    def _receive_captured_furniture(self,furniture_id):
        """Add the validated room-instance ID only once."""
        furniture=str(furniture_id)
        try:
            existing=parse_extra_furniture_sources(
                self.coffee_extra_furniture_var.get(),
                self.coffee_cup_one_var.get(),self.coffee_cup_two_var.get())
            updated=parse_extra_furniture_sources(
                ', '.join((*existing,furniture)),
                self.coffee_cup_one_var.get(),self.coffee_cup_two_var.get())
        except ValueError as exc:
            self.coffee_furniture_capture_var.set(
                'Cannot add captured furniture: '+str(exc))
            return
        self.coffee_extra_furniture_var.set(', '.join(updated))
        self.config['coffee_extra_furniture']=self.coffee_extra_furniture_var.get()
        self.save()
        self.coffee_furniture_capture_var.set(
            f'Captured furniture instance {furniture}. Included in cup/book rotation. '
            'Only works if the furniture actually gives a hand item.')

    def _resolve_coffee_recipient(self):
        """Resolve the exact in-room Habbo username, or use manual ID only if blank."""
        username=self.coffee_username_var.get().strip()
        if not username:
            return self.coffee_recipient_var.get().strip(),''
        if len(username)>80 or any(ch in username for ch in '\r\n\x00'):
            raise ValueError('Enter a valid Habbo username.')
        user=self._room_users.get(username.casefold())
        if user is not None:
            return str(user[1]),user[0]
        # A direct ExtendedProfile response confirms username <-> account ID
        # even when the player has not said anything in the current room.
        profile=self._room_profile_cache.get(username.casefold())
        if profile is not None:
            return str(profile[1]),profile[0]
        raise ValueError('Player "'+username+'" not found in room list, '
                         'and no matching Habbo profile response was received.')

    def _lookup_coffee_profile(self,username,single_cup=False,speed_test=False):
        """Get the exact numeric ID from Habbo without guessing a recipient."""
        if self._coffee_profile_pending is not None:
            self.coffee_status_var.set('Already checking a Habbo username. No coffee sent yet.')
            return
        try:
            expression=coffee_profile_request_expression(username)
            packet=self.packet_extension.string_to_packet(expression)
            if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
                raise ValueError('G-Earth could not resolve GetExtendedProfileByName.')
            self._coffee_profile_generation+=1
            gen=self._coffee_profile_generation
            self._coffee_profile_pending=(username.casefold(),bool(single_cup),gen,
                                          bool(speed_test))
            if self.packet_extension.send_to_server(packet) is False:
                raise RuntimeError('G-Earth rejected the profile request.')
            self.coffee_status_var.set(
                'Checking Habbo profile for "'+username+'"... no coffee sent yet (8s timeout).')
            self.root.after(8000,lambda generation=gen:self._coffee_profile_timeout(generation))
        except (ValueError,TypeError,AttributeError,RuntimeError) as exc:
            self._coffee_profile_pending=None
            self.coffee_status_var.set('Could not look up username: '+str(exc)[:160])

    def _coffee_profile_timeout(self,generation):
        pending=self._coffee_profile_pending
        if pending is None or pending[2]!=generation:
            return
        self._coffee_profile_pending=None
        self.coffee_status_var.set(
            'No matching Habbo profile returned within 8 seconds. No coffee sent. '
            'Check G-Earth connection or leave and re-enter the room.')

    def _accept_coffee_profile(self,name,user_id):
        pending=self._coffee_profile_pending
        if pending is None or name.casefold()!=pending[0]:
            return
        self._coffee_profile_pending=None
        if (not self._habbo_session_connected or
                self.coffee_username_var.get().strip().casefold()!=name.casefold()):
            self.coffee_status_var.set('Profile lookup cancelled: session or username changed.')
            return
        # Do not mislabel profile lookup as evidence of room presence.
        # A server-confirmed name/ID is enough to attempt PassCarryItem,
        # subject to the existing explicit user confirmation. The Habbo
        # server is responsible for rejecting recipients outside the room.
        if name.casefold() in self._room_chat_names:
            self._room_users[name.casefold()]=(name,user_id,None)
            self.coffee_users_status_var.set(
                f'{name} confirmed by Habbo profile and current room chat (ID {user_id}).')
        else:
            self._room_profile_cache[name.casefold()]=(name,user_id)
            self.coffee_users_status_var.set(
                f'Habbo confirmed {name} (ID {user_id}). Room presence not verified; '
                'the recipient does not need to speak to attempt a cup.')
        self.coffee_status_var.set(
            'Exact username and account ID confirmed by Habbo; checking cup actions...')
        self.root.after(0,lambda once=pending[1],bench=(
            pending[3] if len(pending)>3 else False):
            self._start_coffee_loop(single_cup=once,speed_test=bench))

    def _request_own_identity(self,force=False):
        """Request current account ID from Habbo's normal UserObject response.

        InfoRetrieve is a one-shot query, not a repeating packet probe.
        Once the ID is known, pair it with the current Users room index.
        """
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            self.coffee_own_status_var.set(
                'Cannot detect your avatar until Habbo and G-Earth are connected.')
            return False
        now=time.monotonic()
        if now-self._own_identity_last_request<5.0:
            if force:
                self.coffee_own_status_var.set(
                    'Avatar lookup was just requested; check the room-index status again.')
            return False
        try:
            packet=self.packet_extension.string_to_packet('{out:InfoRetrieve}')
            if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
                raise ValueError('InfoRetrieve header is unavailable in G-Earth.')
            self._own_identity_last_request=now
            if self.packet_extension.send_to_server(packet) is False:
                raise RuntimeError('G-Earth refused the avatar identity request.')
            self._own_identity_pending=True
            self.coffee_own_status_var.set(
                'Detecting your Habbo avatar via InfoRetrieve; '
                f'{len(self._room_users)} room player(s) mapped...')
            self.root.after(5000,lambda stamp=now:self._own_identity_timeout(stamp))
            return True
        except (AttributeError,RuntimeError,ValueError,TypeError) as exc:
            self._own_identity_pending=False
            self.coffee_own_status_var.set(
                'Could not request your avatar identity: '+str(exc)[:130])
            return False

    def _own_identity_timeout(self,stamp):
        if (not self._own_identity_pending or
            self._own_identity_last_request!=stamp):
            return
        self._own_identity_pending=False
        if self._own_room_index is not None:
            return
        self.coffee_own_status_var.set(
            'Habbo did not confirm your room index. Click Detect my avatar, '
            'or turn off Wait for my avatar to use the original timed loop.')

    def _recover_own_room_index_from_snapshot(self):
        """Re-check most recent Users snapshot when InfoRetrieve returns later."""
        if (self._own_account_id is None or not self._own_name
            or self._last_room_users_binary is None):
            return False
        name=self._own_name.casefold()
        trusted={name:(self._own_name,self._own_account_id,None)}
        recovered=room_users_from_binary_prefixes(
            self._last_room_users_binary,trusted)
        own=recovered.get(name)
        if own is None or own[1]!=self._own_account_id:
            return False
        self._room_users[name]=own
        self._own_room_index=own[2]
        self.coffee_own_status_var.set(
            f'Your avatar: {self._own_name} — room index {own[2]} '
            '(verified from room roster).')
        return True

    def _refresh_room_players(self):
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            self.coffee_users_status_var.set('Connect G-Earth and join the Habbo room before refreshing.')
            return
        self._room_lookup_generation+=1
        gen=self._room_lookup_generation
        self._room_lookup_pending=True
        self._room_lookup_seen=False
        self._room_lookup_parse_failed=False
        try:
            packet=self.packet_extension.string_to_packet('{out:GetHeightMap}')
            if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
                raise ValueError('GetHeightMap cannot be resolved by G-Earth.')
            if self.packet_extension.send_to_server(packet) is False:
                raise RuntimeError('G-Earth rejected the room refresh request.')
            self.coffee_users_status_var.set(
                f'Room request sent. {len(self._room_users)} player(s) known; '
                'checking for a Users reply (12 second timeout)...')
            self.root.after(12000,lambda generation=gen:self._room_refresh_timeout(generation))
        except Exception as exc:
            self._room_lookup_pending=False
            self.coffee_users_status_var.set('Could not refresh room players: '+str(exc)[:145])

    def _room_refresh_timeout(self,generation):
        if not self._room_lookup_pending or generation!=self._room_lookup_generation:
            return
        self._room_lookup_pending=False
        if not self._habbo_session_connected:
            self.coffee_users_status_var.set('Connection lost. Rejoin the Habbo room with Companion running.')
        elif self._room_lookup_parse_failed:
            self.coffee_users_status_var.set(
                'A Users packet arrived but player names could not be decoded. '
                'The room packet layout may have changed; try a manual numeric target ID.')
        elif self._room_lookup_seen:
            self.coffee_users_status_var.set(
                'A Users packet arrived without valid player IDs. '
                'Try leaving and re-entering the room with Companion connected.')
        else:
            self.coffee_users_status_var.set(
                'No Users packet arrived within 12 seconds. GetHeightMap does not guarantee '
                'a player-list response. Leave and re-enter the room while Companion is connected.')

    def _exclude_coffee_group_recipient(self):
        """Immediate opt-out; excludes are never auto-probed or re-added."""
        name=self.coffee_group_exclude_var.get().strip()
        if not name:
            self.coffee_status_var.set('Enter a username to exclude.')
            return
        current=[n.strip() for n in self.coffee_group_names_var.get().split(',') if n.strip()]
        remaining=[n for n in current if n.casefold()!=name.casefold()]
        if len(remaining)==len(current):
            self.coffee_status_var.set(f'{name} is not in the participant list.')
            return
        self.coffee_group_names_var.set(', '.join(remaining))
        self.config['coffee_group_names']=self.coffee_group_names_var.get()
        self.save()
        if self._coffee_running and self._coffee_group_active:
            if self._coffee_wait_for_hand and self._coffee_ack_phase is not None:
                self._stop_coffee_loop(
                    'Group changed during a pending handoff. Restart for remaining participants.')
                return
            targets=[v for v in self._coffee_group_targets
                     if v[0].casefold()!=name.casefold()]
            if len(targets)<2:
                self._stop_coffee_loop('Fewer than 2 group participants remain; stopped.')
                return
            try:
                seq=build_coffee_group_sequence(self.coffee_cup_one_var.get(),
                                               self.coffee_cup_two_var.get(),targets,
                                               self._coffee_active_extra_sources)
            except ValueError as exc:
                self._stop_coffee_loop('Group rotation update failed: '+str(exc))
                return
            self._coffee_generation+=1
            previous=self._coffee_after_id
            self._coffee_after_id=None
            if previous is not None:
                try:self.root.after_cancel(previous)
                except (tk.TclError,AttributeError):pass
            self._coffee_group_targets=targets
            self._coffee_sequence=seq
            self._coffee_index=0
            self._coffee_target_name=''
            self._coffee_target_room_index=None
            self._coffee_after_id=self.root.after(
                coffee_delay_ms(self._coffee_interval),
                lambda gen=self._coffee_generation:self._coffee_loop_tick(gen))
        self.coffee_status_var.set(f'{name} excluded. No automatic checks or retries.')

    def _open_coffee_recordings(self):
        """Open local recordings on Windows; never uploads recorded game data."""
        folder=APP_DIR/'coffee_sessions'
        try:
            folder.mkdir(parents=True,exist_ok=True)
            if os.name=='nt':
                os.startfile(str(folder))
            else:
                self.coffee_recording_var.set('Results folder: '+str(folder))
        except (OSError,AttributeError) as exc:
            self.coffee_recording_var.set('Cannot open results folder: '+str(exc)[:130])

    def _record_coffee_carry(self,room_index,item_type):
        """Called by G-Earth interception thread; no Tk operations allowed."""
        recorder=getattr(self,'_coffee_recorder',None)
        if recorder is None:
            return
        own_index=self._own_room_index
        target_index=self._coffee_target_room_index
        if own_index is not None and room_index==own_index:
            event=('own_held_update' if item_type>0 else 'own_empty_update')
            recorder.record(event,room_index=room_index,hand_item=item_type,
                            note='server CarryObject about own avatar')
        elif target_index is not None and room_index==target_index:
            event=('target_held_update' if item_type>0 else 'target_empty_update')
            recorder.record(event,name=self._coffee_target_name,
                            room_index=room_index,hand_item=item_type,
                            note='server CarryObject about current recipient; not receipt proof')

    def _run_coffee_speed_test(self):
        """One finite measurement for one willing recipient, no automatic speed ramp."""
        if self.coffee_group_enabled_var.get():
            self.coffee_speed_var.set(
                'Speed testing is single-recipient only. Disable group mode first.')
            return
        if self._own_room_index is None:
            self._request_own_identity()
            self.coffee_speed_var.set(
                'Cannot measure actual pickups until your avatar room index is known. '
                'Use Detect my avatar and re-enter the room if necessary.')
            return
        if self._coffee_running:
            self.coffee_speed_var.set('Press STOP before running a separate speed test.')
            return
        if not self.packet_started or not self._habbo_session_connected:
            self.coffee_speed_var.set('Connect Habbo and G-Earth before testing.')
            return
        self._start_coffee_loop(speed_test=True)

    def _start_coffee_loop(self,single_cup=False,speed_test=False):
        if self._coffee_running:
            self.coffee_status_var.set('Coffee loop already running. Click STOP first.')
            return
        if self._replay_running:
            self.coffee_status_var.set('Stop the single-packet repeater before starting.')
            return
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            if self._coffee_start_queued:
                self.coffee_status_var.set('Preparing G-Earth; the loop has not started yet.')
                return
            try:port=int(self.gearth_port_var.get())
            except (ValueError,TypeError):port=0
            if not self._gearth_extension_port_responds(port):
                self.coffee_status_var.set('G-Earth backend is offline. Start the engine.')
                return
            if not self.packet_started:self._connect_gearth(capture=False)
            if not self.packet_started:
                self.coffee_status_var.set('Could not attach packet tools.')
                return
            self._coffee_start_queued=True
            self._coffee_queued_single=bool(single_cup)
            self._coffee_queue_deadline=time.monotonic()+20
            self.coffee_status_var.set('Waiting for G-Earth and Habbo room connection.')
            self._coffee_queue_after_id=self.root.after(
                350,lambda gen=self._coffee_generation:self._check_queued_coffee_start(gen))
            return

        group_mode=bool(not single_cup and self.coffee_group_enabled_var.get())
        if speed_test and group_mode:
            self.coffee_speed_var.set('Disable group mode for the finite speed test.')
            return
        username=self.coffee_username_var.get().strip()
        if group_mode:
            try:
                group_names=parse_coffee_group_names(self.coffee_group_names_var.get())
            except ValueError as exc:
                self.coffee_status_var.set('Cannot start group: '+str(exc))
                return
            missing=next((n for n in group_names
                          if n.casefold() not in self._room_users
                          and n.casefold() not in self._room_profile_cache),None)
            if missing:
                self._lookup_coffee_profile(missing,single_cup=False)
                return
        elif (username and username.casefold() not in self._room_users
              and username.casefold() not in self._room_profile_cache):
            self._lookup_coffee_profile(
                username,single_cup=single_cup,speed_test=speed_test)
            return
        targets=[]
        try:
            extras=(() if single_cup else parse_extra_furniture_sources(
                self.coffee_extra_furniture_var.get(),
                self.coffee_cup_one_var.get(),self.coffee_cup_two_var.get()))
            if group_mode:
                for n in group_names:
                    record=self._room_users.get(n.casefold())
                    if record is None:record=self._room_profile_cache[n.casefold()]
                    targets.append((record[0],str(record[1])))
                target_name='Group rotation'
                target_id=targets[0][1]
                sequence=build_coffee_group_sequence(self.coffee_cup_one_var.get(),
                                                    self.coffee_cup_two_var.get(),targets,extras)
            else:
                target_id,target_name=self._resolve_coffee_recipient()
                sequence=build_extended_coffee_sequence(
                    self.coffee_cup_one_var.get(),self.coffee_cup_two_var.get(),
                    extras,target_id,single_cup=single_cup)
            interval=validate_coffee_interval(self.coffee_interval_var.get())
            if speed_test and self._own_room_index is None:
                raise ValueError('Cannot test verified throughput without your own '
                                 'avatar room index. Click Detect my avatar.')
            if self.coffee_wait_for_hand_var.get() and self._own_room_index is None:
                self._request_own_identity()
                use_timer=messagebox.askyesno(
                    'Waiting for your avatar ID',
                    'Companion has not yet matched your avatar to a room index. '
                    'It has requested your identity from Habbo.\n\n'
                    'Would you like to use the ORIGINAL timed coffee loop '
                    'for this run instead? It does not confirm pickup or delivery.\n\n'
                    'Yes = timed mode; No = do not send anything yet.',
                    parent=self.root)
                if not use_timer:
                    self.coffee_status_var.set(
                        'No coffee sent. Avatar detection requested; '
                        'click Start again after your room index appears.')
                    return
                self.coffee_wait_for_hand_var.set(False)
            if group_mode and interval<10:
                raise ValueError('Group mode requires at least 10 seconds per packet action.')
            cycles_text=self.coffee_cycles_var.get().strip()
            if speed_test:cycles=3
            elif single_cup:cycles=1
            else:
                if not re.fullmatch(r'[0-9]{1,5}',cycles_text):
                    raise ValueError('Cycles must be an integer from 0 to 10000.')
                cycles=int(cycles_text)
                if cycles>10000:raise ValueError('Cycles must be 0 to 10000.')
            for expr in sequence:
                packet=self.packet_extension.string_to_packet(expr)
                if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
                    raise ValueError('G-Earth could not parse a generated packet.')
        except (ValueError,TypeError,AttributeError,KeyError) as exc:
            self.coffee_status_var.set('Cannot start: '+str(exc)[:170])
            return

        duration=('3-cycle verified speed test (finite)' if speed_test else
                  'one cup' if single_cup else
                  'continuously until STOP' if cycles==0
                  else f'for {cycles} complete cycles')
        if group_mode:
            recipient_display=', '.join(n for n,_ in targets)
            presence_note=('Group mode is for people who agreed to participate. '
                           'A Habbo profile does not verify room presence. '
                           'Do not include anyone who has blocked or opted out.\n')
        else:
            recipient_display=f'{target_name or target_id} (ID {target_id})'
            profile_only=(bool(username) and username.casefold() in self._room_profile_cache
                          and username.casefold() not in self._room_users)
            presence_note=('Profile lookup confirms identity, not room presence.\n'
                           if profile_only else '')
        if not messagebox.askyesno('Give cup' if single_cup else 'Start coffee pass loop',
            f'Send coffee actions {duration}?\n'
            f'Recipient(s): {recipient_display}\n'
            f'{presence_note}'
            f'Requested delay: {interval:g} seconds\n'
            f'Tk scheduling floor: {coffee_delay_ms(interval)} ms '
            '(actual sends may take longer)\n'
            f'Wait for own-hand server updates: '
            f'{"ON" if (self.coffee_wait_for_hand_var.get() or speed_test) else "OFF"}\n'
            f'Hand-item furniture sources per cycle: {len(sequence)//2 if not group_mode else len(extras)+2}\n'
            'The speed test measures your OWN pickup/empty-hand confirmations, '
            'not receipt by another player.\n\n'
            'Only proceed with willing recipients. Habbo may reject or rate-limit actions.',
            parent=self.root):
            self.coffee_status_var.set('Coffee loop cancelled.')
            return
        self.config.update(coffee_cup_one=self.coffee_cup_one_var.get().strip(),
                           coffee_cup_two=self.coffee_cup_two_var.get().strip(),
                           coffee_recipient=self.coffee_recipient_var.get().strip(),
                           coffee_username=self.coffee_username_var.get().strip(),
                           coffee_interval=str(interval),coffee_cycles=str(cycles),
                           coffee_group_names=self.coffee_group_names_var.get().strip(),
                           coffee_group_enabled=bool(self.coffee_group_enabled_var.get()),
                           coffee_wait_for_hand=bool(self.coffee_wait_for_hand_var.get()),
                           coffee_extra_furniture=self.coffee_extra_furniture_var.get().strip())
        self.save()
        # The normal fast loop always writes a complete local CSV. Failure to
        # create the file stops startup rather than silently running unlogged.
        source_ids=(self.coffee_cup_one_var.get().strip(),) if single_cup else (
            self.coffee_cup_one_var.get().strip(),
            self.coffee_cup_two_var.get().strip(),*extras)
        recording_recipients=(targets if group_mode else
                              [(target_name or target_id,str(target_id))])
        try:
            self._coffee_recorder=CoffeeSessionRecorder(
                APP_DIR/'coffee_sessions',interval,source_ids,recording_recipients)
        except (OSError,ValueError,UnicodeError) as exc:
            self.coffee_recording_var.set(
                'Recording could not start: '+str(exc)[:140])
            self.coffee_status_var.set('No coffee sent: session recording could not start.')
            return
        self.coffee_recording_var.set(
            'Recording automatically: '+str(self._coffee_recorder.path))
        self._coffee_generation+=1
        self._coffee_running=True
        self._coffee_sequence=sequence
        self._coffee_active_extra_sources=tuple(extras)
        self._coffee_wait_for_hand=bool(self.coffee_wait_for_hand_var.get() or speed_test)
        self._coffee_speed_active=bool(speed_test)
        self._coffee_speed_started=time.monotonic() if speed_test else 0.0
        self._coffee_speed_delay=interval
        self._coffee_speed_source_attempts={}
        self._coffee_speed_source_confirmations={}
        self._coffee_speed_last_source=None
        self._coffee_speed_pickups=0
        self._coffee_speed_releases=0
        if speed_test:
            self.coffee_speed_var.set(
                f'Finite 3-cycle speed test running at {interval:g}s delay '
                'using confirmed own-avatar CarryObject events...')
        self._coffee_ack_phase=None
        self._coffee_ack_since=0.0
        self._coffee_ack_timer=None
        self._coffee_finish_after_ack=False
        self._coffee_group_active=group_mode
        self._coffee_group_targets=list(targets) if group_mode else []
        self._coffee_target_name='' if group_mode else target_name.casefold()
        self._coffee_interval=interval
        self._coffee_limit=cycles
        self._coffee_index=0
        self._coffee_sent=0
        self._coffee_completed=0
        self._coffee_pass_requests=0
        self._coffee_carry_observations=0
        self._coffee_last_pass_at=0.0
        record=self._room_users.get(target_name.casefold()) if target_name and not group_mode else None
        self._coffee_target_room_index=(record[2] if record and record[2] is not None else None)
        self.coffee_delivery_var.set(coffee_delivery_text(
            self._coffee_pass_requests,self._coffee_carry_observations,
            self._coffee_target_room_index))
        self.coffee_status_var.set(
            f'Coffee loop ON — {len(targets) if group_mode else 1} recipient(s). '
            f'Sent: 0; cycles: 0.')
        self._coffee_after_id=self.root.after(0,lambda gen=self._coffee_generation:
                                                 self._coffee_loop_tick(gen))

    def _check_queued_coffee_start(self,generation):
        self._coffee_queue_after_id=None
        if not self._coffee_start_queued or generation!=self._coffee_generation:
            return
        if self.packet_started and self.packet_extension is not None and self._habbo_session_connected:
            self._coffee_start_queued=False
            # Still asks permission before sending. Nothing runs in the background
            # simply because Habbo or G-Earth connects later.
            if getattr(self,'_coffee_queued_single',False):
                self._start_coffee_loop(single_cup=True)
            else:
                self._start_coffee_loop()
            return
        if time.monotonic()>self._coffee_queue_deadline or not self.packet_started:
            self._coffee_start_queued=False
            self.coffee_status_var.set('Connection was not ready. Join a Habbo room and press Start again.')
            return
        self._coffee_queue_after_id=self.root.after(
            350,lambda gen=generation:self._check_queued_coffee_start(gen))

    def _coffee_ack_timeout(self,generation,phase):
        """Stop instead of guessing when the server never confirms a hand action."""
        if (not self._coffee_running or generation!=self._coffee_generation
            or not self._coffee_wait_for_hand or self._coffee_ack_phase!=phase):
            return
        label=('pickup' if phase=='pickup' else 'pass/release')
        self._stop_coffee_loop(
            f'No server confirmation for your own {label} action. '
            'Cup sequence stopped; no further passes sent.')

    def _on_own_carry_update(self,room_index,item_type,observed_at):
        """Advance only after a NEW event for the local avatar's room index."""
        if (not self._coffee_running or not self._coffee_wait_for_hand
            or not carry_ack_matches(self._coffee_ack_phase,self._own_room_index,
                                     room_index,item_type,observed_at,
                                     self._coffee_ack_since)):
            return
        phase=self._coffee_ack_phase
        self._coffee_ack_phase=None
        timer=self._coffee_ack_timer
        self._coffee_ack_timer=None
        if timer is not None:
            try:self.root.after_cancel(timer)
            except (tk.TclError,AttributeError):pass
        if getattr(self,'_coffee_speed_active',False):
            if phase=='pickup':
                self._coffee_speed_pickups+=1
                source=self._coffee_speed_last_source
                if source is not None:
                    self._coffee_speed_source_confirmations[source]=(
                        self._coffee_speed_source_confirmations.get(source,0)+1)
            elif phase=='release':
                self._coffee_speed_releases+=1
        if phase=='release' and self._coffee_finish_after_ack:
            self._stop_coffee_loop(
                'Requested cycles finished; Habbo reports your hand is empty. '
                'Recipient receipt not independently confirmed.')
            return
        if phase=='pickup':
            self.coffee_status_var.set(
                f'Habbo confirms your avatar is holding an item ({item_type}). '
                'Next: pass to recipient.')
        else:
            self.coffee_status_var.set(
                'Habbo confirms your hand is empty after the pass request. '
                'Next: pick up another cup. Recipient receipt not proven.')
        self._coffee_after_id=self.root.after(
            coffee_delay_ms(self._coffee_interval),
            lambda gen=self._coffee_generation:self._coffee_loop_tick(gen))

    def _coffee_loop_tick(self,generation):
        self._coffee_after_id=None
        if not self._coffee_running or generation!=self._coffee_generation:
            return
        if self._coffee_wait_for_hand and self._coffee_ack_phase is not None:
            return  # waiting for a matching, post-action own CarryObject update
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            self._stop_coffee_loop('Habbo or G-Earth disconnected. Coffee loop stopped.')
            return
        if self._coffee_group_active:
            if len(self._coffee_group_targets)<2:
                self._stop_coffee_loop('No active group rotation; stopped.')
                return
            recipient=self._coffee_group_targets[
                (self._coffee_index//2)%len(self._coffee_group_targets)]
            self._coffee_target_name=recipient[0].casefold()
            record=self._room_users.get(self._coffee_target_name)
            self._coffee_target_room_index=(
                record[2] if record and record[2] is not None else None)
        try:
            expression=self._coffee_sequence[self._coffee_index]
            ext=self.packet_extension
            packet=ext.string_to_packet(expression)
            if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
                raise ValueError('G-Earth rejected a generated packet.')
            sent_at=time.time()
            if ext.send_to_server(packet) is False:
                raise RuntimeError('G-Earth rejected the send.')
        except Exception as exc:
            recorder=getattr(self,'_coffee_recorder',None)
            if recorder is not None:
                recorder.record('send_error',action_number=self._coffee_sent+1,
                                note=str(exc)[:160])
            self._stop_coffee_loop('Coffee loop stopped after error: '+str(exc)[:145])
            return
        self._coffee_sent+=1
        recorder=getattr(self,'_coffee_recorder',None)
        if recorder is not None:
            pickup=self._coffee_index%2==0
            match=re.search(
                r'\{out:(?:UseFurniture|PassCarryItem)\}\{i:([0-9]+)\}',
                expression)
            numeric_id=match.group(1) if match else ''
            current_name=self._coffee_target_name
            saved=recorder.record(
                'pickup_request' if pickup else 'pass_request',
                furniture=numeric_id if pickup else '',
                name=current_name,
                account_id=numeric_id if not pickup else '',
                room_index=(self._own_room_index if pickup else
                            self._coffee_target_room_index),
                action_number=self._coffee_sent,
                cycle=self._coffee_completed+1,
                note='local G-Earth send accepted; server/recipient acceptance unknown')
            if not saved:
                self._stop_coffee_loop(
                    'Automatic recording stopped unexpectedly: '+
                    str(recorder.error or 'CSV file closed')[:110])
                return
            if self._coffee_sent==1 or self._coffee_sent%25==0:
                stats=recorder.stats()
                self.coffee_recording_var.set(
                    f'Recording to {recorder.path.name} — '
                    f'{stats["pickups_sent"]} pickup requests, '
                    f'{stats["passes_sent"]} pass requests, '
                    f'{stats["own_held"]} own held-item updates. '
                    'No server confirmations required to continue.')
        if self._coffee_speed_active and self._coffee_index%2==0:
            # Count only the particular source whose UseFurniture was just sent.
            matched=re.search(r'\{out:UseFurniture\}\{i:([0-9]+)\}',expression)
            if matched:
                source=matched.group(1)
                self._coffee_speed_last_source=source
                self._coffee_speed_source_attempts[source]=(
                    self._coffee_speed_source_attempts.get(source,0)+1)
        # Odd steps are PassCarryItem. Counting a successful local send
        # does NOT establish that Habbo accepted the handoff.
        if self._coffee_index%2==1:
            self._coffee_pass_requests+=1
            self._coffee_last_pass_at=time.time()
            self.coffee_delivery_var.set(coffee_delivery_text(
                self._coffee_pass_requests,self._coffee_carry_observations,
                self._coffee_target_room_index))
        just_picked_up=(self._coffee_index%2==0)
        self._coffee_index=(self._coffee_index+1)%len(self._coffee_sequence)
        limit_reached=False
        if self._coffee_index==0:
            self._coffee_completed+=1
            limit_reached=bool(self._coffee_limit and self._coffee_completed>=self._coffee_limit)
            if limit_reached and not self._coffee_wait_for_hand:
                self._stop_coffee_loop('Requested cycles finished.')
                return
        upcoming=self._coffee_sequence[self._coffee_index]
        next_source=re.search(r'\{out:UseFurniture\}\{i:([0-9]+)\}',upcoming)
        label=(f'Pick up from {next_source.group(1)}'
               if next_source else 'Pass hand item')
        if self._coffee_group_active:
            next_recipient=self._coffee_group_targets[
                (self._coffee_index//2)%len(self._coffee_group_targets)][0]
            self.coffee_status_var.set(
                f'Group ON — next: {next_recipient} ({label}). '
                f'Sent: {self._coffee_sent}; cycles: {self._coffee_completed}.')
        else:
            self.coffee_status_var.set(f'Coffee loop ON — next: {label}. '
                                       f'Sent: {self._coffee_sent}; cycles: {self._coffee_completed}.')
        if self._coffee_running and generation==self._coffee_generation:
            if self._coffee_wait_for_hand:
                self._coffee_ack_phase=('pickup' if just_picked_up else 'release')
                self._coffee_ack_since=sent_at
                self._coffee_finish_after_ack=limit_reached
                phase=self._coffee_ack_phase
                self.coffee_status_var.set(
                    f'Waiting for Habbo server to confirm your own '
                    f'{"pickup" if phase=="pickup" else "empty hand after pass"}. '
                    f'Sent: {self._coffee_sent}; cycles: {self._coffee_completed}.')
                self._coffee_ack_timer=self.root.after(
                    8000 if phase=='pickup' else 25000,
                    lambda gen=generation,expected=phase:
                    self._coffee_ack_timeout(gen,expected))
            else:
                self._coffee_after_id=self.root.after(coffee_delay_ms(self._coffee_interval),
                    lambda gen=generation:self._coffee_loop_tick(gen))

    def _stop_coffee_loop(self,reason=None):
        recorder=getattr(self,'_coffee_recorder',None)
        self._coffee_recorder=None
        if recorder is not None:
            try:
                stats=recorder.finish(reason or 'Stopped by user')
                self.coffee_recording_var.set(
                    f'CSV + summary saved: {recorder.path.parent} | '
                    f'{stats["pickups_sent"]} pickup requests, '
                    f'{stats["passes_sent"]} pass requests, '
                    f'{stats["own_held"]} own holding updates, '
                    f'{stats["own_empty"]} own empty-hand updates. '
                    'Recipient receipt unverified.')
            except (OSError,ValueError) as exc:
                self.coffee_recording_var.set(
                    'Recording saved partially but could not finalize: '+
                    str(exc)[:140])
        if getattr(self,'_coffee_speed_active',False):
            elapsed=time.monotonic()-self._coffee_speed_started
            report=coffee_speed_test_report(
                elapsed,self._coffee_speed_pickups,self._coffee_speed_releases,
                self._coffee_pass_requests,self._coffee_speed_source_attempts,
                self._coffee_speed_source_confirmations,self._coffee_speed_delay)
            self.coffee_speed_var.set(
                ('Test ended: '+str(reason or 'stopped')+'. ')[:120]+report)
        self._coffee_speed_active=False
        self._coffee_running=False
        self._coffee_start_queued=False
        self._coffee_queued_single=False
        self._coffee_target_name=''
        self._coffee_wait_for_hand=False
        self._coffee_ack_phase=None
        self._coffee_finish_after_ack=False
        ack_timer=getattr(self,'_coffee_ack_timer',None)
        self._coffee_ack_timer=None
        if ack_timer is not None:
            try:self.root.after_cancel(ack_timer)
            except (tk.TclError,AttributeError):pass
        self._coffee_group_active=False
        self._coffee_group_targets=[]
        self._coffee_profile_pending=None
        self._coffee_profile_generation=getattr(self,'_coffee_profile_generation',0)+1
        self._coffee_generation+=1
        queued=self._coffee_queue_after_id
        self._coffee_queue_after_id=None
        if queued is not None:
            try:self.root.after_cancel(queued)
            except (tk.TclError,AttributeError):pass
        timer=self._coffee_after_id
        self._coffee_after_id=None
        if timer is not None:
            try:self.root.after_cancel(timer)
            except (tk.TclError,AttributeError):pass
        self.coffee_status_var.set(
            f'{reason or "Coffee loop stopped by user."} '
            f'Sent: {self._coffee_sent}; cycles: {self._coffee_completed}.')

    def _toggle_manipulator(self):
        if self.manipulation_enable_var.get() and not self.packet_started:
            self.manipulation_enable_var.set(False)
            self.manipulator_status.set('Connect Packet Viewer to G-Earth before enabling manipulation.')
            return
        self.manipulation_enabled=bool(self.manipulation_enable_var.get())
        self.manipulator_status.set('Rule engine ON — matching packets may be changed.' if self.manipulation_enabled
                                    else 'Rule engine OFF — no packets are changed.')

    def _refresh_manipulation_rules(self):
        self.rules_tree.delete(*self.rules_tree.get_children())
        for i,r in enumerate(self.packet_rules):
            self.rules_tree.insert('','end',iid=str(i),values=('Yes' if r['enabled'] else 'No',
               r['direction'],r['header'],r['contains'][:72],r['action']))

    def _read_manipulation_form(self):
        return validate_manipulation_rule({'enabled':self.rule_enabled_var.get(),
            'direction':self.rule_direction_var.get(),'header':self.rule_header_var.get(),
            'contains':self.rule_contains_var.get(),'action':self.rule_action_var.get(),
            'replacement':self.replace_expression.get('1.0','end').strip()})

    def _selected_manipulation_index(self):
        selected=self.rules_tree.selection()
        return int(selected[0]) if selected else None

    def _load_manipulation_rule(self,event=None):
        i=self._selected_manipulation_index()
        if i is None or not 0<=i<len(self.packet_rules):return
        r=self.packet_rules[i]
        self.rule_enabled_var.set(r['enabled']);self.rule_direction_var.set(r['direction'])
        self.rule_header_var.set(r['header']);self.rule_contains_var.set(r['contains'])
        self.rule_action_var.set(r['action'])
        self.replace_expression.delete('1.0','end');self.replace_expression.insert('1.0',r['replacement'])

    def _save_manipulation_rules(self):
        self.config['packet_rules']=[r.copy() for r in self.packet_rules]
        self.save()
        self._refresh_manipulation_rules()

    def _add_manipulation_rule(self):
        try:r=self._read_manipulation_form()
        except ValueError as e:self.manipulator_status.set(str(e));return
        if len(self.packet_rules)>=60:
            self.manipulator_status.set('Maximum 60 rules. Delete one first.');return
        self.packet_rules.append(r)
        self._save_manipulation_rules()
        self.manipulator_status.set('Rule added. '+('Engine ON.' if self.manipulation_enabled else 'Engine OFF.'))

    def _update_manipulation_rule(self):
        i=self._selected_manipulation_index()
        if i is None:self.manipulator_status.set('Select a rule first.');return
        try:r=self._read_manipulation_form()
        except ValueError as e:self.manipulator_status.set(str(e));return
        self.packet_rules[i]=r
        self._save_manipulation_rules();self.rules_tree.selection_set(str(i))
        self.manipulator_status.set('Rule updated.')

    def _delete_manipulation_rule(self):
        i=self._selected_manipulation_index()
        if i is None:self.manipulator_status.set('Select a rule to delete.');return
        self.packet_rules.pop(i);self._save_manipulation_rules()
        self.manipulator_status.set('Rule deleted.')

    def _clear_manipulation_editor(self):
        self.rules_tree.selection_remove(*self.rules_tree.selection())
        self.rule_header_var.set('');self.rule_contains_var.set('')
        self.rule_direction_var.set('Outgoing');self.rule_action_var.set('Block')
        self.rule_enabled_var.set(True);self.replace_expression.delete('1.0','end')

    def _load_packet_for_sending(self):
        rows=self.packet_tree.selection()
        if not rows:self.manipulator_status.set('Select a packet in Packet Viewer first.');return
        values=self.packet_tree.item(rows[0],'values')
        if len(values)<3:return
        for t,d,detail in reversed(self.packet_data):
            if t==values[0] and d==values[1] and detail.startswith(values[2]):
                self.inject_direction_var.set(d)
                self.inject_expression.delete('1.0','end')
                self.inject_expression.insert('1.0',detail)
                self.manipulator_status.set('Loaded packet. Review before sending.')
                return

    def _send_manual_packet(self):
        if not self.packet_started or self.packet_extension is None:
            self.manipulator_status.set('Connect Packet Viewer to G-Earth first.');return
        expr=self.inject_expression.get('1.0','end').strip()
        if not 0<len(expr)<=4096:
            self.manipulator_status.set('Enter one G-Earth packet expression (maximum 4096 characters).');return
        direction=self.inject_direction_var.get()
        if not messagebox.askyesno('Send packet once',f'Send one {direction} packet through G-Earth?\nThis may affect your game session.',parent=self.root):return
        try:
            ext=self.packet_extension
            packet=ext.string_to_packet(expr)
            if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
                raise ValueError('G-Earth could not decode the packet expression')
            success=(ext.send_to_server(packet) if direction=='Outgoing' else ext.send_to_client(packet))
            self.manipulator_status.set('Packet send requested.' if success is not False else 'G-Earth rejected the packet.')
        except Exception as exc:self.manipulator_status.set(f'Send failed: {str(exc)[:160]}')

    def _start_packet_replay(self):
        """Replay ONE user-selected outgoing packet at a controlled interval.

        Never infer a packet ID or silently repeat an arbitrary incoming packet.
        Never start before Habbo and the G-Python extension are connected.
        """
        if getattr(self,'_coffee_running',False):
            self.replay_status_var.set('Stop the coffee pass loop before starting the packet repeater.')
            return
        if self._replay_running:
            self.replay_status_var.set('Repeat already running; click STOP first.')
            return
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            self.replay_status_var.set('Enter a Habbo room and connect Packet Viewer first.')
            return
        if self.inject_direction_var.get()!='Outgoing':
            self.replay_status_var.set('Only outgoing client-to-server packets may be repeated.')
            return
        expr=self.inject_expression.get('1.0','end').strip()
        if not 0<len(expr)<=4096:
            self.replay_status_var.set('Load one outgoing cup-action packet from Packet Viewer first.')
            return
        if expr.startswith('[Block') or expr.startswith('[Replace'):
            self.replay_status_var.set('This packet contains rule annotations. Capture it without manipulation.')
            return
        try:
            delay=validate_replay_interval(self.replay_interval_var.get())
            packet=self.packet_extension.string_to_packet(expr)
            if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
                raise ValueError('G-Earth could not parse this packet. Use an outgoing packet from the viewer.')
        except (ValueError,TypeError,AttributeError) as exc:
            self.replay_status_var.set('Repeat not started: '+str(exc)[:140])
            return
        if not messagebox.askyesno('Repeat outgoing action',
            'Repeat this exact outgoing packet every '+format(delay,'.2f')+' seconds until STOP '
            'or until Habbo disconnects?\n\n'
            'Confirm this packet belongs to the cup action. '
            'It will repeatedly send a game action and may be rate-limited by Habbo.',
            parent=self.root):
            self.replay_status_var.set('Repeat cancelled.')
            return
        self._replay_generation+=1
        self._replay_running=True
        self._replay_count=0
        self._replay_expr=expr
        self._replay_interval=delay
        self.replay_status_var.set(f'Repeating outgoing cup action every {delay:g}s. Sent: 0')
        self._replay_after_id=self.root.after(0,lambda generation=self._replay_generation:
                                                 self._packet_replay_tick(generation))

    def _packet_replay_tick(self,generation):
        self._replay_after_id=None
        if not self._replay_running or generation!=self._replay_generation:
            return
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            self._stop_packet_replay('Habbo or G-Earth disconnected. Repeat automatically stopped.')
            return
        try:
            ext=self.packet_extension
            packet=ext.string_to_packet(self._replay_expr)
            if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
                raise ValueError('Packet expression became invalid.')
            success=ext.send_to_server(packet)
            if success is False:
                raise RuntimeError('G-Earth rejected the send.')
        except Exception as exc:
            self._stop_packet_replay('Repeat stopped after send error: '+str(exc)[:140])
            return
        self._replay_count+=1
        self.replay_status_var.set(
            f'Repeating outgoing action every {self._replay_interval:g}s. Sent: {self._replay_count}')
        if self._replay_running and generation==self._replay_generation:
            self._replay_after_id=self.root.after(
                round(self._replay_interval*1000),
                lambda gen=generation:self._packet_replay_tick(gen))

    def _stop_packet_replay(self,reason=None):
        self._replay_running=False
        self._replay_generation+=1
        after_id=self._replay_after_id
        self._replay_after_id=None
        if after_id is not None:
            try:self.root.after_cancel(after_id)
            except (tk.TclError,AttributeError):pass
        status=reason or 'Repeat stopped by user.'
        self.replay_status_var.set(f'{status} Sent: {self._replay_count}')

    def _select_gearth(self):
        path=filedialog.askopenfilename(title='Select G-Earth.exe or G-Earth.jar',
            filetypes=[('G-Earth program','*.exe *.jar'),('All files','*.*')])
        if path:
            self.config['gearth_path']=path
            self.gearth_path_display.set('Selected G-Earth: '+path)
            self.save()
            self.packet_status.set('G-Earth location saved. Check this is the working beta executable, not version 1.5.3.')

    def _save_gearth_auto_arm(self):
        if self.gearth_auto_arm_var.get():
            if not self._network_launch_safe() or not messagebox.askyesno(
                'Enable automatic G-Earth network interception?',
                'A previous engine session coincided with loss of Brave internet access. '
                'This can happen again. Enable automatic startup anyway?'):
                self.gearth_auto_arm_var.set(False)
        self.config['gearth_auto_arm']=bool(self.gearth_auto_arm_var.get())
        self.save()
        if self.config['gearth_auto_arm'] and not self._gearth_auto_arm_attempted:
            self.root.after(100,self._auto_prepare_gearth)

    def _select_habbo_launcher(self):
        path=filedialog.askopenfilename(title='Select your Habbo launcher (not HabboAir.swf)',
                                        filetypes=[('Windows application','*.exe'),('All files','*.*')])
        if not path:return None
        selected=Path(path)
        if selected.suffix.lower()!='.exe' or not selected.is_file():
            self.packet_status.set('Please select the Habbo launcher .exe, not the AIR .swf.')
            return None
        self.config['habbo_launcher_path']=str(selected)
        self.habbo_path_display.set('Habbo launcher: '+str(selected))
        self.save()
        return selected


    @staticmethod
    def _gearth_extension_port_responds(port):
        """A positive probe proves only that the extension socket is listening."""
        try:
            import socket
            with socket.create_connection(('127.0.0.1',int(port)),timeout=0.25):
                return True
        except (OSError,ValueError,TypeError):
            return False

    @staticmethod
    def _discover_gearth_beta():
        """Look only in conventional local install/extraction locations.

        Never silently select an obsolete 1.5.3 copy when beta versions exist.
        """
        home=Path.home()
        roots=[Path(__file__).resolve().parent,home/'Downloads',home/'Desktop',
               home/'Documents',Path(os.environ.get('LOCALAPPDATA',str(home)))/'Programs',
               Path(os.environ.get('PROGRAMFILES',r'C:\Program Files')),
               Path(os.environ.get('PROGRAMFILES(X86)',r'C:\Program Files (x86)'))]
        candidates={}
        for root in roots:
            try:
                if not root.is_dir():continue
                for pattern in ('G-Earth.exe','G-Earth*/G-Earth.exe',
                                '*G-Earth*/*/G-Earth.exe','G-Earth*/*/*/G-Earth.exe'):
                    for path in root.glob(pattern):
                        if path.is_file() and '1.5.3' not in str(path).lower():
                            candidates[str(path.resolve()).lower()]=path.resolve()
            except (OSError,PermissionError):continue
        if not candidates:return None
        def score(path):
            name=str(path).lower()
            return (int('1.5.4' in name),int('beta' in name or 'b29' in name),
                    int('g-earth' in name),-len(name))
        ranked=sorted(candidates.values(),key=score,reverse=True)
        # A top-ranked beta is safe to prefer over older or unversioned copies.
        if len(ranked)>1 and score(ranked[0])[:2]==score(ranked[1])[:2]:
            return None
        return ranked[0]

    def _auto_prepare_gearth(self):
        """Prepare the internal engine; show errors if startup cannot proceed."""
        self._engine_start_attempted=True
        if not self.gearth_auto_arm_var.get():
            self.engine_status_var.set('Engine: automatic startup disabled')
            return
        try:
            self._start_integrated_engine()
        except Exception as exc:
            self._engine_installing=False
            self._engine_last_error=f'{type(exc).__name__}: {str(exc)[:180]}'
            self.engine_status_var.set('Engine setup ERROR: '+self._engine_last_error)
            self.packet_status.set('Internal engine setup error; click Install / repair to retry.')

    def _start_integrated_engine(self):
        """Install the engine independent of whether a Habbo window was detected."""
        self._engine_start_attempted=True
        if self._engine_installing:
            self.engine_status_var.set('Engine: installation already in progress')
            return
        self._engine_last_error=''
        try:port=int(self.gearth_port_var.get())
        except (TypeError,ValueError):port=9092
        if self._gearth_extension_port_responds(port):
            self.engine_status_var.set(f'Engine backend: ONLINE (127.0.0.1:{port}); proxy WAITING state not verified')
            self.packet_status.set('G-Earth backend already running; no second engine launched.')
            self._schedule_gearth_hide(delay_ms=3000)
            return
        exe=managed_gearth_executable()
        if exe:
            self.config['gearth_path']=str(exe)
            self.gearth_path_display.set('Managed engine: '+str(exe))
            self.save()
            self.engine_status_var.set('Engine: installed; starting proxy...')
            self._start_gearth_direct(select_if_missing=False)
            return
        self._engine_installing=True
        self.engine_status_var.set('Engine: importing or downloading the managed runtime...')
        self.packet_status.set('Setting up G-Earth inside Companion. Keep Habbo closed.')
        seed=str(self.config.get('gearth_path') or '')
        threading.Thread(target=self._engine_install_worker,
                         args=(seed,),daemon=True).start()

    def _engine_install_worker(self,seed):
        def status(message):
            self._packet_put(('engine_status',message))
        try:
            exe,origin=install_managed_gearth(seed,status)
            self._packet_put(('engine_installed',str(exe),origin))
        except Exception as exc:
            self._packet_put(('engine_error',f'{type(exc).__name__}: {str(exc)[:200]}'))


    def _network_launch_safe(self):
        state=gearth_network_state()
        if not state['unsafe']:return True
        self.packet_status.set('G-Earth launch BLOCKED by network safety. Click Check Windows network.')
        self.engine_status_var.set('Network safety: inspect existing host redirects or proxy')
        return False

    def _show_network_safety(self):
        state=gearth_network_state()
        lines=['G-Earth-tagged Habbo redirects: '+str(state['redirects']),
               'Windows manual proxy enabled: '+str(state['proxy']),
               'Saved manual proxy server: '+(state['proxy_server'] or '(none)'),
               'Saved local proxy endpoint: '+str(state['local_proxy']),
               'ACTIVE local manual proxy: '+str(state['active_local_proxy'])]
        if state['error']:lines.append('Inspection error: '+state['error'])
        if state['active_local_proxy']:
            lines.append('An active local proxy may interfere with internet browsing if its service is unavailable. '
                         'Use Disable active local proxy ONLY if you do not use this proxy or VPN.')
        elif state['local_proxy']:
            lines.append('The saved localhost address is INACTIVE because the manual proxy is OFF. '
                         'No repair is needed at present.')
        lines.append('Companion does not silently change Windows proxy, DNS, firewall or VPN.')
        messagebox.showinfo('Windows network safety','\n'.join(lines))

    def _disable_local_proxy_ui(self):
        state=gearth_network_state()
        if state['error']:
            messagebox.showerror('Proxy check failed',state['error'])
            return
        if not state['active_local_proxy']:
            messagebox.showinfo('Proxy already disabled',
                'The Windows local manual proxy is OFF. The stored address is inactive and does not need repair.')
            return
        if not messagebox.askyesno('Disable active Windows localhost proxy?',
                'Windows currently routes browser traffic through the local manual proxy:\n'
                +state['proxy_server']+'\n\n'
                'Only proceed if you do not intentionally use this proxy or VPN. '
                'Companion will back up the original registry values, then change ONLY ProxyEnable to OFF. '
                'This might interrupt another program using the proxy. Continue?'):
            return
        try:
            result=disable_active_local_proxy()
            self.packet_status.set(result)
            messagebox.showinfo('Local proxy recovery',result)
        except Exception as exc:
            self.packet_status.set('Local proxy recovery failed: '+str(exc)[:190])
            messagebox.showerror('Local proxy recovery failed',str(exc)[:400])

    def _repair_gearth_hosts_ui(self):
        if os.name!='nt':return
        try:port=int(self.gearth_port_var.get())
        except (ValueError,TypeError):port=9092
        if self._gearth_extension_port_responds(port):
            messagebox.showwarning('Close G-Earth','Close G-Earth before removing host redirects.')
            return
        state=gearth_network_state()
        if state['error']:
            messagebox.showerror('Network inspection failed',state['error']);return
        if not state['redirects']:
            messagebox.showinfo('Nothing to repair','No G-Earth-tagged Habbo redirects found. System proxy untouched.')
            return
        if not messagebox.askyesno('Confirm targeted hosts repair',
            f'Remove {state["redirects"]} exact G-Earth-tagged Habbo redirect(s) and back up the full hosts file? '
            'No other network settings will change. Windows administrator permission is required.'):
            return
        try:
            APP_DIR.mkdir(parents=True,exist_ok=True)
            token=uuid.uuid4().hex
            self._network_repair_report=APP_DIR/('gearth_repair_'+token+'.json')
            shell=ctypes.WinDLL('shell32',use_last_error=True).ShellExecuteW
            shell.argtypes=(wintypes.HWND,wintypes.LPCWSTR,wintypes.LPCWSTR,
                            wintypes.LPCWSTR,wintypes.LPCWSTR,ctypes.c_int)
            shell.restype=ctypes.c_void_p
            args=subprocess.list2cmdline([str(Path(__file__).resolve()),'--repair-gearth-hosts',token])
            code=int(shell(None,'runas',sys.executable,args,str(APP_DIR),1) or 0)
            if code<=32:
                self._network_repair_report=None
                messagebox.showerror('Repair not started','Administrator permission was declined or launch failed.')
                return
            self._network_repair_deadline=time.monotonic()+60
            self.packet_status.set('Waiting for administrator repair result...')
            self.root.after(700,self._poll_network_repair)
        except (OSError,AttributeError,ValueError) as exc:
            self._network_repair_report=None
            self.packet_status.set('Repair could not start: '+str(exc)[:140])

    def _poll_network_repair(self):
        report=self._network_repair_report
        if report is None or not self.root.winfo_exists():return
        if report.is_file():
            try:
                info=json.loads(report.read_text(encoding='utf-8'))
                report.unlink(missing_ok=True)
                ok=bool(info.get('ok'));msg=str(info.get('msg','No details'))[:900]
            except (OSError,ValueError,TypeError) as exc:
                ok=False;msg='Repair result could not be read: '+str(exc)
            self._network_repair_report=None
            self.packet_status.set(('Network repair complete: ' if ok else 'Repair failed: ')+msg)
            (messagebox.showinfo if ok else messagebox.showerror)('Network repair',msg)
        elif time.monotonic()<self._network_repair_deadline:
            self.root.after(700,self._poll_network_repair)
        else:
            self._network_repair_report=None
            self.packet_status.set('No network repair result was returned. Do not assume repair succeeded.')

    def _open_managed_safe(self):
        """Troubleshooting only; normal integrated startup uses auto-connect."""
        exe=managed_gearth_executable()
        if not exe:
            self._start_integrated_engine()
            self.packet_status.set('Setting up the managed engine. Try advanced mode after setup if needed.')
            return
        self.config['gearth_path']=str(exe)
        self.save()
        self._launch_gearth(auto_connect=False,select_if_missing=False)


    def _copy_engine_diagnostic(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._diagnostic_text)
            self.packet_status.set('Diagnostic copied. Paste it into this chat.')
        except tk.TclError as exc:
            self.packet_status.set('Copy failed: '+str(exc)[:100])

    def _diagnose_and_repair(self):
        if not self._network_launch_safe():return
        if not messagebox.askyesno('Network-sensitive engine diagnostic',
            'This diagnostic can start G-Earth with administrator rights and alter Habbo routing. '
            'Brave previously lost internet after an engine startup. Continue?'):return
        if self._diagnostic_running or self._engine_installing:
            self.packet_status.set('A diagnostic or installation is already running.')
            return
        path=managed_gearth_executable()
        if not path:
            self._start_integrated_engine()
            return
        target=self._gearth_connection_target()
        if target is None:return
        self._diagnostic_running=True
        self._engine_last_error=''
        self.engine_status_var.set('Engine: diagnosing startup...')
        threading.Thread(target=self._diagnose_worker,
                         args=(str(path),target),daemon=True).start()

    def _diagnose_worker(self,exe,target):
        """Check the backend; use the tested PowerShell command only if no process."""
        host,gameport=target
        try:
            try:port=int(self.config.get('gearth_port',9092))
            except (ValueError,TypeError):port=9092
            if not 1<=port<=65535:port=9092
            probe=lambda:self._gearth_extension_port_responds(port)
            lines=['Habbo Companion engine diagnostic',
                   'UTC: '+datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'Engine EXE: '+exe,
                   'EXE exists: '+str(Path(exe).is_file()),
                   'Extension port: '+str(port),
                   'Listening before: '+str(probe()),
                   'Target host: '+host,
                   'Target game port: '+str(gameport)]
            flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
            ps_process=r"""$ErrorActionPreference='Stop'
$items=@(Get-CimInstance Win32_Process | Where-Object {
 $_.Name -match 'G-Earth' -or
 (($_.Name -eq 'java.exe' -or $_.Name -eq 'javaw.exe') -and $_.CommandLine -match 'G-Earth|gearth')
} | ForEach-Object { @{name=[string]$_.Name;pid=[int]$_.ProcessId} })
ConvertTo-Json -InputObject $items -Compress -Depth 3
"""
            known=None
            try:
                result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',ps_process],
                    capture_output=True,text=True,timeout=15,creationflags=flags)
                if result.returncode:
                    raise OSError((result.stderr or 'Process query failed')[:160])
                known=json.loads(result.stdout or '[]')
                if isinstance(known,dict):known=[known]
                lines.append('Processes: '+str(known))
            except (OSError,ValueError,TypeError,subprocess.TimeoutExpired) as exc:
                lines.append('Process query error: '+repr(exc))
            if probe():
                outcome='Backend already ONLINE. Proxy WAITING status not independently verified.'
            elif known is None:
                outcome='Cannot rule out an existing process; no duplicate launched.'
            elif known:
                outcome='Java/G-Earth running, but port '+str(port)+' is OFFLINE; no duplicate launched.'
            else:
                self._packet_put(('engine_status','No G-Earth process found; attempting the tested launch...'))
                p=Path(exe).resolve()
                quote=lambda x:"'"+str(x).replace("'","''")+"'"
                arg='--connect flash --host '+host+' --port '+str(gameport)
                cmd=("$ErrorActionPreference='Stop'; Start-Process -FilePath "+
                     quote(str(p))+" -WorkingDirectory "+quote(str(p.parent))+
                     " -ArgumentList "+quote(arg)+" -Verb RunAs -ErrorAction Stop; 'Accepted'")
                try:
                    launched=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',cmd],
                        capture_output=True,text=True,timeout=80,creationflags=flags)
                    lines.append('Launch exit code: '+str(launched.returncode))
                    lines.append('Launch output: '+(launched.stdout or launched.stderr)[:200])
                    if launched.returncode==0:
                        deadline=time.monotonic()+35
                        while time.monotonic()<deadline and not probe():
                            time.sleep(1)
                        outcome='Repair launch accepted; checking the backend.'
                    else:outcome='Repair launch failed: '+(launched.stderr or launched.stdout)[:140]
                except (OSError,subprocess.TimeoutExpired) as exc:
                    outcome='Launch error: '+str(exc)[:140]
                    lines.append(outcome)
            online=probe()
            lines+=['Listening after: '+str(online),
                    'AIR proxy WAITING state: not independently verified']
            if online:outcome='Engine backend ONLINE; proxy WAITING state not verified.'
            lines.append('RESULT: '+outcome)
            report='\n'.join(lines)+'\n'
            try:
                APP_DIR.mkdir(parents=True,exist_ok=True)
                (APP_DIR/'gearth-diagnostic-last.txt').write_text(report,encoding='utf-8')
            except OSError:pass
            self._packet_put(('engine_diagnostic_done',report,outcome))
        except Exception as exc:
            self._packet_put(('engine_diagnostic_done','Diagnostic exception: '+repr(exc),
                               'Diagnostic failed: '+str(exc)[:130]))

    def _engine_heartbeat(self):
        """Expose backend and installation state without trusting a GUI title."""
        if not self.root.winfo_exists():return
        # The Flash/AIR engine should not enable Windows' browser proxy.
        # Only watch after an engine launch accepted by Companion; never
        # silently rewrite registry settings.
        if (time.monotonic()<getattr(self,'_proxy_watch_until',0.0) and not getattr(self,'_proxy_alerted',False)):
            net=gearth_network_state()
            if net['active_local_proxy']:
                self._proxy_alerted=True
                self.gearth_auto_arm_var.set(False)
                self.config['gearth_auto_arm']=False
                self.save()
                self.engine_status_var.set('NETWORK WARNING: unexpected active Windows localhost proxy')
                self.packet_status.set('Windows local proxy was activated after G-Earth started. '
                                       'Auto-start disabled. Close G-Earth; use Disable active local proxy if appropriate.')
                messagebox.showwarning('Windows proxy unexpectedly enabled',
                    'A Windows localhost manual proxy became active after Companion started G-Earth. '
                    'This may disrupt browsing. Automatic G-Earth startup has been disabled. '
                    'Close G-Earth and use Disable active local proxy only if this was not intended.')
        if getattr(self,'_diagnostic_running',False):
            self.root.after(2500,self._engine_heartbeat)
            return
        try:port=int(self.gearth_port_var.get())
        except (TypeError,ValueError):port=9092
        if self._gearth_extension_port_responds(port):
            self._engine_last_error=''
            self.engine_status_var.set(f'Engine backend: ONLINE · extension port {port} · proxy WAITING state not independently verified')
            self._schedule_gearth_hide(delay_ms=1800)
            self._maybe_auto_connect_packet_tools()
        elif self._engine_last_error:
            self.engine_status_var.set('Engine setup ERROR: '+self._engine_last_error)
        elif not self._engine_installing:
            exe=managed_gearth_executable()
            if self._gearth_launch_watch_until>time.monotonic():
                self.engine_status_var.set('Engine: starting; waiting for backend...')
            elif exe:
                self.engine_status_var.set('Engine: installed · backend OFFLINE')
            elif not self._engine_start_attempted:
                self.engine_status_var.set('Engine: startup scheduled (not yet attempted)')
            else:
                self.engine_status_var.set('Engine: not installed. Click Install / repair to retry setup.')
        self.root.after(2500,self._engine_heartbeat)

    def _maybe_auto_connect_packet_tools(self):
        """Attach the local G-Python extension without activating Packet Viewer.

        Before Habbo launches, connecting to G-Earth's local extension port
        cannot interrupt an in-progress AIR loading screen. If Habbo is already
        open, wait for chat/room evidence. The Coffee Pass Loop Start button is
        also an explicit room-ready signal and can attach directly.
        """
        if self.packet_started or time.monotonic()<self._packet_auto_retry_after:
            return
        try:
            game_window=self.tracker.find([self.root.winfo_id(),self.overlay.winfo_id()])
        except (OSError,ValueError,AttributeError):
            game_window=None
        if game_window and self.room_id is None:
            self.packet_connection_status.set(
                'G-Earth online; waiting for Habbo room readiness. '
                'The Coffee Pass Loop Start button can connect directly.')
            return
        self._connect_gearth(capture=False)

    def _start_gearth_direct(self,select_if_missing=True):
        if os.name!='nt':
            self.packet_status.set('G-Earth background launch requires Windows.')
            return False
        if self._gearth_launch_watch_until>time.monotonic():
            self.packet_status.set('G-Earth startup is still being checked. Please do not start Habbo yet.')
            return False
        # The window title detector can mistake the Habbo launcher for AIR.
        # Do not let false matches prevent the proxy from starting.
        try:port=int(self.gearth_port_var.get())
        except (TypeError,ValueError):port=9092
        if not 1<=port<=65535:port=9092
        if self._gearth_extension_port_responds(port):
            self._gearth_auto_arm_attempted=True
            self.packet_status.set(f'G-Earth extension port {port} already responds. Skipped duplicate launch. AIR proxy connection not verified.')
            return True
        path=Path(str(self.config.get('gearth_path') or ''))
        if not path.is_file():
            discovered=self._discover_gearth_beta()
            if discovered:
                path=discovered
                self.config['gearth_path']=str(path)
                self.gearth_path_display.set('Selected G-Earth: '+str(path))
                self.save()
            elif select_if_missing:
                self._select_gearth()
                path=Path(str(self.config.get('gearth_path') or ''))
        if not path.is_file() or path.suffix.lower() not in ('.exe','.jar'):
            self.packet_status.set('Background launch needs the working G-Earth beta EXE. Click Find G-Earth to select it once.')
            return False
        if self._find_gearth_window():
            self._gearth_auto_arm_attempted=True
            self.packet_status.set('G-Earth window is running but extension port is not responding. Check the G-Earth connection before launching Habbo.')
            return True
        if not self._launch_gearth(auto_connect=True,select_if_missing=False):
            return False
        self._gearth_launch_watch_until=time.monotonic()+65
        self._gearth_launch_started=time.monotonic()
        self.root.after(850,self._poll_gearth_direct_launch)
        return True

    def _poll_gearth_direct_launch(self):
        """Do not require a visible GUI. The backend listening port is the probe."""
        if not self.root.winfo_exists():return
        try:port=int(self.gearth_port_var.get())
        except (TypeError,ValueError):port=9092
        if self._gearth_extension_port_responds(port):
            self._gearth_launch_watch_until=0.0
            # Let JavaFX finish opening normally before minimizing the window.
            # This uses the precise launch style that succeeded in PowerShell.
            if self.gearth_minimize_var.get():
                self._schedule_gearth_hide(delay_ms=1800)
            self.packet_status.set(f'G-Earth backend detected: port {port} is listening. Flash/AIR auto-connect was requested. The Habbo proxy WAITING state is not independently verified.')
            return
        if time.monotonic()<self._gearth_launch_watch_until:
            self.root.after(900,self._poll_gearth_direct_launch)
        else:
            self._gearth_launch_watch_until=0.0
            self._gearth_auto_arm_attempted=False
            if self._find_gearth_window():
                self.packet_status.set(f'G-Earth window exists but extension port {port} is still closed. Check beta startup and selected port.')
            else:
                self.packet_status.set('Windows accepted the G-Earth start request but no backend was detected within 65 seconds. Check the saved beta EXE or admin prompt; click Launch + auto-connect to retry.')

    def _hide_gearth_now(self):
        """Explicitly hide the elevated engine GUI, keeping the proxy running."""
        self.gearth_minimize_var.set(True)
        self.config['gearth_minimize']=True
        self.save()
        self._gearth_manual_window=False
        self._gearth_hide_failed=False
        self._gearth_hidden_confirmed=False
        self._gearth_hide_pending=False
        self._gearth_hide_tries=0
        self._schedule_gearth_hide(delay_ms=0)

    def _schedule_gearth_hide(self,delay_ms=3000):
        """Delay GUI hiding until the already-tested normal startup has finished."""
        if os.name!='nt' or not self.root.winfo_exists():return
        if self._gearth_hide_pending or not self.gearth_minimize_var.get():return
        if self._gearth_manual_window or self._gearth_hide_failed or self._gearth_hidden_confirmed:return
        try:port=int(self.gearth_port_var.get())
        except (ValueError,TypeError):port=9092
        if not self._gearth_extension_port_responds(port):
            return
        self._gearth_hide_pending=True
        self._gearth_hide_tries=0
        self.root.after(max(0,int(delay_ms)),self._try_hide_gearth)

    def _try_hide_gearth(self):
        """Retry G-Earth SW_HIDE and verify that its window is no longer visible."""
        if not self.root.winfo_exists() or not self._gearth_hide_pending:return
        if self._gearth_manual_window or not self.gearth_minimize_var.get():
            self._gearth_hide_pending=False
            return
        try:port=int(self.gearth_port_var.get())
        except (ValueError,TypeError):port=9092
        if not self._gearth_extension_port_responds(port):
            self._gearth_hide_pending=False
            return
        hwnd=self._find_gearth_window()
        if not hwnd:
            self._gearth_hide_tries+=1
            if self._gearth_hide_tries<12:
                self.root.after(1000,self._try_hide_gearth)
            else:
                self._gearth_hide_pending=False
                self._gearth_hide_failed=True
                self.packet_status.set('G-Earth backend is online, but its window could not be located to hide.')
            return
        user32=ctypes.WinDLL('user32',use_last_error=True)
        user32.IsWindowVisible.argtypes=[wintypes.HWND]
        user32.IsWindowVisible.restype=wintypes.BOOL
        user32.ShowWindowAsync.argtypes=[wintypes.HWND,ctypes.c_int]
        user32.ShowWindowAsync.restype=wintypes.BOOL
        if not user32.IsWindowVisible(hwnd):
            self._gearth_hidden_confirmed=True
            self._gearth_hide_pending=False
            self.packet_status.set('Engine window hidden. G-Earth keeps running; Advanced G-Earth will show it again.')
            return
        user32.ShowWindowAsync(hwnd,0)  # SW_HIDE, not SW_MINIMIZE
        self._gearth_hide_tries+=1
        if self._gearth_hide_tries<=10:
            self.root.after(1000,self._try_hide_gearth)
        else:
            self._gearth_hide_pending=False
            self._gearth_hide_failed=True
            self.packet_status.set('Windows did not confirm hiding the G-Earth window. The engine remains running. Use Advanced G-Earth if needed.')

    def _minimize_gearth_after_backend(self):
        """Compatibility with pending callbacks from older startup flows."""
        self._schedule_gearth_hide(delay_ms=0)

    def _launch_habbo_with_gearth(self):
        """Start Habbo only after the user confirms G-Earth's WAITING state.

        A timer or an open TCP extension port cannot prove that G-Earth has
        successfully prepared its AIR proxy. Don't auto-connect as a side effect
        of clicking the Habbo launcher button.
        """
        if os.name!='nt':return
        if self.tracker.find([self.root.winfo_id(),self.overlay.winfo_id()]):
            self.packet_status.set('Habbo is already running. Close it before starting a new intercepted session.')
            return
        path=Path(str(self.config.get('habbo_launcher_path') or ''))
        if not path.is_file():
            path=self._select_habbo_launcher()
            if path is None:return
        # The original G-Earth window may be hidden in single-window mode.
        try:port=int(self.gearth_port_var.get())
        except (TypeError,ValueError):port=9092
        if not self._gearth_extension_port_responds(port):
            self._start_integrated_engine()
            self.packet_status.set('The integrated engine is starting. Retry Habbo launch when the backend is online.')
            return
        if not self._find_gearth_window():
            self.packet_status.set('Engine backend online, but native window could not be located. Use Advanced settings to diagnose.')
            return
        if not messagebox.askyesno('Launch Habbo',
            'The integrated G-Earth backend is online and Flash/AIR connection was requested.\\n\\n'
            'Companion cannot independently confirm the proxy is Waiting for connection. '
            'Launch Habbo now? If needed, open Advanced settings to inspect the original engine window.'):
            self.packet_status.set('Habbo launch cancelled.')
            return
        self._finish_habbo_launch()

    def _finish_habbo_launch(self):
        self._gearth_launch_queued=False
        target=Path(str(self.config.get('habbo_launcher_path') or ''))
        if not target.is_file():
            self.packet_status.set('Habbo launcher not found; select it again.')
            return
        if not self._find_gearth_window():
            self.packet_status.set('G-Earth did not appear. Habbo was NOT launched to avoid a failed handshake.')
            return
        if self.tracker.find([self.root.winfo_id(),self.overlay.winfo_id()]):
            self.packet_status.set('Habbo is already open. No duplicate client launched.')
            return
        try:
            os.startfile(str(target))
            self.packet_status.set('Habbo launched. G-Earth should intercept the AIR session. '
                                   'If it freezes at 60%, use Advanced G-Earth and the known-working beta manual connection.')
        except OSError as exc:
            self.packet_status.set('Could not launch Habbo: '+str(exc)[:150])

    def _toggle_engine_advanced(self):
        """Use the same Companion window for all engine configuration."""
        self._engine_advanced_visible=not self._engine_advanced_visible
        if self._engine_advanced_visible:
            self._engine_advanced_panel.pack(
                fill='x',pady=(0,9),before=self._packet_search_row)
            self._engine_advanced_button.configure(text='Advanced settings ▴')
        else:
            self._engine_advanced_panel.pack_forget()
            self._engine_advanced_button.configure(text='Advanced settings ▾')

    def _return_to_single_window(self):
        self._hide_gearth_now()
        if getattr(self,'_engine_advanced_visible',False):
            self._toggle_engine_advanced()

    def _save_gearth_minimize(self):
        enabled=bool(self.gearth_minimize_var.get())
        self.config['gearth_minimize']=enabled
        self.save()
        if enabled:
            self._gearth_manual_window=False
            self._gearth_hide_failed=False
            self._gearth_hidden_confirmed=False
            self._schedule_gearth_hide(delay_ms=0)
        else:
            self._gearth_manual_window=True
            self._gearth_hide_pending=False
            self._show_gearth()

    @staticmethod
    def _find_gearth_window():
        """Find G-Earth's original top-level window by its actual title.

        Never operate on a window if its title cannot be positively identified.
        """
        if os.name!='nt':return 0
        user32=ctypes.WinDLL('user32',use_last_error=True)
        enum_windows=user32.EnumWindows
        callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        enum_windows.argtypes=[callback_type,wintypes.LPARAM]
        enum_windows.restype=wintypes.BOOL
        get_text=user32.GetWindowTextW
        get_text.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        get_text.restype=ctypes.c_int
        is_window=user32.IsWindow
        is_window.argtypes=[wintypes.HWND]
        is_window.restype=wintypes.BOOL
        found=[]
        @callback_type
        def callback(hwnd,lparam):
            if not is_window(hwnd):return True
            buf=ctypes.create_unicode_buffer(256)
            get_text(hwnd,buf,256)
            if re.match(r'^G[- ]Earth(?:\s|$)',buf.value.strip(),re.I):
                found.append(int(hwnd))
                return False
            return True
        enum_windows(callback,0)
        return found[0] if found else 0

    def _show_gearth(self):
        """Restore G-Earth without relaunching it or reconnecting the AIR proxy."""
        if os.name!='nt':return
        self._gearth_manual_window=True
        self._gearth_hide_pending=False
        self._gearth_hide_failed=False
        self._gearth_hidden_confirmed=False
        hwnd=self._find_gearth_window()
        if not hwnd:
            self.packet_status.set('G-Earth window not found. Use Start engine if the backend is offline.')
            return
        user32=ctypes.WinDLL('user32',use_last_error=True)
        user32.ShowWindowAsync.argtypes=[wintypes.HWND,ctypes.c_int]
        user32.ShowWindowAsync.restype=wintypes.BOOL
        user32.ShowWindowAsync(hwnd,5)  # SW_SHOW for a previously hidden window
        self.root.after(250,lambda h=hwnd:self._restore_gearth_window(h))
        self.packet_status.set('Advanced G-Earth shown. Auto-hide is paused until you click Hide now or restart Companion.')

    @staticmethod
    def _restore_gearth_window(hwnd):
        if os.name!='nt':return
        user32=ctypes.WinDLL('user32',use_last_error=True)
        user32.ShowWindowAsync.argtypes=[wintypes.HWND,ctypes.c_int]
        user32.ShowWindowAsync.restype=wintypes.BOOL
        user32.ShowWindowAsync(hwnd,9)  # SW_RESTORE
        user32.SetForegroundWindow.argtypes=[wintypes.HWND]
        user32.SetForegroundWindow.restype=wintypes.BOOL
        user32.SetForegroundWindow(hwnd)

    def _minimize_gearth_if_ready(self):
        """Best-effort only: do not use unsupported cross-process window parenting."""
        if not self._gearth_autostart_active or not self.gearth_minimize_var.get():return
        hwnd=self._find_gearth_window()
        if hwnd:
            user32=ctypes.WinDLL('user32',use_last_error=True)
            user32.ShowWindowAsync.argtypes=[wintypes.HWND,ctypes.c_int]
            user32.ShowWindowAsync.restype=wintypes.BOOL
            user32.ShowWindowAsync(hwnd,6) # SW_MINIMIZE; don't hide an elevated process invisibly
            return
        self._gearth_minimize_tries+=1
        if self._gearth_minimize_tries<15:
            self.root.after(900,self._minimize_gearth_if_ready)

    def _connect_habbo_air(self):
        """Start the managed engine instead of requiring a separately selected EXE."""
        self._start_integrated_engine()

    def _gearth_connection_target(self):
        host=self.gearth_host_var.get().strip().lower()
        raw_port=self.gearth_game_port_var.get().strip()
        if not re.fullmatch(r'[a-z0-9.-]{3,253}',host) or host.startswith('.') or '..' in host:
            self.packet_status.set('Enter a valid hotel hostname, e.g. game-us.habbo.com.')
            return None
        try:port=int(raw_port)
        except ValueError:port=0
        if not 1<=port<=65535:
            self.packet_status.set('Enter a valid Habbo game port, e.g. 30000.')
            return None
        self.config['gearth_host']=host
        self.config['gearth_game_port']=port
        self.save()
        return host,port

    def _launch_gearth(self,auto_connect=False,select_if_missing=True):
        """Run only G-Earth elevated; never elevate the whole chat companion.

        G-Earth's own ConnectionController supports --connect flash (AIR).
        No extension flag is passed as a proxy port; the extension port is separate.
        """
        if not self._network_launch_safe():return False
        path=Path(str(self.config.get('gearth_path') or ''))
        if not path.is_file() and select_if_missing:
            self._select_gearth()
            path=Path(str(self.config.get('gearth_path') or ''))
        if not path.is_file():
            self.packet_status.set('Choose the working G-Earth beta with Find G-Earth first.')
            return False
        if path.suffix.lower() not in ('.exe','.jar'):
            self.packet_status.set('Please select G-Earth.exe (or the G-Earth .jar).')
            return False
        if os.name!='nt':
            self.packet_status.set('This launcher currently supports Windows only.')
            return False
        if self._find_gearth_window():
            self.packet_status.set('G-Earth is already running. No duplicate launch.')
            return False
        try:
            path=path.resolve()
            if auto_connect:
                target=self._gearth_connection_target()
                if target is None:return False
                host,game_port=target
                connection_args=['--connect','flash','--host',host,'--port',str(game_port)]
            else:
                connection_args=[]
            if path.suffix.lower()=='.jar':
                import shutil
                java=shutil.which('javaw.exe') or shutil.which('java.exe')
                if java is None:
                    self.packet_status.set('Java missing. Install Java or choose G-Earth.exe.')
                    return False
                program=java
                parameters=subprocess.list2cmdline(['-jar',str(path)]+connection_args)
            else:
                program=str(path)
                parameters=subprocess.list2cmdline(connection_args) if connection_args else None

            shell32=ctypes.WinDLL('shell32',use_last_error=True)
            execute=shell32.ShellExecuteW
            execute.argtypes=(wintypes.HWND,wintypes.LPCWSTR,wintypes.LPCWSTR,
                              wintypes.LPCWSTR,wintypes.LPCWSTR,ctypes.c_int)
            execute.restype=ctypes.c_void_p
            ctypes.set_last_error(0)
            # The same normal-window launch behavior as the successful
            # PowerShell Start-Process -Verb RunAs test. JavaFX can initialize
            # incorrectly when asked to start minimized (SW_SHOWMINNOACTIVE=7).
            # Minimize only after the extension backend has started responding.
            result=execute(None,'runas',program,parameters,str(path.parent),1)
            if int(result or 0)<=32:
                error=ctypes.get_last_error()
                if error==1223 or int(result or 0)==5:
                    self.packet_status.set('Administrator permission declined; nothing was started.')
                else:
                    self.packet_status.set(f'Could not launch G-Earth (Windows error {error or int(result or 0)}).')
                return False
            self._proxy_watch_until=time.monotonic()+600  # monitor for unexpected system proxy activation
            self._proxy_alerted=False
            self._gearth_autostart_active=bool(auto_connect)
            self._gearth_manual_window=False
            self._gearth_hide_pending=False
            self._gearth_hide_failed=False
            self._gearth_hidden_confirmed=False
            self._gearth_auto_arm_attempted=True  # prevent racing a queued startup probe
            self._gearth_started_at=time.monotonic()
            if auto_connect:
                # Never attach G-Python during Habbo's initial AIR handshake.
                # A successful ShellExecuteW request does not prove that JavaFX
                # or the G-Earth proxy actually started.
                self.packet_status.set(f'Windows accepted the G-Earth start request for {host}:{game_port}. Checking whether the extension backend starts; no packet viewer attached.')
            else:
                self.packet_status.set(f'Opened {path.name} without auto-connect flags. In G-Earth, select Flash/AIR, '
                                       'check game-us.habbo.com:30000 and click Connect before starting Habbo.')
            return True
        except (OSError,ValueError,AttributeError) as exc:
            self.packet_status.set('G-Earth launch failed: '+str(exc)[:130])
            return False

    def _await_gearth_viewer(self,deadline):
        """Do not start a socket extension before the backend's port is listening."""
        if self.packet_started:return
        try:
            port=int(self.gearth_port_var.get())
            if not 1<=port<=65535:raise ValueError()
        except ValueError:
            self.packet_status.set('Invalid extension port; open advanced controls to verify it.')
            return
        try:
            import socket
            with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                ready=sock.connect_ex(('127.0.0.1',port))==0
        except OSError:
            ready=False
        if ready:
            self._connect_gearth()
        elif time.monotonic()<deadline:
            self.root.after(1200,lambda:self._await_gearth_viewer(deadline))
        else:
            self.packet_status.set('G-Earth started, but extension port was not reachable. '
                                   'Use Advanced G-Earth window to check the connection and port.')

    def _connect_gearth(self,capture=True):
        # The same G-Earth extension serves all packet tools. Capturing is
        # optional; auto-connect never enables the packet log or rules.
        if self.packet_started:
            if capture:
                self.packet_active=True
                self.packet_status.set('Packet tools already attached. Viewer capture resumed.')
            return True
        try:
            port=int(self.gearth_port_var.get())
            if not 1<=port<=65535:raise ValueError()
        except ValueError:
            self.packet_status.set('Enter a valid G-Earth extension port (usually 9092).')
            self.packet_connection_status.set('Invalid G-Earth extension port (usually 9092).')
            return False
        self.config['gearth_port']=port
        self.save()
        try:
            import g_python.gextension  # noqa: F401
        except ImportError:
            self.packet_status.set('Install G-Python once with: py -m pip install g-python')
            self.packet_connection_status.set('G-Python missing. Install once with: py -m pip install g-python')
            self._packet_auto_retry_after=time.monotonic()+15
            return False
        self.packet_active=bool(capture)
        self.packet_started=True
        self._account_attached_port=port
        self.packet_connection_status.set(f'Connecting packet tools to G-Earth on port {port}...')
        self.packet_status.set(f'Connecting extension on local port {port}...')
        threading.Thread(target=self._packet_worker,args=(port,),daemon=True).start()
        return True

    def _packet_worker(self,port):
        try:
            from g_python.gextension import Extension
            from g_python.hmessage import Direction
            info={'title':'Habbo Companion Packet Tools',
                  'description':'Packet viewer with optional session rules and manual send',
                  'version':'1.1.10','author':'Habbo Companion'}
            ext=Extension(info,['-p',str(port)])
            self.packet_extension=ext
            def event(name):
                self._packet_put(('status',name))
            ext.on_event('init',lambda:event('G-Earth extension connected.'))
            def connected():
                self._habbo_session_connected=True
                self._packet_put(('session_connection',True))
                self._packet_put(('room_users_reset',))
                event('Habbo AIR connected; capturing packets in Habbo Companion.')
            ext.on_event('connection_start',connected)
            def disconnected():
                self._habbo_session_connected=False
                self.manipulation_enabled=False
                self._packet_put(('session_connection',False))
                self._packet_put(('manip_status','G-Earth disconnected. Manipulation automatically OFF.'))
                self._packet_put(('manip_off',))
                event('Habbo traffic disconnected.')
            ext.on_event('connection_end',disconnected)
            def hook(direction):
                def on_message(msg):
                    if self.fuzz_monitoring:
                        try:
                            mid=int(msg.packet.header_id())
                            raw=getattr(msg.packet,'bytearray',None)
                            if 0<=mid<=65535 and isinstance(raw,(bytes,bytearray)):
                                self._packet_put(('fuzz_observation',direction,mid,len(raw)))
                        except (ValueError,TypeError,AttributeError):
                            pass
                    if not (self.packet_active or self.manipulation_enabled or
                            self.config.get('whispers_right',True) or direction=='Incoming'
                            or (self.responder.enabled and self._responder_chat_template is None)):
                        return
                    try:detail=str(msg.packet.g_string(ext))
                    except Exception:detail='[Packet could not be formatted]'
                    # g_string() is a raw/legacy byte rendering. The previous
                    # gate incorrectly looked for {out:Chat} in that string,
                    # so it could never learn the outgoing Chat packet.
                    # G-Earth's *expression* contains the named Chat header.
                    if (direction=='Outgoing' and self.responder.enabled
                        and self._responder_chat_template is None):
                        if not self._responder_outgoing_seen:
                            self._responder_outgoing_seen=True
                            self._packet_put(('responder_outgoing_seen',))
                        try:
                            observed=msg.packet.g_expression(ext)
                            # Only learn an explicitly named outgoing Chat
                            # with a string field. No guessing packet IDs.
                            if (isinstance(observed,str) and
                                chat_expression_from_template(observed,'probe') is not None):
                                self._packet_put(('responder_chat_template',observed))
                        except Exception:
                            pass
                    if direction=='Outgoing' and self._coffee_furniture_capture_pending:
                        captured=outgoing_furniture_id_from_packet(
                            ext,Direction.TO_SERVER,msg.packet)
                        if captured is not None:
                            self._coffee_furniture_capture_pending=False
                            self._packet_put(('coffee_source_captured',captured))
                    if direction=='Incoming':
                        kind=classify_room_packet(ext,Direction.TO_CLIENT,msg.packet,detail)
                        if kind=='RoomReady':
                            self._packet_put(('room_users_reset',))
                        elif kind=='UserRemove':
                            room_index=removed_room_user_index(detail)
                            if room_index is None:
                                try:room_index=int(msg.packet.read_string(6))
                                except (IndexError,ValueError,TypeError,AttributeError):pass
                            if room_index is None:
                                try:
                                    room_index=removed_room_user_index(
                                        msg.packet.g_expression(ext))
                                except (ValueError,TypeError,AttributeError):
                                    pass
                            self._packet_put(('room_user_removed',room_index))
                        elif kind=='UserObject':
                            identity=own_identity_from_packet(msg.packet)
                            if identity is not None:
                                self._packet_put(('coffee_self_identity',identity[0],identity[1]))
                        elif kind=='ExtendedProfile':
                            profile=profile_recipient_from_packet(msg.packet)
                            if profile is not None:
                                self._packet_put(('coffee_profile',profile[0],profile[1]))
                        elif kind=='CarryObject':
                            carry=carry_object_from_packet(msg.packet)
                            if carry is not None:
                                self._record_coffee_carry(carry[0],carry[1])
                                self._packet_put(('coffee_carry_observed',carry[0],
                                                  carry[1],time.time()))
                        elif kind=='Users':
                            # g_string() is the legacy raw rendering. Use
                            # g_expression() for {i:ID}{s:"username"} fields,
                            # plus the actual binary count/id/name prefix as a
                            # fallback when G-Earth predicts the rest incorrectly.
                            verified_prefix=first_room_user_from_raw_packet(msg.packet)
                            users={}
                            try:
                                predicted=msg.packet.g_expression(ext)
                                if isinstance(predicted,str):
                                    users.update(room_user_ids_from_packet(
                                        predicted,trusted_users=True))
                            except Exception:
                                pass
                            # The actual binary prefix takes precedence over
                            # G-Earth's best-effort predicted expression.
                            users.update(verified_prefix)
                            users.update(full_room_users_from_packet(msg.packet))
                            # Trust only name/account pairs already parsed by the
                            # named Users header, plus our own confirmed identity.
                            trusted=dict(users)
                            if self._own_account_id is not None and self._own_name:
                                trusted.setdefault(
                                    self._own_name.casefold(),
                                    (self._own_name,self._own_account_id,None))
                            users.update(room_users_from_binary_prefixes(
                                msg.packet,trusted))
                            raw=getattr(msg.packet,'bytearray',None)
                            if isinstance(raw,(bytes,bytearray)) and len(raw)<=500000:
                                self._packet_put(('room_users_binary',bytes(raw)))
                            self._packet_put(('room_users_observed',bool(users)))
                            if users:self._packet_put(('room_users',users))
                    if self.config.get('whispers_right',True):
                        whisper_body=whisper_packet_text(detail)
                        if whisper_body is not None:
                            self._packet_put(('whisper_hint',time.time(),whisper_body))
                    if not self.packet_active and not self.manipulation_enabled:
                        return
                    if self.manipulation_enabled and self.packet_rules:
                        try:
                            matched=apply_manipulation_rule(msg,direction,detail,
                                                            tuple(self.packet_rules),ext)
                            if matched:
                                detail=f'[{matched[0]} rule {matched[1]}] '+detail
                        except Exception as exc:
                            self._packet_put(('manip_status',f'Rule error; packet unchanged: {str(exc)[:160]}'))
                    if self.packet_active:
                        self._packet_put(('packet',datetime.now().strftime('%H:%M:%S'),direction,detail[:4000]))
                return on_message
            ext.intercept(Direction.TO_CLIENT,hook('Incoming'))
            ext.intercept(Direction.TO_SERVER,hook('Outgoing'))
            ext.start()
        except Exception as exc:
            self.packet_started=False
            self._habbo_session_connected=False
            self.packet_extension=None
            self._account_attached_port=None
            self._packet_auto_retry_after=time.monotonic()+10
            self._packet_put(('session_connection',False))
            self._packet_put(('packet_connect_error',f'{type(exc).__name__}: {str(exc)[:160]}'))
            self._packet_put(('status',f'G-Earth connection failed: {type(exc).__name__}: {str(exc)[:190]}'))

    def _packet_put(self,item):
        try:self.packet_queue.put_nowait(item)
        except queue.Full:pass  # never block the Habbo packet interception thread

    def _pump_packets(self):
        if not self.root.winfo_exists():return
        for _ in range(150):
            try:item=self.packet_queue.get_nowait()
            except queue.Empty:break
            if item[0]=='fuzz_observation':
                _,direction,mid,size=item
                key=(direction,mid)
                record=self.fuzz_counts.setdefault(key,{'count':0,'min':size,'max':size})
                record['count']+=1
                record['min']=min(record['min'],size)
                record['max']=max(record['max'],size)
                self.fuzz_seen+=1
                if self.fuzz_seen%25==0:
                    self.fuzz_live_var.set(f'Read-only: {self.fuzz_seen} packets, '
                                           f'{len(self.fuzz_counts)} direction/ID groups.')
                continue
            if item[0]=='arcturus_result':
                self.fuzz_running=False
                result=item[1]
                self.arcturus_status_var.set(
                    f"Arcturus localhost test finished: "
                    f"{result['requests']} packets sent (limit {result['case_limit']}). "
                    f"Report: {result['boofuzz_db']}. "
                    "Emulator acceptance not established.")
                continue
            if item[0]=='arcturus_error':
                self.fuzz_running=False
                self.arcturus_status_var.set(item[1])
                continue
            if item[0]=='fuzz_result':
                self.fuzz_running=False
                self.fuzz_last_result=item[1]
                result=item[1]
                self.fuzz_lab_var.set(
                    f"Lab boofuzz done: {result['requests']} requests; "
                    f"{result['accepted']} accepted / {result['rejected']} rejected. "
                    f"Results: {result['scope']}.")
                continue
            if item[0]=='fuzz_error':
                self.fuzz_running=False
                self.fuzz_lab_var.set(item[1])
                continue
            if item[0]=='fuzz_analysis':
                self.fuzz_lab_var.set('Ollama: '+item[1])
                continue
            if item[0]=='classic_ws_probe':
                self._classic_probe_running=False
                self.tcp_status_var.set(item[1])
                self._tcp_log_event('classic',item[1])
                continue
            if item[0] in ('tcp_state','tcp_connected','tcp_failed','tcp_packet'):
                event,ident,generation=item[:3]
                if generation!=self._tcp_generation.get(ident,0):
                    if event=='tcp_connected': item[3].close()
                    continue
                if event=='tcp_state':
                    self._tcp_states[ident]=item[3]
                    self.tcp_status_var.set(item[3])
                    self._tcp_log_event(ident,item[3])
                    self._tcp_render()
                elif event=='tcp_connected':
                    self._tcp_sessions[ident]=item[3]
                    self._tcp_inflight.discard(ident)
                    if item[3].authenticated:
                        self._tcp_states[ident]='Authenticated (direct TCP)'
                        self.tcp_status_var.set(
                            'Habbo sent AuthenticationOK; session is active.')
                    else:
                        self._tcp_states[ident]='Authentication succeeded, '
                        self._tcp_states[ident]+='but the game socket closed.'
                        self.tcp_status_var.set(self._tcp_states[ident])
                    self._tcp_log_event(ident,self._tcp_states[ident])
                    self._tcp_render()
                elif event=='tcp_failed':
                    self._tcp_inflight.discard(ident)
                    self._tcp_states[ident]='Connection failed: '+item[3]
                    self.tcp_status_var.set(self._tcp_states[ident])
                    self._tcp_log_event(ident,self._tcp_states[ident])
                    self._tcp_render()
                elif event=='tcp_packet':
                    self._tcp_log_event(ident,
                        f'Incoming packet ID {item[3]} ({item[4]} bytes)')
                continue
            if item[0]=='direct_ticket_fetched':
                self._direct_ticket_fetch_running=False
                ident,ticket=item[1],item[2]
                if any(a['id']==ident for a in self._account_profiles):
                    # Reject an accidental copy of another account's ticket.
                    if any(v.secret==ticket.secret and key!=ident
                           for key,v in self._direct_ticket_queue.items()):
                        self.direct_status_var.set(
                            'Duplicate ticket returned for two profiles; '
                            'second ticket was not queued.')
                    else:
                        self._direct_ticket_queue[ident]=ticket
                        self._direct_launch_states.pop(ident,None)
                        self._direct_render()
                        self.direct_status_var.set(
                            'Temporary SSO ticket fetched from the existing '
                            'signed-in Habbo profile and queued locally. '
                            'Confirm this browser profile belongs to the '
                            'selected account; server login is not yet verified.')
                continue
            if item[0]=='direct_ticket_fetch_failed':
                self._direct_ticket_fetch_running=False
                self.direct_status_var.set(
                    'Ticket was not fetched: '+item[2])
                continue
            if item[0]=='direct_launch_state':
                ident,status=item[1],item[2]
                self._direct_launch_states[ident]=status
                if self.direct_table.exists(ident):
                    self.direct_table.set(ident,'ticket_state',status)
                continue
            if item[0]=='direct_launch_status':
                self.direct_status_var.set(item[1])
                continue
            if item[0]=='direct_launch_finished':
                self._direct_launch_running=False
                continue
            if item[0]=='headless_state':
                ident,status=item[1],item[2]
                self._headless_account_states[ident]=status
                if self.headless_table.exists(ident):
                    self.headless_table.set(ident,'state',status)
                continue
            if item[0]=='headless_status':
                self.headless_status_var.set(item[1])
                continue
            if item[0]=='account_auto_status':
                if item[1]==self._account_auto_generation:
                    self.account_status_var.set(item[2])
                continue
            if item[0]=='account_auto_stage':
                if item[1]==self._account_auto_generation:
                    self._account_run_states[item[2]]=item[3]
                    if self.account_table.exists(item[2]):
                        self.account_table.set(item[2],'launch_state',item[3])
                continue
            if item[0]=='account_remaining':
                if item[1]==self._account_auto_generation:
                    self._account_remaining_ids=tuple(item[2])
                    self._account_resume_requires_manual=bool(item[3])
                continue
            if item[0]=='account_auto_finished':
                if item[1]==self._account_auto_generation:
                    self._account_auto_running=False
                continue
            if item[0]=='engine_diagnostic_done':
                self._diagnostic_running=False
                self._diagnostic_text=item[1]
                self.engine_status_var.set(item[2])
                self.packet_status.set('Diagnosis completed. Click Copy diagnostic if backend is offline.')
                continue
            if item[0]=='engine_status':
                self.engine_status_var.set('Engine setup: '+item[1])
                continue
            if item[0]=='engine_error':
                self._engine_installing=False
                self._engine_last_error=item[1]
                self.engine_status_var.set('Engine setup ERROR: '+item[1])
                self.packet_status.set('Engine setup failed; use Install / repair to retry. '+item[1])
                continue
            if item[0]=='engine_installed':
                self._engine_installing=False
                self._engine_last_error=''
                self.config['gearth_path']=item[1]
                self.gearth_path_display.set('Managed engine: '+item[1])
                self.save()
                self.engine_status_var.set('Engine installed from '+item[2]+'. Starting...')
                self._start_gearth_direct(select_if_missing=False)
                continue
            if item[0]=='status':
                self.packet_status.set(item[1]);continue
            if item[0]=='packet_connect_error':
                self.packet_connection_status.set('Packet tools failed: '+item[1])
                continue
            if item[0]=='responder_outgoing_seen':
                self._responder_log(
                    'G-Earth observed outgoing traffic; looking for a named Chat packet.')
                continue
            if item[0]=='responder_chat_template':
                self._responder_chat_template=item[1]
                self._responder_log('Outgoing Chat format learned from Habbo.')
                continue
            if item[0]=='whisper_hint':
                _,occurred,body=item
                # The packet and AIR feed may arrive in either order.
                for msg in reversed(self.messages[-24:]):
                    if abs(msg.arrived-occurred)>8:
                        continue
                    if not msg.chat_type_explicit and chat_one_line(msg.body)==body:
                        msg.chat_type=1
                        break
                else:
                    if not any(t==body and abs(at-occurred)<0.4
                               for at,t in self.whisper_hints):
                        self.whisper_hints.append((occurred,body))
                        self.whisper_hints=self.whisper_hints[-32:]
                continue
            if item[0]=='coffee_source_captured':
                self._receive_captured_furniture(item[1])
                continue
            if item[0]=='coffee_profile':
                self._accept_coffee_profile(item[1],item[2])
                continue
            if item[0]=='coffee_self_identity':
                self._own_identity_pending=False
                self._own_account_id=item[1]
                self._own_name=item[2]
                own=self._room_users.get(self._own_name.casefold())
                self._own_room_index=(
                    own[2] if own is not None and own[1]==self._own_account_id
                    else None)
                if self._own_room_index is None:
                    self._recover_own_room_index_from_snapshot()
                if self._own_room_index is not None:
                    self.coffee_own_status_var.set(
                        f'Your avatar: {self._own_name} — room index {self._own_room_index}')
                else:
                    self.coffee_own_status_var.set(
                        f'Account confirmed: {self._own_name} (ID {self._own_account_id}); '
                        'waiting for a room Users packet with a valid avatar index. '
                        'Re-enter the room if needed.')
                continue
            if item[0]=='coffee_carry_observed':
                _,room_index,item_type,seen_at=item
                self._on_own_carry_update(room_index,item_type,seen_at)
                if (self._coffee_pass_requests>0
                    and self._coffee_target_room_index is not None
                    and room_index==self._coffee_target_room_index
                    and item_type>0 and 0<=seen_at-self._coffee_last_pass_at<=4):
                    self._coffee_carry_observations+=1
                    self.coffee_delivery_var.set(coffee_delivery_text(
                        self._coffee_pass_requests,self._coffee_carry_observations,
                        self._coffee_target_room_index))
                continue
            if item[0]=='room_users_reset':
                self._own_room_index=None
                self._last_room_users_binary=None
                self.coffee_own_status_var.set(
                    'Your avatar room index: unknown after room change; waiting for Users.')
                self._room_users.clear()
                self._room_chat_names.clear()
                self._responder_room_speakers.clear()
                self._room_profile_cache.clear()
                self._responder_reset_room_targets()
                self._coffee_profile_pending=None
                self._coffee_profile_generation+=1
                self._coffee_target_room_index=None
                self._coffee_last_pass_at=0.0
                self._room_lookup_pending=False
                self._room_lookup_generation+=1
                self.coffee_users_status_var.set('Room users cleared. Waiting for the current room snapshot...')
                if self._coffee_running:
                    self._stop_coffee_loop('Room changed; coffee pass stopped for safety.')
                continue
            if item[0]=='room_users_binary':
                self._last_room_users_binary=item[1]
                if self._own_account_id is not None and self._own_room_index is None:
                    self._recover_own_room_index_from_snapshot()
                continue
            if item[0]=='room_users_observed':
                self._room_lookup_seen=True
                if not item[1]:
                    self._room_lookup_parse_failed=True
                    self.coffee_users_status_var.set(
                        'Users packet received, but no valid usernames decoded. '
                        'This may be a new Habbo packet layout.')
                continue
            if item[0]=='room_users':
                self._room_users=merge_room_user_records(
                    self._room_users,item[1])
                observed_at=time.time()
                for user_key in item[1]:
                    self._responder_room_roster_seen_at[user_key]=observed_at
                self._responder_refresh_room_users()
                if self._own_account_id is not None:
                    own=next((user for user in item[1].values()
                              if user[1]==self._own_account_id
                              and user[2] is not None),None)
                    if own is not None:
                        self._own_room_index=own[2]
                        self.coffee_own_status_var.set(
                            f'Your avatar: {self._own_name} — room index {own[2]}')
                self._room_lookup_pending=False
                self.coffee_users_status_var.set(
                    f'{len(self._room_users)} player(s) detected in this room. Enter an exact username.')
                if self._own_account_id is None:
                    self._request_own_identity()
                elif self._own_room_index is None:
                    self.coffee_own_status_var.set(
                        f'Your account {self._own_name} is known, but its room index '
                        'has not been decoded. Re-enter the room with G-Earth connected.')
                continue
            if item[0]=='room_user_removed':
                index=item[1]
                if self._own_room_index is not None and index==self._own_room_index:
                    self._own_room_index=None
                    self.coffee_own_status_var.set(
                        'Your avatar left the room; own hand monitoring unavailable.')
                    if self._coffee_running and self._coffee_wait_for_hand:
                        self._stop_coffee_loop('Your avatar left the room; verified cup loop stopped.')
                self._room_users,removed=remove_room_user_by_index(self._room_users,index)
                for name in removed:
                    self._room_chat_names.discard(name)
                    self._responder_room_speakers.pop(name,None)
                    self._responder_room_roster_seen_at.pop(name,None)
                    self._room_profile_cache.pop(name,None)
                self._responder_remove_departed_targets(removed)
                if self._coffee_running and self._coffee_group_active:
                    # A server-confirmed departure is an automatic exclusion,
                    # not evidence of a block. Never retry that recipient.
                    for departed in removed:
                        if any(n.casefold()==departed
                               for n,_ in self._coffee_group_targets):
                            self.coffee_group_exclude_var.set(departed)
                            self._exclude_coffee_group_recipient()
                    if index is None and self._coffee_running:
                        self._stop_coffee_loop(
                            'Player departure could not be identified; group stopped.')
                elif (self._coffee_running and self._coffee_target_name
                      and (self._coffee_target_name in removed or index is None)):
                    self._stop_coffee_loop(
                        'Recipient may have left; coffee pass stopped pending re-verification.')
                self.coffee_users_status_var.set(
                    f'{len(self._room_users)} player(s) mapped. '
                    'A player left; unrelated players remain mapped.')
                continue
            if item[0]=='session_connection':
                self._fuzz_refresh_connected_server()
                self.packet_connection_status.set(
                    'Packet tools READY — Habbo and G-Earth connected.' if item[1]
                    else 'Packet tools attached; waiting for Habbo room connection.')
                if item[1]:
                    # New AIR connection; never reuse a prior Chat packet ID.
                    self._responder_chat_template=None
                    self._responder_outgoing_seen=False
                if not item[1]:
                    self._responder_chat_template=None
                    self._responder_outgoing_seen=False
                    self._responder_generation+=1
                    self.responder.running=False
                    self.responder.reset_room()
                    self._coffee_furniture_capture_pending=False
                    self._own_account_id=None
                    self._own_name=''
                    self._own_room_index=None
                    self._own_identity_pending=False
                    self._own_identity_last_request=0.0
                    self.coffee_own_status_var.set(
                        'Your avatar room index unavailable until Habbo reconnects.')
                    self._room_users.clear()
                    self._last_room_users_binary=None
                    self._room_chat_names.clear()
                    self._responder_room_speakers.clear()
                    self._room_profile_cache.clear()
                    self._responder_reset_room_targets()
                    self._coffee_profile_pending=None
                    self._coffee_profile_generation+=1
                    self._room_lookup_pending=False
                    self._room_lookup_generation+=1
                    self.coffee_users_status_var.set('Disconnected. Room users cleared.')
                    self._stop_packet_replay('Habbo connection ended. Repeat stopped.')
                    self._stop_coffee_loop('Habbo connection ended. Coffee loop stopped.')
                continue
            if item[0]=='manip_status':
                self.manipulator_status.set(item[1]);continue
            if item[0]=='manip_off':
                self.manipulation_enable_var.set(False);continue
            _,timestamp,direction,detail=item
            self.packet_data.append((timestamp,direction,detail))
            if len(self.packet_data)>500:self.packet_data.pop(0)
            needle=self.packet_filter_var.get().lower().strip()
            if needle and needle not in detail.lower():continue
            self.packet_tree.insert('', 'end',values=(timestamp,direction,detail[:145]))
            children=self.packet_tree.get_children()
            if len(children)>500:self.packet_tree.delete(*children[:len(children)-500])
        self.root.after(200,self._pump_packets)

    def _select_packet(self,event=None):
        rows=self.packet_tree.selection()
        if not rows:return
        values=self.packet_tree.item(rows[0],'values')
        if not values:return
        # Viewer uses only local packet data, with no remote requests or changes.
        self.packet_details.delete('1.0','end')
        # Treeview values contain a shortened preview; search the recent in-memory
        # records for the selected row's complete message representation.
        full=next((d for t,dirn,d in reversed(self.packet_data)
                   if t==values[0] and dirn==values[1] and d.startswith(values[2])),values[2])
        self.packet_details.insert('1.0',full)

    def _toggle_capture(self):
        if not self.packet_started:
            self.packet_status.set('Connect to G-Earth before pausing or resuming packet capture.')
            return
        self.packet_active=not self.packet_active
        self.packet_status.set('Packet viewer capturing.' if self.packet_active else 'Packet viewer paused.')

    def _clear_packets(self):
        self.packet_data.clear()
        self.packet_tree.delete(*self.packet_tree.get_children())
        self.packet_details.delete('1.0','end')

    def _export_packets(self):
        if not self.packet_data:
            self.packet_status.set('No packets captured yet.')
            return
        # Default NO is metadata-only, never chat text, tickets or raw data.
        # Advanced users can explicitly opt into a content export for their
        # own offline debugging, but should not share that version.
        raw=messagebox.askyesno(
            'Packet export privacy',
            'Include packet CONTENTS? Those can contain chat, session tokens '
            'and private game data.\n\n'
            'Choose No for the recommended safe metadata-only export. '
            'Only choose Yes for private troubleshooting; do not share it.',
            default='no')
        path=filedialog.asksaveasfilename(
            title=('Export PRIVATE packet details' if raw else
                   'Export SAFE packet metadata'),
            defaultextension='.txt',filetypes=[('Text file','*.txt')])
        if path:
            try:
                with open(path,'w',encoding='utf-8') as fh:
                    for t,d,detail in self.packet_data:
                        fh.write(packet_export_record(
                            t,d,detail,include_contents=raw))
                self.packet_status.set(
                    'Private packet details saved. Do NOT share this export.'
                    if raw else
                    'Safe packet metadata saved without message payloads.')
            except OSError as exc:
                self.packet_status.set(
                    'Export failed: '+redact_sensitive_diagnostic(str(exc))[:130])

    def _chat_line_toggle(self,parent):
        """Persistent, instant ON/OFF layout control; never changes font_size."""
        key='single_line_bubbles'
        var=tk.BooleanVar(value=bool(self.config.get(key,True)))
        label_var=tk.StringVar(value=chat_line_mode_label(var.get()))
        self.cfg_vars[key]=var
        def changed():
            self.config[key]=bool(var.get())
            label_var.set(chat_line_mode_label(var.get()))
            self.save()
        ttk.Checkbutton(parent,textvariable=label_var,variable=var,command=changed,
                        style='Panel.TCheckbutton').pack(anchor='w',pady=(7,2))

    def _check(self,parent,label,key,invert=False):
        if invert:
            value=not self.config[key]
        else:value=self.config[key]
        var=tk.BooleanVar(value=value)
        self.cfg_vars[key]=var
        def cb():
            self.config[key]=not var.get() if invert else var.get()
            self.save()
        ttk.Checkbutton(parent,text=label,variable=var,command=cb,style='Panel.TCheckbutton').pack(anchor='w',pady=2)

    def save(self):
        self.config['theme']=self.theme.get() if hasattr(self,'theme') else self.config['theme']
        try:save_config(self.config)
        except OSError:pass

    def update_theme(self):
        self.config['theme']=self.theme.get();self.save()

    def preview(self):
        now=time.time()
        self.messages.extend([
          Message('auroral','this is the wide chat layout on the left side of the screen',now,style_id=2),
          Message('zip-linez','only messages from people in your camera view',now+0.01,style_id=7),
          Message('Shaolin128','you can adjust the width, height and background here',now+0.02,style_id=4)
        ])
        self._trim_history()
        self.jump_to_latest()
        self.draw()

    def select_feed(self):
        p=filedialog.askopenfilename(title='Find habbo_view_chat.jsonl',filetypes=[('Habbo overlay log','*.jsonl'),('All files','*.*')])
        if p:
            self.config['feed_path']=p;self.save();self.feed=Path(p)
            self.feed_pos=self.feed.stat().st_size if self.feed.exists() else 0
            self.status.set('Log connected: '+str(self.feed))

    def clear_msgs(self):
        self.messages.clear()
        self.scroll_offset=0
        self.visible_count_current=0
        self.active_image_files.clear()
        self.native_images.clear()
        self._update_scroll_status()
        self.draw()

    def _trim_history(self):
        """Keep a fixed-size, in-memory scrollback rather than a growing archive."""
        limit=max(30,int(self.config.get('history_limit',200)))
        if len(self.messages)>limit:
            self.messages=self.messages[-limit:]
        self.scroll_offset=clamp(self.scroll_offset,0,max(0,len(self.messages)-1))
        self._update_scroll_status()

    def _update_scroll_status(self):
        if not hasattr(self,'scroll_status'):return
        total=len(self.messages)
        if self.scroll_offset:
            self.scroll_status.set(f'HISTORY · {self.scroll_offset} newer message(s) below · scroll down to return')
        else:
            visible=min(total,self.visible_count_current)
            more=max(0,total-visible)
            mode='AUTO' if self.config.get('auto_fill_screen',True) else 'MANUAL'
            self.scroll_status.set(f'LIVE · {visible} visible ({mode}) · {more} earlier in scrollback')

    def scroll_chat(self,amount):
        # Positive moves towards earlier messages; negative towards live.
        self.scroll_offset=clamp(self.scroll_offset+int(amount),0,max(0,len(self.messages)-1))
        self._update_scroll_status()
        self.draw()

    def jump_to_latest(self):
        self.scroll_offset=0
        self._update_scroll_status()
        self.draw()

    def _setup_wheel_hook(self):
        """Listen only for wheel motion within the Habbo chat column.

        The overlay remains fully click-through. The hook never reads mouse
        clicks, keystrokes, message contents or any other application data.
        """
        if os.name!='nt' or self.wheel_hook:return
        try:
            u=self.tracker.user32
            class MouseInfo(ctypes.Structure):
                _fields_=[('pt',wintypes.POINT),('mouseData',wintypes.DWORD),
                          ('flags',wintypes.DWORD),('time',wintypes.DWORD),
                          ('dwExtraInfo',ctypes.c_size_t)]
            callback_type=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,ctypes.c_int,
                                             ctypes.c_size_t,ctypes.c_ssize_t)
            u.SetWindowsHookExW.argtypes=(ctypes.c_int,callback_type,ctypes.c_void_p,wintypes.DWORD)
            u.SetWindowsHookExW.restype=ctypes.c_void_p
            u.CallNextHookEx.argtypes=(ctypes.c_void_p,ctypes.c_int,
                                       ctypes.c_size_t,ctypes.c_ssize_t)
            u.CallNextHookEx.restype=ctypes.c_ssize_t
            u.GetForegroundWindow.restype=wintypes.HWND

            @callback_type
            def on_wheel(code,wparam,lparam):
                try:
                    if code>=0 and int(wparam)==0x020A and self.last_rect:
                        pos=ctypes.cast(lparam,ctypes.POINTER(MouseInfo)).contents
                        sx,sy,sw,sh,habbo_hwnd,*_=self.last_rect
                        if int(u.GetForegroundWindow() or 0)==int(habbo_hwnd):
                            mx=pos.pt.x-sx;my=pos.pt.y-sy
                            x=int(self.config.get('x',22))
                            width=min(int(self.config.get('width',540)),max(150,sw-x-10))
                            room_clear=int(self.config.get('bottom_clearance',110)) if not self.config.get('show_room',True) else 0
                            bottom=min(int(sh*int(self.config.get('anchor',80))/100),sh-room_clear-18)
                            if x<=mx<=x+width and 24<=my<=bottom+10:
                                notch=ctypes.c_short((int(pos.mouseData)>>16)&0xffff).value
                                # Only consume if there actually is older/newer chat.
                                if ((notch>0 and len(self.messages)-self.scroll_offset>self.visible_count_current) or
                                    (notch<0 and self.scroll_offset>0)):
                                    self.pending_wheel+=(1 if notch>0 else -1)*max(1,abs(notch)//120)*3
                                    return 1
                except Exception:
                    pass
                return u.CallNextHookEx(self.wheel_hook,code,wparam,lparam)

            self._wheel_cb=on_wheel  # keep callback alive for as long as hook exists
            # Global LL hook callbacks are delivered to this Tk thread's message pump.
            kernel=ctypes.windll.kernel32
            kernel.GetModuleHandleW.argtypes=(wintypes.LPCWSTR,)
            kernel.GetModuleHandleW.restype=ctypes.c_void_p
            handle=u.SetWindowsHookExW(14,self._wheel_cb,kernel.GetModuleHandleW(None),0)
            if not handle:
                self._wheel_cb=None
                self.status.set('Mouse wheel hook unavailable; use panel Older/Newer or Ctrl+Shift+PgUp/PgDn.')
            else:
                self.wheel_hook=handle
                self.wheel_hook_ready=True
        except (OSError,ValueError,TypeError,AttributeError) as e:
            self.wheel_hook=None;self._wheel_cb=None
            self.status.set(f'Mouse wheel unavailable ({str(e)[:75]}); panel scroll buttons still work.')

    def _apply_wheel(self):
        if self.pending_wheel:
            delta=self.pending_wheel
            self.pending_wheel=0
            self.scroll_chat(delta)

    def clear_log(self):
        if self.feed and self.feed.exists():
            try:
                self.feed.write_text('',encoding='utf-8');self.feed_pos=0
                self.status.set('Local log cleared; new chat will still appear.')
            except OSError as e:messagebox.showerror(APP_NAME,str(e))
        self.clear_msgs()

    def _find_feed(self):
        given=self.config.get('feed_path','')
        if given and Path(given).is_file():return Path(given)
        # AIR's applicationStorageDirectory normally resides in AppData/Roaming.
        # Checking this periodically rather than hardcoding an app ID avoids
        # assuming the user's HabboAirPlus launcher installation name.
        roaming=Path(os.environ.get('APPDATA', str(Path.home()/'AppData/Roaming')))
        dirs=[roaming/'Habbo',roaming/'HabboAirPlus',roaming/'com.sulake.habbo',roaming]
        for base in dirs:
            if not base.is_dir():continue
            if (base/FEED_NAME).is_file():return base/FEED_NAME
            if base==roaming:
                try:
                    for folder in base.iterdir():
                        if not folder.is_dir():continue
                        for candidate in (folder/'Local Store'/FEED_NAME,folder/FEED_NAME,
                                          folder/'local store'/FEED_NAME):
                            if candidate.is_file():return candidate
                except OSError:pass
            else:
                try:
                    for x in base.rglob(FEED_NAME):return x
                except OSError:pass
        return None

    def _poll_feed(self):
        if self.feed is None:
            if time.monotonic()-self.last_search>3:
                self.last_search=time.monotonic()
                found=self._find_feed()
                if found:
                    self.feed=found
                    # Start at the end, so old conversation logs aren't replayed.
                    # If the file appeared since this app started, include its first messages.
                    self.feed_pos=0 if found.stat().st_mtime>=self.started else found.stat().st_size
                    self.status.set('Connected to local Habbo chat feed.')
            return
        if not self.feed.is_file():
            self.feed=None;self.feed_pos=0;return
        try:
            size=self.feed.stat().st_size
            if size<self.feed_pos:self.feed_pos=0
            if size==self.feed_pos:return
            with self.feed.open('rb') as fh:
                fh.seek(self.feed_pos)
                data=fh.read(min(size-self.feed_pos,256000))
                if not data:return
                last_newline=data.rfind(b'\n')
                if last_newline<0:return
                self.feed_pos+=last_newline+1
                for line in data[:last_newline+1].splitlines():
                    try:item=json.loads(line.decode('utf-8'))
                    except (UnicodeDecodeError,json.JSONDecodeError):continue
                    if not isinstance(item,dict):continue
                    self.handle_message(item)
        except (OSError,ValueError):pass

    def handle_message(self,item):
        try:
            name=str(item.get('name') or 'Habbo')[:80]
            body=str(item.get('text') or '').strip()
            if not body:return
            # Archive the actual incoming AIR feed event BEFORE applying the
            # VIEW CHAT 'Only people inside my view' visual filter, so public
            # chat from other room participants is never lost from style logs.
            # Ignore whispers even when their type is only known via G-Earth.
            chat_type_explicit=('chatType' in item or 'chat_type' in item)
            chat_type=int(item.get('chatType',item.get('chat_type',0)) or 0)
            if item.get('isWhisper') is True or item.get('whisper') is True:
                chat_type=1
                chat_type_explicit=True
            arrived=time.time()
            if not chat_type_explicit and match_recent_whisper(
                    self.whisper_hints,body,arrived):
                chat_type=1
            self.responder.record_public_message(
                name,body,chat_type=chat_type,now=arrived)
            self._responder_update_logging_status()
            # Update live room state even for chat outside the on-screen
            # viewport. Historical per-user logs are NOT the target roster.
            room=item.get('room')
            if room is not None and self.room_id is not None and room!=self.room_id:
                self._responder_generation+=1
                self.responder.running=False
                self.responder.reset_room()
                self.clear_msgs()
                self._room_users.clear()
                self._room_chat_names.clear()
                self._responder_room_speakers.clear()
                self._room_profile_cache.clear()
                self._responder_reset_room_targets()
                self._coffee_profile_pending=None
                self._coffee_profile_generation+=1
                self.coffee_users_status_var.set('Room changed. Waiting for player IDs...')
                if self._coffee_running:self._stop_coffee_loop('Room changed; coffee pass stopped.')
            if room is not None:self.room_id=room
            if chat_type not in (1,12):
                self._responder_room_speakers[name.casefold()]=(name,arrived)
            x=item.get('x');y=item.get('y');sw=item.get('sw');sh=item.get('sh')
            within=True
            if isinstance(x,(int,float)) and isinstance(y,(int,float)) and sw and sh:
                within=bool(0<=x<=sw and 0<=y<=sh)
            if self.config.get('visible_only',True) and not within:return
            self._room_chat_names.add(name.casefold())
            cached=self._room_profile_cache.pop(name.casefold(),None)
            if cached and self._habbo_session_connected:
                self._room_users[name.casefold()]=(cached[0],cached[1],None)
                self.coffee_users_status_var.set(
                    f'{cached[0]} verified from current room chat and profile (ID {cached[1]}).')
            raw_style=item.get('style')
            style_id=int(raw_style) if raw_style is not None else None
            raw_color=item.get('forcedColor')
            forced_color=int(raw_color) if isinstance(raw_color,(float,int)) else None
            image_path=None
            raw_image=item.get('bubbleImage')
            # Only trust the expected basename beside the local chat feed.
            # Never open arbitrary paths embedded in a chat message.
            if (self.feed is not None and isinstance(raw_image,str)
                and re.fullmatch(r'habbo_view_bubble_[0-9]+_-?[0-9]+_-?[0-9]+\.png',raw_image)):
                # The AIR writer can append the chat record before the PNG is
                # fully on disk. Keep its safe basename and retry at draw time.
                image_path=self.feed.parent/raw_image
            # While reviewing earlier chat, keep the same messages in view as
            # incoming messages arrive instead of snapping back to the bottom.
            if self.scroll_offset>0:self.scroll_offset+=1
            self.messages.append(Message(name,body,arrived,within,room,
                                         style_id,chat_type,forced_color,image_path,
                                         chat_type_explicit))
            self._trim_history()
            self.responder.observe(name,body,own_name=self._own_name,
                                   chat_type=chat_type)
            if image_path:
                self.native_image_count+=1
                if self.native_image_count==1:
                    self.status.set('Displaying original Habbo bubble artwork from the client.')
            elif self.native_image_count==0:
                self.status.set('Waiting for original Habbo bubble PNGs. Missing images show text only.')
        except (ValueError,TypeError):pass

    def _rounded(self,canvas,x1,y1,x2,y2,r,color):
        r=min(r,(x2-x1)/2,(y2-y1)/2)
        canvas.create_polygon(x1+r,y1,x2-r,y1,x2,y1+r,x2,y2-r,
                              x2-r,y2,x1+r,y2,x1,y2-r,x1,y1+r,
                              smooth=True,splinesteps=16,fill=color,outline='')

    def draw(self):
        if not self.last_rect:return
        sx,sy,sw,sh,*_=self.last_rect
        cv=self.stage;cv.delete('all')
        theme=THEMES.get(self.config['theme'],THEMES['Midnight'])
        if not self.config['show_room']:
            # Do not paint over Habbo's native typing/input bar and toolbar.
            room_height=max(0,sh-int(self.config.get('bottom_clearance',110)))
            cv.create_rectangle(0,0,sw,room_height,fill=theme['room'],outline='')
            # Very low-contrast ambient texture, entirely within overlay.
            if self.config['theme']!='Graphite':
                for xx in range(0,sw,115):cv.create_line(xx,0,xx,room_height,fill='#152137',width=1)
                for yy in range(0,room_height,115):cv.create_line(0,yy,sw,yy,fill='#152137',width=1)
                for i in range(min(35,int(sw*sh/35000))):
                    x=(i*193+71)%max(1,sw);y=(i*137+99)%max(1,room_height)
                    cv.create_oval(x,y,x+2,y+2,fill='#263b54',outline='')
        size=int(self.config['font_size'])
        self.canvas_font=font.Font(family='Segoe UI',size=size)
        self.canvas_bold=font.Font(family='Segoe UI Semibold',size=size,weight='bold')
        pad=12
        single_line=bool(self.config.get('single_line_bubbles',True))
        align_whispers=bool(self.config.get('whispers_right',True))
        maxw=(max(80,sw-2*int(self.config['x'])-10) if single_line
              else min(int(self.config['width']),max(150,sw-int(self.config['x'])-10)))
        fline=max(self.canvas_font.metrics('linespace'),self.canvas_bold.metrics('linespace'))+2
        clear=int(self.config.get('bottom_clearance',110)) if not self.config['show_room'] else 0
        cursor=min(int(sh*int(self.config['anchor'])/100), sh-clear-18)
        x=int(self.config['x'])
        gap=int(self.config['gap'])
        show_bubbles=self.config['bubbles']
        # Virtual scrollback: either draw a manual number of bubbles or let the
        # available screen height determine how many fit. The loop stops at the
        # top edge; older messages remain only in the bounded history buffer.
        end=max(0,len(self.messages)-self.scroll_offset)
        if self.config.get('auto_fill_screen',True):
            start=0
        else:
            start=max(0,end-int(self.config.get('visible_messages',14)))
        rendered_count=0
        active_images=set()
        # Native client PNGs are the only speech bubble artwork we ever draw.
        # They contain Habbo's genuine styling, text, chat badges and pointers.
        # Replacing them with Tk polygons/rounded rectangles made fake white
        # bubbles: do not bring those paths back.
        for msg in reversed(self.messages[start:end]):
            right=align_whispers and is_whisper_chat(msg.chat_type)
            native=None
            key=None
            if show_bubbles and msg.bubble_image is not None:
                key=str(msg.bubble_image)
                try:
                    native=self.native_images.get(key)
                    if native is None and msg.bubble_image.is_file():
                        nbytes=msg.bubble_image.stat().st_size
                        if 8<nbytes<2_000_000:
                            loaded=tk.PhotoImage(master=self.root,file=key,format='png')
                            if loaded.width()>0 and loaded.height()>0:
                                native=loaded
                                self.native_images[key]=native
                except (OSError,tk.TclError,ValueError):
                    native=None
            if native is not None:
                w,h=native.width(),native.height()
                top=cursor-h
                if top<24:break
                bx=max(x,sw-x-w) if right else x
                cv.create_image(bx,top,image=native,anchor='nw')
                active_images.add(key)
                cursor=top-gap
                rendered_count+=1
                continue

            # No native image: never fabricate a bubble shape or coloured
            # avatar letter. The transparent text-only fallback is deliberate.
            # A missing PNG might still be in progress on disk; allow the AIR
            # client a moment to finish writing it before falling back.
            if (show_bubbles and msg.bubble_image is not None
                and time.time()-msg.arrived<1.5):
                continue
            content=chat_one_line(msg.name+': '+msg.body)
            available=max(60,maxw-12)
            if single_line:
                lines=[fit_line_ellipsis(content,self.canvas_font,available)]
            else:
                lines=wrap_message(content,available,self.canvas_font)
            height=max(fline, len(lines)*fline)+4
            top=cursor-height
            if top<24:break
            tx=max(x,sw-x-maxw) if right else x
            for line_number,line in enumerate(lines):
                cv.create_text(tx,top+line_number*fline,text=line,anchor='nw',
                               font=self.canvas_font,fill='#dce8f7')
            cursor=top-gap
            rendered_count+=1
        self.visible_count_current=rendered_count
        self.active_image_files=active_images
        self._update_scroll_status()
        if self.scroll_offset:
            cv.create_rectangle(x,22,x+min(maxw,420),49,fill='#23354c',outline='#405e7b')
            cv.create_text(x+10,35,text=f'OLDER CHAT  ·  {self.scroll_offset} newer message(s) below  ·  ↓ scroll for live',
                           anchor='w',font=('Segoe UI',9,'bold'),fill=COMPANION_UI['text'])

    def _hotkeys(self):
        if os.name!='nt':return
        u=self.tracker.user32
        ctrl=bool(u.GetAsyncKeyState(0x11)&0x8000)
        shift=bool(u.GetAsyncKeyState(0x10)&0x8000)
        active=set()
        if ctrl and shift:
            if u.GetAsyncKeyState(0x75)&0x8000:active.add('panel') # F6
            if u.GetAsyncKeyState(0x76)&0x8000:active.add('room') # F7
            if u.GetAsyncKeyState(0x21)&0x8000:active.add('older') # Page Up
            if u.GetAsyncKeyState(0x22)&0x8000:active.add('newer') # Page Down
            if u.GetAsyncKeyState(0x23)&0x8000:active.add('latest') # End
        for key in active-self.last_hotkeys:
            if key=='panel':
                if self.settings_open:self.root.withdraw()
                else:self.root.deiconify();self.root.lift()
                self.settings_open=not self.settings_open
            if key=='older':self.scroll_chat(3)
            if key=='newer':self.scroll_chat(-3)
            if key=='latest':self.jump_to_latest()
            if key=='room':
                self.config['show_room']=not self.config['show_room']
                self.cfg_vars['show_room'].set(not self.config['show_room'])
                self.save()
        self.last_hotkeys=active

    def _maintain_storage(self):
        """Limit temporary disk files without disrupting visible scrollback."""
        if not self.feed or self.config.get('keep_log',False):return
        try:
            # AIR appends to this JSONL file. We've already ingested these
            # records in RAM, so a large log does not need to persist forever.
            if self.feed.is_file():
                size=self.feed.stat().st_size
                if size>2_000_000 and self.feed_pos>=size:
                    with self.feed.open('r+b') as fh:fh.truncate(0)
                    self.feed_pos=0
            retained={str(m.bubble_image) for m in self.messages if m.bubble_image}
            now=time.time()
            for pngfile in self.feed.parent.glob('habbo_view_bubble_*.png'):
                if str(pngfile) not in retained and now-pngfile.stat().st_mtime>30:
                    try:pngfile.unlink()
                    except OSError:pass
        except OSError:pass

    def tick(self):
        try:
            self._hotkeys()
            self._poll_feed()
            self._responder_tick()
            self._apply_wheel()
            # Avoid holding decoded PNG images for all historical messages.
            # Older images remain on disk only while their message is retained.
            if self.feed and time.monotonic()-self.last_native_check>30:
                self.last_native_check=time.monotonic()
                self._maintain_storage()
                for image_key in list(self.native_images):
                    if image_key not in self.active_image_files:
                        self.native_images.pop(image_key,None)
            exclude=[self.root.winfo_id(),self.overlay.winfo_id()]
            geom=self.tracker.find(exclude)
            foreground=self.tracker.foreground_context(geom[4],self.root.winfo_id()) if geom else 'other'
            # Do not hide the overlay simply because Explorer/Discord/Spotify
            # is active. Position it directly above Habbo in the normal z-order
            # instead, so other apps naturally cover it without erasing chat.
            if geom:
                sx,sy,sw,sh,*_=geom
                # Wide, click-through overlay: full-width chat and right-side whispers.
                wide_chat=bool(self.config.get('single_line_bubbles',True)
                               or self.config.get('whispers_right',True))
                overlay_w=(sw if wide_chat or not self.config['show_room']
                           else min(sw,max(260,int(self.config['x'])+int(self.config['width'])+28)))
                overlay_geom=(sx,sy,overlay_w,sh)
                changed=geom!=self.last_rect or overlay_geom!=self.last_overlay_geometry
                self.last_rect=geom
                if changed and not self.clickthrough_failed:
                    self.last_overlay_geometry=overlay_geom
                    self.overlay.geometry(f'{overlay_w}x{sh}+{sx}+{sy}')
                    self.overlay.update_idletasks()
                    # Apply NOACTIVATE before showing, then reapply once mapped.
                    # This avoids the transparent overlay briefly taking focus.
                    self.tracker.set_clickthrough(self.overlay.winfo_id())
                    self.overlay.deiconify()
                    self.overlay.update_idletasks()
                    if not self.tracker.set_clickthrough(self.overlay.winfo_id()):
                        self.clickthrough_failed=True
                        self.overlay.withdraw()
                    else:
                        # Place below unrelated apps EVEN if the panel was
                        # started from Explorer with Habbo in the background.
                        self.tracker.stack_above_habbo(self.overlay.winfo_id(),geom[4])
                    self.last_clickthrough_check=time.monotonic()
                    self.last_stack_check=time.monotonic()
                elif not self.clickthrough_failed and time.monotonic()-self.last_clickthrough_check>6.0:
                    if not self.tracker.set_clickthrough(self.overlay.winfo_id()):
                        self.clickthrough_failed=True
                        self.overlay.withdraw()
                    self.last_clickthrough_check=time.monotonic()
                if (not self.clickthrough_failed and foreground in ('habbo','settings')
                    and time.monotonic()-self.last_stack_check>0.75):
                    # Avoid making repeated z-order calls every 120ms; these
                    # can cause flicker as the cursor crosses layered windows.
                    self.tracker.stack_above_habbo(self.overlay.winfo_id(),geom[4])
                    self.last_stack_check=time.monotonic()
                if self.clickthrough_failed:
                    self.status.set('Overlay hidden: Windows click-through could not be enabled. Restart the panel to retry.')
                elif not self.feed:
                    self.status.set('Habbo found. Waiting for local chat bridge log...')
            else:
                self.overlay.withdraw();self.last_rect=None;self.last_overlay_geometry=None
                self.last_overlay_draw_signature=None
                self.status.set('Waiting for a Habbo client window...')
            # No need to clear and rebuild the entire transparent canvas
            # eight times a second while nothing changes. Keep immediate
            # redraw for new chat, scrolling, layout or room movement.
            visual_keys=('theme','show_room','single_line_bubbles','whispers_right',
                         'bubbles','x','width','anchor','gap','font_size',
                         'bottom_clearance','auto_fill_screen','visible_messages')
            signature=(self.last_rect,self.last_overlay_geometry,self.scroll_offset,
                       len(self.messages),self.messages[-1].arrived if self.messages else None,
                       tuple(self.config.get(k) for k in visual_keys))
            now=time.monotonic()
            if (signature!=self.last_overlay_draw_signature
                or now-self.last_overlay_draw_at>=0.6):
                self.draw()
                self.last_overlay_draw_signature=signature
                self.last_overlay_draw_at=now
        except Exception as e:
            self.status.set(f'Overlay issue: {str(e)[:140]}')
        self.root.after(120,self.tick)

    def close(self):
        self._responder_generation+=1
        self.responder.enabled=False
        # Tickets never outlive the Companion process.
        self._tcp_disconnect_all()
        self._direct_ticket_queue.clear()
        self.direct_ticket_var.set('')
        self._headless_manager.disconnect_all()
        if self._headless_server is not None:
            self._headless_server.stop()
            self._headless_server=None
        self._stop_packet_replay('Companion closed. Repeat stopped.')
        self._stop_coffee_loop('Companion closed. Coffee loop stopped.')
        if self.wheel_hook and os.name=='nt':
            try:
                u=self.tracker.user32
                u.UnhookWindowsHookEx.argtypes=(ctypes.c_void_p,)
                u.UnhookWindowsHookEx.restype=wintypes.BOOL
                u.UnhookWindowsHookEx(self.wheel_hook)
            except (OSError,AttributeError,ValueError):pass
            self.wheel_hook=None
        self.save()
        if not self.config.get('keep_log',False) and self.feed and self.feed.exists():
            try:self.feed.unlink()
            except OSError:pass
        if not self.config.get('keep_log',False) and self.feed:
            try:
                for png in self.feed.parent.glob('habbo_view_bubble_*.png'):
                    if png.is_file():
                        try:png.unlink()
                        except OSError:pass
            except OSError:pass
        self.native_images.clear()
        self.root.destroy()


def main():
    if os.name!='nt':
        raise SystemExit('This overlay needs Windows (for transparent click-through windows).')
    root=tk.Tk()
    ChatOverlayApp(root)
    root.mainloop()


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--repair-gearth-hosts':
        raise SystemExit(elevated_gearth_repair(sys.argv[2]))
    main()