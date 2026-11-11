"""GUI-free verification of the wide chat layout and whisper classification."""
import ast
import re
import json
from pathlib import Path
import unittest

APP=Path(__file__).resolve().parent.parent/'Habbo_Companion.pyw'
CODE=APP.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
HELPERS=('is_whisper_chat','chat_one_line','fit_line_ellipsis','whisper_packet_text','match_recent_whisper')
NODES=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in HELPERS]
assert len(NODES)==len(HELPERS), 'Missing chat layout helpers'
namespace={'re':re,'json':json}
exec(compile(ast.Module(body=NODES,type_ignores=[]),str(APP),'exec'),namespace)


class FixedFont:
    def measure(self,value):
        return len(value)*8


class WideChatTests(unittest.TestCase):
    def test_whispers_are_chat_type_two_only(self):
        f=namespace['is_whisper_chat']
        self.assertTrue(f(2))
        self.assertTrue(f('2'))
        for value in (0,1,3,None,'whisper',''):
            with self.subTest(value=value):
                self.assertFalse(f(value))

    def test_multi_line_message_flattens_to_one_row(self):
        f=namespace['chat_one_line']
        self.assertEqual(
            f('omg cheese and kay can\n i borrow you both\t too please'),
            'omg cheese and kay can i borrow you both too please'
        )

    def test_message_keeps_full_text_if_it_fits(self):
        value='HowlingWolves: emilio argentinian superchad'
        self.assertEqual(
            namespace['fit_line_ellipsis'](value,FixedFont(),1000),value)

    def test_overlong_message_is_a_single_truncated_row(self):
        value='MicrowaveMeal: omg cheese and kay can i borrow you both too please'
        result=namespace['fit_line_ellipsis'](value,FixedFont(),240)
        self.assertNotIn('\n',result)
        self.assertTrue(result.endswith('…'))
        self.assertLessEqual(FixedFont().measure(result),240)

    def test_whisper_packet_detection(self):
        detect=namespace['whisper_packet_text']
        self.assertEqual(detect('{out:Whisper}{s:"Cheesecake"}{s:"test"}'),'test')
        self.assertEqual(detect('{in:Whisper}{i:123}{s:"hi there"}'),'hi there')
        self.assertIsNone(detect('{in:Chat}{i:123}{s:"test"}'))
        self.assertIsNone(detect('{in:Shout}{i:123}{s:"test"}'))
        self.assertIsNone(detect('Whisper mentioned in a regular sentence'))

    def test_whisper_hint_matched_once(self):
        consume=namespace['match_recent_whisper']
        hints=[(100.0,'test')]
        self.assertTrue(consume(hints,'test',101.0))
        self.assertFalse(consume(hints,'test',101.1))
        self.assertEqual(hints,[])

    def test_stale_whisper_hint_not_used(self):
        hints=[(100.0,'test')]
        self.assertFalse(namespace['match_recent_whisper'](hints,'test',130.0))
        self.assertEqual(hints,[])

    def test_single_line_does_not_shrink_or_blit_native_text(self):
        source=CODE[CODE.index('            if single_line:'):CODE.index('            # Legacy wrapped-mode')]
        self.assertNotIn('for pt in range(',source)
        self.assertNotIn('cv.create_image(bx,top,image=native',source)
        self.assertIn('fnt,bold=self.canvas_font,self.canvas_bold',source)
        self.assertIn('fit_line_ellipsis',source)

    def test_toggle_labels_make_both_behaviours_obvious(self):
        label=next(node for node in TREE.body
                   if isinstance(node,ast.FunctionDef) and node.name=='chat_line_mode_label')
        ns={}
        exec(compile(ast.Module(body=[label],type_ignores=[]),str(APP),'exec'),ns)
        self.assertIn('ON',ns['chat_line_mode_label'](True))
        self.assertIn('one long line',ns['chat_line_mode_label'](True))
        self.assertIn('OFF',ns['chat_line_mode_label'](False))
        self.assertIn('multiple lines',ns['chat_line_mode_label'](False))

    def test_wrapped_mode_does_not_use_original_png_embedded_font_sizes(self):
        start=CODE.index('            # Legacy wrapped-mode:')
        end=CODE.index('        self.visible_count_current=rendered_count',start)
        segment=CODE[start:end]
        self.assertNotIn('create_image(bx,top,image=original',segment)
        self.assertIn("font=self.canvas_bold",segment)
        self.assertIn("font=self.canvas_font",segment)
        self.assertIn("wrap_message(' '.join(words)",segment)

    def test_line_toggle_does_not_mutate_font_size(self):
        start=CODE.index('    def _chat_line_toggle(self,parent):')
        end=CODE.index('    def _check(self,parent,label,key,invert=False):',start)
        segment=CODE[start:end]
        self.assertIn("key='single_line_bubbles'",segment)
        self.assertIn('self.save()',segment)
        self.assertNotIn("self.config['font_size']",segment)
        self.assertIn('self._chat_line_toggle(f)',CODE)

    def test_short_widths_are_safe(self):
        self.assertEqual(namespace['fit_line_ellipsis']('hello',FixedFont(),0),'')
        self.assertEqual(namespace['fit_line_ellipsis']('hello',FixedFont(),8),'…')


if __name__=='__main__':
    unittest.main()
