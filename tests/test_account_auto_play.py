"""Regression tests for one-click authenticated Habbo Play -> Launcher flow.

Offline only: tests never navigate to Habbo or read browser cookies.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import re
from unittest.mock import Mock

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
CODE=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
names={'account_browser_debug_port','account_browser_command',
       'account_attempt_auto_play','account_inspect_play_page',
       'account_click_play_button','account_select_classic_launcher'}
funcs=[x for x in TREE.body if isinstance(x,ast.FunctionDef) and x.name in names]
scope={'re':re,'Path':Path}
exec(compile(ast.Module(body=funcs,type_ignores=[]),str(SOURCE),'exec'),scope)
import urllib.parse
scope['validate_habbo_login_url']=lambda url: str(url)

class AccountAutoPlayTests(unittest.TestCase):
    def test_browser_control_port_is_profile_specific_stable(self):
        a=scope['account_browser_debug_port']('ab1234567890')
        b=scope['account_browser_debug_port']('cd1234567890')
        self.assertTrue(43000<=a<63000)
        self.assertNotEqual(a,b)
        self.assertEqual(a,scope['account_browser_debug_port']('ab1234567890'))
        for value in ('bad', '../../secrets'):
            with self.assertRaises(ValueError):
                scope['account_browser_debug_port'](value)

    def test_launch_uses_local_debugging_with_isolated_profile(self):
        args=scope['account_browser_command'](
            'C:/Browser/brave.exe','C:/AccountProfiles/ab1234567890',
            'https://www.habbo.com/',debug_port=44321)
        self.assertIn('--remote-debugging-address=127.0.0.1',args)
        self.assertIn('--remote-debugging-port=44321',args)
        self.assertIn('--new-window',args)
        self.assertIn('--user-data-dir=C:/AccountProfiles/ab1234567890',args)
        self.assertNotIn('--incognito',args)
        self.assertEqual(args[-1],'https://www.habbo.com/')

    def test_cdp_refuses_external_endpoints_even_with_valid_command(self):
        import urllib.parse, socket, base64, os, hashlib, struct, json
        node=next(x for x in TREE.body if isinstance(x,ast.FunctionDef)
                  and x.name=='account_cdp_call')
        local={'urllib':SimpleNamespace(parse=urllib.parse),
               'socket':socket,'base64':base64,'os':os,
               'hashlib':hashlib,'struct':struct,'json':json}
        exec(compile(ast.Module(body=[node],type_ignores=[]),
                     str(SOURCE),'exec'),local)
        fn=local['account_cdp_call']
        for endpoint in ('ws://evil.example/devtools/page/abc',
                         'wss://127.0.0.1/devtools/page/abc',
                         'ws://127.0.0.1:9092/extension',
                         'ws://127.0.0.1:43000/other'):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    fn(endpoint,'Runtime.evaluate',{})

    def test_habbo_js_is_domain_scoped_and_no_password_access(self):
        js=next(x for x in TREE.body if isinstance(x,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='HABBO_AUTO_PLAY_JS'
                        for t in x.targets))
        text=ast.literal_eval(js.value)
        self.assertIn(r'/(^|\.)habbo\.com$/i',text)
        self.assertIn('input[type=password]',text)
        self.assertIn("return {kind:'login'}",text)
        self.assertIn('launch and log in',text)
        self.assertNotIn('document.cookie',text)
        self.assertNotIn('.value=',text)

    def test_saved_session_clicks_play_then_launch(self):
        scope['account_habbo_page']=lambda port:{
            'url':'https://www.habbo.com/',
            'webSocketDebuggerUrl':'ws://127.0.0.1:44321/devtools/page/abc'}
        steps=iter([{'kind':'play-now','label':'Play Now!','x':120,'y':220,'page':'/'},
                    {'kind':'launch','label':'Launch and log in',
                     'x':45,'y':60,'page':'/client'}])
        scope['account_inspect_play_page']=lambda url:next(steps)
        clicks=[]
        scope['account_click_play_button']=lambda url,step:clicks.append(step['kind'])
        scope['time']=SimpleNamespace(sleep=lambda _:None)
        outputs=[]
        self.assertEqual(scope['account_attempt_auto_play'](44321,outputs.append),
                         'launched')
        self.assertEqual(clicks,['play-now','launch'])
        self.assertIn('Launch and log in',outputs[-1])

    def test_unknown_login_stops_and_never_clicks(self):
        scope['account_habbo_page']=lambda port:{
            'url':'https://www.habbo.com/login',
            'webSocketDebuggerUrl':'ws://127.0.0.1:44321/devtools/page/abc'}
        scope['account_inspect_play_page']=lambda url:{'kind':'login'}
        clicks=[]
        scope['account_click_play_button']=lambda url,step:clicks.append(step)
        outputs=[]
        self.assertEqual(scope['account_attempt_auto_play'](44321,outputs.append),
                         'login')
        self.assertEqual(clicks,[])
        self.assertIn('Sign in once',outputs[-1])

    def test_no_cross_account_port_switch_and_powershell_only_known_window(self):
        self.assertIn('account_browser_debug_port(account[',CODE)
        self.assertIn("self._account_auto_running=True",CODE)
        self.assertIn("text='Auto Play selected'",CODE)
        self.assertIn("text='Auto Play all saved accounts'",CODE)
        self.assertIn('if account[\'port\']!=self._account_attached_port:',CODE)
        self.assertIn('if ($title -notmatch',CODE)
        self.assertIn("if ($button.Current.Name -ne 'Classic'",CODE)
        self.assertIn("if len(accounts)>1:break",CODE)
        self.assertIn("('account_auto_finished',generation)",CODE)

if __name__=='__main__':
    unittest.main()
