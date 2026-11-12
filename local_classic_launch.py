# -*- coding: utf-8 -*-
"""Local-only launch of an existing official Habbo Classic AIR executable.

This module has no web requests, downloader, browser control, Bobba integration
or external endpoint. A valid SSO ticket must be supplied by the user.
Ticket values are intentionally never logged or persisted by this module.

The Habbo.exe process itself will need to contact Habbo's official servers
for real gameplay. A started process is NOT proof of successful authentication.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, urlsplit


_SERVER = "hhus"  # Only the user's official Habbo.com hotel.
_TICKET_RE = re.compile(
    r"^(?P<code>[A-Za-z0-9-]{8,160})\.(?P<version>V[1-9][0-9]?)"
    r"(?:\.(?P<username>[A-Za-z0-9_:\-]{1,40}))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClassicTicket:
    """Ephemeral ticket. Do NOT serialize, repr, print or add to settings."""
    server_id: str
    secret: str
    username: str | None = None

    def __repr__(self):
        return (f"ClassicTicket(server_id={self.server_id!r}, "
                f"secret=<redacted>, username={self.username!r})")


def parse_classic_ticket(raw: str) -> ClassicTicket:
    """Parse only supported official habbo.com hotel launch-ticket formats.

    Accepts hhus.<opaque>.V4[.username] or
    habbo://hab?server=hhus&token=<opaque>.V4[.username].
    Does not obtain, verify or renew an SSO token.
    """
    if not isinstance(raw, str) or not 1 <= len(raw) <= 400:
        raise ValueError("Paste a valid Habbo.com launch ticket")
    raw = raw.strip()
    if any(ord(ch) < 32 or ord(ch) > 126 for ch in raw):
        raise ValueError("Unsupported characters in launch ticket")
    if raw.lower().startswith("habbo://"):
        parsed = urlsplit(raw)
        if (parsed.scheme.lower() != "habbo" or parsed.netloc.lower() != "hab"
            or parsed.fragment or parsed.username or parsed.password):
            raise ValueError("Unsupported Habbo launch link")
        q = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        if set(q) != {"server", "token"} or any(len(v) != 1 for v in q.values()):
            raise ValueError("Launch link must contain one server and token")
        if q["server"][0].lower() != _SERVER:
            raise ValueError("Only official Habbo.com (hhus) tickets are supported")
        body = q["token"][0]
    else:
        parts = raw.split(".", 1)
        if len(parts) != 2 or parts[0].lower() != _SERVER:
            raise ValueError("Use an official Habbo.com hhus ticket")
        body = parts[1]
    match = _TICKET_RE.fullmatch(body)
    if not match:
        raise ValueError("Ticket format unrecognised or incomplete")
    return ClassicTicket(
        server_id=_SERVER,
        secret=match.group("code") + "." + match.group("version").upper(),
        username=match.group("username"),
    )


def official_local_executable(path: str | Path) -> Path:
    """Only launch a user-selected local Habbo.exe; never download anything."""
    if not isinstance(path, (Path, str)):
        raise ValueError("Choose an existing local Habbo.exe")
    try:
        exe = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("The selected Habbo.exe does not exist") from exc
    if not exe.is_file() or exe.name.casefold() != "habbo.exe":
        raise ValueError("Select an existing local Habbo.exe file")
    return exe


def launch_local_classic(executable: str | Path, ticket: ClassicTicket) -> int:
    """Start a separate local AIR process with the caller's valid SSO ticket.

    On Windows the opaque token is passed via native process argv, as required
    by Classic. Other local processes with suitable privileges may inspect
    argv: never print or persist it, and don't reuse a ticket unnecessarily.
    """
    if os.name != "nt":
        raise OSError("Direct Classic launch is currently Windows-only")
    if not isinstance(ticket, ClassicTicket) or ticket.server_id != _SERVER:
        raise ValueError("Only official Habbo.com tickets are supported")
    exe = official_local_executable(executable)
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    process = subprocess.Popen(
        [str(exe), "-server", ticket.server_id, "-ticket", ticket.secret],
        cwd=str(exe.parent), creationflags=flags,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return int(process.pid)
