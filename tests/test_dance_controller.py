"""Offline tests for Habbo Companion's Dance Controller.

AST-extracted methods use fake packets and event scheduling only. No G-Earth
process, network connection, browser, or actual Habbo requests are made.
"""
import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace, MethodType
import unittest

SOURCE=Path(__file__).resolve().parent.parent/'Habbo_Companion.pyw'
SRC=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(SRC)
APP=next(n for n in TREE.body if isinstance(n,ast.ClassDef)
         and n.name=='ChatOverlayApp')
CONSTANT='DANCE_STYLE_NAMES'
HELPERS=('dance_packet_expression','dance_cycle_sequence')
METHODS=('_send_dance_action','_play_selected_dance','_start_dance_cycle',
         '_dance_tick','_stop_dance_cycle','_stop_dance_and_cycle')
NS={'datetime':datetime,'tk':SimpleNamespace(TclError=RuntimeError)}
node=next(n for n in TREE.body if isinstance(n,ast.Assign)
          and any(isinstance(t,ast.Name) and t.id==CONSTANT for t in n.targets))
exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),NS)
for name in HELPERS:
    node=next(n for n in TREE.body if isinstance(n,ast.FunctionDef)
              and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),NS)
for name in METHODS:
    node=next(n for n in APP.body if isinstance(n,ast.FunctionDef)
              and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),NS)


class Var:
    def __init__(self,value=''):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


class Packet:
    def is_incomplete_packet(self):return False
    def is_corrupted(self):return False


class Extension:
    def __init__(self):
        self.expressions=[]
        self.sent=[]
        self.invalid=False
        self.reject=False
    def string_to_packet(self,expression):
        self.expressions.append(expression)
        return None if self.invalid else Packet()
    def send_to_server(self,packet):
        if self.reject:return False
        self.sent.append(packet)
        return True


class Root:
    def __init__(self):
        self.tasks={}
        self.cancelled=[]
        self.next_id=0
    def after(self,delay,callback):
        self.next_id+=1
        self.tasks[self.next_id]=(delay,callback)
        return self.next_id
    def after_cancel(self,id):
        self.cancelled.append(id)
        self.tasks.pop(id,None)


def fake_app():
    a=SimpleNamespace(
        root=Root(),config={},
        packet_started=True,packet_extension=Extension(),
        _habbo_session_connected=True,packet_active=True,packets=[],
        dance_status_var=Var(),dance_style_var=Var('Hab-Hop (everyone)'),
        dance_delay_var=Var('3000'),
        dance_enabled_vars={i:Var(True) for i in (1,2,3,4)},
        _dance_running=False,_dance_generation=0,_dance_after_id=None,
        _dance_sequence=(),_dance_step=0,_dance_sent=0,
        _dance_interval_ms=3000,_dance_last_sent_id=None,
        save=lambda:None,_packet_put=lambda e:a.packets.append(e))
    for name in METHODS:
        setattr(a,name,MethodType(NS[name],a))
    return a


