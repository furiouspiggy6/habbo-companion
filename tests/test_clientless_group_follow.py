"""Offline group follow tests."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from clientless_bot import ClientlessBotError

source=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
names={'_bot_follow_group_resolve','_bot_follow_group_toggle','_bot_follow_group_tick','_bot_follow_stop'}
nodes=[n for n in ast.walk(ast.parse(source.read_text(encoding='utf-8')))
       if isinstance(n,ast.FunctionDef) and n.name in names]
scope={'ClientlessBotError':ClientlessBotError,'time':SimpleNamespace(monotonic=lambda:100),
       'encode_clientless_action':Mock(return_value=((1,b'','Walk'),)),
       'threading':SimpleNamespace(Thread=Mock())}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),scope)

class Var:
    def __init__(self,value):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value

class GroupFollowTests(TestCase):
    def make_app(self,target='Leader'):
        accounts=[{'id':ident} for ident in ('a','b','c')]
        state={'generation':1,'room':99,'players':{1:(10,'A'),2:(20,'B'),3:(30,'Leader'),4:(40,'Visitor')}}
        session=SimpleNamespace(release='mapped')
        app=SimpleNamespace(_account_profiles=accounts,_bot_follow_run=None,_bot_follow_group_run=None,
            _bot_selected_profile=lambda:accounts[0],bot_follow_all_var=Var(True),
            bot_follow_target_var=Var(target),bot_follow_status_var=Var(''),
            _coffee_session=lambda ident:session,_coffee_context=lambda ident:(state,'abc'.index(ident)+1,('abc'.index(ident)+1)*10),
            _bot_anti_afk_positions={'a':(10,1,1),'b':(20,2,2),'c':(30,12,8)},
            _bot_anti_afk_rooms={'a':99,'b':99,'c':99},
            _bot_walk_plans={},_bot_action_inflight=set(),_bot_last_action_at={},
            _bot_self_ids={'a':1,'b':2,'c':3},_bot_follow_room_bots={},
            _bot_headers=None,_bot_action_worker=Mock(),root=Mock())
        for name in names:setattr(app,name,scope[name].__get__(app))
        scope['threading'].Thread.reset_mock()
        scope['encode_clientless_action'].reset_mock()
        return app

    def test_group_exact_coords_and_stop(self):
        app=self.make_app()
        app._bot_follow_group_toggle()
        run=app._bot_follow_group_run
        self.assertEqual(set(run['members']),{'a','b'})
        self.assertEqual(scope['threading'].Thread.call_count,2)
        for call in scope['encode_clientless_action'].call_args_list:
            self.assertEqual(call.kwargs,{'x':12,'y':8})
        self.assertEqual(app.root.after.call_args.args[0],3000)
        app._bot_action_inflight.clear()
        app._bot_last_action_at.clear()
        app._bot_anti_afk_positions['c']=(30,13,9)
        app._bot_follow_group_tick(run)
        self.assertEqual(scope['threading'].Thread.call_count,4)
        self.assertEqual(scope['encode_clientless_action'].call_args.kwargs,{'x':13,'y':9})
        self.assertIn('X=13, Y=9',app.bot_follow_status_var.get())
        app.bot_follow_all_var.set(False)
        app._bot_follow_group_toggle()
        app._bot_follow_group_tick(run)
        self.assertEqual(scope['threading'].Thread.call_count,4)

    def test_unconnected_player_rejected(self):
        app=self.make_app('Visitor')
        app._bot_follow_group_toggle()
        self.assertIsNone(app._bot_follow_group_run)
        self.assertFalse(app.bot_follow_all_var.get())
        scope['threading'].Thread.assert_not_called()

    def test_room_bot_all_accounts(self):
        app=self.make_app('RoomBot')
        app._bot_follow_room_bots={a['id']:dict(room=99,generation=1,units={50:('RoomBot',12,8,77)})
                                   for a in app._account_profiles}
        app._bot_anti_afk_positions['c']=(30,3,3)
        app._bot_follow_group_toggle()
        self.assertEqual(set(app._bot_follow_group_run['members']),{'a','b','c'})
        self.assertEqual(scope['threading'].Thread.call_count,3)
        app._bot_follow_room_bots['a']['units'].clear()
        app._bot_follow_group_tick(app._bot_follow_group_run)
        self.assertNotIn('a',app._bot_follow_group_run['members'])
