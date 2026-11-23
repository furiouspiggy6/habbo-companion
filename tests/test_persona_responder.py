"""Offline regression checks for opt-in AI persona responder."""
from pathlib import Path
import ast
import inspect
import unittest.mock
import tempfile
import unittest
from persona_responder import (
    PersonaResponder, chat_expression_from_template,
    clean_model_reply, safe_persona_filename,
    verified_outgoing_chat_frame, replacement_chat_frame,
    selected_usernames, DEFAULT_PERSONALITY, generate_persona_reply,
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

    def test_cooldown_and_questions(self):
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

    def test_style_files_sanitized_and_parsed(self):
        self.assertEqual(safe_persona_filename("../../secret"),"secret.txt")
        self.assertEqual(self.bot.style_examples(),["hey there","what you up to"])


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
        self.assertIn("DO NOT imitate",responses.last["input"][0]["content"])

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

    def _outgoing_frame(self, text, header=1732, tail=b'\x00\x00\x00\x00'):
        encoded=text.encode("utf-8")
        body=header.to_bytes(2,"big")+len(encoded).to_bytes(2,"big")+encoded+tail
        return len(body).to_bytes(4,"big")+body

    def test_manual_probe_verifies_exact_outgoing_chat_frame(self):
        probe="hc-012345abcdef"
        frame=self._outgoing_frame(probe,header=4892)
        self.assertTrue(verified_outgoing_chat_frame(frame,probe))
        self.assertFalse(verified_outgoing_chat_frame(frame,"hc-012345abcdee"))
        self.assertFalse(verified_outgoing_chat_frame(frame,probe.upper()))
        self.assertFalse(verified_outgoing_chat_frame(frame[:-1],probe))
        self.assertFalse(verified_outgoing_chat_frame(
            self._outgoing_frame("other text",4892),probe))
        self.assertFalse(verified_outgoing_chat_frame(
            self._outgoing_frame(probe,header=0),probe))

    def test_manual_probe_replacement_retains_header_and_other_fields(self):
        probe="hc-012345abcdef"
        tail=b'\x00\x00\x00\x03\x00\x00\x00\x05'
        frame=self._outgoing_frame(probe,header=35001,tail=tail)
        self.assertTrue(verified_outgoing_chat_frame(frame,probe))
        updated=replacement_chat_frame(frame,"Hi there 😄")
        self.assertEqual(int.from_bytes(updated[:4],"big"),len(updated)-4)
        self.assertEqual(updated[4:6],frame[4:6])
        size=int.from_bytes(updated[6:8],"big")
        self.assertEqual(updated[8:8+size].decode("utf-8"),"Hi there 😄")
        self.assertEqual(updated[8+size:],tail)
        self.assertIsNone(replacement_chat_frame(frame,"x"*141))
        self.assertIsNone(replacement_chat_frame(frame,"bad\ntext"))
        self.assertIsNone(replacement_chat_frame(
            self._outgoing_frame("not-a-challenge"),"hello"))

    def test_manual_probe_never_uses_a_guess_for_packet_id(self):
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
        self.assertIn("verified_outgoing_chat_frame(raw,phrase)",body)
        self.assertIn("('responder_wire_template',bytes(raw))",body)
        self.assertIn("time.monotonic()-self._responder_probe_started<=90",body)
        from persona_responder_ui import PersonaResponderMixin
        send=inspect.getsource(PersonaResponderMixin._responder_send)
        self.assertIn("replacement_chat_frame(self._responder_wire_template,reply)",send)
        self.assertIn("HPacket(signed_id).append_bytes(wire[6:])",send)

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
