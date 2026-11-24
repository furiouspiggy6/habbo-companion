"""Offline Coffee Pass bulk settings and concurrent run tests."""
import ast
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from clientless_bot import ClientlessBotError

p=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
tree=ast.parse(p.read_text(encoding='utf-8'))
scope={'ClientlessBotError':ClientlessBotError,'time':time}
names=('_coffee_group_apply','_coffee_group_select_all','_coffee_group_clear','_coffee_group_stop',
       '_coffee_refresh_accounts','_coffee_selected','_coffee_selected_accounts',
       '_coffee_load_settings','_coffee_save_settings','_coffee_manual','_coffee_start_run',
       '_coffee_collect_all','_coffee_tick','_coffee_advance')
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
            _coffee_settings=lambda:((476989081,476989024),15,3),
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
            _coffee_settings=lambda:((1,2),10,3),_coffee_build_run=build,
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
        for run in batch['runs']:
            run.update(phase='complete',done=3)
        scope['_coffee_tick'](app,batch)
        app._coffee_stop_run.assert_called_once()
        app._coffee_run=None
        app._coffee_advance.reset_mock()
        scope['_coffee_tick'](app,batch)
        app._coffee_advance.assert_not_called()

    def test_manual_collect_all_dispatches_both(self):
        accounts=[{'id':i} for i in ('a','c')]
        app=SimpleNamespace(_coffee_selected_accounts=lambda:accounts,
            _coffee_settings=lambda:((1,2),10,3),_coffee_context=lambda ident:({'carry':{}},1,0),
            _coffee_send=Mock(),coffee_status_var=Mock(),_coffee_group_refresh=Mock())
        scope['_coffee_collect_all'](app,1)
        self.assertEqual([call.args[0] for call in app._coffee_send.call_args_list],['a','c'])

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

    def test_zero_extra_delay_retains_pickup_cooldown(self):
        state={'generation':1,'room':1,'players':{2:(0,'B')},'carry':{0:(0,101)}}
        other={'generation':1,'room':1,'players':{1:(0,'A')},'carry':{}}
        app=SimpleNamespace(_coffee_context=lambda ident:(state,1,0) if ident=='a' else (other,2,0),
            _coffee_last_pickup={'a':95},_coffee_last_pass={'a':100},
            _bot_action_inflight=set(),_bot_last_action_at={'a':100},
            _coffee_send=Mock(return_value=105))
        run=dict(id='a',peer='b',target=2,generation=1,peer_generation=1,room=1,
            phase='pass',at=100,done=0,count=2,alternate=False,ids=(1,2),delay=0)
        scope['_coffee_advance'](app,run,101)
        self.assertEqual((run['phase'],run['at'],run['done']),('next',101,1))
        scope['_coffee_advance'](app,run,102)
        app._coffee_send.assert_not_called()
        scope['_coffee_advance'](app,run,105)
        app._coffee_send.assert_called_once_with('a','Collect hand item',furniture=1)
