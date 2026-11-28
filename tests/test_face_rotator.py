"""Offline regression tests for the 360-degree turn-in-place Face Rotator.

Every packet is synthetic. No Habbo account, G-Earth or network is used.
"""
import ast
from datetime import datetime
import math
from pathlib import Path
from types import MethodType, SimpleNamespace
import unittest

SOURCE=Path(__file__).resolve().parent.parent/'Habbo_Companion.pyw'
SRC=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(SRC)
APP=next(node for node in TREE.body if isinstance(node,ast.ClassDef)
         and node.name=='ChatOverlayApp')
HELPERS=('face_rotation_targets','face_lookto_expression',
         'outgoing_face_tile_from_packet','outgoing_is_named')
METHODS=('_arm_face_capture','_face_capture_timeout','_accept_face_tile',
         '_start_face_rotator','_face_tick','_stop_face_rotator',
         '_face_position_invalidated')
NS={'datetime':datetime,'math':math,
    'tk':SimpleNamespace(TclError=RuntimeError)}
for name in HELPERS:
    node=next(node for node in TREE.body if isinstance(node,ast.FunctionDef)
              and node.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),NS)
for name in METHODS:
    node=next(node for node in APP.body if isinstance(node,ast.FunctionDef)
              and node.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),NS)
NS['face_rotation_targets']=NS['face_rotation_targets']
NS['face_lookto_expression']=NS['face_lookto_expression']


class Var:
    def __init__(self,value=''):
        self.value=value
    def get(self):
        return self.value
    def set(self,value):
        self.value=value


class Packet:
    bytearray=b'\x00\x00\x00\x0a\x03\xdb\x00\x00\x00\x0a\x00\x00\x00\x0a'
    def __init__(self,x=10,y=10,header=987):
        self.x=x;self.y=y;self.header=header
    def header_id(self):
        return self.header
    def read_int(self,offset):
        return {6:self.x,10:self.y}[offset]
    def is_incomplete_packet(self):
        return False
    def is_corrupted(self):
        return False


class Extension:
    def __init__(self):
        self.sent=[]
        self.expressions=[]
        self.reject=False
        self.packet_infos={'out':{987:[{'Name':'LookTo'}],
                                   888:[{'Name':'MoveAvatar'}]}}
    def string_to_packet(self,expression):
        self.expressions.append(expression)
        return Packet()
    def send_to_server(self,packet):
        if self.reject:return False
        self.sent.append(packet)
        return True


class Root:
    def __init__(self):
        self.next_id=0;self.tasks={};self.cancelled=[]
    def after(self,delay,cb):
        self.next_id+=1
        self.tasks[self.next_id]=(delay,cb)
        return self.next_id
    def after_cancel(self,id):
        self.cancelled.append(id)
        self.tasks.pop(id,None)


def app():
    a=SimpleNamespace(
        root=Root(),packet_started=True,packet_extension=Extension(),
        _habbo_session_connected=True,packet_active=True,
        face_status_var=Var(),face_delay_var=Var('350'),
        face_direction_var=Var('Clockwise'),_face_tile=(10,10),
        _face_capture_pending=False,_face_capture_generation=0,
        _face_running=False,_face_generation=0,_face_after_id=None,
        _face_targets=(),_face_step=0,_face_sent=0,
        _face_interval_ms=350,config={},packets=[],
        save=lambda:None,
        _packet_put=lambda event:a.packets.append(event))
    for name in METHODS:
        setattr(a,name,MethodType(NS[name],a))
    return a


