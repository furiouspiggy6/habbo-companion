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
        self.responder.fixed_target=str(self.config.get('responder_target',''))
        self.responder.auto_rotate=bool(self.config.get('responder_rotation',True))
        self.responder.save_history=bool(self.config.get('responder_capture',False))
        self.responder_enabled_var=tk.BooleanVar(value=False)
        self.responder_send_var=tk.BooleanVar(value=False)
        self.responder_rotation_var=tk.BooleanVar(value=self.responder.auto_rotate)
        self.responder_capture_var=tk.BooleanVar(value=self.responder.save_history)
        self.responder_persona_var=tk.StringVar(value=self.responder.persona)
        self.responder_target_var=tk.StringVar(value=self.responder.fixed_target)
        self.responder_log_dir_var=tk.StringVar(value=str(self.responder.log_dir))
        self.responder_model_var=tk.StringVar(value='gpt-5-mini')
        self.responder_status_var=tk.StringVar(value='OFF. Enable to analyse NEW room chat.')
        self._responder_results=queue.Queue()
        self._responder_generation=0
        self._responder_chat_template=None
        self._responder_last_draft=None

    def _make_responder_panel(self,parent):
        p=self._responder_palette
        frame=ttk.Frame(parent,style='Panel.TFrame',padding=(18,16))
        frame.pack(fill='both',expand=True)
        tk.Label(frame,text='AI PERSONA RESPONDER',font=('Segoe UI Semibold',18),
                 bg=p['background'],fg=p['text']).pack(anchor='w')
        ttk.Label(frame,text='Uses the existing AIR chat feed: no capture.py, '
                  'fixed mouse coordinates or extra login. AI analysis sends sampled '
                  'room messages to OpenAI ONLY while enabled.',
                  style='Panel.TLabel',wraplength=650).pack(anchor='w',pady=(3,12))
        ttk.Checkbutton(frame,text='Enable AI responder for NEW room messages',
                        variable=self.responder_enabled_var,
                        command=self._responder_apply).pack(anchor='w',pady=(2,5))
        ttk.Checkbutton(frame,text='Auto-send replies through G-Earth (OFF by default)',
                        variable=self.responder_send_var).pack(anchor='w',pady=(0,10))
        form=ttk.Frame(frame,style='Panel.TFrame')
        form.pack(fill='x')
        for row,label,var in (
            (0,'Style source username',self.responder_persona_var),
            (1,'Target username (blank = first eligible speaker)',self.responder_target_var),
            (2,'OpenAI model',self.responder_model_var),
        ):
            ttk.Label(form,text=label,style='Panel.TLabel').grid(
                row=row,column=0,sticky='w',pady=5,padx=(0,12))
            ttk.Entry(form,textvariable=var,width=27).grid(
                row=row,column=1,sticky='ew',pady=5)
        form.grid_columnconfigure(1,weight=1)
        ttk.Checkbutton(frame,text='Rotate style every 5 minutes among recently active logged users',
                        variable=self.responder_rotation_var).pack(anchor='w',pady=(12,3))
        ttk.Checkbutton(frame,text='Capture new public chat into local style files (optional)',
                        variable=self.responder_capture_var).pack(anchor='w',pady=(0,8))
        folder=ttk.Frame(frame,style='Panel.TFrame')
        folder.pack(fill='x',pady=(4,5))
        ttk.Label(folder,text='Style logs',style='Panel.TLabel').pack(side='left',padx=(0,7))
        ttk.Entry(folder,textvariable=self.responder_log_dir_var).pack(
            side='left',fill='x',expand=True)
        ttk.Button(folder,text='Browse',command=self._responder_browse).pack(
            side='left',padx=(6,0))
        ttk.Label(frame,text='Choose your old chat_logs/users folder to reuse '
                  'Responder_Single logs. Or capture new style files under '
                  'Companion persona_logs/users. OPENAI_API_KEY must be set '
                  'in your Windows environment; it is never saved in settings.',
                  style='Panel.TLabel',wraplength=650).pack(anchor='w',pady=(3,10))
        actions=ttk.Frame(frame,style='Panel.TFrame')
        actions.pack(fill='x',pady=(0,9))
        ttk.Button(actions,text='Apply settings',command=self._responder_apply).pack(
            side='left',padx=(0,7))
        ttk.Button(actions,text='Send latest draft manually',
                   command=self._responder_send_latest).pack(side='left',padx=(0,7))
        ttk.Button(actions,text='Stop',command=self._responder_stop).pack(side='left')
        ttk.Label(frame,textvariable=self.responder_status_var,
                  style='Panel.TLabel',wraplength=650).pack(anchor='w',pady=(5,9))
        ttk.Label(frame,text='RECENT DECISIONS / DRAFTS',
                  style='Panel.TLabel').pack(anchor='w')
        self.responder_log_text=tk.Text(frame,height=10,wrap='word',state='disabled',
            font=('Consolas',9),bg=p['field'],fg=p['text'],
            insertbackground=p['text'],relief='flat')
        self.responder_log_text.pack(fill='both',expand=True,pady=(5,7))
        ttk.Label(frame,text='For automatic sending, connect Packet Viewer to G-Earth, '
                  'then type one normal public chat line in Habbo. Companion learns '
                  'the outgoing Chat packet format for this session; it does not '
                  'guess packet IDs. Whispers never trigger public replies.',
                  style='Panel.TLabel',wraplength=650).pack(anchor='w')

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

    def _responder_apply(self):
        self._responder_generation+=1
        self.responder.running=False
        self.responder.persona=self.responder_persona_var.get().strip()[:80] or 'Mario35'
        self.responder.fixed_target=self.responder_target_var.get().strip()[:80]
        self.responder.auto_rotate=bool(self.responder_rotation_var.get())
        self.responder.save_history=bool(self.responder_capture_var.get())
        self.responder.log_dir=Path(
            self.responder_log_dir_var.get().strip() or self._responder_default_logs)
        self.responder.reset_room()
        self.responder.enabled=bool(self.responder_enabled_var.get())
        self.config.update(
            responder_persona=self.responder.persona,
            responder_target=self.responder.fixed_target,
            responder_rotation=self.responder.auto_rotate,
            responder_capture=self.responder.save_history,
            responder_log_dir=str(self.responder.log_dir),
        )
        self.save()
        state='ON' if self.responder.enabled else 'OFF'
        self.responder_status_var.set(
            f'AI {state} | style: {self.responder.persona} | '
            f'target: {self.responder.fixed_target or "first eligible speaker"}')
        self._responder_log('Settings applied. AI '+state+'.')

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

    def _responder_worker(self,payload,model,generation):
        try:
            reply=generate_persona_reply(payload,model=model)
            self._responder_results.put((generation,reply,None))
        except Exception as exc:
            self._responder_results.put((generation,None,str(exc)[:200]))

    def _responder_tick(self):
        for _ in range(6):
            try:
                generation,reply,error=self._responder_results.get_nowait()
            except queue.Empty:
                break
            if generation!=self._responder_generation:
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
                self._responder_log('DRAFT '+reply)
                if self.responder_send_var.get():
                    outcome=self._responder_send(reply)
                    self.responder_status_var.set(outcome)
                    self._responder_log(outcome)
                else:
                    self.responder_status_var.set('Draft ready (preview mode).')
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
        self._responder_log('Decision for '+payload['target']+' | style '+payload['persona'])
        threading.Thread(target=self._responder_worker,
                         args=(payload,model,generation),daemon=True).start()
