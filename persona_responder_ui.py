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
)


class PersonaResponderMixin:
    def _responder_setup(self):
        legacy=Path(__file__).resolve().parent/'chat_logs'/'users'
        default_logs=legacy if legacy.is_dir() else self._responder_app_dir/'persona_logs'/'users'
        chosen=str(self.config.get('responder_log_dir','')).strip()
        self._responder_default_logs=default_logs
        self.responder=PersonaResponder(chosen or default_logs)
        self.responder.persona=str(self.config.get('responder_persona','Mario35'))
        self.responder.auto_rotate=bool(self.config.get('responder_rotation',False))
        self.responder.save_history=bool(self.config.get('responder_capture',False))
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
        # On upgrade, preserve an older single-user target instead of silently
        # switching a previously targeted bot to Everyone.
        if previous_target and not self.config.get('responder_targets'):
            current_mode='Selected users'
        self.responder.target_mode=current_mode
        self.responder.fixed_target=''
        self.responder_enabled_var=tk.BooleanVar(value=False)
        self.responder_send_var=tk.BooleanVar(value=False)
        self.responder_rotation_var=tk.BooleanVar(value=self.responder.auto_rotate)
        self.responder_capture_var=tk.BooleanVar(value=self.responder.save_history)
        self.responder_persona_var=tk.StringVar(value=self.responder.persona)
        self.responder_style_mode_var=tk.StringVar(value=self.responder.style_mode)
        self.responder_personality_text=self.responder.personality
        self.responder_tone_var=tk.StringVar(value=self.responder.tone)
        self.responder_humour_var=tk.StringVar(value=str(self.responder.humour))
        self.responder_responsiveness_var=tk.StringVar(
            value=self.responder.responsiveness)
        self.responder_target_mode_var=tk.StringVar(value=self.responder.target_mode)
        self.responder_target_var=tk.StringVar(value=self.responder.selected_users)
        self.responder_log_dir_var=tk.StringVar(value=str(self.responder.log_dir))
        self.responder_model_var=tk.StringVar(value=str(
            self.config.get('responder_model','gpt-5-mini')))
        self.responder_test_user_var=tk.StringVar(value='TestUser')
        self.responder_test_message_var=tk.StringVar(value='hey, what are you up to?')
        self.responder_status_var=tk.StringVar(
            value='OFF. Define your own personality and use Test AI reply below.')
        self._responder_results=queue.Queue()
        self._responder_generation=0
        self._responder_chat_template=None
        self._responder_outgoing_seen=False
        self._responder_last_draft=None
        self._responder_test_running=False
        self._responder_advanced_open=False

    def _make_responder_panel(self,parent):
        """Keep everyday controls on one page; tuck optional controls away."""
        p=self._responder_palette
        frame=ttk.Frame(parent,style='Panel.TFrame',padding=(18,16))
        frame.pack(fill='both',expand=True)

        tk.Label(frame,text='AI RESPONDER',font=('Segoe UI Semibold',18),
                 bg=p['background'],fg=p['text']).pack(anchor='w')
        ttk.Label(frame,text='Choose how it talks and who it responds to.',
                  style='Panel.TLabel').pack(anchor='w',pady=(3,12))

        switches=ttk.Frame(frame,style='Panel.TFrame')
        switches.pack(fill='x',pady=(0,12))
        ttk.Checkbutton(switches,text='Enable AI responder',
                        variable=self.responder_enabled_var,
                        command=self._responder_apply).pack(anchor='w',pady=(0,5))
        ttk.Checkbutton(switches,text='Send replies in Habbo (G-Earth)',
                        variable=self.responder_send_var).pack(anchor='w')
        ttk.Label(switches,text='Turn off sending to preview live replies without posting.',
                  style='Panel.TLabel',wraplength=600).pack(anchor='w',pady=(4,0))

        ttk.Label(frame,text='PERSONALITY',style='Panel.TLabel').pack(
            anchor='w',pady=(0,5))
        self._responder_custom_frame=ttk.Frame(frame,style='Panel.TFrame')
        self._responder_custom_frame.pack(fill='x')
        self.responder_personality_entry=tk.Text(
            self._responder_custom_frame,height=4,wrap='word',
            font=('Segoe UI',10),bg=p['field'],fg=p['text'],
            insertbackground=p['text'],relief='flat')
        self.responder_personality_entry.pack(fill='x')
        self.responder_personality_entry.insert('1.0',self.responder_personality_text)
        ttk.Label(frame,text='Describe its tone, humour and behaviour in plain language.',
                  style='Panel.TLabel',wraplength=600).pack(anchor='w',pady=(4,12))

        audience=ttk.Frame(frame,style='Panel.TFrame')
        audience.pack(fill='x',pady=(0,4))
        ttk.Label(audience,text='REPLY TO',style='Panel.TLabel').pack(
            side='left',padx=(0,12))
        self.responder_target_selector=ttk.Combobox(
            audience,textvariable=self.responder_target_mode_var,
            values=('Everyone','Selected users','First active speaker'),
            state='readonly',width=22)
        self.responder_target_selector.pack(side='left')
        self.responder_target_selector.bind(
            '<<ComboboxSelected>>',lambda event:self._responder_update_target_controls())
        self._responder_targets_frame=ttk.Frame(frame,style='Panel.TFrame')
        ttk.Label(self._responder_targets_frame,
                  text='Usernames (separate with commas)',style='Panel.TLabel').pack(
                      anchor='w',pady=(3,4))
        self.responder_target_entry=ttk.Entry(
            self._responder_targets_frame,textvariable=self.responder_target_var)
        self.responder_target_entry.pack(fill='x')
        self._responder_update_target_controls()

        actions=ttk.Frame(frame,style='Panel.TFrame')
        actions.pack(fill='x',pady=(12,13))
        ttk.Button(actions,text='Save changes',
                   command=self._responder_apply).pack(side='left',padx=(0,8))
        ttk.Button(actions,text='Stop',
                   command=self._responder_stop).pack(side='left')

        ttk.Label(frame,text='TRY A REPLY (PREVIEW ONLY)',
                  style='Panel.TLabel').pack(anchor='w',pady=(0,5))
        preview=ttk.Frame(frame,style='Panel.TFrame')
        preview.pack(fill='x',pady=(0,10))
        ttk.Entry(preview,textvariable=self.responder_test_message_var).pack(
            side='left',fill='x',expand=True,padx=(0,8))
        ttk.Button(preview,text='Test reply',
                   command=self._responder_test_reply).pack(side='left')
        ttk.Label(frame,text='Tests never send to Habbo, even when live sending is enabled.',
                  style='Panel.TLabel',wraplength=600).pack(anchor='w',pady=(0,12))

        self._responder_advanced_button=ttk.Button(
            frame,text='Advanced options ▸',command=self._responder_toggle_advanced)
        self._responder_advanced_button.pack(anchor='w',pady=(0,5))
        self._responder_advanced_area=ttk.Frame(frame,style='Panel.TFrame')
        self._responder_advanced_area.pack(fill='x')
        self._responder_advanced_frame=ttk.Frame(
            self._responder_advanced_area,style='Panel.TFrame',padding=(10,8))

        row=ttk.Frame(self._responder_advanced_frame,style='Panel.TFrame')
        row.pack(fill='x',pady=(0,8))
        ttk.Label(row,text='Reply frequency',style='Panel.TLabel').pack(
            side='left',padx=(0,8))
        ttk.Combobox(row,textvariable=self.responder_responsiveness_var,
                     values=('Natural','Chatty'),state='readonly',
                     width=13).pack(side='left',padx=(0,16))
        ttk.Label(row,text='Model',style='Panel.TLabel').pack(
            side='left',padx=(0,8))
        ttk.Entry(row,textvariable=self.responder_model_var,width=17).pack(side='left')

        row=ttk.Frame(self._responder_advanced_frame,style='Panel.TFrame')
        row.pack(fill='x',pady=(0,8))
        ttk.Label(row,text='Tone',style='Panel.TLabel').pack(side='left',padx=(0,8))
        ttk.Combobox(row,textvariable=self.responder_tone_var,state='readonly',
                     values=('Casual','Friendly','Playful','Dry','Sarcastic','Serious'),
                     width=15).pack(side='left',padx=(0,15))
        ttk.Label(row,text='Humour',style='Panel.TLabel').pack(
            side='left',padx=(0,8))
        ttk.Combobox(row,textvariable=self.responder_humour_var,
                     state='readonly',values=('0','1','2','3','4','5'),
                     width=5).pack(side='left')

        row=ttk.Frame(self._responder_advanced_frame,style='Panel.TFrame')
        row.pack(fill='x',pady=(0,7))
        ttk.Label(row,text='Style source',style='Panel.TLabel').pack(
            side='left',padx=(0,9))
        mode=ttk.Combobox(row,textvariable=self.responder_style_mode_var,
                          values=('Custom personality','Chat-log style'),
                          state='readonly',width=21)
        mode.pack(side='left')
        mode.bind('<<ComboboxSelected>>',
                  lambda event:self._responder_update_style_controls())

        self._responder_logs_frame=ttk.Frame(
            self._responder_advanced_frame,style='Panel.TFrame')
        ttk.Label(self._responder_logs_frame,text='Chat-log source username',
                  style='Panel.TLabel').pack(anchor='w',pady=(5,4))
        ttk.Entry(self._responder_logs_frame,
                  textvariable=self.responder_persona_var).pack(fill='x',pady=(0,5))
        ttk.Checkbutton(self._responder_logs_frame,
                        text='Rotate logged style every 5 minutes',
                        variable=self.responder_rotation_var).pack(anchor='w',pady=3)
        ttk.Checkbutton(self._responder_logs_frame,
                        text='Capture new public chat into local style logs',
                        variable=self.responder_capture_var).pack(anchor='w',pady=3)
        dir_row=ttk.Frame(self._responder_logs_frame,style='Panel.TFrame')
        dir_row.pack(fill='x',pady=(4,6))
        ttk.Entry(dir_row,textvariable=self.responder_log_dir_var).pack(
            side='left',fill='x',expand=True)
        ttk.Button(dir_row,text='Browse logs',command=self._responder_browse).pack(
            side='left',padx=(6,0))
        self._responder_update_style_controls()

        row=ttk.Frame(self._responder_advanced_frame,style='Panel.TFrame')
        row.pack(fill='x',pady=(8,7))
        ttk.Label(row,text='Preview as username',style='Panel.TLabel').pack(
            side='left',padx=(0,8))
        ttk.Entry(row,textvariable=self.responder_test_user_var,width=20).pack(
            side='left')
        row=ttk.Frame(self._responder_advanced_frame,style='Panel.TFrame')
        row.pack(fill='x',pady=(3,6))
        ttk.Button(row,text='Check G-Earth chat capture',
                   command=self._responder_check_capture).pack(
                       side='left',padx=(0,8))
        ttk.Button(row,text='Send latest live draft manually',
                   command=self._responder_send_latest).pack(side='left')
        ttk.Label(self._responder_advanced_frame,
                  text='To send live replies, connect Habbo AIR through G-Earth and '
                  'send one ordinary public chat message to learn its packet format. '
                  'An OpenAI API key must already be configured.',
                  style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(4,7))

        ttk.Label(frame,textvariable=self.responder_status_var,
                  style='Panel.TLabel',wraplength=650).pack(anchor='w',pady=(5,9))
        ttk.Label(frame,text='RECENT ACTIVITY',
                  style='Panel.TLabel').pack(anchor='w')
        self.responder_log_text=tk.Text(frame,height=7,wrap='word',state='disabled',
            font=('Consolas',9),bg=p['field'],fg=p['text'],
            insertbackground=p['text'],relief='flat')
        self.responder_log_text.pack(fill='both',expand=True,pady=(5,7))

    def _responder_toggle_advanced(self):
        self._responder_advanced_open=not self._responder_advanced_open
        if self._responder_advanced_open:
            self._responder_advanced_frame.pack(fill='x')
            self._responder_advanced_button.configure(text='Advanced options ▾')
        else:
            self._responder_advanced_frame.pack_forget()
            self._responder_advanced_button.configure(text='Advanced options ▸')

    def _responder_update_target_controls(self):
        if self.responder_target_mode_var.get()=='Selected users':
            self._responder_targets_frame.pack(fill='x',pady=(0,3))
        else:
            self._responder_targets_frame.pack_forget()

    def _responder_update_style_controls(self):
        if self.responder_style_mode_var.get()=='Chat-log style':
            self._responder_logs_frame.pack(fill='x',pady=(4,7))
        else:
            self._responder_logs_frame.pack_forget()

    def _responder_browse(self):
        folder=filedialog.askdirectory(
            title='Choose chat_logs/users or another style folder',
            initialdir=self.responder_log_dir_var.get())
        if folder:
            self.responder_log_dir_var.set(folder)

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
        """Synchronize custom settings without automatically enabling the bot."""
        self.responder.style_mode=self.responder_style_mode_var.get()
        self.responder.personality=self.responder_personality_entry.get(
            '1.0','end-1c').strip()[:1500] or self.responder.personality
        self.responder.tone=self.responder_tone_var.get()
        self.responder.humour=int(self.responder_humour_var.get())
        self.responder.responsiveness=self.responder_responsiveness_var.get()
        self.responder.persona=self.responder_persona_var.get().strip()[:80] or 'Mario35'
        self.responder.auto_rotate=bool(self.responder_rotation_var.get())
        self.responder.save_history=bool(self.responder_capture_var.get()) if (
            self.responder.style_mode=='Chat-log style') else False
        self.responder.log_dir=Path(
            self.responder_log_dir_var.get().strip() or self._responder_default_logs)

    def _responder_apply(self):
        self._responder_generation+=1
        self.responder.running=False
        self._responder_test_running=False
        self._responder_read_personality()
        self.responder.fixed_target=''
        self.responder.target_mode=self.responder_target_mode_var.get()
        self.responder.selected_users=self.responder_target_var.get().strip()
        self.responder.reset_room()
        valid_selection=(self.responder.target_mode!='Selected users'
                         or bool(self.responder.selected_users.strip(' ,\n\t')))
        self.responder.enabled=bool(self.responder_enabled_var.get()) and valid_selection
        if not valid_selection:
            self.responder_enabled_var.set(False)
            self.responder_status_var.set(
                'Select at least one username before enabling Selected users mode.')
        self.config.update(
            responder_persona=self.responder.persona,
            responder_style_mode=self.responder.style_mode,
            responder_personality=self.responder.personality,
            responder_tone=self.responder.tone,
            responder_humour=self.responder.humour,
            responder_responsiveness=self.responder.responsiveness,
            responder_target_mode=self.responder.target_mode,
            responder_targets=self.responder.selected_users,
            responder_target='',  # clear old single-target configuration
            responder_rotation=self.responder.auto_rotate,
            responder_capture=self.responder.save_history,
            responder_log_dir=str(self.responder.log_dir),
            responder_model=self.responder_model_var.get().strip() or 'gpt-5-mini',
        )
        self.save()
        if valid_selection:
            state='ON' if self.responder.enabled else 'OFF'
            self.responder_status_var.set(
                f'AI {state} | {self.responder.style_mode} | '
                f'{self.responder.target_mode}: '
                f'{self.responder.selected_users if self.responder.target_mode=="Selected users" else "active room"}')
        self._responder_log('Settings applied. AI '+(
            'ON' if self.responder.enabled else 'OFF')+'.')

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
                # Test replies are never remembered or sent, regardless
                # of Auto-send or the active live-room status.
                continue
            self.responder.running=False
            if not self.responder.enabled:
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
                    outcome=self._responder_send(reply)
                    self.responder_status_var.set(outcome)
                    self._responder_log(outcome)
                else:
                    self.responder_status_var.set('Live draft ready (preview mode).')
        if not self.responder.enabled:
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
                            ' | '+payload['style_mode'])
        threading.Thread(target=self._responder_worker,
                         args=(payload,model,generation,False),daemon=True).start()
