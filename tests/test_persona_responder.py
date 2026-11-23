"""Offline regression checks for opt-in AI persona responder."""
from pathlib import Path
import ast
import unittest.mock
import tempfile
import runpy
import time
import unittest
from persona_responder import (
    PersonaResponder, chat_expression_from_template,
    clean_model_reply, safe_persona_filename, parse_style_message,
    selected_usernames, DEFAULT_PERSONALITY, generate_persona_reply,
    list_style_usernames, matching_style_usernames,
    clamp_reply_interval, DEFAULT_REPLY_INTERVAL_SECONDS,
    parse_temporary_instruction, personality_fields,
)

class PersonaResponderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bot = PersonaResponder(Path(self.temp.name))
        (Path(self.temp.name)/"Mario35.txt").write_text(
            "[12:01] Mario35: hey there\n[12:02] Mario35: what you up to\n",
            encoding="utf-8"
        )

    def test_public_logging_enabled_even_when_ai_off_and_custom_mode(self):
        self.assertFalse(self.bot.enabled)
        self.assertTrue(self.bot.save_history)
        self.assertEqual(self.bot.style_mode,'Custom personality')
        self.assertTrue(self.bot.record_public_message(
            'popbrocks','hello ppl',now=1700000000))
        self.assertTrue(self.bot.record_public_message(
            'visitor-6w-3-8','wbu?',now=1700000001))
        self.assertTrue(self.bot.record_public_message(
            'popbrocks','lol yep',now=1700000002))
        folder=Path(self.temp.name)
        lines=(folder/'popbrocks.txt').read_text(
            encoding='utf-8').splitlines()
        self.assertEqual(len(lines),2)
        self.assertTrue(lines[0].endswith('] popbrocks: hello ppl'))
        self.assertTrue(lines[1].endswith('] popbrocks: lol yep'))
        self.assertTrue((folder/'visitor-6w-3-8.txt').is_file())
        self.assertEqual(self.bot.logged_messages,3)
        self.assertFalse(self.bot.running)

    def test_archive_directory_independent_from_style_source(self):
        with tempfile.TemporaryDirectory() as storage:
            archive=Path(storage)/'persona_logs'/'users'
            self.bot.archive_dir=archive
            self.bot.log_dir=Path(storage)/'old_logs'/'users'
            self.bot.log_dir.mkdir(parents=True)
            self.bot.style_mode='Custom personality'
            self.assertTrue(self.bot.record_public_message(
                'Cheesecake','hello room',now=1700000003))
            self.assertTrue((archive/'Cheesecake.txt').is_file())
            self.assertFalse((self.bot.log_dir/'Cheesecake.txt').exists())
            self.assertEqual(self.bot.log_dir.name,'users')

    def test_chat_logging_keeps_owners_public_chat_and_ignores_whispers(self):
        folder=Path(self.temp.name)
        self.assertTrue(self.bot.record_public_message(
            'dan_alt100','this is my own chat',chat_type=0))
        self.assertFalse(self.bot.record_public_message(
            'popbrocks','secret whisper',chat_type=1))
        self.assertFalse(self.bot.record_public_message(
            'popbrocks','also private',chat_type=12))
        self.assertTrue((folder/'dan_alt100.txt').is_file())
        self.assertFalse((folder/'popbrocks.txt').exists())
        self.bot.observe('popbrocks','public reply',own_name='dan_alt100',now=12)
        self.assertFalse((folder/'popbrocks.txt').exists(),
                         'AI observation must not write duplicate log entries')
        self.bot.save_history=False
        self.assertFalse(self.bot.record_public_message(
            'popbrocks','disabled logging',chat_type=0))
        self.assertFalse((folder/'popbrocks.txt').exists())

    def test_background_archives_offscreen_public_chat_before_visual_filter(self):
        scope=runpy.run_path(
            str(Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'),
            run_name='habbo_companion_test')
        App=scope['ChatOverlayApp']
        class Fake:
            config={'visible_only':True}
            whisper_hints=[]
            def __init__(self,bot):
                self.responder=bot
                self._responder_room_speakers={}
                self.updates=0
            def _responder_update_logging_status(self):
                self.updates+=1
        dummy=Fake(self.bot)
        App.handle_message(dummy,{
            'name':'Cheesecake','text':'off screen room chat','chatType':0,
            'x':-40,'y':-40,'sw':800,'sh':600,
        })
        self.assertTrue((Path(self.temp.name)/'Cheesecake.txt').is_file(),
                        'Visibility filter must not suppress background logging')
        self.assertEqual(dummy.updates,1)
        self.assertIn('cheesecake',dummy._responder_room_speakers)
        self.assertEqual(dummy._responder_room_speakers['cheesecake'][0],
                         'Cheesecake')
        App.handle_message(dummy,{
            'name':'MaraGene','text':'private whisper','chatType':1,
            'x':-40,'y':-40,'sw':800,'sh':600,
        })
        self.assertFalse((Path(self.temp.name)/'MaraGene.txt').exists())
        # The G-Earth whisper hint fallback also protects unlabeled whispers.
        dummy.whisper_hints=[(time.time(),'fallback whisper')]
        App.handle_message(dummy,{
            'name':'MaraGene','text':'fallback whisper',
            'x':-40,'y':-40,'sw':800,'sh':600,
        })
        self.assertFalse((Path(self.temp.name)/'MaraGene.txt').exists())
        self.assertEqual(dummy.updates,3)
        self.assertNotIn('maragene',dummy._responder_room_speakers,
                         'Private chat must not appear in room-target suggestions')

    def test_disabled_by_default(self):
        self.bot.observe("someone", "hi", now=5.0)
        self.assertIsNone(self.bot.pop_ready(now=6.0))

    def test_dynamic_target_lock_and_release(self):
        self.bot.enabled=True
        self.bot.target_mode="First active speaker"
        self.bot.observe("Alice","hi",now=10.0)
        self.bot.observe("Bob","test",now=11.0)
        self.assertEqual(self.bot.active_target,"Alice")
        out=self.bot.pop_ready(now=12.0)
        self.assertEqual(out["target"],"Alice")
        self.bot.running=False
        self.bot.observe("Bob","another",now=72.0)
        self.assertEqual(self.bot.active_target,"Bob")

    def test_fixed_target_only(self):
        self.bot.enabled=True
        self.bot.target_mode="Selected users"
        self.bot.selected_users="Alice"
        self.bot.observe("Bob","hi",now=10.0)
        self.assertIsNone(self.bot.pop_ready(now=12.0))
        self.bot.observe("Alice","hi",now=13.0)
        self.assertEqual(self.bot.pop_ready(now=14.0)["target"],"Alice")

    def test_dan_blocked_and_whispers_ignored(self):
        self.bot.enabled=True
        self.bot.observe("Dan2","hi",now=10.0)
        self.bot.observe("Alice","private",chat_type=1,now=11.0)
        self.assertIsNone(self.bot.pop_ready(now=13.0))
        self.bot.observe("Alice","public",now=14.0)
        self.assertEqual(self.bot.pop_ready(now=15.0)["target"],"Alice")

    def test_copied_persona_does_not_inherit_generic_personality_settings(self):
        # Old custom choices can remain stored for switching back, but must
        # never enter a recreated persona's model payload or model instructions.
        self.bot.personality='Helpful cheerful Habbo assistant'
        self.bot.tone='Friendly'
        self.bot.humour=5
        self.bot.responsiveness='Chatty'
        self.bot.style_mode='Chat-log style'
        self.bot.persona='Mario35'
        self.bot.reply_cooldown_seconds=5
        fields=self.bot._personality_payload()
        self.assertNotIn('personality',fields)
        self.assertNotIn('tone',fields)
        self.assertNotIn('humour',fields)
        self.assertNotIn('responsiveness',fields)
        self.assertEqual(fields['persona'],'Mario35')
        self.assertEqual(fields['style_mode'],'Chat-log style')
        self.assertIn('persona_reference',fields)
        self.bot.style_mode='Custom personality'
        fields=self.bot._personality_payload()
        self.assertEqual(fields['tone'],'Friendly')
        self.assertEqual(fields['humour'],5)
        self.assertEqual(fields['responsiveness'],'Chatty')
        self.assertEqual(fields['personality'],'Helpful cheerful Habbo assistant')

    def test_parse_temporary_chat_instructions_and_expiry(self):
        rule=parse_temporary_instruction('be mean to Marc for 10mins',now=100)
        self.assertEqual(rule['kind'],'tease')
        self.assertIn('Marc',rule['instruction'])
        self.assertIn('banter',rule['instruction'])
        self.assertEqual(rule['expires_at'],700)
        afk=parse_temporary_instruction('pretend to go afk for 2 mins',now=100)
        self.assertEqual(afk['kind'],'afk')
        self.assertEqual(afk['expires_at'],220)
        slow=parse_temporary_instruction('type slow',now=100)
        self.assertEqual(slow['kind'],'slow')
        self.assertIsNone(slow['expires_at'])
        custom=parse_temporary_instruction('talk about coffee for 3mins',now=100)
        self.assertEqual(custom['kind'],'custom')
        self.assertEqual(custom['instruction'],'talk about coffee')
        self.assertEqual(custom['expires_at'],280)
        with self.assertRaises(ValueError):
            parse_temporary_instruction('')
        with self.assertRaises(ValueError):
            parse_temporary_instruction('go afk for 0 min')
        with self.assertRaises(ValueError):
            parse_temporary_instruction('go afk for 10 hours')

    def test_instructions_overlay_persona_and_expire_or_remove(self):
        self.bot.persona='Mario35'
        self.bot.style_mode='Chat-log style'
        self.bot.personality='A super-friendly assistant'
        self.bot.add_temporary_instruction('be mean to Marc for 10mins',now=100)
        slow=self.bot.add_temporary_instruction('type slow',now=100)
        self.assertEqual(self.bot.temporary_send_delay(now=120),10)
        self.assertEqual(len(self.bot.active_temporary_instructions(now=120)),2)
        self.assertEqual(len(self.bot._temporary_prompt_instructions(now=120)),1)
        payload=self.bot.test_payload('Alice','hello')
        self.assertNotIn('personality',payload)
        self.assertIn('temporary_instructions',payload)
        self.bot.remove_temporary_instruction(slow['id'])
        self.assertEqual(self.bot.temporary_send_delay(now=120),0)
        self.assertEqual(len(self.bot.active_temporary_instructions(now=701)),0)
        self.assertEqual(self.bot._temporary_prompt_instructions(now=701),[])

    def test_afk_blocks_generation_including_pending_chat_until_expiry(self):
        self.bot.enabled=True
        self.bot.observe('Alice','hey you there?',now=100)
        self.bot.add_temporary_instruction('pretend to go afk for 2 mins',
                                           now=100.1)
        self.assertTrue(self.bot.is_temporarily_afk(now=101))
        self.assertFalse(self.bot.pending)
        self.bot.observe('Alice','chat while afk',now=110)
        self.assertIsNone(self.bot.pop_ready(now=111))
        self.assertIsNone(self.bot.pop_ready(now=219))
        self.assertFalse(self.bot.is_temporarily_afk(now=221))
        self.bot.observe('Alice','welcome back',now=221)
        self.assertIsNotNone(self.bot.pop_ready(now=222))
        self.assertEqual(self.bot._temporary_prompt_instructions(now=222),[])

    def test_persona_mode_keeps_anti_spam_interval_when_slider_is_fast(self):
        self.bot.enabled=True
        self.bot.style_mode='Chat-log style'
        self.bot.reply_cooldown_seconds=5
        self.bot.observe('Alice','hey',now=10)
        self.assertIsNotNone(self.bot.pop_ready(now=11))
        self.bot.running=False
        self.bot.remember_reply('hi',now=11)
        self.bot.observe('Alice','you there',now=20)
        self.assertIsNone(self.bot.pop_ready(now=21))
        self.bot.observe('Alice','you there now',now=40)
        self.assertIsNotNone(self.bot.pop_ready(now=41))

    def test_slider_interval_limits_and_rounding(self):
        self.assertEqual(DEFAULT_REPLY_INTERVAL_SECONDS,30)
        self.assertEqual(clamp_reply_interval(-10),5)
        self.assertEqual(clamp_reply_interval(0),5)
        self.assertEqual(clamp_reply_interval(13),15)
        self.assertEqual(clamp_reply_interval(28),30)
        self.assertEqual(clamp_reply_interval(61),60)
        self.assertEqual(clamp_reply_interval(999),120)
        self.assertEqual(clamp_reply_interval('bad'),30)
        self.assertEqual(clamp_reply_interval(float('nan')),30)

    def test_adjustable_reply_rate_prevents_back_to_back_drafts(self):
        self.assertEqual(self.bot.reply_cooldown_seconds,30)
        self.bot.enabled=True
        # First valid reply is not delayed; the cooldown follows a draft.
        self.bot.observe('Alice','hey',now=10.0)
        self.assertIsNotNone(self.bot.pop_ready(now=11.0))
        self.bot.running=False
        self.bot.remember_reply('hey there',now=11.0)
        self.bot.observe('Alice','you there',now=20.0)
        self.assertIsNone(self.bot.pop_ready(now=21.0))
        # The next eligible message after 30 seconds may get a response.
        self.bot.observe('Alice','hi again',now=40.0)
        self.assertIsNotNone(self.bot.pop_ready(now=41.0))
        self.bot.running=False
        self.bot.remember_reply('hi again',now=41.0)
        # Moving the slider right changes rate immediately.
        self.bot.reply_cooldown_seconds=120
        self.bot.observe('Alice','one more',now=100.0)
        self.assertIsNone(self.bot.pop_ready(now=101.0))
        self.bot.observe('Alice','hello much later',now=161.0)
        self.assertIsNotNone(self.bot.pop_ready(now=162.0))

    def test_cooldown_and_questions(self):
        # Previous short-cooldown regression now uses the slider's fast end.
        self.bot.reply_cooldown_seconds=5
        self.bot.enabled=True
        self.bot.observe("Alice","hi",now=10.0)
        self.assertIsNotNone(self.bot.pop_ready(now=11.0))
        self.bot.running=False
        self.bot.remember_reply("what's up?",now=11.0)
        self.assertTrue(self.bot.is_repeated_question("whats up?"))
        self.bot.observe("Alice","you there?",now=12.0)
        self.assertIsNone(self.bot.pop_ready(now=13.0))
        self.bot.observe("Alice","still there?",now=16.0)
        self.assertIsNotNone(self.bot.pop_ready(now=17.0))

    def test_user_log_username_discovery_and_case_insensitive_search(self):
        folder=Path(self.temp.name)
        (folder/'MaraGene.txt').write_text(
            "[13:00] MaraGene: hey lol\n", encoding='utf-8')
        (folder/'marioboy.txt').write_text(
            "[13:01] marioboy: sup\n", encoding='utf-8')
        (folder/'alice.txt').write_text(
            "[13:02] alice: hello\n", encoding='utf-8')
        (folder/'notes.md').write_text("ignore",encoding='utf-8')
        (folder/'invalid.name.txt').write_text("ignore",encoding='utf-8')
        (folder/'empty_dir.txt').mkdir()
        names=list_style_usernames(folder)
        self.assertEqual(names,['alice','MaraGene','Mario35','marioboy'])
        self.assertEqual(matching_style_usernames(names,'MARA'),['MaraGene'])
        self.assertEqual(matching_style_usernames(names,'ar'),
                         ['MaraGene','Mario35','marioboy'])
        self.assertEqual(matching_style_usernames(names,'e'),
                         ['alice','MaraGene'])
        self.assertEqual(matching_style_usernames(names,'zz'),[])
        self.assertEqual(matching_style_usernames(names,''),names)
        self.assertEqual(len(matching_style_usernames(names,'',limit=2)),2)

    def test_parent_chat_logs_folder_and_selected_style_examples(self):
        folder=Path(self.temp.name)/'chat_logs'/'users'
        folder.mkdir(parents=True)
        (folder/'MaraGene.txt').write_text(
            '[12:00] MaraGene: u okay lol\n'
            '[12:01] MaraGene: wbu thoooo\n',
            encoding='utf-8')
        self.assertEqual(
            list_style_usernames(folder.parent), ['MaraGene'])
        self.bot.log_dir=folder
        self.bot.persona=matching_style_usernames(
            list_style_usernames(folder),'gene')[0]
        self.bot.style_mode='Chat-log style'
        payload=self.bot.test_payload('Someone','hey')
        self.assertEqual(payload['persona'],'MaraGene')
        self.assertEqual(payload['style_examples'],
                         ['u okay lol','wbu thoooo'])
        self.assertEqual(payload['style_mode'],'Chat-log style')

    def test_style_files_sanitized_and_parsed(self):
        self.assertEqual(safe_persona_filename("../../secret"),"secret.txt")
        self.assertEqual(self.bot.style_examples(),["hey there","what you up to"])


    def test_persona_reference_uses_behavior_not_just_unique_style(self):
        folder=Path(self.temp.name)
        (folder/'MaraGene.txt').write_text(
            '[13:00] MaraGene: lol nah\n'
            '[13:01] MaraGene: lol nah\n'
            '[13:02] MaraGene: you fr?\n'
            '[13:03] MaraGene: im just here chilling haha\n'
            '[13:04] MaraGene: bruhh\n',
            encoding='utf-8')
        self.bot.persona='MaraGene'
        self.bot.style_mode='Chat-log style'
        reference=self.bot.persona_reference()
        self.assertEqual(reference['reference_username'],'MaraGene')
        self.assertEqual(reference['evidence_messages_in_recent_log_window'],5)
        self.assertEqual(reference['sample_message_count'],5)
        self.assertEqual(reference['sample_messages_in_chronological_order'],
                         ['lol nah','lol nah','you fr?',
                          'im just here chilling haha','bruhh'])
        self.assertEqual(reference['observable_chat_habits'][
                             'messages_with_questions_percent'],20)
        self.assertEqual(reference['observable_chat_habits'][
                             'messages_with_laughter_percent'],60)
        self.assertIn('limited',reference['evidence_quality'])
        payload=self.bot.test_payload('Someone','you alright?')
        self.assertTrue(payload['persona_simulation'])
        self.assertEqual(payload['persona_reference'],reference)
        self.assertEqual(payload['style_mode'],'Chat-log style')

    def test_persona_reference_is_bounded_and_uses_older_and_recent_messages(self):
        folder=Path(self.temp.name)
        # Bounded processing regardless of how long 24/7 chat logging runs.
        with (folder/'longhistory.txt').open('w',encoding='utf-8') as stream:
            for i in range(2100):
                stream.write(f'[13:00] longhistory: msg{i:04d}\n')
        self.bot.persona='longhistory'
        reference=self.bot.persona_reference()
        self.assertEqual(reference['evidence_messages_in_recent_log_window'],1600)
        samples=reference['sample_messages_in_chronological_order']
        self.assertLessEqual(len(samples),120)
        self.assertEqual(len(samples),120)
        self.assertEqual(samples[0],'msg0500')
        self.assertEqual(samples[-1],'msg2099')
        self.assertIn('msg2010',samples)
        self.assertEqual(self.bot.persona_reference(),reference,
                         'Persona evidence should not randomly change every reply')

    def test_persona_prompt_models_habits_and_does_not_claim_real_identity(self):
        class Stub:
            output_text='lol nah'
        class Responses:
            def create(self,**kwargs):
                self.last=kwargs
                return Stub()
        responses=Responses()
        class Client:
            def __init__(self,**kwargs):
                self.responses=responses
        import sys
        self.bot.style_mode='Chat-log style'
        with unittest.mock.patch.dict('os.environ',{'OPENAI_API_KEY':'test'}):
            with unittest.mock.patch.dict(
                sys.modules,{'openai':unittest.mock.Mock(OpenAI=Client)}):
                reply=generate_persona_reply(self.bot.test_payload('Alice','hey'))
        self.assertEqual(reply,'lol nah')
        system=responses.last['input'][0]['content']
        self.assertIn('coherent conversational',system)
        self.assertIn('Never claim to literally be that person',system)
        self.assertIn('never invent private facts',system)
        submitted=responses.last['input'][1]['content']
        self.assertIn('"persona_reference"',submitted)
        self.assertIn('"persona_simulation": true',submitted)

    def test_chat_log_parsing_preserves_persona_speech_before_colons(self):
        self.assertEqual(
            parse_style_message('[13:01] MaraGene: my take: nah lol','MaraGene'),
            'my take: nah lol')
        self.assertEqual(
            parse_style_message('[13:01] my take: nah lol','MaraGene'),
            'my take: nah lol')
        self.assertEqual(
            parse_style_message('[13:01] Mario35: hi there','Mario35'),
            'hi there')

    def test_persona_selection_deterministic_between_generated_replies(self):
        folder=Path(self.temp.name)
        with (folder/'MaraGene.txt').open('w',encoding='utf-8') as stream:
            for i in range(180):
                stream.write(f'[13:01] MaraGene: message{i:03d} with: punctuation\n')
        self.bot.persona='MaraGene'
        self.bot.style_mode='Chat-log style'
        first=self.bot.style_examples()
        self.assertEqual(first,self.bot.style_examples())
        self.assertEqual(len(first),80)
        self.assertEqual(first[-1],'message179 with: punctuation')
        self.assertEqual(
            self.bot.persona_reference()['sample_messages_in_chronological_order'][-1],
            'message179 with: punctuation')

    def test_custom_personality_requires_no_logs(self):
        self.bot.enabled=True
        self.bot.persona="no-file-needed"
        self.bot.style_mode="Custom personality"
        self.bot.personality="A chill bot that loves puns."
        self.bot.observe("Alice","hi bot",now=10.0)
        payload=self.bot.pop_ready(now=11.0)
        self.assertEqual(payload["personality"],"A chill bot that loves puns.")
        self.assertNotIn("style_examples",payload)
        self.assertEqual(payload["target"],"Alice")

    def test_everyone_can_trigger_and_targets_most_recent_speaker(self):
        self.bot.enabled=True
        self.bot.target_mode="Everyone"
        self.bot.observe("Alice","hey",now=10.0)
        self.bot.observe("Bob","yo",now=10.1)
        payload=self.bot.pop_ready(now=11.0)
        self.assertEqual(payload["target"],"Bob")
        self.assertTrue(payload["new_messages"][1]["reply_eligible"])

    def test_selected_multiple_users_and_non_selected_as_context(self):
        self.bot.enabled=True
        self.bot.target_mode="Selected users"
        self.bot.selected_users=" ALICE, Bob\ncharlie "
        self.assertEqual(selected_usernames(self.bot.selected_users),
                         {"alice","bob","charlie"})
        self.bot.observe("random","no",now=10.0)
        self.assertIsNone(self.bot.pop_ready(now=11.0))
        self.bot.observe("ALICE","hello",now=12.0)
        self.bot.observe("random","hello too",now=12.1)
        payload=self.bot.pop_ready(now=13.0)
        self.assertEqual(payload["target"],"ALICE")
        self.assertTrue(payload["new_messages"][0]["reply_eligible"])
        self.assertFalse(payload["new_messages"][1]["reply_eligible"])

    def test_test_payload_does_not_need_enabled_or_change_live_state(self):
        self.assertFalse(self.bot.enabled)
        payload=self.bot.test_payload("Tester","what's up?")
        self.assertTrue(payload["test_mode"])
        self.assertEqual(payload["target"],"Tester")
        self.assertEqual(payload["personality"],DEFAULT_PERSONALITY)
        self.assertFalse(self.bot.running)
        self.assertEqual(list(self.bot.context),[])

    def test_log_style_optional_and_missing_log_reports_error(self):
        self.bot.style_mode="Chat-log style"
        self.assertIn("style_examples",self.bot.test_payload("a","hi"))
        self.bot.persona="Unknown"
        self.assertIn("error",self.bot.test_payload("a","hi"))

    def test_personality_prompt_and_preview_rule(self):
        class Stub:
            output_text="hey there!"
        class Responses:
            def create(self,**kwargs):
                self.last=kwargs
                return Stub()
        responses=Responses()
        class Client:
            def __init__(self,**kwargs):self.responses=responses
        import sys
        with unittest.mock.patch.dict("os.environ",{"OPENAI_API_KEY":"test"}):
            with unittest.mock.patch.dict(sys.modules,{"openai":unittest.mock.Mock(OpenAI=Client)}):
                reply=generate_persona_reply(self.bot.test_payload("a","hi"))
        self.assertEqual(reply,"hey there!")
        self.assertIn("test_mode",responses.last["input"][0]["content"])
        self.assertIn("do not imitate anyone",responses.last["input"][0]["content"])

    def test_actual_g_earth_expression_is_used_for_capture(self):
        # G-Python's g_string is the legacy/raw representation: it cannot
        # be checked for a {out:Chat} expression prefix.
        source=(Path(__file__).resolve().parents[1] /
                'Habbo_Companion.pyw').read_text(encoding='utf-8')
        tree=ast.parse(source)
        overlay=next(node for node in tree.body
                     if isinstance(node,ast.ClassDef)
                     and node.name=='ChatOverlayApp')
        worker=next(node for node in overlay.body
                    if isinstance(node,ast.FunctionDef)
                    and node.name=='_packet_worker')
        body=ast.get_source_segment(source,worker)
        self.assertIn('observed=msg.packet.g_expression(ext)',body)
        self.assertIn("chat_expression_from_template(observed,'probe')",body)
        self.assertNotIn("detail.lstrip().lower().startswith('{out:chat}')",body)
        self.assertIn("('responder_outgoing_seen',)",body)
        self.assertIn("('responder_chat_template',observed)",body)

    def test_chat_template_accepts_expected_outgoing_expression(self):
        actual='{out:Chat}{s:"hello"}{i:0}{i:0}'
        self.assertEqual(chat_expression_from_template(actual,"hi"),
                         '{out:Chat}{s:"hi"}{i:0}{i:0}')
        # No ability to infer an unverified packet ID from unrelated output.
        self.assertIsNone(chat_expression_from_template(
            '{out:1234}{s:"hello"}{i:0}{i:0}',"hi"))

    def test_template_uses_real_outgoing_packet_shape(self):
        template='{out:Chat}{s:"hello"}{i:0}{i:0}'
        self.assertEqual(
            chat_expression_from_template(template,'yes'),
            '{out:Chat}{s:"yes"}{i:0}{i:0}')
        self.assertIsNone(chat_expression_from_template('{out:Move}{s:"hello"}','yes'))
        self.assertIsNone(chat_expression_from_template('{out:Chat}{i:1}','yes'))
        self.assertIsNone(chat_expression_from_template(template,'bad\nmessage'))
        self.assertIn(r'\"',chat_expression_from_template(template,'he said "hi"'))

    def test_skip_and_reply_limit(self):
        self.assertIsNone(clean_model_reply('SKIP'))
        self.assertEqual(clean_model_reply("  Hey\nthere  "),"Hey there")
        self.assertEqual(len(clean_model_reply("a"*200)),140)

if __name__=="__main__":
    unittest.main()
