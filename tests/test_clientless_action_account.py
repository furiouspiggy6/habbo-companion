import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

class ActionAccountTests(TestCase):
    def test_explicit_sender_never_defaults_to_last_connection(self):
        p=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
        node=next(n for n in ast.walk(ast.parse(p.read_text(encoding='utf-8')))
                  if isinstance(n,ast.FunctionDef) and n.name=='_bot_send_selected_action')
        scope={}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),scope)
        a={'label':'First','id':'abcdef123456'}
        b={'label':'Second','id':'123456abcdef'}
        app=SimpleNamespace(_account_profiles=[a,b],bot_action_account_var=Mock(),
                            bot_status_var=Mock(),_bot_send_action=Mock())
        app.bot_action_account_var.get.return_value='First [abcdef]'
        scope[node.name](app)
        app._bot_send_action.assert_called_once_with(account_override=a)
        app._bot_send_action.reset_mock()
        app.bot_action_account_var.get.return_value=''
        scope[node.name](app)
        app._bot_send_action.assert_not_called()

    def test_all_dropdown_dispatches_only_authenticated_connected_accounts(self):
        p=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
        nodes=[n for n in ast.walk(ast.parse(p.read_text(encoding='utf-8')))
               if isinstance(n,ast.FunctionDef) and n.name in
               ('_bot_refresh_action_accounts','_bot_send_selected_action')]
        scope={}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(p),'exec'),scope)
        accounts=[{'id':i,'label':i} for i in ('a','b','c','d')]
        live=SimpleNamespace(authenticated=True,stop=SimpleNamespace(is_set=lambda:False))
        closed=SimpleNamespace(authenticated=True,stop=SimpleNamespace(is_set=lambda:True))
        app=SimpleNamespace(_account_profiles=accounts,
            _tcp_sessions={'a':live,'b':live,'c':closed},
            _bot_action_inflight=set(),bot_action_account_var=Mock(),
            bot_action_account_picker=Mock(),bot_status_var=Mock())
        app.bot_action_account_var.get.return_value='All connected accounts'
        app._bot_send_action=Mock(side_effect=lambda account_override:
            app._bot_action_inflight.add(account_override['id']))
        scope['_bot_refresh_action_accounts'](app)
        app.bot_action_account_picker.configure.assert_called_once_with(
            values=['All connected accounts','a [a]','b [b]'])
        app.bot_action_account_var.set.assert_not_called()
        scope['_bot_send_selected_action'](app)
        self.assertEqual([c.kwargs['account_override']['id'] for c in
                          app._bot_send_action.call_args_list],['a','b'])
        self.assertIn('2/2',app.bot_status_var.set.call_args.args[0])


    def test_random_outfits_only_send_once_to_each_connected_account(self):
        p=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
        node=next(n for n in ast.walk(ast.parse(p.read_text(encoding='utf-8')))
                  if isinstance(n,ast.FunctionDef) and n.name=='_bot_randomize_outfits')
        from clientless_bot import random_clientless_figure
        scope={'random_clientless_figure':random_clientless_figure}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),scope)
        live=SimpleNamespace(authenticated=True,stop=SimpleNamespace(is_set=lambda:False))
        accounts=[{'id':i,'label':i} for i in ('a','b','c','d')]
        app=SimpleNamespace(_account_profiles=accounts,_tcp_sessions={'a':live,'b':live,'c':live},
            _bot_action_inflight={'c'},bot_account_var=Mock(),bot_outfit_mode_var=Mock(),
            bot_outfit_status_var=Mock())
        app.bot_account_var.get.return_value='All connected accounts'
        app.bot_outfit_mode_var.get.return_value='Male'
        app._bot_send_action=Mock(side_effect=lambda **kw:
            app._bot_action_inflight.add(kw['account_override']['id']))
        scope[node.name](app)
        calls=app._bot_send_action.call_args_list
        self.assertEqual([c.kwargs['account_override']['id'] for c in calls],['a','b'])
        self.assertTrue(all(c.kwargs['action_override']=='Change outfit' for c in calls))
        self.assertTrue(all(c.kwargs['outfit_override'][0]=='M' for c in calls))
        self.assertNotEqual(calls[0].kwargs['outfit_override'],calls[1].kwargs['outfit_override'])
        self.assertIn('2/3',app.bot_outfit_status_var.set.call_args.args[0])
