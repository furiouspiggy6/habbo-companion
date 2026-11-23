"""Regression tests for Habbo Companion's captured-look Outfit Cycler.

Tests are intentionally offline: no Habbo account, G-Earth proxy or packets
are sent. The real application methods are extracted from the .pyw AST.
"""
import ast
from datetime import datetime
import json
import math
from pathlib import Path
import re
from types import MethodType, SimpleNamespace
import unittest

SOURCE=Path(__file__).resolve().parent.parent/'Habbo_Companion.pyw'
TREE=ast.parse(SOURCE.read_text(encoding='utf-8'))
APP=next(node for node in TREE.body if isinstance(node,ast.ClassDef)
         and node.name=='ChatOverlayApp')

HELPERS=('parse_outfit_update_expression','outfit_update_expression',
         'sanitize_outfit_presets')
METHODS=('_arm_outfit_capture','_outfit_capture_timeout',
         '_receive_outfit_capture','_remove_outfit',
         '_start_outfit_cycle','_outfit_tick','_stop_outfit_cycle')
NAMESPACE={'re':re,'json':json,'math':math,'datetime':datetime,
           'tk':SimpleNamespace(TclError=RuntimeError)}
for name in HELPERS:
    node=next(node for node in TREE.body if isinstance(node,ast.FunctionDef)
              and node.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),
         NAMESPACE)
for name in METHODS:
    node=next(node for node in APP.body if isinstance(node,ast.FunctionDef)
              and node.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),
         NAMESPACE)


FIGURE_A='hd-180-1.hr-100-42.ch-210-92.lg-280-1427'
FIGURE_B='hd-180-1.hr-110-42.ch-215-92.lg-290-1427'


class Var:
    def __init__(self,value=''):
        self.value=value
    def set(self,value):
        self.value=value
    def get(self):
        return self.value


class MockPacket:
    def is_incomplete_packet(self):
        return False
    def is_corrupted(self):
        return False


class MockExtension:
    def __init__(self):
        self.expressions=[]
        self.sent=[]
        self.reject=False
    def string_to_packet(self,expression):
        self.expressions.append(expression)
        return MockPacket()
    def send_to_server(self,packet):
        self.sent.append(packet)
        return not self.reject


class MockRoot:
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
    root=MockRoot()
    extension=MockExtension()
    app=SimpleNamespace(
        root=root,packet_started=True,
        packet_extension=extension,_habbo_session_connected=True,
        outfit_status_var=Var(),outfit_delay_var=Var('0.3'),
        outfit_presets=[
            {'gender':'M','figure':FIGURE_A},
            {'gender':'M','figure':FIGURE_B}],
        config={},packet_active=True,packets=[],
        _outfit_capture_pending=False,_outfit_capture_generation=0,
        _outfit_running=False,_outfit_generation=0,
        _outfit_after_id=None,_outfit_index=0,_outfit_sent=0,
        _outfit_interval=0.3,
        save=lambda:None,_render_outfit_presets=lambda:None,
        _packet_put=lambda item:app.packets.append(item))
    for name in METHODS:
        setattr(app,name,MethodType(NAMESPACE[name],app))
    return app


