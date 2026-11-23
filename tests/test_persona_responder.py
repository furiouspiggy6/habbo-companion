"""Offline regression checks for opt-in AI persona responder."""
from pathlib import Path
import tempfile
import unittest
from persona_responder import (
    PersonaResponder, chat_expression_from_template,
    clean_model_reply, safe_persona_filename,
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
        self.bot.fixed_target="Alice"
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
        self.assertEqual(safe_persona_filename("../../secret"),"______secret.txt")
        self.assertEqual(self.bot.style_examples(),["hey there","what you up to"])

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
