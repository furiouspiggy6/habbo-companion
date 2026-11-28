"""Offline structural checks for the native game panel (no game or network)."""
import ast
from pathlib import Path
import unittest

SOURCE=(Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw').read_text(encoding='utf-8')
METHODS={n.name:ast.get_source_segment(SOURCE,n) for n in ast.walk(ast.parse(SOURCE))
         if isinstance(n,ast.FunctionDef)}

class GamePanelTests(unittest.TestCase):
    def test_only_native_launch_arms_panel(self):
        worker=METHODS['_account_auto_worker']
        self.assertIn("('game_panel_arm',generation,native_before)",worker)
        self.assertIn('if native_before is not None:',worker)
        self.assertIn('account_native_client_windows()',METHODS['_game_panel_scan'])
        self.assertIn('set(current)-baseline',METHODS['_game_panel_scan'])

    def test_hotkey_and_recovery(self):
        hotkeys=METHODS['_hotkeys']
        self.assertIn('0xC0',hotkeys)
        self.assertIn('shift and not ctrl and not alt',hotkeys)
        self.assertIn('active-self.last_hotkeys',hotkeys)
        self.assertIn('self._game_panel_toggle()',hotkeys)
        self.assertIn('self._game_panel_detach()',hotkeys)
        self.assertIn('foreground_context',METHODS['_game_panel_toggle'])
        self.assertIn("=='habbo'",METHODS['_game_panel_toggle'])
        self.assertIn("=='settings'",METHODS['_game_panel_toggle'])

    def test_panel_is_interactive_and_not_globally_topmost(self):
        self.assertIn("self.root.attributes('-topmost',False)",METHODS['_game_panel_show'])
        self.assertIn('self.root.focus_force()',METHODS['_game_panel_show'])
        self.assertIn('self.root.withdraw()',METHODS['_game_panel_hide'])
        self.assertIn('self._game_panel_detach()',METHODS['_game_panel_scan'])
        self.assertNotIn('SetParent(',METHODS['_game_panel_show'])
