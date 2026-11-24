"""Offline settings-only bulk selection tests."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from clientless_bot import ClientlessBotError

p=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
tree=ast.parse(p.read_text(encoding='utf-8'))
scope={'ClientlessBotError':ClientlessBotError}
names=('_coffee_group_apply','_coffee_group_select_all','_coffee_group_clear','_coffee_group_stop')
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
