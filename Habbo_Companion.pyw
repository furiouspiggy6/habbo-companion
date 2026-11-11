# -*- coding: utf-8 -*-
"""Habbo View Chat | Standalone Windows overlay and settings panel.

Works with the companion patched HabboAir.swf, which streams incoming chat
messages into the user's local AIR application storage. No networking, input
capture, remote access or gameplay automation. Uses only Python stdlib.
"""
from __future__ import annotations
import ctypes
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
import importlib.util
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font

APP_NAME = 'Habbo View Chat'
APP_DIR = Path(os.environ.get('APPDATA', str(Path.home()))) / 'HabboViewChat'
CONFIG_PATH = APP_DIR / 'settings.json'
FEED_NAME = 'habbo_view_chat.jsonl'
TRANSPARENT = '#ff00fe'

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
    habbo_launcher_path='',
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
    for name in ('Users','RoomReady','UserRemove','ExtendedProfile','CarryObject'):
        if name.casefold() in names or incoming_packet_is(description,name):
            return name
    return None


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



class ChatOverlayApp:
    def __init__(self,root):
        self.root=root;self.root.title('Habbo Companion')
        self.root.geometry('720x900')
        self.root.attributes('-topmost',False)  # behave like a normal app window
        self.root.minsize(540,560)
        self.root.configure(bg='#121a28')
        self.tracker=WinTracker()
        self.config=load_config()
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
        self.coffee_recipient_var=tk.StringVar(value=str(self.config.get('coffee_recipient','68808036')))
        self.coffee_username_var=tk.StringVar(value=str(self.config.get('coffee_username','')))
        self.coffee_users_status_var=tk.StringVar(value='Room users not detected yet. Join a room with G-Earth attached.')
        self._room_users={}
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
        self.coffee_status_var=tk.StringVar(value='Coffee pass loop OFF. Choose a recipient and start manually.')
        self.coffee_delivery_var=tk.StringVar(value='Pass requests sent: 0. No recipient delivery evidence yet.')
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

    def _make_settings(self):
        style=ttk.Style(self.root)
        try:style.theme_use('clam')
        except tk.TclError:pass
        style.configure('Panel.TFrame',background='#121a28')
        style.configure('Panel.TLabel',background='#121a28',foreground='#e1ecf8',font=('Segoe UI',10))
        style.configure('Panel.TCheckbutton',background='#121a28',foreground='#e1ecf8',font=('Segoe UI',10))
        style.configure('Panel.TButton',font=('Segoe UI',9),padding=5)
        style.configure('Panel.TCombobox',font=('Segoe UI',10))
        # One program, one settings window: both features live in tabs.
        self.notebook=ttk.Notebook(self.root)
        self.notebook.pack(fill='both',expand=True)
        outer=ttk.Frame(self.notebook,style='Panel.TFrame')
        self.notebook.add(outer,text='  View Chat  ')
        packets=ttk.Frame(self.notebook,style='Panel.TFrame')
        self.notebook.add(packets,text='  Packet Viewer  ')
        self._make_packet_panel(packets)
        manip=ttk.Frame(self.notebook,style='Panel.TFrame')
        self.notebook.add(manip,text='  Packet Manipulator  ')
        self._make_manipulator_panel(manip)
        updates=ttk.Frame(self.notebook,style='Panel.TFrame')
        self.notebook.add(updates,text='  Updates  ')
        self._make_updates_panel(updates)
        # Scrollable control panel: every setting stays accessible on smaller monitors.
        content=tk.Canvas(outer,bg='#121a28',highlightthickness=0,borderwidth=0)
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
        self.root.bind('<MouseWheel>',scroll_panel)

        tk.Label(f,text='VIEW CHAT',font=('Segoe UI Semibold',19),bg='#121a28',fg='#e6f1ff').pack(anchor='w')
        tk.Label(f,text='Screen-locked chat for your current Habbo view',font=('Segoe UI',9),bg='#121a28',fg='#88a2bc').pack(anchor='w',pady=(0,10))
        lab=ttk.Label(f,textvariable=self.status,style='Panel.TLabel',wraplength=345)
        lab.pack(anchor='w',fill='x',pady=(0,10))
        self._check(f,'Only people inside my view','visible_only')
        self._check(f,'Hide room (ambient background)','show_room',invert=True)
        self._check(f,'Show original Habbo bubbles','bubbles')
        tk.Label(f,text='Original Habbo bubble artwork is always used (no imitation bubbles).',
                 wraplength=352,justify='left',font=('Segoe UI',9),
                 bg='#121a28',fg='#a9c2d8').pack(anchor='w',pady=(3,4))
        self._chat_line_toggle(f)
        self._check(f,'Whispers on the right','whispers_right')
        tk.Label(f,text='Original Habbo bubbles keep their genuine artwork, '
                     'font and wrapping. The one-line switch and Font size '
                     'control only affect text-only messages when Habbo has not '
                     'supplied an original PNG.',
                 wraplength=352,justify='left',font=('Segoe UI',9),
                 bg='#121a28',fg='#88a2bc').pack(anchor='w',pady=(2,4))
        self._check(f,'Keep a local chat log after exit','keep_log')
        self._check(f,'Auto-fill available screen with chat bubbles','auto_fill_screen')
        tk.Label(f,text='The overlay stays above Habbo, but behind other apps. Switching windows does not clear chat.',
                 wraplength=352,justify='left',font=('Segoe UI',9),bg='#121a28',fg='#88a2bc').pack(anchor='w',pady=(2,4))
        tk.Label(f,text='When auto-fill is on, the number of visible bubbles adapts to your screen height. Older messages stay in scrollback.',
                 wraplength=352,justify='left',font=('Segoe UI',9),bg='#121a28',fg='#88a2bc').pack(anchor='w',pady=(2,4))
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
        tk.Label(f,text='Ctrl + Shift + F6  ·  show/hide settings\nCtrl + Shift + F7  ·  toggle room background\nCtrl + Shift + PgUp/PgDn  ·  older/newer chat',font=('Segoe UI',9),justify='left',bg='#121a28',fg='#7f9db7').pack(anchor='w',pady=(13,0))
        tk.Label(f,text='Messages do not expire. Only recent bubbles are drawn; scroll for older.\nHistory is bounded in memory and cleared on exit (unless logging is enabled).\nOriginal artwork comes from your existing modified Habbo client.',font=('Segoe UI',8),justify='left',bg='#121a28',fg='#6f8299').pack(anchor='w',pady=(8,0))

    def _make_updates_panel(self, parent):
        """One-click updates without replacing files by hand."""
        f=ttk.Frame(parent,style='Panel.TFrame',padding=18)
        f.pack(fill='both',expand=True)
        tk.Label(f,text='SOFTWARE UPDATES',font=('Segoe UI Semibold',18),
                 fg='#e6f1ff',bg='#121a28').pack(anchor='w')
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
        ttk.Button(bar,text='Check online',command=self._check_online_update).pack(side='left')
        ttk.Label(f,text='Online updates are inactive until you enter a trusted HTTPS release-manifest URL. Updates are never installed silently.',
                  style='Panel.TLabel',wraplength=510).pack(anchor='w',pady=(0,14))
        ttk.Label(f,textvariable=self.update_status,style='Panel.TLabel',wraplength=510).pack(anchor='w',fill='x',pady=(0,10))
        ttk.Button(f,text='Restore previous version…',command=self._restore_previous_version).pack(anchor='w',pady=(2,8))
        ttk.Button(f,text='Open backups folder',command=self._open_backups).pack(anchor='w',pady=(2,10))
        ttk.Label(f,text='The updater verifies package file hashes and creates a rollback backup. Checksums detect accidental changes, not publisher identity: only install ZIPs you trust.',
                  style='Panel.TLabel',wraplength=510).pack(anchor='w')

    def _save_update_source(self):
        source=self.update_manifest_var.get().strip()
        if source and not source.startswith('https://'):
            messagebox.showerror('Update source','Enter an HTTPS URL, or leave it blank.')
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
                p=urllib.parse.urlsplit(url)
                query=(p.query+'&' if p.query else '')+'check='+uuid.uuid4().hex
                fresh_url=urllib.parse.urlunsplit((p.scheme,p.netloc,p.path,query,p.fragment))
                req=urllib.request.Request(fresh_url,headers={'User-Agent':'HabboCompanionUpdater/1.2','Cache-Control':'no-cache','Pragma':'no-cache'})
                with urllib.request.urlopen(req,timeout=12) as response:
                    if response.geturl().split(':',1)[0]!='https':
                        raise ValueError('Update manifest redirected away from HTTPS')
                    raw=response.read(65_537)
                    if len(raw)>65_536:raise ValueError('Manifest is too large')
                info=json.loads(raw.decode('utf-8'))
                if info.get('app_id')!='habbo-companion':raise ValueError('Not a Habbo Companion update manifest')
                version=str(info['version']);package_url=str(info['package_url'])
                checksum=str(info['sha256']).lower()
                if not package_url.startswith('https://'):raise ValueError('Update package must use HTTPS')
                if not re.fullmatch(r'[a-f0-9]{64}',checksum):raise ValueError('Invalid package checksum')
                helper=self._update_module()
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
                folder=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'HabboCompanion' / 'Downloads'
                folder.mkdir(parents=True,exist_ok=True)
                dest=folder/'latest_habbo_companion_update.zip'
                req=urllib.request.Request(url,headers={'User-Agent':'HabboCompanionUpdater/1.0'})
                with urllib.request.urlopen(req,timeout=25) as response:
                    if response.geturl().split(':',1)[0]!='https':
                        raise ValueError('Update download redirected away from HTTPS')
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
                 fg='#e6f1ff',bg='#121a28').pack(anchor='w')
        tk.Label(holder,text='Use Companion for everything. The working G-Earth engine starts normally '
                 'then hides after its backend is ready. Its original window is troubleshooting only.',
                 fg='#8ea9c1',bg='#121a28',wraplength=630,justify='left').pack(anchor='w',pady=(0,9))
        tk.Label(holder,textvariable=self.engine_status_var,bg='#121a28',fg='#76caab',
                 font=('Segoe UI Semibold',10),wraplength=630,justify='left').pack(anchor='w',pady=(0,9))
        main=ttk.Frame(holder,style='Panel.TFrame')
        main.pack(fill='x',pady=(0,9))
        ttk.Button(main,text='Start engine',command=self._connect_habbo_air).pack(side='left',padx=(0,7))
        ttk.Button(main,text='Launch Habbo',command=self._launch_habbo_with_gearth).pack(side='left',padx=(0,7))
        ttk.Button(main,text='Connect packet tools (manual)',command=self._connect_gearth).pack(side='left')
        tk.Label(holder,text='Packet tools attach automatically when safe. Coffee Pass Loop can '
                 'also connect directly; this manual button is only for troubleshooting.',
                 fg='#93a7bc',bg='#121a28',font=('Segoe UI',9),
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
        tk.Label(adv,textvariable=self.gearth_path_display,bg='#121a28',fg='#8ea9c1',
                 font=('Segoe UI',9),wraplength=610,justify='left').pack(anchor='w',pady=(0,7))
        launcher=ttk.Frame(adv,style='Panel.TFrame');launcher.pack(fill='x',pady=(0,6))
        ttk.Button(launcher,text='Select Habbo launcher',
                   command=self._select_habbo_launcher).pack(side='left',padx=(0,7))
        tk.Label(launcher,textvariable=self.habbo_path_display,bg='#121a28',fg='#8ea9c1',
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
        self.packet_details=tk.Text(holder,height=6,wrap='word',bg='#0a1120',fg='#deedff',
                                    relief='flat',font=('Consolas',9),insertbackground='white')
        self.packet_details.pack(fill='x')
        actions=ttk.Frame(holder,style='Panel.TFrame');actions.pack(fill='x',pady=(8,0))
        ttk.Button(actions,text='Clear viewer',command=self._clear_packets).pack(side='left')
        ttk.Button(actions,text='Export visible packet log…',command=self._export_packets).pack(side='left',padx=(8,0))
        tk.Label(holder,text='Packets are stored only in memory (maximum 500). Nothing is sent anywhere.\n'
                 'G-Earth must prepare BEFORE Habbo begins connecting. On Companion startup, approve the\n'
                 'Windows administrator prompt. Launch Habbo only after G-Earth is waiting.\n'
                 'If Windows accessibility cannot press Connect, G-Earth stays open for manual connection.',
                 bg='#121a28',fg='#8ea9c1',justify='left',font=('Segoe UI',9),
                 wraplength=620).pack(anchor='w',pady=(12,0))

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
                 fg='#e6f1ff',bg='#121a28').pack(anchor='w')
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
        self.replace_expression=tk.Text(form,height=3,wrap='word',font=('Consolas',9),bg='#0a1120',fg='#dceeff',insertbackground='white')
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
        self.inject_expression=tk.Text(holder,height=3,wrap='word',font=('Consolas',9),bg='#0a1120',fg='#dceeff',insertbackground='white')
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
                 fg='#e6f1ff',bg='#121a28').pack(anchor='w')
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
        entry('Delay per action (sec)',self.coffee_interval_var,'Minimum 0.1; maximum 120')
        entry('Complete loop cycles',self.coffee_cycles_var,'0 = until stopped')

        ttk.Label(holder,textvariable=self.packet_connection_status,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(3,5))
        ttk.Label(holder,textvariable=self.coffee_users_status_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,6))
        ttk.Button(holder,text='Refresh room players',command=self._refresh_room_players).pack(anchor='w',pady=(0,9))
        buttons=ttk.Frame(holder,style='Panel.TFrame');buttons.pack(fill='x',pady=(4,12))
        ttk.Button(buttons,text='Give 1 cup',command=lambda:self._start_coffee_loop(single_cup=True)).pack(side='left',padx=(0,9))
        ttk.Button(buttons,text='Start coffee pass loop',command=self._start_coffee_loop).pack(side='left',padx=(0,9))
        ttk.Button(buttons,text='STOP',command=self._stop_coffee_loop).pack(side='left')
        ttk.Label(holder,textvariable=self.coffee_status_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(2,7))
        ttk.Label(holder,text='DELIVERY MONITOR (server activity, not a guarantee)',
                  style='Panel.TLabel').pack(anchor='w',pady=(3,3))
        ttk.Label(holder,textvariable=self.coffee_delivery_var,
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,10))
        ttk.Label(holder,text='No chat required: if the room list is missing, '
                   'the exact username is resolved through Habbo profile lookup. '
                   'Confirm the ID and ensure the recipient is in your room. '
                  'No ID is guessed if the name cannot be found. '
                  'One cup sends Cup 1 + Pass once; the loop alternates both cups. '
                  'G-Earth must be connected. The server can ignore or rate-limit requests.',
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(6,0))

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

    def _lookup_coffee_profile(self,username,single_cup=False):
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
            self._coffee_profile_pending=(username.casefold(),bool(single_cup),gen)
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
        self.root.after(0,lambda once=pending[1]:self._start_coffee_loop(single_cup=once))

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

    def _start_coffee_loop(self,single_cup=False):
        if self._coffee_running:
            self.coffee_status_var.set('Coffee pass loop already running. Click STOP first.')
            return
        if self._replay_running:
            self.coffee_status_var.set('Stop the single-packet repeater before starting this loop.')
            return
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            if self._coffee_start_queued:
                self.coffee_status_var.set('Preparing the G-Earth connection; the loop has not started yet.')
                return
            try:port=int(self.gearth_port_var.get())
            except (TypeError,ValueError):port=0
            if not self._gearth_extension_port_responds(port):
                self.coffee_status_var.set('G-Earth backend is offline. Start the engine first.')
                return
            if not self.packet_started:
                self._connect_gearth(capture=False)
            if not self.packet_started:
                self.coffee_status_var.set('Could not attach packet tools. See connection status above.')
                return
            self._coffee_start_queued=True
            self._coffee_queued_single=bool(single_cup)
            self._coffee_queue_deadline=time.monotonic()+20
            self.coffee_status_var.set('Waiting for G-Earth and the Habbo room connection. No coffee packets sent yet.')
            self._coffee_queue_after_id=self.root.after(
                350,lambda gen=self._coffee_generation:self._check_queued_coffee_start(gen))
            return
        username=self.coffee_username_var.get().strip()
        if (username and username.casefold() not in self._room_users
            and username.casefold() not in self._room_profile_cache):
            self._lookup_coffee_profile(username,single_cup=single_cup)
            return
        try:
            target_id,target_name=self._resolve_coffee_recipient()
            sequence=build_coffee_pass_sequence(self.coffee_cup_one_var.get(),
                                                self.coffee_cup_two_var.get(),
                                                target_id,single_cup=single_cup)
            interval=validate_replay_interval(self.coffee_interval_var.get())
            cycles_text=self.coffee_cycles_var.get().strip()
            if single_cup:
                cycles=1
            else:
                if not re.fullmatch(r'[0-9]{1,5}',cycles_text):
                    raise ValueError('Cycles must be an integer from 0 to 10000.')
                cycles=int(cycles_text)
                if cycles>10000:raise ValueError('Cycles must be 0 to 10000.')
            for expr in sequence:
                packet=self.packet_extension.string_to_packet(expr)
                if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
                    raise ValueError('G-Earth could not parse a generated packet; check its headers.')
        except (ValueError,TypeError,AttributeError) as exc:
            self.coffee_status_var.set('Cannot start: '+str(exc)[:170])
            return
        duration=('one cup' if single_cup else
                  'continuously until STOP' if cycles==0 else f'for {cycles} complete cycles')
        profile_only=(bool(username)
                      and username.casefold() in self._room_profile_cache
                      and username.casefold() not in self._room_users)
        presence_note=('This ID is from Habbo profile lookup, not a verified room '
                       'player list. Check the recipient is in your room.\n'
                       if profile_only else '')
        if not messagebox.askyesno('Give cup' if single_cup else 'Start coffee pass loop',
            f'Send coffee actions {duration}?\n'
            f'Recipient: {target_name or target_id} (ID {target_id})\n'
            f'{presence_note}'
            f'Delay between each packet: {interval:g} seconds\n\n'
            'Only proceed if you are permitted to automate these actions. '
            'Habbo may reject actions or rate-limit them.',
            parent=self.root):
            self.coffee_status_var.set('Coffee loop cancelled.')
            return
        self.config.update(coffee_cup_one=self.coffee_cup_one_var.get().strip(),
                           coffee_cup_two=self.coffee_cup_two_var.get().strip(),
                           coffee_recipient=self.coffee_recipient_var.get().strip(),
                           coffee_username=self.coffee_username_var.get().strip(),
                           coffee_interval=str(interval),coffee_cycles=str(cycles))
        self.save()
        self._coffee_generation+=1
        self._coffee_running=True
        self._coffee_sequence=sequence
        self._coffee_target_name=target_name.casefold()
        self._coffee_interval=interval
        self._coffee_limit=cycles
        self._coffee_index=0
        self._coffee_sent=0
        self._coffee_completed=0
        self._coffee_pass_requests=0
        self._coffee_carry_observations=0
        self._coffee_last_pass_at=0.0
        user=self._room_users.get(target_name.casefold()) if target_name else None
        self._coffee_target_room_index=(user[2] if user and user[2] is not None else None)
        self.coffee_delivery_var.set(coffee_delivery_text(
            self._coffee_pass_requests,self._coffee_carry_observations,
            self._coffee_target_room_index))
        self.coffee_status_var.set(f'Coffee pass ON — action 1/{len(sequence)}. Sent: 0; cycles: 0.')
        self._coffee_after_id=self.root.after(0,lambda generation=self._coffee_generation:
                                                 self._coffee_loop_tick(generation))

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

    def _coffee_loop_tick(self,generation):
        self._coffee_after_id=None
        if not self._coffee_running or generation!=self._coffee_generation:
            return
        if not self.packet_started or self.packet_extension is None or not self._habbo_session_connected:
            self._stop_coffee_loop('Habbo or G-Earth disconnected. Coffee loop stopped.')
            return
        try:
            expression=self._coffee_sequence[self._coffee_index]
            ext=self.packet_extension
            packet=ext.string_to_packet(expression)
            if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
                raise ValueError('G-Earth rejected a generated packet.')
            if ext.send_to_server(packet) is False:
                raise RuntimeError('G-Earth rejected the send.')
        except Exception as exc:
            self._stop_coffee_loop('Coffee loop stopped after error: '+str(exc)[:145])
            return
        self._coffee_sent+=1
        # Odd steps are PassCarryItem. Counting a successful local send
        # does NOT establish that Habbo accepted the handoff.
        if self._coffee_index%2==1:
            self._coffee_pass_requests+=1
            self._coffee_last_pass_at=time.time()
            self.coffee_delivery_var.set(coffee_delivery_text(
                self._coffee_pass_requests,self._coffee_carry_observations,
                self._coffee_target_room_index))
        self._coffee_index=(self._coffee_index+1)%len(self._coffee_sequence)
        if self._coffee_index==0:
            self._coffee_completed+=1
            if self._coffee_limit and self._coffee_completed>=self._coffee_limit:
                self._stop_coffee_loop('Requested cycles finished.')
                return
        label=('Cup 1','Pass','Cup 2','Pass')[self._coffee_index]
        self.coffee_status_var.set(f'Coffee loop ON — next: {label}. '
                                   f'Sent: {self._coffee_sent}; cycles: {self._coffee_completed}.')
        if self._coffee_running and generation==self._coffee_generation:
            self._coffee_after_id=self.root.after(round(self._coffee_interval*1000),
                lambda gen=generation:self._coffee_loop_tick(gen))

    def _stop_coffee_loop(self,reason=None):
        self._coffee_running=False
        self._coffee_start_queued=False
        self._coffee_queued_single=False
        self._coffee_target_name=''
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
                    if not (self.packet_active or self.manipulation_enabled or
                            self.config.get('whispers_right',True) or direction=='Incoming'):
                        return
                    try:detail=str(msg.packet.g_string(ext))
                    except Exception:detail='[Packet could not be formatted]'
                    if direction=='Incoming':
                        kind=classify_room_packet(ext,Direction.TO_CLIENT,msg.packet,detail)
                        if kind=='RoomReady':
                            self._packet_put(('room_users_reset',))
                        elif kind=='UserRemove':
                            room_index=removed_room_user_index(detail)
                            if room_index is None:
                                try:room_index=int(msg.packet.read_string(6))
                                except (IndexError,ValueError,TypeError,AttributeError):pass
                            self._packet_put(('room_user_removed',room_index))
                        elif kind=='ExtendedProfile':
                            profile=profile_recipient_from_packet(msg.packet)
                            if profile is not None:
                                self._packet_put(('coffee_profile',profile[0],profile[1]))
                        elif kind=='CarryObject':
                            carry=carry_object_from_packet(msg.packet)
                            if carry is not None:
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
            if item[0]=='coffee_profile':
                self._accept_coffee_profile(item[1],item[2])
                continue
            if item[0]=='coffee_carry_observed':
                _,room_index,item_type,seen_at=item
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
                self._room_users.clear()
                self._room_chat_names.clear()
                self._room_profile_cache.clear()
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
            if item[0]=='room_users_observed':
                self._room_lookup_seen=True
                if not item[1]:
                    self._room_lookup_parse_failed=True
                    self.coffee_users_status_var.set(
                        'Users packet received, but no valid usernames decoded. '
                        'This may be a new Habbo packet layout.')
                continue
            if item[0]=='room_users':
                self._room_users.update(item[1])
                self._room_lookup_pending=False
                self.coffee_users_status_var.set(
                    f'{len(self._room_users)} player(s) detected in this room. Enter an exact username.')
                continue
            if item[0]=='room_user_removed':
                index=item[1]
                self._room_users,removed=remove_room_user_by_index(self._room_users,index)
                for name in removed:
                    self._room_chat_names.discard(name)
                    self._room_profile_cache.pop(name,None)
                if (self._coffee_running and self._coffee_target_name
                    and (self._coffee_target_name in removed or index is None)):
                    self._stop_coffee_loop(
                        'Recipient may have left; coffee pass stopped pending re-verification.')
                self.coffee_users_status_var.set(
                    f'{len(self._room_users)} player(s) mapped. '
                    'A player left; unrelated players remain mapped.')
                continue
            if item[0]=='session_connection':
                self.packet_connection_status.set(
                    'Packet tools READY — Habbo and G-Earth connected.' if item[1]
                    else 'Packet tools attached; waiting for Habbo room connection.')
                if not item[1]:
                    self._room_users.clear()
                    self._room_chat_names.clear()
                    self._room_profile_cache.clear()
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
        path=filedialog.asksaveasfilename(title='Export packet log (may include private game data)',
            defaultextension='.txt',filetypes=[('Text file','*.txt')])
        if path:
            try:
                with open(path,'w',encoding='utf-8') as fh:
                    for t,d,s in self.packet_data:fh.write(f'{t} [{d}] {s}\n')
                self.packet_status.set('Packet log saved locally. Review its contents before sharing.')
            except OSError as exc:self.packet_status.set('Export failed: '+str(exc)[:130])

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
            x=item.get('x');y=item.get('y');sw=item.get('sw');sh=item.get('sh')
            within=True
            if isinstance(x,(int,float)) and isinstance(y,(int,float)) and sw and sh:
                within=bool(0<=x<=sw and 0<=y<=sh)
            if self.config.get('visible_only',True) and not within:return
            room=item.get('room')
            if room is not None and self.room_id is not None and room!=self.room_id:
                self.clear_msgs()
                self._room_users.clear()
                self._room_chat_names.clear()
                self._room_profile_cache.clear()
                self._coffee_profile_pending=None
                self._coffee_profile_generation+=1
                self.coffee_users_status_var.set('Room changed. Waiting for player IDs...')
                if self._coffee_running:self._stop_coffee_loop('Room changed; coffee pass stopped.')
            if room is not None:self.room_id=room
            self._room_chat_names.add(name.casefold())
            cached=self._room_profile_cache.pop(name.casefold(),None)
            if cached and self._habbo_session_connected:
                self._room_users[name.casefold()]=(cached[0],cached[1],None)
                self.coffee_users_status_var.set(
                    f'{cached[0]} verified from current room chat and profile (ID {cached[1]}).')
            raw_style=item.get('style')
            style_id=int(raw_style) if raw_style is not None else None
            chat_type_explicit=('chatType' in item or 'chat_type' in item)
            chat_type=int(item.get('chatType',item.get('chat_type',0)) or 0)
            if item.get('isWhisper') is True or item.get('whisper') is True:
                chat_type=1
                chat_type_explicit=True
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
            arrived=time.time()
            # G-Earth text-only hints are a fallback ONLY when the AIR feed
            # did not provide an explicit chat type. Never reclassify shouts.
            if not chat_type_explicit and match_recent_whisper(
                    self.whisper_hints,body,arrived):
                chat_type=1
            self.messages.append(Message(name,body,arrived,within,room,
                                         style_id,chat_type,forced_color,image_path,
                                         chat_type_explicit))
            self._trim_history()
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
                           anchor='w',font=('Segoe UI',9,'bold'),fill='#e1f0ff')

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
                elif not self.clickthrough_failed and time.monotonic()-self.last_clickthrough_check>1.5:
                    if not self.tracker.set_clickthrough(self.overlay.winfo_id()):
                        self.clickthrough_failed=True
                        self.overlay.withdraw()
                    self.last_clickthrough_check=time.monotonic()
                if not self.clickthrough_failed and foreground in ('habbo','settings'):
                    # Focusing Habbo normally raises it above the overlay.
                    # Repair only the game's own z-order when it is active,
                    # never while another app is foreground.
                    self.tracker.stack_above_habbo(self.overlay.winfo_id(),geom[4])
                if self.clickthrough_failed:
                    self.status.set('Overlay hidden: Windows click-through could not be enabled. Restart the panel to retry.')
                elif not self.feed:
                    self.status.set('Habbo found. Waiting for local chat bridge log...')
            else:
                self.overlay.withdraw();self.last_rect=None;self.last_overlay_geometry=None
                self.status.set('Waiting for a Habbo client window...')
            self.draw()
        except Exception as e:
            self.status.set(f'Overlay issue: {str(e)[:140]}')
        self.root.after(120,self.tick)

    def close(self):
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