class OutfitCyclerTests(unittest.TestCase):
    def test_only_known_figure_packet_is_accepted(self):
        parse=NAMESPACE['parse_outfit_update_expression']
        expr=NAMESPACE['outfit_update_expression']('M',FIGURE_A)
        self.assertEqual(parse(expr),('M',FIGURE_A))
        self.assertIsNone(parse(
            '{out:SaveWardrobeOutfit}{s:"M"}{s:"'+FIGURE_A+'"}'))
        self.assertIsNone(parse(
            '{out:UpdateFigureData}{s:"M"}{s:"foo"}'))
        self.assertIsNone(parse(
            '{out:UpdateFigureData}{s:"M"}{s:"'+FIGURE_A+'"}{i:1}'))
        self.assertIsNone(parse(
            '{out:UpdateFigureData}{s:"M"}{s:"'+
            FIGURE_A+';{out:Other}{i:1}"}'))
        self.assertIsNone(parse(
            '{out:UpdateFigureData}{s:"M"}{s:"'+FIGURE_A+'"}'+'\nother'))

    def test_sanitizer_deduplicates_caps_and_rejects_malformed_entries(self):
        raw=[{'gender':'M','figure':FIGURE_A},
             {'gender':'M','figure':FIGURE_A},
             {'gender':'F','figure':FIGURE_B},
             {'gender':'M','figure':'invalid'},
             {'gender':None,'figure':FIGURE_A}]
        self.assertEqual(NAMESPACE['sanitize_outfit_presets'](raw),
                         [{'gender':'M','figure':FIGURE_A},
                          {'gender':'F','figure':FIGURE_B}])
        self.assertEqual(NAMESPACE['sanitize_outfit_presets']('junk'),[])

    def test_start_requires_two_outfits_and_connection(self):
        app=fake_app()
        app.outfit_presets=app.outfit_presets[:1]
        app._start_outfit_cycle()
        self.assertFalse(app._outfit_running)
        app.outfit_presets.append({'gender':'F','figure':FIGURE_B})
        app._habbo_session_connected=False
        app._start_outfit_cycle()
        self.assertFalse(app._outfit_running)

    def test_invalid_delay_rejected(self):
        for delay in ('0','0.01','nan','infinity','-1','20','not-a-number'):
            with self.subTest(delay=delay):
                app=fake_app()
                app.outfit_delay_var.set(delay)
                app._start_outfit_cycle()
                self.assertFalse(app._outfit_running)

    def test_cycles_without_guessing_numeric_header_and_records_local_requests(self):
        app=fake_app()
        app.outfit_delay_var.set('0.1')
        app._start_outfit_cycle()
        self.assertTrue(app._outfit_running)
        first_generation=app._outfit_generation
        for _ in range(3):
            app._outfit_tick(first_generation)
        self.assertEqual(app._outfit_sent,3)
        self.assertEqual(len(app.packets),3)
        self.assertEqual([p[0] for p in app.packets],['outfit_local']*3)
        self.assertTrue(all('server application unverified' in p[3]
                            for p in app.packets))
        self.assertEqual(
            app.packet_extension.expressions,
            [NAMESPACE['outfit_update_expression']('M',FIGURE_A),
             NAMESPACE['outfit_update_expression']('M',FIGURE_B),
             NAMESPACE['outfit_update_expression']('M',FIGURE_A)])
        self.assertEqual(app.root.tasks[app._outfit_after_id][0],100)

    def test_no_autocycle_and_stop_cancels_pending_callback(self):
        app=fake_app()
        self.assertFalse(app._outfit_running)
        app._start_outfit_cycle()
        gen=app._outfit_generation
        pending=app._outfit_after_id
        app._stop_outfit_cycle()
        self.assertIn(pending,app.root.cancelled)
        app._outfit_tick(gen)
        self.assertEqual(app._outfit_sent,0)
        self.assertEqual(len(app.packet_extension.sent),0)

    def test_disconnect_stops_and_does_not_send(self):
        app=fake_app()
        app._start_outfit_cycle()
        app._habbo_session_connected=False
        app._outfit_tick(app._outfit_generation)
        self.assertFalse(app._outfit_running)
        self.assertEqual(len(app.packet_extension.sent),0)

    def test_failed_packet_delivery_stops_loop(self):
        app=fake_app()
        app._start_outfit_cycle()
        app.packet_extension.reject=True
        app._outfit_tick(app._outfit_generation)
        self.assertFalse(app._outfit_running)
        self.assertEqual(app._outfit_sent,0)
        self.assertEqual(app.packets,[])

    def test_capture_only_while_armed_and_no_duplicates(self):
        app=fake_app()
        app.outfit_presets=[]
        app._receive_outfit_capture('M',FIGURE_A)
        self.assertEqual(app.outfit_presets,[])
        app._arm_outfit_capture()
        self.assertTrue(app._outfit_capture_pending)
        app._receive_outfit_capture('M',FIGURE_A)
        self.assertFalse(app._outfit_capture_pending)
        self.assertEqual(len(app.outfit_presets),1)
        app._arm_outfit_capture()
        app._receive_outfit_capture('M',FIGURE_A)
        self.assertEqual(len(app.outfit_presets),1)

    def test_capture_timeout(self):
        app=fake_app()
        app._arm_outfit_capture()
        gen=app._outfit_capture_generation
        app._outfit_capture_timeout(gen+1)
        self.assertTrue(app._outfit_capture_pending)
        app._outfit_capture_timeout(gen)
        self.assertFalse(app._outfit_capture_pending)

    def test_integrated_hook_restricts_header_and_clears_on_disconnect(self):
        source=SOURCE.read_text(encoding='utf-8')
        self.assertIn("'updatefiguredata' for info in records",source)
        self.assertIn("if verified else None",source)
        self.assertIn("self._packet_put(('outfit_captured',*parsed))",source)
        self.assertIn("self._stop_outfit_cycle('Habbo disconnected;",source)
        self.assertIn("self._stop_outfit_cycle('Companion closed.",source)
        self.assertIn("'outfit_local':'Outfit Cycler'",source)


if __name__=='__main__':
    unittest.main()
