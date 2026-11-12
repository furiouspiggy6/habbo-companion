"""Native HabboAir launch confirmation avoids false Classic-button stalls.

No real Habbo, credentials, browser cookies or Windows process access.
"""
import ast
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
CODE=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
names={'account_is_native_habbo_window',
       'account_wait_for_new_native_window'}
FUNCS=[n for n in TREE.body if isinstance(n,ast.FunctionDef)
       and n.name in names]
CLASS=next(n for n in TREE.body if isinstance(n,ast.ClassDef)
           and n.name=='ChatOverlayApp')
WORKER=next(n for n in CLASS.body if isinstance(n,ast.FunctionDef)
            and n.name=='_account_auto_worker')


class NativeGameWindowDetection(unittest.TestCase):
    def test_exact_habbo_air_plus_window_title_from_user_screen(self):
        space={'re':re}
        exec(compile(ast.Module(body=FUNCS[:1],type_ignores=[]),
                     str(SOURCE),'exec'),space) if FUNCS[0].name=='account_is_native_habbo_window' else None
        title=next(n for n in FUNCS if n.name=='account_is_native_habbo_window')
        space={'re':re}
        exec(compile(ast.Module(body=[title],type_ignores=[]),
                     str(SOURCE),'exec'),space)
        is_game=space['account_is_native_habbo_window']
        for name in ('HabboAirPlus [OOM] | dan.alt100',
                     'HabboAirPlus [OOM] d277',
                     'HabboAir | another_avatar'):
            self.assertTrue(is_game(name),name)
        for name in ('Habbo - Virtual World, Avatar Chat - Brave',
                     'Habbo Launcher',
                     'Habbo Companion',
                     'HabboAirPlusXYZ',
                     '', 'Chrome - HabboAirPlus'):
            self.assertFalse(is_game(name),name)

    def test_only_a_new_hwnd_pid_pair_counts(self):
        wait=next(n for n in FUNCS if n.name=='account_wait_for_new_native_window')
        state=[frozenset({(123,450)}),frozenset({(123,450),(124,451)})]
        ns={'time':SimpleNamespace(monotonic=lambda:0.0,sleep=lambda _:None),
            'account_native_client_windows':lambda:state.pop(0)}
        exec(compile(ast.Module(body=[wait],type_ignores=[]),
                     str(SOURCE),'exec'),ns)
        self.assertTrue(ns['account_wait_for_new_native_window'](
            frozenset({(123,450)}),2))
        ns['account_native_client_windows']=lambda:frozenset({(123,450)})
        ns['time']=SimpleNamespace(monotonic=lambda:0,sleep=lambda _:None)
        self.assertFalse(ns['account_wait_for_new_native_window'](
            frozenset({(123,450)}),0))
        self.assertFalse(ns['account_wait_for_new_native_window'](None,2))

    def test_screenshot_case_game_directly_opened_continue_alt_automatically(self):
        first={'id':'ab1234567890','label':'Account 1','port':9092,
               'url':'https://www.habbo.com/'}
        second={'id':'cd1234567890','label':'Account 2','port':9093,
                'url':'https://www.habbo.com/'}
        events=[]
        calls=[]
        selectors=[]
        snapshots=[frozenset(),frozenset({(101,1001)})]
        def play(port,report,credentials=None,login_only=False):
            calls.append(('login' if login_only else 'launch',port))
            return 'signed_in' if login_only else 'launched'
        with tempfile.TemporaryDirectory() as tmp:
            ns={
                'APP_DIR':Path(tmp),
                'account_login_browser':lambda:Path('/fake/brave.exe'),
                'account_browser_debug_port':lambda ident:
                   43000+int(ident,16)%20000,
                'account_browser_pages':lambda port:[{'type':'page'}],
                'account_browser_command':lambda *args:[],
                'account_saved_login_read':lambda ident:
                    ('email@example.com','password-only-for-mock'),
                'account_attempt_auto_play':play,
                'account_native_client_windows':lambda:snapshots.pop(0),
                'account_wait_for_new_native_window':lambda before,seconds=1.5:
                    True,
                'account_select_classic_launcher':lambda seconds:
                    selectors.append(seconds) or False,
                'urllib':SimpleNamespace(error=SimpleNamespace(URLError=OSError)),
                'subprocess':SimpleNamespace(Popen=Mock(),DEVNULL=-1),
                'time':SimpleNamespace(sleep=lambda _:None)
            }
            exec(compile(ast.Module(body=[WORKER],type_ignores=[]),
                         str(SOURCE),'exec'),ns)
            ns['_account_auto_worker'](
                SimpleNamespace(_packet_put=events.append),(first,second),5)

        port1=43000+int(first['id'],16)%20000
        port2=43000+int(second['id'],16)%20000
        self.assertEqual(calls,[('login',port1),('login',port2),
                                ('launch',port1),('launch',port2)])
        self.assertEqual(selectors,[])
        self.assertEqual([e for e in events if e[0]=='account_remaining'],
                         [('account_remaining',5,(),False)])
        status=' '.join(e[-1] for e in events if e[0]=='account_auto_status')
        self.assertIn('new native HabboAir window appeared',status)
        self.assertIn('2 native launch request(s)',status)
        self.assertIn('No multi-account G-Earth packet routing yet.',status)
        self.assertNotIn('password-only-for-mock',status)

    def test_windows_enumerator_is_fail_closed(self):
        # Enumeration is Windows-only and does not assume an avatar identity.
        src=ast.get_source_segment(CODE,next(n for n in TREE.body
            if isinstance(n,ast.FunctionDef) and
            n.name=='account_native_client_windows'))
        self.assertIn("if os.name!='nt':",src)
        self.assertIn('return None',src)
        self.assertIn('GetWindowThreadProcessId',src)
        self.assertIn('account_is_native_habbo_window',src)
        self.assertNotIn('gearth_port',src)
        self.assertNotIn('passphrase',src)


if __name__=='__main__':
    unittest.main()