class FaceRotationTests(unittest.TestCase):
    def test_clockwise_targets_360_degrees_without_walking(self):
        t=NS['face_rotation_targets'](10,10)
        self.assertEqual(t,((10,9),(11,9),(11,10),(11,11),
                            (10,11),(9,11),(9,10),(9,9)))
        self.assertEqual(len(set(t)),8)
        self.assertNotIn((10,10),t)
        self.assertEqual(NS['face_rotation_targets'](10,10,False),
                         (t[0],)+tuple(reversed(t[1:])))
        for x,y in t:
            expr=NS['face_lookto_expression'](x,y)
            self.assertTrue(expr.startswith('{out:LookTo}{i:'))
            self.assertNotIn('MoveAvatar',expr)

    def test_invalid_coordinates_and_outside_targets_rejected(self):
        for coords in ((0,2),(-1,3),(1024,5),(1.2,8),(True,3),(4,'6')):
            with self.subTest(coords=coords):
                with self.assertRaises(ValueError):
                    NS['face_rotation_targets'](*coords)
        for coords in ((-1,1),(1025,0),(1.5,4)):
            with self.subTest(coords=coords):
                with self.assertRaises(ValueError):
                    NS['face_lookto_expression'](*coords)

    def test_capture_requires_named_lookto_and_exact_packet_shape(self):
        extension=Extension()
        capture=NS['outgoing_face_tile_from_packet']
        self.assertEqual(capture(extension,'out',Packet(11,17)),(11,17))
        self.assertIsNone(capture(extension,'out',Packet(11,17,888)))
        self.assertIsNone(capture(extension,'in',Packet(11,17)))
        self.assertIsNone(capture(extension,'out',Packet(0,10)))
        p=Packet(10,10)
        p.bytearray=b'\x00'*13
        self.assertIsNone(capture(extension,'out',p))
        self.assertTrue(NS['outgoing_is_named'](
            extension,'out',Packet(header=888),'MoveAvatar'))
        self.assertFalse(NS['outgoing_is_named'](
            extension,'out',Packet(header=987),'MoveAvatar'))

    def test_capture_arm_timeout_and_accept(self):
        a=app()
        a._face_tile=None
        a._arm_face_capture()
        self.assertTrue(a._face_capture_pending)
        self.assertEqual(a.root.tasks[a.root.next_id][0],30000)
        old=a._face_capture_generation
        a._face_capture_timeout(old+1)
        self.assertTrue(a._face_capture_pending)
        a._accept_face_tile(8,9)
        self.assertEqual(a._face_tile,(8,9))
        self.assertFalse(a._face_capture_pending)
        a._arm_face_capture()
        a._face_capture_timeout(a._face_capture_generation)
        self.assertFalse(a._face_capture_pending)
        self.assertIsNone(a._face_tile)

    def test_no_start_without_live_connection_and_tile(self):
        a=app()
        a._face_tile=None
        a._start_face_rotator()
        self.assertFalse(a._face_running)
        a._face_tile=(10,10)
        a._habbo_session_connected=False
        a._start_face_rotator()
        self.assertFalse(a._face_running)

    def test_speed_bounds_are_sensible_and_dont_allow_zero_flood(self):
        for delay in ('0','1','149','-1','60001','nan','hello','1.5'):
            with self.subTest(delay=delay):
                a=app();a.face_delay_var.set(delay)
                a._start_face_rotator()
                self.assertFalse(a._face_running)
        a=app();a.face_delay_var.set('150')
        a._start_face_rotator()
        self.assertTrue(a._face_running)
        self.assertEqual(a.config['face_delay_ms'],'150')

    def test_one_full_rotation_uses_only_lookto(self):
        a=app();a._start_face_rotator()
        self.assertTrue(a._face_running)
        self.assertEqual(a.config['face_direction'],'Clockwise')
        gen=a._face_generation
        for _ in range(8): a._face_tick(gen)
        self.assertEqual(a._face_sent,8)
        self.assertEqual(len(a.packet_extension.sent),8)
        self.assertEqual(a.packet_extension.expressions,
                         [NS['face_lookto_expression'](*xy)
                          for xy in NS['face_rotation_targets'](10,10)])
        self.assertEqual([event[0] for event in a.packets],
                         ['face_local']*8)
        self.assertEqual(a.root.tasks[a._face_after_id][0],350)
        self.assertIn('1 complete 360',a.face_status_var.get())

    def test_reverse_orientation_and_disconnect(self):
        a=app();a.face_direction_var.set('Counterclockwise')
        a._start_face_rotator()
        a._face_tick(a._face_generation)
        a._face_tick(a._face_generation)
        self.assertEqual(a.packet_extension.expressions[-1],
                         NS['face_lookto_expression'](9,9))
        a._habbo_session_connected=False
        a._face_tick(a._face_generation)
        self.assertFalse(a._face_running)
        self.assertIsNone(a._face_tile)

    def test_stop_prevents_any_additional_packets(self):
        a=app();a._start_face_rotator()
        gen=a._face_generation
        pending=a._face_after_id
        a._stop_face_rotator()
        self.assertIn(pending,a.root.cancelled)
        a._face_tick(gen)
        self.assertEqual(a._face_sent,0)
        self.assertEqual(a.packet_extension.sent,[])

    def test_manual_move_clears_saved_position_and_stops(self):
        a=app();a._start_face_rotator()
        a._face_tick(a._face_generation)
        a._face_position_invalidated('Manual walk requested')
        self.assertFalse(a._face_running)
        self.assertIsNone(a._face_tile)
        self.assertIn('Capture your standing tile',a.face_status_var.get())

    def test_failed_send_stops(self):
        a=app();a._start_face_rotator()
        a.packet_extension.reject=True
        a._face_tick(a._face_generation)
        self.assertFalse(a._face_running)
        self.assertEqual(a._face_sent,0)

    def test_hook_room_change_disconnect_and_close_are_wired(self):
        self.assertIn("self._packet_put(('face_tile_captured',*coords))",SRC)
        self.assertIn("'face_movement'",SRC)
        self.assertIn("self._face_position_invalidated('Room changed",SRC)
        self.assertIn("self._face_position_invalidated(\n                        'Habbo disconnected",SRC)
        self.assertIn("self._stop_face_rotator('Companion closed.",SRC)
        self.assertIn("'face_local':'Face Rotator'",SRC)


