# -*- coding: utf-8 -*-
"""Tkinter integration for the opt-in Companion AI responder.

Used as a mixin so that the large legacy app keeps its existing features.
"""
from __future__ import annotations

from pathlib import Path
import queue
import secrets
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog

from persona_responder import (
    PersonaResponder, chat_expression_from_template, generate_persona_reply,
    replacement_chat_frame,
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
        self._responder_wire_template=None
        self._responder_probe_token=None
        self._responder_probe_started=0.0
        self._responder_probe_phrase_var=tk.StringVar(value='')
        self._responder_outgoing_seen=False
        self._responder_last_draft=None
        self._responder_test_running=False

    def _make_responder_panel(self,parent):
        p=self._responder_palette
        frame=ttk.Frame(parent,style='Panel.TFrame',padding=(18,16))
        frame.pack(fill='both',expand=True)
        tk.Label(frame,text='AI RESPONDER',font=('Segoe UI Semibold',18),
                 bg=p['background'],fg=p['text']).pack(anchor='w')
        ttk.Label(frame,text='Your own personality, live Habbo AIR chat, '
                  'and targeted replies. No chat-history imitation required.',
                  style='Panel.TLabel',wraplength=650).pack(anchor='w',pady=(3,12))
        ttk.Checkbutton(frame,text='Enable AI for new public room messages',
                        variable=self.responder_enabled_var,
                        command=self._responder_apply).pack(anchor='w',pady=(1,5))
        ttk.Checkbutton(frame,text='Auto-send through G-Earth (OFF by default)',
                        variable=self.responder_send_var).pack(anchor='w',pady=(0,9))
        tabs=ttk.Notebook(frame)
        tabs.pack(fill='x',pady=(2,9))
        personality_tab=ttk.Frame(tabs,style='Panel.TFrame',padding=12)
        targets_tab=ttk.Frame(tabs,style='Panel.TFrame',padding=12)
        test_tab=ttk.Frame(tabs,style='Panel.TFrame',padding=12)
        tabs.add(personality_tab,text='  Personality  ')
        tabs.add(targets_tab,text='  Who to reply to  ')
        tabs.add(test_tab,text='  Test without sending  ')
        self.responder_tabs=tabs

        choose=ttk.Frame(personality_tab,style='Panel.TFrame')
        choose.pack(fill='x',pady=(0,8))
        ttk.Label(choose,text='Personality source',style='Panel.TLabel').pack(
            side='left',padx=(0,9))
        mode=ttk.Combobox(choose,textvariable=self.responder_style_mode_var,
                          values=('Custom personality','Chat-log style'),
                          state='readonly',width=24)
        mode.pack(side='left')
        mode.bind('<<ComboboxSelected>>',
                  lambda event:self._responder_update_style_controls())

        self._responder_custom_frame=ttk.Frame(personality_tab,style='Panel.TFrame')
        ttk.Label(self._responder_custom_frame,
                  text='Describe how the bot should behave and speak',
                  style='Panel.TLabel').pack(anchor='w',pady=(2,3))
        self.responder_personality_entry=tk.Text(
            self._responder_custom_frame,height=5,wrap='word',
            font=('Segoe UI',10),bg=p['field'],fg=p['text'],
            insertbackground=p['text'],relief='flat')
        self.responder_personality_entry.pack(fill='x',pady=(0,5))
        self.responder_personality_entry.insert('1.0',self.responder_personality_text)
        ttk.Label(self._responder_custom_frame,
            text='Example: A laid-back gamer who jokes often, never sounds robotic, '
                 'and usually uses lowercase short replies.',
            style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,6))

        tone_row=ttk.Frame(personality_tab,style='Panel.TFrame')
        tone_row.pack(fill='x',pady=4)
        ttk.Label(tone_row,text='Tone',style='Panel.TLabel').pack(side='left',padx=(0,7))
        ttk.Combobox(tone_row,textvariable=self.responder_tone_var,state='readonly',
                     values=('Casual','Friendly','Playful','Dry','Sarcastic','Serious'),
                     width=14).pack(side='left',padx=(0,16))
        ttk.Label(tone_row,text='Humour 0–5',style='Panel.TLabel').pack(
            side='left',padx=(0,7))
        ttk.Combobox(tone_row,textvariable=self.responder_humour_var,
                     state='readonly',values=('0','1','2','3','4','5'),
                     width=5).pack(side='left')
        model_row=ttk.Frame(personality_tab,style='Panel.TFrame')
        model_row.pack(fill='x',pady=(7,4))
        ttk.Label(model_row,text='OpenAI model',style='Panel.TLabel').pack(
            side='left',padx=(0,8))
        ttk.Entry(model_row,textvariable=self.responder_model_var,
                  width=20).pack(side='left')
        ttk.Label(personality_tab,
            text='No example user or chat history is required in Custom personality mode.',
            style='Panel.TLabel',wraplength=610).pack(anchor='w',pady=(4,5))
        self._responder_logs_frame=ttk.Frame(personality_tab,style='Panel.TFrame')
        ttk.Label(self._responder_logs_frame,text='Optional historical style source',
                  style='Panel.TLabel').pack(anchor='w',pady=(5,4))
        ttk.Entry(self._responder_logs_frame,
                  textvariable=self.responder_persona_var,width=28).pack(
                      anchor='w',fill='x',pady=(0,5))
        ttk.Checkbutton(self._responder_logs_frame,text='Rotate copied style every 5 minutes',
                        variable=self.responder_rotation_var).pack(anchor='w',pady=3)
        ttk.Checkbutton(self._responder_logs_frame,text='Capture new public room chat locally',
                        variable=self.responder_capture_var).pack(anchor='w',pady=3)
        dir_row=ttk.Frame(self._responder_logs_frame,style='Panel.TFrame')
        dir_row.pack(fill='x',pady=(4,4))
        ttk.Entry(dir_row,textvariable=self.responder_log_dir_var).pack(
            side='left',fill='x',expand=True)
        ttk.Button(dir_row,text='Browse logs',command=self._responder_browse).pack(
            side='left',padx=(6,0))
        self._responder_update_style_controls()

        ttk.Label(targets_tab,text='Which speakers are allowed to trigger replies?',
                  style='Panel.TLabel').pack(anchor='w',pady=(0,6))
        ttk.Combobox(targets_tab,textvariable=self.responder_target_mode_var,
                     values=('Everyone','Selected users','First active speaker'),
                     state='readonly',width=28).pack(anchor='w',pady=(0,10))
        ttk.Label(targets_tab,text='Allowed usernames (separate multiple names with commas)',
                  style='Panel.TLabel').pack(anchor='w',pady=(0,4))
        self.responder_target_entry=ttk.Entry(
            targets_tab,textvariable=self.responder_target_var)
        self.responder_target_entry.pack(fill='x',pady=(0,8))
        ttk.Label(targets_tab,
            text='Everyone: all eligible public speakers. Selected users: only names '
                 'in the list. First active speaker: lock to one person until '
                 'they are quiet for 60 seconds. Other room chat is context only.',
            style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(0,9))
        ttk.Label(targets_tab,text='Reply behaviour',style='Panel.TLabel').pack(
            anchor='w',pady=(2,4))
        ttk.Combobox(targets_tab,textvariable=self.responder_responsiveness_var,
                     values=('Natural','Chatty'),state='readonly',
                     width=20).pack(anchor='w')
        ttk.Label(targets_tab,
            text='Natural replies only when it makes sense. Chatty responds more often, '
                 'still respecting cooldowns. Whispers and own messages do not trigger '
                 'public replies; existing blocked names containing "dan" stay blocked.',
            style='Panel.TLabel',wraplength=620).pack(anchor='w',pady=(8,3))

        ttk.Label(test_tab,text='Type a pretend room message. The bot generates a '
                  'preview using your personality. It will NOT send anything to Habbo.',
                  style='Panel.TLabel',wraplength=610).pack(anchor='w',pady=(0,9))
        ttk.Label(test_tab,text='Test speaker',style='Panel.TLabel').pack(anchor='w')
        ttk.Entry(test_tab,textvariable=self.responder_test_user_var,
                  width=25).pack(anchor='w',pady=(3,7))
        ttk.Label(test_tab,text='Test message',style='Panel.TLabel').pack(anchor='w')
        ttk.Entry(test_tab,textvariable=self.responder_test_message_var).pack(
            fill='x',pady=(3,10))
        ttk.Button(test_tab,text='Test AI reply (preview only)',
                   command=self._responder_test_reply).pack(anchor='w',pady=(0,7))
        ttk.Label(test_tab,text='Testing requires the OpenAI Python package '
                  'and OPENAI_API_KEY. It does not need Habbo or G-Earth to be connected.',
                  style='Panel.TLabel',wraplength=610).pack(anchor='w')

        actions=ttk.Frame(frame,style='Panel.TFrame')
        actions.pack(fill='x',pady=(0,8))
        ttk.Button(actions,text='Apply settings',command=self._responder_apply).pack(
            side='left',padx=(0,7))
        ttk.Button(actions,text='Send latest LIVE draft manually',
                   command=self._responder_send_latest).pack(side='left',padx=(0,7))
        ttk.Button(actions,text='Stop',command=self._responder_stop).pack(side='left')
        probe_row=ttk.Frame(frame,style='Panel.TFrame')
        probe_row.pack(fill='x',pady=(5,6))
        ttk.Button(probe_row,text='Learn my outgoing Chat packet',
                   command=self._responder_start_probe).pack(
                       side='left',padx=(0,7))
        ttk.Entry(probe_row,textvariable=self._responder_probe_phrase_var,
                  state='readonly',width=24).pack(side='left',padx=(0,5))
        ttk.Button(probe_row,text='Copy phrase',
                   command=self._responder_copy_probe).pack(side='left')
        ttk.Button(frame,text='Check G-Earth chat capture',
                   command=self._responder_check_capture).pack(anchor='w',pady=(0,6))
        ttk.Label(frame,textvariable=self.responder_status_var,
                  style='Panel.TLabel',wraplength=650).pack(anchor='w',pady=(5,9))
        ttk.Label(frame,text='RECENT DECISIONS / TEST PREVIEWS',
                  style='Panel.TLabel').pack(anchor='w')
        self.responder_log_text=tk.Text(frame,height=8,wrap='word',state='disabled',
            font=('Consolas',9),bg=p['field'],fg=p['text'],
            insertbackground=p['text'],relief='flat')
        self.responder_log_text.pack(fill='both',expand=True,pady=(5,7))
        ttk.Label(frame,text='To enable live sending, connect Packet Viewer → G-Earth. '
                  'If named Chat detection fails, click Learn my outgoing Chat packet, '
                  'copy the unique phrase and type it once into Habbo public chat. '
                  'Only that exact outgoing packet is used for sending; no guessed IDs.',
                  style='Panel.TLabel',wraplength=650).pack(anchor='w')

    def _responder_update_style_controls(self):
        if self.responder_style_mode_var.get()=='Chat-log style':
            self._responder_custom_frame.pack_forget()
            self._responder_logs_frame.pack(fill='x',pady=5)
        else:
            self._responder_logs_frame.pack_forget()
            self._responder_custom_frame.pack(fill='x',pady=(0,5))

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

    def _responder_start_probe(self):
        """Require a fresh user-typed public chat phrase to identify the packet."""
        if not self.packet_started or not self._habbo_session_connected:
            result='Connect Habbo AIR through the G-Earth Packet Viewer first.'
            self.responder_status_var.set(result)
            self._responder_log(result)
            return
        self._responder_wire_template=None
        self._responder_probe_token='hc-'+secrets.token_hex(6)
        self._responder_probe_started=time.monotonic()
        self._responder_probe_phrase_var.set(self._responder_probe_token)
        result=('Copy the phrase and type it EXACTLY once in Habbo public chat '
                'within 90 seconds. The AI will not send it automatically.')
        self.responder_status_var.set(result)
        self._responder_log('Chat-learning challenge ready. '+result)

    def _responder_copy_probe(self):
        phrase=self._responder_probe_token
        if not phrase:
            self.responder_status_var.set('Click Learn my outgoing Chat packet first.')
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(phrase)
        self.responder_status_var.set('Copied test phrase. Paste and SEND it in Habbo public chat.')

    def _responder_check_capture(self):
        """Explain the live Chat capture status without sending any packets."""
        if not self.packet_started or not self._habbo_session_connected:
            result=('G-Earth game session is not connected. '
                    'Connect Habbo AIR through Packet Viewer first.')
        elif self._responder_wire_template is not None:
            result=('READY: an exact outgoing Chat packet was verified from '
                    'the phrase you typed manually in Habbo.')
        elif self._responder_chat_template is not None:
            result='READY: the outgoing named Chat expression was learned from G-Earth.'
        elif self._responder_probe_token:
            result=('Waiting for the exact challenge text to be sent manually in '
                    'Habbo public chat. Copy the phrase and paste it into Habbo.')
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
        # Prefer the exact verified wire packet. This works even when G-Earth
        # does not know the symbolic name of the outgoing Chat header.
        wire=replacement_chat_frame(self._responder_wire_template,reply)
        if wire is not None:
            try:
                from g_python.hpacket import HPacket
                signed_id=int.from_bytes(wire[4:6],'big',signed=True)
                packet=HPacket(signed_id).append_bytes(wire[6:])
                if packet.is_corrupted() or packet.is_incomplete_packet():
                    raise ValueError('The verified Chat packet failed validation.')
                if self.packet_extension.send_to_server(packet) is False:
                    raise ValueError('G-Earth rejected the verified Chat packet.')
                return 'Send requested using manually verified Chat packet format.'
            except Exception as exc:
                return 'Not sent: '+str(exc)[:160]
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
        if (self._responder_probe_token and
                time.monotonic()-self._responder_probe_started>90):
            self._responder_probe_token=None
            self._responder_probe_started=0.0
            self._responder_probe_phrase_var.set('')
            self._responder_log(
                'Chat-learning phrase expired. Click Learn my outgoing Chat packet again.')
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
