"""GUI-free verification of the wide chat layout and whisper classification."""
import ast
from pathlib import Path
import unittest

APP=Path(__file__).resolve().parent.parent/'Habbo_Companion.pyw'
CODE=APP.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
HELPERS=('is_whisper_chat','chat_one_line','fit_line_ellipsis','native_bubble_fits_single_line')
NODES=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in HELPERS]
assert len(NODES)==len(HELPERS), 'Missing chat layout helpers'
namespace={}
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

    def test_wrapped_native_images_get_compact_fallback(self):
        f=namespace['native_bubble_fits_single_line']
        self.assertTrue(f(200,30,500,36))
        self.assertFalse(f(200,75,500,36))
        self.assertFalse(f(700,30,500,36))
        self.assertFalse(f(0,30,500,36))

    def test_short_widths_are_safe(self):
        self.assertEqual(namespace['fit_line_ellipsis']('hello',FixedFont(),0),'')
        self.assertEqual(namespace['fit_line_ellipsis']('hello',FixedFont(),8),'…')


if __name__=='__main__':
    unittest.main()
