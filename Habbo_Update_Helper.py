# -*- coding: utf-8 -*-
"""Verified local updates for Habbo Companion. Uses only Python standard library.

No elevation. Does not touch Habbo files or user settings. Update packages are
not signatures: only install packages from a trusted publisher.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

APP_ID = 'habbo-companion'
MANIFEST = 'habbo-update.json'
APP_FILES = frozenset({'Habbo_Companion.pyw', 'Habbo_Update_Helper.py', 'headless_transport.py', 'local_classic_launch.py', 'README.txt'})
MAX_PACKAGE = 12 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024


def version_tuple(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}',value):
        raise ValueError('Invalid version; expected major.minor.patch')
    return tuple(map(int,value.split('.')))


def is_newer(candidate,current):
    return version_tuple(candidate)>version_tuple(current)


def inspect_package(package, current_version=None):
    package=Path(package)
    if not package.is_file():raise ValueError('Update ZIP was not found')
    if package.stat().st_size>MAX_PACKAGE:raise ValueError('Update ZIP is too large')
    with zipfile.ZipFile(package) as zf:
        names=zf.namelist()
        if len(names)!=len(set(names)):raise ValueError('Update contains duplicate file names')
        if MANIFEST not in names:raise ValueError('Missing update manifest')
        if len(names)>len(APP_FILES)+1:raise ValueError('Unexpected files in update package')
        for zi in zf.infolist():
            if zi.filename != MANIFEST and zi.filename not in APP_FILES:
                raise ValueError('Update contains an unexpected file: '+zi.filename)
            if '/' in zi.filename or '\\' in zi.filename or '..' in zi.filename:
                raise ValueError('Unsafe path in update package')
            if zi.file_size>MAX_FILE or zi.compress_size>MAX_PACKAGE:
                raise ValueError('Update contains an oversized file')
            mode=(zi.external_attr>>16)&0o170000
            if mode==0o120000:raise ValueError('Symlinks are not allowed in updates')
        info=json.loads(zf.read(MANIFEST).decode('utf-8'))
        if info.get('format')!=1 or info.get('app_id')!=APP_ID:
            raise ValueError('This update is not for Habbo Companion')
        version_tuple(info.get('version'))
        files=info.get('files')
        if not isinstance(files,dict) or 'Habbo_Companion.pyw' not in files:
            raise ValueError('Missing application file in update')
        if set(files)!=set(names)-{MANIFEST}:
            raise ValueError('Manifest file list does not match ZIP contents')
        for name, digest in files.items():
            if name not in APP_FILES or not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):
                raise ValueError('Invalid file name or hash in manifest')
            if hashlib.sha256(zf.read(name)).hexdigest()!=digest:
                raise ValueError('Update verification failed for '+name)
        if current_version not in (None,'unknown') and not is_newer(info['version'],current_version):
            raise ValueError('This update is not newer than your installed version ('+current_version+').')
    return info


def wait_for_process(pid, timeout=45):
    if pid<=0:return True
    if os.name=='nt':
        import ctypes
        SYNCHRONIZE=0x00100000
        PROCESS_QUERY_LIMITED_INFORMATION=0x1000
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        kernel.WaitForSingleObject.restype=ctypes.c_ulong
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(SYNCHRONIZE|PROCESS_QUERY_LIMITED_INFORMATION,False,pid)
        if not handle:return True # Process already exited or cannot be queried.
        try:return kernel.WaitForSingleObject(handle,int(timeout*1000))==0
        finally:kernel.CloseHandle(handle)
    else:
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:os.kill(pid,0)
            except ProcessLookupError:return True
            time.sleep(0.1)
        return False


def data_folder():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'HabboCompanion'


def apply_package(package, install_dir, wait_pid=0, restart_executable=None, no_restart=False):
    root=Path(install_dir).resolve()
    old_manifest=root/'app_manifest.json'
    if not old_manifest.is_file():raise ValueError('Install Habbo Companion before applying updates')
    current=json.loads(old_manifest.read_text(encoding='utf-8'))
    if current.get('app_id')!=APP_ID:raise ValueError('Application identity does not match')
    version=current['version']
    info=inspect_package(package,current_version=version)
    if not wait_for_process(wait_pid):raise TimeoutError('Habbo Companion did not close within 45 seconds')
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
    backup=data_folder()/'Backups'/f'{stamp}_from_{version}_{uuid.uuid4().hex[:6]}'
    backup.mkdir(parents=True,exist_ok=False)
    staging=root/f'.update-staging-{uuid.uuid4().hex[:8]}'
    staging.mkdir(parents=True,exist_ok=False)
    original_files={}
    write_attempted=[]
    try:
        with zipfile.ZipFile(package) as zf:
            for name in info['files']:
                (staging/name).write_bytes(zf.read(name))
        # Backup every file we will change. User settings are never modified.
        for name in set(info['files'])|{'app_manifest.json'}:
            target=root/name
            original_files[name]=target.is_file()
            if target.is_file():shutil.copy2(target,backup/name)
        roaming=Path(os.environ.get('APPDATA',str(Path.home()))) / 'HabboViewChat' / 'settings.json'
        if roaming.is_file():shutil.copy2(roaming,backup/'settings.json')
        new_meta={'app_id':APP_ID,'version':info['version'],'format':1,
                  'updated_at':datetime.now().isoformat(timespec='seconds')}
        (staging/'app_manifest.json').write_text(json.dumps(new_meta,indent=2)+'\n',encoding='utf-8')
        for name in list(info['files'])+['app_manifest.json']:
            write_attempted.append(name)
            os.replace(staging/name,root/name)
    except Exception:
        # Restore the prior working application; settings never touched.
        for name in reversed(write_attempted):
            previous=backup/name
            if original_files.get(name) and previous.is_file():shutil.copy2(previous,root/name)
            elif not original_files.get(name):
                try:(root/name).unlink(missing_ok=True)
                except OSError:pass
        raise
    finally:
        shutil.rmtree(staging,ignore_errors=True)
    if restart_executable and not no_restart:
        subprocess.Popen([str(restart_executable),str(root/'Habbo_Companion.pyw')],cwd=root,
                         close_fds=True)
    return str(backup)


def restore_previous(install_dir, backup_dir, wait_pid=0, restart_executable=None, no_restart=False):
    root=Path(install_dir).resolve()
    backup=Path(backup_dir).resolve()
    allowed_parent=(data_folder()/'Backups').resolve()
    if allowed_parent not in backup.parents or not backup.is_dir():
        raise ValueError('Backup must be located in the Companion backups folder')
    meta_path=backup/'app_manifest.json'
    if not meta_path.is_file():raise ValueError('Backup has no application manifest')
    meta=json.loads(meta_path.read_text(encoding='utf-8'))
    if meta.get('app_id')!=APP_ID:raise ValueError('Backup is not for Habbo Companion')
    version_tuple(meta.get('version'))
    files=[name for name in APP_FILES if (backup/name).is_file()]
    if 'Habbo_Companion.pyw' not in files:raise ValueError('Backup is missing the Companion application')
    if not wait_for_process(wait_pid):raise TimeoutError('Companion did not close')
    now=datetime.now().strftime('%Y%m%d-%H%M%S')
    safety=data_folder()/'Backups'/f'{now}_before_restore_{uuid.uuid4().hex[:6]}'
    safety.mkdir(parents=True,exist_ok=False)
    previous={}
    changed=[]
    try:
        for name in files+['app_manifest.json']:
            target=root/name
            previous[name]=target.is_file()
            if target.is_file():shutil.copy2(target,safety/name)
        for name in files+['app_manifest.json']:
            changed.append(name)
            shutil.copy2(backup/name,root/name)
    except Exception:
        for name in changed:
            if previous.get(name) and (safety/name).is_file():
                shutil.copy2(safety/name,root/name)
        raise
    if restart_executable and not no_restart:
        subprocess.Popen([str(restart_executable),str(root/'Habbo_Companion.pyw')],cwd=root,close_fds=True)
    return str(safety)


def log_result(message):
    folder=data_folder()
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'updater.log').open('a',encoding='utf-8') as stream:
        stream.write(datetime.now().isoformat(timespec='seconds')+'  '+message+'\n')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['inspect','apply','restore'])
    parser.add_argument('--package')
    parser.add_argument('--backup')
    parser.add_argument('--install-dir')
    parser.add_argument('--wait-pid',type=int,default=0)
    parser.add_argument('--restart-executable')
    parser.add_argument('--no-restart',action='store_true')
    args=parser.parse_args()
    try:
        if args.command=='inspect':
            if not args.package:parser.error('--package required for inspect')
            result=inspect_package(args.package)
        elif args.command=='apply':
            if not args.install_dir or not args.package:parser.error('--package and --install-dir required')
            result=apply_package(args.package,args.install_dir,args.wait_pid,args.restart_executable,args.no_restart)
        else:
            if not args.install_dir or not args.backup:parser.error('--backup and --install-dir required')
            result=restore_previous(args.install_dir,args.backup,args.wait_pid,args.restart_executable,args.no_restart)
        log_result('SUCCESS: '+str(result))
        print(result)
    except Exception as exc:
        log_result(f'ERROR: {type(exc).__name__}: {exc}')
        print(f'Update error: {exc}',file=sys.stderr)
        return 1
    return 0

if __name__=='__main__':
    raise SystemExit(main())
