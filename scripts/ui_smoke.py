"""Windows Tk UI smoke test for the modern-dark Habbo Companion workspace.

This instantiates the real controls with background processing disabled. It
never starts G-Earth, a browser, the real Habbo client, or a network request.
"""
from pathlib import Path
import tempfile
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
    assert app.responder.reply_cooldown_seconds==30, (
        'Default reply interval should be a less spammy 30 seconds')
    assert app.responder_reply_interval_scale.winfo_exists(), (
        'Main AI Responder reply-speed slider is missing')
    assert app.responder_reply_interval_text.get().endswith('30 sec'), (
        'Slider must display the current minimum reply interval')
    app.responder_reply_interval_var.set(95)
    app._responder_reply_speed_changed(95)
    assert app.responder.reply_cooldown_seconds==95, (
        'Dragging speed slider must adjust the live AI throttle')
    app._responder_commit_reply_speed()
    assert app.config['responder_reply_interval']==95, (
        'Reply speed must be persisted for next launch')
    assert not app.responder.enabled and not app.responder_send_var.get(), (
        'Moving the slider must not enable the bot or automatic sending')
    assert app.responder.save_history, (
        'Background public chat saving should start ON independently of AI')
    assert app.responder.archive_dir==app._responder_app_dir/'persona_logs'/'users', (
        'Background chat should always be archived to Companion persona_logs/users')
    assert app.responder_capture_var.get(), (
        'Background logging checkbox must reflect enabled state')
    assert 'ON' in app.responder_log_saving_var.get(), (
        'Main responder view should show background logging status')
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
    assert app.responder_target_search_entry.winfo_exists(), (
        'Search room-players input must be available')
    assert app.responder_target_matches_list.winfo_exists(), (
        'Live room username suggestion list is missing')
    assert not app.responder_target_matches_list.winfo_manager(), (
        'Room suggestions must start collapsed')
    # In-room G-Earth roster can include quiet players; AIR public-chat
    # speakers are also eligible even if they are outside the view.
    app._own_name='ownAvatar'
    app._room_users={
        'maragene':('MaraGene',12345,4),
        'cheesecake':('Cheesecake',56789,6),
        'ownavatar':('ownAvatar',111,1),
    }
    app._responder_room_speakers={
        'popbrocks':('popbrocks',123456.0),
    }
    app._responder_refresh_room_users(show=False)
    assert app._responder_room_names==[
        'Cheesecake','MaraGene','popbrocks'], (
        'Room player suggestions must include only this room, not historical logs')
    assert not app.responder_target_matches_list.winfo_manager()
    app.responder_target_search_var.set('ARAg')
    app._responder_refresh_room_users(show=True)
    assert app._responder_target_matches==['MaraGene'], (
        'Case-insensitive substring search of current room failed')
    assert app.responder_target_matches_list.winfo_manager()=='pack'
    assert app.responder_target_matches_list.size()==1
    app.responder_target_matches_list.selection_set(0)
    original_save=app.save
    app.save=lambda:None
    try:
        app._responder_choose_target_user()
        assert app.responder_target_var.get()=='MaraGene'
        assert app.responder.target_mode=='Selected users'
        assert app.responder.selected_users=='MaraGene'
        assert not app.responder_target_matches_list.winfo_manager(), (
            'Selecting a room suggestion must collapse the dropdown')
        app.responder_target_search_var.set('BROCK')
        app._responder_refresh_room_users(show=True)
        assert app._responder_target_matches==['popbrocks']
        app.responder_target_matches_list.selection_set(0)
        app._responder_choose_target_user()
        assert app.responder.selected_users=='MaraGene, popbrocks', (
            'Multiple room selections must accumulate without duplicates')
        app.responder_target_search_var.set('BROCK')
        app._responder_refresh_room_users(show=True)
        app.responder_target_matches_list.selection_set(0)
        app._responder_choose_target_user()
        assert app.responder.selected_users=='MaraGene, popbrocks', (
            'Choosing the same user twice must not duplicate targets')
        app._room_users.clear()
        app._responder_room_speakers.clear()
        app._responder_refresh_room_users(show=True)
        assert not app._responder_room_names, (
            'Disconnected/cleared room must not offer stale users')
        assert not app.responder_target_matches_list.winfo_manager()
    finally:
        app.save=original_save
    app.responder_target_mode_var.set('Everyone')
    app._responder_update_target_controls()
    assert not app._responder_targets_frame.winfo_manager(), (
        'Selected users input did not hide')
    assert app.responder_style_search_entry.winfo_exists(), (
        'Searchable saved username field is missing')
    assert app.responder_style_matches_list.winfo_exists(), (
        'Saved-username suggestions list is missing')
    assert not app.responder_style_matches_list.winfo_manager(), (
        'Suggestions should not expand before searching')
    app._responder_toggle_advanced()
    assert app._responder_advanced_open
    assert app._responder_advanced_frame.winfo_manager()=='pack', (
        'Advanced settings did not expand')
    assert app._responder_logs_frame.winfo_manager()=='pack', (
        'Saved chat-log preferences are inaccessible')
    app._responder_toggle_advanced()
    assert not app._responder_advanced_open
    assert not app._responder_advanced_frame.winfo_manager(), (
        'Advanced settings did not collapse')
    # Confirm both collapsing panels actually reclaim vertical space.
    # The old fill=both/expand=True settings created a huge empty gap.
    app._ui_show_page('responder')
    root.update_idletasks()
    assert app.responder_log_text.winfo_manager()=='pack'
    assert (app.responder_log_text.winfo_y()-
            app._responder_advanced_button.winfo_y()) < 180, (
        'Collapsed Advanced left a large empty gap above Recent Activity')
    assert not app.responder_target_matches_list.winfo_manager()
    assert not app.responder_style_matches_list.winfo_manager()
    # Verify filtering and selecting a real per-user file automatically switches
    # to that specific writing style without enabling any live game sends.
    with tempfile.TemporaryDirectory() as folder:
        (Path(folder)/'MaraGene.txt').write_text(
            '[13:01] MaraGene: heyyy lol\n'
            '[13:02] MaraGene: wbuuu\n',encoding='utf-8')
        (Path(folder)/'Mario35.txt').write_text(
            '[13:03] Mario35: hello\n',encoding='utf-8')
        app.responder_log_dir_var.set(folder)
        app._responder_refresh_style_users()
        assert len(app._responder_style_users)==2, (
            'User log listing failed')
        assert not app.responder_style_matches_list.winfo_manager(), (
            'Search unexpectedly opened the dropdown on refresh')
        app.responder_style_search_var.set('GeNe')
        app._responder_filter_style_users()
        assert app._responder_style_matches==['MaraGene'], (
            'Partial case-insensitive username search failed')
        assert app.responder_style_matches_list.winfo_manager()=='pack', (
            'Search result dropdown did not open')
        app.responder_style_matches_list.selection_set(0)
        original_save=app.save
        app.save=lambda:None
        try:
            app._responder_select_style_user()
            assert app.responder.style_mode=='Chat-log style'
            assert app.responder.save_history, (
                'Selecting a style must not disable background logging')
            assert app.responder.persona=='MaraGene'
            assert app.responder.archive_dir==app._responder_app_dir/'persona_logs'/'users', (
                'Changing style sample folder must not move the background archive')
            assert app.responder.style_examples()==['heyyy lol','wbuuu']
            assert app.responder_personality_entry.cget('state')=='disabled'
            assert not app.responder.auto_rotate, (
                'Single-user style must not rotate unexpectedly')
            assert not app.responder.enabled and not app.responder_send_var.get(), (
                'Selecting a style must not start game messaging')
            app._responder_use_custom_style()
            assert app.responder.style_mode=='Custom personality'
            assert app.responder.save_history, (
                'Custom personality must not disable background logging')
            assert app.responder_personality_entry.cget('state')=='normal'
            app.responder_capture_var.set(False)
            app._responder_change_logging()
            assert not app.responder.save_history and not app.responder.enabled
            app.responder_capture_var.set(True)
            app._responder_change_logging()
            assert app.responder.save_history and not app.responder.enabled
        finally:
            app.save=original_save
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
