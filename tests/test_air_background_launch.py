"""Offline checks for minimised native launch route."""
import ast
from pathlib import Path
import unittest

SOURCE=(Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw').read_text(encoding='utf-8')
METHODS={n.name:ast.get_source_segment(SOURCE,n) for n in ast.walk(ast.parse(SOURCE))
         if isinstance(n,ast.FunctionDef)}

class AirBackgroundLaunchTests(unittest.TestCase):
    def test_native_launch_uses_minimised_normal_browser(self):
        code=METHODS['account_air_browser_command']
        self.assertIn('--start-minimized',code)
        self.assertNotIn('--headless',code)
        worker=METHODS['_account_auto_worker']
        self.assertIn('account_air_browser_command(',worker)
        self.assertIn('credentials=None,login_only=False',worker)
        self.assertIn("outcome!='signed_in'",worker)
        self.assertIn('if spawned is not None and not keep_browser:',worker)
        self.assertIn("('game_panel_arm',generation,native_before)",worker)
        self.assertIn('account_show_login_browser(port)',worker)
