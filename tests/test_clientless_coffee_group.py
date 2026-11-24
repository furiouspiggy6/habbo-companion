"""Offline Coffee Pass bulk settings and sequential run tests."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from clientless_bot import ClientlessBotError

p=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
tree=ast.parse(p.read_text(encoding='utf-8'))
scope={'ClientlessBotError':ClientlessBotError}
names=('_coffee_group_apply','_coffee_group_select_all','_coffee_group_clear','_coffee_group_stop',
       '_coffee_refresh_accounts','_coffee_selected','_coffee_selected_accounts',
       '_coffee_load_settings','_coffee_save_settings','_coffee_manual','_coffee_start_run',
       '_coffee_finish_run')
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

    def test_all_queues_eligible_senders_and_stops_after_last(self):
        accounts=[{'id':i,'label':i.upper()} for i in ('a','b','c')]
        def build(ident,ids,delay,count):
            if ident=='b':
                raise ClientlessBotError('Recipient is not a sender.')
            return dict(id=ident,peer='b',target=2,delay=delay,count=count,done=0)
        app=SimpleNamespace(_coffee_run=None,_coffee_selected_accounts=lambda:accounts,
            _coffee_settings=lambda:((1,2),10,3),_coffee_build_run=build,
            coffee_account_var=Mock(),coffee_consent_var=Mock(),
            coffee_status_var=Mock(),coffee_group_status_var=Mock(),
            _coffee_tick=Mock(),_coffee_stop_run=Mock(),_coffee_group_refresh=Mock(),
            root=Mock())
        app.coffee_account_var.get.return_value='All connected accounts'
        app.coffee_consent_var.get.return_value=True
        scope['_coffee_start_run'](app)
        first=app._coffee_run
        self.assertEqual(first['id'],'a')
        self.assertEqual(first['group_total'],2)
        self.assertEqual(first['skipped'],1)
        self.assertEqual([r['id'] for r in first['remaining']],['c'])
        app._coffee_tick.assert_called_once_with(first)
        scope['_coffee_finish_run'](app,first,100)
        following=app._coffee_run
        self.assertEqual(following['id'],'c')
        self.assertEqual(following['at'],110)
        self.assertEqual(following['group_index'],2)
        app.root.after.assert_called_once()
        scope['_coffee_finish_run'](app,following,120)
        app._coffee_stop_run.assert_called_once()