class DanceControllerTests(unittest.TestCase):
    def test_exact_named_packet_for_known_dances_only(self):
        self.assertEqual([NS['dance_packet_expression'](i) for i in range(5)],
            ['{out:Dance}{i:0}','{out:Dance}{i:1}',
             '{out:Dance}{i:2}','{out:Dance}{i:3}',
             '{out:Dance}{i:4}'])
        for invalid in (True,False,-1,5,17,1.0,'1',None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    NS['dance_packet_expression'](invalid)

    def test_all_four_styles_and_hc_labels(self):
        labels=NS['DANCE_STYLE_NAMES']
        self.assertEqual([labels[i] for i in range(1,5)],
            ['Hab-Hop (everyone)','Pogo Mogo (Habbo Club)',
             'Duck Funk (Habbo Club)','The Rollie (Habbo Club)'])
        self.assertEqual(labels[0],'Stop dancing')

    def test_cycle_sequence_requires_two_valid_styles(self):
        f=NS['dance_cycle_sequence']
        self.assertEqual(f({4:True,2:True,123:True}),(2,4))
        self.assertEqual(f({1:True,2:True,3:True,4:True}),(1,2,3,4))
        for invalid in ({1:True},{},{0:True,4:True},None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):f(invalid)

    def test_manual_dance_and_hc_option_use_same_packet(self):
        a=fake_app()
        for style_id in (1,2,3,4):
            a.dance_style_var.set(NS['DANCE_STYLE_NAMES'][style_id])
            a._play_selected_dance()
        self.assertEqual(a.packet_extension.expressions,[
            NS['dance_packet_expression'](i) for i in (1,2,3,4)])
        self.assertEqual(a._dance_last_sent_id,4)
        self.assertEqual(a._dance_sent,4)
        self.assertEqual(len(a.packets),4)
        self.assertTrue(all(event[0]=='dance_local' for event in a.packets))
        self.assertIn('unverified',a.dance_status_var.get())
        self.assertFalse(a._dance_running)

    def test_cycle_order_and_period(self):
        a=fake_app()
        a.dance_enabled_vars[2].set(False)
        a.dance_enabled_vars[4].set(False)
        a.dance_delay_var.set('2000')
        a._start_dance_cycle()
        self.assertTrue(a._dance_running)
        self.assertEqual(a._dance_sequence,(1,3))
        self.assertEqual(a.root.tasks[a._dance_after_id][0],0)
        gen=a._dance_generation
        for _ in range(5):a._dance_tick(gen)
        self.assertEqual(a.packet_extension.expressions,[
            '{out:Dance}{i:1}','{out:Dance}{i:3}',
            '{out:Dance}{i:1}','{out:Dance}{i:3}',
            '{out:Dance}{i:1}'])
        self.assertEqual(a.root.tasks[a._dance_after_id][0],2000)
        self.assertEqual(a.config['dance_cycle_selected'],[1,3])
        self.assertEqual(a._dance_sent,5)
        self.assertIn('2 complete',a.dance_status_var.get())

    def test_invalid_period_is_rejected_and_no_request_sent(self):
        for raw in ('0','1','999','-1','60001','1.5','none','nan',''):
            with self.subTest(raw=raw):
                a=fake_app();a.dance_delay_var.set(raw)
                a._start_dance_cycle()
                self.assertFalse(a._dance_running)
                self.assertEqual(a.packet_extension.sent,[])
        a=fake_app()
        for i in (2,3,4):a.dance_enabled_vars[i].set(False)
        a._start_dance_cycle()
        self.assertFalse(a._dance_running)
        self.assertIn('at least two',a.dance_status_var.get())

    def test_connection_required_for_manual_and_cycle(self):
        a=fake_app()
        a._habbo_session_connected=False
        a._play_selected_dance()
        a._start_dance_cycle()
        self.assertFalse(a._dance_running)
        self.assertEqual(a.packet_extension.sent,[])

    def test_stop_button_sends_stop_packet_and_cancels_timer(self):
        a=fake_app()
        a._start_dance_cycle()
        gen=a._dance_generation
        a._dance_tick(gen)
        pending=a._dance_after_id
        a._stop_dance_and_cycle()
        self.assertFalse(a._dance_running)
        self.assertIn(pending,a.root.cancelled)
        self.assertEqual(a.packet_extension.expressions[-1],
                         '{out:Dance}{i:0}')
        old_count=len(a.packet_extension.expressions)
        a._dance_tick(gen)
        self.assertEqual(len(a.packet_extension.expressions),old_count)
        self.assertIn('STOP Dance(0)',a.dance_status_var.get())

    def test_manual_selection_interrupts_cycle(self):
        a=fake_app()
        a._start_dance_cycle()
        a.dance_style_var.set('Duck Funk (Habbo Club)')
        a._play_selected_dance()
        self.assertFalse(a._dance_running)
        self.assertEqual(a.packet_extension.expressions,['{out:Dance}{i:3}'])

    def test_disconnected_stop_sends_no_packets(self):
        a=fake_app()
        a._start_dance_cycle()
        a._habbo_session_connected=False
        a._dance_tick(a._dance_generation)
        self.assertFalse(a._dance_running)
        self.assertEqual(a.packet_extension.sent,[])
        a._stop_dance_and_cycle()
        self.assertEqual(a.packet_extension.sent,[])
        self.assertIn('could not request dance stop',a.dance_status_var.get())

    def test_failed_packet_stops_loop(self):
        for flag in ('invalid','reject'):
            with self.subTest(flag=flag):
                a=fake_app()
                a._start_dance_cycle()
                setattr(a.packet_extension,flag,True)
                a._dance_tick(a._dance_generation)
                self.assertFalse(a._dance_running)
                self.assertEqual(a._dance_sent,0)
                self.assertEqual(a.packets,[])

    def test_stop_cancels_callback_and_no_automatic_dance(self):
        a=fake_app()
        self.assertFalse(a._dance_running)
        self.assertEqual(a.packet_extension.sent,[])
        a._start_dance_cycle()
        pending=a._dance_after_id
        gen=a._dance_generation
        a._stop_dance_cycle()
        self.assertIn(pending,a.root.cancelled)
        a._dance_tick(gen)
        self.assertEqual(a.packet_extension.sent,[])
        self.assertEqual(a._dance_sent,0)

    def test_integration_hooks_and_packet_viewer(self):
        self.assertIn("'dance':('Dance Controller'",SRC)
        self.assertIn("self._make_dance_panel(",SRC)
        self.assertIn("self._stop_dance_cycle('Room changed",SRC)
        self.assertIn("self._stop_dance_cycle('Habbo disconnected",SRC)
        self.assertIn("self._stop_dance_cycle('Companion closed",SRC)
        self.assertIn("'dance_local':'Dance Controller'",SRC)


if __name__=='__main__':
    unittest.main()
