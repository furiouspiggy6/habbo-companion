# -*- coding: utf-8 -*-
"""Optional G-Earth gameplay MITM adapter for an independently authenticated bot.

Wire topology:
  Companion action (plaintext) -> G-Earth client socket (127.0.0.1:port)
  -> G-Earth modification pipeline -> upstream relay (127.0.0.2:port)
  -> Companion encrypted Habbo TCP socket.
  Game incoming packet -> upstream relay -> G-Earth modification pipeline
  -> client socket -> Companion's packet observers.

G-Earth's Flash mode normally scans an AIR process for RC4. By sending ONLY
post-authentication *plaintext* framed gameplay via a separate loopback-only
proxy session, this bridge avoids requiring AIR's memory, and avoids passing
SSO tickets, RSA/DH negotiation or encryption keys through G-Earth.

Requires G-Earth Flash mode targeting a hostname which resolves to 127.0.0.2
BEFORE G-Earth rewrites the hostname in the OS hosts file. G-Earth itself
listens at 127.0.0.1:port. Do not use its G-Python extension port (9092).
"""
from __future__ import annotations

import socket
import struct
import threading
import time

DEFAULT_BRIDGE_PORT = 31451
BRIDGE_UPSTREAM = "127.0.0.2"
BRIDGE_DOWNSTREAM = "127.0.0.1"
# nip.io is a convenience DNS alias to 127.0.0.2. On networks that block
# rebinding responses, a dedicated local hosts-file alias is required.
DEFAULT_BRIDGE_HOST = "127.0.0.2.nip.io"
BRIDGE_MAX_FRAME = 65536

# Gameplay-only and client-owned control frames. No auth, handshake, or
# unbounded arbitrary-packet injection reaches the live game server.
# Source-pinned for WIN63-202611041140-327405090.
SAFE_GAMEPLAY_OUT = frozenset((
    216, 2995, 2574, 3463, 3079, 3523, 1366, 207, 1117,
    923, 2391, 2519,
))


class GearthBridgeError(RuntimeError):
    """No authenticated gameplay should bypass an unavailable interception path."""


def _frame(header_id, payload=b""):
    if (type(header_id) is not int or not 0<=header_id<=65535
        or not isinstance(payload, bytes) or len(payload)>BRIDGE_MAX_FRAME-6):
        raise GearthBridgeError("Invalid game frame for local G-Earth relay")
    return struct.pack(">IH",len(payload)+2,header_id)+payload


def _text(data):
    data=data.encode("utf-8")
    return struct.pack(">H",len(data))+data


def _read_exact(sock, size):
    output=bytearray()
    while len(output)<size:
        block=sock.recv(size-len(output))
        if not block:
            raise OSError("G-Earth bridge socket disconnected")
        output.extend(block)
    return bytes(output)


def _read_frame(sock):
    length=struct.unpack(">I",_read_exact(sock,4))[0]
    if length<2 or length>BRIDGE_MAX_FRAME-4:
        raise GearthBridgeError("G-Earth returned an invalid plaintext frame length")
    data=_read_exact(sock,length)
    return struct.unpack_from(">H",data)[0],data[2:]


