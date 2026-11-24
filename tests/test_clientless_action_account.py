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
