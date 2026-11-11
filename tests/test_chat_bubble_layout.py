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

    def test_original_png_drawn_before_any_text_fallback(self):
        body=CODE[CODE.index('    def draw(self):'):CODE.index('    def _hotkeys(self):')]
        self.assertIn('native=self.native_images.get(key)',body)
        self.assertIn('native=tk.PhotoImage' if False else 'native=loaded',body)
        self.assertIn("cv.create_image(bx,top,image=native,anchor='nw')",body)
        self.assertLess(body.index("cv.create_image(bx,top,image=native"),
                        body.index("content=chat_one_line(msg.name+': '+msg.body)"))

    def test_no_imitation_speech_bubbles(self):
        draw=CODE[CODE.index('    def draw(self):'):CODE.index('    def _hotkeys(self):')]
        bubbles=draw[draw.index('        for msg in reversed(self.messages[start:end]):'):]
        self.assertNotIn('self._rounded(',bubbles)
        self.assertNotIn('cv.create_polygon(',bubbles)
        self.assertNotIn('cv.create_oval(',bubbles)
        self.assertNotIn('STYLE_VARIANTS',bubbles)
        self.assertIn('cv.create_text(tx,top+line_number*fline',bubbles)

    def test_toggle_labels_make_both_behaviours_obvious(self):
        label=next(node for node in TREE.body
                   if isinstance(node,ast.FunctionDef) and node.name=='chat_line_mode_label')
        ns={}
        exec(compile(ast.Module(body=[label],type_ignores=[]),str(APP),'exec'),ns)
        self.assertIn('ON',ns['chat_line_mode_label'](True))
        self.assertIn('one long line',ns['chat_line_mode_label'](True))
        self.assertIn('OFF',ns['chat_line_mode_label'](False))
        self.assertIn('multiple lines',ns['chat_line_mode_label'](False))

    def test_native_png_is_pixel_exact_even_when_one_line_is_off(self):
        body=CODE[CODE.index('    def draw(self):'):CODE.index('    def _hotkeys(self):')]
        self.assertIn('if native is not None:',body)
        self.assertIn('cv.create_image(bx,top,image=native',body)
        self.assertIn('continue\n\n            # No native image',body)
        self.assertIn('lines=wrap_message(content,available,self.canvas_font)',body)

    def test_original_artwork_is_not_a_disableable_setting(self):
        self.assertIn("self.config['original_bubble_images']=True",CODE)
        self.assertNotIn("self._check(f,'Use original Habbo bubble colours",CODE)
        self.assertIn("Original Habbo bubble artwork is always used",CODE)

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
