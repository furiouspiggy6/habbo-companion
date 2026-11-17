# -*- coding: utf-8 -*-
"""Experimental, real Habbo.com AIR TCP transport (no game executable).

Requires a real SSO ticket issued by Habbo.com. There is deliberately no
password endpoint, captcha bypass, proxy rotation or fabricated authentication.
Packet IDs and crypto parameters are version-specific and may change.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import socket
import struct
import threading
import time
import urllib.error
import urllib.request

TCP_HOST = "game-us.habbo.com"
TCP_PORT = 30000
TCP_SITE = "https://www.habbo.com"
TCP_CLIENT_DATA = TCP_SITE + "/gamedata/external_variables"
TCP_SSO_URL = TCP_SITE + "/api/client/clientnative/url"
# Last verified public AIR build identifier (HabboAirPlus, 2026-11-04).
# This is a compatibility baseline, NOT proof of the server's latest release.
TCP_FALLBACK_RELEASE = "WIN63-202611041140-327405090"
TCP_MAX_FRAME = 1_048_576
TCP_RSA_N = int(
    "C5DFF029848CD5CF4A84ADEFB2DA6685704920D5EBE8850B82C419A97B95302DE3B8021F37719FEBD4B3516E04D1E4702E74C468C9FF4BBBB5DD44A1E3A08687EDBEF7C30A176F7C8C83226A77F7982F7442D884D8149E924C486F43035C07B9167EA998416919DA4116D5E0598C11BA1542B4160136F04135C06EDF80170245E73C0DAD63895F52DCED3735582C5852744C8EC40AF576F26A9C8DC5B64ED3DAD40EFAAC6A76A1F5C2A422A8A4691F8991356467BDA61E1D34D0F35531058C8F741E4661ACFCB15C806A996AC312A8D33BF45079B89E11787537B37364749B883BDBFDE51A1A55086CF16159F5DEBCC76342AC2EF6950DA0C70C5845C97DFD49", 16
)
TCP_RSA_E = 65537

# Explicitly sourced from the AIR client's HabboMessages.as packet registry
# (habbo-cc/Habbo-Sky feature-air). These headers supersede unverified
# numbers copied from a bot, but 2026 live compatibility is still unproven.
# Do not reinterpret unrelated headers as ban/disconnect messages.
TCP_OUT = dict(hello=4000, init_dh=3110, finish_dh=773, version=1053,
               unique=2490, sso=2419, info=357, pong=2596, latency=295)
TCP_IN = dict(init_dh=1347, finish_dh=3885, auth_ok=2491,
              ping=3928, disconnect=4000)
_TICKET = re.compile(r"^[A-Za-z0-9-]{8,160}\.V[1-9][0-9]?$", re.I)
_RELEASE = re.compile(r"\bWIN63-[0-9]{12}-[0-9]{5,}\b")


class HabboTcpError(Exception):
    """A valid TCP connection does not imply game authentication."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _official_request(url, method="GET", headers=None, timeout=10):
    if url not in (TCP_CLIENT_DATA, TCP_SSO_URL):
        raise ValueError("Only official Habbo.com endpoints are supported")
    request = urllib.request.Request(url, method=method, headers=headers or {})
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(request, timeout=timeout) as response:
        if response.geturl() != url:
            raise HabboTcpError("Unexpected redirect from Habbo.com")
        body = response.read(65537)
    if len(body) > 65536:
        raise HabboTcpError("Habbo.com response too large")
    return body


def fetch_habbo_sso_ticket(session_id, browser_token):
    """Use supplied EXISTING authenticated session cookies; no browser process.

    The caller must not log, save in settings, or expose these cookie values.
    Session expiry, MFA and Habbo anti-abuse checks are never bypassed.
    """
    for value in (session_id, browser_token):
        if (not isinstance(value, str) or not 1 <= len(value) <= 900
            or any(ord(c) < 33 or ord(c) > 126 or c in ";,\r\n" for c in value)):
            raise ValueError("Provide valid Habbo session.id and browser_token values")
    try:
        data = _official_request(TCP_SSO_URL, method="POST", headers={
            "Accept": "application/json",
            "Origin": TCP_SITE,
            "Referer": TCP_SITE + "/",
            "Cookie": "session.id=" + session_id + "; browser_token=" + browser_token,
        })
        decoded = json.loads(data)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HabboTcpError("Habbo rejected the website session (401/403)") from None
        raise HabboTcpError("Habbo ticket endpoint returned HTTP " + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError, ValueError, UnicodeError) as exc:
        raise HabboTcpError("Official Habbo ticket request failed: " + type(exc).__name__) from None
    if not isinstance(decoded, dict):
        raise HabboTcpError("Official Habbo ticket response was not JSON object")
    candidate = decoded.get("ticket")
    if not isinstance(candidate, str) or not 8 < len(candidate) < 400:
        raise HabboTcpError("Habbo returned no recognised SSO ticket")
    return candidate


