"""Offline checks for profile-owned launch modes; no external connections."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
node=next(n for n in ast.walk(ast.parse(SOURCE.read_text(encoding='utf-8')))
          if isinstance(n,ast.FunctionDef) and n.name=='_bot_run_configured_account')
scope={}
exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),scope)

class ProfileLaunchModeTests(TestCase):
    def fixture(self):
        return SimpleNamespace(_tcp_sessions={},_tcp_inflight=set(),
            _bot_gearth_bridges={},bot_status_var=Mock(),_bot_run_account=Mock())
    def test_saved_routes_are_explicit(self):
        for mode,direct,gearth in [('clientless',True,False),('clientless_gearth',False,True)]:
            app=self.fixture()
            account={'id':'abcdef123456','launch_mode':mode}
            scope[node.name](app,account)
            app._bot_run_account.assert_called_once_with(account,force_direct=direct,force_gearth=gearth)
    def test_air_selection_does_not_start_bot(self):
        app=self.fixture()
        scope[node.name](app,{'id':'abcdef123456','launch_mode':'air'})
        app._bot_run_account.assert_not_called()
    def test_existing_direct_socket_cannot_switch_to_proxy(self):
        app=self.fixture()
        app._tcp_sessions['abcdef123456']=SimpleNamespace(authenticated=True,
            stop=SimpleNamespace(is_set=lambda:False))
        scope[node.name](app,{'id':'abcdef123456','launch_mode':'clientless_gearth'})
        app._bot_run_account.assert_not_called()
        self.assertIn('Disconnect',app.bot_status_var.set.call_args.args[0])
