# -*- coding: utf-8 -*-
"""Per-user, one-click installation for Habbo Companion (Windows only)."""
from __future__ import annotations
import base64
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

NAME='Habbo Companion'
FILES=('Habbo_Companion.pyw','Habbo_Update_Helper.py','app_manifest.json',
       'START_Habbo_Companion.bat','DEBUG_Habbo_Companion.bat','README.txt')


def resolve_paths():
    if os.name != 'nt':
        raise RuntimeError('This installer is for Windows only.')
    local=os.environ.get('LOCALAPPDATA')
    roaming=os.environ.get('APPDATA')
    if not local or not roaming:raise RuntimeError('Windows AppData folders are not available')
    root=Path(local)/'Programs'/NAME
    data=Path(local)/'HabboCompanion'
    settings=Path(roaming)/'HabboViewChat'/'settings.json'
    return root,data,settings


def get_gui_python():
    interpreter=Path(sys.executable).resolve()
    for exe in (interpreter.with_name('pythonw.exe'),interpreter.with_name('pythonw3.exe')):
        if exe.is_file():return exe
    candidate=shutil.which('pyw.exe') or shutil.which('pythonw.exe')
    if candidate:return Path(candidate)
    # Console Python fallback still launches the app correctly.
    return interpreter


def add_shortcut(path,pythonw,script,workdir):
    # PowerShell uses the standard Windows shell COM API; no admin access.
    argv=f'"{script}"'
    if pythonw.name.lower()=='pyw.exe':argv=f'-3 {argv}'
    q=lambda value: "'"+str(value).replace("'","''")+"'"
    ps=(
        '$w=New-Object -ComObject WScript.Shell;'
        f'$s=$w.CreateShortcut({q(path)});'
        f'$s.TargetPath={q(pythonw)};'
        f'$s.Arguments={q(argv)};'
        f'$s.WorkingDirectory={q(workdir)};'
        "$s.Description='Launch Habbo Companion';"
        '$s.Save()'
    )
    encoded=base64.b64encode(ps.encode('utf-16le')).decode('ascii')
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                   check=True,capture_output=True,text=True,timeout=25)


def install():
    root,data,settings=resolve_paths()
    source=Path(__file__).resolve().parent/'Payload'
    for filename in FILES:
        if not (source/filename).is_file():raise RuntimeError(f'Installer payload is missing {filename}')
    try:
        import tkinter  # noqa: F401
    except ImportError as exc:
        raise RuntimeError('Python needs Tkinter for the settings panel.') from exc
    metadata=json.loads((source/'app_manifest.json').read_text(encoding='utf-8'))
    if metadata.get('app_id')!='habbo-companion':raise RuntimeError('Incorrect installer payload')
    root.mkdir(parents=True,exist_ok=True)
    backup=data/'Backups'/('installer_'+dt.datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True,exist_ok=True)
    for filename in FILES:
        current=root/filename
        if current.is_file():shutil.copy2(current,backup/filename)
    if settings.is_file():
        shutil.copy2(settings,backup/'settings.json')  # backup only: no edits
        print('Existing chat and G-Earth settings found and preserved.')
    else:
        print('No existing settings found; Companion will use its defaults.')
    staging=root/'.install-staging'
    if staging.is_dir():shutil.rmtree(staging)
    staging.mkdir()
    try:
        for filename in FILES:shutil.copy2(source/filename,staging/filename)
        for filename in FILES:os.replace(staging/filename,root/filename)
    finally:
        shutil.rmtree(staging,ignore_errors=True)
    pythonw=get_gui_python()
    user_desktop=Path(os.environ.get('USERPROFILE',str(Path.home())))/'Desktop'
    desktop=Path(os.environ.get('HABBO_COMPANION_DESKTOP',user_desktop))
    # Redirected Desktop may not exist as a physical directory, so skip it.
    if desktop.is_dir():
        try:
            add_shortcut(desktop/'Habbo Companion.lnk',pythonw,root/'Habbo_Companion.pyw',root)
            print('Desktop shortcut created.')
        except Exception as exc:
            print('Desktop shortcut could not be created:',str(exc)[:150])
    menu=Path(os.environ['APPDATA'])/'Microsoft'/'Windows'/'Start Menu'/'Programs'/NAME
    menu.mkdir(parents=True,exist_ok=True)
    try:
        add_shortcut(menu/'Habbo Companion.lnk',pythonw,root/'Habbo_Companion.pyw',root)
        print('Start-menu shortcut created.')
    except Exception as exc:
        print('Start-menu shortcut could not be created:',str(exc)[:150])
    print(f'Installed version {metadata["version"]} into: {root}')
    print('Settings remain at:',settings)
    print('Backups at:',backup)
    cmd=[str(pythonw)]
    if pythonw.name.lower()=='pyw.exe':cmd.append('-3')
    cmd.append(str(root/'Habbo_Companion.pyw'))
    subprocess.Popen(cmd,cwd=root,close_fds=True)
    return 0

if __name__=='__main__':
    try:raise SystemExit(install())
    except Exception as exc:
        print('INSTALLATION ERROR:',exc)
        traceback.print_exc()
        raise SystemExit(1)
