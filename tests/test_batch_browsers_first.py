"""Regression for launching every isolated browser before slow authentication."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
CODE=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
CLS=next(x for x in TREE.body if isinstance(x,ast.ClassDef)
         and x.name=='ChatOverlayApp')
WORKER=next(x for x in CLS.body if isinstance(x,ast.FunctionDef)
            and x.name=='_account_auto_worker')
ACCOUNTS=[
    {'id':'ab1234567890','label':'Main','port':9092,
     'url':'https://www.habbo.com/'},
    {'id':'cd1234567890','label':'Alt','port':9093,
     'url':'https://www.habbo.com/'}
]


class BatchBrowserFirst(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.events=[]
        self.opened=[]
        self.port1=43000+int(ACCOUNTS[0]['id'],16)%20000
        self.port2=43000+int(ACCOUNTS[1]['id'],16)%20000

    def run_worker(self,first_result='signed_in',second_result='signed_in'):
        result_map={self.port1:first_result,self.port2:second_result}
        started=set()
        calls=[]

        def pages(port):
            if port not in started:
                raise OSError('The profile browser is not launched')
            return [{'type':'page'}]

        def popen(cmd,**kwargs):
            port=int(next(x.split('=',1)[1] for x in cmd
                          if x.startswith('--remote-debugging-port=')))
            started.add(port)
            self.opened.append(port)
            self.events.append(('browser_opened',port))
            return Mock()

        def play(port,report,credentials=None,login_only=False):
            if login_only:
                self.events.append(('login_checked',port))
                return result_map[port]
            self.events.append(('classic_requested',port))
            return 'launched'

        scope={
            'APP_DIR':Path(self.tmp.name),
            'account_login_browser':lambda:Path('/fake/brave.exe'),
            'account_browser_debug_port':lambda i:43000+int(i,16)%20000,
            'account_browser_pages':pages,
            'account_browser_command':lambda browser,folder,url,port:[
                'brave.exe','--remote-debugging-port='+str(port),'--new-window',url],
            'account_saved_login_read':lambda i:('example@example.com','test-only'),
            'account_attempt_auto_play':play,
            'account_native_client_windows':lambda:frozenset(),
            'account_wait_for_new_native_window':lambda before,seconds=1.5:False,
            'account_select_classic_launcher':lambda timeout:True,
            'time':SimpleNamespace(sleep=lambda _:None),
            'urllib':SimpleNamespace(error=SimpleNamespace(URLError=OSError)),
            'subprocess':SimpleNamespace(Popen=popen,DEVNULL=-1),
        }
        exec(compile(ast.Module(body=[WORKER],type_ignores=[]),
                     str(SOURCE),'exec'),scope)
        obj=SimpleNamespace(_packet_put=self.events.append)
        scope['_account_auto_worker'](obj,tuple(ACCOUNTS),1)

    def test_both_browser_windows_requested_before_first_login(self):
        self.run_worker()
        relevant=[e[0] for e in self.events
                  if e[0] in ('browser_opened','login_checked')]
        self.assertEqual(relevant[:3],
                         ['browser_opened','browser_opened','login_checked'])
        self.assertEqual(self.opened,[self.port1,self.port2])
        self.assertIn(('classic_requested',self.port2),self.events)
        self.assertEqual(self.events[-1],('account_auto_finished',1))

    def test_first_account_failed_login_does_not_prevent_alt(self):
        self.run_worker(first_result='login')
        self.assertEqual(self.opened,[self.port1,self.port2])
        self.assertIn(('login_checked',self.port2),self.events)
        self.assertIn(('classic_requested',self.port2),self.events)
        stages=[e for e in self.events if e[0]=='account_auto_stage']
        self.assertIn(( 'account_auto_stage',1,ACCOUNTS[0]['id'],
                        'Sign-in / verification required'),stages)
        self.assertIn(( 'account_auto_stage',1,ACCOUNTS[1]['id'],
                        'Classic selected; client unverified'),stages)

    def test_ui_per_account_status_and_not_fake_proxy(self):
        self.assertIn("('launch_state','Browser / Classic status',340)",CODE)
        self.assertIn("self.account_table.set(item[2],'launch_state',item[3])",CODE)
        self.assertIn("if account_select_classic_launcher(16):",CODE)
        self.assertIn("No multi-account G-Earth packet routing yet.",CODE)


if __name__=='__main__':
    unittest.main()
