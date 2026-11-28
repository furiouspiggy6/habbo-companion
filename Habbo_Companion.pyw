# -*- coding: utf-8 -*-
"""Habbo View Chat | Windows overlay, packet tools and account sessions.

Works with the companion patched HabboAir.swf for chat feeds. Optional G-Earth
extension integration and per-profile local browser automation use network
sockets on the same machine. Saved passwords are held in the local Windows Credential Manager vault only.
"""
from __future__ import annotations
from headless_transport import (HeadlessLocalManager, LocalHeadlessTestServer,
                                MAX_ACCOUNTS as HEADLESS_TEST_MAX_ACCOUNTS)
from local_classic_launch import parse_classic_ticket
from habbo_tcp import (HabboTcpSession, HabboTcpError, fetch_habbo_sso_ticket,
                       probe_classic_websocket, TCP_FALLBACK_RELEASE, validate_socks5_proxy)
from clientless_gearth_bridge import (
    ClientlessGearthBridge, GearthBridgeError, DEFAULT_BRIDGE_PORT,
    DEFAULT_BRIDGE_HOST, verify_bridge_alias)
from clientless_bot import (ClientlessBotError, build_clientless_action,
    capture_clientless_headers, validate_clientless_headers,
    encode_clientless_action, decode_clientless_chat, ClientlessChatDeduplicator, OUTGOING_ACTION_NAMES,
    clientless_walk_positions, decode_clientless_room_observation, decode_clientless_room_bots,
    decode_clientless_hand_observation, validate_clientless_coffee_settings)
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


def fetch_current_update_manifest(url,helper):
    """Cross-check the pinned raw feed against GitHub's repository contents API.

    Keep raw-feed cache busting here so both UI and offline tests share it.
    """
    helper.validate_official_release_url(url,'manifest')
    api='https://api.github.com/repos/furiouspiggy6/habbo-companion/contents/latest.json?ref=main'
    headers={'User-Agent':'HabboCompanionUpdater/1.3','Cache-Control':'no-cache','Pragma':'no-cache'}
    def read(target,accept):
        req=urllib.request.Request(target,headers=dict(headers,Accept=accept))
        with _open_official_update(req,timeout=12) as response:
            if response.geturl()!=target:
                raise ValueError('Update source changed unexpectedly')
            raw=response.read(65_537)
            if len(raw)>65_536:raise ValueError('Manifest is too large')
        return json.loads(raw.decode('utf-8'))
    def validate(info):
        if not isinstance(info,dict) or info.get('app_id')!='habbo-companion':
            raise ValueError('Not a Habbo Companion update manifest')
        version=info['version']
        helper.validate_official_release_url(info['package_url'],'package',version=version)
        if not re.fullmatch(r'[a-f0-9]{64}',str(info['sha256']).lower()):
            raise ValueError('Invalid package checksum')
        return info
    candidates=[]
    errors=[]
    for source,target,accept in (
            ('GitHub API',api,'application/vnd.github.raw+json'),
            ('raw feed',url+'?check='+uuid.uuid4().hex,'application/json')):
        try:
            info=validate(read(target,accept))
            candidates.append((info,source))
        except (OSError,ValueError,KeyError,TypeError) as exc:
            errors.append(source+': '+str(exc)[:120])
    if not candidates:
        raise ValueError('Both update sources failed: '+'; '.join(errors))
    if len(candidates)==2:
        a,b=candidates
        if a[0]['version']==b[0]['version'] and (
                a[0]['sha256'].lower()!=b[0]['sha256'].lower()
                or a[0]['package_url']!=b[0]['package_url']):
            raise ValueError('Update sources disagree on package checksum')
    info,source=max(candidates,key=lambda item:helper.version_tuple(item[0]['version']))
    if errors:source+='; other source unavailable'
    return info,source


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
    coffee=(re.match(r'^\[Coffee Pass Loop\] (UseFurniture|PassCarryItem)\b',
                     str(detail)) if not named else None)
    label=('type '+named.group(1) if named else
           'type '+coffee.group(1) if coffee else 'type unknown')
    return f'{time_part} [{direction_part}] [{label}; payload omitted]\n'

APP_DIR = Path(os.environ.get('APPDATA', str(Path.home()))) / 'HabboViewChat'
CONFIG_PATH = APP_DIR / 'settings.json'
FEED_NAME = 'habbo_view_chat.jsonl'
TRANSPARENT = '#ff00fe'

