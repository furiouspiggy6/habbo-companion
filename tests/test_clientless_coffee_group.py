"""Offline Coffee Pass bulk settings and concurrent run tests."""
import ast
import time
import threading
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch
from clientless_bot import ClientlessBotError, validate_clientless_coffee_settings

p=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
tree=ast.parse(p.read_text(encoding='utf-8'))
scope={'ClientlessBotError':ClientlessBotError,'time':time,'threading':threading,
       'validate_clientless_coffee_settings':validate_clientless_coffee_settings}
names=('_coffee_group_apply','_coffee_group_select_all','_coffee_group_clear','_coffee_group_stop',
       '_coffee_refresh_accounts','_coffee_selected','_coffee_selected_accounts',
       '_coffee_load_settings','_coffee_save_settings','_coffee_manual','_coffee_start_run',
       '_coffee_collect_all','_coffee_manual_report','_coffee_manual_send_result','_coffee_tick','_coffee_advance','_coffee_build_run',
       '_coffee_settings','_coffee_stop_run','_coffee_context','_coffee_target','_coffee_observe')
nodes=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name in names]
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(p),'exec'),scope)

class CoffeeGroupTests(TestCase):
    def test_apply_only_connected_and_selected(self):
        accounts=[{'id':i} for i in ('a','b','c','d')]
        widget=Mock()
        widget.selection.return_value=('a','b','c')
        app=SimpleNamespace(coffee_group_tree=widget,_account_profiles=accounts,
            _coffee_session=lambda ident:object() if ident!='b' else None,
            _coffee_settings=lambda:((476989081,476989024),15,3),
            coffee_alternate_var=Mock(),coffee_group_status_var=Mock(),
            config={'clientless_coffee_presets':{'b':{'one':7},'d':{'one':8}}},
            save=Mock(),_coffee_send=Mock(),_coffee_start_run=Mock())
        app.coffee_alternate_var.get.return_value=True
        scope['_coffee_group_apply'](app)
        presets=app.config['clientless_coffee_presets']
        self.assertEqual(presets['a'],presets['c'])
        self.assertEqual(presets['a']['delay'],15)
        self.assertEqual(presets['b'],{'one':7})
        self.assertEqual(presets['d'],{'one':8})
        app.save.assert_called_once()
        app._coffee_send.assert_not_called()
        app._coffee_start_run.assert_not_called()
    def test_select_all_is_selection_only(self):
        widget=Mock()
        widget.get_children.return_value=('a','c')
        app=SimpleNamespace(coffee_group_tree=widget,_coffee_group_refresh=Mock(),
                            coffee_group_status_var=Mock(),_coffee_send=Mock())
        scope['_coffee_group_select_all'](app)
        widget.selection_set.assert_called_once_with(('a','c'))
        app._coffee_send.assert_not_called()
    def test_stop_does_not_disconnect(self):
        app=SimpleNamespace(_coffee_stop_run=Mock(),_coffee_group_refresh=Mock(),
                            coffee_group_status_var=Mock(),_tcp_disconnect_one=Mock())
        scope['_coffee_group_stop'](app)
        app._coffee_stop_run.assert_called_once()
        app._tcp_disconnect_one.assert_not_called()

    def test_dropdown_all_saves_current_connected_accounts_only(self):
        accounts=[{'id':i,'label':i.upper()} for i in ('a','b','c')]
        app=SimpleNamespace(_account_profiles=accounts,
            _coffee_session=lambda ident:object() if ident!='b' else None,
            _coffee_settings=Mock(return_value=((476989081,476989024),15,3)),
            coffee_account_picker=Mock(),coffee_account_var=Mock(),
            coffee_alternate_var=Mock(),coffee_status_var=Mock(),
            coffee_consent_var=Mock(),_coffee_run=None,_coffee_group_refresh=Mock(),
            _coffee_group_select_all=Mock(),_coffee_send=Mock(),
            config={'clientless_coffee_presets':{'b':{'one':7}}},save=Mock())
        app.coffee_account_var.get.return_value='All connected accounts'
        app.coffee_alternate_var.get.return_value=True
        app._coffee_selected=lambda:scope['_coffee_selected'](app)
        app._coffee_selected_accounts=lambda:scope['_coffee_selected_accounts'](app)
        scope['_coffee_refresh_accounts'](app)
        app.coffee_account_picker.configure.assert_called_once_with(
            values=['All connected accounts','A [a]','C [c]'])
        app.coffee_account_var.set.assert_not_called()
        scope['_coffee_load_settings'](app)
        app._coffee_group_select_all.assert_called_once()
        scope['_coffee_save_settings'](app)
        presets=app.config['clientless_coffee_presets']
        self.assertEqual(presets['a'],presets['c'])
        self.assertEqual(presets['b'],{'one':7})
        app.save.assert_called_once()
        scope['_coffee_manual'](app,'Pass hand item')
        app.coffee_consent_var.get.return_value=False
        app._coffee_stop_run=Mock()
        scope['_coffee_start_run'](app)
        app._coffee_stop_run.assert_called_once()
        app._coffee_send.assert_not_called()
        app.coffee_account_var.get.return_value='C [c]'
        self.assertEqual(app._coffee_selected_accounts(),[accounts[2]])

    def test_all_starts_eligible_senders_together(self):
        accounts=[{'id':i,'label':i.upper()} for i in ('a','b','c')]
        def build(ident,ids,delay,count):
            if ident=='b':
                raise ClientlessBotError('Recipient is not a sender.')
            return dict(id=ident,peer='b',target=2,delay=delay,count=count,done=0,phase='next')
        app=SimpleNamespace(_coffee_run=None,_coffee_selected_accounts=lambda:accounts,
            _coffee_settings=Mock(return_value=((1,2),10,3)),_coffee_build_run=build,
            coffee_account_var=Mock(),coffee_consent_var=Mock(),
            coffee_status_var=Mock(),coffee_group_status_var=Mock(),
            _coffee_tick=Mock(),_coffee_stop_run=Mock(),_coffee_group_refresh=Mock(),
            _coffee_advance=Mock(),root=Mock())
        app.coffee_account_var.get.return_value='All connected accounts'
        app.coffee_consent_var.get.return_value=True
        scope['_coffee_start_run'](app)
        batch=app._coffee_run
        self.assertEqual([r['id'] for r in batch['runs']],['a','c'])
        self.assertEqual(batch['skipped'],1)
        app._coffee_tick.assert_called_once_with(batch)
        scope['_coffee_tick'](app,batch)
        self.assertEqual([call.args[0]['id'] for call in app._coffee_advance.call_args_list],['a','c'])
        gates=[call.kwargs['pickup_gate'] for call in app._coffee_advance.call_args_list]
        self.assertIs(gates[0],gates[1])
        self.assertTrue(gates[0].is_set())
        for run in batch['runs']:
            run.update(phase='complete',done=3)
        scope['_coffee_tick'](app,batch)
        app._coffee_stop_run.assert_called_once()
        app._coffee_run=None
        app._coffee_advance.reset_mock()
        scope['_coffee_tick'](app,batch)
        app._coffee_advance.assert_not_called()

    def test_loop_alternates_to_room_player_without_release_confirmations(self):
        sender={'generation':1,'room':9,'players':{1:(0,'A'),2:(3,'B')},'carry':{}}
        app=SimpleNamespace(
            _coffee_run=None,_account_profiles=[{'id':'a','label':'A'}],
            _coffee_selected_accounts=lambda:[{'id':'a'}],_bot_self_ids={'a':1},
            _coffee_room_state={'a':sender},_tcp_generation={'a':1},
            _coffee_session=lambda ident:object() if ident=='a' else None,
            _bot_action_inflight=set(),
            _bot_last_action_at={},_coffee_last_pickup={},_coffee_last_pass={},
            coffee_one_var=Mock(**{'get.return_value':'101'}),
            coffee_two_var=Mock(**{'get.return_value':'202'}),
            coffee_delay_var=Mock(**{'get.return_value':'0'}),
            coffee_count_var=Mock(**{'get.return_value':''}),
            coffee_account_var=Mock(**{'get.return_value':'A [a]'}),
            coffee_account_picker=Mock(),
            coffee_recipient_var=Mock(**{'get.return_value':' b '}),
            coffee_alternate_var=Mock(**{'get.return_value':False}),
            coffee_consent_var=Mock(**{'get.return_value':True}),
            coffee_status_var=Mock(),coffee_group_status_var=Mock(),
            _coffee_group_refresh=Mock(),root=Mock(),
        )
        for name in ('_coffee_settings','_coffee_build_run','_coffee_start_run',
                     '_coffee_advance','_coffee_tick','_coffee_stop_run',
                     '_coffee_context','_coffee_target','_coffee_refresh_accounts'):
            setattr(app,name,MethodType(scope[name],app))

        clock=SimpleNamespace(now=100)

        def send(ident,action,**_args):
            cooldown=app._coffee_last_pickup if action=='Collect hand item' else app._coffee_last_pass
            cooldown[ident]=app._bot_last_action_at[ident]=clock.now
            if action=='Pass hand item':
                app._bot_action_inflight.add(ident)
            return clock.now

        app._coffee_send=Mock(side_effect=send)
        with patch.dict(scope,time=SimpleNamespace(monotonic=lambda:clock.now)):
            with self.assertRaisesRegex(ClientlessBotError,'Fixed runs require a second connected account'):
                app._coffee_build_run('a',(101,202),0,1)
            app._coffee_start_run(loop=True)
            batch=app._coffee_run
            app._coffee_refresh_accounts()
            self.assertIs(app._coffee_run,batch)
            expected=[]
            for index,furniture in enumerate((101,202,101,202,101,202)):
                clock.now=100+index*10+0.5
                app._coffee_tick(batch)
                expected.append(call('a','Collect hand item',furniture=furniture))
                self.assertEqual(app._coffee_send.call_args_list,expected)
                self.assertEqual(batch['runs'][0]['phase'],'pickup')
                clock.now+=0.5
                sender['carry'][0]=(5,clock.now)
                app._coffee_tick(batch)
                expected.append(call('a','Pass hand item',recipient_id=2))
                self.assertEqual(app._coffee_send.call_args_list,expected)
                clock.now+=0.5
                app._coffee_tick(batch)
                self.assertEqual(batch['runs'][0]['phase'],'pass')
                app._bot_action_inflight.remove('a')
                app._coffee_tick(batch)
                self.assertEqual(batch['runs'][0]['phase'],'next')
                self.assertNotIn(0,sender['carry'])

            self.assertEqual(batch['runs'][0]['phase'],'next')
            self.assertIs(app._coffee_run,batch)
            app.coffee_status_var.set.assert_called_with('Cup loop: 6 cup passes sent — 1/1 active sender(s)')
            pending_tick=app.root.after.call_args.args[1]
            app._coffee_stop_run()
            clock.now+=10
            pending_tick()
            self.assertEqual(app._coffee_send.call_args_list,expected)

    def test_loop_stops_when_room_recipient_leaves_before_pass(self):
        state={'room':9,'generation':1,'players':{1:(0,'A'),2:(3,'B')},'carry':{0:(5,99.5)}}
        run=dict(id='a',peer=None,target=2,room=9,generation=1,phase='pickup',at=99,delay=0)
        batch={'runs':[run]}
        app=SimpleNamespace(
            _coffee_run=batch,_coffee_room_state={'a':state},
            _coffee_context=lambda ident:(state,1,0),_coffee_send=Mock(),
            _bot_action_inflight=set(),_bot_last_action_at={},_coffee_last_pass={},
            _coffee_group_refresh=Mock(),_coffee_stop_run=Mock(),
        )
        app._coffee_advance=MethodType(scope['_coffee_advance'],app)
        scope['_coffee_observe'](app,'a',1,('remove',3))
        with patch.dict(scope,time=SimpleNamespace(monotonic=lambda:100)):
            scope['_coffee_tick'](app,batch)
        app._coffee_stop_run.assert_called_once_with('Run stopped: recipient is no longer in the room.')
        app._coffee_send.assert_not_called()

    def test_loop_continues_after_sending_held_item_without_release_confirmation(self):
        advance=scope['_coffee_advance']
        for completed,next_cup in ((0,101),(1,202)):
            with self.subTest(completed=completed):
                state={'room':9,'generation':1,'players':{2:(3,'B')},'carry':{0:(5,99)}}
                run=dict(id='a',peer=None,target=2,room=9,generation=1,
                    phase='next',at=100,delay=2,count=None,done=completed,
                    ids=(101,202),alternate=True)
                app=SimpleNamespace(
                    _coffee_context=lambda ident:(state,1,0),
                    _coffee_send=Mock(side_effect=[101,108]),
                    _bot_action_inflight=set(),_bot_last_action_at={},
                    _coffee_last_pass={'a':91},_coffee_last_pickup={'a':95},
                )

                advance(app,run,100)
                app._coffee_send.assert_not_called()
                advance(app,run,101)
                app._coffee_send.assert_called_once_with('a','Pass hand item',recipient_id=2)
                self.assertEqual(run['phase'],'pass held item')

                app._bot_action_inflight.add('a')
                advance(app,run,105)
                self.assertEqual(run['phase'],'pass held item')
                app._coffee_send.assert_called_once()

                app._bot_action_inflight.remove('a')
                advance(app,run,106)
                self.assertEqual((run['phase'],run['done']),('next',completed))
                self.assertNotIn(0,state['carry'])
                advance(app,run,107)
                app._coffee_send.assert_called_once()
                advance(app,run,108)
                self.assertEqual(app._coffee_send.call_args_list,[
                    call('a','Pass hand item',recipient_id=2),
                    call('a','Collect hand item',furniture=next_cup),
                ])

    def test_manual_collect_all_dispatches_both(self):
        accounts=[{'id':i} for i in ('a','c')]
        app=SimpleNamespace(_coffee_selected_accounts=lambda:accounts,
            _coffee_settings=lambda:((1,2),10,3),_coffee_context=lambda ident:({'carry':{},'generation':1,'room':9},1,0),
            _coffee_send=Mock(return_value=100),coffee_status_var=Mock(),_coffee_group_refresh=Mock(),_coffee_manual_report=Mock())
        scope['_coffee_collect_all'](app,1)
        self.assertEqual([call.args[0] for call in app._coffee_send.call_args_list],['a','c'])
        gates=[call.kwargs['_start_gate'] for call in app._coffee_send.call_args_list]
        self.assertIs(gates[0],gates[1])
        self.assertTrue(gates[0].is_set())

    def test_manual_collection_releases_gate_only_after_all_prepared(self):
        seen=[]
        def prepare(ident,action,**kwargs):
            gate=kwargs['_start_gate']
            self.assertFalse(gate.is_set())
            seen.append((ident,kwargs['furniture'],gate))
            return 100
        app=SimpleNamespace(
            _coffee_selected_accounts=lambda:[{'id':'a'},{'id':'b'},{'id':'c'}],
            _coffee_settings=lambda:((101,202),10,3),
            _coffee_context=lambda ident:({'carry':{0:(1,0)} if ident=='b' else {},'generation':1,'room':9},1,0),
            _coffee_send=prepare,coffee_status_var=Mock(),_coffee_group_refresh=Mock(),_coffee_manual_report=Mock())
        scope['_coffee_collect_all'](app,2)
        self.assertEqual([(ident,furniture) for ident,furniture,_ in seen],
                         [('a',202),('b',202),('c',202)])
        self.assertIs(seen[0][2],seen[1][2])
        self.assertIs(seen[0][2],seen[2][2])
        self.assertTrue(seen[0][2].is_set())


    def test_manual_group_waits_for_cooldown_then_sends_once_to_every_account(self):
        held={0:(86,99)}
        states={'a':{'carry':held,'generation':1,'room':9},
                'b':{'carry':{},'generation':1,'room':9}}
        app=SimpleNamespace(
            _coffee_selected_accounts=lambda:[{'id':'a'},{'id':'b'}],
            _coffee_settings=lambda:((101,202),10,3),
            _coffee_context=lambda ident:(states[ident],1,0),
            _coffee_last_pickup={'b':95},_bot_last_action_at={},
            _coffee_send=Mock(return_value=105.1),coffee_status_var=Mock(),
            _coffee_group_refresh=Mock(),_coffee_manual_report=Mock(),root=Mock())
        with patch.dict(scope,time=SimpleNamespace(monotonic=lambda:100)):
            scope['_coffee_collect_all'](app,1)
        app._coffee_send.assert_not_called()
        delay,dispatch=app.root.after.call_args.args
        self.assertGreaterEqual(delay,5000)
        self.assertEqual(app._coffee_manual_results['a']['status'],
                         'Queued — waiting for cooldown')
        dispatch()
        self.assertEqual([c.args[0] for c in app._coffee_send.call_args_list],['a','b'])
        self.assertEqual([c.kwargs['furniture'] for c in app._coffee_send.call_args_list],[101,101])
        gates=[c.kwargs['_start_gate'] for c in app._coffee_send.call_args_list]
        self.assertIs(gates[0],gates[1])
        self.assertTrue(gates[0].is_set())
        self.assertEqual(held,{0:(86,99)})
        app.root.after.assert_called_once()

    def test_manual_pickup_completes_on_send_without_hand_item_confirmation(self):
        results={i:dict(status='Sending pickup packet',pending=True,generation=1)
                 for i in ('a','b','d')}
        results['c']=dict(status='Skipped: Account unavailable.',pending=False)
        app=SimpleNamespace(_coffee_manual_results=results,_coffee_run=None,
            _coffee_context=Mock(),coffee_status_var=Mock(),_coffee_group_refresh=Mock(),
            root=Mock())
        app._coffee_manual_report=MethodType(scope['_coffee_manual_report'],app)
        finish=scope['_coffee_manual_send_result']
        finish(app,'a',2,None)
        self.assertTrue(results['a']['pending'])
        finish(app,'a',1,None)
        finish(app,'b',1,'Connection closed')
        finish(app,'d',1,None)
        self.assertEqual(results['a']['status'],'Pickup packet sent')
        self.assertEqual(results['b']['status'],'Send failed: Connection closed')
        self.assertEqual(results['d']['status'],'Pickup packet sent')
        self.assertTrue(results['c']['status'].startswith('Skipped:'))
        self.assertFalse(any(r['pending'] for r in results.values()))
        app.coffee_status_var.set.assert_called_with(
            'Pickup packets: 2/4 sent; 0 sending; 1 skipped; 1 failed. Server pickup not verified.')
        app._coffee_context.assert_not_called()
        app.root.after.assert_not_called()

    def test_advance_uses_own_cooldown(self):
        states={'a':({'generation':1,'room':1,'players':{2:(0,'B')},'carry':{}},1,0),
                'b':({'generation':1,'room':1,'players':{1:(0,'A'),3:(1,'C')},'carry':{}},2,0),
                'c':({'generation':1,'room':1,'players':{2:(0,'B')},'carry':{}},3,0)}
        app=SimpleNamespace(_coffee_context=lambda ident:states[ident],
            _coffee_last_pickup={'a':99},_coffee_last_pass={},_bot_action_inflight=set(),
            _bot_last_action_at={},_coffee_send=Mock(return_value=100))
        def run(ident):
            return dict(id=ident,peer='b',target=2,generation=1,peer_generation=1,
                room=1,phase='next',at=90,done=0,count=1,alternate=False,ids=(1,2))
        a,c=run('a'),run('c')
        scope['_coffee_advance'](app,a,100)
        scope['_coffee_advance'](app,c,100)
        self.assertEqual(a['phase'],'next')
        self.assertEqual(c['phase'],'pickup')
        app._coffee_send.assert_called_once_with('c','Collect hand item',furniture=1)

    def test_fixed_run_waits_for_release_and_retains_pickup_cooldown(self):
        state={'generation':1,'room':1,'players':{2:(0,'B')},'carry':{0:(5,99)}}
        other={'generation':1,'room':1,'players':{1:(0,'A')},'carry':{}}
        app=SimpleNamespace(_coffee_context=lambda ident:(state,1,0) if ident=='a' else (other,2,0),
            _coffee_last_pickup={'a':95},_coffee_last_pass={'a':100},
            _bot_action_inflight=set(),_bot_last_action_at={'a':100},
            _coffee_send=Mock(return_value=105))
        run=dict(id='a',peer='b',target=2,generation=1,peer_generation=1,room=1,
            phase='pass',at=100,done=0,count=2,alternate=False,ids=(1,2),delay=0)
        scope['_coffee_advance'](app,run,101)
        self.assertEqual((run['phase'],run['done']),('pass',0))
        state['carry'][0]=(0,101)
        scope['_coffee_advance'](app,run,101)
        self.assertEqual((run['phase'],run['at'],run['done']),('next',101,1))
        scope['_coffee_advance'](app,run,102)
        app._coffee_send.assert_not_called()
        scope['_coffee_advance'](app,run,105)
        app._coffee_send.assert_called_once_with('a','Collect hand item',furniture=1)


    def test_requested_delay_applies_before_pass_after_pickup_confirmation(self):
        state={'generation':1,'room':1,'players':{2:(0,'B')},'carry':{0:(1,100.2)}}
        other={'generation':1,'room':1,'players':{1:(0,'A')},'carry':{}}
        app=SimpleNamespace(_coffee_context=lambda ident:(state,1,0) if ident=='a' else (other,2,0),
            _coffee_last_pickup={'a':100},_coffee_last_pass={},
            _bot_action_inflight=set(),_bot_last_action_at={'a':100},
            _coffee_send=Mock(return_value=125))
        run=dict(id='a',peer='b',target=2,generation=1,peer_generation=1,
            room=1,phase='pickup',at=100,done=0,count=2,alternate=False,ids=(1,2),delay=25)
        scope['_coffee_advance'](app,run,124)
        app._coffee_send.assert_not_called()
        scope['_coffee_advance'](app,run,125)
        app._coffee_send.assert_called_once_with('a','Pass hand item',recipient_id=2)
        self.assertEqual(run['phase'],'pass')
