# -*- coding: utf-8 -*-
"""Isolated headless session transport for a controlled LOCAL TEST server.

This module is NOT the official Habbo wire protocol or an authentication API.
No Habbo.com host, client ticket, or website credentials are used. It provides
the session isolation and authenticated socket lifecycle needed to prototype a
future provider-specific adapter without opening a browser or game window.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hmac
import json
import secrets
import socket
import struct
import threading

HOST = "127.0.0.1"
MAGIC = b"HCT1"
MAX_BODY = 8192
MAX_ACCOUNTS = 16
_ID_CHARS = frozenset("0123456789abcdef")


class ProtocolError(Exception):
    """A local test server returned an unexpected message."""


def validate_account_id(value):
    if not isinstance(value, str) or len(value) != 12 or any(
        char not in _ID_CHARS for char in value
    ):
        raise ValueError("Invalid opaque account profile identifier")
    return value


def encode_message(kind, **data):
    if not isinstance(kind, str) or not kind.isupper() or len(kind) > 25:
        raise ValueError("Invalid local test message type")
    body = json.dumps({"kind": kind, **data},
                      ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if not 0 < len(body) <= MAX_BODY:
        raise ValueError("Local test message exceeds the limit")
    return MAGIC + struct.pack("!I", len(body)) + body


def recv_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        block = sock.recv(size - len(data))
        if not block:
            raise ConnectionError("Local test socket closed")
        data.extend(block)
    return bytes(data)


def read_message(sock):
    header = recv_exact(sock, 8)
    if header[:4] != MAGIC:
        raise ProtocolError("Not a Companion local-test connection")
    size, = struct.unpack("!I", header[4:])
    if size < 2 or size > MAX_BODY:
        raise ProtocolError("Invalid local-test frame length")
    try:
        obj = json.loads(recv_exact(sock, size).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Malformed local-test message") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("kind"), str):
        raise ProtocolError("Invalid local-test payload")
    return obj


class LocalHeadlessTestServer:
    """Loopback-only fake server with separate, one-use account tickets.

    It deliberately refuses non-loopback listening addresses. Its tickets are
    randomly generated IN MEMORY; never copied from the actual Habbo website.
    """
    def __init__(self, account_ids, host=HOST):
        if host != HOST:
            raise ValueError("Test server must bind only to 127.0.0.1")
        accounts = tuple(account_ids)
        if not accounts or len(accounts) > MAX_ACCOUNTS or len(set(accounts)) != len(accounts):
            raise ValueError("Provide 1–16 distinct test profiles")
        self.tickets = {validate_account_id(a): secrets.token_urlsafe(32)
                        for a in accounts}
        self.host = HOST
        self.port = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._listener = None
        self._connections = {}
        self._threads = []

    def start(self):
        if self._listener is not None:
            raise RuntimeError("Local test server already started")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((HOST, 0))
            sock.listen(MAX_ACCOUNTS)
            sock.settimeout(0.3)
        except Exception:
            sock.close()
            raise
        self.port = sock.getsockname()[1]
        self._listener = sock
        thread = threading.Thread(target=self._accept_loop, daemon=True,
                                  name="headless-test-listener")
        thread.start()
        self._threads.append(thread)
        return self.port

    @property
    def authenticated_ids(self):
        with self._lock:
            return frozenset(self._connections)

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, address = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if address[0] != HOST:
                conn.close()
                continue
            thread = threading.Thread(target=self._handle, args=(conn,),
                                      daemon=True, name="headless-test-account")
            self._threads.append(thread)
            thread.start()

    def _handle(self, conn):
        assigned = None
        try:
            conn.settimeout(3)
            msg = read_message(conn)
            if msg.get("kind") != "AUTH":
                conn.sendall(encode_message("ERROR", reason="auth_required"))
                return
            account_id = validate_account_id(msg.get("account_id"))
            ticket = msg.get("ticket")
            with self._lock:
                expected = self.tickets.get(account_id)
                allowed = (
                    isinstance(ticket, str) and expected is not None
                    and hmac.compare_digest(ticket, expected)
                    and account_id not in self._connections
                )
                if allowed:
                    self._connections[account_id] = conn
                    # One use per profile per test server instance.
                    del self.tickets[account_id]
            if not allowed:
                conn.sendall(encode_message("ERROR", reason="invalid_test_ticket"))
                return
            assigned = account_id
            conn.sendall(encode_message("AUTH_OK", account_id=account_id,
                                        scope="local-test"))
            while not self._stop.is_set():
                msg = read_message(conn)
                if msg.get("kind") == "PING":
                    nonce = msg.get("nonce")
                    if not isinstance(nonce, str) or len(nonce) > 80:
                        raise ProtocolError("Invalid ping nonce")
                    conn.sendall(encode_message("PONG", account_id=assigned,
                                                nonce=nonce))
                elif msg.get("kind") == "CLOSE":
                    break
                else:
                    conn.sendall(encode_message("ERROR", reason="unsupported_test_message"))
        except (OSError, ValueError, ConnectionError, ProtocolError):
            pass
        finally:
            with self._lock:
                if assigned is not None and self._connections.get(assigned) is conn:
                    del self._connections[assigned]
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()

    def stop(self):
        self._stop.set()
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
            self.tickets.clear()
        for conn in connections:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()


class HeadlessLocalSession:
    """One socket per profile. Does not send a packet to Habbo.com."""
    def __init__(self, account_id):
        self.account_id = validate_account_id(account_id)
        self._sock = None
        self._lock = threading.RLock()
        self.status = "Disconnected"

    def connect(self, host, port, test_ticket):
        if host != HOST or not isinstance(port, int) or not 1024 <= port <= 65535:
            raise ValueError("Only a local test server is supported")
        if not isinstance(test_ticket, str) or not test_ticket:
            raise ValueError("A local test ticket is required")
        with self._lock:
            if self._sock is not None:
                raise RuntimeError("This profile already has a test connection")
            sock = socket.create_connection((HOST, port), timeout=3)
            sock.settimeout(3)
            try:
                sock.sendall(encode_message(
                    "AUTH", account_id=self.account_id, ticket=test_ticket))
                reply = read_message(sock)
                if (reply.get("kind") != "AUTH_OK"
                    or reply.get("account_id") != self.account_id
                    or reply.get("scope") != "local-test"):
                    raise ProtocolError("Local test account authentication failed")
            except BaseException:
                sock.close()
                self.status = "Test connection failed"
                raise
            self._sock = sock
            self.status = "Local test authenticated"

    def ping(self):
        with self._lock:
            if self._sock is None:
                raise ConnectionError("Account test session is disconnected")
            nonce = secrets.token_hex(10)
            try:
                self._sock.sendall(encode_message("PING", nonce=nonce))
                reply = read_message(self._sock)
                if (reply.get("kind") != "PONG"
                    or reply.get("nonce") != nonce
                    or reply.get("account_id") != self.account_id):
                    raise ProtocolError("Local test reply belonged to another account")
                return True
            except (OSError, ConnectionError, ProtocolError):
                self.status = "Test connection lost"
                raise

    def close(self):
        with self._lock:
            sock, self._sock = self._sock, None
            self.status = "Disconnected"
            if sock is not None:
                try:
                    sock.sendall(encode_message("CLOSE"))
                except OSError:
                    pass
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()


class HeadlessLocalManager:
    def __init__(self):
        self.sessions = {}
        self._lock = threading.RLock()

    def connect_all(self, server, account_ids):
        accounts = tuple(validate_account_id(a) for a in account_ids)
        if not accounts or len(accounts) > MAX_ACCOUNTS or len(set(accounts)) != len(accounts):
            raise ValueError("Provide 1–16 distinct test profiles")
        if server.port is None:
            raise RuntimeError("Start the local test server before connecting")
        def start(account_id):
            with self._lock:
                existing = self.sessions.get(account_id)
            if existing is not None:
                try:
                    existing.ping()
                    return "Local test authenticated / ping OK"
                except (OSError, ConnectionError, ProtocolError):
                    # A one-use local test ticket cannot be silently replayed.
                    # Users can explicitly reset the test server to reconnect.
                    return "Local test socket lost; reset test server"
            client = HeadlessLocalSession(account_id)
            try:
                client.connect(HOST, server.port, server.tickets[account_id])
                if not client.ping():
                    raise ProtocolError("Local test ping failed")
                with self._lock:
                    self.sessions[account_id] = client
                return "Local test authenticated / ping OK"
            except (OSError, ValueError, RuntimeError, KeyError,
                    ConnectionError, ProtocolError) as exc:
                client.close()
                return "Local test failed: " + type(exc).__name__
        with ThreadPoolExecutor(max_workers=min(len(accounts), 8)) as executor:
            futures = {executor.submit(start, a): a for a in accounts}
            return {futures[f]: f.result() for f in as_completed(futures)}

    def ping_all(self):
        with self._lock:
            entries = list(self.sessions.items())
        results = {}
        for account_id, session in entries:
            try:
                session.ping()
                results[account_id] = "Local test authenticated / ping OK"
            except (OSError, ConnectionError, ProtocolError):
                results[account_id] = "Local test connection lost"
        return results

    def disconnect_all(self):
        with self._lock:
            entries = list(self.sessions.values())
            self.sessions.clear()
        for client in entries:
            client.close()
