"""Isolated tests for the coffee pass packet sequence (no Windows or G-Earth needed)."""
import ast
from pathlib import Path
import re
import unittest

APP=Path(__file__).resolve().parent.parent/'Habbo_Companion.pyw'
TREE=ast.parse(APP.read_text(encoding='utf-8'))
FUNC=next(node for node in TREE.body
          if isinstance(node,ast.FunctionDef) and node.name=='build_coffee_pass_sequence')
NAMESPACE={'re':re}
exec(compile(ast.Module(body=[FUNC],type_ignores=[]),str(APP),'exec'),NAMESPACE)
build=NAMESPACE['build_coffee_pass_sequence']


class CoffeePassSequenceTests(unittest.TestCase):
    def test_two_cups_same_recipient(self):
        self.assertEqual(build('476989081','476989024','68808036'),(
            '{out:UseFurniture}{i:476989081}{i:0}',
            '{out:PassCarryItem}{i:68808036}',
            '{out:UseFurniture}{i:476989024}{i:0}',
            '{out:PassCarryItem}{i:68808036}',
        ))

    def test_target_can_change(self):
        result=build('476989081','476989024','68446836')
        self.assertEqual(result[1],'{out:PassCarryItem}{i:68446836}')
        self.assertEqual(result[3],result[1])

    def test_distinct_cups_required(self):
        with self.assertRaises(ValueError):
            build(4,4,100)

    def test_invalid_ids_rejected(self):
        for value in ('', '0', '-1', '5.0', 'abc', '2147483648'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    build(value,12,34)

    def test_first_second_target_all_validated(self):
        for values in [('5','bad','7'),('5','6','bad')]:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    build(*values)


if __name__=='__main__':
    unittest.main()
