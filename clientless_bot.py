# -*- coding: utf-8 -*-
"""Constrained clientless AIR actions adapted from publicly documented Habbo packets.

Based on protocol structures described by devlyresh/Habbo-Bot (Apache-2.0),
without importing its old authentication code, static packet header table,
proxy handling, auto-spam logic, or direct dependency on third-party packages.

No credentials, generic arbitrary packets, and no automatic mass-bot operation.
Mappings are learned explicitly from the G-Earth AIR extension and tied to one
client release; game-server authentication still belongs to habbo_tcp.py.
"""
from __future__ import annotations

import re
import struct

OUTGOING_ACTION_NAMES = (
    "GetGuestRoom", "Quit", "MoveAvatar", "LookTo", "Chat",
    "Shout", "Whisper", "Dance", "Sign", "ChangePosture",
)
INCOMING_OBSERVED_NAMES = ("Chat", "Shout", "Whisper", "RoomReady")
_ALLOWED_INTS = {
    "dance": (0, 4), "sign": (0, 14), "posture": (0, 1),
    "x": (0, 1023), "y": (0, 1023), "room": (1, 2147483647),
}
_RELEASE_PATTERN = re.compile(r"^WIN63-[0-9]{12}-[0-9]{5,}$")
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


class ClientlessBotError(ValueError):
    """A prohibited or unverified action; never send a guessed packet."""


# Source-pinned November 7, 2026 AIR package 38 mappings.
# plus-emulator/Volt-Renderer commit c8f74ffdd9c3eeb27a532a705e09b665b76e67a1:
# OutgoingHeader.ts and IncomingHeader.ts (ClientHello BUILD matches below).
# These IDs are a COMPATIBILITY BASELINE, not live proof of Habbo.com's
# current release. Never apply them to another WIN63 build, and never guess.
BUNDLED_AIR_RELEASE = "WIN63-202611041140-327405090"
BUNDLED_AIR_HEADERS = {
    "release": BUNDLED_AIR_RELEASE,
    "outgoing": {
        "GetGuestRoom": 216, "MoveAvatar": 2995, "LookTo": 2574,
        "Chat": 3463, "Shout": 3079, "Whisper": 3523,
        "Dance": 1366, "Sign": 207, "ChangePosture": 1117,
        # No verified Quit header in the pinned source: leave it unavailable.
    },
    "incoming": {
        "Chat": 3477, "Shout": 1206, "Whisper": 2229,
        "RoomReady": 2833,  # IncomingHeader.ROOM_ENTER; entry signal, not proof of loading.
    },
}


def bundled_air_headers(release):
    """Return a fresh, release-bound mapping without G-Earth or HabboAIR.

    Unknown/rotated releases fail closed. The caller must not downgrade a
    session's release just to satisfy this map.
    """
    if release != BUNDLED_AIR_RELEASE:
        raise ClientlessBotError(
            "No bundled AIR mapping for this release; import matching "
            "named headers before using clientless actions.")
    return validate_clientless_headers(BUNDLED_AIR_HEADERS, release)


def _int_arg(value, key):
    low, high = _ALLOWED_INTS[key]
    if type(value) is not int or not low <= value <= high:
        raise ClientlessBotError(f"{key} must be an integer from {low} to {high}.")
    return value


def _text_arg(value, maximum=160):
    if (not isinstance(value, str) or not value.strip()
        or len(value) > maximum or any(c in "\x00\r\n" for c in value)):
        raise ClientlessBotError(f"Enter 1–{maximum} characters without newlines.")
    return value.strip()


def _packet_string(value):
    encoded = value.encode("utf-8")
    if len(encoded) > 65535:
        raise ClientlessBotError("Packet text is too long.")
    return struct.pack(">H", len(encoded)) + encoded


def _integer(value):
    return struct.pack(">i", value)


