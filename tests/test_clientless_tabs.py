"""Offline structural regression for the Clientless workspace tabs."""
import ast
from pathlib import Path
from unittest import TestCase
SOURCE=(Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw').read_text(encoding='utf-8')
METHODS={n.name:ast.get_source_segment(SOURCE,n) for n in ast.walk(ast.parse(SOURCE))
         if isinstance(n,ast.FunctionDef) and n.name in
         ('_make_clientless_tabs','_make_clientless_bot_panel','_make_clientless_coffee_panel')}
class ClientlessTabTests(TestCase):
    def test_coffee_tab_has_independent_scroll(self):
        code=METHODS['_make_clientless_tabs']
        self.assertIn("tabs.add(coffee,text='Coffee Pass')",code)
        self.assertIn("tabs.add(main,text='Clientless controls')",code)
        self.assertIn("self._ui_scroll_area(coffee,'bot_coffee')",code)
        self.assertIn("self._ui_scroll_area(main,'bot_controls')",code)
        self.assertIn("self._ui_scroll_canvases['bot']",code)
        self.assertNotIn('_make_clientless_coffee_panel',METHODS['_make_clientless_bot_panel'])
    def test_coffee_panel_has_dark_frames_and_existing_controls(self):
        code=METHODS['_make_clientless_coffee_panel']
        self.assertIn("style='Panel.TFrame'",code)
        self.assertIn("476989081",code)
        self.assertIn("476989024",code)
        self.assertIn("self._coffee_group_apply",code)
        self.assertIn("self._coffee_group_stop",code)