class ClientlessFaceRotationTests(unittest.TestCase):
    def make_app(self):
        from unittest.mock import Mock
        from clientless_bot import ClientlessBotError, encode_clientless_action, BUNDLED_AIR_RELEASE
        names=('_bot_face_start','_bot_face_tick','_bot_face_stop','_bot_face_remove')
        clock=SimpleNamespace(now=100.0)
        ns=dict(NS,ClientlessBotError=ClientlessBotError,
                encode_clientless_action=encode_clientless_action,
                time=SimpleNamespace(monotonic=lambda:clock.now),
                threading=SimpleNamespace(Thread=Mock()))
        nodes=[node for node in APP.body if isinstance(node,ast.FunctionDef) and node.name in names]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),ns)
        accounts=[dict(id='a'),dict(id='b')]
        session=SimpleNamespace(release=BUNDLED_AIR_RELEASE)
        a=SimpleNamespace(root=Root(),bot_account_var=Var('All connected accounts'),
            bot_face_delay_var=Var('400'),bot_face_direction_var=Var('Clockwise'),
            bot_face_status_var=Var(),_bot_face_run=None,_account_profiles=accounts,
            _bot_selected_profile=lambda:accounts[0],
            _coffee_session=lambda ident:session,
            _coffee_context=lambda ident:(dict(generation=1,room=9),1,3 if ident=='a' else 4),
            _bot_anti_afk_positions={'a':(3,10,10),'b':(4,20,20)},
            _bot_anti_afk_rooms={'a':9,'b':9},_bot_walk_plans={},
            _bot_action_inflight=set(),_bot_last_action_at={},_bot_headers=None,
            _bot_action_worker=Mock())
        for name in names:setattr(a,name,MethodType(ns[name],a))
        return a,clock,ns['threading'].Thread

    def test_all_accounts_use_eight_lookto_targets_without_walking(self):
        import struct
        a,clock,worker=self.make_app()
        a._bot_face_start()
        run=a._bot_face_run
        self.assertEqual(set(run['members']),{'a','b'})
        for _ in range(7):
            clock.now+=0.5
            a._bot_action_inflight.clear()
            a._bot_face_tick(run)
        for ident,center in (('a',(10,10)),('b',(20,20))):
            packets=[c.kwargs['args'][-1] for c in worker.call_args_list
                     if c.kwargs['args'][0]==ident]
            self.assertEqual([p[0][2] for p in packets],['LookTo']*8)
            self.assertEqual([struct.unpack('>ii',p[0][1]) for p in packets],
                             list(NS['face_rotation_targets'](*center)))
        a._bot_face_stop()
        a._bot_face_tick(run)
        self.assertEqual(worker.call_count,16)

    def test_moved_avatar_stops_and_delay_guard_is_retained(self):
        a,clock,worker=self.make_app()
        a.bot_account_var.set('A [a]')
        a.bot_face_delay_var.set('0')
        a._bot_face_start()
        self.assertIsNone(a._bot_face_run)
        a.bot_face_delay_var.set('400')
        a._bot_face_start()
        run=a._bot_face_run
        a._bot_face_tick(run)
        self.assertEqual(worker.call_count,1)
        a._bot_anti_afk_positions['a']=(3,11,10)
        a._bot_action_inflight.clear()
        clock.now+=1
        a._bot_face_tick(run)
        self.assertIsNone(a._bot_face_run)
        self.assertEqual(worker.call_count,1)

    def test_outfit_cycling_and_rotation_share_action_slots(self):
        from clientless_bot import random_clientless_figure
        a,clock,worker=self.make_app()
        names=('_bot_randomize_outfits','_bot_outfit_cycle_start',
               '_bot_outfit_cycle_tick','_bot_outfit_cycle_stop')
        ns=dict(NS,random_clientless_figure=random_clientless_figure,
                time=SimpleNamespace(monotonic=lambda:clock.now))
        nodes=[node for node in APP.body if isinstance(node,ast.FunctionDef)
               and node.name in names]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),ns)
        for name in names:setattr(a,name,MethodType(ns[name],a))
        a.bot_outfit_mode_var=Var('Mixed')
        a.bot_outfit_interval_var=Var('5')
        a.bot_outfit_status_var=Var()
        a._tcp_sessions={ident:SimpleNamespace(authenticated=True,
                        stop=SimpleNamespace(is_set=lambda:False))
                        for ident in ('a','b')}
        a._tcp_generation={'a':1,'b':1}
        outfits=[]
        def send(account_override,action_override,outfit_override):
            ident=account_override['id']
            self.assertNotIn(ident,a._bot_action_inflight)
            self.assertGreaterEqual(clock.now-a._bot_last_action_at.get(ident,0),0.4)
            outfits.append(ident)
            a._bot_action_inflight.add(ident)
            a._bot_last_action_at[ident]=clock.now
        a._bot_send_action=send
        a._bot_face_start()
        a._bot_outfit_cycle_start()
        run=a._bot_outfit_run
        self.assertEqual(run['pending'],{'a','b'})
        self.assertEqual(outfits,[])
        self.assertEqual(a.root.tasks[run['timer']][0],100)
        a._bot_action_inflight.clear()
        clock.now+=0.5
        a._bot_face_tick(a._bot_face_run)
        self.assertEqual(worker.call_count,2)
        a._bot_outfit_cycle_tick(run)
        self.assertCountEqual(outfits,['a','b'])
        self.assertEqual(run['pending'],set())
        self.assertEqual(a.root.tasks[run['timer']][0],5000)
        a._bot_action_inflight.clear()
        clock.now+=0.5
        a._bot_face_tick(a._bot_face_run)
        self.assertEqual(worker.call_count,4)
        a._bot_outfit_cycle_tick(run)
        self.assertEqual(run['pending'],{'a','b'})
        a._bot_outfit_cycle_stop()
        a._bot_action_inflight.clear()
        clock.now+=0.5
        a._bot_face_tick(a._bot_face_run)
        self.assertEqual(worker.call_count,6)
        a._bot_outfit_cycle_tick(run)
        self.assertEqual(len(outfits),2)

if __name__=='__main__':
    unittest.main()