def build_clientless_action(action, **kwargs):
    """Construct a bounded, named sequence for one user-initiated action.

    Return (G-Earth message name, binary payload) tuples. Header resolution
    happens separately and must match the session's AIR release. Never take
    the message name or integer packet header from arbitrary user text.
    """
    if action == "Join room":
        room = _int_arg(kwargs.get("room"), "room")
        # Source bot uses two requests, first inspecting the room then entering.
        return (
            ("GetGuestRoom", _integer(room)+_integer(0)+_integer(1)),
            ("GetGuestRoom", _integer(room)+_integer(1)+_integer(0)),
        )
    if action == "Leave room":
        return (("Quit", b""),)
    if action in ("Walk", "Face tile"):
        x = _int_arg(kwargs.get("x"), "x")
        y = _int_arg(kwargs.get("y"), "y")
        return ((("MoveAvatar" if action=="Walk" else "LookTo"),
                 _integer(x)+_integer(y)),)
    if action == "Say":
        text = _text_arg(kwargs.get("text"))
        # WIN63 AIR ChatMessageComposer returns [text, styleId, trackingId].
        # The client constructor defaults the tracking ID to -1. Omitting
        # this third field causes an incomplete chat body on the wire.
        return (("Chat", _packet_string(text)+_integer(0)+_integer(-1)),)
    if action == "Shout":
        text = _text_arg(kwargs.get("text"))
        # ShoutMessageComposer is only [text, styleId]; do not add an int.
        return (("Shout", _packet_string(text)+_integer(0)),)
    if action == "Whisper":
        recipient = kwargs.get("recipient")
        if (not isinstance(recipient, str)
            or not _USERNAME_PATTERN.fullmatch(recipient)):
            raise ClientlessBotError("Enter a valid Habbo recipient username.")
        text = _text_arg(kwargs.get("text"), 128)
        return (("Whisper", _packet_string(recipient+" "+text)+_integer(0)),)
    if action == "Dance":
        return (("Dance", _integer(_int_arg(kwargs.get("dance"), "dance"))),)
    if action == "Sign":
        return (("Sign", _integer(_int_arg(kwargs.get("sign"), "sign"))),)
    if action == "Posture":
        return (("ChangePosture",
                 _integer(_int_arg(kwargs.get("posture"), "posture"))),)
    raise ClientlessBotError("Unsupported clientless action.")


def _known_header_entries(entries, names):
    """Only accept *unambiguous* G-Earth Name -> integer header pairs."""
    allowed = {name.casefold():name for name in names}
    found = {}
    ambiguous = set()
    if not isinstance(entries, dict):
        return {}
    for packet_id, records in entries.items():
        if type(packet_id) is not int or not 1 <= packet_id <= 65535:
            continue
        if not isinstance(records, (tuple, list)):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            label = record.get("Name")
            normalized = allowed.get(label.casefold()) if isinstance(label, str) else None
            if normalized:
                if normalized in found and found[normalized] != packet_id:
                    ambiguous.add(normalized)
                found[normalized] = packet_id
    for name in ambiguous:
        del found[name]
    return found


def capture_clientless_headers(outgoing_entries, incoming_entries, release):
    """Whitelist metadata-only mappings from a currently running AIR client."""
    if not isinstance(release, str) or not _RELEASE_PATTERN.fullmatch(release):
        raise ClientlessBotError("Verified WIN63 release identifier required.")
    out = _known_header_entries(outgoing_entries, OUTGOING_ACTION_NAMES)
    inc = _known_header_entries(incoming_entries, INCOMING_OBSERVED_NAMES)
    if not out:
        raise ClientlessBotError("G-Earth has no mapped clientless action headers.")
    return {"release": release, "outgoing": out, "incoming": inc}


def validate_clientless_headers(mapping, release):
    """Reject release mismatch, tampering, duplicates and unknown message names."""
    if (not isinstance(mapping, dict) or not isinstance(release, str)
        or not _RELEASE_PATTERN.fullmatch(release)
        or mapping.get("release") != release):
        raise ClientlessBotError("Packet mapping missing or from a different AIR release.")
    result = {"release": release}
    for key, names in (("outgoing",OUTGOING_ACTION_NAMES),
                       ("incoming",INCOMING_OBSERVED_NAMES)):
        raw = mapping.get(key, {})
        if not isinstance(raw, dict):
            raise ClientlessBotError("Invalid packet mapping.")
        if any(name not in names for name in raw):
            raise ClientlessBotError("Unrecognized packet mapping entry.")
        seen = set()
        result[key] = {}
        for name, number in raw.items():
            if type(number) is not int or not 1 <= number <= 65535 or number in seen:
                raise ClientlessBotError("Invalid or duplicate packet header.")
            seen.add(number)
            result[key][name] = number
    return result


