"""GUI-free tests for the integrated G-Earth auto-attach and coffee queue."""
import ast
from pathlib import Path
import time
from types import SimpleNamespace
import unittest

SOURCE=Path(__file__).resolve().parent.parent/'Habbo_Companion.pyw'
tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ChatOverlayApp')
needed={'_maybe_auto_connect_packet_tools','_check_queued_coffee_start','_stop_coffee_loop'}
selected=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in needed]
assert {n.name for n in selected}==needed
namespace={'time':time}
exec(compile(ast.Module(body=selected,type_ignores=[]),str(SOURCE),'exec'),namespace)


class RecordingValue:
    def __init__(self):self.value=''
    def set(self,value):self.value=value


class FakeRoot:
    def __init__(self):
        self.scheduled=[]
        self.cancelled=[]
    def winfo_id(self):return 1
    def after(self,delay,callback):
        self.scheduled.append((delay,callback))
        return len(self.scheduled)
    def after_cancel(self,token):self.cancelled.append(token)


class AutoConnectTests(unittest.TestCase):
    def fake(self,window=None,room=None):
        calls=[]
        fake=SimpleNamespace(
            packet_started=False,_packet_auto_retry_after=0.0,
            tracker=SimpleNamespace(find=lambda excluded:window),
            root=FakeRoot(),overlay=SimpleNamespace(winfo_id=lambda:2),
            room_id=room,packet_connection_status=RecordingValue(),
            _connect_gearth=lambda capture:calls.append(capture))
        return fake,calls

    def test_auto_attaches_before_habbo_launch_without_enabling_capture(self):
        fake,calls=self.fake()
        namespace['_maybe_auto_connect_packet_tools'](fake)
        self.assertEqual(calls,[False])

    def test_defer_during_loading_screen(self):
        fake,calls=self.fake(window=('game',),room=None)
        namespace['_maybe_auto_connect_packet_tools'](fake)
        self.assertEqual(calls,[])
        self.assertIn('waiting',fake.packet_connection_status.value)

    def test_attach_with_room_evidence(self):
        fake,calls=self.fake(window=('game',),room=123)
        namespace['_maybe_auto_connect_packet_tools'](fake)
        self.assertEqual(calls,[False])

    def test_no_duplicate_or_early_retry(self):
        fake,calls=self.fake()
        fake.packet_started=True
        namespace['_maybe_auto_connect_packet_tools'](fake)
        fake.packet_started=False
        fake._packet_auto_retry_after=time.monotonic()+60
        namespace['_maybe_auto_connect_packet_tools'](fake)
        self.assertEqual(calls,[])

    def test_queued_start_only_when_session_is_connected(self):
        fake=SimpleNamespace(
            _coffee_queue_after_id=45,_coffee_start_queued=True,
            _coffee_generation=4,packet_started=True,
            packet_extension=object(),_habbo_session_connected=False,
            _coffee_queue_deadline=time.monotonic()+10,root=FakeRoot(),
            coffee_status_var=RecordingValue(),_start_coffee_loop=lambda:None)
        namespace['_check_queued_coffee_start'](fake,4)
        self.assertEqual(fake.root.scheduled[0][0],350)
        calls=[]
        fake._start_coffee_loop=lambda:calls.append(True)
        fake._habbo_session_connected=True
        namespace['_check_queued_coffee_start'](fake,4)
        self.assertEqual(calls,[True])
        self.assertFalse(fake._coffee_start_queued)

    def test_stop_cancels_pending_start_and_repeat(self):
        fake=SimpleNamespace(
            _coffee_running=True,_coffee_start_queued=True,
            _coffee_generation=7,_coffee_queue_after_id=1,
            _coffee_after_id=2,root=FakeRoot(),
            coffee_status_var=RecordingValue(),_coffee_sent=0,
            _coffee_completed=0)
        # Same scheduling cancellation and stop semantics, without Tk.
        import sys
        fake_tk=SimpleNamespace(TclError=RuntimeError)
        namespace['_stop_coffee_loop'].__globals__['tk']=fake_tk
        namespace['_stop_coffee_loop'](fake,'Stopped')
        self.assertFalse(fake._coffee_running)
        self.assertFalse(fake._coffee_start_queued)
        self.assertEqual(fake.root.cancelled,[1,2])
        self.assertEqual(fake._coffee_generation,8)


if __name__=='__main__':
    unittest.main()