def verify_bridge_alias(host=DEFAULT_BRIDGE_HOST):
    """Return an explicit error rather than proxying to external addresses."""
    if (not isinstance(host,str) or not 4<=len(host)<=128
        or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"
               for c in host)):
        raise GearthBridgeError("Invalid G-Earth bridge hostname")
    try:
        addresses={item[4][0] for item in socket.getaddrinfo(
            host,None,family=socket.AF_INET,type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise GearthBridgeError(
            "Bridge hostname did not resolve. Local DNS may block nip.io; "
            "configure a local hosts alias to 127.0.0.2.") from exc
    if addresses!={BRIDGE_UPSTREAM}:
        raise GearthBridgeError(
            "Bridge hostname must resolve ONLY to 127.0.0.2 before starting "
            "G-Earth; refusing to send local gameplay to a different address.")
    return host


class ClientlessGearthBridge:
    """A single-account, bounded loopback-only plaintext gameplay connector."""

    def __init__(self, account_id, status=None, port=DEFAULT_BRIDGE_PORT):
        if type(port) is not int or not 1024<=port<=65535:
            raise GearthBridgeError("Invalid bridge listener port")
        self.account_id=account_id
        self.port=port
        self.status=status or (lambda _msg:None)
        self.listener=None
        self.front=None
        self.upstream=None
        self.session=None
        self.stop=threading.Event()
        self._lock_front=threading.Lock()
        self._lock_upstream=threading.Lock()
        self.ready=False
        self.delivered_in=0
        self.delivered_out=0

    def prepare(self):
        """Bind local upstream *before* launching G-Earth to avoid races."""
        if self.listener is not None:
            raise GearthBridgeError("Bridge is already preparing")
        listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:
            listener.bind((BRIDGE_UPSTREAM,self.port))
            listener.listen(1)
            listener.settimeout(0.5)
        except OSError:
            listener.close()
            raise GearthBridgeError(
                "Cannot reserve 127.0.0.2 bridge port. Check local port conflicts "
                "and Windows loopback support.") from None
        self.listener=listener
        self.stop.clear()

    def attach(self,session):
        if self.session is not None:
            raise GearthBridgeError("Bridge can only serve one game session")
        self.session=session

    def connect(self,release,timeout=35):
        """Connect to a *prepared G-Earth Flash game proxy*, not port 9092.

        The first successful client connect must send a valid AIR greeting to
        confirm G-Earth's packet stream. G-Earth then connects our local
        upstream bound to 127.0.0.2. Fail closed if the second half is absent.
        """
        if self.listener is None:
            raise GearthBridgeError("Bridge upstream must be prepared first")
        deadline=time.monotonic()+max(1,min(timeout,60))
        front=None
        while time.monotonic()<deadline and not self.stop.is_set():
            try:
                front=socket.create_connection((BRIDGE_DOWNSTREAM,self.port),
                                               timeout=0.5)
                break
            except OSError:
                time.sleep(0.35)
        if front is None:
            raise GearthBridgeError(
                "G-Earth Flash proxy did not listen at 127.0.0.1:"+
                str(self.port)+". Check that G-Earth started in Flash mode "
                "with the bridge hostname and this port.")
        self.front=front
        front.settimeout(10)
        # Synthetic local tunnel greeting only. NEVER put an SSO ticket in it.
        greeting=(_text(release)+_text("FLASH31")+struct.pack(">ii",6,4))
        try:
            front.sendall(_frame(4000,greeting))
            upstream=None
            while time.monotonic()<deadline and not self.stop.is_set():
                try:
                    upstream,_=self.listener.accept()
                    break
                except socket.timeout:
                    continue
            if upstream is None:
                raise GearthBridgeError(
                    "G-Earth accepted the client side, but its local upstream "
                    "was never connected. Interception is NOT active.")
            upstream.settimeout(None)
            front.settimeout(None)
            self.upstream=upstream
            # The synthetic greeting is passed to G-Earth's local upstream.
            head,payload=_read_frame(upstream)
            if head!=4000 or not payload.startswith(_text(release)):
                raise GearthBridgeError(
                    "G-Earth bridge did not forward the expected AIR greeting.")
            self.ready=True
            self.status("G-Earth plaintext gameplay proxy confirmed on localhost")
            threading.Thread(target=self._read_outgoing,daemon=True,
                             name="gearth-gameplay-out-"+self.account_id).start()
            threading.Thread(target=self._read_incoming,daemon=True,
                             name="gearth-gameplay-in-"+self.account_id).start()
        except (OSError,ValueError,GearthBridgeError):
            self.close()
            raise

    def send_outgoing(self,packet_id,payload):
        """A bot action enters G-Earth, not the real game socket."""
        if not self.ready or self.front is None or self.stop.is_set():
            raise GearthBridgeError("G-Earth interception path is not ready")
        if packet_id not in SAFE_GAMEPLAY_OUT:
            raise GearthBridgeError(
                "Unknown client packet cannot be forwarded through G-Earth")
        data=_frame(packet_id,payload)
        with self._lock_front:
            try:self.front.sendall(data)
            except OSError:
                self.close()
                raise GearthBridgeError("G-Earth client connection lost") from None

    def send_incoming(self,packet_id,payload):
        """A decrypted server packet enters G-Earth before the bot sees it."""
        if not self.ready or self.upstream is None or self.stop.is_set():
            raise GearthBridgeError("G-Earth interception path is not ready")
        data=_frame(packet_id,payload)
        with self._lock_upstream:
            try:self.upstream.sendall(data)
            except OSError:
                self.close()
                raise GearthBridgeError("G-Earth upstream connection lost") from None

    def _read_outgoing(self):
        try:
            while not self.stop.is_set():
                packet_id,payload=_read_frame(self.upstream)
                if (packet_id not in SAFE_GAMEPLAY_OUT or len(payload)>8192):
                    self.status("Rejected unmapped or oversized G-Earth outgoing packet")
                    continue
                session=self.session
                if (session is None or not session.authenticated
                    or session.stop.is_set()):
                    continue
                session._send(packet_id,payload,via_gearth=True)
                self.delivered_out+=1
        except (OSError,ValueError,GearthBridgeError):
            if not self.stop.is_set():
                self.status("G-Earth gameplay modification path disconnected")
                self.close()

    def _read_incoming(self):
        try:
            while not self.stop.is_set():
                packet_id,payload=_read_frame(self.front)
                session=self.session
                if (session is None or not session.authenticated
                    or session.stop.is_set()):
                    continue
                # G-Earth's incoming block/replace has already happened.
                session.on_packet(packet_id,len(payload))
                if session.on_content is not None:
                    session.on_content(packet_id,payload)
                self.delivered_in+=1
        except (OSError,ValueError,GearthBridgeError):
            if not self.stop.is_set():
                self.status("G-Earth gameplay observation path disconnected")
                self.close()

    def close(self):
        self.stop.set()
        self.ready=False
        for field in ("front","upstream","listener"):
            sock=getattr(self,field)
            setattr(self,field,None)
            if sock is not None:
                try:sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
                try:sock.close()
                except OSError:pass
        # The authenticated socket must never revert to direct gameplay
        # simply because the local interception path disappeared.
        session=self.session
        if session is not None and session.authenticated and not session.stop.is_set():
            threading.Thread(target=session.close,daemon=True).start()