def official_release():
    """Try live public game data; return (release, was_currently_verified)."""
    try:
        source = _official_request(TCP_CLIENT_DATA).decode("utf-8")
        match = _RELEASE.search(source)
        if match:
            return match.group(), True
    except (OSError, UnicodeError, HabboTcpError):
        pass
    return TCP_FALLBACK_RELEASE, False


def _string(value):
    if not isinstance(value, str):
        raise TypeError("Expected string")
    encoded = value.encode("utf-8")
    if len(encoded) > 65535:
        raise ValueError("Packet string too long")
    return struct.pack(">H", len(encoded)) + encoded


def _decode_string(payload, offset=0):
    if len(payload) < offset + 2:
        raise HabboTcpError("Truncated packet string")
    length = struct.unpack_from(">H", payload, offset)[0]
    offset += 2
    if len(payload) < offset + length:
        raise HabboTcpError("Truncated packet string body")
    return payload[offset:offset + length].decode("utf-8"), offset + length


def _frame(packet_id, payload=b""):
    body = struct.pack(">H", packet_id) + payload
    if len(body) > TCP_MAX_FRAME:
        raise ValueError("Packet too large")
    return struct.pack(">I", len(body)) + body


def _rsa_decipher_decimal(value):
    """Verify a server-signed legacy PKCS#1 type-01 number."""
    if not isinstance(value, str) or len(value) > 1024:
        raise HabboTcpError("Invalid RSA signed value")
    try:
        integer = int(value, 16)
        if integer < 1 or integer >= TCP_RSA_N:
            raise ValueError("Invalid RSA range")
        size = (TCP_RSA_N.bit_length() + 7) // 8
        raw = pow(integer, TCP_RSA_E, TCP_RSA_N).to_bytes(size, "big")
        if not raw.startswith(b"\x00\x01"):
            raise ValueError("Invalid RSA signature padding")
        marker = raw.index(b"\x00", 2)
        if marker < 10 or any(byte != 0xff for byte in raw[2:marker]):
            raise ValueError("Invalid RSA signature padding")
        plaintext = raw[marker + 1:]
        if not plaintext or not plaintext.isascii():
            raise ValueError("Invalid RSA plaintext")
        number = int(plaintext.decode("ascii"))
        if number <= 0:
            raise ValueError("Invalid key parameter")
        return number
    except (ValueError, OverflowError) as exc:
        raise HabboTcpError("Server RSA key validation failed") from exc


def _rsa_encipher_decimal(integer):
    payload = str(integer).encode("ascii")
    size = (TCP_RSA_N.bit_length() + 7) // 8
    pad_count = size - len(payload) - 3
    if pad_count < 8:
        raise HabboTcpError("Client RSA message too large")
    padding = bytearray()
    while len(padding) < pad_count:
        padding.extend(b for b in secrets.token_bytes(pad_count - len(padding)) if b)
    message = b"\x00\x02" + bytes(padding) + b"\x00" + payload
    return pow(int.from_bytes(message, "big"), TCP_RSA_E, TCP_RSA_N).to_bytes(size, "big").hex()


class _ArcFour:
    """Legacy Habbo AIR RC4 variant: different inbound and outbound PRGA."""
    def __init__(self, key, inbound=False):
        if not key:
            raise ValueError("Empty cipher key")
        self.state = list(range(256))
        j = 0
        for i in range(256):
            j = (j + self.state[i] + key[i % len(key)]) & 255
            self.state[i], self.state[j] = self.state[j], self.state[i]
        self.i = self.j = 0
        self.inbound = inbound

    def apply(self, data):
        result = bytearray(len(data))
        for index, value in enumerate(data):
            self.i = (self.i + 1) & 255
            self.j = (self.j + self.state[self.i]) & 255
            s = self.state
            s[self.i], s[self.j] = s[self.j], s[self.i]
            k = s[(s[self.i] + s[self.j]) & 255]
            if self.inbound:
                k = s[k]
            result[index] = value ^ k
        return bytes(result)


