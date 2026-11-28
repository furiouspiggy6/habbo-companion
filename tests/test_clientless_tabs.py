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
        self.assertNotIn("text='Sessions'",code)
        self.assertIn("tabs.add(actions,text='Actions & chat')",code)
        self.assertIn("tabs.add(automation,text='Automation')",code)
        self.assertIn("self._ui_scroll_area(actions,'bot_actions')",code)
        self.assertIn("self._ui_scroll_area(automation,'bot_automation')",code)
        self.assertIn("self._ui_scroll_area(coffee,'bot_coffee')",code)
        self.assertIn("self._ui_scroll_canvases['bot']",code)
        self.assertIn("tabs.add(connection,text='Settings')",code)
        self.assertIn("self._ui_scroll_area(connection,'bot_connection')",code)
        self.assertIn("str(connection):'bot_connection'",code)
        self.assertLess(code.index("self._make_clientless_connection_panel("),
                        code.index("self._make_clientless_bot_panel("))
        self.assertNotIn('_make_clientless_coffee_panel',METHODS['_make_clientless_bot_panel'])
    def test_coffee_panel_has_dark_frames_and_existing_controls(self):
        code=METHODS['_make_clientless_coffee_panel']
        self.assertIn("style='Panel.TFrame'",code)
        self.assertIn("476989081",code)
        self.assertIn("476989024",code)
        self.assertIn("self._coffee_group_apply",code)
        self.assertIn("self._coffee_group_stop",code)

    def test_shared_context_and_action_fields(self):
        code=METHODS['_make_clientless_bot_panel']
        self.assertIn('textvariable=self.bot_room_var',code)
        self.assertIn('context,textvariable=self.bot_account_var',code)
        self.assertIn("self.bot_action_var.trace_add('write',show_action_fields)",code)
        self.assertIn("row.pack_forget()",code)
        self.assertIn("command=self._bot_send_selected_action",code)
        self.assertIn("frame=ttk.Frame(automation",code)
        self.assertIn("frame=ttk.Frame(settings",code)
