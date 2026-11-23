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