def profile_fingerprint(account_id):
    """Stable, independently scoped AIR-compatible identifier for one profile.

    This is a non-secret device label, not a login credential. Do not use a
    password, session cookie or SSO ticket as its input.
    """
    if not isinstance(account_id, str) or not re.fullmatch("[0-9a-f]{12}", account_id):
        raise ValueError("Invalid account profile")
    return "~" + hashlib.md5(("HabboCompanion:profile:" + account_id).encode("ascii")).hexdigest()


class HabboTcpSession:
    """A per-profile game socket, with independently maintained cipher state."""
    def __init__(self, account_id, status=None, packet=None):
        if not isinstance(account_id, str) or not re.fullmatch("[0-9a-f]{12}", account_id):
            raise ValueError("Invalid account profile")
        self.account_id = account_id
        self.on_status = status or (lambda msg: None)
        self.on_packet = packet or (lambda packet_id, size: None)
        self.sock = None
        self.tx = None
        self.rx = None
        self.authenticated = False
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        # TCP is a byte stream: reads may be fragmented or time out halfway
        # through a packet. Keep partial bytes and the decoded frame length
        # across retries without advancing the stream cipher twice.
        self._recv_pending = bytearray()
        self._frame_size = None

    def _recv(self, amount):
        if not 0 < amount <= TCP_MAX_FRAME:
            raise HabboTcpError("Invalid requested read length")
        while len(self._recv_pending) < amount:
            sock = self.sock
            if sock is None:
                raise HabboTcpError("Game socket is disconnected")
            # Only read the outstanding bytes. This prevents plaintext bytes
            # from being prefetched past the DH -> encrypted framing boundary.
            block = sock.recv(amount - len(self._recv_pending))
            if not block:
                raise HabboTcpError("Game socket closed by server")
            self._recv_pending.extend(block)
        result = bytes(self._recv_pending[:amount])
        del self._recv_pending[:amount]
        return result

    def _read(self):
        if self._frame_size is None:
            header = self._recv(4)
            if self.rx:
                header = self.rx.apply(header)
            size = struct.unpack(">I", header)[0]
            if size < 2 or size > TCP_MAX_FRAME:
                raise HabboTcpError("Invalid game packet frame length")
            self._frame_size = size
        # On socket.timeout, _recv preserves partial bytes and _frame_size
        # remains set, so the next attempt resumes the same frame.
        body = self._recv(self._frame_size)
        self._frame_size = None
        if self.rx:
            body = self.rx.apply(body)
        return struct.unpack_from(">H", body, 0)[0], body[2:]

    def _send(self, packet_id, body=b"", plaintext=False):
        data = _frame(packet_id, body)
        with self.lock:
            sock = self.sock
            if sock is None:
                raise HabboTcpError("Game socket is disconnected")
            if self.tx and not plaintext:
                data = self.tx.apply(data)
            sock.sendall(data)

    def _await_packet(self, wanted, limit=15):
        stage = {
            TCP_IN["init_dh"]: "initial Diffie-Hellman handshake",
            TCP_IN["finish_dh"]: "Diffie-Hellman key confirmation",
            TCP_IN["auth_ok"]: "SSO authentication",
        }.get(wanted, "game-server response")
        deadline = time.monotonic() + limit
        unexpected = []
        while time.monotonic() < deadline:
            self.sock.settimeout(max(0.2, min(3.0, deadline - time.monotonic())))
            try:
                packet_id, payload = self._read()
            except socket.timeout:
                continue
            if packet_id == wanted:
                return payload
            if packet_id == TCP_IN["ping"]:
                self._send(TCP_OUT["pong"])
                continue
            if packet_id == TCP_IN["disconnect"]:
                # Only confirmed disconnect header is interpreted; unknown
                # headers are recorded numerically without payload contents.
                reason = ""
                if len(payload) >= 4:
                    code = struct.unpack_from(">i", payload)[0]
                    reason = " (reason code " + str(code) + ")"
                raise HabboTcpError(
                    "Game server sent disconnect packet " + str(packet_id)
                    + reason + " during " + stage)
            if len(unexpected) < 6:
                unexpected.append(packet_id)
        detail = ""
        if unexpected:
            detail = " (unexpected packet IDs: " + ",".join(map(str,unexpected)) + ")"
        raise HabboTcpError("Timed out during " + stage + detail)

    def connect(self, ticket, release=None, timeout=12):
        if self.sock:
            raise RuntimeError("Profile is already connected")
        if not isinstance(ticket, str) or not _TICKET.fullmatch(ticket):
            raise ValueError("Official Habbo SSO ticket required")
        if release is None:
            release, is_current = official_release()
            if not is_current:
                self.on_status("Official version lookup unavailable; using public 2026-11-04 AIR build (not live-verified)")
        elif not _RELEASE.fullmatch(release):
            raise ValueError("Invalid Habbo client release version")
        self.stop.clear()
        started = time.monotonic()
        try:
            self.sock = socket.create_connection((TCP_HOST, TCP_PORT), timeout=timeout)
            self.sock.settimeout(timeout)
            self.on_status("TCP connected (AIR "+release+"; documented AIR packet IDs); awaiting first DH response")
            self._send(TCP_OUT["hello"], _string(release) + _string("FLASH25")
                       + struct.pack(">ii", 6, 4), plaintext=True)
            self._send(TCP_OUT["init_dh"], plaintext=True)
            init = self._await_packet(TCP_IN["init_dh"], 15)
            signed_p, offset = _decode_string(init)
            signed_g, _ = _decode_string(init, offset)
            p, g = _rsa_decipher_decimal(signed_p), _rsa_decipher_decimal(signed_g)
            if p.bit_length() < 128 or not 1 < g < p:
                raise HabboTcpError("Invalid DH group")
            private = secrets.randbits(120) | (1 << 119)
            public = pow(g, private, p)
            self.on_status("Server DH parameters validated; sending client DH key")
            self._send(TCP_OUT["finish_dh"], _string(_rsa_encipher_decimal(public)),
                       plaintext=True)
            self.on_status("Waiting for server DH key confirmation")
            answer = self._await_packet(TCP_IN["finish_dh"], 15)
            signed_public, offset = _decode_string(answer)
            server_public = _rsa_decipher_decimal(signed_public)
            if not 1 < server_public < p:
                raise HabboTcpError("Invalid DH public key")
            inbound_enabled = bool(answer[offset]) if offset < len(answer) else False
            shared = pow(server_public, private, p)
            key = shared.to_bytes((shared.bit_length() + 7) // 8, "big")
            self.tx = _ArcFour(key)
            self.rx = _ArcFour(key, inbound=True) if inbound_enabled else None
            self.on_status("Encrypted handshake complete; authenticating SSO")
            self._send(TCP_OUT["version"],
                       struct.pack(">i", 401) + _string("app:/") + _string(TCP_CLIENT_DATA))
            fingerprint = profile_fingerprint(self.account_id)
            self._send(TCP_OUT["unique"], _string(fingerprint) + _string("WIN/51,1,1,5"))
            elapsed = int((time.monotonic() - started) * 1000)
            self._send(TCP_OUT["sso"], _string(ticket) + struct.pack(">i", min(elapsed, 2147483647)))
            self._await_packet(TCP_IN["auth_ok"], 18)
            self.authenticated = True
            self.on_status("Authenticated with Habbo.com via direct TCP")
            self._send(TCP_OUT["info"])
            self.sock.settimeout(3)
            self.thread = threading.Thread(target=self._receive_forever, daemon=True,
                                           name="habbo-tcp-" + self.account_id)
            self.thread.start()
        except BaseException:
            self.close()
            raise

    def _receive_forever(self):
        next_ping = time.monotonic() + 15
        try:
            while not self.stop.is_set():
                if time.monotonic() >= next_ping:
                    self._send(TCP_OUT["latency"], struct.pack(">i", secrets.randbelow(2147483647)))
                    next_ping = time.monotonic() + 15
                try:
                    packet_id, body = self._read()
                except socket.timeout:
                    continue
                if packet_id == TCP_IN["ping"]:
                    self._send(TCP_OUT["pong"])
                elif packet_id == TCP_IN["disconnect"]:
                    raise HabboTcpError("Game server disconnected this account")
                self.on_packet(packet_id, len(body))
        except (OSError, HabboTcpError, ValueError):
            if not self.stop.is_set():
                self.on_status("Game connection lost")
        finally:
            self.close()

    def close(self):
        self.stop.set()
        self.authenticated = False
        with self.lock:
            sock, self.sock = self.sock, None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        self.tx = self.rx = None
        # No carryover data/cipher state may survive a disconnected account.
        self._recv_pending.clear()
        self._frame_size = None
