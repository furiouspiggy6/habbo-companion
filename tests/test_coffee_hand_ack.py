"""Wait for server CarryObject updates about the sender's own avatar before next coffee action."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

APP=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
CODE=APP.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
names={'own_identity_from_packet','full_room_users_from_packet',
       'carry_ack_matches','carry_object_from_packet'}
funcs=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in names]
ns={}
exec(compile(ast.Module(body=funcs,type_ignores=[]),str(APP),'exec'),ns)

class MockPacket:
    def __init__(self):
        self.read_index=22
    def read_int(self,index):return {6:2,10:16212392}[index]
    def read_string(self,index):return {10:'dan.alt100'}[index]

class FakeRoot:
    def __init__(self):self.actions=[];self.cancelled=[]
    def after(self,ms,callback):
        self.actions.append((ms,callback))
        return len(self.actions)
    def after_cancel(self,i):self.cancelled.append(i)

class Value:
    def __init__(self):self.value=''
    def set(self,x):self.value=x

CL=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name=='ChatOverlayApp')
methods={}
for name in ('_on_own_carry_update','_coffee_ack_timeout'):
    n=next(n for n in CL.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[n],type_ignores=[]),str(APP),'exec'),methods)

class CoffeeConfirmationTests(unittest.TestCase):
    def test_own_identity_packet(self):
        self.assertEqual(ns['own_identity_from_packet'](MockPacket()),
                         (2,'dan.alt100'))

    def test_full_room_parser_preserves_cursor_and_room_index(self):
        p=MockPacket()
        class Entity:
            def __init__(self,name,ident,index):
                self.name=name;self.id=ident;self.index=index
        def parser(pkt):
            pkt.read_index=1000
            return [Entity('dan.alt100',16212392,8),
                    Entity('Atuu',1681,3)]
        users=ns['full_room_users_from_packet'](p,parser)
        self.assertEqual(users['dan.alt100'],('dan.alt100',16212392,8))
        self.assertEqual(users['atuu'],('Atuu',1681,3))
        self.assertEqual(p.read_index,22)
        self.assertEqual(ns['full_room_users_from_packet'](p,lambda _:[]),{})
        self.assertEqual(p.read_index,22)

    def test_only_post_action_updates_from_self_allow_progress(self):
        m=ns['carry_ack_matches']
        self.assertTrue(m('pickup',8,8,5,15,14))
        self.assertTrue(m('release',8,8,0,15,14))
        self.assertFalse(m('pickup',8,3,5,15,14))
        self.assertFalse(m('pickup',None,8,5,15,14))
        self.assertFalse(m('pickup',8,8,0,15,14))
        self.assertFalse(m('release',8,8,5,15,14))
        self.assertFalse(m('release',8,8,0,13,14))
        self.assertFalse(m('release',8,8,0,40,14))

    def fake(self,phase='pickup',finished=False):
        root=FakeRoot()
        state=SimpleNamespace(
            root=root,_coffee_running=True,_coffee_wait_for_hand=True,
            _coffee_ack_phase=phase,_own_room_index=8,
            _coffee_ack_since=14.0,_coffee_ack_timer=33,
            _coffee_finish_after_ack=finished,_coffee_interval=0.5,
            _coffee_generation=7,coffee_status_var=Value(),
            _coffee_after_id=None,stops=[])
        state._stop_coffee_loop=lambda msg:state.stops.append(msg)
        state._coffee_loop_tick=lambda generation:None
        return state

    def test_pickup_advances_only_after_own_held_item(self):
        obj=self.fake()
        methods['_on_own_carry_update'](obj,3,5,15)
        self.assertEqual(len(obj.root.actions),0)
        methods['_on_own_carry_update'](obj,8,0,15)
        self.assertEqual(len(obj.root.actions),0)
        methods['_on_own_carry_update'](obj,8,6,15)
        self.assertEqual(obj._coffee_ack_phase,None)
        self.assertEqual(obj.root.cancelled,[33])
        self.assertEqual(obj.root.actions[0][0],500)
        self.assertIn('holding an item',obj.coffee_status_var.value)

    def test_release_requires_own_empty_hand_and_finishes(self):
        obj=self.fake('release',True)
        methods['_on_own_carry_update'](obj,8,6,15)
        self.assertEqual(obj.stops,[])
        methods['_on_own_carry_update'](obj,8,0,15)
        self.assertEqual(len(obj.stops),1)
        self.assertIn('Recipient receipt not independently confirmed',obj.stops[0])
        self.assertEqual(len(obj.root.actions),0)

    def test_missing_ack_stops_without_further_passes(self):
        obj=self.fake('pickup')
        methods['_coffee_ack_timeout'](obj,7,'pickup')
        self.assertEqual(len(obj.stops),1)
        self.assertIn('No server confirmation',obj.stops[0])
        obj.stops.clear()
        methods['_coffee_ack_timeout'](obj,6,'pickup')
        methods['_coffee_ack_timeout'](obj,7,'release')
        self.assertEqual(obj.stops,[])

    def test_old_timed_mode_preserved_and_carry_hook_present(self):
        self.assertIn("coffee_wait_for_hand=False",CODE)
        self.assertIn("Wait for my avatar to receive/pass each cup",CODE)
        self.assertIn("elif kind=='UserObject':",CODE)
        self.assertIn("users.update(full_room_users_from_packet(msg.packet))",CODE)
        self.assertIn("self._on_own_carry_update(room_index,item_type,seen_at)",CODE)

if __name__=='__main__':
    unittest.main()
