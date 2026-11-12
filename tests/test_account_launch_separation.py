"""The website/Classic account launcher must not be blocked by active G-Earth."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

APP=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
CODE=APP.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
CLS=next(n for n in TREE.body if isinstance(n,ast.ClassDef)
         and n.name=='ChatOverlayApp')
NODE=next(n for n in CLS.body if isinstance(n,ast.FunctionDef)
          and n.name=='_account_auto_play')


class Variable:
    def __init__(self,value=''):
        self.value=value
    def get(self):
        return self.value
    def set(self,new):
        self.value=new


class FakeThread:
    calls=[]
    def __init__(self,*,target,args,daemon):
        self.calls.append((target,args,daemon))
    def start(self):
        pass


scope={'account_browser_debug_port':lambda ident:43000+int(ident,16)%20000,
       'threading':SimpleNamespace(Thread=FakeThread)}
exec(compile(ast.Module(body=[NODE],type_ignores=[]),str(APP),'exec'),scope)


class AccountLaunchSeparationTests(unittest.TestCase):
    def setUp(self):
        FakeThread.calls=[]
        self.selected={'id':'cd1234567890','label':'Alt','port':9093,
                       'url':'https://www.habbo.com/'}
        self.switched=[]
        self.started=[]
        self.obj=SimpleNamespace(
            _account_auto_running=False,
            _account_profiles=[self.selected],
            _account_selected=lambda:self.selected,
            _account_attached_port=9092,
            packet_started=True,
            _account_auto_generation=0,
            _account_run_states={},
            _account_remaining_ids=(),
            _account_resume_requires_manual=False,
            _accounts_render=lambda:None,
            account_status_var=Variable(),
            _account_auto_worker=lambda *_:None,
            _account_use_port=lambda:self.switched.append('selected'),
            _gearth_extension_port_responds=lambda port:False,
            _start_integrated_engine=lambda:self.started.append('engine'))
        self.launch=scope['_account_auto_play']

    def test_launch_alt_does_not_require_g_earth_restart(self):
        self.launch(self.obj)
        self.assertTrue(self.obj._account_auto_running)
        self.assertEqual(len(FakeThread.calls),1)
        self.assertFalse(self.switched)
        self.assertFalse(self.started)
        self.assertEqual(self.obj._account_attached_port,9092)
        self.assertIn('port 9092',self.obj.account_status_var.value)
        self.assertIn('NOT intercept',self.obj.account_status_var.value)
        args=FakeThread.calls[0][1]
        self.assertEqual(args[0][0]['port'],9093)
        self.assertFalse(args[2])  # full Classic flow

    def test_open_login_while_main_proxy_attached(self):
        self.launch(self.obj,login_only=True)
        self.assertEqual(len(FakeThread.calls),1)
        self.assertTrue(FakeThread.calls[0][1][2])
        self.assertFalse(self.switched)
        self.assertEqual(self.obj._account_attached_port,9092)

    def test_launch_main_account_keeps_same_packet_binding(self):
        self.selected['port']=9092
        self.launch(self.obj)
        self.assertEqual(len(FakeThread.calls),1)
        self.assertNotIn('NOT intercept',self.obj.account_status_var.value)
        self.assertFalse(self.switched)

    def test_when_no_packet_attached_full_launch_may_select_port(self):
        self.obj.packet_started=False
        self.launch(self.obj)
        self.assertEqual(self.switched,['selected'])
        self.assertEqual(len(FakeThread.calls),1)
        self.assertFalse(self.started)  # no auto-engine for 9093

    def test_login_only_never_switches_packet_port_even_when_unattached(self):
        self.obj.packet_started=False
        self.launch(self.obj,login_only=True)
        self.assertFalse(self.switched)
        self.assertEqual(len(FakeThread.calls),1)


if __name__=='__main__':
    unittest.main()
