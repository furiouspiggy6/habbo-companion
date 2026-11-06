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
    theme='Midnight',
    topmost=False,
    keep_log=False,
    feed_path='',
    gearth_path='',
    gearth_port=9092,
    gearth_host='game-us.habbo.com',
    gearth_game_port=30000,
    gearth_minimize=True,
    gearth_auto_arm=True,
    gearth_background_v108=False,
    gearth_visible_debug_v106=False,
    gearth_startup_safety_v104=True,
    gearth_startup_uia_v105=False,
    packet_rules=[],
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
        return {**DEFAULT,**{k:v for k,v in saved.items() if k in DEFAULT}}
    except (OSError, ValueError, TypeError):
        return DEFAULT.copy()


def save_config(cfg):
    APP_DIR.mkdir(exist_ok=True, parents=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding='utf-8')


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


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
        self.root=root;self.root.title('Habbo Companion — Chat + Packets')
        self.root.geometry('720x900')
        self.root.attributes('-topmost',False)  # behave like a normal app window
        self.root.minsize(540,560)
        self.root.configure(bg='#121a28')
        self.tracker=WinTracker()
        self.config=load_config()
        # Packet tools are optional. The existing local AIR chat bridge works
        # even without G-Earth or G-Python installed.
        self.packet_queue=queue.Queue(maxsize=1200)
        self.packet_data=[]
        self.packet_active=False
        self.packet_started=False
        self.packet_extension=None
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
        self.gearth_process=None
        self._gearth_minimize_tries=0
        self._gearth_autostart_active=False
        self._gearth_auto_arm_attempted=False
        self._gearth_launch_queued=False
        self._gearth_started_at=0.0
        self._gearth_launch_watch_until=0.0
        self._gearth_launch_started=0.0
        self._engine_installing=False
        self.engine_status_var=tk.StringVar(value='Engine: checking installation...')
        self.gearth_auto_arm_var=tk.BooleanVar(value=bool(self.config.get('gearth_auto_arm',True)))
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
        self._check(f,'Show bubble backgrounds','bubbles')
        self._check(f,'Original Habbo bubble artwork (native PNG)','original_bubble_images')
        self._check(f,'Fallback bubble colours if original unavailable','respect_chat_styles')
        self._check(f,'Keep a local chat log after exit','keep_log')
        self._check(f,'Auto-fill available screen with chat bubbles','auto_fill_screen')
        tk.Label(f,text='The overlay stays above Habbo, but behind other apps. Switching windows does not clear chat.',
                 wraplength=352,justify='left',font=('Segoe UI',9),bg='#121a28',fg='#88a2bc').pack(anchor='w',pady=(2,4))
        tk.Label(f,text='When auto-fill is on, the number of visible bubbles adapts to your screen height. Older messages stay in scrollback.',
                 wraplength=352,justify='left',font=('Segoe UI',9),bg='#121a28',fg='#88a2bc').pack(anchor='w',pady=(2,4))
        for label,key,low,high,desc in [
            ('Vertical starting point','anchor',45,95,'% of screen height'),
            ('Left margin','x',0,200,'pixels from window edge'),
            ('Bubble width','width',250,800,'pixels'),
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
                req=urllib.request.Request(url,headers={'User-Agent':'HabboCompanionUpdater/1.0'})
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
                    self.root.after(0,lambda:self._finish_online_update('Already up to date ('+self.current_app_version+').'))
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
        """Read-only packet inspector powered by optional G-Earth G-Python extension."""
        holder=ttk.Frame(parent,style='Panel.TFrame',padding=14)
        holder.pack(fill='both',expand=True)
        tk.Label(holder,text='PACKET VIEWER',font=('Segoe UI Semibold',18),
                 fg='#e6f1ff',bg='#121a28').pack(anchor='w')
        tk.Label(holder,text='Companion manages the official G-Earth engine internally. It imports your selected beta or installs a SHA-256-verified official copy once, then launches the proxy. No separate G-Earth installation needed.',
                 fg='#8ea9c1',bg='#121a28',wraplength=600,justify='left').pack(anchor='w',pady=(0,9))
        tk.Label(holder,textvariable=self.engine_status_var,bg='#121a28',fg='#76caab',
                 font=('Segoe UI Semibold',10),wraplength=620,justify='left').pack(anchor='w',pady=(0,9))
        gearth_row=ttk.Frame(holder,style='Panel.TFrame');gearth_row.pack(fill='x',pady=(2,7))
        ttk.Button(gearth_row,text='Open engine (safe)',command=self._open_managed_safe).pack(side='left',padx=(0,6))
        ttk.Button(gearth_row,text='Start engine',command=self._connect_habbo_air).pack(side='left',padx=(0,6))
        ttk.Button(gearth_row,text='Advanced G-Earth',command=self._show_gearth).pack(side='left',padx=(0,6))
        ttk.Button(gearth_row,text='Install / repair',command=self._start_integrated_engine).pack(side='left',padx=(0,6))
        tk.Label(holder,textvariable=self.gearth_path_display,bg='#121a28',fg='#8ea9c1',font=('Segoe UI',9),wraplength=620,justify='left').pack(anchor='w',fill='x',pady=(0,6))
        auto_row=ttk.Frame(holder,style='Panel.TFrame');auto_row.pack(fill='x',pady=(0,5))
        ttk.Checkbutton(auto_row,text='Automatically start the integrated engine with Companion',
                        variable=self.gearth_auto_arm_var,command=self._save_gearth_auto_arm).pack(side='left')
        launch_row=ttk.Frame(holder,style='Panel.TFrame');launch_row.pack(fill='x',pady=(0,5))
        ttk.Button(launch_row,text='Launch Habbo after G-Earth is ready',command=self._launch_habbo_with_gearth).pack(side='left',padx=(0,7))
        ttk.Button(launch_row,text='Select Habbo launcher',command=self._select_habbo_launcher).pack(side='left')
        tk.Label(holder,textvariable=self.habbo_path_display,bg='#121a28',fg='#8ea9c1',font=('Segoe UI',9),wraplength=620,justify='left').pack(anchor='w',fill='x',pady=(0,6))

        hotel_opts=ttk.Frame(holder,style='Panel.TFrame');hotel_opts.pack(fill='x',pady=(0,8))
        ttk.Label(hotel_opts,text='Hotel host:',style='Panel.TLabel').pack(side='left')
        ttk.Entry(hotel_opts,textvariable=self.gearth_host_var,width=24).pack(side='left',padx=(6,9))
        ttk.Label(hotel_opts,text='Game port:',style='Panel.TLabel').pack(side='left')
        ttk.Entry(hotel_opts,textvariable=self.gearth_game_port_var,width=7).pack(side='left',padx=(6,9))
        connection_opts=ttk.Frame(holder,style='Panel.TFrame');connection_opts.pack(fill='x',pady=(0,7))
        ttk.Checkbutton(connection_opts,text='Keep engine window minimized',variable=self.gearth_minimize_var,
                        command=self._save_gearth_minimize).pack(side='left',padx=(0,10))
        ttk.Label(connection_opts,text='Extension port:',style='Panel.TLabel').pack(side='left')
        ttk.Entry(connection_opts,textvariable=self.gearth_port_var,width=7).pack(side='left',padx=(5,7))
        ttk.Button(connection_opts,text='Connect viewer',command=self._connect_gearth).pack(side='left')
        ttk.Label(holder,textvariable=self.packet_status,style='Panel.TLabel',wraplength=610).pack(anchor='w',fill='x',pady=(0,8))
        opts=ttk.Frame(holder,style='Panel.TFrame');opts.pack(fill='x',pady=(0,7))
        ttk.Label(opts,text='Find in packets',style='Panel.TLabel').pack(side='left',padx=(0,6))
        ttk.Entry(opts,textvariable=self.packet_filter_var).pack(side='left',fill='x',expand=True,padx=(0,7))
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
        # Separate from native G-Earth UI; shares the same extension session as Packet Viewer.
        holder=ttk.Frame(parent,style='Panel.TFrame',padding=13)
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
        ttk.Label(holder,text='Changing or blocking essential packets can disconnect Habbo. Rules stay saved but never auto-enable. '
                  'Only send packets for your own session. No automatic replay or flood controls.',
                  style='Panel.TLabel',wraplength=630).pack(anchor='w',pady=(8,0))
        self._refresh_manipulation_rules()

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

    def _select_gearth(self):
        path=filedialog.askopenfilename(title='Select G-Earth.exe or G-Earth.jar',
            filetypes=[('G-Earth program','*.exe *.jar'),('All files','*.*')])
        if path:
            self.config['gearth_path']=path
            self.gearth_path_display.set('Selected G-Earth: '+path)
            self.save()
            self.packet_status.set('G-Earth location saved. Check this is the working beta executable, not version 1.5.3.')

    def _save_gearth_auto_arm(self):
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
        """Prepare the internal engine, then request G-Earth's own AIR proxy."""
        if not self.gearth_auto_arm_var.get():
            self.engine_status_var.set('Engine: automatic startup disabled')
            return
        self._start_integrated_engine()

    def _start_integrated_engine(self):
        """A single Companion action installs (once), starts, and monitors."""
        if self._engine_installing:
            self.engine_status_var.set('Engine: installation already in progress')
            return
        if self.tracker.find([self.root.winfo_id(),self.overlay.winfo_id()]):
            self.engine_status_var.set('Engine: Habbo already open; start the engine before login')
            return
        try:port=int(self.gearth_port_var.get())
        except (TypeError,ValueError):port=9092
        if self._gearth_extension_port_responds(port):
            self.engine_status_var.set(f'Engine backend: ONLINE (127.0.0.1:{port}); proxy WAITING state not verified')
            self.packet_status.set('G-Earth backend already running; no second engine launched.')
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
        self.engine_status_var.set('Engine: installing the managed runtime...')
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

    def _engine_heartbeat(self):
        """Expose backend and installation state without trusting a GUI title."""
        if not self.root.winfo_exists():return
        try:port=int(self.gearth_port_var.get())
        except (TypeError,ValueError):port=9092
        if self._gearth_extension_port_responds(port):
            self.engine_status_var.set(f'Engine backend: ONLINE · extension port {port} · proxy WAITING state not independently verified')
        elif not self._engine_installing:
            exe=managed_gearth_executable()
            if self._gearth_launch_watch_until>time.monotonic():
                self.engine_status_var.set('Engine: starting; waiting for backend...')
            elif exe:
                self.engine_status_var.set('Engine: installed · backend OFFLINE')
            else:
                self.engine_status_var.set('Engine: not yet installed')
        self.root.after(2500,self._engine_heartbeat)

    def _start_gearth_direct(self,select_if_missing=True):
        if os.name!='nt':
            self.packet_status.set('G-Earth background launch requires Windows.')
            return False
        if self._gearth_launch_watch_until>time.monotonic():
            self.packet_status.set('G-Earth startup is still being checked. Please do not start Habbo yet.')
            return False
        if self.tracker.find([self.root.winfo_id(),self.overlay.winfo_id()]):
            self.packet_status.set('Habbo is already open. G-Earth must start before game login.')
            return False
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
                self.root.after(3500,self._minimize_gearth_after_backend)
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

    def _minimize_gearth_after_backend(self):
        """Minimize the working GUI only after startup; keep G-Earth running."""
        if not self.root.winfo_exists() or not self.gearth_minimize_var.get():
            return
        try:port=int(self.gearth_port_var.get())
        except (TypeError,ValueError):port=9092
        if not self._gearth_extension_port_responds(port):
            return
        hwnd=self._find_gearth_window()
        if hwnd:
            user32=ctypes.WinDLL('user32',use_last_error=True)
            user32.ShowWindowAsync.argtypes=[wintypes.HWND,ctypes.c_int]
            user32.ShowWindowAsync.restype=wintypes.BOOL
            user32.ShowWindowAsync(hwnd,6)

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
        if not self._find_gearth_window():
            self._start_integrated_engine()
            self.packet_status.set('Starting the internal G-Earth engine. Wait until the proxy is ready, then launch Habbo again.')
            return
        if not messagebox.askyesno('G-Earth connection check',
            'Does the G-Earth beta currently display "Waiting for connection"?\n\n'
            'If not, click No and connect manually in G-Earth first.\n\n'
            'Only click Yes when G-Earth is actually waiting for Habbo.'):
            self.packet_status.set('Habbo not launched. Connect G-Earth first and verify its state.')
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

    def _save_gearth_minimize(self):
        self.config['gearth_minimize']=bool(self.gearth_minimize_var.get())
        self.save()

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
        if os.name!='nt':return
        hwnd=self._find_gearth_window()
        if not hwnd:
            self.packet_status.set('G-Earth window not found. Use Connect Habbo AIR to start it.')
            return
        user32=ctypes.WinDLL('user32',use_last_error=True)
        user32.ShowWindowAsync.argtypes=[wintypes.HWND,ctypes.c_int]
        user32.ShowWindowAsync.restype=wintypes.BOOL
        user32.ShowWindowAsync(hwnd,9)  # SW_RESTORE; user can use the native advanced controls
        user32.SetForegroundWindow.argtypes=[wintypes.HWND]
        user32.SetForegroundWindow.restype=wintypes.BOOL
        user32.SetForegroundWindow(hwnd)
        self._gearth_autostart_active=False
        self.packet_status.set('Advanced G-Earth window opened. Changes here remain in G-Earth.')

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
            self._gearth_autostart_active=bool(auto_connect)
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

    def _connect_gearth(self):
        if self.packet_started:
            self.packet_active=True
            self.packet_status.set('Viewer already started. Capture resumed.')
            return
        try:
            port=int(self.gearth_port_var.get())
            if not 1<=port<=65535:raise ValueError()
        except ValueError:
            self.packet_status.set('Enter a valid G-Earth extension port (usually 9092).')
            return
        self.config['gearth_port']=port
        self.save()
        try:
            import g_python.gextension  # noqa: F401
        except ImportError:
            self.packet_status.set('Install G-Python once with: py -m pip install g-python')
            return
        self.packet_active=True
        self.packet_started=True
        self.packet_status.set(f'Connecting extension on local port {port}...')
        threading.Thread(target=self._packet_worker,args=(port,),daemon=True).start()

    def _packet_worker(self,port):
        try:
            from g_python.gextension import Extension
            from g_python.hmessage import Direction
            info={'title':'Habbo Companion Packet Tools',
                  'description':'Packet viewer with optional session rules and manual send',
                  'version':'1.1.0','author':'Habbo Companion'}
            ext=Extension(info,['-p',str(port)])
            self.packet_extension=ext
            def event(name):
                self._packet_put(('status',name))
            ext.on_event('init',lambda:event('G-Earth extension connected.'))
            ext.on_event('connection_start',lambda:event('Habbo AIR connected; capturing packets in Habbo Companion.'))
            def disconnected():
                self.manipulation_enabled=False
                self._packet_put(('manip_status','G-Earth disconnected. Manipulation automatically OFF.'))
                self._packet_put(('manip_off',))
                event('Habbo traffic disconnected.')
            ext.on_event('connection_end',disconnected)
            def hook(direction):
                def on_message(msg):
                    if not self.packet_active and not self.manipulation_enabled:return
                    try:detail=str(msg.packet.g_string(ext))[:4000]
                    except Exception:detail='[Packet could not be formatted]'
                    if self.manipulation_enabled and self.packet_rules:
                        try:
                            matched=apply_manipulation_rule(msg,direction,detail,
                                                            tuple(self.packet_rules),ext)
                            if matched:
                                detail=f'[{matched[0]} rule {matched[1]}] '+detail
                        except Exception as exc:
                            self._packet_put(('manip_status',f'Rule error; packet unchanged: {str(exc)[:160]}'))
                    if self.packet_active:
                        self._packet_put(('packet',datetime.now().strftime('%H:%M:%S'),direction,detail))
                return on_message
            ext.intercept(Direction.TO_CLIENT,hook('Incoming'))
            ext.intercept(Direction.TO_SERVER,hook('Outgoing'))
            ext.start()
        except Exception as exc:
            self.packet_started=False
            self._packet_put(('status',f'G-Earth connection failed: {type(exc).__name__}: {str(exc)[:190]}'))

    def _packet_put(self,item):
        try:self.packet_queue.put_nowait(item)
        except queue.Full:pass  # never block the Habbo packet interception thread

    def _pump_packets(self):
        if not self.root.winfo_exists():return
        for _ in range(150):
            try:item=self.packet_queue.get_nowait()
            except queue.Empty:break
            if item[0]=='engine_status':
                self.engine_status_var.set('Engine setup: '+item[1])
                continue
            if item[0]=='engine_error':
                self._engine_installing=False
                self.engine_status_var.set('Engine install FAILED: '+item[1])
                self.packet_status.set('Engine setup failed; use Install / repair to retry. '+item[1])
                continue
            if item[0]=='engine_installed':
                self._engine_installing=False
                self.config['gearth_path']=item[1]
                self.gearth_path_display.set('Managed engine: '+item[1])
                self.save()
                self.engine_status_var.set('Engine installed from '+item[2]+'. Starting...')
                self._start_gearth_direct(select_if_missing=False)
                continue
            if item[0]=='status':
                self.packet_status.set(item[1]);continue
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
            if room is not None:self.room_id=room
            raw_style=item.get('style')
            style_id=int(raw_style) if raw_style is not None else None
            chat_type=int(item.get('chatType',0) or 0)
            raw_color=item.get('forcedColor')
            forced_color=int(raw_color) if isinstance(raw_color,(float,int)) else None
            image_path=None
            raw_image=item.get('bubbleImage')
            # Only trust the expected basename beside the local chat feed.
            # Never open arbitrary paths embedded in a chat message.
            if (self.feed is not None and isinstance(raw_image,str)
                and re.fullmatch(r'habbo_view_bubble_[0-9]+_-?[0-9]+_-?[0-9]+\.png',raw_image)):
                candidate=self.feed.parent/raw_image
                try:
                    if candidate.is_file() and 8<candidate.stat().st_size<2_000_000:
                        image_path=candidate
                except OSError:pass
            # While reviewing earlier chat, keep the same messages in view as
            # incoming messages arrive instead of snapping back to the bottom.
            if self.scroll_offset>0:self.scroll_offset+=1
            self.messages.append(Message(name,body,time.time(),within,room,
                                         style_id,chat_type,forced_color,image_path))
            self._trim_history()
            if self.config.get('original_bubble_images',True):
                if image_path:
                    self.native_image_count+=1
                    if self.native_image_count==1:
                        self.status.set('Receiving original Habbo bubble images (native client artwork).')
                elif self.native_image_count==0:
                    self.status.set('No original bubble images yet. Check that both updated files are installed.')
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
        maxw=min(int(self.config['width']), max(150,sw-int(self.config['x'])-10))
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
        for msg in reversed(self.messages[start:end]):
            # Original: render the actual image produced by Habbo's own
            # PooledChatBubble/ChatStyle renderer. Keeps fonts, background,
            # borders, avatar artwork, and pointers pixel-for-pixel.
            if (show_bubbles and self.config.get('original_bubble_images',True)
                and msg.bubble_image is not None):
                key=str(msg.bubble_image)
                try:
                    original=self.native_images.get(key)
                    if original is None:
                        original=tk.PhotoImage(master=self.root,file=key,format='png')
                        self.native_images[key]=original
                    w,h=original.width(),original.height()
                    if w>0 and h>0:
                        top=cursor-h
                        if top<24:break
                        cv.create_image(x,top,image=original,anchor='nw')
                        cursor=top-gap
                        rendered_count+=1
                        active_images.add(key)
                        continue
                except (OSError,tk.TclError,ValueError):
                    pass  # old client or corrupted image: use normal fallback
            # Compact Habbo-like bubbles: username and first part of the message
            # share a line; follow-on text wraps to the available wide column.
            username=msg.name+':'
            inset=pad+22  # avatar emblem to the left of the text
            fullw=max(110,maxw-inset-pad)
            name_w=self.canvas_bold.measure(username)
            available=max(45,fullw-name_w-7)
            words=msg.body.replace('\n',' ').split()
            first=[]
            while words:
                candidate=' '.join(first+[words[0]])
                if self.canvas_font.measure(candidate)>available:break
                first.append(words.pop(0))
            first_line=' '.join(first)
            rest=wrap_message(' '.join(words),fullw,self.canvas_font) if words else []
            line_count=1+len(rest)
            height=2*pad+fline*line_count
            line1_w=name_w+(7+self.canvas_font.measure(first_line) if first_line else 0)
            content_w=max([line1_w]+[self.canvas_font.measure(t) for t in rest])
            boxw=min(maxw,max(160,content_w+inset+pad))
            top=cursor-height
            if top<24:break
            if show_bubbles:
                bg,fg,emblem,edge=(get_message_colors(msg,theme)
                    if self.config.get('respect_chat_styles',True) else
                    (theme['bubble'],theme['fg'],theme['acc'],theme['name']))
                cv.create_rectangle(x+3,top+4,x+boxw+3,cursor+4,fill='#070e19',outline='')
                self._rounded(cv,x,top,x+boxw,cursor,9,edge)
                self._rounded(cv,x+2,top+2,x+boxw-2,cursor-2,7,bg)
                name_fg=fg
            else:
                fg='#edf4ff';name_fg='#83c9f7';emblem='#334d66'
            # Small avatar-like initial. No third-party game art is required.
            ix=x+pad+7;iy=top+pad+fline/2
            cv.create_oval(ix-9,iy-9,ix+9,iy+9,fill=emblem,outline='')
            cv.create_text(ix,iy,text=msg.name[:1].upper(),anchor='center',
                           font=('Segoe UI Semibold',9),fill='#f8fbff')
            tx=x+inset;ty=top+pad
            cv.create_text(tx,ty,text=username,anchor='nw',font=self.canvas_bold,fill=name_fg)
            if first_line:
                cv.create_text(tx+name_w+7,ty,text=first_line,anchor='nw',font=self.canvas_font,fill=fg)
            for i,line in enumerate(rest,1):
                cv.create_text(tx,ty+i*fline,text=line,anchor='nw',font=self.canvas_font,fill=fg)
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
                # When the room is visible, only cover the left chat column.
                # This also limits click obstruction if a Windows theme interferes
                # with the click-through style. The room-hidden option uses the
                # full client width for its background.
                overlay_w=sw if not self.config['show_room'] else min(sw,max(260,
                    int(self.config['x'])+int(self.config['width'])+28))
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
    main()