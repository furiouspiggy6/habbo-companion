"""Windows Tk UI smoke test for the modern-dark Habbo Companion workspace.

This instantiates the real controls with background processing disabled. It
never starts G-Earth, a browser, the real Habbo client, or a network request.
"""
from pathlib import Path
import runpy
import sys
import tkinter as tk

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
scope=runpy.run_path(str(ROOT/'Habbo_Companion.pyw'),
                     run_name='habbo_companion_ui_smoke')
App=scope['ChatOverlayApp']
PAGES={'overview','accounts','tcp','chat','responder','packet','fuzz','manip',
       'classic','headless','updates'}

# Do not create overlay hooks or start background network/engine work.
App._make_overlay=lambda self:None
App.tick=lambda self:None
App._pump_packets=lambda self:None
App._setup_wheel_hook=lambda self:None
App._tcp_auto_connect_startup=lambda self:None
App._auto_prepare_gearth=lambda self:None
App._engine_heartbeat=lambda self:None

root=tk.Tk()
try:
    root.withdraw()
    app=App(root)
    root.deiconify()
    root.update_idletasks()
    assert set(app._ui_pages)==PAGES, 'Missing workspace page'
    assert set(app._ui_nav_buttons)==PAGES, 'Missing sidebar destination'
    assert app._ui_active=='overview', 'Incorrect startup workspace'
    assert app.account_table.winfo_exists(), 'Accounts list failed to build'
    assert app.tcp_table.winfo_exists(), 'Direct TCP list failed to build'
    assert app.packet_tree.winfo_exists(), 'Packet Viewer failed to build'
    assert app.fuzz_live_var.get().startswith('Passive reader OFF'), 'Protocol Lab failed to initialize'
    assert app.rules_tree.winfo_exists(), 'Packet Manipulator failed to build'
    assert app.tcp_log.winfo_exists(), 'Server log failed to build'
    assert app.responder_log_text.winfo_exists(), 'AI Responder log failed to build'
    assert not app.responder.enabled, 'AI must start disabled'
    assert not app.responder_send_var.get(), 'Auto-send must start disabled'
    # Simplified single-screen responder: advanced controls remain available
    # but hidden; switching targets must reveal the username field in place.
    assert not app._responder_advanced_open, 'Advanced must start collapsed'
    assert not app._responder_advanced_frame.winfo_manager(), (
        'Advanced settings should be hidden initially')
    assert app.responder_personality_entry.winfo_exists(), (
        'Main personality editor missing')
    assert app.responder_target_selector.winfo_exists(), (
        'Main targeting selector missing')
    assert not app._responder_targets_frame.winfo_manager(), (
        'Usernames should be hidden when targeting Everyone')
    app.responder_target_mode_var.set('Selected users')
    app._responder_update_target_controls()
    assert app._responder_targets_frame.winfo_manager()=='pack', (
        'Selected users input did not appear')
    assert app._responder_targets_frame.master==app._responder_targets_area, (
        'Selected users input moved out of its reserved layout')
    app.responder_target_mode_var.set('Everyone')
    app._responder_update_target_controls()
    assert not app._responder_targets_frame.winfo_manager(), (
        'Selected users input did not hide')
    app._responder_toggle_advanced()
    assert app._responder_advanced_open
    assert app._responder_advanced_frame.winfo_manager()=='pack', (
        'Advanced settings did not expand')
    app.responder_style_mode_var.set('Chat-log style')
    app._responder_update_style_controls()
    assert app._responder_logs_frame.winfo_manager()=='pack', (
        'Optional chat-log controls are inaccessible')
    app.responder_style_mode_var.set('Custom personality')
    app._responder_update_style_controls()
    assert not app._responder_logs_frame.winfo_manager(), (
        'Legacy style fields should hide in custom mode')
    app._responder_toggle_advanced()
    assert not app._responder_advanced_open
    assert not app._responder_advanced_frame.winfo_manager(), (
        'Advanced settings did not collapse')
    assert not app.responder.enabled and not app.responder_send_var.get(), (
        'Navigating UI controls should never enable chat or sending')
    assert app._ui_scroll_canvases.keys()>=PAGES, 'Scrollable page missing'
    for page in PAGES:
        app._ui_show_page(page)
        root.update_idletasks()
        assert app._ui_active==page, 'Sidebar navigation failed: '+page
        title=app._ui_title_var.get()
        assert title, 'Empty page title: '+page
    app._ui_show_page('accounts')
    assert app._ui_title_var.get()=='Accounts'
    app._ui_show_page('overview')
    app._ui_refresh_dashboard()
    assert app._ui_dashboard_vars['accounts'].get().isdigit()
    assert root.winfo_width()>=940, 'Workspace width collapsed'
    print('Modern-dark Tkinter workspace and all eleven navigation pages: PASS')
finally:
    root.destroy()
