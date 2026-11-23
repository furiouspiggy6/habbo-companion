"""Windows Tk UI smoke test for the modern-dark Habbo Companion workspace.

This instantiates the real controls with background processing disabled. It
never starts G-Earth, a browser, the real Habbo client, or a network request.
"""
from pathlib import Path
import tempfile
import time
import runpy
import sys
import tkinter as tk

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
scope=runpy.run_path(str(ROOT/'Habbo_Companion.pyw'),
                     run_name='habbo_companion_ui_smoke')
App=scope['ChatOverlayApp']
PAGES={'overview','accounts','tcp','bot','chat','responder','packet','outfits','face','dance','fuzz','manip',
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
    assert app.bot_account_picker.winfo_exists(), 'Clientless Bot account list missing'
    assert app.bot_action_picker.winfo_exists(), 'Clientless Bot action list missing'
    assert app.bot_chat_log.winfo_exists(), 'Clientless chat display missing'
    assert app._bot_action_inflight==set(), 'Clientless actions must start idle'
    assert app.packet_tree.winfo_exists(), 'Packet Viewer failed to build'
    assert app.outfit_listbox.winfo_exists(), 'Outfit Cycler UI failed to build'
    assert not app._outfit_running, 'Outfit Cycler must start OFF'
    assert app.outfit_delay_var.get()=='300', 'Incorrect default millisecond interval'
    assert not app._face_running, 'Face Rotator must start OFF'
    assert app._face_tile is None, 'Face Rotator must require a fresh standing tile'
    assert app.face_delay_var.get()=='350', 'Incorrect default face turn interval'
    assert app.face_direction_var.get()=='Clockwise', 'Incorrect default direction'
    assert not app._dance_running, 'Dance Controller must start OFF'
    assert app.dance_style_var.get()=='Hab-Hop (everyone)'
    assert app.dance_delay_var.get()=='3000'
    assert app.dance_style_picker.winfo_exists(), 'Dance selector did not render'
    assert len(app.dance_enabled_vars)==4, 'Missing dance-cycle choices'
    assert app.fuzz_live_var.get().startswith('Passive reader OFF'), 'Protocol Lab failed to initialize'
    assert app.arcturus_header_var.get()=='', (
        'Arcturus header must be supplied by the emulator owner, never guessed')
    assert app.arcturus_cases_var.get()=='20'
    assert '127.0.0.1:30000' in app.arcturus_status_var.get()
    app._fuzz_preview_arcturus()
    assert 'Enter a known Arcturus header ID' in app.arcturus_status_var.get(), (
        'Empty header must fail safely without connecting to any server')
    app.arcturus_header_var.set('not-a-number')
    app._fuzz_preview_arcturus()
    assert 'Preview error:' in app.arcturus_status_var.get()
    app.arcturus_header_var.set('896')
    assert app._fuzz_arcturus_header_id()==896
    app.arcturus_cases_var.set('1000')
    app._fuzz_start_arcturus()
    assert 'Invalid Arcturus test' in app.arcturus_status_var.get(), (
        'Too many cases must be rejected without opening a socket')
    app.arcturus_cases_var.set('20')
    assert app.rules_tree.winfo_exists(), 'Packet Manipulator failed to build'
    assert app.tcp_log.winfo_exists(), 'Server log failed to build'
    assert app.responder_log_text.winfo_exists(), (
        'AI Responder activity log missing')
    assert not app.responder.enabled, 'AI must start OFF'
    assert not app.responder_send_var.get(), 'Sending must start OFF'
    assert app.responder.save_history, (
        'Public chat must be archived even with AI disabled')
    assert app.responder.archive_dir==app._responder_app_dir/'persona_logs'/'users'
    assert app.responder_instruction_input.winfo_exists()
    assert app.responder_style_search_entry.winfo_exists()
    assert app.responder_personality_entry.winfo_exists()
    assert app.responder_target_search_entry.winfo_exists()
    assert app.responder_everyone_check.winfo_exists()
    assert not hasattr(app,'_responder_advanced_button'), (
        'Redundant Advanced options should be gone')
    assert not hasattr(app,'responder_target_selector'), (
        'Old Reply To dropdown should be replaced with checkboxes')
    assert not hasattr(app,'responder_tone_combo')
    assert not hasattr(app,'responder_humour_combo')
    assert not hasattr(app,'responder_responsiveness_combo')
    assert not hasattr(app,'responder_rotation_check')
    assert 'ON' not in app.responder_log_saving_var.get() or app.responder.save_history

    # The slider must be usable for both custom personas and saved chat personas.
    assert app.responder.reply_cooldown_seconds==10
    assert int(float(app.responder_reply_interval_scale.cget('from')))==0
    assert int(float(app.responder_reply_interval_scale.cget('to')))==30
    assert 'disabled' not in app.responder_reply_interval_scale.state()
    app.responder_reply_interval_var.set(0)
    app._responder_reply_speed_changed(0)
    app._responder_commit_reply_speed()
    assert app.responder.reply_cooldown_seconds==0
    assert app.config['responder_reply_interval']==0
    assert 'Immediately' in app.responder_reply_interval_text.get()
    app.responder_reply_interval_var.set(30)
    app._responder_reply_speed_changed(30)
    app._responder_commit_reply_speed()
    assert app.responder.reply_cooldown_seconds==30
    assert app.config['responder_reply_interval']==30

    # Current room roster drives visible actual checkboxes—not historical logs.
    app._own_name='ownAvatar'
    app._room_users={
        'maragene':('MaraGene',12345,4),
        'cheesecake':('Cheesecake',56789,6),
        'ownavatar':('ownAvatar',111,1),
    }
    app._responder_room_speakers={'popbrocks':('popbrocks',time.time())}
    app._responder_refresh_room_users()
    assert app._responder_room_names==[
        'Cheesecake','MaraGene','popbrocks']
    assert app.responder_everyone_var.get(), (
        'Everyone should be checked by default')
    assert all(var.get() for _name,var in
               app._responder_target_checkboxes.values())
    original_save=app.save
    app.save=lambda:None
    try:
        app.responder_everyone_var.set(False)
        app._responder_toggle_everyone()
        assert app.responder_target_mode_var.get()=='Selected users'
        assert not app.responder_target_var.get()
        assert all(not var.get() for _name,var in
                   app._responder_target_checkboxes.values())
        assert not app.responder.enabled
        app._responder_target_checkboxes['maragene'][1].set(True)
        app._responder_target_selection_changed()
        assert app.responder.selected_users=='MaraGene'
        app._responder_target_checkboxes['popbrocks'][1].set(True)
        app._responder_target_selection_changed()
        assert app.responder.selected_users=='MaraGene, popbrocks'
        app.responder_target_search_var.set('GENE')
        app._responder_render_target_checklist()
        assert set(app._responder_target_checkboxes)=={'maragene'}
        assert app._responder_target_checkboxes['maragene'][1].get()
        app.responder_target_search_var.set('')
        app._responder_render_target_checklist()
        assert app._responder_target_checkboxes['popbrocks'][1].get(), (
            'Filtering must not lose checked selections')
        app.responder_everyone_var.set(True)
        app._responder_toggle_everyone()
        assert app.responder_target_mode_var.get()=='Everyone'
        assert all(var.get() for _name,var in
                   app._responder_target_checkboxes.values())
        # Live-room user joins while Everyone is ticked.
        app._room_users['newplayer']=('NewPlayer',556,7)
        app._responder_refresh_room_users()
        assert app._responder_target_checkboxes['newplayer'][1].get()
        # Unchecking an individual switches to selected subset.
        app._responder_target_checkboxes['maragene'][1].set(False)
        app._responder_target_selection_changed()
        assert app.responder.target_mode=='Selected users'
        assert 'maragene' not in app.responder.selected_users.casefold()
        assert 'NewPlayer' in app.responder.selected_users
        # G-Earth confirms an indexed avatar has left: remove their checkbox,
        # selected target and any pending work for the departed player.
        app._room_users.pop('newplayer')
        app._responder_remove_departed_targets(('newplayer',))
        assert 'newplayer' not in app._responder_target_checkboxes
        assert 'newplayer' not in app.responder.selected_users.casefold()
        assert app.responder.target_mode=='Selected users'
        # A player only inferred from AIR chat must disappear after silence.
        app._responder_room_speakers['popbrocks']=('popbrocks',time.time()-100)
        app._responder_refresh_room_users()
        assert 'popbrocks' not in app._responder_target_checkboxes
        assert 'popbrocks' not in app._responder_room_names
        # Unindexed Users packet names also expire if no newer chat or
        # roster evidence confirms that the player remains here.
        app._room_users['unknown-index']=('UnknownIndex',123456,None)
        app._responder_room_roster_seen_at['unknown-index']=time.time()-100
        app._responder_refresh_room_users()
        assert 'unknown-index' not in app._responder_target_checkboxes
        assert app.responder.save_history

        # Selecting a saved persona hides unrelated custom options but keeps
        # the reply-speed slider active.
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'MaraGene.txt').write_text(
                '[13:01] MaraGene: heyyy lol\n'
                '[13:02] MaraGene: wbuuu\n',encoding='utf-8')
            app.responder_log_dir_var.set(folder)
            app._responder_refresh_style_users()
            app.responder_style_search_var.set('gene')
            app._responder_filter_style_users()
            assert app._responder_style_matches==['MaraGene']
            app.responder_style_matches_list.selection_set(0)
            app._responder_select_style_user()
            assert app.responder.style_mode=='Chat-log style'
            assert app.responder.persona=='MaraGene'
            assert not app._responder_custom_frame.winfo_manager(), (
                'Custom personality must hide while recreating a saved persona')
            assert 'disabled' not in app.responder_reply_interval_scale.state()
            assert not {'tone','humour','responsiveness','personality'}.intersection(
                app.responder.test_payload('Alice','hey'))
            app._responder_use_custom_style()
            assert app._responder_custom_frame.winfo_manager()=='pack'
            assert app.responder_personality_entry.cget('state')=='normal'
            app.responder_personality_entry.delete('1.0','end')
            app.responder_personality_entry.insert(
                '1.0','A sarcastic, sleepy Habbo visitor.')
            app._responder_apply()
            assert app.responder.personality=='A sarcastic, sleepy Habbo visitor.'
            assert app.responder.test_payload('Alice','hey')['personality']==(
                'A sarcastic, sleepy Habbo visitor.')

        # One enable control is sufficient: AI-on sends through G-Earth,
        # AI-off stops both generating and sending.
        app.responder_everyone_var.set(True)
        app._responder_toggle_everyone()
        app.responder_enabled_var.set(True)
        app._responder_apply()
        assert app.responder.enabled and app.responder_send_var.get()
        app._responder_stop()
        assert not app.responder.enabled and not app.responder_send_var.get()
        assert app.responder.save_history, 'Logging must remain ON after stopping AI'
        app.responder_instruction_input.insert(
            '1.0','type slow\npretend to go afk for 2mins')
        app._responder_add_instructions()
        assert len(app.responder.temporary_instructions)==2
        assert app.responder_instruction_list.winfo_manager()=='pack'
        app._responder_clear_instructions()
        assert not app.responder_instruction_list.winfo_manager(), (
            'Empty instruction list must collapse')
    finally:
        app.save=original_save
    app._room_users.clear()
    app._responder_room_speakers.clear()
    app._responder_refresh_room_users()
    assert not app._responder_room_names
    assert not app._responder_target_checkboxes
    assert not app.responder.enabled
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
    print('Modern-dark Tkinter workspace and all twelve navigation pages: PASS')
finally:
    root.destroy()