# Shared modern-dark application chrome.  These colours apply only to the
# Companion control window; the original in-game Habbo bubble art and overlay
# themes above remain independent.
COMPANION_UI = {
    'background': '#111113',
    'sidebar': '#09090B',
    'surface': '#19191C',
    'raised': '#26262B',
    'field': '#0D0D10',
    'border': '#333338',
    'text': '#F1F1F4',
    'muted': '#ABABB5',
    'faint': '#777780',
    'accent': '#5865F2',
    'accent_hover': '#6875FF',
    'success': '#57C89A',
    'danger': '#F08A91',
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
    tcp_proxy_enabled=False,
    tcp_proxy_url='socks5://127.0.0.1:1080',
    # Persistent clientless favorites and read-only AIR packet header mappings.
    clientless_last_room_id='69118545',
    clientless_header_map=None,
    clientless_standalone=True,
    # Pre-start choice; ON will fail closed until a true G-Earth MITM exists.
    clientless_gearth_intercept=False,
    clientless_auto_walk=False,
    clientless_walk_presets={},
    # Optional overrides for each saved account; fallback is room-wide preset.
    clientless_account_walk_presets={},
    clientless_anti_afk_profiles={},
    clientless_coffee_presets={},
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
        profile={'id':ident,'label':label,'port':port,'url':url}
        if entry.get('launch_mode') in ('air','gearth','clientless','clientless_gearth'):
            profile['launch_mode']=entry['launch_mode']
        valid.append(profile)
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


def account_air_browser_command(browser,folder,url,debug_port):
    """Visible Chromium for the official native application handoff."""
    return account_browser_command(browser,folder,url,debug_port)


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
    if (/^play\s+in\s+app\s*!?(?:\s+h)?$/i.test(text)) return 'play';
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
    if kind=='app-error':
        # Only report the known visible Habbo app error. Never read raw page
        # contents or click through a failed launch dialog.
        target=page.get_by_text(re.compile(
            r'^an error occurred[.!]?\s*please try again later[.!]?$',re.I),
            exact=True).filter(visible=True)
        return target.first if account_playwright_visible(target) else None
    patterns={
        'open-login':r'^(?:log\s*in|login|sign\s*in)\s*!?$',
        'submit':r"^(?:let['’]?s\s+go|log\s*in|login|sign\s*in|continue)\s*!?$",
        'play':r'^play(?:\s+now)?(?:\s+h)?\s*!?$',
        'play-app':r'^\s*play\s*in\s*app\s*!?(?:\s*(?:h|habbo(?:\s*(?:icon|logo))?|[\u24bd\u24d7]))?\s*$',
        'launch':r'^launch\s*(?:and|&)\s*log\s*in\s*!?$',
    }
    pattern=re.compile(patterns[kind],re.I)
    # Prefer semantic buttons and links before custom-styled text controls.
    for role in ('button','link'):
        target=page.get_by_role(role,name=pattern).filter(visible=True)
        if account_playwright_visible(target):
            return target.first
    target=page.locator('button,a,[role="button"],input[type="submit"],input[type="button"]').filter(
        has_text=pattern,visible=True)
    if account_playwright_visible(target):
        return target.first
    # Some Habbo PLAY buttons render as styled spans. Playwright still
    # dispatches trusted click input to the text/containing control.
    if kind in ('play','play-app','launch'):
        target=page.get_by_text(pattern,exact=True).filter(visible=True)
        if account_playwright_visible(target):
            return target.first
    return None


def account_playwright_select_page(browser):
    """Select a Habbo tab from the already isolated browser context."""
    candidates=[]
    for context in browser.contexts:
        for page in reversed(context.pages):
            if not account_playwright_is_official(page.url):
                continue
            try:
                if account_playwright_control(page,'app-error') is not None:
                    priority=0
                elif account_playwright_visible(
                        page.locator('input[type="password"]:visible')):
                    priority=3
                elif account_playwright_control(page,'launch') is not None:
                    priority=6
                elif account_playwright_control(page,'play-app') is not None:
                    priority=5
                elif account_playwright_control(page,'play') is not None:
                    priority=4
                elif account_playwright_control(page,'open-login') is not None:
                    priority=2
                else:
                    priority=1
                # Prefer the currently visible tab when equally suitable;
                # do not select an old error dialog over a usable home page.
                try:
                    foreground=bool(page.evaluate("document.visibilityState === 'visible'"))
                except Exception:
                    foreground=False
                candidates.append((priority,foreground,page))
            except (OSError,RuntimeError):
                continue
    if not candidates:
        return None
    return max(candidates,key=lambda entry:entry[:2])[2]


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
            # A response with headers but no requestfinished event may still
            # be streaming. Do not block the native launch waiting on it.
            if not rec.get('completed') or rec.get('failed'):
                continue
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
            if not login_only:
                for _ in range(12):
                    if page is not None:
                        break
                    time.sleep(0.5)
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
                if not login_only:
                    page.bring_to_front()
                    # Collapse restored duplicate home tabs in this isolated
                    # account context. Never close a game, login route, or
                    # unrelated page, and never clear cookies or storage.
                    home_urls=('https://habbo.com','https://habbo.com/',
                               'https://www.habbo.com','https://www.habbo.com/')
                    if page.url in home_urls:
                        closed=0
                        for duplicate in tuple(getattr(page.context,'pages',())):
                            if duplicate is page or duplicate.url not in home_urls:
                                continue
                            try:
                                duplicate.close(run_before_unload=False)
                                closed+=1
                            except Exception:
                                # A disappearing tab must not abort launch.
                                continue
                        if closed:
                            report(f'Reused saved account browser; closed {closed} duplicate Habbo home tab(s).')
                    # Wait for a real recognised website control. Do not
                    # click coordinates, fabricate a login or repeat a request.
                    for _ in range(24):
                        if not account_playwright_is_official(page.url):
                            return 'unknown'
                        if account_playwright_login_form(page) is not None or any(
                            account_playwright_control(page,kind) is not None
                            for kind in ('play-app','play','launch','open-login','app-error')):
                            break
                        page.wait_for_timeout(500)
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
                    if (account_playwright_control(page,'play-app') is not None or
                            account_playwright_control(page,'play') is not None or
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
                app_requested=False
                app_waits=0
                def native_site_error():
                    if account_playwright_control(page,'app-error') is None:
                        return False
                    # Report only HTTP status, never URLs, bodies or tickets.
                    failures=[rec.get('status') for rec in getattr(
                        monitor,'requests',{}).values()
                        if rec.get('service')=='Habbo'
                        and rec.get('method')=='POST'
                        and isinstance(rec.get('status'),int)
                        and rec['status']>=400]
                    report('Habbo Play in App returned an error'+
                           (' (HTTP '+str(failures[-1])+')' if failures else '')+
                           '. No automatic launch retry.')
                    return True
                for _ in range(24):
                    if not account_playwright_is_official(page.url):
                        return 'launched' if app_requested else 'unknown'
                    if not app_requested and account_playwright_login_form(page) is not None:
                        report('Website login or verification still required. No additional login submitted.')
                        return 'login'
                    if native_site_error():
                        return 'app_error'
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
                    if app_requested:
                        # Wait briefly for the official launcher dialog, then
                        # let the caller confirm the native window.
                        app_waits+=1
                        if app_waits>=6:
                            break
                        page.wait_for_timeout(850)
                        continue
                    app=account_playwright_control(page,'play-app')
                    if app is not None:
                        report('Play in App located; clicking the native app button.')
                        try:
                            app.click(timeout=9000)
                        except Exception as exc:
                            report('Playwright Play in App: '+
                                   account_playwright_safe_error(exc)+'.')
                            return 'stalled'
                        app_requested=True
                        report('Clicked Play in App; checking for native launcher or Launch and log in.')
                        page.wait_for_timeout(850)
                        continue
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
                if account_playwright_is_official(page.url) and native_site_error():
                    return 'app_error'
                if app_requested:
                    return 'launched'  # Caller verifies the native window or launcher.
                report('No recognised Play in App or Launch and log in control became available.')
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
            # The shared first-party browser ticket helper uses only the
            # isolated Habbo tab and requests a real ticket from the official
            # site.
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


def account_request_native_air_launch(ticket):
    """Pass a fresh, validated official ticket to the installed Windows handler.

    No browser UI is opened and no ticket is persisted or included in errors.
    The OS protocol handler must be installed; a request is not proof of login.
    """
    if os.name!='nt':
        raise OSError('HabboAIR launch requires Windows.')
    body=ticket.secret+('.'+ticket.username if ticket.username else '')
    checked=parse_classic_ticket(ticket.server_id+'.'+body)
    uri='habbo://hab?'+urllib.parse.urlencode({
        'server':checked.server_id,'token':body})
    try:
        os.startfile(uri)
    except (OSError,ValueError):
        raise OSError('The Habbo Windows launcher could not be opened. '
                      'Check the installed Habbo app and protocol association.') from None


def account_show_login_browser(debug_port):
    """Restore an isolated browser for manual login or a stalled AIR launch."""
    page=account_habbo_page(debug_port)
    if not page:
        return
    ws=page['webSocketDebuggerUrl']
    try:
        info=account_cdp_call(ws,'Browser.getWindowForTarget')
        window_id=info.get('windowId')
        if window_id is not None:
            account_cdp_call(ws,'Browser.setWindowBounds',{
                'windowId':window_id,'bounds':{'windowState':'normal'}})
        account_cdp_call(ws,'Page.bringToFront')
        return True
    except (OSError,ValueError,RuntimeError,TimeoutError):
        return False


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


def parse_outfit_update_expression(expression):
    """Only accept the known two-string, named UpdateFigureData outfit action.

    All other outgoing packets are ignored, including similarly named wardrobe
    save requests. Figures may contain only Habbo clothing token syntax.
    """
    if not isinstance(expression,str) or len(expression)>1100:
        return None
    match=re.fullmatch(
        r'\{out:UpdateFigureData\}\{s:"([MFmf])"\}\{s:"([^"\\]{5,1024})"\}',
        expression)
    if not match:
        return None
    gender,figure=match.group(1).upper(),match.group(2)
    parts=figure.split('.')
    if not 2<=len(parts)<=50:
        return None
    if not all(re.fullmatch(r'[a-z]{2}-[0-9]{1,7}(?:-[0-9]{1,7}){1,3}',part)
               for part in parts):
        return None
    if not any(part.startswith('hd-') for part in parts):
        return None
    return gender,figure


def outfit_update_expression(gender,figure):
    """Build a G-Earth packet with a named live header from validated values."""
    pair=parse_outfit_update_expression(
        '{out:UpdateFigureData}{s:'+json.dumps(str(gender))+
        '}{s:'+json.dumps(str(figure))+'}')
    if pair is None:
        raise ValueError('Invalid saved outfit. Capture a normal Looks save in Habbo.')
    return ('{out:UpdateFigureData}{s:'+json.dumps(pair[0])+
            '}{s:'+json.dumps(pair[1])+'}')


def face_rotation_targets(tile_x,tile_y,clockwise=True):
    """Eight look-at targets around a stationary avatar (45 degrees apart).

    No MoveAvatar packet is constructed, and the center square is never sent
    as a movement destination. The LookTo protocol takes absolute target
    tile coordinates; it does not request a walk to those coordinates.
    """
    if (type(tile_x) is not int or type(tile_y) is not int
        or not 1<=tile_x<=1023 or not 1<=tile_y<=1023):
        raise ValueError('Capture your standing tile before rotating.')
    offsets=((0,-1),(1,-1),(1,0),(1,1),
             (0,1),(-1,1),(-1,0),(-1,-1))
    if not clockwise:
        offsets=(offsets[0],)+tuple(reversed(offsets[1:]))
    return tuple((tile_x+dx,tile_y+dy) for dx,dy in offsets)


def face_lookto_expression(tile_x,tile_y):
    """Only the named turning header and two bounded integer coordinates."""
    if (type(tile_x) is not int or type(tile_y) is not int
        or not 0<=tile_x<=1024 or not 0<=tile_y<=1024):
        raise ValueError('LookTo target must be within the nearby tile grid.')
    return f'{{out:LookTo}}{{i:{tile_x}}}{{i:{tile_y}}}'


def outgoing_face_tile_from_packet(extension,direction,packet):
    """Capture a human-generated LookTo using the mapped header, not a guess.

    Only a standard 4-byte length, 2-byte header, two-int LookTo packet is
    accepted; the user is instructed to click their OWN avatar to identify
    their current standing tile. A generic LookTo target cannot by itself
    prove the coordinates belong to the user's avatar.
    """
    try:
        infos=(getattr(extension,'packet_infos',None) or {}).get(
            direction,{}).get(packet.header_id(),())
        if not any(str(info.get('Name','')).casefold()=='lookto'
                   for info in infos):
            return None
        raw=getattr(packet,'bytearray',None)
        if (not isinstance(raw,(bytes,bytearray)) or len(raw)!=14
            or bytes(raw[:4])!=b'\x00\x00\x00\x0a'):
            return None
        x,y=packet.read_int(6),packet.read_int(10)
        face_rotation_targets(x,y)
        return x,y
    except (ValueError,TypeError,AttributeError,IndexError,KeyError):
        return None


def outgoing_is_named(extension,direction,packet,name):
    """Check a named G-Earth outgoing header without hardcoded packet IDs."""
    try:
        infos=(getattr(extension,'packet_infos',None) or {}).get(
            direction,{}).get(packet.header_id(),())
        return any(str(info.get('Name','')).casefold()==name.casefold()
                   for info in infos)
    except (ValueError,TypeError,AttributeError,KeyError):
        return False


DANCE_STYLE_NAMES={
    0:'Stop dancing',
    1:'Hab-Hop (everyone)',
    2:'Pogo Mogo (Habbo Club)',
    3:'Duck Funk (Habbo Club)',
    4:'The Rollie (Habbo Club)',
}


def dance_packet_expression(style_id):
    """Named AIR Dance action; 0 is stop, 1–4 are standard Habbo dances.

    This is not a request to bypass HC access checks; the server decides
    whether the account can use the selected dance.
    """
    if type(style_id) is not int or style_id not in DANCE_STYLE_NAMES:
        raise ValueError('Dance style must be a Habbo dance ID from 0 to 4.')
    return f'{{out:Dance}}{{i:{style_id}}}'


def dance_cycle_sequence(enabled):
    """Take checked dance IDs in deterministic order; reject invalid IDs."""
    try:
        selected=tuple(i for i in (1,2,3,4) if enabled.get(i,False))
    except (AttributeError,TypeError):
        raise ValueError('Choose at least two dance styles.')
    if len(selected)<2:
        raise ValueError('Choose at least two dance styles for cycling.')
    return selected


def initial_outfit_delay_ms(settings):
    """Migrate v1.1.89's seconds to milliseconds without changing speed."""
    if 'outfit_delay_ms' in settings:
        return str(settings['outfit_delay_ms'])
    try:
        seconds=float(settings.get('outfit_delay','0.3'))
    except (TypeError,ValueError):
        seconds=0.3
    if not math.isfinite(seconds) or seconds<0:
        seconds=0.3
    return f'{seconds*1000:g}'


def sanitize_outfit_presets(raw):
    """Persist only harmless validated figure/gender pairs, max 8."""
    result=[]
    if not isinstance(raw,list):
        return result
    seen=set()
    for entry in raw[:48]:
        if not isinstance(entry,dict):
            continue
        gender,figure=entry.get('gender'),entry.get('figure')
        try:outfit_update_expression(gender,figure)
        except ValueError:continue
        key=(str(gender).upper(),figure)
        if key not in seen:
            seen.add(key)
            result.append({'gender':key[0],'figure':figure})
        if len(result)>=8:
            break
    return result


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



def format_coffee_packet_viewer_event(expression, local_sent):
    """Summarize generated cup requests without exposing arbitrary packet text."""
    expression=str(expression)
    furniture=re.fullmatch(r'\{out:UseFurniture\}\{i:([0-9]{1,10})\}\{i:0\}',expression)
    recipient=re.fullmatch(r'\{out:PassCarryItem\}\{i:([0-9]{1,10})\}',expression)
    if furniture:
        label='UseFurniture → furniture '+furniture.group(1)
    elif recipient:
        label='PassCarryItem → recipient '+recipient.group(1)
    else:
        # Unknown expressions may contain secrets. Never display them verbatim.
        label='unrecognized generated action'
    outcome=('local G-Earth send accepted; server/recipient unverified'
             if local_sent else
             'local G-Earth send failed; server/recipient unverified')
    return '[Coffee Pass Loop] '+label+' | '+outcome


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

CLIENTLESS_COFFEE_HOUSE_ROOM_ID = 69118545


def clientless_saved_room_value(value):
    """Return a persisted, valid numeric room ID, or the Coffee House default.

    Never persist a full URL, arbitrary text or a negative/overflowing ID.
    This setting contains no session credentials.
    """
    if type(value) is int:
        number=value
    elif isinstance(value,str) and re.fullmatch(r'[0-9]{1,10}',value.strip()):
        number=int(value.strip())
    else:
        number=0
    if not 1<=number<=2147483647:
        number=CLIENTLESS_COFFEE_HOUSE_ROOM_ID
    return str(number)


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
        self.root.geometry('1120x740')
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
        self._tcp_sessions={}
        self._tcp_inflight=set()
        self._tcp_generation={}
        self._tcp_states={}
        self._tcp_log_packet_ids=False
        self._bot_headers=self.config.get('clientless_header_map')
        self._bot_action_inflight=set()
        self._bot_last_action_at={}
        # Pending one-click room entries are tied to the exact account generation.
        self._bot_pending_room={}
        self._bot_run_room_targets={}
        # Account-level explicit Direct TCP permission for multi-select mode;
        # never treat a global G-Earth ON setting as permission to bypass.
        self._bot_multi_direct_ids=set()
        self._bot_multi_start_generation=0
        self._bot_multi_ui_generation=0
        self.bot_multi_status_var=tk.StringVar(
            value='Select multiple profiles below and choose Run highlighted.')
        self._bot_gearth_bridges={}
        self._bot_walk_plans={}
        self._bot_follow_run=None
        self._bot_follow_group_run=None
        self._bot_follow_room_bots={}
        self._bot_self_ids={}
        self._bot_user_roster={}
        self._bot_chat_dedup=ClientlessChatDeduplicator()
        self._coffee_room_state={}
        self._coffee_manual_results={}
        self._coffee_run=None
        self._coffee_last_pass={}
        self._coffee_last_pickup={}
        # Read-only, generation-scoped avatar location for stationary anti-AFK.
        self._bot_anti_afk_rooms={}
        self._bot_anti_afk_positions={}
        self._bot_anti_afk_last={}
        self.bot_anti_afk_var=tk.BooleanVar(value=False)
        self.bot_anti_afk_status_var=tk.StringVar(
            value='Anti-AFK OFF for the selected profile.')
        self.bot_auto_walk_var=tk.BooleanVar(
            value=bool(self.config.get('clientless_auto_walk',False)))
        self.bot_walk_primary_var=tk.StringVar(value='')
        self.bot_walk_backups_var=tk.StringVar(value='')
        self.bot_walk_status_var=tk.StringVar(
            value='Automatic walking is OFF until you save positions and enable it.')
        self.bot_standalone_var=tk.BooleanVar(
            value=bool(self.config.get('clientless_standalone',True)))
        # Legacy internal fallback stays OFF; launch routing is now per account.
        self.bot_gearth_var=tk.BooleanVar(value=False)
        self.bot_gearth_status_var=tk.StringVar(
            value='Choose Direct TCP or G-Earth for each profile in Accounts.')
        self.bot_account_var=tk.StringVar(value='')
        self.bot_action_var=tk.StringVar(value='Say')
        self.bot_message_var=tk.StringVar(value='')
        self.bot_recipient_var=tk.StringVar(value='')
        self.bot_room_var=tk.StringVar(value=clientless_saved_room_value(
            self.config.get('clientless_last_room_id')))
        self.bot_x_var=tk.StringVar(value='0')
        self.bot_y_var=tk.StringVar(value='0')
        self.bot_id_var=tk.StringVar(value='1')
        self.bot_status_var=tk.StringVar(value=
            'Choose a saved profile to connect directly and join your saved room. '
            'HabboAIR and G-Earth are not required for the bundled AIR release.')
        self._classic_probe_running=False
        self.tcp_status_var=tk.StringVar(
            value='Real TCP: enter an official ticket or save an authenticated Habbo session.')
        self.tcp_ticket_var=tk.StringVar(value='')
        self.tcp_session_id_var=tk.StringVar(value='')
        self.tcp_browser_token_var=tk.StringVar(value='')
        self.tcp_autostart_var=tk.BooleanVar(
            value=bool(self.config.get('tcp_auto_connect',False)))
        self.tcp_proxy_enabled_var=tk.BooleanVar(
            value=self.config.get('tcp_proxy_enabled') is True)
        self.tcp_proxy_url_var=tk.StringVar(
            value=str(self.config.get('tcp_proxy_url','socks5://127.0.0.1:1080')))
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
        self.packet_auto_capture_var=tk.BooleanVar(
            value=bool(self.config.get('packet_auto_capture',True)))
        self.packet_started=False
        self.packet_extension=None
        # Passive G-Earth metadata: no raw payloads, tickets, or chat text stored.
        self.fuzz_monitoring=False
        self.fuzz_counts={}
        self.fuzz_seen=0
        self.fuzz_running=False
        self.fuzz_last_result=None
        self.fuzz_target_ip_var=tk.StringVar(value='127.0.0.1')
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
        self.packet_connection_status=tk.StringVar(
            value='Packet viewer waiting for a G-Earth/Habbo connection; no packets received yet.')
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
        # Saved looks are validated client-observed clothing figure strings,
        # never arbitrary packets, credentials, or user-supplied headers.
        self.outfit_presets=sanitize_outfit_presets(
            self.config.get('outfit_presets',[]))
        self.outfit_status_var=tk.StringVar(
            value='Capture at least two looks from the Habbo Looks editor.')
        self.outfit_delay_var=tk.StringVar(
            value=initial_outfit_delay_ms(self.config))
        self._outfit_capture_pending=False
        self._outfit_capture_generation=0
        self._outfit_running=False
        self._outfit_generation=0
        self._outfit_after_id=None
        self._outfit_index=0
        self._outfit_sent=0
        self._outfit_interval_ms=300.0
        # Face Rotator: one deliberately captured standing square per room,
        # eight LookTo directions, never a MoveAvatar request.
        self.face_status_var=tk.StringVar(
            value='Capture your standing tile by clicking your own avatar.')
        self.face_delay_var=tk.StringVar(
            value=str(self.config.get('face_delay_ms','350')))
        self.face_direction_var=tk.StringVar(
            value=str(self.config.get('face_direction','Clockwise')))
        self._face_tile=None
        self._face_capture_pending=False
        self._face_capture_generation=0
        self._face_running=False
        self._face_generation=0
        self._face_after_id=None
        self._face_targets=()
        self._face_step=0
        self._face_sent=0
        self._face_interval_ms=350
        # Dance Controller uses only named Dance(0..4) commands,
        # never fakes Habbo Club access or assumes server confirmation.
        self.dance_status_var=tk.StringVar(
            value='Choose a dance style, then press Dance. Habbo Club '
                  'may be required for Pogo Mogo, Duck Funk and The Rollie.')
        self.dance_style_var=tk.StringVar(
            value=str(self.config.get('dance_selected','Hab-Hop (everyone)')))
        if self.dance_style_var.get() not in DANCE_STYLE_NAMES.values():
            self.dance_style_var.set(DANCE_STYLE_NAMES[1])
        self.dance_delay_var=tk.StringVar(
            value=str(self.config.get('dance_delay_ms','3000')))
        selected=self.config.get('dance_cycle_selected',[1,2,3,4])
        if not isinstance(selected,(list,tuple)):
            selected=[1,2,3,4]
        self.dance_enabled_vars={
            i:tk.BooleanVar(value=i in selected) for i in (1,2,3,4)}
        self._dance_running=False
        self._dance_generation=0
        self._dance_after_id=None
        self._dance_sequence=()
        self._dance_step=0
        self._dance_sent=0
        self._dance_interval_ms=3000
        self._dance_last_sent_id=None
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
        self.packet_status=tk.StringVar(value=(
            'Preparing G-Earth. Packet capture will start automatically when Habbo connects.'
            if self.config.get('gearth_auto_arm') else
            'G-Earth auto-start is OFF. Start the engine and connect Habbo to view live packets.'))
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
        self._game_panel_windows=set()
        self._game_panel_pending=[]
        self._game_panel_target=None
        self._game_panel_restore=None
        self._game_panel_last_scan=0.0
        self.status=tk.StringVar(value='Waiting for Habbo...')
        self.scroll_status=tk.StringVar(value='LIVE · scroll up over the chat to see older messages')
        self.cfg_vars={}
        self.canvas_font=None;self.canvas_bold=None
        self._make_overlay()
        self._make_settings()
        self.root.protocol('WM_DELETE_WINDOW',self._game_panel_close_or_exit)
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
        style.configure('.',font=('Segoe UI',9),background=p['background'],foreground=p['text'])
        style.configure('TRadiobutton',background=p['background'],foreground=p['text'],padding=2)
        style.map('TRadiobutton',background=[('active',p['background'])],foreground=[('disabled',p['faint'])])
        style.configure('Panel.TFrame',background=p['background'])
        style.configure('Sidebar.TFrame',background=p['sidebar'])
        style.configure('Card.TFrame',background=p['surface'])
        style.configure('TLabel',background=p['background'],
                        foreground=p['text'],font=('Segoe UI',9))
        style.configure('Panel.TLabel',background=p['background'],
                        foreground=p['text'],font=('Segoe UI',9))
        style.configure('Card.TLabel',background=p['surface'],
                        foreground=p['text'],font=('Segoe UI',9))
        style.configure('Muted.TLabel',background=p['background'],
                        foreground=p['muted'],font=('Segoe UI',9))
        style.configure('TCheckbutton',background=p['background'],
                        foreground=p['text'],font=('Segoe UI',9),padding=2)
        style.map('TCheckbutton',
                  background=[('active',p['background'])],
                  foreground=[('disabled',p['faint'])])
        style.configure('Panel.TCheckbutton',background=p['background'],
                        foreground=p['text'],font=('Segoe UI',9),padding=2)
        style.map('Panel.TCheckbutton',
                  background=[('active',p['background'])],
                  foreground=[('disabled',p['faint'])])
        style.configure('TButton',font=('Segoe UI Semibold',9),
                        padding=(8,4),background=p['raised'],
                        foreground=p['text'],borderwidth=0,relief='flat',
                        focusthickness=0,focuscolor=p['raised'])
        style.map('TButton',
                  background=[('disabled',p['surface']),
                              ('pressed','#383840'),
                              ('active','#323239')],
                  foreground=[('disabled',p['faint'])])
        style.configure('Primary.TButton',
                        font=('Segoe UI Semibold',9),padding=(10,5),
                        background=p['accent'],foreground='#FFFFFF',
                        borderwidth=0,relief='flat')
        style.map('Primary.TButton',
                  background=[('pressed','#4752C4'),
                              ('active',p['accent_hover'])],
                  foreground=[('disabled',p['faint'])])
        style.configure('Danger.TButton',background='#402529',
                        foreground='#FFD4DB',font=('Segoe UI',9),
                        padding=(8,4),borderwidth=0)
        style.map('Danger.TButton',background=[('active','#563036')])
        style.configure('TEntry',fieldbackground=p['field'],
                        foreground=p['text'],insertcolor=p['text'],
                        bordercolor=p['border'],lightcolor=p['border'],
                        darkcolor=p['border'],padding=(6,4))
        style.map('TEntry',bordercolor=[('focus',p['accent'])])
        style.configure('TCombobox',fieldbackground=p['field'],
                        foreground=p['text'],arrowcolor=p['muted'],
                        background=p['raised'],padding=2)
        style.map('TCombobox',
                  fieldbackground=[('readonly',p['field']),('disabled',p['surface'])],
                  foreground=[('readonly',p['text']),('disabled',p['faint'])],
                  selectbackground=[('readonly','#383F78')],
                  selectforeground=[('readonly',p['text'])])
        self.root.option_add('*TCombobox*Listbox.background',p['field'])
        self.root.option_add('*TCombobox*Listbox.foreground',p['text'])
        self.root.option_add('*TCombobox*Listbox.selectBackground','#383F78')
        self.root.option_add('*TCombobox*Listbox.selectForeground',p['text'])
        style.configure('TScale',background=p['background'],
                        troughcolor=p['raised'])
        style.configure('TLabelframe',background=p['background'],
                        bordercolor=p['border'])
        style.configure('TLabelframe.Label',background=p['background'],
                        foreground=p['text'])
        style.configure('Treeview',background=p['surface'],
                        fieldbackground=p['surface'],foreground=p['text'],
                        rowheight=24,borderwidth=0,relief='flat',
                        font=('Segoe UI',9))
        style.configure('Treeview.Heading',background=p['raised'],
                        foreground=p['muted'],padding=(6,4),
                        font=('Segoe UI Semibold',9),relief='flat')
        style.map('Treeview',
                  background=[('selected','#383F78')],
                  foreground=[('selected',p['text'])])
        style.map('Treeview.Heading',
                  background=[('active','#303036')])
        style.configure('Vertical.TScrollbar',
                        background=p['raised'],troughcolor=p['background'],
                        arrowcolor=p['muted'],borderwidth=0)
        style.configure('TNotebook',background=p['background'],borderwidth=0)
        style.configure('TNotebook.Tab',background=p['raised'],
                        foreground=p['muted'],padding=(9,5))
        style.map('TNotebook.Tab',
                  background=[('selected',p['surface']),
                              ('active','#303036')],
                  foreground=[('selected',p['text'])])

    def _ui_nav_button(self,parent,title,callback,primary=False):
        p=COMPANION_UI
        return tk.Button(parent,text=title,command=callback,
            font=('Segoe UI Semibold',10 if primary else 9),
            bg=p['sidebar'],fg=p['muted'],activebackground=p['raised'],
            activeforeground=p['text'],highlightbackground=p['sidebar'],
            highlightcolor=p['accent'],highlightthickness=1,relief='flat',
            borderwidth=0,cursor='hand2',padx=11 if primary else 9,
            pady=6 if primary else 3,takefocus=True)

    def _ui_add_nav(self,parent,group,items):
        keys=tuple(item[0] for item in items)
        self._ui_group_pages[group]=keys
        self._ui_group_last[group]=keys[0]
        for key in keys:
            self._ui_page_group[key]=group
        button=self._ui_nav_button(parent,group,
            lambda g=group:self._ui_show_page(self._ui_group_last[g]),True)
        button.pack(side='left',padx=(0,3))
        self._ui_group_buttons[group]=button
        if len(items)==1:
            self._ui_nav_buttons[keys[0]]=button
            return
        row=tk.Frame(self._ui_subnav,bg=COMPANION_UI['sidebar'])
        self._ui_group_rows[group]=row
        for key,title,_subtitle in items:
            child=self._ui_nav_button(row,title,lambda dest=key:self._ui_show_page(dest))
            child.pack(side='left',padx=(0,2))
            self._ui_nav_buttons[key]=child

    def _ui_show_page(self,key):
        if key not in self._ui_pages:
            return
        self._ui_active=key
        self._ui_pages[key].tkraise()
        p=COMPANION_UI
        title,subtitle=self._ui_page_meta[key]
        self._ui_title_var.set(title)
        self._ui_subtitle_var.set(subtitle)
        group=self._ui_page_group[key]
        self._ui_group_last[group]=key
        for name,button in self._ui_group_buttons.items():
            chosen=name==group
            button.configure(bg=p['raised'] if chosen else p['sidebar'],
                             fg=p['text'] if chosen else p['muted'])
        for dest,button in self._ui_nav_buttons.items():
            if button in self._ui_group_buttons.values():
                continue
            chosen=dest==key
            button.configure(bg=p['raised'] if chosen else p['sidebar'],
                             fg=p['accent_hover'] if chosen else p['muted'])
        for row in self._ui_group_rows.values():
            row.pack_forget()
        row=self._ui_group_rows.get(group)
        if row is None:
            self._ui_subnav.pack_forget()
        else:
            self._ui_subnav.pack(fill='x',before=self._ui_stack)
            row.pack(fill='x',padx=10,pady=(2,3))
        if key=='accounts':
            self._ui_refresh_dashboard()

    def _ui_scroll_area(self,page,key,*,style='Panel.TFrame',padding=0):
        """Scroll long tool panels without hiding controls on smaller displays."""
        background=ttk.Style(self.root).lookup(style,'background')
        holder=ttk.Frame(page,style=style)
        holder.pack(fill='both',expand=True)
        holder.rowconfigure(0,weight=1)
        holder.columnconfigure(0,weight=1)
        canvas=tk.Canvas(holder,bg=background,borderwidth=0,highlightthickness=0)
        bar=ttk.Scrollbar(holder,orient='vertical',command=canvas.yview)

        def update_scrollbar(first,last):
            bar.set(first,last)
            if float(first)==0 and float(last)==1:
                bar.grid_remove()
            else:
                bar.grid()

        canvas.configure(yscrollcommand=update_scrollbar)
        canvas.grid(row=0,column=0,sticky='nsew')
        bar.grid(row=0,column=1,sticky='ns')
        inside=ttk.Frame(canvas,style=style,padding=padding)
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
        if isinstance(event.widget,(ttk.Treeview,tk.Text,ttk.Combobox,tk.Listbox)):
            return
        key=self._ui_active
        canvas=self._ui_scroll_canvases.get(key)
        if canvas is not None and event.delta:
            steps=max(1,abs(event.delta)//120)
            canvas.yview_scroll(-steps if event.delta > 0 else steps,'units')

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

    def _ui_dashboard_pulse(self):
        if not self.root.winfo_exists():
            return
        self._ui_refresh_dashboard()
        self.root.after(1700,self._ui_dashboard_pulse)

    def _make_dashboard_panel(self,parent):
        """Compact account totals; no duplicate navigation or connection controls."""
        strip=ttk.Frame(parent,style='Panel.TFrame')
        strip.pack(fill='x',pady=(0,10))
        self._ui_dashboard_vars={}
        for key,label in (('accounts','Saved'),('connected','Connected clientless'),
                          ('connecting','Connecting')):
            variable=tk.StringVar(value='0')
            self._ui_dashboard_vars[key]=variable
            ttk.Label(strip,text=label+':',style='Muted.TLabel').pack(side='left',padx=(0,4))
            ttk.Label(strip,textvariable=variable,style='Panel.TLabel').pack(side='left',padx=(0,16))
        self._ui_refresh_dashboard()

    def _make_settings(self):
        """Build the compact top-navigation workspace."""
        self._ui_styles()
        p=COMPANION_UI
        self._ui_pages={}
        self._ui_scroll_canvases={}
        self._ui_nav_buttons={}
        self._ui_active='accounts'
        navigation = (
            ('Accounts', (
                ('accounts', 'Accounts', 'Saved profiles and launch modes'),
            )),
            ('Clientless Bot', (
                ('bot', 'Clientless Bot', 'Room, chat and avatar controls'),
            )),
            ('Chat & AI', (
                ('chat', 'View Chat', 'Original Habbo bubbles and overlay settings'),
                ('responder', 'AI Responder', 'Writing style and room targets'),
            )),
            ('Tools', (
                ('outfits', 'Outfits', 'Capture and rotate through saved looks'),
                ('face', 'Face', 'Turn in place without walking'),
                ('dance', 'Dance', 'Choose and cycle through dance moves'),
                ('packet', 'Packet Viewer', 'G-Earth connection, filters and traffic'),
                ('manip', 'Packet Rules', 'Packet rules and manual actions'),
                ('fuzz', 'Protocol Lab', 'Passive G-Earth reader and protocol tests'),
                ('headless', 'Headless Test', 'Local connection testing'),
            )),
            ('Settings', (
                ('updates', 'Updates', 'Check, install and restore updates'),
            )),
        )
        self._ui_page_meta = {
            key: (title, subtitle)
            for _group, items in navigation
            for key, title, subtitle in items
        }
        self._ui_group_pages={}
        self._ui_group_last={}
        self._ui_page_group={}
        self._ui_group_buttons={}
        self._ui_group_rows={}
        self._ui_title_var=tk.StringVar()
        self._ui_subtitle_var=tk.StringVar()
        shell=tk.Frame(self.root,bg=p['background'])
        shell.pack(fill='both',expand=True)
        top=tk.Frame(shell,bg=p['sidebar'])
        top.pack(fill='x')
        tk.Label(top,text='H',font=('Segoe UI Black',13),bg=p['accent'],
                 fg='#FFFFFF',width=2,pady=2).pack(side='left',padx=(9,8),pady=5)
        nav=tk.Frame(top,bg=p['sidebar'])
        nav.pack(side='left',fill='x',expand=True)
        tk.Label(top,text='Shift + `  •  game panel',font=('Segoe UI',9),
                 bg=p['sidebar'],fg=p['muted']).pack(side='right',padx=9)
        self._ui_subnav=tk.Frame(shell,bg=p['sidebar'])
        for group,items in navigation:
            self._ui_add_nav(nav,group,items)
        tk.Frame(shell,bg=p['border'],height=1).pack(fill='x')
        stack=tk.Frame(shell,bg=p['background'])
        self._ui_stack=stack
        stack.pack(fill='both',expand=True,padx=6,pady=4)
        stack.grid_rowconfigure(0,weight=1)
        stack.grid_columnconfigure(0,weight=1)
        for key in self._ui_page_meta:
            page=ttk.Frame(stack,style='Panel.TFrame')
            page.grid(row=0,column=0,sticky='nsew')
            self._ui_pages[key]=page
        self._make_packet_panel(self._ui_scroll_area(
            self._ui_pages['packet'],'packet'))
        self._make_outfit_panel(self._ui_scroll_area(
            self._ui_pages['outfits'],'outfits'))
        self._make_face_panel(self._ui_scroll_area(
            self._ui_pages['face'],'face'))
        self._make_dance_panel(self._ui_scroll_area(
            self._ui_pages['dance'],'dance'))
        self._make_fuzz_panel(self._ui_scroll_area(
            self._ui_pages['fuzz'],'fuzz'))
        self._make_responder_panel(self._ui_scroll_area(
            self._ui_pages['responder'],'responder'))
        self._make_accounts_panel(self._ui_scroll_area(
            self._ui_pages['accounts'],'accounts'))
        self._make_clientless_tabs(self._ui_pages['bot'])
        self._make_headless_panel(self._ui_scroll_area(
            self._ui_pages['headless'],'headless'))
        self._make_manipulator_panel(self._ui_scroll_area(
            self._ui_pages['manip'],'manip'))
        self._make_updates_panel(self._ui_scroll_area(
            self._ui_pages['updates'],'updates'))
        self._make_chat_panel(self._ui_scroll_area(
            self._ui_pages['chat'],'chat',padding=(18,14)))
        self.root.bind('<MouseWheel>',self._ui_mousewheel)
        self._ui_show_page('accounts')
        self.root.after(1700,self._ui_dashboard_pulse)

    def _make_chat_panel(self,f):
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


    def _make_clientless_connection_panel(self, parent):
        """Connection preferences and diagnostics for the shared clientless backend."""
        f=ttk.Frame(parent,style='Panel.TFrame',padding=9)
        f.pack(fill='both',expand=True)
        tk.Label(f,text='CLIENTLESS CONNECTION SETTINGS',
                 font=('Segoe UI Semibold',13),bg=COMPANION_UI['background'],
                 fg=COMPANION_UI['text']).pack(anchor='w',pady=(0,8))
        ttk.Label(f,text='Manage account connections in Accounts.',
                  style='Panel.TLabel',wraplength=615).pack(anchor='w',fill='x',pady=(0,10))
        proxy_row=ttk.Frame(f,style='Panel.TFrame')
        proxy_row.pack(fill='x',pady=(0,6))
        ttk.Checkbutton(proxy_row,text='Use SOCKS5 proxy',
            variable=self.tcp_proxy_enabled_var,command=self._tcp_proxy_changed,
            style='Panel.TCheckbutton').pack(side='left',padx=(0,8))
        ttk.Entry(proxy_row,textvariable=self.tcp_proxy_url_var,width=34).pack(
            side='left',fill='x',expand=True,padx=(0,6))
        ttk.Button(proxy_row,text='Save',command=self._tcp_proxy_changed).pack(side='left')
        ttk.Label(f,text='Shared game TCP proxy for new connections only. '
            'Browser sign-in is unchanged. Requires a trusted SOCKS5 service '
            'and python-socks (python -m pip install python-socks).',
            style='Panel.TLabel',wraplength=615).pack(anchor='w',pady=(0,8))
        ttk.Checkbutton(
            f,
            text='Automatically connect saved TCP accounts when Companion opens',
            variable=self.tcp_autostart_var,
            command=self._tcp_autostart_changed,
            style='Panel.TCheckbutton').pack(anchor='w',pady=(3,9))
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
        ttk.Label(f,text='TCP connection log',style='Panel.TLabel').pack(anchor='w')
        show_packet_ids=tk.BooleanVar(value=self._tcp_log_packet_ids)

        def update_packet_logging():
            self._tcp_log_packet_ids=show_packet_ids.get()

        ttk.Checkbutton(f,text='Show incoming packet IDs',variable=show_packet_ids,
                        command=update_packet_logging,
                        style='Panel.TCheckbutton').pack(anchor='w')
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

    def _make_clientless_tabs(self,parent):
        header=ttk.Frame(parent,style='Panel.TFrame',padding=(9,5))
        header.pack(fill='x')
        tabs=ttk.Notebook(parent)
        tabs.pack(fill='both',expand=True,padx=7,pady=(2,0))
        actions=ttk.Frame(tabs,style='Panel.TFrame')
        automation=ttk.Frame(tabs,style='Panel.TFrame')
        coffee=ttk.Frame(tabs,style='Panel.TFrame')
        connection=ttk.Frame(tabs,style='Panel.TFrame')
        tabs.add(actions,text='Actions & chat')
        tabs.add(automation,text='Automation')
        tabs.add(coffee,text='Coffee Pass')
        tabs.add(connection,text='Settings')
        # Build connection widgets first for the shared status renderer.
        settings=self._ui_scroll_area(connection,'bot_connection')
        self._make_clientless_connection_panel(settings)
        self._make_clientless_bot_panel(
            header,self._ui_scroll_area(actions,'bot_actions'),
            self._ui_scroll_area(automation,'bot_automation'),settings)
        self._make_clientless_coffee_panel(self._ui_scroll_area(coffee,'bot_coffee'))
        def select_scroll(_event=None):
            key={str(actions):'bot_actions',
                 str(automation):'bot_automation',str(coffee):'bot_coffee',
                 str(connection):'bot_connection'}.get(tabs.select(),'bot_actions')
            self._ui_scroll_canvases['bot']=self._ui_scroll_canvases[key]
            if key=='bot_coffee':
                self._coffee_refresh_accounts()
        tabs.bind('<<NotebookTabChanged>>',select_scroll)
        select_scroll()
        self._coffee_refresh_accounts()

    def _make_clientless_bot_panel(self,header,actions,automation,settings):
        """Build compact session, manual action and automation views."""
        ttk.Label(header,text='Choose the connection mode in Accounts.',
                  style='Muted.TLabel').pack(anchor='w',pady=(0,5))
        context=ttk.Frame(header,style='Panel.TFrame')
        context.pack(fill='x')
        ttk.Label(context,text='Connected accounts',
                  style='Panel.TLabel').grid(row=0,column=0,sticky='w',padx=(0,10))
        ttk.Label(context,text='Room ID',style='Panel.TLabel').grid(row=0,column=1,sticky='w')
        self.bot_account_picker=ttk.Combobox(
            context,textvariable=self.bot_account_var,state='readonly',width=32)
        self.bot_account_picker.grid(row=1,column=0,sticky='ew',padx=(0,10),pady=(3,4))
        ttk.Entry(context,textvariable=self.bot_room_var,width=13).grid(
            row=1,column=1,sticky='w',pady=(3,4))
        context.columnconfigure(0,weight=1)
        self.bot_account_picker.bind(
            '<<ComboboxSelected>>',lambda _event:self._bot_select_only())
        ttk.Label(header,textvariable=self.bot_status_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(3,0))

        frame=ttk.Frame(automation,style='Panel.TFrame',padding=8)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='AUTOMATIC WALKING',style='Section.TLabel').pack(
            anchor='w',pady=(6,5))
        ttk.Label(frame,text='Saved positions apply to the Room ID above; backups are tried in order.',
                  style='Muted.TLabel',wraplength=620).pack(anchor='w',pady=(0,7))
        walkrow=ttk.Frame(frame,style='Panel.TFrame')
        walkrow.pack(fill='x',pady=(0,5))
        ttk.Label(walkrow,text='Primary X,Y',style='Panel.TLabel').pack(side='left')
        ttk.Entry(walkrow,textvariable=self.bot_walk_primary_var,
                  width=12).pack(side='left',padx=(10,18))
        ttk.Label(walkrow,text='Backups (X,Y;X,Y;X,Y)',
                  style='Panel.TLabel').pack(side='left')
        ttk.Entry(walkrow,textvariable=self.bot_walk_backups_var,
                  width=24).pack(side='left',padx=(9,0),fill='x',expand=True)
        walkbuttons=ttk.Frame(frame,style='Panel.TFrame')
        walkbuttons.pack(fill='x',pady=(0,7))
        ttk.Checkbutton(walkbuttons,text='Walk automatically after room entry',
                        variable=self.bot_auto_walk_var,
                        command=self._bot_save_walk_preset,
                        style='Panel.TCheckbutton').pack(side='left',padx=(0,8))
        ttk.Button(walkbuttons,text='Save positions',
                   command=self._bot_save_walk_preset).pack(side='left',padx=(0,6))
        ttk.Button(walkbuttons,text='Load room positions',
                   command=self._bot_load_walk_preset).pack(side='left')
        override_buttons=ttk.Frame(frame,style='Panel.TFrame')
        override_buttons.pack(fill='x',pady=(0,6))
        ttk.Button(override_buttons,text='Save positions for current account',
                   command=self._bot_save_account_walk_preset).pack(
                       side='left',padx=(0,7))
        ttk.Button(override_buttons,text='Clear account override',
                   command=self._bot_clear_account_walk_preset).pack(side='left')
        ttk.Label(frame,text='Room presets are shared unless an account override is saved.',
                  style='Muted.TLabel',wraplength=620).pack(anchor='w',pady=(0,5))
        ttk.Label(frame,textvariable=self.bot_walk_status_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,12))
        ttk.Label(frame,text='FOLLOW USER',style='Section.TLabel').pack(anchor='w',pady=(6,5))
        ttk.Label(frame,text='Follow the exact X/Y coordinates of a named room bot or another connected account you control. '
                  'Coordinates update when the target moves in the same room.',
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,5))
        self.bot_follow_target_var=tk.StringVar(value='')
        self.bot_follow_status_var=tk.StringVar(value='Follow is off.')
        ttk.Label(frame,text='Target Habbo username',style='Panel.TLabel').pack(anchor='w')
        ttk.Entry(frame,textvariable=self.bot_follow_target_var,width=42).pack(anchor='w',pady=(3,5))
        self.bot_follow_all_var=tk.BooleanVar(value=False)
        ttk.Checkbutton(frame,text='All connected accounts — follow target coordinate changes',
                        variable=self.bot_follow_all_var,command=self._bot_follow_group_toggle,
                        style='Panel.TCheckbutton').pack(anchor='w',pady=(0,5))
        follow_buttons=ttk.Frame(frame,style='Panel.TFrame')
        follow_buttons.pack(anchor='w',pady=(0,5))
        ttk.Button(follow_buttons,text='Start following',style='Primary.TButton',
                   command=self._bot_follow_start).pack(side='left',padx=(0,6))
        ttk.Button(follow_buttons,text='Stop following',
                   command=self._bot_follow_stop).pack(side='left',padx=(0,6))
        ttk.Label(frame,textvariable=self.bot_follow_status_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,12))
        ttk.Label(frame,text='STATIONARY ANTI-AFK (EXPERIMENTAL)',
                  style='Section.TLabel').pack(anchor='w',pady=(1,5))
        ttk.Checkbutton(
            frame,text='Enable anti-AFK for this saved account',
            variable=self.bot_anti_afk_var,
            command=self._bot_anti_afk_changed,
            style='Panel.TCheckbutton').pack(anchor='w',pady=(0,6))
        ttk.Label(frame,text='Stationary LookTo about every four minutes in a confirmed room. '
                  'Server-side AFK prevention is not guaranteed.',
                  style='Muted.TLabel',wraplength=620).pack(anchor='w',pady=(0,5))
        ttk.Label(frame,textvariable=self.bot_anti_afk_status_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,12))
        frame=ttk.Frame(actions,style='Panel.TFrame',padding=8)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='SAVED ROOM',style='Section.TLabel').pack(
            anchor='w',pady=(0,5))
        favorite=ttk.Frame(frame,style='Panel.TFrame')
        favorite.pack(fill='x',pady=(0,4))
        ttk.Label(favorite,text='Coffee House  ·  Room 69118545',
                  style='Panel.TLabel').pack(side='left',padx=(0,15))
        self.bot_coffee_house_button=ttk.Button(
            favorite,text='Join Coffee House',
            command=self._bot_join_coffee_house)
        self.bot_coffee_house_button.pack(side='left')
        ttk.Label(frame,text='Joins only when clicked.',
                  style='Muted.TLabel').pack(anchor='w',pady=(0,8))

        # Both manual actions and automation use the explicit connected-account selection.
        self.bot_action_account_var=self.bot_account_var
        self.bot_action_account_picker=self.bot_account_picker
        ttk.Label(frame,text='MANUAL ACCOUNT ACTIONS',style='Section.TLabel').pack(anchor='w',pady=(4,5))
        ttk.Label(frame,text='Action',style='Panel.TLabel').pack(anchor='w')
        self.bot_action_picker=ttk.Combobox(
            frame,textvariable=self.bot_action_var,state='readonly',width=25,
            values=('Say','Shout','Whisper','Join room','Leave room',
                    'Walk','Face tile','Dance','Sign','Posture'))
        self.bot_action_picker.pack(anchor='w',pady=(3,9))
        # Keep one room field in the shared header. Only show inputs for
        # the chosen manual action; switching actions never sends packets.
        fields={}
        for key,label,var in (
            ('message','Message',self.bot_message_var),
            ('recipient','Recipient username',self.bot_recipient_var),
            ('x','Tile X',self.bot_x_var),
            ('y','Tile Y',self.bot_y_var),
            ('number','Number',self.bot_id_var)):
            row=ttk.Frame(frame,style='Panel.TFrame')
            ttk.Label(row,text=label,width=25,style='Panel.TLabel').pack(side='left')
            ttk.Entry(row,textvariable=var,width=36).pack(side='left',fill='x',expand=True)
            fields[key]=row
        input_area=ttk.Frame(frame,style='Panel.TFrame')
        input_area.pack(fill='x')
        number_label=fields['number'].winfo_children()[0]
        # All fields are children of frame; pack them before the stable
        # anchor so the Send button and chat never change order.
        def show_action_fields(*_args):
            needed={
                'Say':('message',),'Shout':('message',),
                'Whisper':('recipient','message'),
                'Walk':('x','y'),'Face tile':('x','y'),
                'Dance':('number',),'Sign':('number',),'Posture':('number',),
            }.get(self.bot_action_var.get(),())
            number_label.configure(text={'Dance':'Dance number (0–4)',
                'Sign':'Sign number (0–14)','Posture':'Posture number (0–1)'}.get(
                    self.bot_action_var.get(),'Number'))
            for row in fields.values():
                row.pack_forget()
            for key in needed:
                fields[key].pack(fill='x',pady=(0,5),before=input_area)
        self.bot_action_var.trace_add('write',show_action_fields)
        show_action_fields()
        ttk.Button(frame,text='Send action to selected accounts',style='Primary.TButton',
                   command=self._bot_send_selected_action).pack(anchor='w',pady=(3,11))
        ttk.Label(frame,text='Incoming chat',style='Section.TLabel').pack(anchor='w',pady=(0,5))
        ttk.Label(frame,text='Public chat is merged per room; whispers stay account-specific.',
                  style='Muted.TLabel').pack(anchor='w',pady=(0,5))
        self.bot_chat_log=tk.Text(
            frame,height=7,state='disabled',
            bg=COMPANION_UI['field'],fg=COMPANION_UI['text'],
            relief='flat',font=('Consolas',9))
        self.bot_chat_log.pack(fill='both',expand=True,pady=(0,6))

        frame=ttk.Frame(settings,style='Panel.TFrame',padding=8)
        frame.pack(fill='x')
        diagnostics=ttk.LabelFrame(frame,text='Advanced diagnostics',padding=7)
        diagnostics.pack(fill='x',pady=(0,10))
        ttk.Button(diagnostics,text='Check bridge hostname',
                   command=self._bot_gearth_probe).pack(side='left',padx=(0,7))
        ttk.Button(diagnostics,text='Capture newer AIR mappings',
                   command=self._bot_capture_mapping).pack(side='left')
        ttk.Label(frame,textvariable=self.bot_gearth_status_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,10))
        self._bot_refresh_accounts()
        self._bot_load_walk_preset()
        self._bot_anti_afk_load_selected()
        # One bounded Tk timer for all authenticated profiles; no extra
        # background threads, no activity when disabled or disconnected.
        self.root.after(10000,self._bot_anti_afk_tick)

    def _bot_refresh_accounts(self):
        if not hasattr(self,'bot_account_picker'):
            return
        items=[a['label']+' ['+a['id'][:6]+']' for a in self._account_profiles
               if (session:=self._tcp_sessions.get(a['id'])) is not None
               and session.authenticated and not session.stop.is_set()]
        current=self.bot_account_var.get()
        if items:
            items.insert(0,'All connected accounts')
        self.bot_account_picker.configure(values=items)
        if current not in items:
            self.bot_account_var.set('')
        self._bot_anti_afk_load_selected()
        self._bot_refresh_action_accounts()
        if hasattr(self,'coffee_account_picker'):
            self._coffee_refresh_accounts()
        if hasattr(self,'bot_multi_tree'):
            self._bot_multi_refresh()

    def _make_clientless_coffee_panel(self,frame):
        content=ttk.Frame(frame,style='Panel.TFrame',padding=(18,16))
        content.pack(anchor='nw',fill='x')
        tk.Label(content,text='Coffee Pass',font=('Segoe UI Semibold',17),
                 bg=COMPANION_UI['background'],fg=COMPANION_UI['text']).pack(anchor='w')
        ttk.Label(content,text='Hand-item controls and connected account settings via Direct TCP.',
                  style='Muted.TLabel').pack(anchor='w',pady=(4,12))
        panel=ttk.Frame(content,style='Panel.TFrame')
        panel.pack(anchor='nw',pady=(0,12))
        self.coffee_account_var=tk.StringVar(value='')
        self.coffee_account_picker=ttk.Combobox(panel,textvariable=self.coffee_account_var,state='readonly',width=43)
        ttk.Label(panel,text='Connected sender',style='Panel.TLabel').pack(anchor='w')
        self.coffee_account_picker.pack(anchor='w',pady=(3,14))
        self.coffee_account_picker.bind('<<ComboboxSelected>>',lambda _event:self._coffee_load_settings())
        self.coffee_recipient_var=tk.StringVar(value='')
        self.coffee_one_var=tk.StringVar(value='476989081')
        self.coffee_two_var=tk.StringVar(value='476989024')
        self.coffee_consent_var=tk.BooleanVar(value=False)
        self.coffee_status_var=tk.StringVar(value='Select a connected account in a room.')
        for label,var in (('Recipient username or room player ID',self.coffee_recipient_var),
                          ('Cup 1 furniture ID',self.coffee_one_var),
                          ('Cup 2 furniture ID',self.coffee_two_var)):
            row=ttk.Frame(panel,style='Panel.TFrame')
            row.pack(anchor='w',pady=3)
            ttk.Label(row,text=label,width=34,style='Panel.TLabel').pack(side='left',padx=(0,12))
            ttk.Entry(row,textvariable=var,width=26).pack(side='left')
        ttk.Label(panel,text='The continuous loop alternates both furniture IDs until STOP. Local packet-send results do not verify server pickup or delivery.',
                  style='Muted.TLabel',wraplength=620).pack(anchor='w',pady=(3,0))
        ttk.Checkbutton(panel,text='I control the sending accounts',variable=self.coffee_consent_var,
                        style='Panel.TCheckbutton').pack(anchor='w')
        buttons=ttk.Frame(panel,style='Panel.TFrame')
        buttons.pack(anchor='w',pady=(8,3))
        for text,command in (('Collect cup 1',lambda:self._coffee_manual('Collect hand item',1)),
                             ('Collect cup 2',lambda:self._coffee_manual('Collect hand item',2)),
                             ('Pass held cup',lambda:self._coffee_manual('Pass hand item')),
                             ('Save settings',self._coffee_save_settings)):
            ttk.Button(buttons,text=text,command=command).pack(side='left',padx=(0,4))
        runs=ttk.Frame(panel,style='Panel.TFrame')
        runs.pack(anchor='w',pady=(5,8))
        ttk.Button(runs,text='Loop cups 1 and 2',style='Primary.TButton',
                   command=lambda:self._coffee_start_run(loop=True)).pack(side='left',padx=(0,7))
        ttk.Button(runs,text='STOP',style='Danger.TButton',
                   command=self._coffee_stop_run).pack(side='left')
        ttk.Label(panel,textvariable=self.coffee_status_var,style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(4,0))
        ttk.Label(content,text='CONNECTED ACCOUNTS',style='Section.TLabel').pack(anchor='w',pady=(4,8))
        group=ttk.Frame(content,style='Panel.TFrame')
        group.pack(anchor='nw',pady=(0,8))
        self.coffee_group_tree=ttk.Treeview(group,columns=('room','item','run'),
            show='tree headings',selectmode='extended',height=5)
        for key,label,width in (('#0','Account',180),('room','Room',90),
                                ('item','Hand item',100),('run','Pickup / run status',260)):
            self.coffee_group_tree.heading(key,text=label)
            self.coffee_group_tree.column(key,width=width,minwidth=65,stretch=True)
        self.coffee_group_tree.pack(fill='x',pady=(0,5))
        self.coffee_group_status_var=tk.StringVar(value='Highlight accounts to apply shared settings.')
        group_buttons=ttk.Frame(group,style='Panel.TFrame')
        group_buttons.pack(anchor='w')
        for label,command in (
                ('Select all connected',self._coffee_group_select_all),
                ('Deselect all',self._coffee_group_clear),
                ('Apply settings',self._coffee_group_apply),
                ('Stop all runs',self._coffee_group_stop)):
            ttk.Button(group_buttons,text=label,command=command).pack(side='left',padx=(0,4))
        ttk.Label(group,textvariable=self.coffee_group_status_var,style='Panel.TLabel',
                  wraplength=620).pack(anchor='w',pady=(4,0))

    def _coffee_refresh_accounts(self):
        picker=getattr(self,'coffee_account_picker',None)
        if picker is None:return
        items=[a['label']+' ['+a['id'][:6]+']' for a in self._account_profiles
               if self._coffee_session(a['id']) is not None]
        if items:
            items.insert(0,'All connected accounts')
        picker.configure(values=items)
        if self.coffee_account_var.get() not in items:
            self.coffee_account_var.set('')
            self.coffee_consent_var.set(False)
        batch=self._coffee_run
        if batch and any(
            self._coffee_session(run['id']) is None
            or (run['peer'] is not None and self._coffee_session(run['peer']) is None)
            for run in batch['runs'] if run['phase']!='complete'
        ):
            self._coffee_stop_run('Run stopped: account disconnected.')
        self._coffee_group_refresh()

    def _coffee_group_refresh(self):
        tree=getattr(self,'coffee_group_tree',None)
        if tree is None:return
        if not tree.winfo_exists():return
        highlighted=set(tree.selection())
        eligible=set()
        batch=self._coffee_run
        runs=batch['runs'] if batch else []
        for account in self._account_profiles:
            ident=account['id']
            if self._coffee_session(ident) is None:continue
            eligible.add(ident)
            room='—'
            item='Awaiting room'
            try:
                state,own,index=self._coffee_context(ident)
                room=str(state['room'])
                observed=state['carry'].get(index)
                item=('Not observed' if observed is None else
                      'Empty' if observed[0]==0 else 'Item '+str(observed[0]))
            except ClientlessBotError:
                pass
            run=next((r for r in runs if r['id']==ident),None)
            status=('Sender: '+run['phase'] if run else
                    'Receiver' if any(r['target']==self._bot_self_ids.get(ident) for r in runs) else 'Idle')
            if not run and status=='Idle':
                result=getattr(self,'_coffee_manual_results',{}).get(ident)
                if result is not None:
                    status=result['status']
            values=(room,item,status)
            if tree.exists(ident):
                tree.item(ident,text=account['label'],values=values)
            else:
                tree.insert('','end',iid=ident,text=account['label'],values=values)
        for ident in tree.get_children(''):
            if ident not in eligible:tree.delete(ident)
        keep=tuple(ident for ident in tree.get_children('') if ident in highlighted)
        if keep:tree.selection_set(keep)

    def _coffee_group_select_all(self):
        self._coffee_group_refresh()
        tree=self.coffee_group_tree
        ids=tuple(tree.get_children(''))
        if ids:tree.selection_set(ids)
        self.coffee_group_status_var.set(str(len(ids))+' connected account(s) selected.')

    def _coffee_group_clear(self):
        tree=self.coffee_group_tree
        selected=tree.selection()
        if selected:tree.selection_remove(selected)
        self.coffee_group_status_var.set('Selection cleared.')

    def _coffee_group_apply(self):
        selected=set(self.coffee_group_tree.selection())
        ids=[a['id'] for a in self._account_profiles
             if a['id'] in selected and self._coffee_session(a['id']) is not None]
        if not ids:
            self.coffee_group_status_var.set('Select connected accounts first.')
            return
        try:machines,_,_=self._coffee_settings()
        except ClientlessBotError as exc:
            self.coffee_group_status_var.set(str(exc));return
        raw=self.config.get('clientless_coffee_presets',{})
        presets=dict(raw) if isinstance(raw,dict) else {}
        for ident in ids:
            presets[ident]=dict(one=machines[0],two=machines[1])
        self.config['clientless_coffee_presets']=presets
        self.save()
        self.coffee_group_status_var.set('Settings saved for '+str(len(ids))+' connected account(s).')

    def _coffee_group_stop(self):
        results=getattr(self,'_coffee_manual_results',{})
        if any(r.get('status','').startswith('Queued') for r in results.values()):
            self._coffee_manual_results={}
        self._coffee_stop_run('All coffee runs stopped.')
        self._coffee_group_refresh()
        self.coffee_group_status_var.set('All coffee runs stopped. Accounts remain connected.')

    def _coffee_session(self,ident):
        session=self._tcp_sessions.get(ident)
        if (session is None or not session.authenticated or session.stop.is_set()
                or getattr(session,'gameplay_bridge',None) is not None):
            return None
        return session

    def _coffee_selected(self):
        selected=self.coffee_account_var.get()
        return next((a for a in self._account_profiles
                     if a['label']+' ['+a['id'][:6]+']'==selected and
                     self._coffee_session(a['id']) is not None),None)

    def _coffee_selected_accounts(self):
        if self.coffee_account_var.get()=='All connected accounts':
            return [a for a in self._account_profiles
                    if self._coffee_session(a['id']) is not None]
        account=self._coffee_selected()
        return [account] if account is not None else []

    def _coffee_load_settings(self):
        if self.coffee_account_var.get()=='All connected accounts':
            self.coffee_consent_var.set(False)
            self._coffee_group_select_all()
            self.coffee_status_var.set('All connected senders selected. Enter a player in the room to start the cup loop.')
            return
        account=self._coffee_selected()
        if account is None:return
        raw=self.config.get('clientless_coffee_presets',{})
        preset=raw.get(account['id'],{}) if isinstance(raw,dict) else {}
        if not isinstance(preset,dict):preset={}
        for key,var,default in (
                ('one',self.coffee_one_var,'476989081'),('two',self.coffee_two_var,'476989024')):
            var.set(str(preset.get(key,default)))
        self.coffee_consent_var.set(False)
        self.coffee_status_var.set('Selected '+account['label']+'.')

    def _coffee_settings(self,*,loop=True):
        # The panel exposes only continuous mode and furniture IDs.
        return validate_clientless_coffee_settings(self.coffee_one_var.get(),
            self.coffee_two_var.get(),'0',None if loop else '5')

    def _coffee_save_settings(self):
        accounts=self._coffee_selected_accounts()
        if not accounts:
            self.coffee_status_var.set('Select a connected account first.')
            return
        try:ids,_,_=self._coffee_settings()
        except ClientlessBotError as exc:
            self.coffee_status_var.set(str(exc));return
        raw=self.config.get('clientless_coffee_presets',{})
        presets=dict(raw) if isinstance(raw,dict) else {}
        for account in accounts:
            presets[account['id']]=dict(one=ids[0],two=ids[1])
        self.config['clientless_coffee_presets']=presets
        self.save()
        label=(str(len(accounts))+' connected account(s)' if self.coffee_account_var.get()=='All connected accounts'
               else accounts[0]['label'])
        self.coffee_status_var.set('Coffee settings saved for '+label+'.')

    def _coffee_observe(self,ident,generation,observation):
        kind,value=observation
        state=self._coffee_room_state.get(ident)
        if kind=='room':
            self._coffee_room_state[ident]=dict(generation=generation,room=value,players={},carry={})
            if self._coffee_run and any(ident in (r['id'],r['peer']) for r in self._coffee_run['runs']
                                        if r['phase']!='complete'):
                self._coffee_stop_run('Run stopped: room changed.')
            self._coffee_group_refresh()
            return
        if not state or state['generation']!=generation:return
        if kind=='players':
            state['players'].update(value)
            if len(state['players'])>200:state['players'].clear()
        elif kind=='remove':
            state['players']={uid:unit for uid,unit in state['players'].items() if unit[0]!=value}
            state['carry'].pop(value,None)
        elif kind=='carry':
            index,item=value
            if any(unit[0]==index for unit in state['players'].values()):
                state['carry'][index]=(item,time.monotonic())
        self._coffee_group_refresh()

    def _coffee_context(self,ident):
        state=self._coffee_room_state.get(ident)
        if (self._coffee_session(ident) is None or not state or
            state['generation']!=self._tcp_generation.get(ident,0)):
            raise ClientlessBotError('Join a room and wait for the server room roster.')
        own=self._bot_self_ids.get(ident)
        unit=state['players'].get(own)
        if unit is None:raise ClientlessBotError('Your avatar has not been identified in this room.')
        return state,own,unit[0]

    def _coffee_target(self,state,own):
        text=self.coffee_recipient_var.get().strip()
        matches=[uid for uid,unit in state['players'].items() if uid!=own and
                 (str(uid)==text or unit[1].casefold()==text.casefold())]
        if not text:
            raise ClientlessBotError('Enter a recipient username or player ID.')
        if not matches:
            own_unit=state['players'].get(own)
            if str(own)==text or (own_unit and own_unit[1].casefold()==text.casefold()):
                raise ClientlessBotError('This account is the recipient.')
            raise ClientlessBotError('Recipient not found in this account’s room roster.')
        if len(matches)!=1:
            raise ClientlessBotError('Multiple matching players. Enter the exact player ID.')
        return matches[0]

    def _coffee_send(self,ident,action,*,_start_gate=None,_manual_pickup=False,_manual_pass=False,_loop_action=False,**kwargs):
        session=self._coffee_session(ident)
        if session is None:raise ClientlessBotError('Account is not connected by Direct TCP.')
        if ident in self._bot_action_inflight:raise ClientlessBotError('Previous action is still sending.')
        now=time.monotonic()
        manual_action=(_manual_pickup and action=='Collect hand item') or (
            _manual_pass and action=='Pass hand item')
        if not (manual_action or _loop_action) and now-self._bot_last_action_at.get(ident,0)<0.4:
            raise ClientlessBotError('Previous action is still settling.')
        cooldowns=(self._coffee_last_pass if action=='Pass hand item' else self._coffee_last_pickup)
        last=cooldowns.get(ident,0.0)
        if not (manual_action or _loop_action) and now-last<10:
            raise ClientlessBotError('Please wait before sending another hand-item action.')
        packets=encode_clientless_action(self._bot_headers,session.release,action,**kwargs)
        generation=self._tcp_generation.get(ident,0)
        previous_action=self._bot_last_action_at.get(ident)
        previous_cooldown=cooldowns.get(ident)
        self._bot_action_inflight.add(ident)
        self._bot_last_action_at[ident]=now
        cooldowns[ident]=now
        def send_when_ready():
            if _start_gate is not None:
                _start_gate.wait()
            self._bot_action_worker(ident,generation,session,action,packets)
        try:
            threading.Thread(target=send_when_ready,daemon=True).start()
        except (RuntimeError,OSError):
            self._bot_action_inflight.discard(ident)
            if previous_action is None:self._bot_last_action_at.pop(ident,None)
            else:self._bot_last_action_at[ident]=previous_action
            if previous_cooldown is None:cooldowns.pop(ident,None)
            else:cooldowns[ident]=previous_cooldown
            raise
        return now

    def _coffee_manual(self,action,source=1):
        if self._coffee_run:
            self.coffee_status_var.set('Stop the active run before sending a manual cup.');return
        if self.coffee_account_var.get()=='All connected accounts':
            if action=='Pass hand item':
                self._coffee_pass_all()
            else:
                self._coffee_collect_all(source)
            return
        account=self._coffee_selected()
        if account is None:
            self.coffee_status_var.set('Select a connected account.');return
        ident=account['id']
        try:
            state,own,index=self._coffee_context(ident)
            if action=='Pass hand item':
                if state['carry'].get(index,(0,0))[0]<=0:
                    raise ClientlessBotError('Wait for your avatar to receive a hand item.')
                target=self._coffee_target(state,own)
                self._coffee_send(ident,action,recipient_id=target)
                state['carry'].pop(index,None)
            else:
                ids,_,_=self._coffee_settings()
                self._coffee_send(ident,action,furniture=ids[source-1])
                state['carry'].pop(index,None)
            self.coffee_status_var.set(account['label']+': request sent; waiting for server activity.')
        except (ValueError,TypeError,RuntimeError,OSError) as exc:
            self.coffee_status_var.set(str(exc)[:180])

    def _coffee_collect_all(self,source):
        try:
            ids,_,_=self._coffee_settings()
        except (ValueError,TypeError,RuntimeError,OSError) as exc:
            self.coffee_status_var.set(str(exc)[:180]);return
        accounts=tuple(self._coffee_selected_accounts())
        results={a['id']:{'status':'Queued','pending':False} for a in accounts}
        self._coffee_manual_results=results

        def dispatch():
            if self._coffee_manual_results is not results:return
            if getattr(self,'_coffee_run',None):
                for result in results.values():
                    result['status']='Skipped: Active cup run.'
                self._coffee_manual_report(results)
                return
            gate=threading.Event()
            try:
                for account in accounts:
                    ident=account['id']
                    result=results[ident]
                    try:
                        state,_,index=self._coffee_context(ident)
                        # A manual pickup is an explicit request even if an item is held.
                        # Preserve observed carry state until the server updates it.
                        self._coffee_send(ident,'Collect hand item',
                                          furniture=ids[source-1],_start_gate=gate,
                                          _manual_pickup=True)
                        result.update(status='Sending pickup packet',pending=True,
                                      generation=state['generation'])
                    except (ValueError,TypeError,RuntimeError,OSError) as exc:
                        detail=str(exc)[:110] if isinstance(exc,ClientlessBotError) else type(exc).__name__
                        result['status']='Skipped: '+detail
            finally:
                gate.set()
            self._coffee_manual_report(results)

        dispatch()

    def _coffee_pass_all(self):
        """Prepare and dispatch one explicit group pass without a local cooldown."""
        if not self.coffee_recipient_var.get().strip():
            self.coffee_status_var.set('Enter a recipient username or player ID.')
            return
        accounts=tuple(self._coffee_selected_accounts())
        results={a['id']:{'status':'Queued','pending':False,
                          'action':'Pass hand item'} for a in accounts}
        self._coffee_manual_results=results
        prepared={}
        target_id=None
        for account in accounts:
            ident=account['id']
            result=results[ident]
            try:
                state,own,index=self._coffee_context(ident)
                target=self._coffee_target(state,own)
                if target_id is not None and target!=target_id:
                    raise ClientlessBotError('Recipient differs between senders.')
                target_id=target
                prepared[ident]=(state['generation'],state['room'],own,index,target)
            except (ValueError,TypeError,RuntimeError,OSError) as exc:
                detail=str(exc)[:110] if isinstance(exc,ClientlessBotError) else type(exc).__name__
                result['status']='Skipped: '+detail

        def dispatch():
            if self._coffee_manual_results is not results:return
            if getattr(self,'_coffee_run',None):
                for ident in prepared:
                    results[ident]['status']='Skipped: Active cup run.'
                self._coffee_manual_report(results)
                return
            gate=threading.Event()
            try:
                for ident,(generation,room,own,index,target) in prepared.items():
                    result=results[ident]
                    try:
                        state,current_own,current_index=self._coffee_context(ident)
                        if (state['generation'],state['room'],current_own,current_index)!=(
                                generation,room,own,index) or target not in state['players']:
                            raise ClientlessBotError('Account or recipient changed rooms.')
                        if state['carry'].get(index,(0,0))[0]<=0:
                            raise ClientlessBotError('No held cup observed.')
                        self._coffee_send(ident,'Pass hand item',
                                          recipient_id=target,_start_gate=gate,_manual_pass=True)
                        result.update(status='Sending pass packet',pending=True,
                                      generation=generation)
                    except (ValueError,TypeError,RuntimeError,OSError) as exc:
                        detail=str(exc)[:110] if isinstance(exc,ClientlessBotError) else type(exc).__name__
                        result['status']='Skipped: '+detail
            finally:
                gate.set()
            self._coffee_manual_report(results)

        dispatch()

    def _coffee_manual_send_result(self,ident,generation,error,action='Collect hand item'):
        """Complete manual collection on local send outcome, not server pickup."""
        results=getattr(self,'_coffee_manual_results',{})
        result=results.get(ident)
        if (not result or not result.get('pending') or result.get('generation')!=generation
                or result.get('action','Collect hand item')!=action):
            return
        sent_status='Pass packet sent' if action=='Pass hand item' else 'Pickup packet sent'
        result.update(status=sent_status if error is None else
                      'Send failed: '+str(error)[:110],pending=False)
        self._coffee_manual_report(results)

    def _coffee_manual_report(self,results):
        """Summarize local sends without polling for hand-item confirmation."""
        if self._coffee_manual_results is not results:
            return
        passing=any(r.get('action')=='Pass hand item' for r in results.values())
        sent_status='Pass packet sent' if passing else 'Pickup packet sent'
        sent=sum(r['status']==sent_status for r in results.values())
        pending=sum(r['pending'] for r in results.values())
        skipped=sum(r['status'].startswith('Skipped:') for r in results.values())
        failed=len(results)-sent-pending-skipped
        if not self._coffee_run:
            self.coffee_status_var.set(
                f'{"Pass" if passing else "Pickup"} packets: {sent}/{len(results)} sent; {pending} sending; '
                f'{skipped} skipped; {failed} failed. Server {"delivery" if passing else "pickup"} not verified.')
        self._coffee_group_refresh()

    def _coffee_build_run(self,ident,ids,seconds,count):
        state,own,_=self._coffee_context(ident)
        target=self._coffee_target(state,own)
        peer=peer_generation=None
        if count is not None:
            peer=next((a['id'] for a in self._account_profiles
                       if a['id']!=ident and self._coffee_session(a['id']) is not None
                       and self._bot_self_ids.get(a['id'])==target),None)
            if peer is None:
                raise ClientlessBotError('Fixed runs require a second connected account you control. Use the cup loop for other room players.')
            other,_,_=self._coffee_context(peer)
            if other['room']!=state['room'] or own not in other['players']:
                raise ClientlessBotError('Both accounts must be confirmed in the same room.')
            peer_generation=other['generation']
        return dict(id=ident,peer=peer,target=target,
            generation=state['generation'],peer_generation=peer_generation,
            room=state['room'],ids=ids,delay=seconds,count=count,done=0,
            alternate=True,
            phase='next',at=time.monotonic())

    def _coffee_start_run(self,*,loop=True):
        if self._coffee_run:
            self.coffee_status_var.set('A coffee run is already active.');return
        accounts=self._coffee_selected_accounts()
        if not accounts:
            self.coffee_status_var.set('Select a connected account.');return
        try:
            ids,seconds,count=self._coffee_settings(loop=loop)
            if not self.coffee_consent_var.get():
                raise ClientlessBotError('Confirm you control the sending accounts before starting a run.')
            group=self.coffee_account_var.get()=='All connected accounts'
            runs=[]
            skipped=0
            for account in accounts:
                try:
                    run=self._coffee_build_run(account['id'],ids,seconds,count)
                    if runs and (run['peer']!=runs[0]['peer'] or run['target']!=runs[0]['target']):
                        raise ClientlessBotError('Recipient differs between senders.')
                    runs.append(run)
                except (ValueError,TypeError,RuntimeError,OSError):
                    if not group:raise
                    skipped+=1
            if not runs:
                if loop:
                    raise ClientlessBotError('No eligible senders. Enter a player in the same room.')
                raise ClientlessBotError('No eligible senders. Enter a connected recipient you control and join the same room.')
            batch=dict(runs=runs,skipped=skipped)
            self._coffee_run=batch
            self.coffee_group_status_var.set(str(len(runs))+' active sender(s); '+str(skipped)+
                ' skipped (recipient or unavailable). Synchronized ready pickups.')
            self._coffee_tick(batch)
        except (ValueError,TypeError,RuntimeError,OSError) as exc:
            self._coffee_stop_run(str(exc)[:180])

    def _coffee_stop_run(self,message='Coffee run stopped.'):
        batch=self._coffee_run
        self._coffee_run=None
        if batch and batch.get('loop_timer') is not None:
            self.root.after_cancel(batch.pop('loop_timer'))
        self.coffee_status_var.set(message)
        self._coffee_group_refresh()

    def _coffee_advance(self,run,now,pickup_gate=None):
        ident=run['id']
        state,own,index=self._coffee_context(ident)
        if state['generation']!=run['generation'] or state['room']!=run['room']:
            raise ClientlessBotError('Run stopped: account or room changed.')
        if run['target'] not in state['players']:
            raise ClientlessBotError('Run stopped: recipient is no longer in the room.')
        if run['peer'] is not None:
            other,peer_id,_=self._coffee_context(run['peer'])
            if (other['generation']!=run['peer_generation'] or other['room']!=run['room']
                or peer_id!=run['target'] or own not in other['players']):
                raise ClientlessBotError('Run stopped: account or room changed.')
        phase=run['phase']
        continuous=run['count'] is None
        ready=(ident not in self._bot_action_inflight and
               (continuous or now-self._bot_last_action_at.get(ident,0)>=0.4))
        ready_to_pass=ready and (continuous or now>=self._coffee_last_pass.get(ident,0)+10)
        loop_options={'_loop_action':True} if continuous else {}
        item,seen=state['carry'].get(index,(0,0))
        if continuous and not ready and now-run['at']>=20:
            raise ClientlessBotError('Run stopped: local send did not finish.')
        if phase=='next':
            if not ready or now<run['at']:
                return
            if continuous and item>0 and not run.get('loop_started') and not run['done']:
                if ready_to_pass:
                    run['at']=self._coffee_send(ident,'Pass hand item',recipient_id=run['target'],**loop_options)
                    run['phase']='pass held item'
                    run['loop_started']=True
                return
            if not continuous and now<self._coffee_last_pickup.get(ident,0)+10:
                return
            if not continuous and item>0:
                raise ClientlessBotError('Run stopped: avatar already holds an item.')
            slot=run['done']%2 if run['alternate'] else 0
            options=dict(loop_options)
            if pickup_gate is not None:
                options['_start_gate']=pickup_gate
            run['at']=self._coffee_send(ident,'Collect hand item',furniture=run['ids'][slot],**options)
            run['phase']='pickup'
            if continuous:
                run['loop_started']=True
        elif phase=='pickup':
            confirmed=item>0 and seen>=run['at']
            if not continuous and not confirmed and now-run['at']>20:
                raise ClientlessBotError('Run stopped: pickup was not confirmed.')
            required_delay=run['delay'] if continuous else max(0.4,run['delay'])
            if (continuous or confirmed) and ready_to_pass and now>=run['at']+required_delay:
                run['at']=self._coffee_send(ident,'Pass hand item',recipient_id=run['target'],**loop_options)
                run['phase']='pass'
        elif phase in ('pass','pass held item'):
            if run['count'] is not None:
                if now-run['at']>20:
                    raise ClientlessBotError('Run stopped: hand-item release was not confirmed.')
                if item!=0 or seen<run['at']:
                    return
            if ident in self._bot_action_inflight:
                if now-run['at']>20:
                    raise ClientlessBotError('Run stopped: pass send did not finish.')
                return
            if run['count'] is None and seen<=run['at']:
                # Drop the pre-pass observation so it cannot trigger a second pass.
                state['carry'].pop(index,None)
            if phase=='pass':
                run['done']+=1
            if run['count'] is not None and run['done']>=run['count']:
                run['phase']='complete'
            else:
                run['phase']='next'
                run['at']=now+run['delay']

    def _coffee_schedule_loop_tick(self,batch,delay_ms):
        """One replaceable UI timer, awakened by local send completions."""
        if self._coffee_run is not batch:return
        timer=batch.pop('loop_timer',None)
        if timer is not None:
            self.root.after_cancel(timer)
        def wake():
            if self._coffee_run is not batch:return
            batch.pop('loop_timer',None)
            self._coffee_tick(batch)
        batch['loop_timer']=self.root.after(delay_ms,wake)

    def _coffee_tick(self,batch):
        if self._coffee_run is not batch:return
        try:
            runs=batch['runs']
            now=time.monotonic()
            pickup_gate=threading.Event() if len(runs)>1 else None
            try:
                for run in runs:
                    if run['phase']!='complete':
                        if pickup_gate is None:
                            self._coffee_advance(run,now)
                        else:
                            self._coffee_advance(run,now,pickup_gate=pickup_gate)
            finally:
                if pickup_gate is not None:
                    pickup_gate.set()
            done=sum(r['done'] for r in runs)
            active=sum(r['phase']!='complete' for r in runs)
            if not active:
                self._coffee_stop_run('Run complete: '+str(done)+' releases observed across '+
                    str(len(runs))+' sender(s); '+str(batch['skipped'])+' skipped. Receipt not verified.')
                return
            if runs[0]['count'] is None:
                progress=f'Cup loop: {done} cup passes sent'
            else:
                total=sum(r['count'] for r in runs)
                progress=f'Coffee run: {done}/{total}'
            self.coffee_status_var.set(f'{progress} — {active}/{len(runs)} active sender(s)')
            self._coffee_group_refresh()
            if runs[0]['count'] is None:
                # Wait for the next configured deadline, or a socket-send event.
                # A watchdog still stops a stalled local send; no pickup ACK is required.
                deadlines=[]
                for run in runs:
                    if run['phase']=='complete':continue
                    if run['id'] in self._bot_action_inflight:
                        deadlines.append(run['at']+20)
                    elif run['phase']=='pickup':
                        deadlines.append(run['at']+run['delay'])
                    elif run['phase']=='next':
                        deadlines.append(run['at'])
                    else:
                        deadlines.append(now)
                remaining=max(0,min(deadlines)-time.monotonic())
                self._coffee_schedule_loop_tick(batch,int(remaining*1000)+1 if remaining else 0)
            else:
                self.root.after(250,lambda:self._coffee_tick(batch))
        except (ValueError,TypeError,RuntimeError,OSError) as exc:
            self._coffee_stop_run(str(exc)[:180])

    def _bot_select_only(self):
        all_selected=self.bot_account_var.get()=='All connected accounts'
        follow_var=getattr(self,'bot_follow_all_var',None)
        if follow_var is not None and bool(follow_var.get())!=all_selected:
            follow_var.set(all_selected)
            self._bot_follow_group_toggle()
        self._bot_anti_afk_load_selected()
        self._bot_load_walk_preset()
        if all_selected:
            self.bot_status_var.set('All connected accounts selected. Actions require an explicit click.')

    def _bot_refresh_action_accounts(self):
        picker=getattr(self,'bot_action_account_picker',None)
        if picker is None:return
        items=[]
        for account in self._account_profiles:
            session=self._tcp_sessions.get(account['id'])
            if session is not None and session.authenticated and not session.stop.is_set():
                items.append(account['label']+' ['+account['id'][:6]+']')
        if items:
            items.insert(0,'All connected accounts')
        picker.configure(values=items)
        # Do not silently transfer a user's action to another account.
        if self.bot_action_account_var.get() not in items:
            self.bot_action_account_var.set('')

    def _bot_send_selected_action(self):
        selected=self.bot_action_account_var.get()
        if selected=='All connected accounts':
            accounts=[a for a in self._account_profiles
                if (session:=self._tcp_sessions.get(a['id'])) is not None
                and session.authenticated and not session.stop.is_set()]
            if not accounts:
                self.bot_status_var.set('No connected accounts.')
                return
            started=0
            for account in accounts:
                ident=account['id']
                already=ident in self._bot_action_inflight
                self._bot_send_action(account_override=account)
                if not already and ident in self._bot_action_inflight:
                    started+=1
            self.bot_status_var.set(
                f'Action queued for {started}/{len(accounts)} connected accounts; '
                'existing per-account timing and routing checks apply.')
            return
        account=next((a for a in self._account_profiles
                      if a['label']+' ['+a['id'][:6]+']'==selected),None)
        if account is None:
            self.bot_status_var.set('Choose a connected account under Send action as.')
            return
        self._bot_send_action(account_override=account)

    def _bot_selected_profile(self):
        selected=self.bot_account_var.get()
        return next((a for a in self._account_profiles
                     if a['label']+' ['+a['id'][:6]+']'==selected),None)

    def _bot_gearth_changed(self):
        """Store the pre-start routing choice; never switch active TCP sockets."""
        selected=self._bot_selected_profile()
        if selected is not None:
            ident=selected['id']
            session=self._tcp_sessions.get(ident)
            if (ident in self._tcp_inflight or
                (session is not None and session.authenticated
                 and not session.stop.is_set())):
                self.bot_gearth_var.set(bool(
                    self.config.get('clientless_gearth_intercept',False)))
                self.bot_gearth_status_var.set(
                    'Disconnect the selected profile before changing '
                    'its connection mode. Its existing routing is unchanged.')
                return
        if selected is not None:
            bridge=self._bot_gearth_bridges.pop(selected['id'],None)
            if bridge is not None:bridge.close()
        enabled=bool(self.bot_gearth_var.get())
        self.config['clientless_gearth_intercept']=enabled
        self.save()
        self.bot_gearth_status_var.set(
            'G-Earth ON: selecting an account prepares the local gameplay '
            'relay, launches G-Earth and waits for its Flash packet proxy. '
            'Direct Habbo authentication remains inside Companion.' if enabled else
            'G-Earth OFF: the selected bot will use Direct TCP. '
            'Clientless packets will not route through G-Earth.')

    def _bot_gearth_probe(self):
        """Validate upstream DNS before G-Earth redirects its own hostname."""
        try:
            verify_bridge_alias(DEFAULT_BRIDGE_HOST)
            self.bot_gearth_status_var.set(
                'Bridge hostname resolves locally to 127.0.0.3. '
                'Ready to start G-Earth and its game packet relay; '
                'no Habbo account has been connected by this check.')
        except GearthBridgeError as exc:
            self.bot_gearth_status_var.set(
                'Bridge hostname unavailable: '+str(exc)[:210])

    def _bot_start_gearth_bridge(self,ident):
        """Explicit single-profile G-Earth game-packet route, no AIR required."""
        if self._bot_gearth_bridges:
            self.bot_gearth_status_var.set(
                'A G-Earth bot relay is already active. Disconnect it first.')
            return False
        if self._find_gearth_window():
            self.bot_gearth_status_var.set(
                'Close the existing G-Earth window first. The clientless '
                'mode must launch its OWN Flash proxy on game port 31451; '
                'an extension connected on 9092 is not enough.')
            return False
        try:
            verify_bridge_alias(DEFAULT_BRIDGE_HOST)
            bridge=ClientlessGearthBridge(
                ident,status=lambda msg:self._packet_put(
                    ('bot_gearth_status',ident,msg)),
                port=DEFAULT_BRIDGE_PORT)
            bridge.prepare()
        except (GearthBridgeError,OSError,ValueError) as exc:
            self.bot_gearth_status_var.set(
                'G-Earth local relay setup failed: '+str(exc)[:220])
            return False
        if not self._launch_gearth(
                auto_connect=True,select_if_missing=False,
                target_override=(DEFAULT_BRIDGE_HOST,DEFAULT_BRIDGE_PORT)):
            bridge.close()
            self.bot_gearth_status_var.set(
                'Could not start G-Earth Flash proxy. Check the Packet Tools '
                'G-Earth executable path, permissions, and diagnostic status.')
            return False
        self._bot_gearth_bridges[ident]=bridge
        self.bot_gearth_status_var.set(
            'G-Earth starting for '+ident[:6]+'. '
            'Waiting for the localhost gameplay proxy. '
            'No SSO ticket or DH keys will pass through G-Earth.')
        return True

    def _bot_standalone_changed(self):
        enabled=bool(self.bot_standalone_var.get())
        self.config['clientless_standalone']=enabled
        self.save()
        self.bot_status_var.set(
            'Legacy G-Earth packet-tool auto-start '+
            ('disabled.' if enabled else 'allowed.')+
            ' The explicit G-Earth ON clientless bridge is independent.')

    def _bot_load_walk_preset(self):
        room=clientless_saved_room_value(self.bot_room_var.get())
        stored=self.config.get('clientless_walk_presets',{})
        values=stored.get(room,[]) if isinstance(stored,dict) else []
        account=self._bot_selected_profile()
        account_walk=self.config.get('clientless_account_walk_presets',{})
        override=False
        if account is not None and isinstance(account_walk,dict):
            per_account=account_walk.get(account['id'],{})
            if isinstance(per_account,dict) and room in per_account:
                values=per_account[room]
                override=True
        valid=[]
        try:
            if isinstance(values,list) and values:
                valid=clientless_walk_positions(
                    ','.join(map(str,values[0])),
                    ';'.join(','.join(map(str,p)) for p in values[1:]))
        except (TypeError,ValueError,IndexError):
            pass
        self.bot_walk_primary_var.set(
            ','.join(map(str,valid[0])) if valid else '')
        self.bot_walk_backups_var.set(
            ';'.join(','.join(map(str,p)) for p in valid[1:]))
        self.bot_walk_status_var.set(
            ('Loaded '+str(len(valid))+' '+
             ('account-specific' if override else 'room-wide')+
             ' tile(s) for room '+room+'.'
             if valid else 'No automatic walking positions saved for room '+room+'.'))

    def _bot_save_walk_preset(self):
        room=clientless_saved_room_value(self.bot_room_var.get())
        # Never associate a preset with an invalid/unintended room ID.
        if str(self.bot_room_var.get()).strip()!=room:
            self.bot_walk_status_var.set('Enter a valid numeric Room ID first.')
            self.bot_auto_walk_var.set(False)
            return
        try:
            positions=clientless_walk_positions(
                self.bot_walk_primary_var.get(),self.bot_walk_backups_var.get())
        except (ClientlessBotError,ValueError,TypeError) as exc:
            self.bot_walk_status_var.set('Cannot save: '+str(exc)[:145])
            self.bot_auto_walk_var.set(False)
            return
        if self.bot_auto_walk_var.get() and not positions:
            self.bot_walk_status_var.set(
                'Save a primary X,Y destination before enabling auto-walk.')
            self.bot_auto_walk_var.set(False)
            return
        saved=self.config.get('clientless_walk_presets')
        saved=dict(saved) if isinstance(saved,dict) else {}
        if positions:
            saved[room]=[list(p) for p in positions]
        else:
            saved.pop(room,None)
        self.config['clientless_walk_presets']=saved
        self.config['clientless_auto_walk']=bool(self.bot_auto_walk_var.get())
        self.save()
        self.bot_walk_status_var.set(
            'Room '+room+': '+str(len(positions))+' destination(s) saved. '+
            ('Automatic walking ON.' if self.bot_auto_walk_var.get()
             else 'Automatic walking OFF.'))

    def _bot_save_account_walk_preset(self):
        account=self._bot_selected_profile()
        if account is None:
            self.bot_walk_status_var.set(
                'Select an account in Connected account first.')
            return
        room=clientless_saved_room_value(self.bot_room_var.get())
        if str(self.bot_room_var.get()).strip()!=room:
            self.bot_walk_status_var.set('Enter a valid Room ID first.')
            return
        try:
            positions=clientless_walk_positions(
                self.bot_walk_primary_var.get(),
                self.bot_walk_backups_var.get())
        except (ClientlessBotError,ValueError,TypeError) as exc:
            self.bot_walk_status_var.set('Cannot save: '+str(exc)[:155])
            return
        if not positions:
            self.bot_walk_status_var.set(
                'Enter a primary X,Y. To remove an override use '
                'Clear account override.')
            return
        all_presets=self.config.get('clientless_account_walk_presets',{})
        all_presets=dict(all_presets) if isinstance(all_presets,dict) else {}
        own=all_presets.get(account['id'],{})
        own=dict(own) if isinstance(own,dict) else {}
        own[room]=[list(point) for point in positions]
        all_presets[account['id']]=own
        self.config['clientless_account_walk_presets']=all_presets
        self.save()
        self.bot_walk_status_var.set(
            account['label']+': '+str(len(positions))+
            ' personal walking tile(s) saved for room '+room+'. '+
            ('Automatic walking ON.' if self.bot_auto_walk_var.get()
             else 'Enable Walk automatically after room entry to use them.'))

    def _bot_clear_account_walk_preset(self):
        account=self._bot_selected_profile()
        if account is None:
            self.bot_walk_status_var.set('Select an account first.')
            return
        room=clientless_saved_room_value(self.bot_room_var.get())
        own_all=self.config.get('clientless_account_walk_presets',{})
        own_all=dict(own_all) if isinstance(own_all,dict) else {}
        own=own_all.get(account['id'],{})
        own=dict(own) if isinstance(own,dict) else {}
        own.pop(room,None)
        if own:
            own_all[account['id']]=own
        else:
            own_all.pop(account['id'],None)
        self.config['clientless_account_walk_presets']=own_all
        self.save()
        self._bot_load_walk_preset()

    def _bot_arm_walk(self,ident,generation,session,room):
        """Arm only a saved, user-enabled route for the requested room."""
        self._bot_walk_plans.pop(ident,None)
        self._bot_user_roster.pop(ident,None)
        self._bot_anti_afk_rooms.pop(ident,None)
        self._bot_anti_afk_positions.pop(ident,None)
        if not self.bot_auto_walk_var.get():
            return
        stored=self.config.get('clientless_walk_presets',{})
        raw=stored.get(str(room)) if isinstance(stored,dict) else None
        account_presets=self.config.get('clientless_account_walk_presets',{})
        profile_presets=(account_presets.get(ident,{})
                         if isinstance(account_presets,dict) else {})
        if isinstance(profile_presets,dict) and str(room) in profile_presets:
            raw=profile_presets[str(room)]
        if not isinstance(raw,list) or not raw:
            self.bot_walk_status_var.set(
                'Room '+str(room)+': no saved destinations; no auto-walk.')
            return
        try:
            positions=clientless_walk_positions(
                ','.join(map(str,raw[0])),
                ';'.join(','.join(map(str,p)) for p in raw[1:]))
            # Fail closed for an unknown release or invalid walk header.
            encode_clientless_action(self._bot_headers,session.release,'Walk',
                                     x=positions[0][0],y=positions[0][1])
        except (ClientlessBotError,ValueError,TypeError,IndexError) as exc:
            self.bot_walk_status_var.set('Cannot arm auto-walk: '+str(exc)[:155])
            return
        self._bot_walk_plans[ident]={
            'generation':generation,'room':room,'points':positions,
            'phase':'waiting_room','deadline':time.monotonic()+18,
            'attempt':-1,'room_index':None,'position':None,
            'requested':None,'movement_seen':False,
        }
        self.bot_walk_status_var.set(
            'Room '+str(room)+': waiting for server room-entry confirmation.')
        self.root.after(800,lambda uid=ident,gen=generation:
                        self._bot_walk_tick(uid,gen))

    def _bot_walk_maybe_start(self,ident,generation):
        plan=self._bot_walk_plans.get(ident)
        if not plan or plan['generation']!=generation:
            return
        if plan['phase']!='waiting_avatar':
            return
        uid=self._bot_self_ids.get(ident)
        roster=self._bot_user_roster.get(ident,{})
        unit=roster.get(uid)
        if unit is None:
            return
        room_index,x,y=unit
        plan['room_index']=room_index
        plan['position']=(x,y)
        self._bot_walk_next(ident,generation,'Avatar identified')

    def _bot_receive_walk_observation(self,ident,generation,observation):
        kind,value=observation
        if kind=='ready':
            follow=getattr(self,'_bot_follow_run',None)
            if follow and ident in (follow['id'],follow['peer']):
                self._bot_follow_stop('Follow stopped: room entry changed.')
            # A new room invalidates the previous avatar's room index and tile.
            self._bot_anti_afk_rooms[ident]=value
            self._bot_anti_afk_positions.pop(ident,None)
            self._bot_user_roster.pop(ident,None)
            self._bot_anti_afk_last[ident]=time.monotonic()
        elif kind=='identity':
            self._bot_self_ids[ident]=value
        elif kind=='users':
            self._bot_user_roster[ident]=value
        if kind in ('identity','users'):
            uid=self._bot_self_ids.get(ident)
            unit=self._bot_user_roster.get(ident,{}).get(uid)
            if unit is not None and ident in self._bot_anti_afk_rooms:
                self._bot_anti_afk_positions[ident]=unit
        if kind=='status':
            previous=self._bot_anti_afk_positions.get(ident)
            if previous is not None:
                for index,x,y,_movement in value:
                    if index==previous[0]:
                        self._bot_anti_afk_positions[ident]=(index,x,y)
                        break
        plan=self._bot_walk_plans.get(ident)
        if plan is None or plan['generation']!=generation:
            return
        if kind=='ready' and value!=plan['room']:
            self.bot_walk_status_var.set(
                'Auto-walk stopped: server entered a different room.')
            self._bot_walk_plans.pop(ident,None)
            return
        if kind=='ready' and value==plan['room']:
            plan['phase']='waiting_avatar'
            plan['deadline']=time.monotonic()+15
            self.bot_walk_status_var.set(
                'Room entry confirmed; identifying your avatar before walking.')
        if kind in ('ready','identity','users'):
            self._bot_walk_maybe_start(ident,generation)
            return
        if kind=='status' and plan['room_index'] is not None:
            for index,x,y,movement in value:
                if index!=plan['room_index']:
                    continue
                plan['position']=(x,y)
                if plan['phase']=='walking' and plan['requested']==(x,y):
                    self.bot_walk_status_var.set(
                        'Arrived at '+str(x)+','+str(y)+' (server position confirmed).')
                    self._bot_walk_plans.pop(ident,None)
                    return
                if plan['phase']=='walking' and movement==plan['requested']:
                    plan['movement_seen']=True
                break

    def _bot_walk_next(self,ident,generation,reason):
        plan=self._bot_walk_plans.get(ident)
        if not plan or plan['generation']!=generation:
            return
        attempt=plan['attempt']+1
        if attempt>=len(plan['points']):
            self.bot_walk_status_var.set(
                'Stopped: no saved destination was confirmed reached. '
                'Check that the room is loaded and the tiles are accessible.')
            self._bot_walk_plans.pop(ident,None)
            return
        target=plan['points'][attempt]
        if plan['position']==target:
            self.bot_walk_status_var.set(
                'Already at '+str(target[0])+','+str(target[1])+
                ' (initial room position confirmed).')
            self._bot_walk_plans.pop(ident,None)
            return
        plan['attempt']=attempt
        plan['requested']=target
        plan['movement_seen']=False
        plan['phase']='queued'
        plan['deadline']=time.monotonic()+5
        self.bot_walk_status_var.set(
            ('Primary' if attempt==0 else 'Backup '+str(attempt))+
            ' tile '+str(target[0])+','+str(target[1])+
            ' queued ('+reason+').')
        self._bot_walk_send(ident,generation)

    def _bot_walk_send(self,ident,generation):
        plan=self._bot_walk_plans.get(ident)
        if not plan or plan['generation']!=generation or plan['phase']!='queued':
            return
        session=self._tcp_sessions.get(ident)
        if (not session or not session.authenticated or session.stop.is_set()
            or self._tcp_generation.get(ident,0)!=generation):
            self.bot_walk_status_var.set('Auto-walk stopped: Direct TCP disconnected.')
            self._bot_walk_plans.pop(ident,None)
            return
        if ident in self._bot_action_inflight:
            return  # _bot_walk_tick retries after the current action finishes.
        x,y=plan['requested']
        try:
            packets=encode_clientless_action(
                self._bot_headers,session.release,'Walk',x=x,y=y)
        except (ClientlessBotError,ValueError,TypeError) as exc:
            self.bot_walk_status_var.set('Auto-walk unavailable: '+str(exc)[:150])
            self._bot_walk_plans.pop(ident,None)
            return
        self._bot_action_inflight.add(ident)
        self._bot_last_action_at[ident]=time.monotonic()
        plan['phase']='walking'
        plan['deadline']=time.monotonic()+14
        self.bot_walk_status_var.set(
            ('Primary' if plan['attempt']==0 else 'Backup '+str(plan['attempt']))+
            ': walking to '+str(x)+','+str(y)+'; waiting for server position.')
        threading.Thread(
            target=self._bot_action_worker,
            args=(ident,generation,session,'Auto Walk',packets),
            daemon=True,name='companion-auto-walk-'+ident).start()

    def _bot_walk_tick(self,ident,generation):
        plan=self._bot_walk_plans.get(ident)
        if not plan or plan['generation']!=generation:
            return
        session=self._tcp_sessions.get(ident)
        if (self._tcp_generation.get(ident,0)!=generation
            or not session or not session.authenticated or session.stop.is_set()):
            self.bot_walk_status_var.set('Auto-walk stopped: connection changed.')
            self._bot_walk_plans.pop(ident,None)
            return
        now=time.monotonic()
        if plan['phase']=='queued':
            if now>plan['deadline']:
                self._bot_walk_next(ident,generation,'Send queue timed out')
            else:
                self._bot_walk_send(ident,generation)
        elif now>=plan['deadline']:
            if plan['phase']=='walking':
                # Timeout means no confirmed arrival; try the next saved tile.
                self._bot_walk_next(ident,generation,
                                    'Destination not confirmed within 14 seconds')
            elif plan['phase']=='waiting_room':
                self.bot_walk_status_var.set(
                    'Auto-walk skipped: the game did not confirm room entry.')
                self._bot_walk_plans.pop(ident,None)
            elif plan['phase']=='waiting_avatar':
                self.bot_walk_status_var.set(
                    'Auto-walk skipped: your avatar could not be identified.')
                self._bot_walk_plans.pop(ident,None)
        if ident in self._bot_walk_plans:
            self.root.after(800,lambda uid=ident,gen=generation:
                            self._bot_walk_tick(uid,gen))

    def _bot_follow_observe(self,ident,generation,kind,value):
        if kind=='ready':
            self._bot_follow_room_bots[ident]=dict(generation=generation,room=value,units={})
            return
        cache=self._bot_follow_room_bots.get(ident)
        if not cache or cache['generation']!=generation:return
        units=cache['units']
        if kind=='bots':
            units.update(value)
            if len(units)>200:units.clear()
        elif kind=='status':
            for idx,x,y,_ in value:
                if idx in units:
                    name,_,_,uid=units[idx]
                    units[idx]=(name,x,y,uid)
        elif kind=='remove':
            units.pop(value,None)
        elif kind=='players':
            for unit in value.values():
                units.pop(unit[0],None)

    def _bot_follow_wake(self,ident):
        """Re-evaluate relevant follows after room observations or local sends."""
        run=getattr(self,'_bot_follow_run',None)
        if run and ident in (run['id'],run['peer']):
            self._bot_follow_tick(run)
        group=getattr(self,'_bot_follow_group_run',None)
        if group and (ident in group['members'] or ident==group['key'][3]):
            self._bot_follow_group_tick(group)

    def _bot_follow_defer(self,run,seconds,group=False):
        """Coalesce pending changes until the existing movement guard permits a send."""
        if run.get('deferred'):return
        run['deferred']=True
        def wake():
            run['deferred']=False
            if group:
                self._bot_follow_group_tick(run)
            else:
                self._bot_follow_tick(run)
        self.root.after(max(1,int(seconds*1000)+1),wake)

    def _bot_follow_stop(self,message='Follow stopped.'):
        self._bot_follow_run=None
        self._bot_follow_group_run=None
        var=getattr(self,'bot_follow_all_var',None)
        if var is not None:var.set(False)
        self.bot_follow_status_var.set(message)

    def _bot_follow_start(self):
        if getattr(self,'_bot_follow_group_run',None) is not None:
            self.bot_follow_status_var.set('All-account follow is already enabled.')
            return
        if self._bot_follow_run is not None:
            self.bot_follow_status_var.set('Stop the current follow session before starting another.')
            return
        all_accounts=getattr(self,'bot_follow_all_var',None)
        header=getattr(self,'bot_account_var',None)
        header_all=header is not None and header.get()=='All connected accounts'
        if all_accounts is not None and (header_all or all_accounts.get()):
            all_accounts.set(True)
            self._bot_follow_group_start()
            return
        follower=self._bot_selected_profile()
        username=self.bot_follow_target_var.get().strip()
        try:
            if follower is None or not username:
                raise ClientlessBotError('Select a follower and enter the target Habbo username.')
            ident=follower['id']
            state,own,_=self._coffee_context(ident)
            bots=getattr(self,'_bot_follow_room_bots',{}).get(ident,{})
            entries=bots.get('units',{}) if bots.get('generation')==state['generation'] and bots.get('room')==state['room'] else {}
            targets=[(idx,u) for idx,u in entries.items() if u[0].casefold()==username.casefold()]
            matches=[uid for uid,unit in state['players'].items()
                     if unit[1].casefold()==username.casefold() and uid!=own]
            if len(targets)+len(matches)!=1:
                raise ClientlessBotError('Enter an unambiguous room bot or connected avatar username.')
            if targets:
                idx,unit=targets[0]
                if ident not in self._bot_anti_afk_positions:
                    raise ClientlessBotError('Wait for your confirmed avatar position.')
                self._bot_walk_plans.pop(ident,None)
                run=dict(id=ident,peer=None,generation=state['generation'],room=state['room'],
                         bot_index=idx,bot_id=unit[3],last_target=None,last_sent=None,label=unit[0])
                self._bot_follow_run=run
                self.bot_follow_status_var.set('Following room bot '+unit[0]+'.')
                self._bot_follow_tick(run)
                return
            target=matches[0]
            peers=[a['id'] for a in self._account_profiles if a['id']!=ident
                   and self._coffee_session(a['id']) is not None
                   and self._bot_self_ids.get(a['id'])==target]
            if len(peers)!=1:
                raise ClientlessBotError('The target must be another connected account you control.')
            peer=peers[0]
            other,peer_uid,_=self._coffee_context(peer)
            if peer_uid!=target:
                raise ClientlessBotError('Target identity changed; select the username again.')
            if state['room']!=other['room'] or target not in state['players'] or own not in other['players']:
                raise ClientlessBotError('Both accounts must be visible in the same room.')
            if ident not in self._bot_anti_afk_positions or peer not in self._bot_anti_afk_positions:
                raise ClientlessBotError('Wait for confirmed avatar positions.')
            self._bot_walk_plans.pop(ident,None)
            run=dict(id=ident,peer=peer,generation=state['generation'],
                     peer_generation=other['generation'],room=state['room'],
                     last_target=None,last_sent=None,label=state['players'][target][1])
            self._bot_follow_run=run
            self.bot_follow_status_var.set('Following '+run['label']+' in this room.')
            self._bot_follow_tick(run)
        except (ValueError,TypeError,RuntimeError,OSError) as exc:
            self._bot_follow_stop(str(exc)[:160])

    def _bot_follow_tick(self,run):
        if self._bot_follow_run is not run:return
        ident,peer=run['id'],run['peer']
        try:
            state,own,index=self._coffee_context(ident)
            if state['generation']!=run['generation'] or state['room']!=run['room'] or self._bot_anti_afk_rooms.get(ident)!=run['room']:
                raise ClientlessBotError('Follow stopped: account or room changed.')
            pos=self._bot_anti_afk_positions.get(ident)
            if peer is None:
                bots=self._bot_follow_room_bots.get(ident,{})
                peer_index=run['bot_index']
                unit=bots.get('units',{}).get(peer_index)
                if (bots.get('generation')!=run['generation'] or bots.get('room')!=run['room']
                    or unit is None or unit[3]!=run['bot_id'] or unit[0]!=run['label']):
                    raise ClientlessBotError('Follow stopped: room bot left or changed.')
                lead=(peer_index,unit[1],unit[2])
            else:
                other,target,peer_index=self._coffee_context(peer)
                if (other['generation']!=run['peer_generation'] or other['room']!=run['room']
                    or target not in state['players'] or own not in other['players']
                    or self._bot_anti_afk_rooms.get(peer)!=run['room']):
                    raise ClientlessBotError('Follow stopped: account or room changed.')
                lead=self._bot_anti_afk_positions.get(peer)
            if pos is None or lead is None or pos[0]!=index or lead[0]!=peer_index:
                raise ClientlessBotError('Follow stopped: avatar position unavailable.')
            x,y=pos[1:]
            tx,ty=lead[1:]
            dest=(tx,ty)
            if not (0<=tx<=1023 and 0<=ty<=1023):
                raise ClientlessBotError('Target coordinates are out of range.')
            remaining=2-(time.monotonic()-self._bot_last_action_at.get(ident,0))
            if (x,y)==dest:
                run['last_sent']=dest
                self.bot_follow_status_var.set(f'Following {run["label"]} — at X={tx}, Y={ty}.')
            elif dest!=run['last_sent'] and ident not in self._bot_action_inflight and remaining<=0:
                session=self._coffee_session(ident)
                if session is None:raise ClientlessBotError('Follower disconnected.')
                packets=encode_clientless_action(self._bot_headers,session.release,'Walk',x=tx,y=ty)
                self._bot_action_inflight.add(ident)
                self._bot_last_action_at[ident]=time.monotonic()
                try:
                    threading.Thread(target=self._bot_action_worker,
                        args=(ident,run['generation'],session,'Follow Walk',packets),
                        daemon=True).start()
                except (RuntimeError,OSError):
                    self._bot_action_inflight.discard(ident)
                    raise
                run['last_sent']=dest
                self.bot_follow_status_var.set(f'Following {run["label"]} — walking to X={tx}, Y={ty}.')
            elif dest!=run['last_sent'] and ident not in self._bot_action_inflight:
                self._bot_follow_defer(run,remaining)
            run['last_target']=dest
        except (ValueError,TypeError,RuntimeError,OSError) as exc:
            self._bot_follow_stop(str(exc)[:160])

    def _bot_follow_group_resolve(self,ident,username):
        """Resolve a server-classified bot or a locally connected peer."""
        state,own,index=self._coffee_context(ident)
        room,generation=state['room'],state['generation']
        pos=self._bot_anti_afk_positions.get(ident)
        if (pos is None or pos[0]!=index or
                self._bot_anti_afk_rooms.get(ident)!=room):
            raise ClientlessBotError('Wait for a confirmed avatar position.')
        bots=self._bot_follow_room_bots.get(ident,{})
        entries=bots.get('units',{}) if (bots.get('generation')==generation
            and bots.get('room')==room) else {}
        matches=[unit for unit in entries.values() if unit[0].casefold()==username]
        players=[uid for uid,unit in state['players'].items()
                 if unit[1].casefold()==username and uid!=own]
        if len(matches)+len(players)!=1:
            raise ClientlessBotError('Target is not unambiguously visible.')
        if matches:
            unit=matches[0]
            return (room,'bot',unit[3],None),generation,None,pos[1:],unit[1:3]
        target=players[0]
        peers=[a['id'] for a in self._account_profiles if a['id']!=ident
               and self._coffee_session(a['id']) is not None
               and self._bot_self_ids.get(a['id'])==target]
        if len(peers)!=1:
            raise ClientlessBotError('Target must be a connected account or room bot.')
        peer=peers[0]
        other,peer_uid,peer_index=self._coffee_context(peer)
        lead=self._bot_anti_afk_positions.get(peer)
        if (peer_uid!=target or other['room']!=room or own not in other['players']
                or self._bot_anti_afk_rooms.get(peer)!=room or lead is None
                or lead[0]!=peer_index):
            raise ClientlessBotError('Target position is not confirmed in this room.')
        return (room,'peer',target,peer),generation,other['generation'],pos[1:],lead[1:]

    def _bot_follow_group_toggle(self):
        """Select follower scope without resolving a target or sending movement."""
        if getattr(self,'_bot_follow_run',None) or getattr(self,'_bot_follow_group_run',None):
            selected=bool(self.bot_follow_all_var.get())
            self._bot_follow_stop('Follow stopped: follower selection changed.')
            self.bot_follow_all_var.set(selected)
        self.bot_follow_status_var.set(
            'All connected accounts selected. Click Start following.'
            if self.bot_follow_all_var.get() else
            'Single account selected. Choose a follower and click Start following.')

    def _bot_follow_group_start(self):
        username=self.bot_follow_target_var.get().strip()
        if not username:
            self.bot_follow_status_var.set('Enter a target username before starting follow.')
            return
        members={}
        key=None
        selected=self._bot_selected_profile()
        profiles=sorted(self._account_profiles,key=lambda a: a['id']!=(selected or {}).get('id'))
        for account in profiles:
            ident=account['id']
            if self._coffee_session(ident) is None:continue
            try:
                candidate,generation,peer_generation,_,_=self._bot_follow_group_resolve(ident,username.casefold())
            except (ValueError,TypeError,RuntimeError,OSError):
                continue
            if key is None:key=candidate
            if candidate!=key:continue
            members[ident]=(generation,peer_generation)
        if not members:
            self.bot_follow_status_var.set(
                'No eligible followers: check direct TCP connections, same room, target identity and avatar positions.')
            return
        self._bot_follow_run=None
        for ident in members:self._bot_walk_plans.pop(ident,None)
        run=dict(key=key,members=members,username=username.casefold(),label=username)
        self._bot_follow_group_run=run
        self._bot_follow_group_tick(run)

    def _bot_follow_group_tick(self,run):
        if getattr(self,'_bot_follow_group_run',None) is not run:return
        if not self.bot_follow_all_var.get():
            self._bot_follow_stop()
            return
        sent=0
        latest_dest=None
        last_sent=run.setdefault('last_sent',{})
        pending=[]
        for ident,versions in tuple(run['members'].items()):
            try:
                key,generation,peer_generation,pos,dest=self._bot_follow_group_resolve(ident,run['username'])
                if key!=run['key'] or (generation,peer_generation)!=versions:
                    raise ClientlessBotError('Room or account changed.')
                if not all(0<=coord<=1023 for coord in dest):
                    raise ClientlessBotError('Target coordinates are out of range.')
                latest_dest=dest
                if pos==dest:
                    last_sent[ident]=dest
                    continue
                if last_sent.get(ident)==dest or ident in self._bot_action_inflight:
                    continue
                remaining=0.4-(time.monotonic()-self._bot_last_action_at.get(ident,0))
                if remaining>0:
                    pending.append(remaining)
                    continue
                session=self._coffee_session(ident)
                if session is None:raise ClientlessBotError('Account disconnected.')
                packets=encode_clientless_action(self._bot_headers,session.release,'Walk',x=dest[0],y=dest[1])
                self._bot_action_inflight.add(ident)
                self._bot_last_action_at[ident]=time.monotonic()
                try:
                    threading.Thread(target=self._bot_action_worker,
                        args=(ident,generation,session,'Group Follow Walk',packets),daemon=True).start()
                except (RuntimeError,OSError):
                    self._bot_action_inflight.discard(ident)
                    raise
                last_sent[ident]=dest
                sent+=1
            except (ValueError,TypeError,RuntimeError,OSError):
                run['members'].pop(ident,None)
                last_sent.pop(ident,None)
        if not run['members']:
            self._bot_follow_stop('All-account follow stopped: target or followers unavailable.')
            return
        coordinates=(f' — X={latest_dest[0]}, Y={latest_dest[1]}' if latest_dest is not None else '')
        self.bot_follow_status_var.set('Following '+run['label']+coordinates+' — '+str(len(run['members']))+
            ' connected follower(s); '+str(sent)+' new movement request(s).')
        if pending:
            self._bot_follow_defer(run,min(pending),group=True)

    def _bot_multi_refresh(self):
        """Keep multi-select rows in sync without losing highlighted profiles."""
        tree=getattr(self,'bot_multi_tree',None)
        if tree is None:
            return
        try:
            if not tree.winfo_exists():
                return
            highlighted=set(tree.selection())
            for key in tree.get_children(''):
                tree.delete(key)
            for account in self._account_profiles:
                ident=account['id']
                session=self._tcp_sessions.get(ident)
                if (session is not None and session.authenticated
                    and not session.stop.is_set()):
                    connection=('Connected · G-Earth' if ident in
                                self._bot_gearth_bridges else 'Connected · Direct TCP')
                elif ident in self._tcp_inflight:
                    connection='Connecting…'
                else:
                    state=str(self._tcp_states.get(ident,'Disconnected'))
                    connection=state[:58]
                room=self._bot_run_room_targets.get(ident,'—')
                tree.insert('', 'end',iid=ident,text=account['label'],
                            values=(connection,
                                'G-Earth' if ident in self._bot_gearth_bridges else
                                'Direct TCP' if ident in self._tcp_inflight or
                                (session is not None and session.authenticated and not session.stop.is_set()) else
                                {'clientless':'Direct TCP (saved)',
                                 'clientless_gearth':'G-Earth (saved)',
                                 'air':'HabboAIR (saved)',
                                 'gearth':'AIR + G-Earth (saved)'}.get(account.get('launch_mode'),'Not set'),
                                room))
            keep=tuple(a['id'] for a in self._account_profiles
                       if a['id'] in highlighted)
            if keep:
                tree.selection_set(keep)
        except (tk.TclError,ValueError):
            pass

    def _bot_multi_tick(self,generation):
        if generation!=self._bot_multi_ui_generation:
            return
        tree=getattr(self,'bot_multi_tree',None)
        try:
            if tree is None or not tree.winfo_exists():
                return
            self._bot_multi_refresh()
            self.root.after(2500,lambda generation=generation:
                            self._bot_multi_tick(generation))
        except (tk.TclError,RuntimeError):
            pass

    def _bot_multi_selected(self):
        tree=getattr(self,'account_table',None)
        if tree is None:
            tree=getattr(self,'bot_multi_tree',None)
        if tree is None:
            return ()
        try:
            selected=set(tree.selection())
        except tk.TclError:
            return ()
        return tuple(a for a in self._account_profiles
                     if a['id'] in selected)

    def _bot_multi_select_all(self):
        tree=getattr(self,'account_table',None)
        if tree is None:
            self._bot_multi_refresh()
            tree=getattr(self,'bot_multi_tree',None)
        if tree is None:
            return
        tree.selection_set(tuple(a['id'] for a in self._account_profiles))
        self.bot_multi_status_var.set(
            str(len(self._account_profiles))+' profiles highlighted. '
            'Click Launch highlighted to connect; nothing starts automatically.')

    def _bot_multi_run_selected(self):
        """Explicit user action; one independently authenticated socket per id."""
        chosen=self._bot_multi_selected()
        if not chosen:
            self.bot_multi_status_var.set(
                'Highlight one or more saved profiles first (Ctrl/Shift).')
            return
        try:
            room=int(str(self.bot_room_var.get()).strip())
            if not 1<=room<=2147483647:
                raise ValueError()
        except (TypeError,ValueError):
            self.bot_multi_status_var.set(
                'Enter a valid numeric Room ID (1–2147483647) before launching.')
            return
        # This explicit legacy shortcut never overrides an incompatible saved mode.
        if any(a.get('launch_mode','clientless')!='clientless' for a in chosen):
            self.bot_multi_status_var.set(
                'Run highlighted is Direct TCP only. Deselect profiles saved with other launch modes, or change their mode in Accounts.')
            return
        self._bot_multi_start_generation+=1
        generation=self._bot_multi_start_generation
        count=len(chosen)
        self.bot_multi_status_var.set(
            'Starting '+str(count)+' saved profile(s) for room '+str(room)+
            ' using Direct TCP for newly connected accounts. Existing '
            'authenticated profiles (including G-Earth) stay unchanged.')
        for i,account in enumerate(chosen):
            # Stagger the independent browser login workers to avoid opening
            # many isolated Chromium sessions in the same millisecond.
            self.root.after(
                1200*i,lambda uid=account['id'],gen=generation,target=room:
                self._bot_multi_run_one(uid,gen,target))

    def _bot_multi_run_one(self,ident,generation,room):
        if generation!=self._bot_multi_start_generation:
            return  # stop highlighted invalidates queued starts.
        account=next((a for a in self._account_profiles
                      if a['id']==ident),None)
        if account is None:
            return
        session=self._tcp_sessions.get(ident)
        if (ident in self._tcp_inflight or
            (session is not None and session.authenticated
             and not session.stop.is_set())):
            # Existing sessions keep their room, auto-walk and AFK state.
            self._bot_multi_refresh()
            return
        if account.get('launch_mode','clientless')!='clientless':
            self.bot_multi_status_var.set('A queued profile changed mode; launch it from Accounts.')
            return
        self._bot_run_account(account,room_override=room,force_direct=True)
        self._bot_multi_refresh()

    def _bot_multi_disconnect_selected(self):
        chosen=self._bot_multi_selected()
        if not chosen:
            self.bot_multi_status_var.set(
                'Highlight one or more profiles to disconnect.')
            return
        # Stop any queued starts first, then only disconnect highlighted IDs.
        self._bot_multi_start_generation+=1
        for account in chosen:
            self._tcp_disconnect_one(account['id'])
        self._tcp_render()
        self._bot_multi_refresh()
        self.bot_multi_status_var.set(
            'Disconnected '+str(len(chosen))+' selected profile(s); '
            'other accounts remain running.')

    def _bot_run_from_accounts(self):
        account=self._account_selected()
        if account is not None:
            if self.bot_account_var.get()!='All connected accounts':
                self.bot_account_var.set(
                    account['label']+' ['+account['id'][:6]+']')
            self._bot_run_configured_account(account)
            self.account_status_var.set(self.bot_status_var.get())

    def _bot_run_configured_account(self,account):
        """Use the selected profile's saved mode; never change a live route."""
        mode=account.get('launch_mode','clientless')
        if mode not in ('clientless','clientless_gearth'):
            self.bot_status_var.set('This profile is set to HabboAIR. Choose a clientless mode in Accounts first.')
            return
        ident=account['id']
        session=self._tcp_sessions.get(ident)
        if ident in self._tcp_inflight or (session is not None and
                session.authenticated and not session.stop.is_set()):
            actual_gearth=ident in self._bot_gearth_bridges
            if actual_gearth!=(mode=='clientless_gearth'):
                self.bot_status_var.set('Disconnect this account before changing its live connection mode.')
            else:
                self.bot_status_var.set('This account is already connecting or connected in its selected mode.')
            return
        self._bot_run_account(account,force_direct=(mode=='clientless'),
                              force_gearth=(mode=='clientless_gearth'))

    def _bot_anti_afk_is_enabled(self,ident):
        selected=self.config.get('clientless_anti_afk_profiles',{})
        return (isinstance(selected,dict) and selected.get(ident) is True)

    def _bot_anti_afk_load_selected(self):
        account=self._bot_selected_profile()
        selected=getattr(self,'bot_account_var',None)
        if selected is not None and selected.get()=='All connected accounts':
            self.bot_anti_afk_var.set(False)
            self.bot_anti_afk_status_var.set(
                'Select an individual account to change its anti-AFK settings.')
            return
        enabled=(account is not None and
                 self._bot_anti_afk_is_enabled(account['id']))
        self.bot_anti_afk_var.set(enabled)
        self.bot_anti_afk_status_var.set(
            'Anti-AFK ON for this account: every four minutes, only after '
            'your avatar is identified in a room; no walking or chat.'
            if enabled else 'Anti-AFK OFF for the selected account.')

    def _bot_anti_afk_changed(self):
        account=self._bot_selected_profile()
        if account is None:
            self.bot_anti_afk_var.set(False)
            self.bot_anti_afk_status_var.set(
                'Select a saved account before enabling anti-AFK.')
            return
        ident=account['id']
        enabled=bool(self.bot_anti_afk_var.get())
        raw=self.config.get('clientless_anti_afk_profiles',{})
        saved=dict(raw) if isinstance(raw,dict) else {}
        if enabled:
            saved[ident]=True
            # Always begin with a full interval. Toggling does not immediately
            # inject an action into a connecting or already active account.
            self._bot_anti_afk_last[ident]=time.monotonic()
        else:
            saved.pop(ident,None)
            self._bot_anti_afk_last.pop(ident,None)
        self.config['clientless_anti_afk_profiles']=saved
        self.save()
        self.bot_anti_afk_status_var.set(
            ('Anti-AFK enabled for '+account['label']+
             ': first stationary action after four minutes if in a room.'
             if enabled else 'Anti-AFK disabled for '+account['label']+'.'))

    def _bot_anti_afk_tick(self):
        """One Tk-owned timer; no movement, chat, or guessed room coordinates.

        Does not run without an authenticated profile, verified room entry,
        matching avatar index and known current location. The action uses the
        same whitelisted LookTo packet path as manual Face tile and therefore
        respects optional G-Earth interception, including fail-closed sends.
        """
        now=time.monotonic()
        try:
            for ident,session in tuple(self._tcp_sessions.items()):
                if not self._bot_anti_afk_is_enabled(ident):
                    continue
                if (not session or not session.authenticated or
                    session.stop.is_set() or ident in self._tcp_inflight or
                    ident in self._bot_action_inflight or
                    ident in self._bot_walk_plans or
                    ident not in self._bot_anti_afk_rooms):
                    continue
                last=self._bot_anti_afk_last.get(ident)
                if last is None:
                    self._bot_anti_afk_last[ident]=now
                    continue
                if now-last<240:
                    continue
                position=self._bot_anti_afk_positions.get(ident)
                if position is None:
                    continue  # Never guess the tile or move the avatar.
                _index,x,y=position
                generation=self._tcp_generation.get(ident,0)
                try:
                    packets=encode_clientless_action(
                        self._bot_headers,session.release,'Face tile',x=x,y=y)
                except (ClientlessBotError,ValueError,TypeError) as exc:
                    self._bot_anti_afk_last[ident]=now
                    selected=self._bot_selected_profile()
                    if selected is not None and selected['id']==ident:
                        self.bot_anti_afk_status_var.set(
                            'Anti-AFK unavailable: '+str(exc)[:155])
                    continue
                self._bot_anti_afk_last[ident]=now
                self._bot_last_action_at[ident]=now
                self._bot_action_inflight.add(ident)
                selected=self._bot_selected_profile()
                if selected is not None and selected['id']==ident:
                    self.bot_anti_afk_status_var.set(
                        'Sending stationary anti-AFK LookTo at '+
                        str(x)+','+str(y)+' (server idle reset not verified).')
                threading.Thread(
                    target=self._bot_action_worker,
                    args=(ident,generation,session,'Anti-AFK',packets),
                    daemon=True,name='companion-anti-afk-'+ident).start()
        finally:
            try:
                self.root.after(10000,self._bot_anti_afk_tick)
            except (tk.TclError,RuntimeError):
                pass

    def _bot_run_selected(self):
        self._bot_anti_afk_load_selected()
        self._bot_load_walk_preset()
        account=self._bot_selected_profile()
        if account is None:
            self.bot_status_var.set('Choose a saved Habbo account profile first.')
            return
        self._bot_run_configured_account(account)

    def _bot_run_account(self,account,room_override=None,force_direct=False,
                         force_gearth=False):
        """One click: user-selected profile, optional G-Earth gameplay MITM.

        Login and RC4 remain in Companion. With G-Earth ON, post-auth gameplay
        is routed through a separate loopback-only plaintext Flash proxy.
        """
        ident=account['id']
        if not any(p['id']==ident for p in self._account_profiles):
            self.bot_status_var.set('This account profile has been removed.')
            return
        if force_direct:
            # This is a separate, explicitly labelled multi-account action.
            # The single-account G-Earth ON preference remains untouched.
            self._bot_multi_direct_ids.add(ident)
        elif force_gearth or self.bot_gearth_var.get():
            session=self._tcp_sessions.get(ident)
            if ident in self._tcp_inflight or (
                session is not None and session.authenticated):
                self.bot_status_var.set(
                    'Disconnect this account before starting its G-Earth '
                    'interception session; existing Direct TCP stays unchanged.')
                return
            if not self._bot_start_gearth_bridge(ident):
                self.bot_status_var.set(self.bot_gearth_status_var.get())
                return
            self._bot_multi_direct_ids.discard(ident)
        room=(int(room_override) if room_override is not None else
              int(clientless_saved_room_value(self.bot_room_var.get())))
        if not 1<=room<=2147483647:
            self.bot_status_var.set('Invalid clientless Room ID.')
            return
        if room_override is None:
            self.bot_room_var.set(str(room))
        # Crucial: never cancel another live profile's room join or walking.
        self._bot_pending_room.pop(ident,None)
        self._bot_walk_plans.pop(ident,None)
        self._bot_run_room_targets[ident]=room
        session=self._tcp_sessions.get(ident)
        if session and session.authenticated and not session.stop.is_set():
            self._bot_send_action(account_override=account,
                                  action_override='Join room',
                                  room_override=room)
            return
        if ident not in self._tcp_inflight:
            # Prefer Windows-vault session cookies (no browser necessary).
            self._tcp_connect_one(account)
            if ident not in self._tcp_inflight:
                # Missing cookies: import via the profile's isolated browser.
                self._tcp_connect_one(account,auto_capture=True)
        if ident not in self._tcp_inflight:
            bridge=self._bot_gearth_bridges.pop(ident,None)
            if bridge:bridge.close()
            if force_direct:self._bot_multi_direct_ids.discard(ident)
            self.bot_status_var.set(
                'Could not start game TCP for '+account['label']+': '+
                self._tcp_states.get(ident,'no valid saved session.'))
            return
        self._bot_pending_room[ident]=(
            self._tcp_generation.get(ident,0),room)
        self.bot_status_var.set(
            'Connecting '+account['label']+
            ' in the background; Coffee House / saved room '+str(room)+
            ' will be requested after Habbo confirms authentication.')
        self._tcp_render()

    def _bot_dispatch_pending_room(self,ident,generation):
        pending=self._bot_pending_room.pop(ident,None)
        if not pending or pending[0]!=generation:
            return
        account=next((a for a in self._account_profiles
                      if a['id']==ident),None)
        session=self._tcp_sessions.get(ident)
        if (account is None or not session or not session.authenticated
            or session.stop.is_set()
            or self._tcp_generation.get(ident,0)!=generation):
            return
        self._bot_send_action(account_override=account,
                              action_override='Join room',
                              room_override=pending[1])

    def _bot_disconnect_selected(self):
        account=self._bot_selected_profile()
        if account is None:
            return
        self._bot_pending_room.pop(account['id'],None)
        self._bot_walk_plans.pop(account['id'],None)
        self._tcp_disconnect_one(account['id'])
        self._tcp_render()
        self._bot_multi_refresh()
        self.bot_status_var.set('Disconnected '+account['label']+'.')

    def _bot_join_coffee_house(self):
        """Explicit one-click favorite; never sends automatically on startup."""
        self.bot_action_var.set('Join room')
        self.bot_room_var.set(str(CLIENTLESS_COFFEE_HOUSE_ROOM_ID))
        selected=getattr(self,'bot_account_var',None)
        if selected is not None and selected.get()=='All connected accounts':
            self._bot_send_selected_action()
        else:
            self._bot_send_action()

    def _bot_connect_selected(self):
        account=self._bot_selected_profile()
        if account is not None and account.get('launch_mode')=='clientless_gearth':
            self._bot_run_configured_account(account)
            return
        if account is None:
            self.bot_status_var.set('Add and select an account in Accounts first.')
            return
        self._tcp_connect_one(account)
        self._tcp_render()
        self.bot_status_var.set('Direct TCP connection requested for '+account['label']+
                                '. Check the Direct TCP log for authentication status.')

    def _bot_capture_mapping(self):
        ext=self.packet_extension
        if ext is None or not self.packet_started or not self._habbo_session_connected:
            self.bot_status_var.set(
                'Connect the matching Habbo AIR client through G-Earth first.')
            return
        try:
            from g_python.hmessage import Direction
            mapping=capture_clientless_headers(
                (getattr(ext,'packet_infos',None) or {}).get(Direction.TO_SERVER,{}),
                (getattr(ext,'packet_infos',None) or {}).get(Direction.TO_CLIENT,{}),
                TCP_FALLBACK_RELEASE)
            mapping=validate_clientless_headers(mapping,TCP_FALLBACK_RELEASE)
        except (ImportError,ValueError,TypeError,AttributeError) as exc:
            self.bot_status_var.set('Could not capture named headers: '+str(exc)[:140])
            return
        self._bot_headers=mapping
        # Only integer packet IDs and a public release string are persisted.
        self.config['clientless_header_map']=mapping
        self.save()
        names=', '.join(mapping['outgoing'])
        self.bot_status_var.set(
            f'Captured {len(mapping["outgoing"])} outgoing / '
            f'{len(mapping["incoming"])} incoming named headers for '
            f'{TCP_FALLBACK_RELEASE}. Mappings assume the G-Earth AIR client '
            'matches that build; mismatched releases will be rejected. '
            'Actions available: '+names[:190])

    def _bot_send_action(self,account_override=None,action_override=None,
                         room_override=None):
        # Prevent manual actions from bypassing the selected interception
        # mode even if a socket was established through the separate TCP tab.
        bridge_choice=getattr(self,'bot_gearth_var',None)
        route_account=(account_override if account_override is not None
                       else self._bot_selected_profile())
        if route_account is not None:
            route_id=route_account['id']
            bridge=getattr(self,'_bot_gearth_bridges',{}).get(route_id)
            route_session=self._tcp_sessions.get(route_id)
            actual_bridge=getattr(route_session,'gameplay_bridge',None)
            explicit_direct=route_id in getattr(self,'_bot_multi_direct_ids',set())
            wants_bridge=(route_account.get('launch_mode')=='clientless_gearth'
                          or (not route_account.get('launch_mode') and
                              bridge_choice is not None and bridge_choice.get()))
            if (actual_bridge is not None or bridge is not None or
                    (wants_bridge and not explicit_direct)) and (
                    bridge is None or not bridge.ready):
                self.bot_status_var.set(
                    'G-Earth interception ON, but the local packet relay '
                    'is not ready. Actions cannot bypass it.')
                return
        account=(account_override if account_override is not None
                 else self._bot_selected_profile())
        if account is None:
            self.bot_status_var.set('Select a saved account first.')
            return
        ident=account['id']
        session=self._tcp_sessions.get(ident)
        if session is None or not session.authenticated or session.stop.is_set():
            self.bot_status_var.set('Selected account is not game-authenticated '
                                    'in Direct TCP. Check Direct TCP diagnostics.')
            return
        if ident in self._bot_action_inflight:
            self.bot_status_var.set('Previous action is still being sent.')
            return
        now=time.monotonic()
        if now-self._bot_last_action_at.get(ident,0)<0.4:
            self.bot_status_var.set('Please allow at least 400 ms between actions.')
            return
        action=(action_override if action_override is not None
                else self.bot_action_var.get())
        args={}
        try:
            if action=='Join room':
                args['room']=(int(room_override) if room_override is not None
                              else int(self.bot_room_var.get()))
            elif action in ('Walk','Face tile'):
                args['x']=int(self.bot_x_var.get())
                args['y']=int(self.bot_y_var.get())
            elif action in ('Say','Shout'):
                args['text']=self.bot_message_var.get()
            elif action=='Whisper':
                args['text']=self.bot_message_var.get()
                args['recipient']=self.bot_recipient_var.get()
            elif action in ('Dance','Sign','Posture'):
                args[action.lower()]=int(self.bot_id_var.get())
            packets=encode_clientless_action(
                self._bot_headers,session.release,action,**args)
        except (ValueError,TypeError,AttributeError) as exc:
            self.bot_status_var.set('Action not ready: '+str(exc)[:160])
            return
        follow=getattr(self,'_bot_follow_run',None)
        if follow and ((action in ('Join room','Leave room') and ident in (follow['id'],follow['peer']))
                       or (action=='Walk' and ident==follow['id'])):
            self._bot_follow_stop('Follow stopped by manual action.')
        group=getattr(self,'_bot_follow_group_run',None)
        if group and ((ident in group['members'] and action in ('Walk','Join room','Leave room'))
                      or (ident==group['key'][3] and action in ('Join room','Leave room'))):
            self._bot_follow_stop('All-account follow stopped by manual action.')
        # Remember the last VALID room ID, including manually entered IDs.
        # Coffee House itself remains a fixed, named favorite regardless.
        if action=='Join room':
            self.config['clientless_last_room_id']=str(args['room'])
            self.save()
            self._bot_arm_walk(ident,self._tcp_generation.get(ident,0),
                               session,args['room'])
        elif action=='Leave room':
            self._bot_anti_afk_rooms.pop(ident,None)
        elif action=='Walk' and action_override is None:
            # Explicit manual movement cancels automatic walking.
            self._bot_walk_plans.pop(ident,None)
        self._bot_last_action_at[ident]=now
        self._bot_action_inflight.add(ident)
        self.bot_status_var.set('Sending '+action+' via authenticated Direct TCP '
                                'for '+account['label']+'…')
        generation=self._tcp_generation.get(ident,0)
        threading.Thread(
            target=self._bot_action_worker,
            args=(ident,generation,session,action,packets),
            daemon=True,name='companion-bot-send-'+ident).start()

    def _bot_action_worker(self,ident,generation,session,action,packets):
        try:
            if self._tcp_generation.get(ident,0)!=generation:
                raise HabboTcpError('Connection was replaced before the action.')
            for packet_id,body,_name in packets:
                session.send_game_action(packet_id,body)
            self._packet_put(('bot_action_result',ident,generation,
                              action,len(packets),None))
        except (HabboTcpError,ValueError,OSError,RuntimeError) as exc:
            # Never log packet bytes, session cookies or authentication tickets.
            detail=(str(exc)[:120] if isinstance(exc,(HabboTcpError,ClientlessBotError))
                    else type(exc).__name__)
            self._packet_put(('bot_action_result',ident,generation,
                              action,0,detail))

    def _bot_observe_packet(self,ident,generation,session,packet_id,body):
        """Only expose parsed chat prefixes, not raw packets or credentials."""
        mapping=self._bot_headers
        if not session.authenticated:
            return
        observed=decode_clientless_room_observation(session.release,packet_id,body)
        if observed is not None:
            self._packet_put(('bot_walk_observation',ident,generation,observed))
        bots=decode_clientless_room_bots(session.release,packet_id,body)
        if bots is not None:
            self._packet_put(('bot_room_bots',ident,generation,bots))
        hand=decode_clientless_hand_observation(session.release,packet_id,body)
        if hand is not None:
            self._packet_put(('bot_hand_observation',ident,generation,hand))
        try:
            parsed=decode_clientless_chat(mapping,session.release,packet_id,body)
        except (ClientlessBotError,ValueError,TypeError):
            return
        if parsed is not None:
            self._packet_put(('bot_chat',ident,generation,*parsed))

    def _bot_show_chat(self,ident,kind,index,message):
        if not hasattr(self,'bot_chat_log') or not self.bot_chat_log.winfo_exists():
            return
        room=self._bot_anti_afk_rooms.get(ident)
        if not self._bot_chat_dedup.should_display(
                ident,room,kind,index,message,time.monotonic()):
            return
        widget=self.bot_chat_log
        widget.configure(state='normal')
        clean=''.join(ch for ch in str(message) if ch.isprintable())[:300]
        source=(f'Room {room}' if kind in ('Chat','Shout') and room is not None
                else ident[:6])
        widget.insert('end',f'{time.strftime("%H:%M:%S")} '
                      f'[{source}] {kind} room index {index}: {clean}\n')
        if int(widget.index('end-1c').split('.')[0])>150:
            widget.delete('1.0','40.0')
        widget.see('end')
        widget.configure(state='disabled')

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
        return self._account_selected()

    def _tcp_render(self):
        # Refresh connection status in the single Accounts table, without
        # rebuilding rows or altering the user's selection.
        table=getattr(self,'account_table',None)
        if table is not None:
            for account in self._account_profiles:
                ident=account['id']
                if table.exists(ident):
                    table.set(ident,'launch_state',self._account_display_status(ident))
        self._fuzz_refresh_connected_server()
        self._bot_refresh_accounts()

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
            self.account_status_var.set(self.tcp_status_var.get())
            return
        self.tcp_session_id_var.set('')
        self.tcp_browser_token_var.set('')
        self.tcp_status_var.set('Saved website session removed from Windows vault.')
        self.account_status_var.set(self.tcp_status_var.get())

    def _tcp_proxy_changed(self):
        enabled=bool(self.tcp_proxy_enabled_var.get())
        value=self.tcp_proxy_url_var.get().strip()
        if enabled:
            try:
                validate_socks5_proxy(value)
            except ValueError as exc:
                self.tcp_proxy_enabled_var.set(
                    self.config.get('tcp_proxy_enabled') is True)
                self.tcp_status_var.set(str(exc))
                return
        self.config['tcp_proxy_enabled']=enabled
        self.config['tcp_proxy_url']=value
        self.save()
        self.tcp_status_var.set(
            'SOCKS5 proxy '+('enabled' if enabled else 'disabled')+
            ' for new game TCP connections. Reconnect to apply.')

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
        bridge_choice=getattr(self,'bot_gearth_var',None)
        if bridge_choice is not None and bridge_choice.get():
            self.tcp_status_var.set(
                'G-Earth ON: choose a clientless profile to start the '
                'dedicated gameplay relay before logging in.')
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
        if (account.get('launch_mode')=='clientless_gearth' and
                ident not in getattr(self,'_bot_gearth_bridges',{})):
            self._tcp_states[ident]='Launch Clientless Bot with G-Earth from Accounts'
            return
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
        # A new login must not inherit identity or position observations
        # from a previous socket, even when the saved profile ID is reused.
        getattr(self,'_bot_walk_plans',{}).pop(ident,None)
        getattr(self,'_bot_self_ids',{}).pop(ident,None)
        getattr(self,'_bot_user_roster',{}).pop(ident,None)
        getattr(self,'_bot_anti_afk_rooms',{}).pop(ident,None)
        getattr(self,'_bot_anti_afk_positions',{}).pop(ident,None)
        getattr(self,'_bot_anti_afk_last',{}).pop(ident,None)
        generation=self._tcp_generation.get(ident,0)+1
        self._tcp_generation[ident]=generation
        self._tcp_inflight.add(ident)
        self._tcp_states[ident]=(
            'Automatically importing website session' if auto_capture
            else 'Starting direct TCP')
        threading.Thread(
            target=self._tcp_connect_worker,
            args=(dict(account),ticket,cookies,generation,auto_capture),
            kwargs=({'proxy_url':self.config.get('tcp_proxy_url','')}
                    if getattr(self,'config',{}).get('tcp_proxy_enabled') is True else {}),
            daemon=True,name='companion-live-tcp-'+ident).start()

    def _tcp_connect_worker(self,account,ticket,cookies,generation,
                            auto_capture=False, proxy_url=None):
        ident=account['id']
        session=None

        def log_packet(packet_id,size):
            if self._tcp_log_packet_ids:
                self._packet_put(('tcp_packet',ident,generation,packet_id,size))

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
            bridge=self._bot_gearth_bridges.get(ident)
            if bridge is not None:
                self._packet_put(('tcp_state',ident,generation,
                                  'Waiting for G-Earth local gameplay proxy '
                                  'before authenticating Habbo'))
                bridge.connect(TCP_FALLBACK_RELEASE,timeout=35)
                if self._tcp_generation.get(ident,0)!=generation:
                    raise GearthBridgeError('Profile changed during G-Earth setup')
            session=HabboTcpSession(
                ident,
                status=lambda msg:self._packet_put(
                    ('tcp_state',ident,generation,msg)),
                packet=log_packet,
                content=lambda packet_id,body:self._bot_observe_packet(
                    ident,generation,session,packet_id,body),
                gameplay_bridge=bridge)
            if bridge is not None:
                bridge.attach(session)
            if proxy_url is None:
                session.connect(actual)
            else:
                session.connect(actual,proxy_url=proxy_url)
            self._packet_put(('tcp_connected',ident,generation,session))
        except (OSError,ValueError,RuntimeError,HabboTcpError,TimeoutError) as exc:
            if session:
                session.close()
            bridge=self._bot_gearth_bridges.get(ident)
            if bridge is not None:
                bridge.close()
            # Never put HTTP responses, cookies, SSO tokens or keys in diagnostics.
            detail=(str(exc)[:180] if isinstance(
                exc,(HabboTcpError,ValueError,GearthBridgeError))
                else type(exc).__name__)
            self._packet_put(('tcp_failed',ident,generation,detail))

    def _tcp_connect_selected(self):
        account=self._tcp_selected()
        if account:
            self._tcp_connect_one(account,use_form=True)
            self._tcp_render()

    def _tcp_connect_all(self):
        for account in self._account_profiles:
            self._tcp_connect_one(account)
        self._tcp_render()
        self.tcp_status_var.set('Requested independent TCP login for each '
                                'profile with a saved session.')

    def _tcp_disconnect_one(self,ident):
        self._bot_pending_room.pop(ident,None)
        self._bot_run_room_targets.pop(ident,None)
        self._bot_multi_direct_ids.discard(ident)
        getattr(self,'_coffee_room_state',{}).pop(ident,None)
        bridge=self._bot_gearth_bridges.pop(ident,None)
        if bridge is not None:bridge.close()
        self._bot_walk_plans.pop(ident,None)
        self._bot_self_ids.pop(ident,None)
        self._bot_user_roster.pop(ident,None)
        self._bot_anti_afk_rooms.pop(ident,None)
        self._bot_anti_afk_positions.pop(ident,None)
        self._bot_anti_afk_last.pop(ident,None)
        self._tcp_generation[ident]=self._tcp_generation.get(ident,0)+1
        self._tcp_inflight.discard(ident)
        session=self._tcp_sessions.pop(ident,None)
        if session:
            session.close()
        self._tcp_states[ident]='Disconnected'
        self._bot_follow_wake(ident)

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

    def _make_accounts_panel(self,parent):
        """Build the profile list and account settings."""
        p=COMPANION_UI
        f=ttk.Frame(parent,style='Panel.TFrame',padding=(10,8))
        f.pack(fill='both',expand=True)
        self._make_dashboard_panel(f)
        columns=ttk.Frame(f,style='Panel.TFrame')
        columns.pack(fill='both',expand=True)

        # LEFT — profile selection and lifecycle.
        left=ttk.Frame(columns,style='Card.TFrame',padding=9,width=325)
        left.pack(side='left',fill='y',padx=(0,8))
        left.pack_propagate(False)
        tk.Label(left,text='SAVED PROFILES',
                 font=('Segoe UI Semibold',9),
                 fg=p['accent'],bg=p['surface']).pack(
                     anchor='w',pady=(2,9))
        self.account_table=ttk.Treeview(
            left,columns=('name','port','launch_state'),
            show='headings',height=10,selectmode='extended')
        for key,heading,width in (
            ('name','Account',117),
            ('port','Port',48),
            ('launch_state','Status',120)):
            self.account_table.heading(key,text=heading)
            self.account_table.column(key,width=width,stretch=False)
        self.account_table.pack(fill='x',pady=(0,6))
        self.account_table.bind('<<TreeviewSelect>>',self._account_on_select)
        actions=ttk.Frame(left,style='Card.TFrame')
        actions.pack(fill='x',pady=(0,4))
        ttk.Button(actions,text='Add account',style='Primary.TButton',
                   command=self._account_add).pack(
                       side='left',padx=(0,7))
        ttk.Button(actions,text='Remove entry',style='Danger.TButton',
                   command=self._account_remove).pack(side='left')

        ttk.Button(left,text='Select all',command=self._bot_multi_select_all).pack(anchor='w',pady=(0,5))
        ttk.Button(left,text='Launch highlighted (direct)',
                   command=self._bot_multi_run_selected).pack(anchor='w',pady=(0,5))
        ttk.Button(left,text='Disconnect highlighted',
                   command=self._bot_multi_disconnect_selected).pack(anchor='w',pady=(0,5))
        ttk.Label(left,textvariable=self.bot_multi_status_var,style='Card.TLabel',
                  wraplength=275).pack(anchor='w',fill='x',pady=(0,7))
        ttk.Label(left,text='Ctrl/Shift selects multiple profiles.',style='Card.TLabel').pack(anchor='w')

        # RIGHT — profile details, login, and separate advanced controls.
        details_padding=9
        right=ttk.Frame(columns,style='Card.TFrame',padding=details_padding)
        right.pack(side='left',fill='both',expand=True)
        tk.Label(right,text='Account settings',
                 font=('Segoe UI Semibold',12),
                 fg=p['text'],bg=p['surface']).pack(anchor='w',pady=(0,4))

        def field(parent,label,var,row,column=0,span=1,secret=False):
            ttk.Label(parent,text=label,style='Card.TLabel').grid(
                row=row*2,column=column,columnspan=span,
                sticky='w',padx=(0,12),pady=(3,2))
            entry=ttk.Entry(parent,textvariable=var,
                            show='*' if secret else '')
            entry.grid(row=row*2+1,column=column,columnspan=span,
                       sticky='ew',padx=(0,12),pady=(0,4))
            return entry

        basics=ttk.Frame(right,style='Card.TFrame')
        basics.pack(fill='x')
        basics.columnconfigure(0,weight=2)
        basics.columnconfigure(1,weight=1)
        field(basics,'Account label',self.account_label_var,0)
        field(basics,'G-Earth extension port',self.account_port_var,0,1)
        field(basics,'Login website (HTTPS)',self.account_login_url_var,1,
              span=2)
        ttk.Button(right,text='Save changes',
                   command=self._account_save_selected).pack(anchor='w',pady=(4,8))
        port_actions=ttk.Frame(right,style='Card.TFrame')
        port_actions.pack(fill='x')
        ttk.Button(port_actions,text='Use G-Earth port',
                   command=self._account_use_port).pack(side='left',padx=(0,9))
        ttk.Button(port_actions,text='Check port',
                   command=self._account_check_port).pack(side='left')

        tk.Frame(right,bg=p['border'],height=1).pack(
            fill='x',pady=(7,6))
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
        ttk.Button(secrets_row,text='Save login',
                   command=self._account_save_login).pack(
                       side='left',padx=(0,9))
        ttk.Button(secrets_row,text='Forget login',
                   command=self._account_forget_login).pack(side='left')
        ttk.Button(right,text='Forget saved website session',
                   command=self._tcp_forget_session).pack(anchor='w',pady=(0,5))
        ttk.Button(right,text='Open account login',
                   style='Primary.TButton',
                   command=self._account_open_login).pack(
                       anchor='w',pady=(3,7))
        login_note=tk.Label(right,text='Saved passwords go to Windows Credential Manager. '
                            'Complete CAPTCHA or email verification on Habbo.',
                            font=('Segoe UI',9),bg=p['surface'],fg=p['muted'],
                            wraplength=280,justify='left')
        login_note.pack(anchor='w',pady=(5,0))

        tk.Frame(right,bg=p['border'],height=1).pack(
            fill='x',pady=(7,6))
        tk.Label(right,text='LAUNCH & AUTOMATION',
                 font=('Segoe UI Semibold',9),
                 fg=p['accent'],bg=p['surface']).pack(
                     anchor='w',pady=(0,4))
        autoplay=ttk.Frame(right,style='Card.TFrame')
        autoplay.pack(fill='x',pady=(0,7))
        target=ttk.Frame(right,style='Card.TFrame')
        target.pack(fill='x',before=autoplay,pady=(0,5))
        ttk.Label(target,text='Clientless start room',style='Card.TLabel').pack(side='left',padx=(0,8))
        ttk.Entry(target,textvariable=self.bot_room_var,width=13).pack(side='left')
        self.account_launch_mode_var=tk.StringVar(value='air')
        modes=ttk.Frame(right,style='Card.TFrame')
        modes.pack(fill='x',pady=(0,7),before=autoplay)
        for label,value in (
                ('HabboAIR without G-Earth','air'),
                ('HabboAIR with G-Earth','gearth'),
                ('Clientless Bot without G-Earth','clientless'),
                ('Clientless Bot with G-Earth','clientless_gearth')):
            ttk.Radiobutton(modes,text=label,value=value,
                variable=self.account_launch_mode_var,
                command=self._account_remember_launch_mode).pack(anchor='w')
        ttk.Button(modes,text='Launch selected account',
                   style='Primary.TButton',
                   command=self._account_launch_selected_mode).pack(
                       anchor='w',pady=(7,3))
        ttk.Button(autoplay,text='Auto Play all saved accounts',
                   command=lambda:self._account_auto_play(
                       all_accounts=True)).pack(side='left')
        ttk.Button(right,text='Continue unfinished accounts',
                   command=self._account_resume_pending).pack(
                       anchor='w',pady=(0,5))
        status=tk.Label(right,textvariable=self.account_status_var,
                         bg=p['surface'],fg=p['success'],justify='left',
                         wraplength=280,font=('Segoe UI',9))
        status.pack(anchor='w',fill='x',pady=(2,9))
        launch_note=tk.Label(right,text='Launch mode is saved per profile. Close the G-Earth proxy '
                             'for direct AIR or have it ready for intercepted AIR. '
                             'Companion supports one G-Earth connection at a time.',
                             font=('Segoe UI',9),fg=p['muted'],bg=p['surface'],
                             wraplength=280,justify='left')
        launch_note.pack(anchor='w')

        def wrap_notes(event):
            width=max(1,event.width-2*details_padding)
            for label in (login_note,status,launch_note):
                label.configure(wraplength=width)

        right.bind('<Configure>',wrap_notes)
        self._accounts_render()
        self._account_on_select()

    def _account_display_status(self,ident):
        session=self._tcp_sessions.get(ident)
        if session is not None and session.authenticated and not session.stop.is_set():
            return 'Connected · G-Earth' if ident in self._bot_gearth_bridges else 'Connected · Clientless'
        if ident in self._tcp_inflight:
            return self._tcp_states.get(ident,'Connecting…')
        account=next((a for a in self._account_profiles if a['id']==ident),{})
        if account.get('launch_mode') in ('air','gearth'):
            return self._account_run_states.get(ident,'Not started')
        return self._tcp_states.get(ident,self._account_run_states.get(ident,'Not started'))

    def _accounts_render(self,select_id=None):
        table=self.account_table
        previous=tuple(table.selection()) if select_id is None else (select_id,)
        for row in table.get_children():
            table.delete(row)
        for item in self._account_profiles:
            name=item['label']+(' (active)' if item['id']==self._account_active_id else '')
            table.insert('', 'end',iid=item['id'],
                         values=(name,item['port'],
                                  self._account_display_status(item['id'])))
        keep=tuple(ident for ident in previous if table.exists(ident))
        if not keep and self._account_profiles:
            keep=(self._account_profiles[0]['id'],)
        if keep:
            table.selection_set(keep)
            table.focus(keep[0])

    def _account_selected(self):
        selection=self.account_table.selection()
        if len(selection)!=1:
            self.account_status_var.set('Select exactly one account to edit or launch individually. Use highlighted controls for multiple profiles.')
            return None
        return next((a for a in self._account_profiles if a['id']==selection[0]),None)

    def _account_on_select(self,event=None):
        account=self._account_selected()
        if account is None:return
        if hasattr(self,'account_launch_mode_var'):
            self.account_launch_mode_var.set(account.get('launch_mode','air'))
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
               if saved else 'Enter email and password, then click Save login.'))

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

    def _account_remember_launch_mode(self):
        account=self._account_selected()
        if account is None:return
        mode=self.account_launch_mode_var.get()
        if mode not in ('air','gearth','clientless','clientless_gearth'):return
        account['launch_mode']=mode
        self.config['account_profiles']=self._account_profiles
        self.save()

    def _account_launch_selected_mode(self):
        account=self._account_selected()
        if account is None:return
        if self._account_auto_running:
            self.account_status_var.set('An account launch is already in progress.')
            return
        mode=self.account_launch_mode_var.get()
        self._account_remember_launch_mode()
        if mode in ('clientless','clientless_gearth'):
            self.gearth_auto_arm_var.set(False)
            self.config['gearth_auto_arm']=False
            self.bot_standalone_var.set(True)
            self.config['clientless_standalone']=True
            self.save()
            self._bot_run_from_accounts()
            return
        if mode not in ('air','gearth'):return
        # Do not let a scheduled global startup silently change the chosen route.
        self.gearth_auto_arm_var.set(False)
        self.config['gearth_auto_arm']=False
        if mode=='air':
            self.bot_standalone_var.set(True)
            self.config['clientless_standalone']=True
            self.save()
            if (self.packet_started or self._engine_installing
                or self._gearth_launch_watch_until>time.monotonic()
                or self._find_gearth_window()
                or gearth_network_state()['unsafe']
                or any(self._gearth_extension_port_responds(p)
                       for p in {9092,account['port']})):
                self.account_status_var.set(
                    'Direct AIR launch blocked: close G-Earth and finish its network cleanup, then retry.')
                return
        else:
            port=account['port']
            # Overlay tracking accepts broad Habbo titles (including Brave).
            # Only native AIR windows and actual game-session events block launch.
            native=account_native_client_windows()
            if native is None:
                self.account_status_var.set(
                    'Cannot verify native AIR windows. Retry launch after Windows window inspection succeeds.')
                return
            if native:
                self.account_status_var.set(
                    'A native HabboAIR game window is already open ('+str(len(native))+'). Close that game before launching intercepted AIR.')
                return
            if self._habbo_session_connected:
                self.account_status_var.set(
                    'G-Earth reports an active game connection. Disconnect that game before launching another.')
                return
            if self.packet_started and self._account_attached_port!=port:
                self.account_status_var.set(
                    'Idle packet tools are attached to port '+str(self._account_attached_port)+
                    '; selected profile requires port '+str(port)+'. Use the matching proxy endpoint.')
                return
            # An idle extension on the selected port is safe to reuse.
            self._account_use_port()
            if not self._gearth_extension_port_responds(port):
                if port==9092:
                    self._start_integrated_engine()
                    self.account_status_var.set(
                        'G-Earth starting. When it says Waiting for connection, click Launch selected account again.')
                else:
                    self.account_status_var.set(
                        'Start the configured G-Earth proxy on extension port '+str(port)+' and retry.')
                return
            if not messagebox.askyesno('HabboAIR with G-Earth',
                    'Confirm the selected G-Earth proxy is Waiting for connection. '
                    'An open extension port alone does not prove interception. Launch now?',
                    parent=self.root):
                return
            self.bot_standalone_var.set(False)
            self.config['clientless_standalone']=False
            self.save()
        self._account_auto_play(explicit_launch_mode=mode)

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
                           remaining_only=False,explicit_launch_mode=None):
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
        if (explicit_launch_mode is None and not login_only and not self.packet_started
                and not all_accounts and not remaining_only):
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
            (f'Opening {len(accounts)} browser profile(s) for manual sign-in.' if login_only
             else f'Starting {len(accounts)} native launch(es) via Play in App.')
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

        if not login_only:
            # Keep the official website in the foreground until the native
            # client is confirmed. Do not gate this on headless ticket capture
            # or a separate sign-in-only pass that can miss the Play control.
            attempted_ids=set()
            unresolved=False
            confirmed=0
            failure_notes=[]
            try:
                browser=account_login_browser()
                if browser is None:
                    report('Brave/Chrome/Edge not found; install one first.')
                    queue_unfinished(set())
                    return
                for n,account in enumerate(accounts,1):
                    label=account['label']
                    ident=account['id']
                    spawned=None
                    keep_browser=False
                    debug_port=account_browser_debug_port(ident)
                    stage(account,'Preparing native launch')
                    report(f'{n}/{len(accounts)}: {label}: preparing saved website session...')
                    try:
                        if any(account_browser_debug_port(other['id'])==debug_port
                               for other in self._account_profiles
                               if other['id']!=ident):
                            raise ValueError('Account browser port conflict.')
                        folder=APP_DIR/'account_browser_profiles'/ident
                        try:
                            account_browser_pages(debug_port)
                        except (OSError,ValueError,TimeoutError,UnicodeError,urllib.error.URLError):
                            folder.mkdir(parents=True,exist_ok=True)
                            cmd=account_air_browser_command(browser,folder,account['url'],debug_port)
                            spawned=subprocess.Popen(cmd,cwd=str(browser.parent),
                                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                            for _ in range(28):
                                time.sleep(0.45)
                                try:
                                    account_browser_pages(debug_port)
                                    break
                                except (OSError,ValueError,TimeoutError,UnicodeError,urllib.error.URLError):
                                    continue
                            else:
                                raise RuntimeError('Account browser control unavailable.')
                        account_show_login_browser(debug_port)
                        credentials=account_saved_login_read(ident)
                        native_before=account_native_client_windows()
                        stage(account,'Signing in / Play in App')
                        # One browser automation pass handles both sign-in and
                        # Play in App. A slow page cannot be rejected simply
                        # because the sign-in-only probe did not see a button.
                        launch_details=[]
                        def relay_launch(msg,name=label):
                            safe=str(msg)
                            if safe.startswith(('Playwright Play in App:',
                                'Playwright PLAY:', 'Playwright launch:',
                                'Playwright could not operate',
                                'No recognised Play in App',
                                'Habbo Play in App returned an error',
                                'Website login or verification still required')):
                                launch_details.append(safe[:180])
                            report(f'{name}: {safe}')
                        outcome=account_attempt_auto_play(
                            debug_port,relay_launch,
                            credentials=credentials,login_only=False)
                        if outcome!='launched':
                            note=('Habbo website rejected Play in App' if outcome=='app_error'
                                  else 'Sign-in / verification required' if outcome=='login'
                                  else 'Play in App not confirmed ('+str(outcome)+')')
                            stage(account,note)
                            failure_notes.append(label+': '+note+
                                (' — '+launch_details[-1] if launch_details else ''))
                            # A click failure can leave an unresolved launcher
                            # or external-protocol prompt. Do not launch another.
                            keep_browser=True
                            account_show_login_browser(debug_port)
                            unresolved=outcome in ('stalled','control_error')
                            if outcome=='app_error':
                                report(f'{label}: Habbo displayed its own app-launch error. '
                                       'Close the error, reload the website and test Play in App manually.')
                            break
                        attempted_ids.add(ident)
                        if native_before is not None:
                            self._packet_put(('game_panel_arm',generation,native_before))
                        stage(account,'Checking native game / Classic launcher')
                        appeared=account_wait_for_new_native_window(native_before,2.5)
                        if not appeared:
                            if account_select_classic_launcher(16):
                                stage(account,'Classic selected; waiting for game')
                                appeared=account_wait_for_new_native_window(native_before,8.0)
                            else:
                                appeared=account_wait_for_new_native_window(native_before,0.8)
                        if appeared:
                            confirmed+=1
                            stage(account,'New HabboAir window (account unverified)')
                        else:
                            keep_browser=True
                            account_show_login_browser(debug_port)
                            unresolved=True
                            stage(account,'Needs manual Classic / permission')
                            for future in accounts[n:]:
                                stage(future,'Waiting: previous launcher unresolved')
                            report(f'{label}: finish any Habbo launcher or browser permission prompt.')
                            break
                    except (OSError,ValueError,RuntimeError,TimeoutError) as exc:
                        note='Browser / launch setup failed ('+type(exc).__name__+')'
                        stage(account,note)
                        failure_notes.append(label+': '+note)
                    finally:
                        # Only close our own temporary browser, never a user's
                        # existing window. Leave permission prompts available.
                        if spawned is not None and not keep_browser:
                            try:
                                page=account_habbo_page(debug_port)
                                if page:
                                    account_cdp_call(page['webSocketDebuggerUrl'],
                                                     'Browser.close',timeout=2)
                            except (OSError,ValueError,RuntimeError,TimeoutError):
                                try:spawned.terminate()
                                except OSError:pass
                unfinished=queue_unfinished(attempted_ids,unresolved)
                summary=(f'Native launch requests: {len(attempted_ids)}/{len(accounts)}; '
                         f'{confirmed} new game window(s); {len(unfinished)} unfinished.')
                if failure_notes:
                    summary+=' '+failure_notes[-1]+'.'
                if unresolved:
                    summary+=' Finish the outstanding permission/launcher step.'
                elif unfinished:
                    summary+=' Use Open account login if sign-in needs attention.'
                report(summary)
            except Exception as exc:
                queue_unfinished(attempted_ids,True)
                report('Native AIR launch stopped: '+type(exc).__name__)
            finally:
                self._packet_put(('account_auto_finished',generation))
            return

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
                        account_show_login_browser(port)
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
            report(f'Browser sign-in complete: {len(authenticated)}/{total} '
                   f'ready. {len(failures)} need attention.')
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
                info,source=fetch_current_update_manifest(url,helper)
                version=str(info['version']);package_url=str(info['package_url'])
                checksum=str(info['sha256']).lower()
                if not helper.is_newer(version,self.current_app_version):
                    self.root.after(0,lambda v=version,src=source:self._finish_online_update(
                        f'No newer update. Installed: {self.current_app_version}; feed: {v} ({src}).'))
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
                  wraplength=630).pack(anchor='w',fill='x',pady=(0,6))
        ttk.Label(holder,textvariable=self.packet_connection_status,
                  style='Panel.TLabel',wraplength=630).pack(
                      anchor='w',fill='x',pady=(0,7))
        ttk.Checkbutton(holder,
                        text='Automatically capture packets when Habbo connects',
                        variable=self.packet_auto_capture_var,
                        command=self._save_packet_auto_capture).pack(
                            anchor='w',pady=(0,9))
        opts=ttk.Frame(holder,style='Panel.TFrame')
        self._packet_search_row=opts
        opts.pack(fill='x',pady=(0,7))
        ttk.Label(opts,text='Find packets',style='Panel.TLabel').pack(side='left',padx=(0,6))
        ttk.Entry(opts,textvariable=self.packet_filter_var).pack(
            side='left',fill='x',expand=True,padx=(0,7))
        ttk.Button(opts,text='Pause / Resume',command=self._toggle_capture).pack(side='left')
        region=ttk.Frame(holder,style='Panel.TFrame');region.pack(fill='both',expand=True)
        self.packet_tree=ttk.Treeview(
            region,columns=('time','direction','summary','source'),
            show='headings',height=15)
        for col,head,width in [
                ('time','Time',78),('direction','Direction',95),
                ('summary','Packet (read-only)',325),
                ('source','Source',125)]:
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
        tk.Label(holder,text='Source distinguishes G-Earth traffic from Coffee Pass Loop requests. '
                 'A local send is not proof of server acceptance or a received cup.\n'
                 'The viewer retains the most recent 500 packets in memory.\n'
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


    def _make_outfit_panel(self,parent):
        holder=ttk.Frame(parent,style='Panel.TFrame',padding=16)
        holder.pack(fill='both',expand=True)
        tk.Label(holder,text='OUTFIT CYCLER',font=('Segoe UI Semibold',18),
                 fg=COMPANION_UI['text'],bg=COMPANION_UI['background']).pack(anchor='w')
        ttk.Label(holder,text='Capture your own outfits by saving different looks '
                  'inside Habbo. The cycler sends the same named outfit-change '
                  'action, one at a time. No packet ID is guessed.',
                  style='Panel.TLabel',wraplength=610).pack(anchor='w',pady=(5,13))
        ttk.Label(holder,textvariable=self.packet_connection_status,
                  style='Panel.TLabel',wraplength=610).pack(anchor='w',pady=(0,8))
        self.outfit_listbox=tk.Listbox(holder,height=8,exportselection=False,
                  bg=COMPANION_UI['field'],fg=COMPANION_UI['text'],
                  selectbackground=COMPANION_UI['raised'],
                  selectforeground=COMPANION_UI['text'],
                  relief='flat',font=('Segoe UI',10))
        self.outfit_listbox.pack(fill='x',pady=(0,9))
        bar=ttk.Frame(holder,style='Panel.TFrame')
        bar.pack(fill='x',pady=(0,12))
        ttk.Button(bar,text='Capture next outfit change',
                   command=self._arm_outfit_capture).pack(side='left',padx=(0,8))
        ttk.Button(bar,text='Remove selected',
                   command=self._remove_outfit).pack(side='left')
        speed=ttk.Frame(holder,style='Panel.TFrame')
        speed.pack(fill='x',pady=(0,12))
        ttk.Label(speed,text='Milliseconds per outfit',style='Panel.TLabel').pack(side='left')
        ttk.Entry(speed,textvariable=self.outfit_delay_var,width=9).pack(
            side='left',padx=(9,12))
        ttk.Label(speed,text='0 = fastest; decimals allowed (default 300 ms)',
                  style='Panel.TLabel').pack(side='left')
        buttons=ttk.Frame(holder,style='Panel.TFrame')
        buttons.pack(fill='x',pady=(0,10))
        ttk.Button(buttons,text='Start cycling',style='Primary.TButton',
                   command=self._start_outfit_cycle).pack(side='left',padx=(0,10))
        ttk.Button(buttons,text='STOP',
                   command=self._stop_outfit_cycle).pack(side='left')
        ttk.Label(holder,textvariable=self.outfit_status_var,
                  style='Panel.TLabel',wraplength=610).pack(anchor='w',pady=(0,10))
        ttk.Label(holder,text='Instructions: Connect G-Earth, press Capture, then '
                  'open Looks in Habbo and apply/save a different outfit. '
                  'Repeat for at least two looks. Outfits are saved locally. '
                  'Cycling stops on disconnect or error. Local send acceptance '
                  'does not guarantee the server applied every look.',
                  style='Panel.TLabel',wraplength=610).pack(anchor='w')
        self._render_outfit_presets()

    def _render_outfit_presets(self):
        if not hasattr(self,'outfit_listbox'):
            return
        selected=self.outfit_listbox.curselection()
        keep=selected[0] if selected else None
        self.outfit_listbox.delete(0,'end')
        for index,preset in enumerate(self.outfit_presets):
            self.outfit_listbox.insert(
                'end',f'Outfit {index+1}  ·  {preset["gender"]}  ·  '+
                f'{len(preset["figure"].split("."))} clothing parts')
        if keep is not None and keep<len(self.outfit_presets):
            self.outfit_listbox.selection_set(keep)

    def _arm_outfit_capture(self):
        if self._outfit_running:
            self.outfit_status_var.set('Press STOP before recording more looks.')
            return
        if (not self.packet_started or self.packet_extension is None
            or not self._habbo_session_connected):
            self.outfit_status_var.set('Connect Habbo through G-Earth before capturing.')
            return
        if len(self.outfit_presets)>=8:
            self.outfit_status_var.set('Eight outfits saved. Remove one to capture another.')
            return
        self._outfit_capture_generation+=1
        generation=self._outfit_capture_generation
        self._outfit_capture_pending=True
        self.outfit_status_var.set(
            'Capture armed: change your look and press Save in Habbo within 30 seconds.')
        self.root.after(30000,
                        lambda gen=generation:self._outfit_capture_timeout(gen))

    def _outfit_capture_timeout(self,generation):
        if (generation!=self._outfit_capture_generation
            or not self._outfit_capture_pending):
            return
        self._outfit_capture_pending=False
        self.outfit_status_var.set(
            'No verified UpdateFigureData action captured. '
            'Try another manual Looks save with Habbo connected via G-Earth.')

    def _receive_outfit_capture(self,gender,figure):
        if not self._outfit_capture_pending:
            return
        self._outfit_capture_pending=False
        try:
            outfit_update_expression(gender,figure)
        except ValueError:
            self.outfit_status_var.set('Look capture rejected: invalid clothing fields.')
            return
        pair={'gender':gender,'figure':figure}
        if pair in self.outfit_presets:
            self.outfit_status_var.set(
                'That outfit is already saved. Capture a visibly different look.')
            return
        if len(self.outfit_presets)>=8:
            self.outfit_status_var.set('Eight outfits saved; remove one first.')
            return
        self.outfit_presets.append(pair)
        self.config['outfit_presets']=list(self.outfit_presets)
        self.save()
        self._render_outfit_presets()
        self.outfit_status_var.set(
            f'Outfit {len(self.outfit_presets)} saved from a real Habbo clothing change. '
            'Capture one more or press Start cycling.')

    def _remove_outfit(self):
        if self._outfit_running:
            self.outfit_status_var.set('Stop cycling before editing saved looks.')
            return
        indices=self.outfit_listbox.curselection()
        if not indices:
            self.outfit_status_var.set('Select an outfit to remove.')
            return
        self.outfit_presets.pop(indices[0])
        self.config['outfit_presets']=list(self.outfit_presets)
        self.save()
        self._render_outfit_presets()
        self.outfit_status_var.set('Selected outfit removed.')

    def _start_outfit_cycle(self):
        if self._outfit_running:
            self.outfit_status_var.set('Already cycling; press STOP to finish.')
            return
        if not self.packet_started or not self.packet_extension or not self._habbo_session_connected:
            self.outfit_status_var.set('Connect Habbo through G-Earth before starting.')
            return
        if len(self.outfit_presets)<2:
            self.outfit_status_var.set('Capture at least two different looks first.')
            return
        try:
            interval_ms=float(self.outfit_delay_var.get().strip())
            if not math.isfinite(interval_ms) or interval_ms<0:
                raise ValueError('Delay must be a non-negative number of milliseconds.')
            for outfit in self.outfit_presets:
                outfit_update_expression(outfit['gender'],outfit['figure'])
        except (ValueError,KeyError,TypeError) as exc:
            self.outfit_status_var.set('Cannot start: '+str(exc)[:125])
            return
        self.config['outfit_delay_ms']=str(interval_ms)
        self.save()
        self._outfit_capture_pending=False
        self._outfit_generation+=1
        self._outfit_running=True
        self._outfit_interval_ms=interval_ms
        self._outfit_index=0
        self._outfit_sent=0
        self.outfit_status_var.set(
            f'Cycling {len(self.outfit_presets)} saved looks every {interval_ms:g} ms. '
            '0 ms means no requested pause between callbacks. '
            'Actual scheduling and server application are unverified.')
        self._outfit_after_id=self.root.after(
            0,lambda gen=self._outfit_generation:self._outfit_tick(gen))

    def _outfit_tick(self,generation):
        self._outfit_after_id=None
        if not self._outfit_running or generation!=self._outfit_generation:
            return
        if not self.packet_started or not self.packet_extension or not self._habbo_session_connected:
            self._stop_outfit_cycle('Habbo/G-Earth disconnected; cycling stopped.')
            return
        index=self._outfit_index%len(self.outfit_presets)
        preset=self.outfit_presets[index]
        try:
            expression=outfit_update_expression(preset['gender'],preset['figure'])
            ext=self.packet_extension
            packet=ext.string_to_packet(expression)
            if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
                raise ValueError('G-Earth could not build a valid look-change packet.')
            if ext.send_to_server(packet) is False:
                raise RuntimeError('G-Earth rejected the look-change request.')
        except Exception as exc:
            self._stop_outfit_cycle('Outfit change failed: '+str(exc)[:140])
            return
        self._outfit_sent+=1
        self._outfit_index=(index+1)%len(self.outfit_presets)
        if self.packet_active:
            self._packet_put((
                'outfit_local',datetime.now().strftime('%H:%M:%S'),
                'Outgoing',f'[Outfit Cycler] UpdateFigureData → Outfit {index+1} | '
                'local G-Earth send accepted; server application unverified'))
        self.outfit_status_var.set(
            f'Cycling — outfit {index+1}/{len(self.outfit_presets)}; '
            f'local requests: {self._outfit_sent}. '
            'Server rate limits/accepted changes are unknown.')
        if self._outfit_running and generation==self._outfit_generation:
            self._outfit_after_id=self.root.after(
                round(self._outfit_interval_ms),
                lambda gen=generation:self._outfit_tick(gen))

    def _stop_outfit_cycle(self,reason=None):
        self._outfit_running=False
        self._outfit_generation+=1
        self._outfit_capture_pending=False
        after_id=self._outfit_after_id
        self._outfit_after_id=None
        if after_id is not None:
            try:self.root.after_cancel(after_id)
            except (tk.TclError,AttributeError):pass
        if reason is None:
            reason='Outfit cycling stopped.'
        self.outfit_status_var.set(
            f'{reason} Local requests sent: {self._outfit_sent}.')

    def _make_face_panel(self,parent):
        holder=ttk.Frame(parent,style='Panel.TFrame',padding=16)
        holder.pack(fill='both',expand=True)
        tk.Label(holder,text='360° FACE ROTATOR',
                 font=('Segoe UI Semibold',18),
                 fg=COMPANION_UI['text'],bg=COMPANION_UI['background']).pack(anchor='w')
        ttk.Label(holder,text='Rotate through all eight facing directions '
                  'in 45° steps. Only LookTo packets are sent; your avatar '
                  'is never instructed to walk to another square.',
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(5,13))
        ttk.Label(holder,textvariable=self.packet_connection_status,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,12))
        ttk.Button(holder,text='Capture my standing tile',
                   command=self._arm_face_capture).pack(anchor='w',pady=(0,9))
        ttk.Label(holder,text='Within 30 seconds, click your OWN avatar '
                  'once inside Habbo (not the floor or another player). '
                  'Companion reads the normal LookTo target. '
                  'You must recapture after moving or changing rooms.',
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,14))
        opts=ttk.Frame(holder,style='Panel.TFrame')
        opts.pack(fill='x',pady=(0,12))
        ttk.Label(opts,text='Milliseconds per 45° turn',
                  style='Panel.TLabel').pack(side='left')
        ttk.Entry(opts,textvariable=self.face_delay_var,width=8).pack(
            side='left',padx=(9,14))
        ttk.Label(opts,text='150–60000 ms (default 350)',
                  style='Panel.TLabel').pack(side='left')
        direction=ttk.Frame(holder,style='Panel.TFrame')
        direction.pack(fill='x',pady=(0,14))
        ttk.Label(direction,text='Direction',
                  style='Panel.TLabel').pack(side='left',padx=(0,13))
        ttk.Radiobutton(direction,text='Clockwise',
                        variable=self.face_direction_var,
                        value='Clockwise').pack(side='left',padx=(0,16))
        ttk.Radiobutton(direction,text='Counterclockwise',
                        variable=self.face_direction_var,
                        value='Counterclockwise').pack(side='left')
        actions=ttk.Frame(holder,style='Panel.TFrame')
        actions.pack(fill='x',pady=(0,10))
        ttk.Button(actions,text='Start 360° rotation',
                   style='Primary.TButton',
                   command=self._start_face_rotator).pack(side='left',padx=(0,10))
        ttk.Button(actions,text='STOP',
                   command=self._stop_face_rotator).pack(side='left')
        ttk.Label(holder,textvariable=self.face_status_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,10))
        ttk.Label(holder,text='Stops on manual movement, room change, '
                  'game disconnect or packet error. Sends are local G-Earth '
                  'requests; Habbo may rate-limit or ignore fast turns.',
                  style='Panel.TLabel',wraplength=620).pack(anchor='w')

    def _arm_face_capture(self):
        if self._face_running:
            self.face_status_var.set('Press STOP before capturing a new tile.')
            return
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            self.face_status_var.set('Connect Habbo through G-Earth first.')
            return
        self._face_tile=None
        self._face_capture_pending=True
        self._face_capture_generation+=1
        self.face_status_var.set('Capture armed: click your OWN avatar in Habbo '
                                 'within 30 seconds, not an empty square.')
        self.root.after(30000,
                        lambda gen=self._face_capture_generation:
                        self._face_capture_timeout(gen))

    def _face_capture_timeout(self,generation):
        if generation!=self._face_capture_generation or not self._face_capture_pending:
            return
        self._face_capture_pending=False
        self.face_status_var.set('No LookTo packet captured. Click Capture '
                                 'and click your own avatar again.')

    def _accept_face_tile(self,x,y):
        if not self._face_capture_pending:
            return
        self._face_capture_pending=False
        try:
            face_rotation_targets(x,y)
        except ValueError as exc:
            self.face_status_var.set('Invalid tile: '+str(exc))
            return
        self._face_tile=(x,y)
        self.face_status_var.set(
            f'Captured LookTo target ({x},{y}). If you clicked your own avatar, '
            'this is your standing square. Press Start to rotate without walking.')

    def _start_face_rotator(self):
        if self._face_running:
            self.face_status_var.set('Already rotating; press STOP first.')
            return
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            self.face_status_var.set('Connect Habbo through G-Earth first.')
            return
        if self._face_tile is None:
            self.face_status_var.set('Capture your standing tile by clicking '
                                     'your own avatar before starting.')
            return
        try:
            delay=int(self.face_delay_var.get().strip())
            if not 150<=delay<=60000:
                raise ValueError('Enter 150–60000 milliseconds.')
            direction=self.face_direction_var.get()
            if direction not in ('Clockwise','Counterclockwise'):
                raise ValueError('Choose clockwise or counterclockwise.')
            targets=face_rotation_targets(*self._face_tile,
                                          clockwise=(direction=='Clockwise'))
            # Prevalidate every named LookTo command. Do not send movement.
            for x,y in targets:
                face_lookto_expression(x,y)
        except (ValueError,TypeError) as exc:
            self.face_status_var.set('Cannot start: '+str(exc))
            return
        self.config['face_delay_ms']=str(delay)
        self.config['face_direction']=direction
        self.save()
        self._face_capture_pending=False
        self._face_generation+=1
        self._face_running=True
        self._face_targets=targets
        self._face_interval_ms=delay
        self._face_step=0
        self._face_sent=0
        self.face_status_var.set(
            f'Rotating {direction.lower()} every {delay} ms '
            f'around ({self._face_tile[0]},{self._face_tile[1]}). '
            'Only named LookTo actions; no walking.')
        self._face_after_id=self.root.after(
            0,lambda gen=self._face_generation:self._face_tick(gen))

    def _face_tick(self,generation):
        self._face_after_id=None
        if not self._face_running or generation!=self._face_generation:
            return
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            self._stop_face_rotator('G-Earth or Habbo disconnected.')
            self._face_tile=None
            return
        if len(self._face_targets)!=8:
            self._stop_face_rotator('Rotation targets unavailable.')
            return
        index=self._face_step%8
        x,y=self._face_targets[index]
        try:
            expression=face_lookto_expression(x,y)
            ext=self.packet_extension
            packet=ext.string_to_packet(expression)
            if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
                raise ValueError('G-Earth could not construct the named LookTo packet.')
            if ext.send_to_server(packet) is False:
                raise RuntimeError('G-Earth rejected the LookTo request.')
        except Exception as exc:
            self._stop_face_rotator('Rotation stopped: '+str(exc)[:130])
            return
        self._face_sent+=1
        self._face_step=(index+1)%8
        if self.packet_active:
            self._packet_put((
                'face_local',datetime.now().strftime('%H:%M:%S'),
                'Outgoing',f'[Face Rotator] LookTo target ({x},{y}), '
                f'45° step {index+1}/8 | local send accepted; facing unverified'))
        self.face_status_var.set(
            f'Rotating in place — step {index+1}/8, '
            f'{self._face_sent} local LookTo requests, '
            f'{self._face_sent//8} complete 360° cycles attempted. '
            'Server-facing updates unverified.')
        if self._face_running and generation==self._face_generation:
            self._face_after_id=self.root.after(
                self._face_interval_ms,
                lambda gen=generation:self._face_tick(gen))

    def _stop_face_rotator(self,reason=None):
        self._face_running=False
        self._face_generation+=1
        self._face_capture_pending=False
        after_id=self._face_after_id
        self._face_after_id=None
        if after_id is not None:
            try:self.root.after_cancel(after_id)
            except (tk.TclError,AttributeError):pass
        if reason is None:
            reason='Face rotation stopped.'
        self.face_status_var.set(
            f'{reason} {self._face_sent} local LookTo requests attempted.')

    def _face_position_invalidated(self,reason):
        if self._face_running:
            self._stop_face_rotator(reason)
        self._face_capture_pending=False
        self._face_tile=None
        self.face_status_var.set(reason+' Capture your standing tile again.')

    def _make_dance_panel(self,parent):
        holder=ttk.Frame(parent,style='Panel.TFrame',padding=16)
        holder.pack(fill='both',expand=True)
        tk.Label(holder,text='DANCE CONTROLLER',
                 font=('Segoe UI Semibold',18),
                 fg=COMPANION_UI['text'],bg=COMPANION_UI['background']).pack(anchor='w')
        ttk.Label(holder,text='Play a single Habbo dance or automatically '
                  'switch between the moves you choose. Uses the live '
                  'named Dance packet, with no numeric header guessing.',
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(5,12))
        ttk.Label(holder,textvariable=self.packet_connection_status,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,12))
        ttk.Label(holder,text='PLAY A DANCE',
                  style='Section.TLabel').pack(anchor='w',pady=(0,8))
        picker=ttk.Frame(holder,style='Panel.TFrame')
        picker.pack(fill='x',pady=(0,11))
        self.dance_style_picker=ttk.Combobox(
            picker,textvariable=self.dance_style_var,width=27,
            values=tuple(DANCE_STYLE_NAMES[i] for i in (1,2,3,4)),
            state='readonly')
        self.dance_style_picker.pack(side='left',padx=(0,12))
        ttk.Button(picker,text='Dance',style='Primary.TButton',
                   command=self._play_selected_dance).pack(side='left')
        ttk.Label(holder,text='Hab-Hop is available to everyone. '
                  'Pogo Mogo, Duck Funk and The Rollie normally require '
                  'Habbo Club; the server decides which moves you can use.',
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,17))
        ttk.Label(holder,text='AUTO-CYCLE DANCES',
                  style='Section.TLabel').pack(anchor='w',pady=(0,8))
        for style_id in (1,2,3,4):
            ttk.Checkbutton(holder,text=DANCE_STYLE_NAMES[style_id],
                            variable=self.dance_enabled_vars[style_id]).pack(
                                anchor='w',pady=(0,5))
        period=ttk.Frame(holder,style='Panel.TFrame')
        period.pack(fill='x',pady=(12,14))
        ttk.Label(period,text='Milliseconds per dance',
                  style='Panel.TLabel').pack(side='left')
        ttk.Entry(period,textvariable=self.dance_delay_var,width=9).pack(
            side='left',padx=(9,12))
        ttk.Label(period,text='1000–60000 ms (default 3000)',
                  style='Panel.TLabel').pack(side='left')
        actions=ttk.Frame(holder,style='Panel.TFrame')
        actions.pack(fill='x',pady=(0,13))
        ttk.Button(actions,text='Start cycling',
                   style='Primary.TButton',
                   command=self._start_dance_cycle).pack(side='left',padx=(0,10))
        ttk.Button(actions,text='STOP DANCING',
                   command=self._stop_dance_and_cycle).pack(side='left')
        ttk.Label(holder,textvariable=self.dance_status_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,10))
        ttk.Label(holder,text='Cycle only sends locally accepted Dance '
                  'requests. It stops on room change, disconnect or send '
                  'failure. Actual dance changes may be delayed or ignored '
                  'by Habbo; this tool never guarantees server acceptance.',
                  style='Panel.TLabel',wraplength=620).pack(anchor='w')

    def _send_dance_action(self,style_id):
        """One named Dance packet; G-Earth and Habbo handle live validation."""
        expression=dance_packet_expression(style_id)
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            raise RuntimeError('Connect Habbo through G-Earth before dancing.')
        ext=self.packet_extension
        packet=ext.string_to_packet(expression)
        if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
            raise ValueError('No valid named Dance packet in current G-Earth mappings.')
        if ext.send_to_server(packet) is False:
            raise RuntimeError('G-Earth rejected the Dance request.')
        self._dance_sent+=1
        self._dance_last_sent_id=style_id
        if self.packet_active:
            self._packet_put((
                'dance_local',datetime.now().strftime('%H:%M:%S'),
                'Outgoing',f'[Dance Controller] Dance {style_id} — '
                f'{DANCE_STYLE_NAMES[style_id]} | local G-Earth send accepted; '
                'server application and HC access unverified'))

    def _play_selected_dance(self):
        if self._dance_running:
            self._stop_dance_cycle('Dance cycling stopped; playing selection.')
        try:
            label=self.dance_style_var.get()
            style_id=next((i for i in (1,2,3,4)
                           if DANCE_STYLE_NAMES[i]==label),None)
            if style_id is None:
                raise ValueError('Choose one of the four supported dances.')
            self._send_dance_action(style_id)
        except (ValueError,RuntimeError,AttributeError) as exc:
            self.dance_status_var.set('Could not dance: '+str(exc)[:140])
            return
        self.config['dance_selected']=label
        self.save()
        self.dance_status_var.set(
            f'{DANCE_STYLE_NAMES[style_id]} requested. '
            'Local G-Earth send accepted; server application unverified.')

    def _start_dance_cycle(self):
        if self._dance_running:
            self.dance_status_var.set('Already cycling; press STOP DANCING.')
            return
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            self.dance_status_var.set('Connect Habbo through G-Earth first.')
            return
        try:
            delay=int(self.dance_delay_var.get().strip())
            if not 1000<=delay<=60000:
                raise ValueError('Enter 1000–60000 milliseconds per dance.')
            sequence=dance_cycle_sequence({
                i:self.dance_enabled_vars[i].get() for i in (1,2,3,4)})
            for style_id in sequence:
                dance_packet_expression(style_id)
        except (ValueError,TypeError,KeyError,AttributeError) as exc:
            self.dance_status_var.set('Cannot cycle: '+str(exc)[:140])
            return
        self.config['dance_delay_ms']=str(delay)
        self.config['dance_cycle_selected']=list(sequence)
        self.save()
        self._dance_generation+=1
        self._dance_running=True
        self._dance_sequence=sequence
        self._dance_step=0
        self._dance_interval_ms=delay
        self._dance_sent=0
        self.dance_status_var.set(
            f'Cycling {len(sequence)} dances every {delay} ms. '
            'No dance changes have been server-confirmed.')
        self._dance_after_id=self.root.after(
            0,lambda gen=self._dance_generation:self._dance_tick(gen))

    def _dance_tick(self,generation):
        self._dance_after_id=None
        if not self._dance_running or generation!=self._dance_generation:
            return
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            self._stop_dance_cycle('Habbo or G-Earth disconnected; cycling stopped.')
            return
        style_id=self._dance_sequence[self._dance_step%len(self._dance_sequence)]
        try:
            self._send_dance_action(style_id)
        except (ValueError,RuntimeError,AttributeError) as exc:
            self._stop_dance_cycle('Dance cycling stopped: '+str(exc)[:140])
            return
        self._dance_step+=1
        self.dance_status_var.set(
            f'Cycling — {DANCE_STYLE_NAMES[style_id]}; '
            f'{self._dance_sent} local dance requests attempted, '
            f'{self._dance_step//len(self._dance_sequence)} complete '
            'rotations through selected moves. '
            'Server response unverified.')
        if self._dance_running and generation==self._dance_generation:
            self._dance_after_id=self.root.after(
                self._dance_interval_ms,
                lambda gen=generation:self._dance_tick(gen))

    def _stop_dance_cycle(self,reason=None):
        """Cancel scheduled sends; do not send a packet on disconnect/close."""
        self._dance_running=False
        self._dance_generation+=1
        after_id=self._dance_after_id
        self._dance_after_id=None
        if after_id is not None:
            try:self.root.after_cancel(after_id)
            except (tk.TclError,AttributeError):pass
        if reason is None:
            reason='Dance cycling stopped.'
        self.dance_status_var.set(
            f'{reason} {self._dance_sent} local dance requests attempted.')

    def _stop_dance_and_cycle(self):
        """Explicit button: stop the loop, then request actual dance type 0."""
        self._stop_dance_cycle('Dance cycling stopped.')
        try:
            self._send_dance_action(0)
        except (ValueError,RuntimeError,AttributeError) as exc:
            self.dance_status_var.set(
                'Cycling stopped locally; could not request dance stop: '+
                str(exc)[:125])
            return
        self.dance_status_var.set(
            'STOP Dance(0) sent via G-Earth. '
            'Server confirmation unverified; no cycle remains scheduled.')

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
            if getattr(self,'packet_active',False):
                self._packet_put((
                    'packet_local',datetime.now().strftime('%H:%M:%S'),
                    'Outgoing',format_coffee_packet_viewer_event(
                        locals().get('expression',''),False)))
            recorder=getattr(self,'_coffee_recorder',None)
            if recorder is not None:
                recorder.record('send_error',action_number=self._coffee_sent+1,
                                note=str(exc)[:160])
            self._stop_coffee_loop('Coffee loop stopped after error: '+str(exc)[:145])
            return
        # Direct G-Earth sends do not necessarily appear in intercept hooks.
        # Record the local request only; never infer server/recipient acceptance.
        if getattr(self,'packet_active',False):
            self._packet_put((
                'packet_local',datetime.now().strftime('%H:%M:%S'),
                'Outgoing',format_coffee_packet_viewer_event(expression,True)))
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
        if len(values)>3 and values[3] in ('Coffee Pass Loop','Outfit Cycler'):
            self.manipulator_status.set(
                'Generated-action log entries are summaries, not replayable packets.')
            return
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
        if getattr(self,'bot_standalone_var',None) is not None and self.bot_standalone_var.get():
            self.engine_status_var.set('Engine: skipped (clientless-only mode)')
            return
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
        """Attach G-Python and automatically capture when the user allows it.

        Before Habbo launches, connecting to G-Earth's local extension port
        cannot interrupt an in-progress AIR loading screen. If Habbo is already
        open, wait for chat/room evidence. The Coffee Pass Loop Start button is
        also an explicit room-ready signal and can attach directly.
        """
        if (self.packet_started or time.monotonic()<self._packet_auto_retry_after
            or (getattr(self,'bot_standalone_var',None) is not None
                and self.bot_standalone_var.get())):
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
        self._connect_gearth(capture=self.packet_auto_capture_var.get())

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

    def _launch_gearth(self,auto_connect=False,select_if_missing=True,
                       target_override=None):
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
                if target_override is not None:
                    if target_override != (DEFAULT_BRIDGE_HOST,DEFAULT_BRIDGE_PORT):
                        raise ValueError('Invalid local G-Earth bridge target')
                    host,game_port=target_override
                else:
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
                # Other tools may have attached without logging before Habbo
                # connected. Arm the viewer for each new game connection.
                if self.config.get('packet_auto_capture',True):
                    self.packet_active=True
                self._packet_put(('session_connection',True))
                self._packet_put(('room_users_reset',))
                event('Habbo AIR connected; packet viewer LIVE.' if self.packet_active
                      else 'Habbo AIR connected; packet viewer paused.')
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
                            or self._outfit_capture_pending or self._face_capture_pending
                            or self._face_tile is not None
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
                    if direction=='Outgoing' and self._outfit_capture_pending:
                        # Validate the actual mapped header, not just an untrusted
                        # expression printed by G-Earth. Capture only this packet.
                        try:
                            records=(getattr(ext,'packet_infos',None) or {}).get(
                                Direction.TO_SERVER,{}).get(msg.packet.header_id(),())
                            verified=any(str(info.get('Name','')).casefold()==
                                         'updatefiguredata' for info in records)
                            parsed=(parse_outfit_update_expression(
                                msg.packet.g_expression(ext)) if verified else None)
                            if parsed is not None:
                                self._packet_put(('outfit_captured',*parsed))
                        except (ValueError,TypeError,AttributeError,IndexError):
                            pass
                    if direction=='Outgoing' and self._face_capture_pending:
                        # The user must click their own avatar to make this
                        # target their current position. We verify packet
                        # name/shape but cannot infer who the user clicked.
                        coords=outgoing_face_tile_from_packet(
                            ext,Direction.TO_SERVER,msg.packet)
                        if coords is not None:
                            self._packet_put(('face_tile_captured',*coords))
                    if direction=='Outgoing' and self._face_tile is not None:
                        if outgoing_is_named(
                                ext,Direction.TO_SERVER,msg.packet,'MoveAvatar'):
                            self._packet_put(('face_movement',))
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
                    'Results are for a synthetic test server only.')
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
            if item[0]=='bot_gearth_status':
                _,ident,message=item
                if ident in self._bot_gearth_bridges:
                    self.bot_gearth_status_var.set(message)
                continue
            if item[0]=='bot_action_result':
                _,ident,generation,action,count,error=item
                self._bot_action_inflight.discard(ident)
                if generation!=self._tcp_generation.get(ident,0):
                    continue
                if action in ('Collect hand item','Pass hand item'):
                    self._coffee_manual_send_result(ident,generation,error,action)
                    if error is not None:
                        if self._coffee_run and any(r['id']==ident for r in self._coffee_run['runs']
                                                    if r['phase']!='complete'):
                            self._coffee_stop_run('Run stopped: '+error)
                        else:self.coffee_status_var.set('Hand-item action failed: '+error)
                batch=self._coffee_run
                if batch and any(r['id']==ident and r['count'] is None
                                 and r['phase']!='complete' for r in batch['runs']):
                    self._coffee_schedule_loop_tick(batch,0)
                if error is None and action!='Anti-AFK':
                    # Ordinary user actions postpone automatic idle refreshes.
                    self._bot_anti_afk_last[ident]=time.monotonic()
                if action=='Anti-AFK':
                    selected=self._bot_selected_profile()
                    if selected is not None and selected['id']==ident:
                        self.bot_anti_afk_status_var.set(
                            'Stationary LookTo sent via game session. '
                            'Server idle reset not verified.' if error is None
                            else 'Anti-AFK send failed: '+error)
                    continue
                if action=='Join room' and error is not None:
                    self._bot_walk_plans.pop(ident,None)
                    self.bot_walk_status_var.set('Room join failed: '+error)
                if action=='Follow Walk' and error is not None:
                    follow=getattr(self,'_bot_follow_run',None)
                    if follow and follow['id']==ident and follow['generation']==generation:
                        self._bot_follow_stop('Follow stopped: '+error)
                if action=='Group Follow Walk' and error is not None:
                    group=getattr(self,'_bot_follow_group_run',None)
                    if group and group['members'].get(ident,(None,None))[0]==generation:
                        group['members'].pop(ident,None)
                        if not group['members']:
                            self._bot_follow_stop('All-account follow stopped: '+error)
                self._bot_follow_wake(ident)
                if action=='Auto Walk' and error is not None:
                    self._bot_walk_next(ident,generation,'Walk request failed')
                if (action=='Auto Walk' and error is None
                    and ident in self._bot_walk_plans):
                    self.bot_walk_status_var.set(
                        'Walking request sent; awaiting avatar position confirmation.')
                label=next((a['label'] for a in self._account_profiles
                            if a['id']==ident),ident[:6])
                self.bot_status_var.set(
                    (label+': Direct TCP local send accepted: '+action+
                     f' ({count} packet(s)). Server application not verified.'
                     if error is None else label+': Clientless action failed: '+error))
                continue
            if item[0]=='bot_room_bots':
                _,ident,generation,bots=item
                if generation==self._tcp_generation.get(ident,0):
                    self._bot_follow_observe(ident,generation,'bots',bots)
                    self._bot_follow_wake(ident)
                continue
            if item[0]=='bot_hand_observation':
                _,ident,generation,observation=item
                if generation==self._tcp_generation.get(ident,0):
                    self._coffee_observe(ident,generation,observation)
                    self._bot_follow_observe(ident,generation,*observation)
                    if observation[0] in ('remove','players','room'):
                        self._bot_follow_wake(ident)
                continue
            if item[0]=='bot_walk_observation':
                _,ident,generation,observation=item
                if generation==self._tcp_generation.get(ident,0):
                    self._bot_receive_walk_observation(ident,generation,observation)
                    self._bot_follow_observe(ident,generation,*observation)
                    self._bot_follow_wake(ident)
                continue
            if item[0]=='bot_chat':
                _,ident,generation,kind,index,message=item
                if generation==self._tcp_generation.get(ident,0):
                    self._bot_show_chat(ident,kind,index,message)
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
                        self._bot_anti_afk_last[ident]=time.monotonic()
                        bridge=self._bot_gearth_bridges.get(ident)
                        self._tcp_states[ident]=(
                            'Authenticated (G-Earth gameplay proxy)'
                            if bridge is not None and bridge.ready else
                            'Authenticated (direct TCP)')
                        self.tcp_status_var.set(
                            'Habbo authenticated; clientless gameplay routed '
                            'through G-Earth.' if bridge is not None else
                            'Habbo sent AuthenticationOK; session is active.')
                    else:
                        self._tcp_states[ident]='Authentication succeeded, '
                        self._tcp_states[ident]+='but the game socket closed.'
                        self.tcp_status_var.set(self._tcp_states[ident])
                    self._tcp_log_event(ident,self._tcp_states[ident])
                    self._tcp_render()
                    if item[3].authenticated:
                        # Tk event queue owns the transition; this callback must
                        # recheck account generation before sending anything.
                        if ident in self._bot_pending_room:
                            self.root.after(0,lambda uid=ident,gen=generation:
                                self._bot_dispatch_pending_room(uid,gen))
                    else:
                        self._bot_pending_room.pop(ident,None)
                        bridge=self._bot_gearth_bridges.pop(ident,None)
                        if bridge:bridge.close()
                elif event=='tcp_failed':
                    self._tcp_inflight.discard(ident)
                    bridge=self._bot_gearth_bridges.pop(ident,None)
                    if bridge:bridge.close()
                    pending=self._bot_pending_room.pop(ident,None)
                    if pending and pending[0]==generation:
                        self.bot_status_var.set(
                            'Clientless profile connection failed: '+item[3])
                    self._tcp_states[ident]='Connection failed: '+item[3]
                    self._bot_follow_wake(ident)
                    self.tcp_status_var.set(self._tcp_states[ident])
                    self._tcp_log_event(ident,self._tcp_states[ident])
                    self._tcp_render()
                elif event=='tcp_packet':
                    self._tcp_log_event(ident,
                        f'Incoming packet ID {item[3]} ({item[4]} bytes)')
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
            if item[0]=='game_panel_arm':
                if item[1]==self._account_auto_generation:
                    self._game_panel_pending.append((frozenset(item[2]),time.monotonic()+60.0))
                continue
            if item[0]=='account_auto_status':
                if item[1]==self._account_auto_generation:
                    self.account_status_var.set(item[2])
                continue
            if item[0]=='account_auto_stage':
                if item[1]==self._account_auto_generation:
                    self._account_run_states[item[2]]=item[3]
                    if self.account_table.exists(item[2]):
                        self.account_table.set(item[2],'launch_state',self._account_display_status(item[2]))
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
                self._stop_dance_cycle('Room changed; dance cycling stopped.')
                self._face_position_invalidated('Room changed; rotation stopped.')
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
            if item[0]=='outfit_captured':
                self._receive_outfit_capture(item[1],item[2])
                continue
            if item[0]=='face_tile_captured':
                self._accept_face_tile(item[1],item[2])
                continue
            if item[0]=='face_movement':
                self._face_position_invalidated(
                    'Manual walk requested; rotation stopped.')
                continue
            if item[0]=='session_connection':
                self._fuzz_refresh_connected_server()
                self.packet_connection_status.set(
                    ('Packet Viewer LIVE — G-Earth and Habbo connected.'
                     if self.packet_active else
                     'G-Earth and Habbo connected; packet capture paused.')
                    if item[1] else
                    'G-Earth packet tools attached; waiting for Habbo traffic.')
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
                    self._stop_outfit_cycle('Habbo disconnected; cycling stopped.')
                    self._stop_dance_cycle('Habbo disconnected; dance cycling stopped.')
                    self._face_position_invalidated(
                        'Habbo disconnected; face rotation stopped.')
                continue
            if item[0]=='manip_status':
                self.manipulator_status.set(item[1]);continue
            if item[0]=='manip_off':
                self.manipulation_enable_var.set(False);continue
            if item[0] not in ('packet','packet_local','outfit_local','face_local','dance_local'):
                continue
            if item[0] in ('packet_local','outfit_local','face_local','dance_local') and not self.packet_active:
                continue  # Pause also pauses locally generated-request entries.
            _,timestamp,direction,detail=item
            source=({'packet':'G-Earth','packet_local':'Coffee Pass Loop',
                     'outfit_local':'Outfit Cycler',
                     'face_local':'Face Rotator',
                     'dance_local':'Dance Controller'}[item[0]])
            self.packet_data.append((timestamp,direction,detail))
            if len(self.packet_data)>500:self.packet_data.pop(0)
            needle=self.packet_filter_var.get().lower().strip()
            if needle and needle not in detail.lower():continue
            self.packet_tree.insert(
                '', 'end',values=(timestamp,direction,detail[:145],source))
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

    def _save_packet_auto_capture(self):
        enabled=bool(self.packet_auto_capture_var.get())
        self.config['packet_auto_capture']=enabled
        self.save()
        if self.packet_started:
            self.packet_active=enabled
            if self._habbo_session_connected:
                self.packet_status.set(
                    'Packet viewer LIVE — incoming and outgoing packets.'
                    if enabled else 'Packet viewer paused; auto-capture disabled.')
                self.packet_connection_status.set(
                    'Packet Viewer LIVE — G-Earth and Habbo connected.'
                    if enabled else
                    'G-Earth and Habbo connected; packet capture paused.')
            else:
                self.packet_status.set(
                    'Auto-capture enabled; waiting for Habbo traffic.' if enabled
                    else 'Auto-capture disabled; viewer paused.')
        elif enabled:
            self.packet_status.set(
                'Auto-capture enabled. Waiting for G-Earth and an active Habbo session.')
        else:
            self.packet_status.set(
                'Auto-capture disabled. Use Connect packet tools (manual) to capture.')

    def _toggle_capture(self):
        if not self.packet_started:
            self.packet_status.set('Connect to G-Earth before pausing or resuming packet capture.')
            return
        self.packet_active=not self.packet_active
        self.packet_status.set('Packet viewer capturing.' if self.packet_active else 'Packet viewer paused.')
        if self._habbo_session_connected:
            self.packet_connection_status.set(
                'Packet Viewer LIVE — G-Earth and Habbo connected.'
                if self.packet_active else
                'G-Earth and Habbo connected; packet capture paused.')

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

    def _game_panel_close_or_exit(self):
        if self._game_panel_target is not None:
            self._game_panel_hide()
        else:
            self.close()

    def _game_panel_hide(self,return_focus=True):
        self.root.withdraw()
        self.settings_open=False
        self.root.attributes('-topmost',False)
        if return_focus and self._game_panel_target is not None:
            try:
                u=self.tracker.user32
                u.SetForegroundWindow.argtypes=(wintypes.HWND,)
                u.SetForegroundWindow.restype=wintypes.BOOL
                u.SetForegroundWindow(self._game_panel_target[0])
            except (OSError,AttributeError,ValueError,TypeError):
                pass

    def _game_panel_detach(self):
        saved=self._game_panel_restore
        self._game_panel_target=None
        self._game_panel_windows.clear()
        self._game_panel_pending.clear()
        self._game_panel_restore=None
        self.root.attributes('-topmost',False)
        self.root.deiconify()
        self.root.state('normal')
        if saved:
            geometry,state,minimum=saved
            self.root.minsize(*minimum)
            self.root.geometry(geometry)
            if state=='zoomed':
                self.root.state('zoomed')
        self.settings_open=True

    def _game_panel_scan(self):
        if not (self._game_panel_pending or self._game_panel_windows):
            return
        now=time.monotonic()
        if now-self._game_panel_last_scan<0.5:
            return
        self._game_panel_last_scan=now
        current=account_native_client_windows()
        if current is None:
            # An enumeration error is not proof that a game closed.
            return
        self._game_panel_windows.intersection_update(current)
        pending=[]
        new=set()
        for baseline,deadline in self._game_panel_pending:
            found=set(current)-baseline
            if found:
                new.update(found)
            elif now<deadline:
                pending.append((baseline,deadline))
        self._game_panel_pending=pending
        new.difference_update(self._game_panel_windows)
        self._game_panel_windows.update(new)
        if new:
            # Prefer the actual foreground game when several windows appeared.
            chosen=next((w for w in sorted(new) if self.tracker.foreground_context(
                w[0],self.root.winfo_id())=='habbo'),min(new))
            if self._game_panel_restore is None:
                self._game_panel_restore=(self.root.geometry(),self.root.state(),self.root.minsize())
            self._game_panel_target=chosen
            self._game_panel_hide(return_focus=False)
        elif self._game_panel_target is not None and self._game_panel_target not in current:
            if self._game_panel_windows:
                self._game_panel_target=min(self._game_panel_windows)
                self._game_panel_hide(return_focus=False)
            else:
                # Closing the last tracked game restores the standalone panel.
                self._game_panel_detach()

    def _game_panel_show(self,target):
        u=self.tracker.user32
        rect=wintypes.RECT()
        u.GetWindowRect.argtypes=(wintypes.HWND,ctypes.POINTER(wintypes.RECT))
        u.GetWindowRect.restype=wintypes.BOOL
        if not u.GetWindowRect(target[0],ctypes.byref(rect)):
            return
        w=rect.right-rect.left
        h=rect.bottom-rect.top
        if w<250 or h<250:
            return
        # Keep the normal interactive Tk window, sized within the game.
        # No DLL injection, reparenting, or global always-on-top mode.
        margin=12
        width=min(1120,w-2*margin)
        height=min(740,h-2*margin)
        self._game_panel_target=target
        self.root.attributes('-topmost',False)
        self.root.deiconify()
        self.root.state('normal')
        self.root.minsize(min(940,width),min(620,height))
        self.root.geometry(f'{width}x{height}')
        self.root.update_idletasks()
        u.GetAncestor.argtypes=(wintypes.HWND,wintypes.UINT)
        u.GetAncestor.restype=wintypes.HWND
        hwnd=u.GetAncestor(self.root.winfo_id(),2) or self.root.winfo_id()
        u.SetWindowPos.argtypes=(wintypes.HWND,wintypes.HWND,ctypes.c_int,
            ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT)
        u.SetWindowPos.restype=wintypes.BOOL
        u.SetWindowPos(hwnd,0,rect.left+(w-width)//2,rect.top+(h-height)//2,
                       width,height,0x0010)
        self.root.lift()
        self.root.focus_force()
        self.settings_open=True

    def _game_panel_toggle(self):
        if not self._game_panel_windows:
            return
        # Only respond while a tracked native game or Companion is focused.
        root_id=self.root.winfo_id()
        foreground=next((w for w in sorted(self._game_panel_windows)
                         if self.tracker.foreground_context(w[0],root_id)=='habbo'),None)
        if foreground is not None:
            self._game_panel_show(foreground)
        elif (self._game_panel_target is not None and self.settings_open and
                self.tracker.foreground_context(self._game_panel_target[0],root_id)=='settings'):
            self._game_panel_hide()

    def _hotkeys(self):
        if os.name!='nt':return
        u=self.tracker.user32
        ctrl=bool(u.GetAsyncKeyState(0x11)&0x8000)
        shift=bool(u.GetAsyncKeyState(0x10)&0x8000)
        active=set()
        alt=bool(u.GetAsyncKeyState(0x12)&0x8000)
        if shift and not ctrl and not alt and u.GetAsyncKeyState(0xC0)&0x8000:
            active.add('game_panel') # Shift + grave/backtick (US/UK keyboard)
        if ctrl and shift:
            if u.GetAsyncKeyState(0x75)&0x8000:active.add('panel') # F6
            if u.GetAsyncKeyState(0x76)&0x8000:active.add('room') # F7
            if u.GetAsyncKeyState(0x21)&0x8000:active.add('older') # Page Up
            if u.GetAsyncKeyState(0x22)&0x8000:active.add('newer') # Page Down
            if u.GetAsyncKeyState(0x23)&0x8000:active.add('latest') # End
        for key in active-self.last_hotkeys:
            if key=='game_panel':
                self._game_panel_toggle()
            if key=='panel':
                if self._game_panel_target is not None:
                    # Existing recovery shortcut restores standalone mode.
                    self._game_panel_detach()
                elif self.settings_open:
                    self.root.withdraw()
                    self.settings_open=False
                else:
                    self.root.deiconify()
                    self.root.lift()
                    self.settings_open=True
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
            self._game_panel_scan()
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
        self._headless_manager.disconnect_all()
        if self._headless_server is not None:
            self._headless_server.stop()
            self._headless_server=None
        self._stop_packet_replay('Companion closed. Repeat stopped.')
        self._stop_coffee_loop('Companion closed. Coffee loop stopped.')
        self._stop_outfit_cycle('Companion closed. Outfit cycling stopped.')
        self._stop_face_rotator('Companion closed. Face rotation stopped.')
        self._stop_dance_cycle('Companion closed. Dance cycling stopped.')
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
