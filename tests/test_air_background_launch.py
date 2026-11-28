"""Offline checks for the native launch route."""
import ast
from pathlib import Path
import unittest

SOURCE=(Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw').read_text(encoding='utf-8')
METHODS={n.name:ast.get_source_segment(SOURCE,n) for n in ast.walk(ast.parse(SOURCE))
         if isinstance(n,ast.FunctionDef)}

class AirBackgroundLaunchTests(unittest.TestCase):
    def test_native_launch_uses_normal_browser_and_single_play_pass(self):
        code=METHODS['account_air_browser_command']
        self.assertNotIn('--start-minimized',code)
        self.assertNotIn('--headless',code)
        worker=METHODS['_account_auto_worker']
        native=worker.split('prelaunched=set()',1)[0]
        self.assertIn('account_air_browser_command(',native)
        self.assertEqual(native.count('account_attempt_auto_play('),1)
        self.assertIn('credentials=credentials,login_only=False',native)
        self.assertIn('account_show_login_browser(debug_port)',native)
        self.assertIn('if spawned is not None and not keep_browser:',native)
        self.assertIn("('game_panel_arm',generation,native_before)",native)

    def test_native_controller_waits_for_visible_controls(self):
        code=METHODS['account_playwright_auto_play']
        self.assertIn('page.bring_to_front()',code)
        self.assertIn('for _ in range(24):',code)
        self.assertIn('No additional login submitted.',code)
        self.assertIn('native_site_error()',code)
