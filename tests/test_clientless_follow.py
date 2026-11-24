"""Offline tests of opt-in follow between two locally connected accounts."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from clientless_bot import ClientlessBotError

source=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
names={'_bot_follow_start','_bot_follow_tick','_bot_follow_stop'}
nodes=[n for n in ast.walk(ast.parse(source.read_text(encoding='utf-8')))
       if isinstance(n,ast.FunctionDef) and n.name in names]
scope={'ClientlessBotError':ClientlessBotError,'time':SimpleNamespace(monotonic=lambda:100),
       'encode_clientless_action':Mock(return_value=((1,b'','Walk'),)),
       'threading':SimpleNamespace(Thread=Mock())}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),scope)

class FollowTests(TestCase):
    def make_app(self):
        a={'id':'abcdef','label':'A'}
        b={'id':'bcdefa','label':'B'}
        state={'generation':1,'room':99,'players':{1:(10,'A'),2:(20,'B')}}
        session=SimpleNamespace(release='mapped')
        app=SimpleNamespace(_bot_follow_run=None,_account_profiles=[a,b],
            _bot_selected_profile=lambda:a,bot_follow_target_var=Mock(),
            bot_follow_status_var=Mock(),_coffee_context=lambda ident:(state,1,10)
            if ident==a['id'] else (state,2,20),
            _bot_anti_afk_positions={a['id']:(10,1,1),b['id']:(20,5,5)},
            _bot_anti_afk_rooms={a['id']:99,b['id']:99},
            _bot_walk_plans={},_bot_action_inflight=set(),_bot_last_action_at={},
            _bot_self_ids={a['id']:1,b['id']:2},
            _coffee_session=lambda ident:session,_bot_headers=None,
            _bot_action_worker=Mock(),root=Mock())
        app.bot_follow_target_var.get.return_value=' b '
        for name in names:setattr(app,name,scope[name].__get__(app))
        scope['threading'].Thread.reset_mock()
        scope['encode_clientless_action'].reset_mock()
        return app

    def test_walk_once_near_leader_and_stop(self):
        app=self.make_app()
        app._bot_follow_start()
        run=app._bot_follow_run
        self.assertIsNotNone(run)
        scope['encode_clientless_action'].assert_called_once_with(None,'mapped','Walk',x=4,y=5)
        app.root.after.assert_called_once()
        self.assertEqual(app.root.after.call_args.args[0],2000)
        app._bot_action_inflight.clear()
        app._bot_follow_tick(run)
        self.assertEqual(scope['threading'].Thread.call_count,1)
        app._bot_follow_stop()
        app._bot_follow_tick(run)
        self.assertEqual(scope['threading'].Thread.call_count,1)

    def test_reject_unknown_or_self(self):
        for label in ('Unknown','A',''):
            app=self.make_app()
            app.bot_follow_target_var.get.return_value=label
            app._bot_follow_start()
            self.assertIsNone(app._bot_follow_run)
            scope['threading'].Thread.assert_not_called()

    def test_room_change_stops(self):
        app=self.make_app()
        app._bot_follow_start()
        run=app._bot_follow_run
        app._bot_anti_afk_rooms['bcdefa']=100
        app._bot_follow_tick(run)
        self.assertIsNone(app._bot_follow_run)
        self.assertEqual(scope['threading'].Thread.call_count,1)

    def test_reject_unconnected_room_avatar(self):
        app=self.make_app()
        state,_,_=app._coffee_context('abcdef')
        state['players'][3]=(30,'Visitor')
        app.bot_follow_target_var.get.return_value='Visitor'
        app._bot_follow_start()
        self.assertIsNone(app._bot_follow_run)
        scope['threading'].Thread.assert_not_called()
