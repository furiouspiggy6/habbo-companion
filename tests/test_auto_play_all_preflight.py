"""Batch regression: each saved account login is checked before Classic launch."""
import ast
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
TEXT=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(TEXT)
CLS=next(x for x in TREE.body if isinstance(x,ast.ClassDef)
         and x.name=='ChatOverlayApp')
WORKER=next(x for x in CLS.body if isinstance(x,ast.FunctionDef)
            and x.name=='_account_auto_worker')


class AutoPlayAllBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a={'id':'ab1234567890','label':'Account 1',
                'port':9092,'url':'https://www.habbo.com/'}
        self.b={'id':'cd1234567890','label':'Account 2',
                'port':9093,'url':'https://www.habbo.com/'}
        self.events=[]
        self.calls=[]
        self.launches=[]
        self.selections=[]
        scope={
            'APP_DIR':Path(self.tmp.name),
            'account_login_browser':lambda:Path('/fake/brave.exe'),
            'account_browser_debug_port':lambda i:43000+int(i,16)%20000,
            'account_browser_pages':lambda port:[{'type':'page'}],
            'account_browser_command':lambda *args:[],
            'account_saved_login_read':lambda account_id:(
                'account@example.com','local-placeholder'),
            'account_select_classic_launcher':lambda timeout:(
                self.selections.append(timeout) or True),
            'account_attempt_auto_play':self.fake_play,
            'urllib':SimpleNamespace(error=SimpleNamespace(URLError=OSError)),
            'subprocess':SimpleNamespace(Popen=Mock(),DEVNULL=-1),
            'time':SimpleNamespace(sleep=lambda _:None),
        }
        exec(compile(ast.Module(body=[WORKER],type_ignores=[]),
                     str(SOURCE),'exec'),scope)
        self.worker=scope['_account_auto_worker']
        self.app=SimpleNamespace(_packet_put=self.events.append)

    def fake_play(self,port,report,credentials=None,login_only=False):
        self.calls.append((port,login_only))
        return 'signed_in' if login_only else 'launched'

    def summary(self):
        return ' '.join(event[-1] for event in self.events if
                        event[0]=='account_auto_status')

    def test_all_profiles_open_before_any_classic_launch(self):
        self.worker(self.app,(self.a,self.b),1)
        ports=[43000+int(a['id'],16)%20000 for a in (self.a,self.b)]
        self.assertEqual(self.calls,list(zip(ports,[True,True]))+
                         list(zip(ports,[False,False])))
        self.assertEqual(self.selections,[16,16])
        self.assertIn('2/2 website logins',self.summary())
        self.assertIn('G-Earth routing for additional accounts is NOT automatic.',
                      self.summary())
        self.assertEqual(self.events[-1],('account_auto_finished',1))

    def test_first_login_failure_does_not_prevent_second_browser(self):
        original=self.fake_play
        count=[0]
        def fake(port,report,credentials=None,login_only=False):
            if login_only and count[0]==0:
                count[0]+=1
                return 'login'
            return original(port,report,credentials,login_only)
        self.worker.__globals__['account_attempt_auto_play']=fake
        self.worker(self.app,(self.a,self.b),2)
        self.assertEqual(self.selections,[16])
        self.assertIn('1/2 website logins',self.summary())
        self.assertIn('Account 1 website login not confirmed',self.summary())
        self.assertEqual(self.events[-1],('account_auto_finished',2))

    def test_unresolved_classic_pauses_second_native_launch(self):
        self.worker.__globals__['account_select_classic_launcher']=lambda t:False
        self.worker(self.app,(self.a,self.b),3)
        self.assertEqual(len(self.calls),3)  # two login preflights, one launch
        self.assertIn('remaining native launches paused',self.summary())
        self.assertIn('manual classic selection',self.summary().lower())
        self.assertEqual(self.events[-1],('account_auto_finished',3))

    def test_login_only_just_opens_and_checks_both(self):
        self.worker(self.app,(self.a,self.b),4,login_only=True)
        self.assertEqual(len(self.calls),2)
        self.assertTrue(all(only for _,only in self.calls))
        self.assertFalse(self.selections)
        self.assertEqual(self.events[-1],('account_auto_finished',4))

    def test_ui_explains_g_earth_is_not_multi_proxy(self):
        self.assertIn('G-Earth routing to multiple game clients is NOT yet implemented.',TEXT)
        self.assertIn('account_browser_pages(debug_port)',TEXT)


if __name__=='__main__':
    unittest.main()
