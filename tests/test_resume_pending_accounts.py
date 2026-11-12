"""Resumable Classic batch: never replay a native request already sent."""
import ast
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
TEXT=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(TEXT)
CLS=next(n for n in TREE.body if isinstance(n,ast.ClassDef)
         and n.name=='ChatOverlayApp')
NAMES={'_account_auto_worker','_account_auto_play','_account_resume_pending'}
METHODS={n.name:n for n in CLS.body if isinstance(n,ast.FunctionDef)
         and n.name in NAMES}
FIRST={'id':'ab1234567890','label':'Main','port':9092,
       'url':'https://www.habbo.com/'}
SECOND={'id':'cd1234567890','label':'Alt','port':9093,
        'url':'https://www.habbo.com/'}


class FakeThread:
    calls=[]
    def __init__(self,*,target,args,daemon):
        self.calls.append(args)
    def start(self): pass


class Var:
    def __init__(self):self.value=''
    def set(self,x):self.value=x


class ResumeBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.events=[]
        self.calls=[]
        self.ports={
            FIRST['id']:43000+int(FIRST['id'],16)%20000,
            SECOND['id']:43000+int(SECOND['id'],16)%20000}
        self.login_results={
            self.ports[FIRST['id']]:'signed_in',
            self.ports[SECOND['id']]:'login'}

    def run_worker(self,launch_selected=False,accounts=(FIRST,SECOND)):
        def play(port,report,credentials=None,login_only=False):
            self.calls.append((port,login_only))
            return self.login_results[port] if login_only else 'launched'
        scope={
            'APP_DIR':Path(self.tmp.name),
            'account_login_browser':lambda:Path('/fake/brave.exe'),
            'account_browser_debug_port':lambda i:self.ports[i],
            'account_browser_pages':lambda p:[{'type':'page'}],
            'account_browser_command':lambda *args:[],
            'account_saved_login_read':lambda i:('email@example.com','secret-only-local'),
            'account_attempt_auto_play':play,
            'account_native_client_windows':lambda:frozenset(),
            'account_wait_for_new_native_window':lambda before,seconds=1.5:False,
            'account_select_classic_launcher':lambda t:launch_selected,
            'urllib':SimpleNamespace(error=SimpleNamespace(URLError=OSError)),
            'subprocess':SimpleNamespace(Popen=Mock(),DEVNULL=-1),
            'time':SimpleNamespace(sleep=lambda _:None)}
        exec(compile(ast.Module(body=[METHODS['_account_auto_worker']],
                                type_ignores=[]),str(SOURCE),'exec'),scope)
        app=SimpleNamespace(_packet_put=self.events.append)
        scope['_account_auto_worker'](app,accounts,5)
        self.assertEqual(self.events[-1],('account_auto_finished',5))
        return [e for e in self.events if e[0]=='account_remaining']

    def test_exact_screenshot_case_one_login_one_launch_none_selected(self):
        queued=self.run_worker(launch_selected=False)
        self.assertEqual(queued,[('account_remaining',5,(SECOND['id'],),True)])
        self.assertEqual(self.calls,[
            (self.ports[FIRST['id']],True),
            (self.ports[SECOND['id']],True),
            (self.ports[FIRST['id']],False)])
        self.assertFalse(any('secret-only-local' in str(e) for e in self.events))
        summaries=[e[-1] for e in self.events if e[0]=='account_auto_status']
        self.assertTrue(any('1/2 website logins' in s for s in summaries))
        self.assertTrue(any('Continue unfinished accounts' in s for s in summaries))

    def test_two_authenticated_first_classic_prompt_queues_only_alt(self):
        self.login_results[self.ports[SECOND['id']]]='signed_in'
        queued=self.run_worker(launch_selected=False)
        self.assertEqual(queued,[('account_remaining',5,(SECOND['id'],),True)])
        self.assertNotIn((self.ports[SECOND['id']],False),self.calls)

    def test_successful_classic_still_queues_failed_signin_only(self):
        queued=self.run_worker(launch_selected=True)
        self.assertEqual(queued,[('account_remaining',5,(SECOND['id'],),False)])

    def test_resume_only_queues_unfinished_account_without_switching_gearth(self):
        FakeThread.calls=[]
        ns={'account_browser_debug_port':lambda i:self.ports[i],
            'threading':SimpleNamespace(Thread=FakeThread)}
        exec(compile(ast.Module(body=[METHODS['_account_auto_play']],
                                type_ignores=[]),str(SOURCE),'exec'),ns)
        switched=[]
        app=SimpleNamespace(
            _account_auto_running=False,
            _account_profiles=[FIRST,SECOND],
            _account_remaining_ids=(SECOND['id'],),
            _account_resume_requires_manual=True,
            _account_selected=lambda:FIRST,
            packet_started=True,_account_attached_port=9092,
            _account_auto_generation=0,_account_run_states={},
            _accounts_render=lambda:None,
            account_status_var=Var(),
            _account_auto_worker=lambda *_:None,
            _account_use_port=lambda:switched.append('changed'),
            _gearth_extension_port_responds=lambda p:True,
            _start_integrated_engine=lambda:None)
        ns['_account_auto_play'](app,remaining_only=True)
        self.assertEqual(len(FakeThread.calls),1)
        self.assertEqual([a['id'] for a in FakeThread.calls[0][0]],[SECOND['id']])
        self.assertEqual(switched,[])
        self.assertEqual(app._account_attached_port,9092)

    def test_resume_requires_confirmation_when_previous_prompt_pending(self):
        ns={'messagebox':SimpleNamespace(askyesno=lambda *args,**kw:False)}
        exec(compile(ast.Module(body=[METHODS['_account_resume_pending']],
                                type_ignores=[]),str(SOURCE),'exec'),ns)
        called=[]
        app=SimpleNamespace(_account_auto_running=False,
                            _account_remaining_ids=(SECOND['id'],),
                            _account_resume_requires_manual=True,
                            _account_auto_play=lambda **kwargs:called.append(kwargs),
                            root=object(),
                            account_status_var=Var())
        ns['_account_resume_pending'](app)
        self.assertEqual(called,[])
        ns['messagebox']=SimpleNamespace(askyesno=lambda *args,**kw:True)
        ns['_account_resume_pending'](app)
        self.assertEqual(called,[{'remaining_only':True}])

    def test_queue_event_updates_only_matching_generation(self):
        node=next(n for n in CLS.body if isinstance(n,ast.FunctionDef)
                  and n.name=='_pump_packets')
        src=ast.get_source_segment(TEXT,node)
        self.assertIn("if item[0]=='account_remaining':",src)
        self.assertIn("if item[1]==self._account_auto_generation:",src)
        self.assertIn("self._account_remaining_ids=tuple(item[2])",src)


if __name__=='__main__':
    unittest.main()
