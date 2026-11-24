"""Offline regression tests for intercepted AIR launch preflight."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)
            and n.name=='_account_launch_selected_mode')

class LaunchGuardTests(TestCase):
    def run_guard(self,native=frozenset(),connected=False,attached=9092):
        scope={'account_native_client_windows':lambda:native,
               'messagebox':SimpleNamespace(askyesno=lambda *a,**k:True)}
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(SOURCE),'exec'),scope)
        app=SimpleNamespace(
            _account_selected=lambda:{'port':9092},
            _account_auto_running=False,
            account_launch_mode_var=SimpleNamespace(get=lambda:'gearth'),
            _account_remember_launch_mode=Mock(),
            gearth_auto_arm_var=Mock(),config={},bot_standalone_var=Mock(),
            save=Mock(),packet_started=True,_account_attached_port=attached,
            _habbo_session_connected=connected,account_status_var=Mock(),
            _account_use_port=Mock(),_gearth_extension_port_responds=lambda p:True,
            _account_auto_play=Mock(),root=None)
        scope[method.name](app)
        return app

    def test_idle_matching_extension_reused(self):
        app=self.run_guard()
        app._account_auto_play.assert_called_once_with(explicit_launch_mode='gearth')

    def test_active_game_or_different_endpoint_blocks(self):
        for args in ({'native':frozenset({(1,2)})},{'connected':True},
                     {'attached':9093},{'native':None}):
            with self.subTest(args=args):
                app=self.run_guard(**args)
                app._account_auto_play.assert_not_called()
                app.account_status_var.set.assert_called()
