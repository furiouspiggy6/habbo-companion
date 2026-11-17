"""Offline checks for the 2026 modern-dark Companion workspace.

These tests inspect the real Tkinter source without needing Windows, browser
credentials, a game connection or a display server.
"""
import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'Habbo_Companion.pyw').read_text(encoding='utf-8')
TREE=ast.parse(SOURCE)
APP=next(n for n in TREE.body if isinstance(n,ast.ClassDef)
         and n.name=='ChatOverlayApp')
METHODS={n.name:n for n in APP.body if isinstance(n,ast.FunctionDef)}
PAGE_NAMES={'overview','accounts','tcp','chat','packet','manip',
            'classic','headless','updates'}


class ModernWorkspaceTests(unittest.TestCase):
    def test_nine_sections_are_accessible_from_sidebar(self):
        for name in ('_ui_styles','_ui_add_nav','_ui_show_page',
                     '_ui_scroll_area','_ui_mousewheel',
                     '_make_dashboard_panel','_make_settings',
                     '_make_accounts_panel'):
            self.assertIn(name,METHODS)
        settings=ast.get_source_segment(SOURCE,METHODS['_make_settings'])
        for key in PAGE_NAMES:
            self.assertIn("'"+key+"'",settings)
        self.assertNotIn('self.notebook=',settings)
        self.assertIn("self._ui_show_page('overview')",settings)
        self.assertIn('self._make_packet_panel(',settings)
        self.assertIn('self._make_accounts_panel(',settings)
        self.assertIn('self._make_live_tcp_panel(',settings)
        self.assertIn('self._make_direct_classic_panel(',settings)
        self.assertIn('self._make_manipulator_panel(',settings)
        self.assertIn('self._make_headless_panel(',settings)
        self.assertIn('self._make_updates_panel(',settings)

    def test_existing_security_and_connection_buttons_are_preserved(self):
        accounts=ast.get_source_segment(SOURCE,METHODS['_make_accounts_panel'])
        for callback in ('_account_add','_account_remove',
                         '_account_save_selected','_account_save_login',
                         '_account_forget_login','_account_open_login',
                         '_account_auto_play','_account_resume_pending',
                         '_account_use_port','_account_check_port'):
            self.assertIn('self.'+callback,accounts)
        self.assertIn("show='*' if secret else ''",accounts)
        self.assertIn('self._accounts_render()',accounts)
        tcp=ast.get_source_segment(SOURCE,METHODS['_make_live_tcp_panel'])
        for callback in ('_tcp_auto_import_selected','_tcp_connect_all',
                         '_tcp_disconnect_all','_tcp_test_classic_websocket'):
            self.assertIn('self.'+callback,tcp)

    def test_scroll_dispatch_is_page_specific(self):
        settings=ast.get_source_segment(SOURCE,METHODS['_make_settings'])
        self.assertIn("self._ui_scroll_canvases['chat']=content",settings)
        self.assertIn("self.root.bind('<MouseWheel>',self._ui_mousewheel)",
                      settings)
        self.assertNotIn("self.root.bind('<MouseWheel>',scroll_panel)",settings)
        scroll=ast.get_source_segment(SOURCE,METHODS['_ui_mousewheel'])
        self.assertIn('self._ui_active',scroll)
        self.assertIn('ttk.Treeview',scroll)
        self.assertIn('tk.Text',scroll)

    def test_palette_is_independent_from_habbo_bubble_theme(self):
        palettes=next(n for n in TREE.body if isinstance(n,ast.Assign)
                      and any(isinstance(t,ast.Name) and t.id=='COMPANION_UI'
                              for t in n.targets))
        names=ast.literal_eval(palettes.value)
        self.assertTrue(all(value.startswith('#') and len(value)==7
                            for value in names.values()))
        self.assertNotEqual(names['background'],names['surface'])
        self.assertNotEqual(names['sidebar'],names['surface'])
        self.assertIn("'Midnight': dict(room=",SOURCE)
        self.assertIn("self.config['original_bubble_images']=True",SOURCE)

    def test_dashboard_connection_counts_do_not_infer_server_login(self):
        source=ast.get_source_segment(SOURCE,METHODS['_ui_refresh_dashboard'])
        self.assertIn('sess.authenticated',source)
        self.assertIn('self._tcp_inflight',source)
        self.assertNotIn('session_hint',source)
        self.assertNotIn('cookies',source)


if __name__=='__main__':
    unittest.main()