def encode_clientless_action(mapping, release, action, **kwargs):
    """Fail entirely before sending if any required header is missing."""
    validated = (bundled_air_headers(release) if mapping is None
                 else validate_clientless_headers(mapping, release))
    actions = build_clientless_action(action, **kwargs)
    result = []
    for name, body in actions:
        packet_id = validated["outgoing"].get(name)
        if packet_id is None:
            raise ClientlessBotError(
                f"G-Earth mapping is missing {name}. Capture matching AIR headers first.")
        result.append((packet_id, body, name))
    return tuple(result)


def decode_clientless_chat(mapping, release, packet_id, payload):
    """Best-effort text-only room chat prefix; no user identity inference.

    AIR message structure starts with a 32-bit room index and UTF-8 string.
    Other fields are deliberately ignored; this does not replace the original
    AIR bubble feed and is never persisted by the clientless module.
    """
    headers = (bundled_air_headers(release) if mapping is None
               else validate_clientless_headers(mapping, release))["incoming"]
    name = next((k for k in ("Chat","Shout","Whisper")
                 if headers.get(k) == packet_id), None)
    if name is None or not isinstance(payload, bytes) or not 6 <= len(payload) <= 8192:
        return None
    index, length = struct.unpack_from(">iH", payload, 0)
    if not 0 <= index <= 100000 or not 1 <= length <= 2048 or len(payload) < 6+length:
        return None
    try:
        body = payload[6:6+length].decode("utf-8")
    except UnicodeError:
        return None
    if any(char in "\x00\r" for char in body):
        return None
    return name,index,body


# Source-pinned, read-only room/position observations from the same WIN63
# package-38 build as BUNDLED_AIR_HEADERS. No guessed headers for other builds.
# IncomingHeader: ROOM_ENTER=2833, UNIT=3357, UNIT_STATUS=996, USER_INFO=1168.
# Parser layouts: RoomEnterParser, RoomUnitParser, RoomUnitStatusParser,
# UserInfoDataParser in plus-emulator/Volt-Renderer at commit c8f74ffd.
_ROOM_ENTER=2833
_ROOM_UNITS=3357
_UNIT_STATUS=996
_USER_INFO=1168


def clientless_walk_positions(primary, backups=""):
    """Validate one primary X,Y and up to three ordered fallback positions.

    An empty primary disables the preset; never invent 0,0 as a destination.
    """
    if not isinstance(primary, str) or not isinstance(backups, str):
        raise ClientlessBotError("Walk coordinates must be text.")
    if not primary.strip():
        if backups.strip():
            raise ClientlessBotError("Set the primary X,Y before backups.")
        return ()
    raw=[primary.strip()]
    if backups.strip():
        raw.extend(s.strip() for s in backups.split(";"))
    if len(raw)>4 or any(not s for s in raw):
        raise ClientlessBotError("Use a primary and at most three backups separated by semicolons.")
    points=[]
    for item in raw:
        match=re.fullmatch(r"([0-9]{1,4})\s*,\s*([0-9]{1,4})",item)
        if not match:
            raise ClientlessBotError("Each position must be X,Y, e.g. 10,15.")
        x,y=int(match[1]),int(match[2])
        _int_arg(x,"x")
        _int_arg(y,"y")
        if (x,y) in points:
            raise ClientlessBotError("Primary and backup positions must be different.")
        points.append((x,y))
    return tuple(points)


def _walk_int(payload,offset):
    if offset+4>len(payload):
        raise ValueError("Truncated room integer.")
    return struct.unpack_from(">i",payload,offset)[0],offset+4


def _walk_short(payload,offset):
    if offset+2>len(payload):
        raise ValueError("Truncated room short.")
    return struct.unpack_from(">H",payload,offset)[0],offset+2


def _walk_string(payload,offset):
    size,offset=_walk_short(payload,offset)
    if size>2048 or offset+size>len(payload):
        raise ValueError("Truncated/oversize room string.")
    return payload[offset:offset+size].decode("utf-8"),offset+size


def _walk_byte(payload,offset):
    if offset>=len(payload):
        raise ValueError("Truncated room flag.")
    return payload[offset],offset+1


