# -*- coding: utf-8 -*-
"""Tkinter integration for the opt-in Companion AI responder.

Used as a mixin so that the large legacy app keeps its existing features.
"""
from __future__ import annotations

from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog

from persona_responder import (
    PersonaResponder, chat_expression_from_template, generate_persona_reply,
    list_style_usernames, matching_style_usernames, clamp_reply_interval,
    selected_usernames,
)


class PersonaResponderMixin:
    def _responder_setup(self):
        legacy=Path(__file__).resolve().parent/'chat_logs'/'users'
        default_logs=legacy if legacy.is_dir() else self._responder_app_dir/'persona_logs'/'users'
        chosen=str(self.config.get('responder_log_dir','')).strip()
        self._responder_default_logs=default_logs
        self.responder=PersonaResponder(chosen or default_logs)
        self.responder.reply_cooldown_seconds=clamp_reply_interval(
            self.config.get('responder_reply_interval',10))
        # Always save fresh messages in Companion's own per-user archive,
        # even if the user browses a different historical style source.
        self.responder.archive_dir=self._responder_app_dir/'persona_logs'/'users'
        self.responder.persona=str(self.config.get('responder_persona','Mario35'))
        self.responder.auto_rotate=False  # One selected persona only.
        # Independent, default-on background archive: older versions kept
        # responder_capture=False and accidentally disabled it in custom mode.
        self.responder.save_history=True  # Always archive public chat, even with AI OFF.
        self.responder.style_mode=str(self.config.get('responder_style_mode','Custom personality'))
        self.responder.personality=str(self.config.get(
            'responder_personality',self.responder.personality))
        self.responder.tone=str(self.config.get('responder_tone','Casual'))
        self.responder.humour=int(self.config.get('responder_humour',2))
        self.responder.responsiveness=str(
            self.config.get('responder_responsiveness','Natural'))
        previous_target=str(self.config.get('responder_target','')).strip()
        self.responder.selected_users=str(
            self.config.get('responder_targets','') or previous_target)
        current_mode=str(self.config.get('responder_target_mode','Everyone'))
        if current_mode not in ('Everyone','Selected users'):
            # Old First active speaker has no equivalent checkbox: keep
            # targeting restricted, never silently broaden to Everyone.
            current_mode='Selected users'
        # On upgrade, preserve an older single-user target instead of silently
        # switching a previously targeted bot to Everyone.
        if previous_target and not self.config.get('responder_targets'):
            current_mode='Selected users'
        self.responder.target_mode=current_mode
        self.responder.fixed_target=''
        self.responder_enabled_var=tk.BooleanVar(value=False)
        # There is no separate send toggle: enabling the AI means sending via
        # the existing G-Earth game session when one is connected.
        self.responder_send_var=tk.BooleanVar(value=False)
        self.responder_everyone_var=tk.BooleanVar(
            value=self.responder.target_mode=='Everyone')
        self._responder_target_checkboxes={}
        self._responder_last_room_refresh=0.0
        self.responder_reply_interval_var=tk.DoubleVar(
            value=self.responder.reply_cooldown_seconds)
        self.responder_reply_interval_text=tk.StringVar(
            value=self._responder_reply_speed_label(
                self.responder.reply_cooldown_seconds))
        self.responder_rotation_var=tk.BooleanVar(value=self.responder.auto_rotate)
        self.responder_capture_var=tk.BooleanVar(value=self.responder.save_history)
        self.responder_log_saving_var=tk.StringVar(value='')
        self.responder_persona_var=tk.StringVar(value=self.responder.persona)
        self.responder_style_mode_var=tk.StringVar(value=self.responder.style_mode)
        self.responder_style_search_var=tk.StringVar(
            value=self.responder.persona if self.responder.style_mode=='Chat-log style' else '')
        self.responder_style_status_var=tk.StringVar(
            value='Using your custom personality.')
        self._responder_style_users=[]
        self._responder_style_matches=[]
        self._responder_style_sources={}
        self.responder_personality_text=self.responder.personality
        self.responder_tone_var=tk.StringVar(value=self.responder.tone)
        self.responder_humour_var=tk.StringVar(value=str(self.responder.humour))
        self.responder_responsiveness_var=tk.StringVar(
            value=self.responder.responsiveness)
        self.responder_target_mode_var=tk.StringVar(value=self.responder.target_mode)
        self.responder_target_var=tk.StringVar(value=self.responder.selected_users)
        self.responder_target_search_var=tk.StringVar(value='')
        self.responder_room_status_var=tk.StringVar(value='Search detected room players.')
        self._responder_room_names=[]
        self._responder_target_matches=[]
        self._responder_room_speakers={}
        self.responder_log_dir_var=tk.StringVar(value=str(self.responder.log_dir))
        self.responder_model_var=tk.StringVar(value=str(
            self.config.get('responder_model','gpt-5-mini')))
        self.responder_test_user_var=tk.StringVar(value='TestUser')
        self.responder_test_message_var=tk.StringVar(value='hey, what are you up to?')
        self.responder_status_var=tk.StringVar(
            value='OFF. Choose a personality or search your saved chat logs.')
        self._responder_results=queue.Queue()
        self._responder_generation=0
        self._responder_chat_template=None
        self._responder_outgoing_seen=False
        self._responder_last_draft=None
        self._responder_test_running=False
        self._responder_advanced_open=False
        self._responder_scheduled_send=None
        self._responder_instruction_rows=[]
        self._responder_instruction_display=()
        self.responder_instruction_status_var=tk.StringVar(
            value='No temporary instructions active.')

    def _make_responder_panel(self,parent):
        """Persona-first controls: choose identity, speed and live room audience."""
        p=self._responder_palette
        frame=ttk.Frame(parent,style='Panel.TFrame',padding=(18,16))
        frame.pack(fill='x')

        tk.Label(frame,text='AI RESPONDER',font=('Segoe UI Semibold',18),
                 bg=p['background'],fg=p['text']).pack(anchor='w')
        ttk.Label(frame,text='Choose a chat persona, who to reply to, and how fast.',
                  style='Panel.TLabel').pack(anchor='w',pady=(3,12))
        ttk.Checkbutton(frame,text='Enable AI responder (send in Habbo)',
                        variable=self.responder_enabled_var,
                        command=self._responder_apply).pack(
                            anchor='w',pady=(0,4))
        ttk.Label(frame,text='Uses the connected Habbo AIR / G-Earth session. '
                  'Turn AI off to stop replies; no extra send switch is needed.',
                  style='Panel.TLabel',wraplength=660).pack(
                      anchor='w',pady=(0,15))

        style_row=ttk.Frame(frame,style='Panel.TFrame')
        style_row.pack(fill='x',pady=(0,6))
        ttk.Label(style_row,text='CHAT PERSONA — SAVED ROOM LOGS',
                  style='Panel.TLabel').pack(side='left')
        ttk.Button(style_row,text='Use custom personality',
                   command=self._responder_use_custom_style).pack(side='right')
        search_row=ttk.Frame(frame,style='Panel.TFrame')
        search_row.pack(fill='x',pady=(0,4))
        self.responder_style_search_entry=ttk.Entry(
            search_row,textvariable=self.responder_style_search_var)
        self.responder_style_search_entry.pack(
            side='left',fill='x',expand=True,padx=(0,8))
        ttk.Button(search_row,text='Refresh names',
                   command=self._responder_refresh_style_users).pack(side='left')
        self._responder_suggestions_area=ttk.Frame(
            frame,style='Panel.TFrame')
        self._responder_suggestions_area.pack(fill='x')
        self.responder_style_matches_list=tk.Listbox(
            self._responder_suggestions_area,height=6,exportselection=False,
            selectmode='browse',font=('Segoe UI',10),
            bg=p['field'],fg=p['text'],
            selectbackground=p['accent'],selectforeground=p['background'],
            borderwidth=0,highlightthickness=1,relief='flat')
        self.responder_style_matches_list.bind(
            '<<ListboxSelect>>',self._responder_select_style_user)
        self.responder_style_search_entry.bind(
            '<KeyRelease>',self._responder_filter_style_users)
        self.responder_style_search_entry.bind(
            '<FocusIn>',lambda event:self._responder_filter_style_users())
        self.responder_style_search_entry.bind(
            '<Escape>',lambda event:self._responder_hide_style_matches())
        self.responder_style_search_entry.bind(
            '<Down>',self._responder_focus_style_matches)
        ttk.Label(frame,textvariable=self.responder_style_status_var,
                  style='Panel.TLabel',wraplength=650).pack(
                      anchor='w',pady=(3,12))

        # The custom box appears only after "Use custom personality".
        # It does not interfere with recreated chat personas.
        self._responder_custom_frame=ttk.Frame(frame,style='Panel.TFrame')
        ttk.Label(self._responder_custom_frame,
                  text='CUSTOM PERSONALITY',style='Panel.TLabel').pack(
                      anchor='w',pady=(0,5))
        self.responder_personality_entry=tk.Text(
            self._responder_custom_frame,height=4,wrap='word',
            font=('Segoe UI',10),bg=p['field'],fg=p['text'],
            insertbackground=p['text'],relief='flat')
        self.responder_personality_entry.pack(fill='x')
        self.responder_personality_entry.insert(
            '1.0',self.responder_personality_text)
        ttk.Label(self._responder_custom_frame,
                  text='Edit this freely. Saved personas never inherit it.',
                  style='Panel.TLabel',wraplength=630).pack(
                      anchor='w',pady=(3,9))

        self._responder_speed_area=ttk.Frame(frame,style='Panel.TFrame')
        self._responder_speed_area.pack(fill='x',pady=(0,14))
        title_row=ttk.Frame(self._responder_speed_area,style='Panel.TFrame')
        title_row.pack(fill='x',pady=(0,4))
        ttk.Label(title_row,text='REPLY SPEED',
                  style='Panel.TLabel').pack(side='left')
        ttk.Label(title_row,textvariable=self.responder_reply_interval_text,
                  style='Panel.TLabel').pack(side='right')
        self.responder_reply_interval_scale=ttk.Scale(
            self._responder_speed_area,from_=0,to=30,orient='horizontal',
            variable=self.responder_reply_interval_var,
            command=self._responder_reply_speed_changed)
        self.responder_reply_interval_scale.pack(fill='x',pady=(0,2))
        self.responder_reply_interval_scale.bind(
            '<ButtonRelease-1>',self._responder_commit_reply_speed)
        caption=ttk.Frame(self._responder_speed_area,style='Panel.TFrame')
        caption.pack(fill='x')
        ttk.Label(caption,text='Immediately (0s)',
                  style='Panel.TLabel').pack(side='left')
        ttk.Label(caption,text='30 seconds',
                  style='Panel.TLabel').pack(side='right')
        ttk.Label(self._responder_speed_area,
                  text='Minimum gap between AI replies, for BOTH saved and custom personas.',
                  style='Panel.TLabel',wraplength=650).pack(
                      anchor='w',pady=(4,0))

        ttk.Label(frame,text='REPLY TO — PEOPLE IN THIS ROOM',
                  style='Panel.TLabel').pack(anchor='w',pady=(0,6))
        all_row=ttk.Frame(frame,style='Panel.TFrame')
        all_row.pack(fill='x',pady=(0,6))
        self.responder_everyone_check=ttk.Checkbutton(
            all_row,text='Everyone (select all)',
            variable=self.responder_everyone_var,
            command=self._responder_toggle_everyone)
        self.responder_everyone_check.pack(side='left')
        ttk.Button(all_row,text='Refresh room',
                   command=self._responder_refresh_room_users).pack(
                       side='right')
        self.responder_target_search_entry=ttk.Entry(
            frame,textvariable=self.responder_target_search_var)
        self.responder_target_search_entry.pack(fill='x',pady=(0,6))
        self.responder_target_search_entry.bind(
            '<KeyRelease>',lambda event:self._responder_render_target_checklist())
        self._responder_targets_area=ttk.Frame(frame,style='Panel.TFrame')
        self._responder_targets_area.pack(fill='x')
        self._responder_target_checks_frame=ttk.Frame(
            self._responder_targets_area,style='Panel.TFrame')
        self._responder_target_checks_frame.pack(fill='x')
        ttk.Label(frame,textvariable=self.responder_room_status_var,
                  style='Panel.TLabel',wraplength=650).pack(
                      anchor='w',pady=(5,12))

        ttk.Label(frame,text='TEMPORARY INSTRUCTIONS',
                  style='Panel.TLabel').pack(anchor='w',pady=(0,5))
        ttk.Label(frame,text='One instruction per line; timed instructions expire.',
                  style='Panel.TLabel',wraplength=650).pack(
                      anchor='w',pady=(0,5))
        self.responder_instruction_input=tk.Text(
            frame,height=2,wrap='word',font=('Segoe UI',10),
            bg=p['field'],fg=p['text'],insertbackground=p['text'],relief='flat')
        self.responder_instruction_input.pack(fill='x',pady=(0,6))
        action_row=ttk.Frame(frame,style='Panel.TFrame')
        action_row.pack(fill='x',pady=(0,5))
        ttk.Button(action_row,text='Add instruction',
                   command=self._responder_add_instructions).pack(
                       side='left',padx=(0,7))
        ttk.Button(action_row,text='Remove selected',
                   command=self._responder_remove_instruction).pack(
                       side='left',padx=(0,7))
        ttk.Button(action_row,text='Clear all',
                   command=self._responder_clear_instructions).pack(side='left')
        self._responder_instruction_list_area=ttk.Frame(
            frame,style='Panel.TFrame')
        self._responder_instruction_list_area.pack(fill='x')
        self.responder_instruction_list=tk.Listbox(
            self._responder_instruction_list_area,
            height=3,exportselection=False,selectmode='browse',
            font=('Segoe UI',10),bg=p['field'],fg=p['text'],
            selectbackground=p['accent'],selectforeground=p['background'],
            borderwidth=0,highlightthickness=1,relief='flat')
        ttk.Label(frame,textvariable=self.responder_instruction_status_var,
                  style='Panel.TLabel',wraplength=650).pack(
                      anchor='w',pady=(4,5))
        ttk.Label(frame,text='Examples: be mean to Marc for 10mins, '
                  'type slow, pretend to go afk for 2mins.',
                  style='Panel.TLabel',wraplength=650).pack(
                      anchor='w',pady=(0,12))

        buttons=ttk.Frame(frame,style='Panel.TFrame')
        buttons.pack(fill='x',pady=(0,10))
        ttk.Button(buttons,text='Save changes',
                   command=self._responder_apply).pack(
                       side='left',padx=(0,8))
        ttk.Button(buttons,text='Stop AI',
                   command=self._responder_stop).pack(side='left')

        ttk.Label(frame,textvariable=self.responder_log_saving_var,
                  style='Panel.TLabel',wraplength=650).pack(
                      anchor='w',pady=(3,7))
        ttk.Label(frame,textvariable=self.responder_status_var,
                  style='Panel.TLabel',wraplength=650).pack(
                      anchor='w',pady=(0,9))
        ttk.Label(frame,text='RECENT ACTIVITY',
                  style='Panel.TLabel').pack(anchor='w')
        self.responder_log_text=tk.Text(
            frame,height=6,wrap='word',state='disabled',
            font=('Consolas',9),bg=p['field'],fg=p['text'],
            insertbackground=p['text'],relief='flat')
        self.responder_log_text.pack(fill='x',pady=(5,7))
        self._responder_update_style_controls()
        self._responder_refresh_style_users()
        self._responder_refresh_room_users()
        self._responder_update_logging_status()

    @staticmethod
    def _responder_reply_speed_label(seconds):
        interval=clamp_reply_interval(seconds)
        return ('Immediately (no added cooldown)' if interval==0
                else f'Minimum {interval} sec between replies')

    def _responder_reply_speed_changed(self,value):
        """Enable instant to 30-second pacing equally for all personas."""
        seconds=clamp_reply_interval(value)
        self.responder.reply_cooldown_seconds=seconds
        self.responder_reply_interval_text.set(
            self._responder_reply_speed_label(seconds))

    def _responder_commit_reply_speed(self,event=None):
        seconds=clamp_reply_interval(self.responder_reply_interval_var.get())
        self.responder_reply_interval_var.set(seconds)
        self._responder_reply_speed_changed(seconds)
        self.config['responder_reply_interval']=seconds
        self.save()

    def _responder_refresh_room_users(self):
        """Show current room roster; never offer stale historical chat usernames."""
        found={}
        own=str(getattr(self,'_own_name','') or '').casefold()
        for user in getattr(self,'_room_users',{}).values():
            if isinstance(user,(tuple,list)) and user:
                name=str(user[0]).strip()
                if name and name.casefold()!=own:
                    found[name.casefold()]=name
        for name,_stamp in getattr(self,'_responder_room_speakers',{}).values():
            if name and name.casefold()!=own:
                found.setdefault(name.casefold(),name)
        names=sorted(found.values(),key=str.casefold)
        previous=self._responder_room_names
        self._responder_room_names=names
        if names!=previous or not self.responder_room_status_var.get().startswith(
                (str(len(names))+' players detected.', 'No room players detected')):
            self._responder_render_target_checklist()

    def _responder_render_target_checklist(self):
        """Draw actual checkboxes in a compact grid (not an editable name list)."""
        for widget in self._responder_target_checks_frame.winfo_children():
            widget.destroy()
        self._responder_target_checkboxes={}
        all_selected=self.responder_everyone_var.get()
        selected=selected_usernames(self.responder_target_var.get())
        query=self.responder_target_search_var.get().strip().casefold()
        filtered=matching_style_usernames(self._responder_room_names,query,limit=80)
        for index,name in enumerate(filtered):
            var=tk.BooleanVar(
                value=all_selected or name.casefold() in selected)
            checkbox=ttk.Checkbutton(
                self._responder_target_checks_frame,text=name,variable=var,
                command=self._responder_target_selection_changed)
            checkbox.grid(row=index//3,column=index%3,sticky='w',
                          padx=(0,13),pady=(0,5))
            self._responder_target_checkboxes[name.casefold()]=(name,var)
        # Keep a selected user checked when the filter hides them: their
        # selection lives in responder_target_var, not the rendered widgets.
        found=len(self._responder_room_names)
        matched=len(filtered)
        if found:
            self.responder_room_status_var.set(
                f'{found} players detected. '+
                (f'Showing {matched} matches. ' if query else '')+
                'Tick individuals, or tick Everyone to include all.')
        else:
            self.responder_room_status_var.set(
                'No room players detected yet. Connect Habbo AIR and '
                'G-Earth, then select Refresh room.')

    def _responder_target_selection_changed(self):
        # Reconcile only VISIBLE checkboxes into the remembered selection.
        selected=(set(name.casefold() for name in self._responder_room_names)
                  if self.responder_everyone_var.get() else
                  selected_usernames(self.responder_target_var.get()))
        for key,(_name,var) in self._responder_target_checkboxes.items():
            if var.get():
                selected.add(key)
            else:
                selected.discard(key)
        if self.responder_everyone_var.get():
            self.responder_everyone_var.set(False)
        self.responder_target_mode_var.set('Selected users')
        display={name.casefold():name for name in self._responder_room_names}
        self.responder_target_var.set(
            ', '.join(display.get(key,key) for key in
                      sorted(selected,key=str.casefold)))
        self._responder_apply()

    def _responder_toggle_everyone(self):
        all_checked=self.responder_everyone_var.get()
        if all_checked:
            self.responder_target_mode_var.set('Everyone')
            self.responder_target_var.set(
                ', '.join(self._responder_room_names))
        else:
            # Unchecking Everyone starts a fresh explicit subset.
            self.responder_target_mode_var.set('Selected users')
            self.responder_target_var.set('')
        self._responder_render_target_checklist()
        self._responder_apply()

    def _responder_mode_display(self):
        return ('Chat persona simulation' if
                self.responder.style_mode=='Chat-log style' else
                self.responder.style_mode)

    def _responder_update_style_controls(self):
        copying=self.responder_style_mode_var.get()=='Chat-log style'
        if copying:
            self._responder_custom_frame.pack_forget()
            reference=self.responder.persona_reference()
            count=(reference or {}).get('evidence_messages_in_recent_log_window',0)
            note=(' Limited evidence—more messages will give better results.'
                  if count<60 else ' Based on observed public chat.')
            self.responder_style_status_var.set(
                f"Simulating {self.responder.persona}'s conversational persona "
                f"from {count} saved messages."+note)
        else:
            self.responder_personality_entry.configure(state='normal')
            if not self._responder_custom_frame.winfo_manager():
                self._responder_custom_frame.pack(
                    fill='x',before=self._responder_speed_area,pady=(0,6))
            self.responder_style_status_var.set(
                'Custom personality: edit your own description below, or '
                'search for a saved player to recreate their persona.')

    def _responder_style_directory(self):
        path=Path(self.responder_log_dir_var.get().strip() or
                  self._responder_default_logs).expanduser()
        if path.name.casefold()=='chat_logs' and (path/'users').is_dir():
            path=path/'users'
        return path

    def _responder_refresh_style_users(self):
        """Find logged users automatically; no folder selection needed."""
        archive=self._responder_app_dir/'persona_logs'/'users'
        candidates=(
            archive,
            self._responder_style_directory(),
            Path(__file__).resolve().parent/'chat_logs'/'users',
            self._responder_app_dir/'chat_logs'/'users',
            self._responder_default_logs,
        )
        seen=set()
        sources={}
        for folder in candidates:
            folder=Path(folder).expanduser()
            if folder in seen:
                continue
            seen.add(folder)
            for name in list_style_usernames(folder):
                sources.setdefault(name.casefold(),(name,folder))
        self._responder_style_sources={
            key:folder for key,(_name,folder) in sources.items()}
        self._responder_style_users=sorted(
            (name for name,_folder in sources.values()),key=str.casefold)
        self._responder_filter_style_users(show=False)
        if not self._responder_style_users:
            self.responder_style_status_var.set(
                'No recorded users yet. Keep Habbo AIR running and public '
                'room chat will be saved automatically.')
        else:
            self._responder_update_style_controls()

    def _responder_filter_style_users(self,event=None,show=True):
        """Display a dropdown-like list of case-insensitive partial matches."""
        if event is not None and event.keysym in (
            'Up','Down','Return','Escape','Tab','Left','Right'):
            return
        query=self.responder_style_search_var.get()
        names=matching_style_usernames(self._responder_style_users,query,limit=80)
        self._responder_style_matches=names
        box=self.responder_style_matches_list
        box.delete(0,'end')
        for name in names:
            box.insert('end',name)
        if names and show:
            box.configure(height=min(7,len(names)))
            if not box.winfo_manager():
                box.pack(fill='x',pady=(0,5))
        else:
            self._responder_hide_style_matches()

    def _responder_hide_style_matches(self):
        self.responder_style_matches_list.pack_forget()

    def _responder_focus_style_matches(self,event=None):
        if self._responder_style_matches:
            self.responder_style_matches_list.focus_set()
            self.responder_style_matches_list.selection_set(0)
            self.responder_style_matches_list.activate(0)
        return 'break'

    def _responder_select_style_user(self,event=None):
        """Switch to a selected real log file, never an unverified typed name."""
        selected=self.responder_style_matches_list.curselection()
        if not selected:
            return
        name=self.responder_style_matches_list.get(selected[0])
        self.responder_style_matches_list.selection_clear(0,'end')
        if name not in self._responder_style_users:
            return
        directory=self._responder_style_sources.get(
            name.casefold(),self._responder_style_directory())
        profile=PersonaResponder(directory)
        profile.persona=name
        reference=profile.persona_reference()
        self._responder_hide_style_matches()
        if not reference:
            self.responder_style_status_var.set(
                'No usable messages found for '+name+'. Select another user.')
            return
        self.responder_style_search_var.set(name)
        self.responder_log_dir_var.set(str(directory))
        self.responder_persona_var.set(name)
        self.responder_style_mode_var.set('Chat-log style')
        # Selecting a specific user must not rotate away to someone else.
        self.responder_rotation_var.set(False)
        self._responder_apply()
        # Apply the widget states after the model/config change as well; this
        # ensures no save-time UI redraw restores generic settings.
        self._responder_update_style_controls()
        sample_count=reference['evidence_messages_in_recent_log_window']
        confidence=('Limited evidence; gather more messages for a closer match.'
                    if sample_count<60 else
                    'Behaviour based on saved public messages.')
        self.responder_style_status_var.set(
            f"Simulating {name}'s chat persona using {sample_count} logged "
            f"messages. {confidence}")
        self._responder_log(
            f'Chat persona set to {name}: {sample_count} messages examined; '
            'using their observed conversation habits, humour and reactions.')

    def _responder_use_custom_style(self):
        self.responder_style_mode_var.set('Custom personality')
        self._responder_hide_style_matches()
        self._responder_update_style_controls()
        self._responder_apply()

    def _responder_instruction_changed(self):
        """Invalidate any in-flight or scheduled chat using outdated rules."""
        self._responder_generation+=1
        self.responder.running=False
        self._responder_scheduled_send=None
        self.responder.pending.clear()
        self.responder.pending_since=None
        self.responder.has_trigger=False

    def _responder_add_instructions(self):
        lines=self.responder_instruction_input.get('1.0','end-1c').splitlines()
        added=[]
        errors=[]
        for line in lines:
            if not line.strip():
                continue
            try:
                added.append(self.responder.add_temporary_instruction(line))
            except ValueError as exc:
                errors.append(str(exc))
        if added:
            self._responder_instruction_changed()
            self.responder_instruction_input.delete('1.0','end')
            for rule in added:
                self._responder_log('Temporary instruction added: '+rule['label'])
            if any(rule['kind']=='afk' for rule in added):
                self._responder_log(
                    'AFK active: live AI drafts and outgoing messages paused.')
        if errors:
            self.responder_instruction_status_var.set('; '.join(errors)[:230])
            self._responder_log('Instruction error: '+'; '.join(errors)[:200])
        self._responder_refresh_instructions(force=bool(added))

    def _responder_remove_instruction(self):
        selection=self.responder_instruction_list.curselection()
        if not selection or selection[0]>=len(self._responder_instruction_rows):
            self.responder_instruction_status_var.set(
                'Select an active instruction to remove.')
            return
        rule_id=self._responder_instruction_rows[selection[0]]
        if self.responder.remove_temporary_instruction(rule_id):
            self._responder_instruction_changed()
            self._responder_log('Temporary instruction removed.')
        self._responder_refresh_instructions(force=True)

    def _responder_clear_instructions(self):
        if self.responder.temporary_instructions:
            self.responder.temporary_instructions.clear()
            self._responder_instruction_changed()
            self._responder_log('All temporary instructions cleared.')
        self._responder_refresh_instructions(force=True)

    def _responder_refresh_instructions(self,force=False):
        rules=self.responder.active_temporary_instructions()
        now=time.monotonic()
        labels=[]
        for rule in rules:
            expiry=rule['expires_at']
            if expiry is None:
                suffix='until removed'
            else:
                remaining=max(0,int(expiry-now+0.999))
                suffix=(f'{remaining//60}m {remaining%60:02d}s'
                        if remaining>=60 else f'{remaining}s')
            labels.append(f"{rule['label']}  •  {suffix}")
        view=tuple((rule['id'],label) for rule,label in zip(rules,labels))
        if not force and view==self._responder_instruction_display:
            return
        self._responder_instruction_display=view
        box=self.responder_instruction_list
        selected=box.curselection()
        old_selected=(self._responder_instruction_rows[selected[0]]
                      if selected and selected[0]<len(self._responder_instruction_rows)
                      else None)
        self._responder_instruction_rows=[rule['id'] for rule in rules]
        box.delete(0,'end')
        for label in labels:
            box.insert('end',label)
        if labels:
            box.configure(height=min(4,len(labels)))
            if not box.winfo_manager():
                box.pack(fill='x',pady=(2,5))
            if old_selected in self._responder_instruction_rows:
                box.selection_set(self._responder_instruction_rows.index(
                    old_selected))
        else:
            box.pack_forget()
        if rules:
            self.responder_instruction_status_var.set(
                f"{len(rules)} active instruction(s). "
                "Expired instructions disappear automatically.")
        else:
            self.responder_instruction_status_var.set(
                'No temporary instructions active.')

    def _responder_update_logging_status(self):
        if not hasattr(self,'responder_log_saving_var'):
            return
        self.responder.save_history=True
        if self.responder.log_error:
            self.responder_log_saving_var.set(self.responder.log_error)
        else:
            self.responder_log_saving_var.set(
                'Public room chat automatically saved: '+
                str(self.responder.logged_messages)+
                ' messages this session (even with AI OFF).')

    def _responder_log(self,detail):
        if not hasattr(self,'responder_log_text'):
            return
        widget=self.responder_log_text
        widget.configure(state='normal')
        widget.insert('end',time.strftime('%H:%M:%S')+'  '+detail[:400]+'\n')
        if int(widget.index('end-1c').split('.')[0])>250:
            widget.delete('1.0','25.0')
        widget.see('end')
        widget.configure(state='disabled')

    def _responder_read_personality(self):
        """Keep custom description separate from a recreated logged persona."""
        self.responder.style_mode=self.responder_style_mode_var.get()
        custom=self.responder_personality_entry.get('1.0','end-1c').strip()
        if custom:
            self.responder.personality=custom[:1500]
        self.responder.persona=(
            self.responder_persona_var.get().strip()[:80] or 'Mario35')
        self.responder.auto_rotate=False
        # Recording public chat is always on, independent of AI status.
        self.responder.save_history=True
        self.responder.log_dir=self._responder_style_directory()

    def _responder_apply(self):
        self._responder_generation+=1
        self._responder_scheduled_send=None
        self.responder.running=False
        self._responder_test_running=False
        self._responder_read_personality()
        self._responder_commit_reply_speed()
        self.responder.fixed_target=''
        self.responder.target_mode=self.responder_target_mode_var.get()
        self.responder.selected_users=self.responder_target_var.get().strip()
        self.responder.reset_room()
        valid_selection=(self.responder.target_mode!='Selected users'
                         or bool(selected_usernames(self.responder.selected_users)))
        self.responder.enabled=(
            bool(self.responder_enabled_var.get()) and valid_selection)
        # Enabling the responder means replying through G-Earth—no separate
        # auto-send switch that could silently leave it in preview mode.
        self.responder_send_var.set(self.responder.enabled)
        if not valid_selection:
            self.responder_enabled_var.set(False)
            self.responder_status_var.set(
                'Tick at least one room player, or choose Everyone.')
        self.config.update(
            responder_persona=self.responder.persona,
            responder_style_mode=self.responder.style_mode,
            responder_personality=self.responder.personality,
            responder_target_mode=self.responder.target_mode,
            responder_targets=self.responder.selected_users,
            responder_target='',
            responder_rotation=False,
            responder_capture=True,
            background_public_chat_logging=True,
            responder_log_dir=str(self.responder.log_dir),
            responder_reply_interval=self.responder.reply_cooldown_seconds,
        )
        self.save()
        if valid_selection:
            state='ON' if self.responder.enabled else 'OFF'
            self.responder_status_var.set(
                f'AI {state} | {self._responder_mode_display()} | '+
                ('Everyone in room' if self.responder.target_mode=='Everyone'
                 else self.responder.selected_users))
        self._responder_log('Settings applied. AI '+(
            'ON (sending through G-Earth)' if self.responder.enabled
            else 'OFF')+'.')
        self._responder_update_logging_status()

    def _responder_test_reply(self):
        """Test current unsaved personality settings with no game send side effects."""
        if self._responder_test_running:
            self.responder_status_var.set('A preview request is already running.')
            return
        self._responder_read_personality()
        payload=self.responder.test_payload(
            self.responder_test_user_var.get(),self.responder_test_message_var.get())
        if 'error' in payload:
            self.responder_status_var.set(payload['error'])
            return
        self._responder_test_running=True
        model=self.responder_model_var.get().strip() or 'gpt-5-mini'
        self.responder_status_var.set('Generating test preview. No Habbo send will occur.')
        self._responder_log('TEST input: '+payload['target']+': '+
                            payload['new_messages'][0]['message'])
        threading.Thread(target=self._responder_worker,
                         args=(payload,model,self._responder_generation,True),
                         daemon=True).start()

    def _responder_check_capture(self):
        """Explain the live Chat capture status without sending any packets."""
        if not self.packet_started or not self._habbo_session_connected:
            result=('G-Earth game session is not connected. '
                    'Connect Habbo AIR through Packet Viewer first.')
        elif self._responder_chat_template is not None:
            result='READY: the outgoing Chat format was learned from G-Earth.'
        elif self._responder_outgoing_seen:
            result=('G-Earth is observing outgoing packets, but has not '
                    'identified a named public Chat packet. Send an ordinary '
                    'public message, then check Packet Viewer / G-Earth packet '
                    'names if it still fails.')
        else:
            result=('G-Earth is connected, but no outgoing packet has been '
                    'observed while AI was enabled. Type a normal public '
                    'message into Habbo AIR.')
        self.responder_status_var.set(result)
        self._responder_log(result)

    def _responder_stop(self):
        self.responder_enabled_var.set(False)
        self.responder_send_var.set(False)
        self._responder_apply()

    def _responder_send(self,reply):
        if (not self.packet_started or not self._habbo_session_connected
            or self.packet_extension is None):
            return 'Not sent: connect Habbo through G-Earth first.'
        expr=chat_expression_from_template(self._responder_chat_template,reply)
        if expr is None:
            if self._responder_outgoing_seen:
                return ('Not sent: outgoing packets were seen, but G-Earth '
                        'did not identify the public Chat packet. '
                        'Check G-Earth packet names or click Check G-Earth chat capture.')
            return 'Not sent: type one normal public Habbo chat line to learn its format.'
        try:
            ext=self.packet_extension
            packet=ext.string_to_packet(expr)
            if packet is None or packet.is_incomplete_packet() or packet.is_corrupted():
                raise ValueError('G-Earth could not decode the observed Chat packet.')
            if ext.send_to_server(packet) is False:
                raise ValueError('G-Earth rejected the packet.')
            return 'Send requested through connected G-Earth session.'
        except Exception as exc:
            return 'Not sent: '+str(exc)[:160]

    def _responder_send_latest(self):
        if not self._responder_last_draft:
            self.responder_status_var.set('No draft yet. Enable AI to generate from new chat.')
            return
        outcome=self._responder_send(self._responder_last_draft)
        self.responder_status_var.set(outcome)
        self._responder_log(outcome)

    def _responder_worker(self,payload,model,generation,test=False):
        try:
            reply=generate_persona_reply(payload,model=model)
            self._responder_results.put((generation,reply,None,test))
        except Exception as exc:
            self._responder_results.put((generation,None,str(exc)[:200],test))

    def _responder_tick(self):
        now=time.monotonic()
        if now-self._responder_last_room_refresh>=2.0:
            self._responder_last_room_refresh=now
            self._responder_refresh_room_users()
        self._responder_refresh_instructions()
        if self.responder.is_temporarily_afk() and self._responder_scheduled_send:
            self._responder_scheduled_send=None
            self._responder_log('Delayed AI send cancelled because AFK is active.')
        for _ in range(6):
            try:
                generation,reply,error,test=self._responder_results.get_nowait()
            except queue.Empty:
                break
            if generation!=self._responder_generation:
                continue
            if test:
                self._responder_test_running=False
                if error:
                    self.responder_status_var.set('Test error: '+error)
                    self._responder_log('TEST ERROR '+error)
                else:
                    text=reply or '(AI returned SKIP)'
                    self.responder_status_var.set('Test preview complete. Nothing was sent.')
                    self._responder_log('TEST PREVIEW '+text)
                continue
            self.responder.running=False
            if not self.responder.enabled or self.responder.is_temporarily_afk():
                continue
            if error:
                self.responder_status_var.set('AI error: '+error)
                self._responder_log('ERROR '+error)
            elif not reply:
                self.responder_status_var.set('SKIP — no natural reply needed.')
                self._responder_log('SKIP')
            elif self.responder.is_repeated_question(reply):
                self._responder_log('SKIP repeated question: '+reply)
            else:
                self.responder.remember_reply(reply)
                self._responder_last_draft=reply
                self._responder_log('LIVE DRAFT '+reply)
                if self.responder_send_var.get():
                    delay=self.responder.temporary_send_delay()
                    if delay:
                        self._responder_scheduled_send=(
                            time.monotonic()+delay,reply,generation)
                        self.responder_status_var.set(
                            f'Slow typing active: sending after {int(delay)}s '
                            '(one full G-Earth chat packet).')
                        self._responder_log(
                            f'Slow-send scheduled: {int(delay)} second delay.')
                    else:
                        outcome=self._responder_send(reply)
                        self.responder_status_var.set(outcome)
                        self._responder_log(outcome)
                else:
                    self.responder_status_var.set('Live draft ready (preview mode).')
        if self._responder_scheduled_send:
            due,reply,generation=self._responder_scheduled_send
            if time.monotonic()>=due:
                self._responder_scheduled_send=None
                if (generation==self._responder_generation and
                        self.responder.enabled and
                        self.responder_send_var.get() and
                        not self.responder.is_temporarily_afk()):
                    outcome=self._responder_send(reply)
                    self.responder_status_var.set(outcome)
                    self._responder_log(outcome)
            else:
                # Prevent overlapping requests from stacking multiple sends.
                return
        if not self.responder.enabled or self.responder.is_temporarily_afk():
            return
        payload=self.responder.pop_ready()
        if not payload:
            return
        if 'error' in payload:
            self.responder_status_var.set(payload['error'])
            return
        generation=self._responder_generation
        model=self.responder_model_var.get().strip() or 'gpt-5-mini'
        self._responder_log('Live decision for '+payload['target']+
                            ' | '+('Chat persona simulation' if
                                   payload['style_mode']=='Chat-log style'
                                   else payload['style_mode']))
        threading.Thread(target=self._responder_worker,
                         args=(payload,model,generation,False),daemon=True).start()
