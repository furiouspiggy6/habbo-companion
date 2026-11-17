"""Windows smoke test for real Playwright + existing Chromium CDP connection.

This uses a synthetic HTML form loaded via page.set_content. It never opens
Habbo.com, submits real credentials, or accesses any external account.
"""
from pathlib import Path
import os
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright


ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def browser_path():
    choices=[]
    for env in ('PROGRAMFILES(X86)','PROGRAMFILES','LOCALAPPDATA'):
        root=os.environ.get(env)
        if root:
            choices.extend([
                Path(root)/'Microsoft/Edge/Application/msedge.exe',
                Path(root)/'Google/Chrome/Application/chrome.exe',
                Path(root)/'BraveSoftware/Brave-Browser/Application/brave.exe',
            ])
    choices.extend(Path(p) for name in ('msedge.exe','chrome.exe','brave.exe')
                   if (p:=shutil.which(name)))
    return next((p for p in choices if p.is_file()),None)


def free_port():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def main():
    executable=browser_path()
    if executable is None:
        raise RuntimeError('A system Chromium browser is missing from Windows runner.')
    app=runpy.run_path(str(ROOT/'Habbo_Companion.pyw'),
                       run_name='companion_playwright_smoke')
    with tempfile.TemporaryDirectory() as temp:
        port=free_port()
        command=[
            str(executable),f'--user-data-dir={temp}',
            '--remote-debugging-address=127.0.0.1',
            f'--remote-debugging-port={port}','--headless=new',
            '--no-first-run','--no-default-browser-check','about:blank'
        ]
        process=subprocess.Popen(command,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(75):
                try:
                    with opener.open(
                        f'http://127.0.0.1:{port}/json/version',
                        timeout=1) as res:
                        if res.status==200:
                            break
                except (OSError,ValueError):
                    time.sleep(0.2)
            else:
                raise RuntimeError('CDP port did not open for managed Chromium.')

            with sync_playwright() as playwright:
                browser=playwright.chromium.connect_over_cdp(
                    f'http://127.0.0.1:{port}',timeout=15000)
                context=browser.contexts[0]
                page=context.new_page()
                page.set_content("""
                <html><body>
                  <button style="display:none">Let's Go!</button>
                  <div role="dialog">
                    <form id="login">
                      <input type="email" aria-label="Email">
                      <input type="password" aria-label="Password">
                      <button type="submit">Let's Go!</button>
                    </form>
                  </div>
                  <button id="play" style="display:none">PLAY</button>
                  <script>
                    window.testSubmits=0;
                    document.querySelector('form').addEventListener('submit',
                      e=>{e.preventDefault();window.testSubmits++;
                          document.getElementById('login').hidden=true;
                          document.getElementById('play').style.display='block';});
                  </script>
                </body></html>
                """)
                form=app['account_playwright_login_form'](page)
                assert form is not None, 'Playwright failed to locate visible login form'
                email,password,submit=form
                email.fill('example@test.invalid')
                password.fill('synthetic-password')
                submit.click(timeout=5000)
                assert page.evaluate('window.testSubmits')==1, (
                    'The selected button did not invoke the real form handler')
                play=app['account_playwright_control'](page,'play')
                assert play is not None, 'Playwright failed to find PLAY after login'
                print('Playwright real-browser CDP + locator integration: PASS')
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)


if __name__=='__main__':
    main()