def _walk_user_roster(payload):
    """Parse bounded AIR Users, returning *only numeric* user -> room indexes.

    Names, figures and other personal profile metadata are discarded.
    Reject partially decoded data instead of attributing another user's
    position to the selected account.
    """
    count,at=_walk_int(payload,0)
    if not 0<=count<=200:
        raise ValueError("Invalid room roster count.")
    users={}
    for _ in range(count):
        user_id,at=_walk_int(payload,at)
        _,at=_walk_string(payload,at) # username (not retained)
        _,at=_walk_string(payload,at) # custom
        _,at=_walk_string(payload,at) # figure
        room_index,at=_walk_int(payload,at)
        x,at=_walk_int(payload,at)
        y,at=_walk_int(payload,at)
        _,at=_walk_string(payload,at) # z
        _,at=_walk_int(payload,at) # direction
        unit_type,at=_walk_int(payload,at)
        if unit_type==1:  # Habbo player
            _,at=_walk_string(payload,at) # gender
            _,at=_walk_int(payload,at) # group id
            _,at=_walk_int(payload,at) # group status
            _,at=_walk_string(payload,at) # group name
            _,at=_walk_string(payload,at) # swim figure
            _,at=_walk_int(payload,at) # activity
            _,at=_walk_byte(payload,at) # is moderator
            _,at=_walk_int(payload,at) # badge rank
            if user_id>0 and 0<=room_index<=100000 and 0<=x<=1023 and 0<=y<=1023:
                users[user_id]=(room_index,x,y)
        elif unit_type==2: # Pet
            _,at=_walk_int(payload,at) # subtype
            _,at=_walk_int(payload,at) # owner
            _,at=_walk_string(payload,at)
            _,at=_walk_int(payload,at) # rarity
            for _ in range(6):
                _,at=_walk_byte(payload,at)
            _,at=_walk_int(payload,at)
            _,at=_walk_string(payload,at)
        elif unit_type==3: # Bot
            pass
        elif unit_type==4: # Rentable bot
            _,at=_walk_string(payload,at)
            _,at=_walk_int(payload,at)
            _,at=_walk_string(payload,at)
            skills,at=_walk_int(payload,at)
            if not 0<=skills<=64:
                raise ValueError("Invalid bot skill count.")
            for _ in range(skills):
                _,at=_walk_short(payload,at)
        else:
            raise ValueError("Unknown user type.")
    if at!=len(payload):
        raise ValueError("Unexpected room roster tail.")
    return users


def _walk_statuses(payload):
    count,at=_walk_int(payload,0)
    if not 0<=count<=200:
        raise ValueError("Invalid status count.")
    records=[]
    for _ in range(count):
        index,at=_walk_int(payload,at)
        x,at=_walk_int(payload,at)
        y,at=_walk_int(payload,at)
        _,at=_walk_string(payload,at) # z
        for _ in range(3):
            _,at=_walk_int(payload,at)
        actions,at=_walk_string(payload,at)
        target=None
        match=re.search(r"(?:^|/)mv\s+(\d+),(\d+),",actions)
        if match:
            tx,ty=int(match[1]),int(match[2])
            if 0<=tx<=1023 and 0<=ty<=1023:
                target=(tx,ty)
        if 0<=index<=100000 and 0<=x<=1023 and 0<=y<=1023:
            records.append((index,x,y,target))
    if at!=len(payload):
        raise ValueError("Unexpected status data.")
    return tuple(records)


def decode_clientless_room_observation(release, packet_id, payload):
    """Read-only, source-pinned room signals; None means unverified.

    Returns ('ready', room id), ('identity', user id), ('users', numeric
    index map), or ('status', numeric status tuple). No text/credentials.
    """
    if (release!=BUNDLED_AIR_RELEASE
        or type(packet_id) is not int
        or not isinstance(payload,bytes) or not 4<=len(payload)<=16384):
        return None
    try:
        if packet_id==_ROOM_ENTER:
            if len(payload)!=4:
                return None
            room,at=_walk_int(payload,0)
            return ("ready",room) if 0<room<=2147483647 else None
        if packet_id==_USER_INFO:
            user_id,at=_walk_int(payload,0)
            name,at=_walk_string(payload,at)
            return ("identity",user_id) if user_id>0 and 0<len(name)<=32 else None
        if packet_id==_ROOM_UNITS:
            return ("users",_walk_user_roster(payload))
        if packet_id==_UNIT_STATUS:
            return ("status",_walk_statuses(payload))
    except (ValueError,UnicodeError,struct.error,OverflowError):
        return None
    return None
